"""Email and webhook notification handlers."""

import json
import ssl
from datetime import datetime, timedelta
from typing import Optional, List
import asyncio

import aiosmtplib
import certifi
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import httpx

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .database import async_session
from .logging_config import get_logger
from .models import Run, Script, AppSetting

logger = get_logger("notifications")


async def send_email(
    to: str,
    subject: str,
    body: str,
    html_body: Optional[str] = None
) -> bool:
    """Send an email using configured SMTP settings."""
    if not settings.smtp_host or not settings.smtp_from:
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.smtp_from
        msg["To"] = to

        msg.attach(MIMEText(body, "plain"))
        if html_body:
            msg.attach(MIMEText(html_body, "html"))

        tls_context = ssl.create_default_context(cafile=certifi.where())
        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user or None,
            password=settings.smtp_password or None,
            start_tls=settings.smtp_use_tls,
            tls_context=tls_context,
        )
        return True
    except Exception as e:
        logger.error("Email send error", exc_info=True)
        return False


async def send_webhook(url: str, payload: dict) -> bool:
    """Send a webhook POST request."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                json=payload,
                timeout=10.0,
                headers={"Content-Type": "application/json"}
            )
            return response.status_code < 400
    except Exception as e:
        logger.error("Webhook send error", exc_info=True)
        return False


async def send_run_notification(run_id: int) -> None:
    """Send notifications for a completed run based on script settings."""
    async with async_session() as session:
        result = await session.execute(
            select(Run).where(Run.id == run_id)
        )
        run = result.scalar_one_or_none()
        if not run:
            return

        result = await session.execute(
            select(Script).where(Script.id == run.script_id)
        )
        script = result.scalar_one_or_none()
        if not script:
            return

        # Check notification settings
        should_notify = False
        if script.notification_setting == "always":
            should_notify = True
        elif script.notification_setting == "on_failure" and run.status != "success":
            should_notify = True

        if not should_notify:
            return

        # Prepare notification content
        status_emoji = {
            "success": "✅",
            "failed": "❌",
            "timeout": "⏰",
            "killed": "🛑"
        }.get(run.status, "❓")

        subject = f"{status_emoji} Script '{script.name}' - {run.status.upper()}"

        body = f"""GridRunner Notification

Script: {script.name}
Status: {run.status.upper()}
Started: {run.started_at.strftime('%Y-%m-%d %H:%M:%S')}
Duration: {run.duration:.1f}s
Exit Code: {run.exit_code}

--- STDOUT ---
{run.stdout or '(no output)'}

--- STDERR ---
{run.stderr or '(no errors)'}
"""

        html_body = f"""
<html>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
<h2>{status_emoji} Script '{script.name}' - {run.status.upper()}</h2>
<table style="border-collapse: collapse;">
<tr><td style="padding: 4px 12px 4px 0; color: #666;">Status:</td><td>{run.status.upper()}</td></tr>
<tr><td style="padding: 4px 12px 4px 0; color: #666;">Started:</td><td>{run.started_at.strftime('%Y-%m-%d %H:%M:%S')}</td></tr>
<tr><td style="padding: 4px 12px 4px 0; color: #666;">Duration:</td><td>{run.duration:.1f}s</td></tr>
<tr><td style="padding: 4px 12px 4px 0; color: #666;">Exit Code:</td><td>{run.exit_code}</td></tr>
</table>
<h3>STDOUT</h3>
<pre style="background: #f5f5f5; padding: 12px; overflow-x: auto;">{run.stdout or '(no output)'}</pre>
<h3>STDERR</h3>
<pre style="background: #fef2f2; padding: 12px; overflow-x: auto;">{run.stderr or '(no errors)'}</pre>
</body>
</html>
"""

        # Send email notification
        # Get recipient from settings
        result = await session.execute(
            select(AppSetting).where(AppSetting.key == "notification_email")
        )
        setting = result.scalar_one_or_none()
        if setting and setting.value:
            await send_email(setting.value, subject, body, html_body)

        # Send webhook if configured
        if script.webhook_url:
            await send_webhook(script.webhook_url, {
                "event": "run_completed",
                "script": {
                    "id": script.id,
                    "name": script.name,
                },
                "run": {
                    "id": run.id,
                    "status": run.status,
                    "exit_code": run.exit_code,
                    "duration": run.duration,
                    "started_at": run.started_at.isoformat(),
                    "ended_at": run.ended_at.isoformat() if run.ended_at else None,
                }
            })


async def send_daily_digest() -> None:
    """Send daily digest email summarizing all runs from the past 24 hours."""
    if not settings.daily_digest_enabled:
        return

    recipients = [
        r.strip() for r in settings.daily_digest_recipients.split(",")
        if r.strip()
    ]
    if not recipients:
        return

    async with async_session() as session:
        # Get runs from last 24 hours
        since = datetime.utcnow() - timedelta(hours=24)
        result = await session.execute(
            select(Run)
            .where(Run.started_at >= since)
            .order_by(Run.started_at.desc())
        )
        runs = result.scalars().all()

        if not runs:
            return

        # Gather script info
        script_ids = set(r.script_id for r in runs)
        result = await session.execute(
            select(Script).where(Script.id.in_(script_ids))
        )
        scripts = {s.id: s for s in result.scalars().all()}

        # Build summary
        total = len(runs)
        successful = sum(1 for r in runs if r.status == "success")
        failed = sum(1 for r in runs if r.status != "success")

        subject = f"📊 Daily Script Report: {successful}/{total} successful"

        body_lines = [
            "GridRunner - Daily Digest",
            "=" * 40,
            f"Period: Last 24 hours",
            f"Total Runs: {total}",
            f"Successful: {successful}",
            f"Failed: {failed}",
            "",
            "Run Details:",
            "-" * 40,
        ]

        for run in runs[:50]:  # Limit to 50 most recent
            script = scripts.get(run.script_id)
            script_name = script.name if script else f"Script #{run.script_id}"
            status_icon = "✅" if run.status == "success" else "❌"
            body_lines.append(
                f"{status_icon} {script_name} - {run.status} "
                f"({run.duration:.1f}s) at {run.started_at.strftime('%H:%M:%S')}"
            )

        body = "\n".join(body_lines)

        for recipient in recipients:
            await send_email(recipient, subject, body)


async def test_smtp_connection() -> dict:
    """Test SMTP connection with current settings."""
    if not settings.smtp_host:
        return {"success": False, "error": "SMTP host not configured"}

    try:
        tls_context = ssl.create_default_context(cafile=certifi.where())
        smtp = aiosmtplib.SMTP(
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            start_tls=settings.smtp_use_tls,
            tls_context=tls_context,
        )
        await smtp.connect()
        if settings.smtp_user and settings.smtp_password:
            await smtp.login(settings.smtp_user, settings.smtp_password)
        await smtp.quit()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}
