"""Dashboard data routes."""

from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_session
from ..models import Run, Script, Schedule
from ..executor import running_processes
from ..scheduler import get_upcoming_runs
from .auth import require_auth

router = APIRouter()


class DashboardStats(BaseModel):
    total_scripts: int
    total_schedules: int
    active_schedules: int
    running_now: int
    runs_today: int
    successful_today: int
    failed_today: int
    success_rate_today: float


class RunningScript(BaseModel):
    run_id: int
    script_id: int
    script_name: str
    started_at: datetime
    duration_so_far: float


class RecentRun(BaseModel):
    id: int
    script_id: int
    script_name: str
    status: str
    started_at: datetime
    duration: Optional[float]
    trigger_type: str


class UpcomingRun(BaseModel):
    schedule_id: int
    script_id: int
    script_name: str
    next_run: str


class FailedScript(BaseModel):
    script_id: int
    script_name: str
    failure_count: int
    last_failure: datetime
    health_score: float


@router.get("/stats", response_model=DashboardStats)
async def get_dashboard_stats(
    request: Request,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_auth)
):
    """Get dashboard summary statistics."""
    # Count scripts
    result = await session.execute(select(func.count(Script.id)))
    total_scripts = result.scalar() or 0

    # Count schedules
    result = await session.execute(select(func.count(Schedule.id)))
    total_schedules = result.scalar() or 0

    result = await session.execute(
        select(func.count(Schedule.id)).where(Schedule.enabled == True)
    )
    active_schedules = result.scalar() or 0

    # Running now
    running_now = len(running_processes)

    # Today's stats
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    result = await session.execute(
        select(func.count(Run.id)).where(Run.started_at >= today_start)
    )
    runs_today = result.scalar() or 0

    result = await session.execute(
        select(func.count(Run.id)).where(
            and_(
                Run.started_at >= today_start,
                Run.status == "success"
            )
        )
    )
    successful_today = result.scalar() or 0

    result = await session.execute(
        select(func.count(Run.id)).where(
            and_(
                Run.started_at >= today_start,
                Run.status.in_(["failed", "timeout", "killed"])
            )
        )
    )
    failed_today = result.scalar() or 0

    success_rate = 0.0
    if runs_today > 0:
        success_rate = (successful_today / runs_today) * 100

    return DashboardStats(
        total_scripts=total_scripts,
        total_schedules=total_schedules,
        active_schedules=active_schedules,
        running_now=running_now,
        runs_today=runs_today,
        successful_today=successful_today,
        failed_today=failed_today,
        success_rate_today=round(success_rate, 1)
    )


@router.get("/running", response_model=List[RunningScript])
async def get_running_scripts(
    request: Request,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_auth)
):
    """Get currently running scripts."""
    running = []

    for run_id in running_processes.keys():
        result = await session.execute(
            select(Run)
            .options(selectinload(Run.script))
            .where(Run.id == run_id)
        )
        run = result.scalar_one_or_none()

        if run:
            duration = (datetime.utcnow() - run.started_at).total_seconds()
            running.append(RunningScript(
                run_id=run.id,
                script_id=run.script_id,
                script_name=run.script.name if run.script else f"Script #{run.script_id}",
                started_at=run.started_at,
                duration_so_far=round(duration, 1)
            ))

    return running


@router.get("/recent", response_model=List[RecentRun])
async def get_recent_runs(
    request: Request,
    limit: int = 10,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_auth)
):
    """Get recent runs."""
    result = await session.execute(
        select(Run)
        .options(selectinload(Run.script))
        .order_by(Run.started_at.desc())
        .limit(limit)
    )
    runs = result.scalars().all()

    return [
        RecentRun(
            id=r.id,
            script_id=r.script_id,
            script_name=r.script.name if r.script else f"Script #{r.script_id}",
            status=r.status,
            started_at=r.started_at,
            duration=r.duration,
            trigger_type=r.trigger_type
        )
        for r in runs
    ]


@router.get("/upcoming", response_model=List[UpcomingRun])
async def get_upcoming_scheduled_runs(
    request: Request,
    limit: int = 10,
    _: None = Depends(require_auth)
):
    """Get upcoming scheduled runs."""
    upcoming = await get_upcoming_runs(limit)
    return [
        UpcomingRun(
            schedule_id=u["schedule_id"],
            script_id=u["script_id"],
            script_name=u["script_name"],
            next_run=u["next_run"]
        )
        for u in upcoming
    ]


@router.get("/failures", response_model=List[FailedScript])
async def get_recent_failures(
    request: Request,
    hours: int = 24,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_auth)
):
    """Get scripts with recent failures."""
    since = datetime.utcnow() - timedelta(hours=hours)

    # Get failed runs grouped by script
    result = await session.execute(
        select(
            Run.script_id,
            func.count(Run.id).label("failure_count"),
            func.max(Run.started_at).label("last_failure")
        )
        .where(
            and_(
                Run.started_at >= since,
                Run.status.in_(["failed", "timeout", "killed"])
            )
        )
        .group_by(Run.script_id)
        .order_by(func.count(Run.id).desc())
    )
    failures = result.fetchall()

    failed_scripts = []
    for script_id, failure_count, last_failure in failures:
        result = await session.execute(
            select(Script)
            .options(selectinload(Script.runs))
            .where(Script.id == script_id)
        )
        script = result.scalar_one_or_none()

        if script:
            failed_scripts.append(FailedScript(
                script_id=script.id,
                script_name=script.name,
                failure_count=failure_count,
                last_failure=last_failure,
                health_score=script.health_score
            ))

    return failed_scripts


@router.get("/activity")
async def get_activity_chart(
    request: Request,
    days: int = 7,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_auth)
):
    """Get activity data for chart (runs per day)."""
    since = datetime.utcnow() - timedelta(days=days)

    result = await session.execute(
        select(Run.started_at, Run.status)
        .where(Run.started_at >= since)
        .order_by(Run.started_at)
    )
    runs = result.fetchall()

    # Group by day
    activity = {}
    for started_at, status in runs:
        day = started_at.strftime("%Y-%m-%d")
        if day not in activity:
            activity[day] = {"date": day, "success": 0, "failed": 0, "total": 0}
        activity[day]["total"] += 1
        if status == "success":
            activity[day]["success"] += 1
        elif status in ["failed", "timeout", "killed"]:
            activity[day]["failed"] += 1

    # Fill in missing days
    current = datetime.utcnow()
    for i in range(days):
        day = (current - timedelta(days=i)).strftime("%Y-%m-%d")
        if day not in activity:
            activity[day] = {"date": day, "success": 0, "failed": 0, "total": 0}

    return sorted(activity.values(), key=lambda x: x["date"])
