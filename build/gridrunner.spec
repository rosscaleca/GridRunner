# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for GridRunner."""

import sys
from pathlib import Path

block_cipher = None

# Resolve all paths relative to the project root (one level up from this spec file)
ROOT = Path(SPECPATH).parent

a = Analysis(
    [str(ROOT / "run.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "frontend"), "frontend"),
    ],
    hiddenimports=[
        "backend",
        "backend.main",
        "backend.config",
        "backend.database",
        "backend.models",
        "backend.executor",
        "backend.scheduler",
        "backend.notifications",
        "backend.logging_config",
        "backend.api",
        "backend.api.auth",
        "backend.api.scripts",
        "backend.api.schedules",
        "backend.api.runs",
        "backend.api.dashboard",
        "backend.api.settings",
        "backend.api.cron",
        "backend.api.runtimes",
        "backend.api.environments",
        "backend.runtimes",
        "uvicorn",
        "uvicorn.config",
        "uvicorn.main",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.http.httptools_impl",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "uvicorn.lifespan.off",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.loops.asyncio",
        "sqlalchemy.dialects.sqlite",
        "sqlalchemy.dialects.sqlite.aiosqlite",
        "aiosqlite",
        "webview",
        "apscheduler",
        "apscheduler.triggers.interval",
        "apscheduler.triggers.cron",
        "apscheduler.triggers.date",
        "apscheduler.jobstores.memory",
        "apscheduler.executors.asyncio",
        "aiosmtplib",
        "bcrypt",
        "multipart",
        "python_multipart",
        "sse_starlette",
        "httpx",
        "aiofiles",
        "itsdangerous",
        "greenlet",
        "pydantic",
        "pydantic_settings",
        "python_crontab",
        "crontab",
        "starlette.middleware.sessions",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "pytest_asyncio"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GridRunner",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=str(ROOT / "assets" / "GridRunner.icns") if sys.platform == "darwin" else (
        str(ROOT / "assets" / "GridRunner.ico") if sys.platform == "win32" else None
    ),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="GridRunner",
)

# macOS .app bundle
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="GridRunner.app",
        icon=str(ROOT / "assets" / "GridRunner.icns"),
        bundle_identifier="com.gridrunner.app",
        info_plist={
            "CFBundleName": "GridRunner",
            "CFBundleDisplayName": "GridRunner",
            "CFBundleVersion": "1.0.0",
            "CFBundleShortVersionString": "1.0.0",
            "NSHighResolutionCapable": True,
        },
    )
