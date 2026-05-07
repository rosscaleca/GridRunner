# UI Refresh via SSE — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Push backend mutations to the frontend via Server-Sent Events so every page stays fresh without quit-and-relaunch, and add a floating manual Refresh button as a lifeline when the SSE connection is unhealthy.

**Architecture:** A new `backend/events.py` provides in-memory pub/sub primitives. A new `backend/api/events.py` exposes a `/api/events` SSE stream (using sse-starlette's `EventSourceResponse`, already a dependency). Mutation handlers across `executor.py`, `api/scripts.py`, `api/schedules.py`, `api/runs.py`, `api/settings.py`, and `api/cron.py` call `events.emit(<type>)` after their commits. The frontend `Alpine.store('app')` opens one EventSource on init, routes events to a per-component subscription bus with 200 ms debounce, and exposes `refreshCurrentPage()` for the floating Refresh button. Existing per-component polling (`dashboard._scheduleRefresh`, `scripts._startRunPoll`) is removed.

**Tech Stack:** Python 3.10+ / FastAPI / asyncio.Queue (backend pub/sub); sse-starlette `EventSourceResponse` (existing dep); Alpine.js 3 / vanilla EventSource API / vanilla CSS (frontend). Tests via pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-05-07-ui-refresh-sse-design.md`

---

## File Structure

| File | Role |
|---|---|
| `backend/events.py` (new) | Module-level in-memory pub/sub: `emit()`, `add_subscriber()`, `remove_subscriber()`. ~30 lines. |
| `backend/api/events.py` (new) | `GET /api/events` SSE endpoint using `EventSourceResponse`. ~40 lines. |
| `backend/main.py` | Mount the new events router. |
| `backend/executor.py` | Emit `runs.changed` after Run row creation in `execute_script` and after status transition in `_run_script_process`. |
| `backend/api/scripts.py` | Emit `scripts.changed` (CRUD), `categories.changed` (category CRUD). |
| `backend/api/schedules.py` | Emit `scripts.changed` on create/update/delete/toggle. |
| `backend/api/runs.py` | Emit `runs.changed` on `delete_run`, `cleanup_old_runs`, `cleanup_excess_runs`. |
| `backend/api/settings.py` | Emit `settings.changed` on the four settings updates; emit all three multi-domain events on `restore_config`. |
| `backend/api/cron.py` | Emit all three multi-domain events on `import_cron_jobs`. |
| `frontend/js/app.js` | Add event-bus methods on `Alpine.store('app')`; subscribe component `init()`s; wire debounce; remove `dashboard._scheduleRefresh` and `scripts._startRunPoll`. |
| `frontend/index.html` | Render floating Refresh button outside page templates. |
| `frontend/css/styles.css` | `.refresh-fab` styles + connected/disconnected/reconnecting/refreshing states. |
| `tests/test_events.py` (new) | Unit tests for `backend/events.py` pub/sub. |
| `tests/test_api_events.py` (new) | Smoke test for the SSE endpoint (status code + content-type). |

**Test design note:** Per the project's existing pattern, we don't have a FastAPI `TestClient` fixture. Task 1 unit-tests the pub/sub thoroughly. Task 2 verifies the endpoint mounts and returns the right content-type via a minimal `TestClient` invocation (added inline to that one test file). Per-handler emit assertions are NOT automated — the spec calls for manual verification in Task 7 by observing the live SSE stream as mutations occur. This trade-off matches the cancel-run feature's testing scope.

---

## Task 1: Backend events.py pub/sub primitives

**Files:**
- Create: `backend/events.py`
- Create: `tests/test_events.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_events.py`:

```python
"""Tests for backend.events in-memory pub/sub."""

import asyncio

import pytest

from backend import events


@pytest.fixture(autouse=True)
def clean_subscribers():
    """Reset the module-level subscriber list before/after each test."""
    events._subscribers.clear()
    yield
    events._subscribers.clear()


def test_emit_with_no_subscribers_does_not_raise():
    events.emit("runs.changed")  # should be a no-op


def test_emit_pushes_to_single_subscriber():
    q = asyncio.Queue()
    events.add_subscriber(q)
    events.emit("runs.changed")
    assert q.get_nowait() == "runs.changed"


def test_emit_pushes_to_multiple_subscribers():
    q1 = asyncio.Queue()
    q2 = asyncio.Queue()
    events.add_subscriber(q1)
    events.add_subscriber(q2)
    events.emit("scripts.changed")
    assert q1.get_nowait() == "scripts.changed"
    assert q2.get_nowait() == "scripts.changed"


def test_emit_drops_when_subscriber_queue_full_without_raising():
    q = asyncio.Queue(maxsize=1)
    events.add_subscriber(q)
    events.emit("runs.changed")
    events.emit("runs.changed")  # would block; emit() must drop instead
    # First event still present, second dropped
    assert q.get_nowait() == "runs.changed"
    assert q.empty()


def test_remove_subscriber_stops_delivery():
    q = asyncio.Queue()
    events.add_subscriber(q)
    events.remove_subscriber(q)
    events.emit("runs.changed")
    assert q.empty()


def test_remove_unknown_subscriber_is_noop():
    q = asyncio.Queue()
    events.remove_subscriber(q)  # never added; should not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/rosscaleca/Development/GridRunner && uv run pytest tests/test_events.py -v`

Expected: `ModuleNotFoundError: No module named 'backend.events'` — all six tests fail at collection.

- [ ] **Step 3: Implement `backend/events.py`**

Create `backend/events.py`:

```python
"""In-memory pub/sub for SSE event broadcasting.

Single-process desktop app, so subscribers are tracked in a module-level list.
Each subscriber owns an asyncio.Queue that the SSE endpoint pulls events from.
emit() is non-blocking: if a subscriber's queue is full, the event is dropped
for that subscriber rather than blocking the publisher.
"""

import asyncio


_subscribers: list[asyncio.Queue] = []


def emit(event_type: str) -> None:
    """Push an event type string to every subscriber queue.

    Non-blocking. Drops the event for any subscriber whose queue is full
    (e.g., a slow or stuck consumer) rather than blocking the publisher.
    """
    for q in _subscribers:
        try:
            q.put_nowait(event_type)
        except asyncio.QueueFull:
            pass


def add_subscriber(q: asyncio.Queue) -> None:
    """Register a queue to receive future emit() calls."""
    _subscribers.append(q)


def remove_subscriber(q: asyncio.Queue) -> None:
    """Stop delivering events to this queue. No-op if queue not registered."""
    try:
        _subscribers.remove(q)
    except ValueError:
        pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/rosscaleca/Development/GridRunner && uv run pytest tests/test_events.py -v`

Expected: 6 passed.

- [ ] **Step 5: Run the full suite to confirm no regressions**

Run: `cd /Users/rosscaleca/Development/GridRunner && uv run pytest -v`

Expected: all previously-passing tests still pass; 6 new tests pass.

- [ ] **Step 6: Commit**

```bash
cd /Users/rosscaleca/Development/GridRunner
git add backend/events.py tests/test_events.py
git commit -m "feat: in-memory pub/sub primitives for SSE event broadcasting

Single-process desktop app, so a module-level subscribers list is fine.
Non-blocking emit drops events for slow consumers rather than stalling
the publisher."
```

---

## Task 2: Backend SSE endpoint at `/api/events`

**Files:**
- Create: `backend/api/events.py`
- Modify: `backend/main.py`
- Create: `tests/test_api_events.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_api_events.py`:

```python
"""Smoke test for the /api/events SSE endpoint."""

from fastapi.testclient import TestClient

from backend.main import app


def test_events_endpoint_returns_event_stream():
    """The endpoint exists, returns 200, and advertises text/event-stream."""
    with TestClient(app) as client:
        # stream=True so we don't try to drain the (infinite) body
        with client.stream("GET", "/api/events") as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            # Read just the first chunk to verify the connected frame arrives
            first_chunk = next(response.iter_bytes(chunk_size=128))
            assert b"event: connected" in first_chunk
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/rosscaleca/Development/GridRunner && uv run pytest tests/test_api_events.py -v`

Expected: 404 (route not registered yet) or import error.

- [ ] **Step 3: Implement `backend/api/events.py`**

Create `backend/api/events.py`:

```python
"""SSE endpoint streaming domain-event notifications to the frontend."""

import asyncio
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

from .. import events
from .auth import require_auth


router = APIRouter()


@router.get("/")
async def stream_events(
    request: Request,
    _: None = Depends(require_auth),
):
    """Long-lived SSE stream of coarse domain-event notifications.

    Frame format: `event: <type>\\ndata: {}\\n\\n` where <type> is one of
    runs.changed, scripts.changed, categories.changed, settings.changed,
    plus an initial 'connected' frame and a 'ping' frame every 30s of
    silence to keep the connection alive.
    """
    async def event_generator() -> AsyncGenerator[dict, None]:
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        events.add_subscriber(queue)
        try:
            yield {"event": "connected", "data": "{}"}
            while True:
                if await request.is_disconnected():
                    return
                try:
                    event_type = await asyncio.wait_for(queue.get(), timeout=30)
                    yield {"event": event_type, "data": "{}"}
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}
        finally:
            events.remove_subscriber(queue)

    return EventSourceResponse(event_generator())
```

- [ ] **Step 4: Wire the router into `backend/main.py`**

Edit `backend/main.py`. Add the import alongside the others (around line 28):

```python
from .api.events import router as events_router
```

Add the `include_router` call alongside the others (around line 79, after the environments router):

```python
app.include_router(events_router, prefix="/api/events", tags=["events"])
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Users/rosscaleca/Development/GridRunner && uv run pytest tests/test_api_events.py -v`

Expected: 1 passed.

- [ ] **Step 6: Run the full suite**

Run: `cd /Users/rosscaleca/Development/GridRunner && uv run pytest -v`

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
cd /Users/rosscaleca/Development/GridRunner
git add backend/api/events.py backend/main.py tests/test_api_events.py
git commit -m "feat: SSE endpoint at /api/events for domain-event push

Each connection gets its own asyncio.Queue. Yields an initial
'connected' frame, then events as they arrive, with a 30s 'ping'
heartbeat to keep the connection alive."
```

---

## Task 3: Backend emit calls in mutation paths

**Files:**
- Modify: `backend/executor.py` (2 emit points)
- Modify: `backend/api/scripts.py` (6 emit points: 3 script CRUD + 3 category CRUD)
- Modify: `backend/api/schedules.py` (4 emit points: create/update/delete/toggle)
- Modify: `backend/api/runs.py` (3 emit points: delete + 2 cleanup)
- Modify: `backend/api/settings.py` (5 emit points: 4 settings updates + restore)
- Modify: `backend/api/cron.py` (1 emit point: import)

No test changes — per-handler emit assertions are deferred to manual verification in Task 7. The pattern is mechanical and any miss is observable in the SSE stream.

- [ ] **Step 1: Add emits to `backend/executor.py`**

Edit `backend/executor.py`. Add the import near the existing imports (around line 16):

```python
from . import events
```

In `execute_script` (around line 159), after `await session.commit()` and `await session.refresh(run)` and the `run_id = run.id` assignment, add ONE emit before the `asyncio.create_task` line:

```python
        run_id = run.id

    events.emit("runs.changed")
    asyncio.create_task(_run_script_process(script_id, run_id))
    return run_id
```

In `_run_script_process` (around line 196), after the final `await session.commit()` near the end (the one after `run.stdout = ...` and `run.stderr = ...`), add an emit:

```python
        await session.commit()

        events.emit("runs.changed")

        # Trigger notifications if needed
        from .notifications import send_run_notification
        await send_run_notification(run_id)
```

(The emit comes BEFORE the notification call so the UI updates immediately, regardless of how slow notification delivery is.)

- [ ] **Step 2: Add emits to `backend/api/scripts.py`**

Edit `backend/api/scripts.py`. Add the import near the existing imports (around line 13):

```python
from .. import events
```

In `create_script` (around line 165), after `await session.commit()` and `await session.refresh(script)`, add an emit before `return ScriptResponse(...)`:

```python
    await session.refresh(script)

    events.emit("scripts.changed")

    return ScriptResponse(
```

In `update_script` (around line 290), same pattern — after the `await session.refresh(script)` before the return:

```python
    await session.refresh(script)

    events.emit("scripts.changed")

    return ScriptResponse(
```

In `delete_script` (around line 335), after `await session.delete(script)` and `await session.commit()`, before the return:

```python
    await session.delete(script)
    await session.commit()

    events.emit("scripts.changed")

    return {"message": "Script deleted"}
```

In `create_category` (around line 467), after `await session.refresh(category)`, before the return:

```python
    await session.refresh(category)

    events.emit("categories.changed")

    return CategoryResponse(
```

In `update_category` (around line 500), after `await session.refresh(category)`:

```python
    await session.refresh(category)

    events.emit("categories.changed")

    return CategoryResponse(
```

In `delete_category` (around line 535), after `await session.delete(category)` and `await session.commit()`:

```python
    await session.delete(category)
    await session.commit()

    events.emit("categories.changed")

    return {"message": "Category deleted"}
```

- [ ] **Step 3: Add emits to `backend/api/schedules.py`**

Edit `backend/api/schedules.py`. Add the import near the existing imports (around line 12):

```python
from .. import events
```

All four schedule endpoints get the same one-liner: `events.emit("scripts.changed")` immediately after the final `await session.commit()` and before the return statement. (Schedules nest under scripts in the UI, so any schedule change should refresh the Scripts page.)

In `create_schedule` (~line 119), after `await session.refresh(schedule)`:

```python
    await session.refresh(schedule)

    events.emit("scripts.changed")

    return ScheduleResponse(...)
```

In `update_schedule` (~line 217), after the final `await session.refresh(schedule)`:

```python
    await session.refresh(schedule)

    events.emit("scripts.changed")

    return ScheduleResponse(...)
```

In `delete_schedule` (~line 268), after `await session.commit()`:

```python
    await session.delete(schedule)
    await session.commit()

    events.emit("scripts.changed")

    return {"message": "Schedule deleted"}
```

In `toggle_schedule_endpoint` (~line 293), after the toggle commits:

```python
    await session.commit()

    events.emit("scripts.changed")

    return {"message": "...", "enabled": ...}
```

(Adjust the exact return shape to match the existing code; the emit goes on its own line right before whatever the existing return statement looks like.)

- [ ] **Step 4: Add emits to `backend/api/runs.py`**

Edit `backend/api/runs.py`. Add the import near the existing imports:

```python
from .. import events
```

In `delete_run` (around line 157), after `await session.delete(run)` and `await session.commit()`, before the return:

```python
    await session.delete(run)
    await session.commit()

    events.emit("runs.changed")

    return {"message": "Run deleted"}
```

In `cleanup_old_runs` (around line 182), after the bulk delete commits, before the return:

```python
    await session.commit()

    events.emit("runs.changed")

    return {"message": f"Deleted {count} runs", "count": count}
```

In `cleanup_excess_runs` (around line 206), same pattern after its commit:

```python
    await session.commit()

    events.emit("runs.changed")

    return {"message": f"Deleted {total} runs", "count": total}
```

(Match the actual return shape of each endpoint; the emit is one line before whatever return is already there.)

- [ ] **Step 5: Add emits to `backend/api/settings.py`**

Edit `backend/api/settings.py`. Add the import near the existing imports:

```python
from .. import events
```

All four settings endpoints get the same one-liner: `events.emit("settings.changed")` after the writes commit, before the return.

In `update_smtp_settings` (~line 153):

```python
    await session.commit()

    events.emit("settings.changed")

    return {"message": "SMTP settings updated"}
```

In `update_digest_settings` (~line 175), `update_retention_settings` (~line 194), and `update_notification_settings` (~line 212), apply the identical pattern: after the final `await session.commit()`, add `events.emit("settings.changed")` on its own line, then leave the existing return statement.

(Skip `update_dark_mode` — it's a per-user UI preference. In a single-user local app there's no other session to notify, and emitting it could cause a self-loop refresh.)

In `restore_config` (around line 331), the import touches every domain. After the successful import commit, emit all three:

```python
        events.emit("scripts.changed")
        events.emit("categories.changed")
        events.emit("settings.changed")
```

- [ ] **Step 6: Add emits to `backend/api/cron.py`**

Edit `backend/api/cron.py`. Add the import:

```python
from .. import events
```

In `import_cron_jobs` (around line 107), after the bulk import commits, emit:

```python
    events.emit("scripts.changed")
    events.emit("categories.changed")  # cron import may create categories
    events.emit("settings.changed")  # in case any settings were touched
```

(The third emit is defensive; cron import currently doesn't touch settings, but the spec calls for it for consistency with `restore_config`.)

- [ ] **Step 7: Run the full suite to confirm no regressions**

Run: `cd /Users/rosscaleca/Development/GridRunner && uv run pytest -v`

Expected: all tests pass. The emit calls are no-ops when there are no subscribers, so existing tests are unaffected.

- [ ] **Step 8: Commit**

```bash
cd /Users/rosscaleca/Development/GridRunner
git add backend/executor.py backend/api/scripts.py backend/api/schedules.py backend/api/runs.py backend/api/settings.py backend/api/cron.py
git commit -m "feat: emit domain-change events from mutation handlers

executor + scripts/schedules/runs/settings/cron handlers now publish
runs.changed, scripts.changed, categories.changed, or settings.changed
after their commits, picked up by SSE subscribers."
```

---

## Task 4: Frontend event bus on `Alpine.store('app')`

**Files:**
- Modify: `frontend/js/app.js` (the `Alpine.store('app', {...})` block, lines ~5-75)

- [ ] **Step 1: Add a top-of-file `debounce` helper**

Edit `frontend/js/app.js`. At the very top of the file, BEFORE `document.addEventListener('alpine:init', ...)`, add:

```javascript
// Small debounce helper used to coalesce SSE event bursts into single refetches.
function debounce(fn, ms) {
    let timer;
    return (...args) => {
        clearTimeout(timer);
        timer = setTimeout(() => fn(...args), ms);
    };
}
```

- [ ] **Step 2: Add event-bus state and methods to `Alpine.store('app')`**

Inside the `Alpine.store('app', {...})` block, add the following properties to the state object (alongside `authenticated`, `darkMode`, etc.):

```javascript
        eventSource: null,
        eventSubscribers: {},        // { eventType: Set<callback> }
        pageRefreshers: {},          // { pageName: refreshFn }
        sseConnected: false,
        _reconnectTimer: null,
        _reconnectDelay: 1000,       // backoff state, reset on successful connect
```

Add these methods inside the same store object, after `showToast` and the new `cancelRun` (from the cancel-run feature) but before `logout`:

```javascript
        initEvents() {
            if (this.eventSource) return;
            const es = new EventSource('/api/events/');
            es.addEventListener('connected', () => {
                this.sseConnected = true;
                this._reconnectDelay = 1000;  // reset backoff on successful connect
            });
            ['runs.changed', 'scripts.changed', 'categories.changed', 'settings.changed'].forEach(type => {
                es.addEventListener(type, () => this._fireSubscribers(type));
            });
            es.onerror = () => {
                this.sseConnected = false;
                this._scheduleReconnect();
            };
            this.eventSource = es;
        },

        subscribeEvents(eventType, callback) {
            if (!this.eventSubscribers[eventType]) {
                this.eventSubscribers[eventType] = new Set();
            }
            this.eventSubscribers[eventType].add(callback);
            return () => this.eventSubscribers[eventType]?.delete(callback);
        },

        registerRefresher(pageName, refreshFn) {
            this.pageRefreshers[pageName] = refreshFn;
        },

        async refreshCurrentPage() {
            const fn = this.pageRefreshers[this.currentPage];
            if (fn) await fn();
        },

        _fireSubscribers(eventType) {
            const subs = this.eventSubscribers[eventType];
            if (subs) subs.forEach(cb => cb());
        },

        _scheduleReconnect() {
            if (this._reconnectTimer) return;
            if (this.eventSource) {
                this.eventSource.close();
                this.eventSource = null;
            }
            this._reconnectTimer = setTimeout(() => {
                this._reconnectTimer = null;
                this._reconnectDelay = Math.min(this._reconnectDelay * 2, 30000);
                this.initEvents();
            }, this._reconnectDelay);
        },
```

- [ ] **Step 3: Call `initEvents()` from the store's `init()` after auth**

In the existing `async init()` method of `Alpine.store('app')` (around line 14-32), add the `initEvents()` call inside the `if (this.authenticated)` branch, AFTER the dark-mode setup:

```javascript
        async init() {
            try {
                const status = await api.getAuthStatus();
                this.authenticated = status.authenticated;
                this.needsSetup = status.needs_setup;
                this.authEnabled = status.auth_enabled ?? true;

                if (this.authenticated) {
                    const settings = await api.getSettings();
                    this.darkMode = settings.dark_mode;
                    this.applyTheme();
                    this.initEvents();
                }
            } catch (error) {
                console.error('Init error:', error);
            }
            this.loading = false;
        },
```

Also call `initEvents()` from the `auth.login()` flow (around line 70-80) on successful login, since `init()` won't re-run after login:

```javascript
        async login() {
            this.error = '';
            this.loading = true;
            try {
                await api.login(this.password);
                Alpine.store('app').authenticated = true;
                Alpine.store('app').init();
                Alpine.store('app').initEvents();
            } catch (e) {
                this.error = 'Invalid password';
            }
            this.loading = false;
        },
```

(Note: `initEvents` is idempotent — the `if (this.eventSource) return;` guard at its top makes the duplicate call harmless if `init()` already opened it.)

- [ ] **Step 4: Sanity-check the file still parses**

Run: `cd /Users/rosscaleca/Development/GridRunner && node --check frontend/js/app.js`

Expected: no output.

- [ ] **Step 5: Commit**

```bash
cd /Users/rosscaleca/Development/GridRunner
git add frontend/js/app.js
git commit -m "feat: SSE event bus on Alpine.store('app')

Opens one EventSource on auth-confirmed init, routes events to
per-component subscriber callbacks, exposes refreshCurrentPage()
for the upcoming floating Refresh button, reconnects with
exponential backoff (1s -> 30s) on error."
```

---

## Task 5: Frontend component subscriptions + remove old polling

**Files:**
- Modify: `frontend/js/app.js`:
  - `dashboard` component: subscribe + register; remove `_scheduleRefresh` and `_refreshTimer`
  - `scripts` component: subscribe + register; remove `_startRunPoll` and `_runPollTimer` references
  - `history` component: subscribe + register
  - `settings` component: subscribe + register

- [ ] **Step 1: Update the `dashboard` component**

In `Alpine.data('dashboard', () => ({...}))` (around line 107):

Replace the existing `init` and `_scheduleRefresh` methods:

```javascript
        async init() {
            await this.refresh();
            // Auto-refresh: 2s when scripts are running, 10s otherwise
            this._scheduleRefresh();
        },

        _scheduleRefresh() {
            const interval = (this.running && this.running.length > 0) ? 2000 : 10000;
            this._refreshTimer = setTimeout(async () => {
                await this.refresh();
                this._scheduleRefresh();
            }, interval);
        },
```

with:

```javascript
        async init() {
            await this.refresh();
            const debounced = debounce(() => this.refresh(), 200);
            const store = Alpine.store('app');
            store.registerRefresher('dashboard', () => this.refresh());
            store.subscribeEvents('runs.changed', debounced);
            store.subscribeEvents('scripts.changed', debounced);
        },
```

(The `_refreshTimer` property on the state object can also be removed since nothing references it anymore. Clean-up only — not strictly required.)

- [ ] **Step 2: Update the `scripts` component**

In `Alpine.data('scripts', () => ({...}))` (around line 174):

In the existing `async init()` method (around line 243):

```javascript
        async init() {
            await this.refresh();
            this.loadRuntimes();
        },
```

Update to:

```javascript
        async init() {
            await this.refresh();
            this.loadRuntimes();
            const debounced = debounce(() => this.refresh(), 200);
            const store = Alpine.store('app');
            store.registerRefresher('scripts', () => this.refresh());
            store.subscribeEvents('runs.changed', debounced);
            store.subscribeEvents('scripts.changed', debounced);
            store.subscribeEvents('categories.changed', debounced);
        },
```

In `runScript` (around line 389), remove the `_startRunPoll()` call since SSE now drives `is_running` flips:

```javascript
        async runScript(script) {
            try {
                const result = await api.runScript(script.id);
                Alpine.store('app').showToast(`Started: ${script.name}`, 'success');
                await this.refresh();
                // Poll until no scripts are running
                this._startRunPoll();
            } catch (e) {
                Alpine.store('app').showToast(e.message, 'error');
            }
        },
```

becomes:

```javascript
        async runScript(script) {
            try {
                const result = await api.runScript(script.id);
                Alpine.store('app').showToast(`Started: ${script.name}`, 'success');
                await this.refresh();
            } catch (e) {
                Alpine.store('app').showToast(e.message, 'error');
            }
        },
```

Delete the `_startRunPoll()` method entirely (around line 401-411). Search for `_runPollTimer` and remove any other references.

- [ ] **Step 3: Update the `history` component**

In `Alpine.data('history', () => ({...}))` (around line 646):

The existing `async init()` method:

```javascript
        async init() {
            await this.refresh();
        },
```

Update to:

```javascript
        async init() {
            await this.refresh();
            const debounced = debounce(() => this.refresh(), 200);
            const store = Alpine.store('app');
            store.registerRefresher('history', () => this.refresh());
            store.subscribeEvents('runs.changed', debounced);
            store.subscribeEvents('scripts.changed', debounced);
        },
```

- [ ] **Step 4: Update the `settings` component**

In `Alpine.data('settings', () => ({...}))` (around line 728):

The existing `async init()` method:

```javascript
        async init() {
            await this.refresh();
        },
```

Update to:

```javascript
        async init() {
            await this.refresh();
            const debounced = debounce(() => this.refresh(), 200);
            const store = Alpine.store('app');
            store.registerRefresher('settings', () => this.refresh());
            store.subscribeEvents('settings.changed', debounced);
            store.subscribeEvents('categories.changed', debounced);
            store.subscribeEvents('scripts.changed', debounced);
        },
```

- [ ] **Step 5: Sanity-check the file still parses**

Run: `cd /Users/rosscaleca/Development/GridRunner && node --check frontend/js/app.js`

Expected: no output.

- [ ] **Step 6: Commit**

```bash
cd /Users/rosscaleca/Development/GridRunner
git add frontend/js/app.js
git commit -m "feat: subscribe components to SSE; remove per-page polling

dashboard, scripts, history, and settings components now register
themselves with the page-refresher registry and subscribe to relevant
SSE events with a 200ms debounce. Dashboard's _scheduleRefresh
chain and scripts' _startRunPoll interval are removed; SSE drives
freshness instead."
```

---

## Task 6: Floating Refresh button (HTML + CSS)

**Files:**
- Modify: `frontend/index.html` (add button outside page templates)
- Modify: `frontend/css/styles.css` (add `.refresh-fab` styles + states)

- [ ] **Step 1: Add the button to `frontend/index.html`**

Edit `frontend/index.html`. The toast container is currently the last element before `</body>` (around line 1041):

```html
    <div class="toast-container">
        <template x-for="toast in $store.app.toasts" :key="toast.id">
            <div class="toast" :class="toast.type" x-text="toast.message"></div>
        </template>
    </div>
</body>
</html>
```

Add the floating Refresh button RIGHT AFTER the toast container, before `</body>`:

```html
    <div class="toast-container">
        <template x-for="toast in $store.app.toasts" :key="toast.id">
            <div class="toast" :class="toast.type" x-text="toast.message"></div>
        </template>
    </div>
    <button x-show="$store.app.authenticated"
            class="refresh-fab"
            :class="{
                'fab-connected': $store.app.sseConnected,
                'fab-disconnected': !$store.app.sseConnected,
                'fab-refreshing': fabRefreshing
            }"
            x-data="{ fabRefreshing: false }"
            @click="fabRefreshing = true; await $store.app.refreshCurrentPage(); fabRefreshing = false"
            :title="$store.app.sseConnected ? 'Refresh current page (live updates: connected)' : 'Refresh current page (live updates: disconnected)'">
        <span class="refresh-icon">↻</span>
    </button>
</body>
</html>
```

- [ ] **Step 2: Add the CSS styles to `frontend/css/styles.css`**

Edit `frontend/css/styles.css`. Append at the end of the file:

```css
/* Floating Refresh button (bottom-right) */
.refresh-fab {
    position: fixed;
    bottom: 24px;
    right: 24px;
    width: 48px;
    height: 48px;
    border-radius: 50%;
    border: 2px solid var(--border-color);
    background: var(--bg-secondary);
    color: var(--text-primary);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.5rem;
    line-height: 1;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
    transition: transform 0.15s ease, border-color 0.3s ease, box-shadow 0.15s ease;
    z-index: 1000;
}

.refresh-fab:hover {
    transform: scale(1.05);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
}

.refresh-fab:active {
    transform: scale(0.95);
}

.refresh-fab.fab-connected {
    border-color: var(--success);
}

.refresh-fab.fab-disconnected {
    border-color: var(--text-muted);
}

.refresh-fab.fab-refreshing .refresh-icon {
    animation: refresh-spin 0.8s linear infinite;
}

@keyframes refresh-spin {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
}
```

- [ ] **Step 3: Sanity-check the HTML parses**

Run: `cd /Users/rosscaleca/Development/GridRunner && python3 -c "from html.parser import HTMLParser; HTMLParser().feed(open('frontend/index.html').read())"`

Expected: no output (HTMLParser is lenient; this just catches gross errors).

- [ ] **Step 4: Commit**

```bash
cd /Users/rosscaleca/Development/GridRunner
git add frontend/index.html frontend/css/styles.css
git commit -m "feat: floating Refresh button with SSE connection indicator

Bottom-right circular button. Border color reflects SSE state
(green when connected, gray when disconnected). Click triggers
refresh on whatever page is currently visible. Hidden when
unauthenticated."
```

---

## Task 7: End-to-end manual verification

**Files:** none modified; this task is verification only.

The e2e tests below cannot be automated — they require running the desktop app and observing UI updates. Run from a fresh session.

- [ ] **Step 1: Start the app**

Run: `cd /Users/rosscaleca/Development/GridRunner && uv run run.py`

The desktop window should open. Open the browser dev tools if accessible (or the live log at `~/.gridrunner/logs/gridrunner.log`).

- [ ] **Step 2: Verify the Refresh button shows connected state**

Look bottom-right. Should see a circular button with a refresh-arrow icon and a GREEN border (SSE connected).

If the border is gray or yellow, check the log for SSE errors. The endpoint is `GET /api/events/`.

- [ ] **Step 3: Verify cross-page navigation no longer requires manual refresh**

Open a second terminal. Use curl to mutate state while watching the UI:

```bash
PORT=$(lsof -i -P -n | grep -i Python | grep LISTEN | head -1 | awk '{print $9}' | cut -d: -f2)
echo "GridRunner port: $PORT"

# Create a script
curl -s -X POST http://127.0.0.1:$PORT/api/scripts \
  -H "Content-Type: application/json" \
  -d '{"name":"SSE test","script_type":"python","path":"/tmp/gridrunner-cancel-test.py","timeout":120,"retry_count":0,"retry_delay":60,"notification_setting":"never"}'
```

In the app: navigate to **Scripts**. Confirm the new "SSE test" entry appears within ~1s WITHOUT clicking Refresh.

- [ ] **Step 4: Verify History page auto-refreshes**

In the app: navigate to **History**. Note the current run count.

In the second terminal, trigger a script run:

```bash
SCRIPT_ID=$(curl -s http://127.0.0.1:$PORT/api/scripts | python3 -c "import sys,json; print(next(s['id'] for s in json.load(sys.stdin) if s['name']=='SSE test'))")
curl -s -X POST http://127.0.0.1:$PORT/api/scripts/$SCRIPT_ID/run
```

In the app History page, the new run should appear within ~1s without filter toggle or manual refresh. Wait 60s for it to finish; the status should transition from "running" to "success" within ~1s of completion.

- [ ] **Step 5: Verify Dashboard "Currently Running" updates without polling**

Trigger another run via curl. Navigate to **Dashboard**. The run should appear in "Currently Running" within ~1s. After 60s, it should disappear within ~1s of completion.

- [ ] **Step 6: Verify the manual Refresh button works on each page**

On each page (Dashboard, Scripts, History, Settings), click the floating Refresh button. The icon should spin briefly. Verify on Settings: change a category color via the second terminal, then on the Settings page click Refresh — the new color appears immediately.

- [ ] **Step 7: Verify SSE reconnect**

In a third terminal, kill and restart the GridRunner backend (in practice this means closing and relaunching the app; for a more controlled test, do it via the dev-mode `uvicorn ... --reload` workflow).

While the backend is down: the floating Refresh button border should turn gray within ~1-30s (depending on backoff state).

When the backend comes back: the border should turn green again within ~30s.

- [ ] **Step 8: Verify dark-mode styling**

Toggle dark mode (top-right of the app). The floating Refresh button should remain visible and styled appropriately against the dark background.

- [ ] **Step 9: Run the full pytest suite**

Run: `cd /Users/rosscaleca/Development/GridRunner && uv run pytest -v`

Expected: all tests pass (existing + new from Tasks 1 and 2).

- [ ] **Step 10: No commit needed for verification-only steps**

If any tweaks were made during verification, commit them as a follow-up `chore:` or `fix:` commit. Otherwise this task is complete.
