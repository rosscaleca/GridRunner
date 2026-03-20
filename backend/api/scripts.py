"""Script CRUD routes."""

from datetime import datetime
from typing import Optional, List
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_session
from ..models import Script, Category, Run
from ..executor import execute_script, kill_script, running_processes, validate_script as validate_script_config
from ..runtimes import get_interpreter_version
from .auth import require_auth

router = APIRouter()


class ScriptCreate(BaseModel):
    name: str
    description: Optional[str] = None
    script_type: str = "python"  # python, bash, node, ruby, go, r, julia, swift, deno, lua, java, executable, other
    path: str
    interpreter_path: Optional[str] = None  # Custom interpreter override (optional)
    working_directory: Optional[str] = None
    env_vars: Optional[dict] = None
    args: Optional[str] = None
    timeout: int = 3600
    retry_count: int = 0
    retry_delay: int = 60
    category_id: Optional[int] = None
    notification_setting: str = "on_failure"
    webhook_url: Optional[str] = None
    venv_path: Optional[str] = None
    interpreter_version: Optional[str] = None


class ScriptUpdate(ScriptCreate):
    pass


class ScriptResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    script_type: str
    path: str
    interpreter_path: Optional[str]
    working_directory: Optional[str]
    env_vars: Optional[dict]
    args: Optional[str]
    timeout: int
    retry_count: int
    retry_delay: int
    category_id: Optional[int]
    category_name: Optional[str] = None
    notification_setting: str
    webhook_url: Optional[str]
    venv_path: Optional[str] = None
    interpreter_version: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    health_score: float = 100.0
    is_running: bool = False
    last_run_status: Optional[str] = None
    last_run_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CategoryCreate(BaseModel):
    name: str
    color: str = "#6366f1"


class CategoryResponse(BaseModel):
    id: int
    name: str
    color: str
    script_count: int = 0

    class Config:
        from_attributes = True


@router.get("", response_model=List[ScriptResponse])
async def list_scripts(
    request: Request,
    category_id: Optional[int] = None,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_auth)
):
    """List all scripts."""
    query = select(Script).options(selectinload(Script.category), selectinload(Script.runs))

    if category_id:
        query = query.where(Script.category_id == category_id)

    result = await session.execute(query.order_by(Script.name))
    scripts = result.scalars().all()

    responses = []
    for script in scripts:
        # Get last run
        last_run = None
        if script.runs:
            last_run = max(script.runs, key=lambda r: r.started_at)

        # Check if running
        is_running = any(
            r.id in running_processes for r in script.runs if r.status == "running"
        )

        responses.append(ScriptResponse(
            id=script.id,
            name=script.name,
            description=script.description,
            script_type=script.script_type,
            path=script.path,
            interpreter_path=script.interpreter_path,
            working_directory=script.working_directory,
            env_vars=script.env_vars,
            args=script.args,
            timeout=script.timeout,
            retry_count=script.retry_count,
            retry_delay=script.retry_delay,
            category_id=script.category_id,
            category_name=script.category.name if script.category else None,
            notification_setting=script.notification_setting,
            webhook_url=script.webhook_url,
            venv_path=script.venv_path,
            interpreter_version=script.interpreter_version,
            created_at=script.created_at,
            updated_at=script.updated_at,
            health_score=script.health_score,
            is_running=is_running,
            last_run_status=last_run.status if last_run else None,
            last_run_at=last_run.started_at if last_run else None,
        ))

    return responses


@router.post("", response_model=ScriptResponse)
async def create_script(
    data: ScriptCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_auth)
):
    """Create a new script."""
    script_data = data.model_dump()

    # Auto-detect interpreter version if not provided
    if not script_data.get("interpreter_version"):
        binary = script_data.get("interpreter_path")
        st = script_data.get("script_type", "python")
        if binary:
            version = await get_interpreter_version(binary, st)
            if version:
                script_data["interpreter_version"] = f"{st.capitalize()} {version}"

    script = Script(**script_data)
    session.add(script)
    await session.commit()
    await session.refresh(script)

    return ScriptResponse(
        id=script.id,
        name=script.name,
        description=script.description,
        script_type=script.script_type,
        path=script.path,
        interpreter_path=script.interpreter_path,
        working_directory=script.working_directory,
        env_vars=script.env_vars,
        args=script.args,
        timeout=script.timeout,
        retry_count=script.retry_count,
        retry_delay=script.retry_delay,
        category_id=script.category_id,
        notification_setting=script.notification_setting,
        webhook_url=script.webhook_url,
        venv_path=script.venv_path,
        interpreter_version=script.interpreter_version,
        created_at=script.created_at,
        updated_at=script.updated_at,
    )


@router.get("/{script_id}", response_model=ScriptResponse)
async def get_script(
    script_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_auth)
):
    """Get a script by ID."""
    result = await session.execute(
        select(Script)
        .options(selectinload(Script.category), selectinload(Script.runs))
        .where(Script.id == script_id)
    )
    script = result.scalar_one_or_none()

    if not script:
        raise HTTPException(status_code=404, detail="Script not found")

    last_run = None
    if script.runs:
        last_run = max(script.runs, key=lambda r: r.started_at)

    return ScriptResponse(
        id=script.id,
        name=script.name,
        description=script.description,
        script_type=script.script_type,
        path=script.path,
        interpreter_path=script.interpreter_path,
        working_directory=script.working_directory,
        env_vars=script.env_vars,
        args=script.args,
        timeout=script.timeout,
        retry_count=script.retry_count,
        retry_delay=script.retry_delay,
        category_id=script.category_id,
        category_name=script.category.name if script.category else None,
        notification_setting=script.notification_setting,
        webhook_url=script.webhook_url,
        venv_path=script.venv_path,
        interpreter_version=script.interpreter_version,
        created_at=script.created_at,
        updated_at=script.updated_at,
        health_score=script.health_score,
        last_run_status=last_run.status if last_run else None,
        last_run_at=last_run.started_at if last_run else None,
    )


@router.put("/{script_id}", response_model=ScriptResponse)
async def update_script(
    script_id: int,
    data: ScriptUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_auth)
):
    """Update a script."""
    result = await session.execute(
        select(Script).where(Script.id == script_id)
    )
    script = result.scalar_one_or_none()

    if not script:
        raise HTTPException(status_code=404, detail="Script not found")

    update_data = data.model_dump()

    # Auto-detect interpreter version if interpreter changed and version not explicitly set
    if not update_data.get("interpreter_version"):
        binary = update_data.get("interpreter_path")
        st = update_data.get("script_type", script.script_type)
        if binary:
            version = await get_interpreter_version(binary, st)
            if version:
                update_data["interpreter_version"] = f"{st.capitalize()} {version}"

    for key, value in update_data.items():
        setattr(script, key, value)

    script.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(script)

    return ScriptResponse(
        id=script.id,
        name=script.name,
        description=script.description,
        script_type=script.script_type,
        path=script.path,
        interpreter_path=script.interpreter_path,
        working_directory=script.working_directory,
        env_vars=script.env_vars,
        args=script.args,
        timeout=script.timeout,
        retry_count=script.retry_count,
        retry_delay=script.retry_delay,
        category_id=script.category_id,
        notification_setting=script.notification_setting,
        webhook_url=script.webhook_url,
        venv_path=script.venv_path,
        interpreter_version=script.interpreter_version,
        created_at=script.created_at,
        updated_at=script.updated_at,
    )


@router.delete("/{script_id}")
async def delete_script(
    script_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_auth)
):
    """Delete a script."""
    result = await session.execute(
        select(Script).where(Script.id == script_id)
    )
    script = result.scalar_one_or_none()

    if not script:
        raise HTTPException(status_code=404, detail="Script not found")

    await session.delete(script)
    await session.commit()

    return {"message": "Script deleted"}


@router.post("/{script_id}/run")
async def run_script(
    script_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_auth)
):
    """Trigger a manual script run."""
    result = await session.execute(
        select(Script).where(Script.id == script_id)
    )
    script = result.scalar_one_or_none()

    if not script:
        raise HTTPException(status_code=404, detail="Script not found")

    run_id = await execute_script(script_id, trigger_type="manual")
    return {"message": "Script started", "run_id": run_id}


@router.post("/{script_id}/kill")
async def kill_running_script(
    script_id: int,
    run_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_auth)
):
    """Kill a running script."""
    # Validate run exists and belongs to this script
    result = await session.execute(
        select(Run).where(Run.id == run_id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.script_id != script_id:
        raise HTTPException(status_code=400, detail="Run does not belong to this script")

    success = await kill_script(run_id)
    if success:
        return {"message": "Script killed"}
    raise HTTPException(status_code=404, detail="No running process found")


@router.get("/{script_id}/health")
async def get_health(
    script_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_auth)
):
    """Get script health score."""
    result = await session.execute(
        select(Script)
        .options(selectinload(Script.runs))
        .where(Script.id == script_id)
    )
    script = result.scalar_one_or_none()

    if not script:
        raise HTTPException(status_code=404, detail="Script not found")

    return {"health_score": script.health_score}


@router.get("/{script_id}/validate")
async def validate_script_endpoint(
    script_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_auth)
):
    """Validate script file and interpreter exist."""
    result = await session.execute(
        select(Script).where(Script.id == script_id)
    )
    script = result.scalar_one_or_none()

    if not script:
        raise HTTPException(status_code=404, detail="Script not found")

    # Use the centralized validation function
    issues = validate_script_config(script)

    return {
        "valid": len(issues) == 0,
        "issues": issues
    }


# Category endpoints
@router.get("/categories/", response_model=List[CategoryResponse])
async def list_categories(
    request: Request,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_auth)
):
    """List all categories."""
    result = await session.execute(
        select(Category).options(selectinload(Category.scripts))
    )
    categories = result.scalars().all()

    return [
        CategoryResponse(
            id=cat.id,
            name=cat.name,
            color=cat.color,
            script_count=len(cat.scripts)
        )
        for cat in categories
    ]


@router.post("/categories/", response_model=CategoryResponse)
async def create_category(
    data: CategoryCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_auth)
):
    """Create a new category."""
    category = Category(**data.model_dump())
    session.add(category)
    await session.commit()
    await session.refresh(category)

    return CategoryResponse(
        id=category.id,
        name=category.name,
        color=category.color,
        script_count=0
    )


@router.delete("/categories/{category_id}")
async def delete_category(
    category_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_auth)
):
    """Delete a category."""
    result = await session.execute(
        select(Category).where(Category.id == category_id)
    )
    category = result.scalar_one_or_none()

    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    await session.delete(category)
    await session.commit()

    return {"message": "Category deleted"}
