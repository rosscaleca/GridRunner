"""FastAPI application entry point."""

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from .config import settings
from .database import init_db, async_session
from .logging_config import setup_logging
from .scheduler import start_scheduler, stop_scheduler
from .api.settings import load_settings_from_db

# Import API routers
from .api.auth import router as auth_router
from .api.scripts import router as scripts_router
from .api.schedules import router as schedules_router
from .api.runs import router as runs_router
from .api.dashboard import router as dashboard_router
from .api.settings import router as settings_router
from .api.cron import router as cron_router
from .api.runtimes import router as runtimes_router
from .api.environments import router as environments_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    settings.ensure_directories()
    setup_logging()
    await init_db()
    async with async_session() as session:
        await load_settings_from_db(session)
    await start_scheduler()
    yield
    # Shutdown
    await stop_scheduler()


app = FastAPI(
    title="GridRunner",
    description="Manage and schedule scripts",
    version="1.0.0",
    lifespan=lifespan,
)

# Add CORS middleware — local-only desktop app, all requests are same-origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add session middleware
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    max_age=settings.session_expire_hours * 3600,
)

# Include API routers
app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(scripts_router, prefix="/api/scripts", tags=["scripts"])
app.include_router(schedules_router, prefix="/api/schedules", tags=["schedules"])
app.include_router(runs_router, prefix="/api/runs", tags=["runs"])
app.include_router(dashboard_router, prefix="/api/dashboard", tags=["dashboard"])
app.include_router(settings_router, prefix="/api/settings", tags=["settings"])
app.include_router(cron_router, prefix="/api/cron", tags=["cron"])
app.include_router(runtimes_router, prefix="/api/runtimes", tags=["runtimes"])
app.include_router(environments_router, prefix="/api/environments", tags=["environments"])

# Get the frontend directory path (PyInstaller bundles under sys._MEIPASS)
if getattr(sys, 'frozen', False):
    FRONTEND_DIR = Path(sys._MEIPASS) / "frontend"
else:
    FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


# Mount static files
if FRONTEND_DIR.exists():
    app.mount("/css", StaticFiles(directory=FRONTEND_DIR / "css"), name="css")
    app.mount("/js", StaticFiles(directory=FRONTEND_DIR / "js"), name="js")


@app.get("/")
async def serve_frontend():
    """Serve the frontend index.html."""
    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return JSONResponse(
        {"message": "Frontend not found. API is running at /docs"},
        status_code=200
    )


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


def run():
    """Run the application with uvicorn."""
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    run()
