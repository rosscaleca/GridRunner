"""Run history routes."""

from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, delete, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sse_starlette.sse import EventSourceResponse

from ..database import get_session
from ..models import Run, Script
from ..executor import stream_output
from ..config import settings
from .auth import require_auth

router = APIRouter()


class RunResponse(BaseModel):
    id: int
    script_id: int
    script_name: Optional[str] = None
    schedule_id: Optional[int]
    started_at: datetime
    ended_at: Optional[datetime]
    duration: Optional[float]
    exit_code: Optional[int]
    status: str
    trigger_type: str
    stdout: Optional[str] = None
    stderr: Optional[str] = None

    class Config:
        from_attributes = True


class RunListResponse(BaseModel):
    id: int
    script_id: int
    script_name: Optional[str] = None
    started_at: datetime
    ended_at: Optional[datetime]
    duration: Optional[float]
    exit_code: Optional[int]
    status: str
    trigger_type: str

    class Config:
        from_attributes = True


@router.get("", response_model=List[RunListResponse])
async def list_runs(
    request: Request,
    script_id: Optional[int] = None,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_auth)
):
    """List run history with optional filters."""
    query = select(Run).options(selectinload(Run.script))

    if script_id:
        query = query.where(Run.script_id == script_id)
    if status:
        query = query.where(Run.status == status)

    query = query.order_by(Run.started_at.desc()).offset(offset).limit(limit)
    result = await session.execute(query)
    runs = result.scalars().all()

    return [
        RunListResponse(
            id=r.id,
            script_id=r.script_id,
            script_name=r.script.name if r.script else None,
            started_at=r.started_at,
            ended_at=r.ended_at,
            duration=r.duration,
            exit_code=r.exit_code,
            status=r.status,
            trigger_type=r.trigger_type
        )
        for r in runs
    ]


@router.get("/{run_id}", response_model=RunResponse)
async def get_run(
    run_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_auth)
):
    """Get run details with output logs."""
    result = await session.execute(
        select(Run)
        .options(selectinload(Run.script))
        .where(Run.id == run_id)
    )
    run = result.scalar_one_or_none()

    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    return RunResponse(
        id=run.id,
        script_id=run.script_id,
        script_name=run.script.name if run.script else None,
        schedule_id=run.schedule_id,
        started_at=run.started_at,
        ended_at=run.ended_at,
        duration=run.duration,
        exit_code=run.exit_code,
        status=run.status,
        trigger_type=run.trigger_type,
        stdout=run.stdout,
        stderr=run.stderr
    )


@router.get("/{run_id}/stream")
async def stream_run_output(
    run_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_auth)
):
    """Stream live output from a running script via SSE."""
    # Verify run exists
    result = await session.execute(
        select(Run).where(Run.id == run_id)
    )
    run = result.scalar_one_or_none()

    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    async def event_generator():
        async for data in stream_output(run_id):
            import json
            yield {
                "event": "output",
                "data": json.dumps(data)
            }
            if data.get("status") != "running":
                break

    return EventSourceResponse(event_generator())


@router.delete("/{run_id}")
async def delete_run(
    run_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_auth)
):
    """Delete a run record."""
    result = await session.execute(
        select(Run).where(Run.id == run_id)
    )
    run = result.scalar_one_or_none()

    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    if run.status == "running":
        raise HTTPException(status_code=400, detail="Cannot delete a running task")

    await session.delete(run)
    await session.commit()

    return {"message": "Run deleted"}


@router.delete("/cleanup/old")
async def cleanup_old_runs(
    request: Request,
    days: Optional[int] = None,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_auth)
):
    """Clean up runs older than retention period."""
    retention_days = days or settings.log_retention_days
    cutoff = datetime.utcnow() - timedelta(days=retention_days)

    result = await session.execute(
        delete(Run).where(
            and_(
                Run.started_at < cutoff,
                Run.status != "running"
            )
        )
    )
    await session.commit()

    return {"deleted": result.rowcount}


@router.post("/cleanup/excess")
async def cleanup_excess_runs(
    request: Request,
    max_per_script: Optional[int] = None,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_auth)
):
    """Keep only the N most recent runs per script."""
    max_entries = max_per_script or settings.max_log_entries_per_script

    # Get all scripts
    result = await session.execute(select(Script.id))
    script_ids = [row[0] for row in result.fetchall()]

    total_deleted = 0

    for script_id in script_ids:
        # Get runs for this script ordered by date
        result = await session.execute(
            select(Run.id)
            .where(
                and_(
                    Run.script_id == script_id,
                    Run.status != "running"
                )
            )
            .order_by(Run.started_at.desc())
            .offset(max_entries)
        )
        run_ids_to_delete = [row[0] for row in result.fetchall()]

        if run_ids_to_delete:
            await session.execute(
                delete(Run).where(Run.id.in_(run_ids_to_delete))
            )
            total_deleted += len(run_ids_to_delete)

    await session.commit()

    return {"deleted": total_deleted}


@router.get("/{run_id}/download")
async def download_log(
    run_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_auth)
):
    """Download run output as a text file."""
    from fastapi.responses import PlainTextResponse

    result = await session.execute(
        select(Run)
        .options(selectinload(Run.script))
        .where(Run.id == run_id)
    )
    run = result.scalar_one_or_none()

    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    script_name = run.script.name if run.script else f"script_{run.script_id}"
    timestamp = run.started_at.strftime("%Y%m%d_%H%M%S")

    content = f"""GridRunner - Run Log
========================
Script: {script_name}
Run ID: {run.id}
Status: {run.status}
Started: {run.started_at}
Ended: {run.ended_at or 'N/A'}
Duration: {run.duration or 0:.2f}s
Exit Code: {run.exit_code}
Trigger: {run.trigger_type}

--- STDOUT ---
{run.stdout or '(no output)'}

--- STDERR ---
{run.stderr or '(no errors)'}
"""

    return PlainTextResponse(
        content=content,
        headers={
            "Content-Disposition": f"attachment; filename={script_name}_{timestamp}.log"
        }
    )
