"""Schedule management routes."""

from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_session
from ..models import Schedule, Script
from ..scheduler import add_job, remove_job, toggle_schedule
from .auth import require_auth

router = APIRouter()


class ScheduleCreate(BaseModel):
    script_id: int
    schedule_type: str  # interval, cron, specific_time
    interval_value: Optional[int] = None
    interval_unit: Optional[str] = None  # minutes, hours, days
    cron_expression: Optional[str] = None
    specific_time: Optional[str] = None  # HH:MM
    days_of_week: Optional[List[int]] = None  # [0-6]
    enabled: bool = True


class ScheduleUpdate(BaseModel):
    schedule_type: Optional[str] = None
    interval_value: Optional[int] = None
    interval_unit: Optional[str] = None
    cron_expression: Optional[str] = None
    specific_time: Optional[str] = None
    days_of_week: Optional[List[int]] = None
    enabled: Optional[bool] = None


class ScheduleResponse(BaseModel):
    id: int
    script_id: int
    script_name: Optional[str] = None
    schedule_type: str
    interval_value: Optional[int]
    interval_unit: Optional[str]
    cron_expression: Optional[str]
    specific_time: Optional[str]
    days_of_week: Optional[List[int]]
    enabled: bool
    next_run: Optional[datetime]
    created_at: datetime
    human_readable: str = ""

    class Config:
        from_attributes = True


def get_human_readable(schedule: Schedule) -> str:
    """Convert schedule to human-readable format."""
    if schedule.schedule_type == "interval":
        unit = schedule.interval_unit or "minutes"
        value = schedule.interval_value or 1
        if value == 1:
            unit = unit.rstrip("s")  # Remove 's' for singular
        return f"Every {value} {unit}"

    elif schedule.schedule_type == "cron":
        return f"Cron: {schedule.cron_expression}"

    elif schedule.schedule_type == "specific_time":
        time_str = schedule.specific_time or "00:00"
        if schedule.days_of_week:
            day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            days = ", ".join(day_names[d] for d in sorted(schedule.days_of_week))
            return f"At {time_str} on {days}"
        return f"Daily at {time_str}"

    return "Unknown schedule"


@router.get("", response_model=List[ScheduleResponse])
async def list_schedules(
    request: Request,
    script_id: Optional[int] = None,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_auth)
):
    """List all schedules."""
    query = select(Schedule).options(selectinload(Schedule.script))

    if script_id:
        query = query.where(Schedule.script_id == script_id)

    result = await session.execute(query.order_by(Schedule.created_at.desc()))
    schedules = result.scalars().all()

    return [
        ScheduleResponse(
            id=s.id,
            script_id=s.script_id,
            script_name=s.script.name if s.script else None,
            schedule_type=s.schedule_type,
            interval_value=s.interval_value,
            interval_unit=s.interval_unit,
            cron_expression=s.cron_expression,
            specific_time=s.specific_time,
            days_of_week=s.days_of_week,
            enabled=s.enabled,
            next_run=s.next_run,
            created_at=s.created_at,
            human_readable=get_human_readable(s)
        )
        for s in schedules
    ]


@router.post("", response_model=ScheduleResponse)
async def create_schedule(
    data: ScheduleCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_auth)
):
    """Create a new schedule."""
    # Verify script exists
    result = await session.execute(
        select(Script).where(Script.id == data.script_id)
    )
    script = result.scalar_one_or_none()
    if not script:
        raise HTTPException(status_code=404, detail="Script not found")

    # Validate schedule data
    if data.schedule_type == "interval":
        if not data.interval_value or not data.interval_unit:
            raise HTTPException(
                status_code=400,
                detail="Interval schedules require interval_value and interval_unit"
            )
    elif data.schedule_type == "cron":
        if not data.cron_expression:
            raise HTTPException(
                status_code=400,
                detail="Cron schedules require cron_expression"
            )
    elif data.schedule_type == "specific_time":
        if not data.specific_time:
            raise HTTPException(
                status_code=400,
                detail="Specific time schedules require specific_time"
            )

    schedule = Schedule(**data.model_dump())
    session.add(schedule)
    await session.commit()
    await session.refresh(schedule)

    # Add job to scheduler if enabled
    if schedule.enabled:
        await add_job(schedule.id, session)
        await session.refresh(schedule)

    return ScheduleResponse(
        id=schedule.id,
        script_id=schedule.script_id,
        script_name=script.name,
        schedule_type=schedule.schedule_type,
        interval_value=schedule.interval_value,
        interval_unit=schedule.interval_unit,
        cron_expression=schedule.cron_expression,
        specific_time=schedule.specific_time,
        days_of_week=schedule.days_of_week,
        enabled=schedule.enabled,
        next_run=schedule.next_run,
        created_at=schedule.created_at,
        human_readable=get_human_readable(schedule)
    )


@router.get("/{schedule_id}", response_model=ScheduleResponse)
async def get_schedule(
    schedule_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_auth)
):
    """Get a schedule by ID."""
    result = await session.execute(
        select(Schedule)
        .options(selectinload(Schedule.script))
        .where(Schedule.id == schedule_id)
    )
    schedule = result.scalar_one_or_none()

    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    return ScheduleResponse(
        id=schedule.id,
        script_id=schedule.script_id,
        script_name=schedule.script.name if schedule.script else None,
        schedule_type=schedule.schedule_type,
        interval_value=schedule.interval_value,
        interval_unit=schedule.interval_unit,
        cron_expression=schedule.cron_expression,
        specific_time=schedule.specific_time,
        days_of_week=schedule.days_of_week,
        enabled=schedule.enabled,
        next_run=schedule.next_run,
        created_at=schedule.created_at,
        human_readable=get_human_readable(schedule)
    )


@router.put("/{schedule_id}", response_model=ScheduleResponse)
async def update_schedule(
    schedule_id: int,
    data: ScheduleUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_auth)
):
    """Update a schedule."""
    result = await session.execute(
        select(Schedule)
        .options(selectinload(Schedule.script))
        .where(Schedule.id == schedule_id)
    )
    schedule = result.scalar_one_or_none()

    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    # Update fields
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(schedule, key, value)

    await session.commit()

    # Update scheduler job
    if schedule.enabled:
        await add_job(schedule.id, session)
    else:
        await remove_job(schedule.id)

    await session.refresh(schedule)

    return ScheduleResponse(
        id=schedule.id,
        script_id=schedule.script_id,
        script_name=schedule.script.name if schedule.script else None,
        schedule_type=schedule.schedule_type,
        interval_value=schedule.interval_value,
        interval_unit=schedule.interval_unit,
        cron_expression=schedule.cron_expression,
        specific_time=schedule.specific_time,
        days_of_week=schedule.days_of_week,
        enabled=schedule.enabled,
        next_run=schedule.next_run,
        created_at=schedule.created_at,
        human_readable=get_human_readable(schedule)
    )


@router.delete("/{schedule_id}")
async def delete_schedule(
    schedule_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_auth)
):
    """Delete a schedule."""
    result = await session.execute(
        select(Schedule).where(Schedule.id == schedule_id)
    )
    schedule = result.scalar_one_or_none()

    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    # Remove from scheduler
    await remove_job(schedule_id)

    await session.delete(schedule)
    await session.commit()

    return {"message": "Schedule deleted"}


@router.post("/{schedule_id}/toggle")
async def toggle_schedule_endpoint(
    schedule_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_auth)
):
    """Toggle schedule enabled/disabled."""
    result = await session.execute(
        select(Schedule).where(Schedule.id == schedule_id)
    )
    schedule = result.scalar_one_or_none()

    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    new_state = not schedule.enabled
    await toggle_schedule(schedule_id, new_state)

    return {"enabled": new_state}
