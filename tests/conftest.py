"""Shared test fixtures."""

import asyncio
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.models import Script


@pytest_asyncio.fixture
async def db_session():
    """Provide an async SQLAlchemy session backed by an in-memory SQLite DB."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture
def sample_script() -> Script:
    """Return a Script model instance (not persisted)."""
    return Script(
        id=1,
        name="Test Script",
        path="/tmp/test_script.py",
        script_type="python",
        timeout=60,
        retry_count=0,
        retry_delay=10,
    )


@pytest.fixture
def sample_bash_script() -> Script:
    """Return a bash Script model instance."""
    return Script(
        id=2,
        name="Bash Script",
        path="/tmp/test_script.sh",
        script_type="bash",
        timeout=60,
        retry_count=0,
        retry_delay=10,
    )


@pytest.fixture
def sample_python_venv_script(tmp_path) -> Script:
    """Return a Python Script with a mock venv directory structure."""
    venv_dir = tmp_path / "venv"
    bin_dir = venv_dir / "bin"
    bin_dir.mkdir(parents=True)
    python3 = bin_dir / "python3"
    python3.write_text("#!/bin/sh\n")
    python3.chmod(0o755)
    pip = bin_dir / "pip"
    pip.write_text("#!/bin/sh\n")
    pip.chmod(0o755)
    return Script(
        id=3,
        name="Venv Script",
        path="/tmp/test_script.py",
        script_type="python",
        timeout=60,
        retry_count=0,
        retry_delay=10,
        venv_path=str(venv_dir),
    )
