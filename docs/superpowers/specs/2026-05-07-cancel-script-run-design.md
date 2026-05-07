# Cancel a Running Script — Design

**Date:** 2026-05-07
**Status:** Approved (brainstorm), pending implementation plan

## Problem

There is no UI affordance to cancel a script that is currently running. Users have to wait for the timeout, kill the process out-of-band, or quit the app.

## Approach

Frontend-only feature. The backend already supports termination:

- `executor.kill_script(run_id)` — sends SIGTERM, waits 0.5s, then SIGKILL if still alive (`backend/executor.py:344`).
- `POST /api/scripts/{script_id}/kill?run_id={run_id}` — REST endpoint (`backend/api/scripts.py:361`).
- `api.killScript(scriptId, runId)` — frontend wrapper (`frontend/js/api.js:113`).

What's missing is the UI. Add Cancel buttons on the three places running state is already shown.

## UI surfaces

### 1. Dashboard "Currently Running" card

`frontend/index.html:166-180`. Each row currently shows script name, elapsed duration, and a passive "Running" badge. Add a `btn-sm btn-danger` "Cancel" button to the right of the badge. The dashboard's `running` array already carries `script_id` and `run_id` per row.

### 2. Scripts page row

`frontend/index.html:369`. When `script.is_running`, swap the disabled "Run" button for an enabled `btn-sm btn-danger` "Cancel" button.

The `ScriptResponse` model exposes `is_running: bool` but not the running run's id. Add a `running_run_id: Optional[int]` field to `ScriptResponse` and populate it in the same `list_scripts` loop that derives `is_running` (`backend/api/scripts.py:107-162`). Tiny additive change.

### 3. Run detail modal (History page)

When `selectedRun.status === 'running'`, add a "Cancel Run" button in the modal header. Same flow.

## Interaction

```
user clicks Cancel
  → window.confirm('Cancel "<script_name>"? The script will be terminated.')
  → if confirmed: button disabled (prevents double-click)
    → api.killScript(scriptId, runId)
       ├ 200 → success toast 'Cancelled <script_name>' → refresh current view
       ├ 404 → info toast 'Run already finished' (silent success — race case)
       └ 5xx → error toast with message → re-enable button
```

After a successful kill, immediately `await this.refresh()` on the current view so the row state updates without waiting for the next poll tick.

## Backend change (minimal)

Add `running_run_id: Optional[int] = None` to `ScriptResponse` in `backend/api/scripts.py:45`. In `list_scripts`, set it from the same `script.runs` lookup that derives `is_running`:

```python
running_run = next(
    (r for r in script.runs if r.status == "running" and r.id in running_processes),
    None,
)
is_running = running_run is not None
running_run_id = running_run.id if running_run else None
```

`get_script` (single-script GET) gets the same treatment for consistency, though no current consumer needs it.

## Edge cases

- **Race (process finished before kill arrives):** backend returns 404. Treat as success with a neutral info toast.
- **Double-click:** button disabled while the request is in flight.
- **Auth disabled (default):** no change — `require_auth` is a no-op.

## Out of scope

- "Kill all running" bulk action — not needed; this is a single-user local app.
- Cancel for queued/scheduled-but-not-yet-running runs — APScheduler manages these and they aren't surfaced as cancellable entities.
- Re-run-after-cancel one-click — the existing Run button covers it once `is_running` flips false.
- Soft-cancel (let the script clean up) vs. hard-kill — backend already does graceful SIGTERM with 0.5s grace before SIGKILL. Good enough.

## Testing

- `tests/test_executor.py` already covers `kill_script` for the SIGTERM path. No new backend tests required.
- `ScriptResponse.running_run_id` derivation should get a unit test asserting it's set when a run is in `running_processes` and `None` otherwise.
- Manual UI verification on macOS desktop build: cancel from each of the 3 surfaces, confirm prompt appearance, race-case toast, re-enabled button on error.

## File touch list

| File | Change |
|---|---|
| `backend/api/scripts.py` | Add `running_run_id` to `ScriptResponse`; populate in `list_scripts` and `get_script`. |
| `frontend/index.html` | Add Cancel button in 3 places (dashboard running card, scripts row, run detail modal). |
| `frontend/js/app.js` | Add `cancelRun(scriptId, runId, scriptName)` method on `dashboard`, `scripts`, and `history` components (or a shared helper). |
| `tests/test_executor.py` or new test file | Optional: assert `running_run_id` derivation. |
