# GridRunner

A pywebview desktop application (FastAPI + Alpine.js) for managing, scheduling, and monitoring scripts on your local machine.

## Stack

- **Backend:** Python 3.10+, FastAPI, SQLAlchemy (async, SQLite via aiosqlite), APScheduler, Pydantic v2
- **Frontend:** Alpine.js 3 (bundled locally), vanilla CSS (single `index.html` + JS modules)
- **Desktop:** pywebview (native OS webview window), uvicorn in background thread
- **Auth:** bcrypt password hashing, session-based auth via Starlette SessionMiddleware (disabled by default)

## Project Structure

```
run.py                   # Desktop entry point (pywebview + uvicorn)
backend/
  main.py                # FastAPI app, lifespan, middleware, static file serving
  config.py              # Pydantic Settings (env prefix: GRIDRUNNER_)
  database.py            # SQLAlchemy async engine + session factory
  models.py              # ORM models: Script, Schedule, Run, Category, AppSetting
  executor.py            # Subprocess execution, process tracking, kill logic, venv support
  runtimes.py            # Runtime discovery — scan system for installed interpreters + versions
  scheduler.py           # APScheduler integration (AsyncIOScheduler)
  notifications.py       # Email (aiosmtplib) and webhook notifications
  logging_config.py      # Structured logging (console + rotating file)
  api/
    auth.py              # Login, setup, logout, password change + rate limiting
    scripts.py           # Script CRUD, run, kill, validate, categories
    schedules.py         # Schedule CRUD, toggle
    runs.py              # Run history, detail, delete, download
    dashboard.py         # Stats, running/upcoming/recent/failures
    settings.py          # App settings CRUD, backup/restore, cron import
    cron.py              # Crontab parsing + import
    runtimes.py          # Runtime discovery API (GET /api/runtimes, POST /api/runtimes/refresh)
    environments.py      # Python venv management (detect, create, packages)
frontend/
  index.html             # Single-page app shell
  css/styles.css         # All styles
  js/
    alpine.min.js        # Alpine.js 3 (bundled locally for offline use)
    api.js               # Fetch wrapper for all API endpoints
    app.js               # Alpine.js components and store
build/
  gridrunner.spec        # PyInstaller spec file
  build_macos.sh         # macOS build script → dist/macos/GridRunner.app
  build_linux.sh         # Linux build script → dist/linux/GridRunner/
  build_windows.bat      # Windows build script → dist/windows/GridRunner/
assets/
  GridRunner.icns        # macOS app icon
  GridRunner.ico         # Windows app icon
tests/
  conftest.py            # Fixtures: in-memory SQLite, db_session, sample scripts, venv fixtures
  test_executor.py       # Tests for build_command, validate_script, get_script_type_from_extension, venv support
  test_runtimes.py       # Tests for runtime discovery: version parsing, strategies, caching
  test_scheduler.py      # Tests for job management with APScheduler
```

## How to Run

```bash
# Desktop app (native window)
cd /path/to/GridRunner
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python run.py

# With auth enabled
GRIDRUNNER_AUTH_ENABLED=true python run.py

# Development (browser, with hot reload)
uvicorn backend.main:app --host 127.0.0.1 --port 8420 --reload
```

## How to Test

```bash
source venv/bin/activate
pytest -v
```

## How to Build

```bash
# macOS
bash build/build_macos.sh    # → dist/macos/GridRunner.app

# Linux (requires libwebkit2gtk-4.0-dev)
bash build/build_linux.sh    # → dist/linux/GridRunner/

# Windows
build\build_windows.bat      # → dist\windows\GridRunner\GridRunner.exe
```

To create a release: `git tag v1.x.0 && git push origin v1.x.0`

## Environment Variables

All prefixed with `GRIDRUNNER_`:

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | (insecure default) | Session signing key |
| `PORT` | 8420 | Server port (auto-assigned in desktop mode) |
| `HOST` | 127.0.0.1 | Bind address |
| `TIMEZONE` | America/Los_Angeles | Display timezone |
| `AUTH_ENABLED` | false | Enable password authentication |

## Key Patterns

- **Desktop app:** `run.py` finds a free port, starts uvicorn in a daemon thread, opens pywebview window on main thread. Window close triggers server shutdown.
- **Frozen path resolution:** `backend/main.py` checks `sys.frozen` for PyInstaller builds and resolves frontend files from `sys._MEIPASS`.
- **Auth optional:** `auth_enabled` setting (env `GRIDRUNNER_AUTH_ENABLED`). When disabled (default), `require_auth` is a no-op and `/api/auth/status` returns `authenticated=True`. Frontend hides logout/security UI.
- **Single-process local app:** No multi-worker concerns; in-memory rate limiting and process tracking are fine
- **Async throughout:** async SQLAlchemy sessions, async subprocess execution, async APScheduler
- **Script types (18):** python, bash, sh, zsh, node, ruby, perl, php, go, r, julia, swift, deno, lua, java, powershell, executable, other
- **Script execution:** `executor.py` builds command arrays per script type, manages subprocess lifecycle with timeout/retry. Python scripts can use `venv_path` for virtual environment isolation.
- **Runtime discovery:** `runtimes.py` scans the system for installed interpreters (pyenv, nvm, homebrew, system) and caches results. Exposed via `GET /api/runtimes`.
- **Environment management:** `api/environments.py` — detect venvs near a script path, create new venvs, list/install/uninstall packages. Exposed via `/api/environments/*`.
- **Database migration:** `database.py:migrate_db()` adds new columns to existing SQLite databases on startup (no Alembic). Script model has `venv_path` and `interpreter_version` fields.
- **Scheduling:** APScheduler `AsyncIOScheduler` with `MemoryJobStore`; schedules rebuilt from DB on startup
- **Logging:** `backend/logging_config.py` — structured logging to console (INFO) and `~/.gridrunner/logs/gridrunner.log` (DEBUG, 5MB rotating, 3 backups). Use `get_logger(name)` to obtain child loggers.
- **Data directory:** `~/.gridrunner/` (DB, logs, backups)
- **Alpine.js bundled locally:** `frontend/js/alpine.min.js` for offline desktop use

## CORS

Origins set to `*` — appropriate for a local-only desktop app where all requests originate from the same machine.

## Rate Limiting

Login endpoint is rate-limited: 5 failed attempts per 5-minute window per client IP. Resets on server restart. Only active when auth is enabled.
