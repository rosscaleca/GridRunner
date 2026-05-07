# UI Refresh via SSE + Manual Refresh Button — Design

**Date:** 2026-05-07
**Status:** Approved (brainstorm), pending implementation plan

## Problem

UI components in GridRunner go stale after their initial load:

- **History** never auto-refreshes after init; finished runs don't appear without a manual filter toggle or app relaunch.
- **Scripts** misses background activity (schedule firings, externally created scripts) once the in-flight-run poller stops.
- **Settings** only loads on init; categories/SMTP/etc. don't reflect external changes.
- **Cross-page navigation** preserves stale state because Alpine `x-show` keeps components alive between page switches.

The user has been quitting and relaunching the app to see updated state.

## Approach

Replace per-component polling with a single Server-Sent Events stream from backend to frontend, plus a manual Refresh button as a lifeline when the SSE connection is unhealthy.

**Why SSE over polling-everywhere:** real-time push, single connection, minimal traffic, predictable. Why over WebSockets: this is a one-way push (server → client); SSE is the simpler primitive that fits.

**Why coarse events:** event taxonomy stays at the domain level (`runs.changed`, `scripts.changed`, `categories.changed`, `settings.changed`). Components refetch their full list when their event fires. No per-entity event payloads, no in-place state patching. Network cost on a localhost desktop app is negligible; simplicity wins.

## Backend

### `backend/events.py` (new)

In-memory pub/sub for SSE subscribers. Single-process, no Redis required.

```python
_subscribers: list[asyncio.Queue] = []

def emit(event_type: str) -> None:
    """Non-blocking. Push event to every subscriber queue. Drop if queue full."""
    for q in _subscribers:
        try:
            q.put_nowait(event_type)
        except asyncio.QueueFull:
            pass  # subscriber too slow; drop rather than block

def add_subscriber(q: asyncio.Queue) -> None: ...
def remove_subscriber(q: asyncio.Queue) -> None: ...
```

### `backend/api/events.py` (new)

```python
@router.get("/events")
async def stream_events(request: Request, _: None = Depends(require_auth)):
    async def gen():
        queue = asyncio.Queue(maxsize=100)
        events.add_subscriber(queue)
        try:
            yield f"event: connected\ndata: {{}}\n\n"
            while True:
                if await request.is_disconnected():
                    return
                try:
                    event_type = await asyncio.wait_for(queue.get(), timeout=30)
                    yield f"event: {event_type}\ndata: {{}}\n\n"
                except asyncio.TimeoutError:
                    yield f"event: ping\ndata: {{}}\n\n"
        finally:
            events.remove_subscriber(queue)
    return StreamingResponse(gen(), media_type="text/event-stream")
```

Wired into `backend/main.py`'s router list.

### Emit call sites

After every successful DB commit in mutation paths:

| Event | Files / functions |
|---|---|
| `runs.changed` | `executor.execute_script` (after Run row created), `executor._run_script_process` (after status transition to success/failed/timeout/killed), `api/runs.py:delete_run` |
| `scripts.changed` | `api/scripts.py`: `create_script`, `update_script`, `delete_script`. `api/schedules.py`: all CRUD (schedules nest under scripts) |
| `categories.changed` | `api/scripts.py` category CRUD endpoints |
| `settings.changed` | `api/settings.py` SMTP/digest/retention/notification updates |

**Backup-restore** (`api/settings.py:restore_config` and `api/cron.py:import_cron_jobs`) can change everything; both emit `scripts.changed`, `categories.changed`, AND `settings.changed` after a successful import.

`kill_script` itself doesn't need to emit — the subprocess termination triggers `_run_script_process`'s status-update path which emits.

Each emit is a one-liner: `events.emit("runs.changed")`. ~12 call sites total.

## Frontend

### Event bus on `Alpine.store('app')`

New properties and methods:

```js
eventSource: null,
eventSubscribers: {},      // { eventType: Set<callback> }
pageRefreshers: {},        // { pageName: refreshFn }
sseConnected: false,
_reconnectTimer: null,
_reconnectDelay: 1000,     // backoff state, reset on successful connect

initEvents() { /* open EventSource, wire listeners */ },
subscribeEvents(eventType, callback) { /* returns unsubscribe fn */ },
registerRefresher(pageName, refreshFn) { /* called by each component on init */ },
async refreshCurrentPage() { /* called by floating refresh button */ },
_fireSubscribers(eventType) { /* internal */ },
_scheduleReconnect() { /* exponential backoff: 1s → 2s → 4s → 8s → 16s → 30s cap */ },
```

`initEvents()` is called from the store's existing `init()` after auth is confirmed.

### Component subscriptions

Each component's `init()` gains two lines (a registration and one or more event subscriptions):

```js
async init() {
    await this.refresh();
    Alpine.store('app').registerRefresher('dashboard', () => this.refresh());
    Alpine.store('app').subscribeEvents('runs.changed', () => this.refresh());
    Alpine.store('app').subscribeEvents('scripts.changed', () => this.refresh());
}
```

| Component | Subscribes to |
|---|---|
| `dashboard` | `runs.changed`, `scripts.changed` |
| `scripts` | `runs.changed`, `scripts.changed`, `categories.changed` |
| `history` | `runs.changed`, `scripts.changed` (script delete cascades to runs) |
| `settings` | `settings.changed`, `categories.changed`, `scripts.changed` (backup/restore can change everything) |

### Polling timers removed

- `dashboard._scheduleRefresh()` and the `_refreshTimer` setTimeout chain — deleted; SSE drives freshness.
- `scripts._startRunPoll()` and the `_runPollTimer` setInterval — deleted; SSE drives `is_running` flips on the row.

Net code reduction in those components.

### Debouncing

Each component's refresh is wrapped with a 200ms debounce so a burst of events (e.g., 10 schedules firing simultaneously) coalesces into a single refetch:

```js
async init() {
    this._debouncedRefresh = debounce(() => this.refresh(), 200);
    // ...subscribe with this._debouncedRefresh
}
```

Small utility (`debounce(fn, ms)`) added to a frontend `js/util.js` (new file) or inlined in `app.js` if a single helper.

### Floating Refresh button

Rendered once at the bottom of `index.html`, outside the page templates:

```html
<button class="refresh-fab"
        :class="{ 'connected': $store.app.sseConnected, 'disconnected': !$store.app.sseConnected }"
        @click="$store.app.refreshCurrentPage()"
        title="Refresh current page">
    <span class="refresh-icon">↻</span>
</button>
```

CSS: fixed bottom-right (`position: fixed; bottom: 24px; right: 24px;`), circular, ~48px. Connected = green ring. Disconnected = gray ring. While reconnecting = yellow with subtle pulse. While refresh is in flight (after click) = inner spinner.

Handler `refreshCurrentPage()` looks up the registered refresher for `currentPage` and awaits it.

## Auth

When `AUTH_ENABLED=true`, the SSE endpoint sits behind the existing `require_auth` dependency. If the session expires mid-stream, server closes the connection; frontend sees `onerror`; reconnect attempts fail with 401; the existing `auth:required` event from any non-SSE call (e.g., the manual refresh) takes the user back to login.

## Out of scope

- **Per-entity events** (`run.started{run_id}`, etc.) — coarse refetch is simpler and fast enough on localhost.
- **Page Visibility API gating** — pywebview windows don't background tabs the way browsers do.
- **Server-side event replay/buffering** — best-effort delivery is fine; manual refresh covers the gap.
- **WebSocket bidirectional channel** — we only push server→client; SSE is the right primitive.
- **Cross-page navigation refresh** — with SSE keeping every component fresh in the background, navigation should "just work." If staleness still surfaces, a one-line `refresh()` in the navigate handler can be added later.

## Testing

- `tests/test_events.py` (new) — unit tests for `backend/events.py`: `emit` pushes to every subscriber queue; `add_subscriber`/`remove_subscriber` lifecycle; full-queue drops without raising.
- `tests/test_api_events.py` (new) — FastAPI TestClient connects to `/api/events`, asserts the initial `connected` frame, calls `emit()`, asserts the resulting frame appears in stream output.
- Existing mutation tests (`test_executor.py`, `test_api_scripts.py`) extended to assert `events.emit` was called with the right event type. Use a fixture that captures emit calls into a list.
- Frontend: no JS test harness; rely on `node --check` and manual e2e (open app, mutate via API in a second terminal, observe frontend update without manual refresh).

## File touch list

| File | Change |
|---|---|
| `backend/events.py` | NEW: pub/sub primitives. |
| `backend/api/events.py` | NEW: SSE endpoint. |
| `backend/main.py` | Mount the new events router. |
| `backend/executor.py` | Emit `runs.changed` on start + status-transition. |
| `backend/api/scripts.py` | Emit `scripts.changed` (CRUD) + `categories.changed` (category CRUD). |
| `backend/api/schedules.py` | Emit `scripts.changed` on schedule CRUD. |
| `backend/api/runs.py` | Emit `runs.changed` on delete. |
| `backend/api/settings.py` | Emit `settings.changed` on settings update + backup-restore. |
| `frontend/js/app.js` | Event bus on store; component subscriptions; remove old polling timers. |
| `frontend/index.html` | Floating Refresh button rendered once outside the page templates. |
| `frontend/css/styles.css` | `.refresh-fab` styles + connected/disconnected/reconnecting states. |
| `tests/test_events.py` | NEW: unit tests for the pub/sub. |
| `tests/test_api_events.py` | NEW: SSE endpoint integration test. |
| Existing test files | Extended assertions on emit calls. |
