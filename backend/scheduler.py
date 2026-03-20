"""APScheduler integration for script scheduling."""

from datetime import datetime, timedelta
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.jobstores.memory import MemoryJobStore

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .database import async_session
from .logging_config import get_logger
from .models import Schedule, Script
from .executor import execute_script

logger = get_logger("scheduler")


# Global scheduler instance
scheduler: Optional[AsyncIOScheduler] = None


def get_scheduler() -> AsyncIOScheduler:
    """Get the global scheduler instance."""
    global scheduler
    if scheduler is None:
        scheduler = AsyncIOScheduler(
            jobstores={"default": MemoryJobStore()},
            job_defaults={
                "coalesce": True,  # Combine missed runs into one
                "max_instances": 1,  # Don't allow concurrent runs of same job
                "misfire_grace_time": 60,  # Allow 60s grace period for misfired jobs
            }
        )
    return scheduler


async def start_scheduler() -> None:
    """Start the scheduler and load all enabled schedules."""
    sched = get_scheduler()
    if not sched.running:
        sched.start()
        await load_all_schedules()


async def stop_scheduler() -> None:
    """Stop the scheduler."""
    sched = get_scheduler()
    if sched.running:
        sched.shutdown(wait=False)


async def load_all_schedules() -> None:
    """Load all enabled schedules from database."""
    async with async_session() as session:
        result = await session.execute(
            select(Schedule).where(Schedule.enabled == True)
        )
        schedules = result.scalars().all()

        loaded = 0
        failed = 0
        for schedule in schedules:
            try:
                success = await add_job(schedule.id, session)
                if success:
                    loaded += 1
                else:
                    failed += 1
            except Exception:
                logger.warning(
                    "Failed to load schedule %d", schedule.id, exc_info=True
                )
                failed += 1

        logger.info(
            "Schedule rebuild complete: %d loaded, %d failed", loaded, failed
        )


def get_job_id(schedule_id: int) -> str:
    """Generate consistent job ID for a schedule."""
    return f"schedule_{schedule_id}"


async def add_job(schedule_id: int, session: Optional[AsyncSession] = None) -> bool:
    """Add or update a job for a schedule."""
    close_session = session is None
    if session is None:
        session = async_session()
        await session.__aenter__()

    try:
        result = await session.execute(
            select(Schedule).where(Schedule.id == schedule_id)
        )
        schedule = result.scalar_one_or_none()

        if not schedule or not schedule.enabled:
            return False

        sched = get_scheduler()
        job_id = get_job_id(schedule_id)

        # Remove existing job if any
        existing = sched.get_job(job_id)
        if existing:
            sched.remove_job(job_id)

        # Create trigger based on schedule type
        trigger = None

        if schedule.schedule_type == "interval":
            kwargs = {}
            if schedule.interval_unit == "minutes":
                kwargs["minutes"] = schedule.interval_value
            elif schedule.interval_unit == "hours":
                kwargs["hours"] = schedule.interval_value
            elif schedule.interval_unit == "days":
                kwargs["days"] = schedule.interval_value
            trigger = IntervalTrigger(**kwargs)

        elif schedule.schedule_type == "cron":
            if schedule.cron_expression:
                parts = schedule.cron_expression.split()
                if len(parts) >= 5:
                    trigger = CronTrigger(
                        minute=parts[0],
                        hour=parts[1],
                        day=parts[2],
                        month=parts[3],
                        day_of_week=parts[4]
                    )

        elif schedule.schedule_type == "specific_time":
            if schedule.specific_time:
                hour, minute = map(int, schedule.specific_time.split(":"))
                # If days_of_week specified, use those
                if schedule.days_of_week:
                    # Convert to cron day format (mon=0 in our DB, mon=0 in APScheduler)
                    days = ",".join(str(d) for d in schedule.days_of_week)
                    trigger = CronTrigger(hour=hour, minute=minute, day_of_week=days)
                else:
                    # Daily at specific time
                    trigger = CronTrigger(hour=hour, minute=minute)

        if trigger:
            # Add the job
            job = sched.add_job(
                run_scheduled_script,
                trigger=trigger,
                id=job_id,
                args=[schedule.script_id, schedule_id],
                replace_existing=True,
            )

            # Update next run time
            schedule.next_run = job.next_run_time
            await session.commit()
            return True

        return False

    finally:
        if close_session:
            await session.__aexit__(None, None, None)


async def remove_job(schedule_id: int) -> bool:
    """Remove a job for a schedule."""
    sched = get_scheduler()
    job_id = get_job_id(schedule_id)
    job = sched.get_job(job_id)
    if job:
        sched.remove_job(job_id)
        return True
    return False


async def run_scheduled_script(script_id: int, schedule_id: int) -> None:
    """Execute a script as a scheduled run."""
    try:
        await execute_script(
            script_id=script_id,
            schedule_id=schedule_id,
            trigger_type="scheduled"
        )
    except Exception as e:
        logger.error("Scheduled execution error for script %d", script_id, exc_info=True)

    # Update next run time
    async with async_session() as session:
        result = await session.execute(
            select(Schedule).where(Schedule.id == schedule_id)
        )
        schedule = result.scalar_one_or_none()
        if schedule:
            sched = get_scheduler()
            job = sched.get_job(get_job_id(schedule_id))
            if job:
                schedule.next_run = job.next_run_time
                await session.commit()


async def get_upcoming_runs(limit: int = 10) -> list:
    """Get the next N upcoming scheduled runs."""
    sched = get_scheduler()
    jobs = sched.get_jobs()

    upcoming = []
    for job in jobs:
        if job.next_run_time:
            # Extract schedule_id from job_id
            schedule_id = int(job.id.replace("schedule_", ""))

            async with async_session() as session:
                result = await session.execute(
                    select(Schedule).where(Schedule.id == schedule_id)
                )
                schedule = result.scalar_one_or_none()

                if schedule:
                    result = await session.execute(
                        select(Script).where(Script.id == schedule.script_id)
                    )
                    script = result.scalar_one_or_none()

                    upcoming.append({
                        "schedule_id": schedule_id,
                        "script_id": schedule.script_id,
                        "script_name": script.name if script else "Unknown",
                        "next_run": job.next_run_time.isoformat(),
                    })

    # Sort by next run time
    upcoming.sort(key=lambda x: x["next_run"])
    return upcoming[:limit]


async def toggle_schedule(schedule_id: int, enabled: bool) -> bool:
    """Enable or disable a schedule."""
    async with async_session() as session:
        result = await session.execute(
            select(Schedule).where(Schedule.id == schedule_id)
        )
        schedule = result.scalar_one_or_none()

        if not schedule:
            return False

        schedule.enabled = enabled
        await session.commit()

        if enabled:
            await add_job(schedule_id, session)
        else:
            await remove_job(schedule_id)

        return True
