"""Cron import feature routes."""

import platform
import subprocess
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..logging_config import get_logger
from ..models import Script, Schedule
from ..scheduler import add_job
from .auth import require_auth

logger = get_logger("api.cron")

router = APIRouter()


class CronJob(BaseModel):
    expression: str
    command: str
    path: Optional[str] = None
    is_python: bool = False
    selected: bool = False


class CronImportRequest(BaseModel):
    jobs: List[CronJob]


def parse_crontab() -> List[dict]:
    """Parse the current user's crontab."""
    try:
        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            return []

        jobs = []
        for line in result.stdout.splitlines():
            line = line.strip()

            # Skip comments and empty lines
            if not line or line.startswith("#"):
                continue

            # Parse cron expression (first 5 fields) and command
            parts = line.split(None, 5)
            if len(parts) < 6:
                continue

            expression = " ".join(parts[:5])
            command = parts[5]

            # Check if it's a Python script
            is_python = "python" in command.lower() or command.endswith(".py")

            # Try to extract the script path
            path = None
            if is_python:
                # Common patterns:
                # python /path/to/script.py
                # /usr/bin/python3 /path/to/script.py
                # python3 script.py
                cmd_parts = command.split()
                for part in cmd_parts:
                    if part.endswith(".py"):
                        path = part
                        break

            jobs.append({
                "expression": expression,
                "command": command,
                "path": path,
                "is_python": is_python
            })

        return jobs

    except FileNotFoundError:
        return []
    except Exception as e:
        logger.warning("Error parsing crontab", exc_info=True)
        return []


@router.get("/parse", response_model=List[CronJob])
async def parse_user_crontab(
    request: Request,
    _: None = Depends(require_auth)
):
    """Parse the current user's crontab and return jobs."""
    if platform.system() == "Windows":
        return []  # crontab is not available on Windows
    jobs = parse_crontab()
    return [CronJob(**job) for job in jobs]


@router.post("/import")
async def import_cron_jobs(
    data: CronImportRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_auth)
):
    """Import selected cron jobs as scripts with schedules."""
    imported = {"scripts": 0, "schedules": 0}

    for job in data.jobs:
        if not job.selected:
            continue

        # Extract script path and name
        if job.path:
            path = job.path
            name = path.split("/")[-1].replace(".py", "").replace("_", " ").title()
        else:
            # Use command as path if no path extracted
            path = job.command
            name = f"Imported Cron Job"

        # Create script
        script = Script(
            name=name,
            description=f"Imported from cron: {job.command}",
            path=path,
            interpreter_path="python3"
        )
        session.add(script)
        await session.commit()
        await session.refresh(script)
        imported["scripts"] += 1

        # Create schedule with cron expression
        schedule = Schedule(
            script_id=script.id,
            schedule_type="cron",
            cron_expression=job.expression,
            enabled=True
        )
        session.add(schedule)
        await session.commit()
        await session.refresh(schedule)

        # Add to scheduler
        await add_job(schedule.id, session)
        imported["schedules"] += 1

    return {
        "message": f"Imported {imported['scripts']} scripts with {imported['schedules']} schedules",
        "imported": imported
    }


@router.post("/validate-expression")
async def validate_cron_expression(
    request: Request,
    expression: str,
    _: None = Depends(require_auth)
):
    """Validate a cron expression and show next run times."""
    from apscheduler.triggers.cron import CronTrigger
    from datetime import datetime, timedelta

    try:
        parts = expression.split()
        if len(parts) != 5:
            return {
                "valid": False,
                "error": "Cron expression must have 5 parts: minute hour day month day_of_week"
            }

        trigger = CronTrigger(
            minute=parts[0],
            hour=parts[1],
            day=parts[2],
            month=parts[3],
            day_of_week=parts[4]
        )

        # Calculate next few run times
        next_runs = []
        current = datetime.now()
        for _ in range(5):
            next_run = trigger.get_next_fire_time(None, current)
            if next_run:
                next_runs.append(next_run.isoformat())
                current = next_run + timedelta(seconds=1)

        return {
            "valid": True,
            "next_runs": next_runs,
            "human_readable": describe_cron(parts)
        }

    except Exception as e:
        return {
            "valid": False,
            "error": str(e)
        }


def describe_cron(parts: List[str]) -> str:
    """Generate human-readable description of cron expression."""
    minute, hour, day, month, dow = parts

    descriptions = []

    # Time
    if minute == "*" and hour == "*":
        descriptions.append("Every minute")
    elif minute == "0" and hour == "*":
        descriptions.append("Every hour")
    elif minute != "*" and hour != "*":
        descriptions.append(f"At {hour}:{minute.zfill(2)}")
    elif minute != "*":
        descriptions.append(f"At minute {minute}")
    elif hour != "*":
        descriptions.append(f"Every minute during hour {hour}")

    # Day of month
    if day != "*":
        descriptions.append(f"on day {day}")

    # Month
    month_names = {
        "1": "January", "2": "February", "3": "March", "4": "April",
        "5": "May", "6": "June", "7": "July", "8": "August",
        "9": "September", "10": "October", "11": "November", "12": "December"
    }
    if month != "*":
        if month in month_names:
            descriptions.append(f"in {month_names[month]}")
        else:
            descriptions.append(f"in month {month}")

    # Day of week
    day_names = {
        "0": "Sunday", "1": "Monday", "2": "Tuesday", "3": "Wednesday",
        "4": "Thursday", "5": "Friday", "6": "Saturday",
        "sun": "Sunday", "mon": "Monday", "tue": "Tuesday", "wed": "Wednesday",
        "thu": "Thursday", "fri": "Friday", "sat": "Saturday"
    }
    if dow != "*":
        dow_lower = dow.lower()
        if dow_lower in day_names:
            descriptions.append(f"on {day_names[dow_lower]}")
        else:
            descriptions.append(f"on weekday {dow}")

    return " ".join(descriptions) if descriptions else "Custom schedule"
