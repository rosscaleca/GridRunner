"""Authentication routes."""

import time
from collections import defaultdict
from typing import Optional

import bcrypt
from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_session
from ..models import AppSetting

router = APIRouter()

# In-memory login rate limiter: IP -> list of failed-attempt timestamps
_failed_attempts: dict[str, list[float]] = defaultdict(list)
_RATE_LIMIT_WINDOW = 300  # 5 minutes
_RATE_LIMIT_MAX = 5  # max failed attempts per window


def _check_rate_limit(client_ip: str) -> None:
    """Raise HTTP 429 if the client has exceeded the login failure rate limit."""
    now = time.monotonic()
    # Prune old entries
    _failed_attempts[client_ip] = [
        t for t in _failed_attempts[client_ip] if now - t < _RATE_LIMIT_WINDOW
    ]
    if len(_failed_attempts[client_ip]) >= _RATE_LIMIT_MAX:
        raise HTTPException(
            status_code=429,
            detail="Too many failed login attempts. Try again later.",
        )


def _record_failed_attempt(client_ip: str) -> None:
    """Record a failed login attempt for rate limiting."""
    _failed_attempts[client_ip].append(time.monotonic())


class LoginRequest(BaseModel):
    password: str


class SetupRequest(BaseModel):
    password: str


class AuthStatus(BaseModel):
    authenticated: bool
    needs_setup: bool
    auth_enabled: bool


async def get_password_hash(session: AsyncSession) -> Optional[str]:
    """Get the stored password hash."""
    result = await session.execute(
        select(AppSetting).where(AppSetting.key == "password_hash")
    )
    setting = result.scalar_one_or_none()
    return setting.value if setting else None


async def require_auth(request: Request):
    """Dependency to require authentication."""
    if not settings.auth_enabled:
        return
    if not request.session.get("authenticated"):
        raise HTTPException(status_code=401, detail="Not authenticated")


@router.get("/status", response_model=AuthStatus)
async def auth_status(
    request: Request,
    session: AsyncSession = Depends(get_session)
):
    """Check authentication status."""
    if not settings.auth_enabled:
        return AuthStatus(
            authenticated=True,
            needs_setup=False,
            auth_enabled=False,
        )
    password_hash = await get_password_hash(session)
    return AuthStatus(
        authenticated=request.session.get("authenticated", False),
        needs_setup=password_hash is None,
        auth_enabled=True,
    )


@router.post("/setup")
async def setup_password(
    data: SetupRequest,
    session: AsyncSession = Depends(get_session)
):
    """Set up initial password."""
    # Check if password already exists
    existing = await get_password_hash(session)
    if existing:
        raise HTTPException(status_code=400, detail="Password already configured")

    # Hash password
    password_hash = bcrypt.hashpw(
        data.password.encode("utf-8"),
        bcrypt.gensalt()
    ).decode("utf-8")

    # Store hash
    setting = AppSetting(key="password_hash", value=password_hash)
    session.add(setting)
    await session.commit()

    return {"message": "Password configured successfully"}


@router.post("/login")
async def login(
    data: LoginRequest,
    request: Request,
    session: AsyncSession = Depends(get_session)
):
    """Authenticate with password."""
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(client_ip)

    password_hash = await get_password_hash(session)

    if not password_hash:
        raise HTTPException(status_code=400, detail="Password not configured")

    if bcrypt.checkpw(data.password.encode("utf-8"), password_hash.encode("utf-8")):
        request.session["authenticated"] = True
        return {"message": "Login successful"}

    _record_failed_attempt(client_ip)
    raise HTTPException(status_code=401, detail="Invalid password")


@router.post("/logout")
async def logout(request: Request):
    """Clear session."""
    request.session.clear()
    return {"message": "Logged out"}


@router.post("/change-password")
async def change_password(
    data: SetupRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_auth)
):
    """Change the password."""
    # Hash new password
    password_hash = bcrypt.hashpw(
        data.password.encode("utf-8"),
        bcrypt.gensalt()
    ).decode("utf-8")

    # Update hash
    result = await session.execute(
        select(AppSetting).where(AppSetting.key == "password_hash")
    )
    setting = result.scalar_one_or_none()

    if setting:
        setting.value = password_hash
    else:
        setting = AppSetting(key="password_hash", value=password_hash)
        session.add(setting)

    await session.commit()
    return {"message": "Password changed successfully"}
