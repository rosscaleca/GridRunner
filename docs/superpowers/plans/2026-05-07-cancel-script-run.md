# Cancel a Running Script — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add UI affordances (Cancel buttons on Dashboard, Scripts row, and Run-detail modal) that let the user terminate a currently-running script via the existing backend `/api/scripts/{id}/kill` endpoint.

**Architecture:** Frontend-only feature with one additive backend field. A small pure helper derives both `is_running` and a new `running_run_id` on `ScriptResponse` so the Scripts page can call `kill?run_id=...`. A shared `cancelRun()` method on the global Alpine store handles confirm + API call + toast for all three UI surfaces; each component awaits it and refreshes its own data. The frontend `api.js` `request()` wrapper is extended to attach `response.status` to thrown errors so the 404 race-case can be distinguished from real failures.

**Tech Stack:** Python 3.10+ / FastAPI / SQLAlchemy async / Pydantic v2 (backend), Alpine.js 3 / vanilla CSS / fetch (frontend). Tests via pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-05-07-cancel-script-run-design.md`

---

## File Structure

| File | Role |
|---|---|
| `backend/api/scripts.py` | Add `running_run_id` field to `ScriptResponse`; introduce pure helper `find_running_run(runs, running_processes)`; use it in `list_scripts` and `get_script`. |
| `tests/test_api_scripts.py` (new) | Unit tests for `find_running_run`. |
| `frontend/js/api.js` | Extend `request()` to attach `error.status = response.status` on non-OK responses. |
| `frontend/js/app.js` | Add `cancelRun()` method on `Alpine.store('app')`; add per-component cancel handlers on `dashboard`, `scripts`, and `history`. |
| `frontend/index.html` | Add Cancel buttons in 3 surfaces: dashboard "Currently Running" rows, scripts table row (conditional on `is_running`), Run-detail modal footer. |

---

## Task 1: Backend — `find_running_run` helper + `running_run_id` on `ScriptResponse`

**Files:**
- Create: `tests/test_api_scripts.py`
- Modify: `backend/api/scripts.py` (add helper near top of file; modify `ScriptResponse`, `list_scripts`, `get_script`)

- [ ] **Step 1: Write the failing test**

Create `tests/test_api_scripts.py`:

```python
"""Tests for backend.api.scripts pure helpers."""

from backend.api.scripts import find_running_run
from backend.models import Run


def _run(run_id: int, status: str) -> Run:
    """Construct a Run instance for testing (not persisted)."""
    return Run(id=run_id, script_id=1, status=status)


def test_find_running_run_returns_run_when_status_running_and_tracked():
    runs = [_run(10, "success"), _run(11, "running")]
    running_processes = {11: object()}
    result = find_running_run(runs, running_processes)
    assert result is not None
    assert result.id == 11


def test_find_running_run_returns_none_when_status_running_but_not_tracked():
    runs = [_run(11, "running")]
    running_processes = {}
    assert find_running_run(runs, running_processes) is None


def test_find_running_run_returns_none_when_no_running_runs():
    runs = [_run(10, "success"), _run(11, "failed")]
    running_processes = {99: object()}
    assert find_running_run(runs, running_processes) is None


def test_find_running_run_returns_none_for_empty_runs():
    assert find_running_run([], {}) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/rosscaleca/Development/GridRunner && uv run pytest tests/test_api_scripts.py -v`

Expected: `ImportError: cannot import name 'find_running_run' from 'backend.api.scripts'` — all four tests fail at collection.

- [ ] **Step 3: Add the helper and `running_run_id` field**

Edit `backend/api/scripts.py`. Near the top (after the imports, before any router definitions), add:

```python
def find_running_run(runs, running_processes):
    """Return the Run currently tracked as a live process, or None.

    A run counts as 'running' only if both its status field is 'running' AND its id
    is present in the in-memory running_processes dict (which the executor populates
    while a subprocess is alive). This avoids treating crashed-server orphans as live.
    """
    for run in runs:
        if run.status == "running" and run.id in running_processes:
            return run
    return None
```

In the `ScriptResponse` class (currently ending around line 70), add the new field alongside `is_running`:

```python
class ScriptResponse(BaseModel):
    # ...existing fields up through is_running...
    is_running: bool = False
    running_run_id: Optional[int] = None
    last_run_status: Optional[str] = None
    last_run_at: Optional[datetime] = None

    class Config:
        from_attributes = True
```

In `list_scripts` (currently ~line 130), replace the existing `is_running = any(...)` derivation and the subsequent `ScriptResponse(...)` construction with:

```python
        # Derive running state via the helper
        running_run = find_running_run(script.runs, running_processes)
        is_running = running_run is not None
        running_run_id = running_run.id if running_run else None

        responses.append(ScriptResponse(
            id=script.id,
            name=script.name,
            description=script.description,
            script_type=script.script_type,
            path=script.path,
            interpreter_path=script.interpreter_path,
            working_directory=script.working_directory,
            env_vars=script.env_vars,
            args=script.args,
            timeout=script.timeout,
            retry_count=script.retry_count,
            retry_delay=script.retry_delay,
            category_id=script.category_id,
            category_name=script.category.name if script.category else None,
            notification_setting=script.notification_setting,
            webhook_url=script.webhook_url,
            venv_path=script.venv_path,
            interpreter_version=script.interpreter_version,
            created_at=script.created_at,
            updated_at=script.updated_at,
            health_score=script.health_score,
            is_running=is_running,
            running_run_id=running_run_id,
            last_run_status=last_run.status if last_run else None,
            last_run_at=last_run.started_at if last_run else None,
        ))
```

In `get_script` (currently ~line 212), make the analogous addition immediately before the existing `return ScriptResponse(...)`:

```python
    running_run = find_running_run(script.runs, running_processes)
    is_running = running_run is not None
    running_run_id = running_run.id if running_run else None

    return ScriptResponse(
        # ...existing fields...
        is_running=is_running,
        running_run_id=running_run_id,
        last_run_status=last_run.status if last_run else None,
        last_run_at=last_run.started_at if last_run else None,
    )
```

(`get_script` currently doesn't pass `is_running` at all; add it here too for consistency with `list_scripts`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/rosscaleca/Development/GridRunner && uv run pytest tests/test_api_scripts.py -v`

Expected: 4 passed.

- [ ] **Step 5: Run the full test suite to confirm no regressions**

Run: `cd /Users/rosscaleca/Development/GridRunner && uv run pytest -v`

Expected: All previously-passing tests still pass; 4 new tests pass.

- [ ] **Step 6: Commit**

```bash
cd /Users/rosscaleca/Development/GridRunner
git add backend/api/scripts.py tests/test_api_scripts.py
git commit -m "feat: expose running_run_id on ScriptResponse

Add find_running_run() helper and use it in list_scripts and
get_script to populate is_running plus a new running_run_id field.
The Scripts page Cancel button needs the run_id to call /kill."
```

---

## Task 2: Frontend — attach `status` to errors thrown by `api.js`

**Files:**
- Modify: `frontend/js/api.js:33-36`

This change is small enough to skip TDD (no JS test harness exists in the repo). Verify by inspection.

- [ ] **Step 1: Modify `request()` to attach status before throwing**

Edit `frontend/js/api.js`. Replace lines 33–36:

```javascript
            if (!response.ok) {
                const error = await response.json().catch(() => ({}));
                throw new Error(error.detail || `HTTP ${response.status}`);
            }
```

with:

```javascript
            if (!response.ok) {
                const body = await response.json().catch(() => ({}));
                const err = new Error(body.detail || `HTTP ${response.status}`);
                err.status = response.status;
                throw err;
            }
```

- [ ] **Step 2: Confirm no other test or call site relies on the error object's exact shape**

Run: `cd /Users/rosscaleca/Development/GridRunner && grep -rn "\.status" frontend/js/`

Expected: existing call sites already access `e.message` only; `e.status` was undefined before, so attaching it is purely additive.

- [ ] **Step 3: Commit**

```bash
cd /Users/rosscaleca/Development/GridRunner
git add frontend/js/api.js
git commit -m "feat: attach HTTP status to errors thrown by api client

Lets callers distinguish 404 from 5xx. Used by the upcoming
cancelRun() helper to silently treat 'process already gone' as
success."
```

---

## Task 3: Frontend — shared `cancelRun()` on `Alpine.store('app')`

**Files:**
- Modify: `frontend/js/app.js:5-61` (the `Alpine.store('app', { ... })` block)

- [ ] **Step 1: Add `cancelRun()` method to the app store**

Edit `frontend/js/app.js`. Inside the `Alpine.store('app', { ... })` object, add a new method right after `showToast` (line ~55) and before `logout`:

```javascript
        async cancelRun(scriptId, runId, scriptName) {
            if (!confirm(`Cancel "${scriptName}"? The script will be terminated.`)) {
                return false;
            }
            try {
                await api.killScript(scriptId, runId);
                this.showToast(`Cancelled ${scriptName}`, 'success');
                return true;
            } catch (e) {
                if (e.status === 404) {
                    // Race: process finished a moment before the kill arrived.
                    // Per spec, treat as success with a neutral info toast.
                    this.showToast('Run already finished', 'info');
                    return true;
                }
                this.showToast(e.message || 'Failed to cancel run', 'error');
                return false;
            }
        },
```

- [ ] **Step 2: Sanity-check the file still parses**

Run: `cd /Users/rosscaleca/Development/GridRunner && node --check frontend/js/app.js`

Expected: no output (success).

- [ ] **Step 3: Commit**

```bash
cd /Users/rosscaleca/Development/GridRunner
git add frontend/js/app.js
git commit -m "feat: add shared cancelRun() helper on app store

Encapsulates confirm prompt, API call, and toast feedback so all
three Cancel-button surfaces use identical behavior."
```

---

## Task 4: Frontend — Cancel button on Dashboard "Currently Running"

**Files:**
- Modify: `frontend/index.html:166-180` (the `Currently Running` template)
- Modify: `frontend/js/app.js` — `dashboard` component (~line 107)

- [ ] **Step 1: Add Cancel button to the dashboard "Currently Running" row template**

Edit `frontend/index.html`. Replace lines 168–179 (the `<template x-for="run in running">` block) with:

```html
                                            <template x-for="run in running" :key="run.run_id">
                                                <div class="flex items-center justify-between" style="padding: 8px 0; border-bottom: 1px solid var(--border-color);">
                                                    <div>
                                                        <div x-text="run.script_name"></div>
                                                        <div class="text-muted" x-text="formatDuration(run.duration_so_far)"></div>
                                                    </div>
                                                    <div class="flex items-center gap-2">
                                                        <span class="badge badge-info">
                                                            <span class="spinner" style="width: 12px; height: 12px;"></span>
                                                            Running
                                                        </span>
                                                        <button class="btn btn-sm btn-danger"
                                                                @click="cancelRun(run)"
                                                                :disabled="cancelling.includes(run.run_id)">
                                                            Cancel
                                                        </button>
                                                    </div>
                                                </div>
                                            </template>
```

- [ ] **Step 2: Add `cancelling` state and `cancelRun()` method to the `dashboard` component**

Edit `frontend/js/app.js`. In the `Alpine.data('dashboard', () => ({...}))` block (starting line ~107), add `cancelling: []` to the state object alongside the other arrays, and add a `cancelRun` method. The component should look like:

```javascript
    Alpine.data('dashboard', () => ({
        stats: null,
        running: [],
        recent: [],
        upcoming: [],
        failures: [],
        cancelling: [],
        loading: true,

        // ...existing init / _scheduleRefresh / refresh methods unchanged...

        async cancelRun(run) {
            this.cancelling.push(run.run_id);
            try {
                const ok = await Alpine.store('app').cancelRun(
                    run.script_id, run.run_id, run.script_name
                );
                if (ok) await this.refresh();
            } finally {
                this.cancelling = this.cancelling.filter(id => id !== run.run_id);
            }
        },

        // ...existing formatDuration / formatDate / getStatusBadgeClass unchanged...
    }));
```

- [ ] **Step 3: Sanity-check the file still parses**

Run: `cd /Users/rosscaleca/Development/GridRunner && node --check frontend/js/app.js`

Expected: no output.

- [ ] **Step 4: Manual verification**

Start the app: `cd /Users/rosscaleca/Development/GridRunner && uv run run.py`

In the desktop window:
1. Trigger a long-running script (or create one that sleeps 60s).
2. Navigate to Dashboard. Confirm the row shows a red "Cancel" button next to "Running".
3. Click Cancel. Confirm a `Cancel "<name>"? The script will be terminated.` prompt appears.
4. Confirm the prompt. The row should disappear from "Currently Running" within ~2s, and a green success toast should appear.
5. Trigger another run; confirm the prompt; cancel before the script finishes; verify the toast appears.

- [ ] **Step 5: Commit**

```bash
cd /Users/rosscaleca/Development/GridRunner
git add frontend/index.html frontend/js/app.js
git commit -m "feat: cancel button on dashboard Currently Running rows"
```

---

## Task 5: Frontend — Cancel button on Scripts page row

**Files:**
- Modify: `frontend/index.html:367-376` (the script row action buttons)
- Modify: `frontend/js/app.js` — `scripts` component

- [ ] **Step 1: Conditionally render Run vs Cancel in the scripts table**

Edit `frontend/index.html`. Replace line 369 (`<button class="btn btn-sm btn-success" @click="runScript(script)" :disabled="script.is_running">Run</button>`) with:

```html
                                                        <template x-if="!script.is_running">
                                                            <button class="btn btn-sm btn-success" @click="runScript(script)">Run</button>
                                                        </template>
                                                        <template x-if="script.is_running">
                                                            <button class="btn btn-sm btn-danger"
                                                                    @click="cancelRun(script)"
                                                                    :disabled="cancelling.includes(script.id)">
                                                                Cancel
                                                            </button>
                                                        </template>
```

- [ ] **Step 2: Add `cancelling` state and `cancelRun()` method to the `scripts` component**

Edit `frontend/js/app.js`. In the `Alpine.data('scripts', () => ({...}))` block (starting line ~174), add `cancelling: []` to the state and a `cancelRun` method (place it near `runScript`, around line ~389):

```javascript
        cancelling: [],

        // ...existing methods...

        async cancelRun(script) {
            if (!script.running_run_id) {
                Alpine.store('app').showToast('No running run found for this script', 'error');
                return;
            }
            this.cancelling.push(script.id);
            try {
                const ok = await Alpine.store('app').cancelRun(
                    script.id, script.running_run_id, script.name
                );
                if (ok) await this.refresh();
            } finally {
                this.cancelling = this.cancelling.filter(id => id !== script.id);
            }
        },
```

- [ ] **Step 3: Sanity-check the file still parses**

Run: `cd /Users/rosscaleca/Development/GridRunner && node --check frontend/js/app.js`

Expected: no output.

- [ ] **Step 4: Manual verification**

Run app, navigate to Scripts, run a long script, confirm the "Run" button on the row swaps to a red "Cancel" button. Click Cancel, confirm prompt, confirm — within ~2s the row's status flips back to (e.g.) "killed" or the previous last_run_status, and the Cancel button reverts to "Run".

- [ ] **Step 5: Commit**

```bash
cd /Users/rosscaleca/Development/GridRunner
git add frontend/index.html frontend/js/app.js
git commit -m "feat: cancel button on scripts row (replaces Run while running)"
```

---

## Task 6: Frontend — Cancel button in Run-detail modal

**Files:**
- Modify: `frontend/index.html:821-825` (the modal footer)
- Modify: `frontend/js/app.js` — `history` component

- [ ] **Step 1: Add Cancel button to the modal footer**

Edit `frontend/index.html`. Replace lines 821–825 (the existing `<div class="modal-footer">...</div>`) with:

```html
                                <div class="modal-footer">
                                    <template x-if="selectedRun.status === 'running'">
                                        <button class="btn btn-danger"
                                                @click="cancelRunFromModal()"
                                                :disabled="cancellingModal">
                                            Cancel Run
                                        </button>
                                    </template>
                                    <a :href="'/api/runs/' + selectedRun.id + '/download'" class="btn btn-secondary" download>Download Log</a>
                                    <button class="btn btn-primary" @click="closeRunModal()">Close</button>
                                </div>
```

- [ ] **Step 2: Add `cancellingModal` state and `cancelRunFromModal()` to the `history` component**

Edit `frontend/js/app.js`. In the `Alpine.data('history', () => ({...}))` block (starting line ~646), add `cancellingModal: false` to the state and a method below `viewRun`:

```javascript
        cancellingModal: false,

        // ...existing methods through viewRun...

        async cancelRunFromModal() {
            if (!this.selectedRun || this.selectedRun.status !== 'running') return;
            this.cancellingModal = true;
            try {
                const ok = await Alpine.store('app').cancelRun(
                    this.selectedRun.script_id,
                    this.selectedRun.id,
                    this.selectedRun.script_name || `Run #${this.selectedRun.id}`
                );
                if (ok) {
                    // Refresh selected run detail and the underlying history list
                    try {
                        this.selectedRun = await api.getRun(this.selectedRun.id);
                    } catch (_) { /* run may have just finished; ignore */ }
                    await this.refresh();
                }
            } finally {
                this.cancellingModal = false;
            }
        },
```

- [ ] **Step 3: Sanity-check the file still parses**

Run: `cd /Users/rosscaleca/Development/GridRunner && node --check frontend/js/app.js`

Expected: no output.

- [ ] **Step 4: Manual verification**

Run app, navigate to History, trigger a long script run from elsewhere (Scripts page), then in History click "View Logs" on the running row to open the modal. Confirm the red "Cancel Run" button appears in the footer (only while status === 'running'). Click it, accept the confirm prompt; the modal's Status badge should update to `killed` (or the run-detail should reflect the terminated state) and the History list should refresh.

- [ ] **Step 5: Commit**

```bash
cd /Users/rosscaleca/Development/GridRunner
git add frontend/index.html frontend/js/app.js
git commit -m "feat: cancel button in run detail modal (history view)"
```

---

## Task 7: End-to-end verification — race case + error case

**Files:** none modified; this task is verification only.

- [ ] **Step 1: Verify the 404 race case (silent success)**

Run app. Trigger a script that finishes quickly (e.g., `echo hello` with a 0.5s sleep). Open the Scripts page and immediately click Cancel. It is plausible the script will already be done; confirm the prompt; expected toast: a neutral `'Run already finished'` info-style toast (blue/accent left border), not a red error toast.

If you cannot reliably hit the race window manually, simulate by stopping the server mid-flight or by editing `executor.kill_script` to return False unconditionally for one test pass — then revert. (Do not commit any temporary changes.)

- [ ] **Step 2: Verify the error case (5xx or other failure)**

Stop the server while a script is running, then click Cancel from a stale UI. Expected: a red error toast with a message; the button re-enables.

- [ ] **Step 3: Verify all three surfaces still work in dark mode**

Toggle dark mode (top-right of UI) and repeat the Dashboard / Scripts / History modal cancel flows once each. Confirm the red `btn-danger` Cancel button is visible against the dark background.

- [ ] **Step 4: Final test-suite run**

Run: `cd /Users/rosscaleca/Development/GridRunner && uv run pytest -v`

Expected: all tests pass.

- [ ] **Step 5: No commit needed for verification-only steps**

If any tweaks were made during verification (e.g., copy adjustments, styling fixes), commit them as a follow-up `chore:` or `fix:` commit. Otherwise this task is complete.
