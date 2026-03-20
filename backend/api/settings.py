"""Application settings routes."""

import json
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..logging_config import get_logger
from ..models import AppSetting, Script, Schedule, Category
from ..config import settings
from ..notifications import test_smtp_connection
from .auth import require_auth

logger = get_logger("api.settings")

router = APIRouter()


class SMTPSettings(BaseModel):
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True


class DigestSettings(BaseModel):
    daily_digest_enabled: bool = False
    daily_digest_time: str = "08:00"
    daily_digest_recipients: str = ""


class RetentionSettings(BaseModel):
    log_retention_days: int = 30
    max_log_entries_per_script: int = 100


class NotificationSettings(BaseModel):
    notification_email: str = ""


class AllSettings(BaseModel):
    smtp: SMTPSettings = SMTPSettings()
    digest: DigestSettings = DigestSettings()
    retention: RetentionSettings = RetentionSettings()
    notification: NotificationSettings = NotificationSettings()
    dark_mode: bool = False


async def get_setting(session: AsyncSession, key: str) -> Optional[str]:
    """Get a setting value from database."""
    result = await session.execute(
        select(AppSetting).where(AppSetting.key == key)
    )
    setting = result.scalar_one_or_none()
    return setting.value if setting else None


async def set_setting(session: AsyncSession, key: str, value: str) -> None:
    """Set a setting value in database."""
    result = await session.execute(
        select(AppSetting).where(AppSetting.key == key)
    )
    setting = result.scalar_one_or_none()

    if setting:
        setting.value = value
    else:
        setting = AppSetting(key=key, value=value)
        session.add(setting)


@router.get("", response_model=AllSettings)
async def get_all_settings(
    request: Request,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_auth)
):
    """Get all application settings."""
    # Get settings from database
    smtp_settings = await get_setting(session, "smtp_settings")
    digest_settings = await get_setting(session, "digest_settings")
    retention_settings = await get_setting(session, "retention_settings")
    notification_email = await get_setting(session, "notification_email")
    dark_mode = await get_setting(session, "dark_mode")

    # Defensive JSON parsing — fall back to defaults on corrupted data
    try:
        smtp = SMTPSettings(**json.loads(smtp_settings)) if smtp_settings else SMTPSettings()
    except (json.JSONDecodeError, Exception):
        logger.warning("Corrupted smtp_settings in database, using defaults", exc_info=True)
        smtp = SMTPSettings()

    try:
        digest = DigestSettings(**json.loads(digest_settings)) if digest_settings else DigestSettings()
    except (json.JSONDecodeError, Exception):
        logger.warning("Corrupted digest_settings in database, using defaults", exc_info=True)
        digest = DigestSettings()

    try:
        retention = RetentionSettings(**json.loads(retention_settings)) if retention_settings else RetentionSettings()
    except (json.JSONDecodeError, Exception):
        logger.warning("Corrupted retention_settings in database, using defaults", exc_info=True)
        retention = RetentionSettings()

    return AllSettings(
        smtp=smtp,
        digest=digest,
        retention=retention,
        notification=NotificationSettings(notification_email=notification_email or ""),
        dark_mode=dark_mode == "true" if dark_mode else False
    )


@router.put("/smtp")
async def update_smtp_settings(
    data: SMTPSettings,
    request: Request,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_auth)
):
    """Update SMTP settings."""
    await set_setting(session, "smtp_settings", json.dumps(data.model_dump()))
    await session.commit()

    # Update global config
    settings.smtp_host = data.smtp_host
    settings.smtp_port = data.smtp_port
    settings.smtp_user = data.smtp_user
    settings.smtp_password = data.smtp_password
    settings.smtp_from = data.smtp_from
    settings.smtp_use_tls = data.smtp_use_tls

    return {"message": "SMTP settings updated"}


@router.put("/digest")
async def update_digest_settings(
    data: DigestSettings,
    request: Request,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_auth)
):
    """Update daily digest settings."""
    await set_setting(session, "digest_settings", json.dumps(data.model_dump()))
    await session.commit()

    # Update global config
    settings.daily_digest_enabled = data.daily_digest_enabled
    settings.daily_digest_time = data.daily_digest_time
    settings.daily_digest_recipients = data.daily_digest_recipients

    return {"message": "Digest settings updated"}


@router.put("/retention")
async def update_retention_settings(
    data: RetentionSettings,
    request: Request,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_auth)
):
    """Update log retention settings."""
    await set_setting(session, "retention_settings", json.dumps(data.model_dump()))
    await session.commit()

    # Update global config
    settings.log_retention_days = data.log_retention_days
    settings.max_log_entries_per_script = data.max_log_entries_per_script

    return {"message": "Retention settings updated"}


@router.put("/notification")
async def update_notification_settings(
    data: NotificationSettings,
    request: Request,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_auth)
):
    """Update notification settings."""
    await set_setting(session, "notification_email", data.notification_email)
    await session.commit()

    return {"message": "Notification settings updated"}


@router.put("/dark-mode")
async def update_dark_mode(
    request: Request,
    enabled: bool = True,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_auth)
):
    """Toggle dark mode."""
    await set_setting(session, "dark_mode", "true" if enabled else "false")
    await session.commit()

    return {"dark_mode": enabled}


@router.post("/smtp/test")
async def test_smtp(
    request: Request,
    _: None = Depends(require_auth)
):
    """Test SMTP connection."""
    result = await test_smtp_connection()
    return result


@router.get("/backup")
async def backup_config(
    request: Request,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_auth)
):
    """Export all configuration as JSON."""
    # Get all scripts
    result = await session.execute(select(Script))
    scripts = result.scalars().all()

    # Get all categories
    result = await session.execute(select(Category))
    categories = result.scalars().all()

    # Get all schedules
    result = await session.execute(select(Schedule))
    schedules = result.scalars().all()

    # Get all settings
    result = await session.execute(select(AppSetting))
    app_settings = result.scalars().all()

    backup = {
        "version": "1.0",
        "exported_at": datetime.utcnow().isoformat(),
        "categories": [
            {
                "id": c.id,
                "name": c.name,
                "color": c.color
            }
            for c in categories
        ],
        "scripts": [
            {
                "id": s.id,
                "name": s.name,
                "description": s.description,
                "path": s.path,
                "interpreter_path": s.interpreter_path,
                "working_directory": s.working_directory,
                "env_vars": s.env_vars,
                "args": s.args,
                "timeout": s.timeout,
                "retry_count": s.retry_count,
                "retry_delay": s.retry_delay,
                "category_id": s.category_id,
                "notification_setting": s.notification_setting,
                "webhook_url": s.webhook_url
            }
            for s in scripts
        ],
        "schedules": [
            {
                "id": sch.id,
                "script_id": sch.script_id,
                "schedule_type": sch.schedule_type,
                "interval_value": sch.interval_value,
                "interval_unit": sch.interval_unit,
                "cron_expression": sch.cron_expression,
                "specific_time": sch.specific_time,
                "days_of_week": sch.days_of_week,
                "enabled": sch.enabled
            }
            for sch in schedules
        ],
        "settings": {
            s.key: s.value for s in app_settings
            if s.key != "password_hash"  # Don't export password
        }
    }

    return JSONResponse(
        content=backup,
        headers={
            "Content-Disposition": f"attachment; filename=gridrunner-backup-{datetime.utcnow().strftime('%Y%m%d')}.json"
        }
    )


@router.post("/restore")
async def restore_config(
    request: Request,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_auth)
):
    """Restore configuration from backup JSON."""
    try:
        content = await file.read()
        backup = json.loads(content.decode("utf-8"))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid backup file: {e}")

    if "version" not in backup:
        raise HTTPException(status_code=400, detail="Invalid backup format")

    restored = {"categories": 0, "scripts": 0, "schedules": 0, "settings": 0}

    # Restore categories
    for cat_data in backup.get("categories", []):
        cat_id = cat_data.pop("id", None)
        category = Category(**cat_data)
        session.add(category)
        restored["categories"] += 1

    await session.commit()

    # Restore scripts (need to map old category IDs to new)
    for script_data in backup.get("scripts", []):
        script_data.pop("id", None)
        script = Script(**script_data)
        session.add(script)
        restored["scripts"] += 1

    await session.commit()

    # Restore schedules
    for sch_data in backup.get("schedules", []):
        sch_data.pop("id", None)
        schedule = Schedule(**sch_data)
        session.add(schedule)
        restored["schedules"] += 1

    await session.commit()

    # Restore settings
    for key, value in backup.get("settings", {}).items():
        await set_setting(session, key, value)
        restored["settings"] += 1

    await session.commit()

    # Save backup file
    backup_path = settings.data_dir / "backups" / f"restored-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.json"
    backup_path.write_text(json.dumps(backup, indent=2))

    return {"message": "Configuration restored", "restored": restored}


@router.get("/service/status")
async def get_service_status(
    request: Request,
    _: None = Depends(require_auth)
):
    """Get service status information."""
    import os
    from ..scheduler import get_scheduler

    scheduler = get_scheduler()

    return {
        "running": True,
        "scheduler_running": scheduler.running,
        "scheduled_jobs": len(scheduler.get_jobs()),
        "data_directory": str(settings.data_dir),
        "pid": os.getpid(),
        "host": settings.host,
        "port": settings.port
    }
