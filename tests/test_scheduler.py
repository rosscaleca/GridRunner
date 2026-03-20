"""Tests for backend.scheduler functions."""

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.memory import MemoryJobStore

from backend.database import Base
from backend.models import Script, Schedule
from backend.scheduler import get_job_id, add_job, remove_job


@pytest_asyncio.fixture
async def db_with_script():
    """Create an in-memory DB with a sample script and return (session, script)."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        script = Script(
            name="Sched Test",
            path="/tmp/sched_test.py",
            script_type="python",
            timeout=60,
            retry_count=0,
            retry_delay=10,
        )
        session.add(script)
        await session.commit()
        await session.refresh(script)
        yield session, script

    await engine.dispose()


# ── get_job_id ──────────────────────────────────────────────────────────────


class TestGetJobId:
    def test_format(self):
        assert get_job_id(42) == "schedule_42"

    def test_different_ids(self):
        assert get_job_id(1) != get_job_id(2)


# ── add_job ─────────────────────────────────────────────────────────────────


class TestAddJob:
    @pytest_asyncio.fixture(autouse=True)
    async def _setup_scheduler(self):
        """Start a fresh scheduler for each test."""
        import backend.scheduler as sched_mod

        self._original = sched_mod.scheduler
        sched_mod.scheduler = AsyncIOScheduler(
            jobstores={"default": MemoryJobStore()},
            job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 60},
        )
        sched_mod.scheduler.start()
        yield
        sched_mod.scheduler.shutdown(wait=False)
        sched_mod.scheduler = self._original

    async def test_interval_schedule(self, db_with_script):
        session, script = db_with_script
        schedule = Schedule(
            script_id=script.id,
            schedule_type="interval",
            interval_value=30,
            interval_unit="minutes",
            enabled=True,
        )
        session.add(schedule)
        await session.commit()
        await session.refresh(schedule)

        result = await add_job(schedule.id, session)
        assert result is True

    async def test_cron_schedule(self, db_with_script):
        session, script = db_with_script
        schedule = Schedule(
            script_id=script.id,
            schedule_type="cron",
            cron_expression="0 2 * * *",
            enabled=True,
        )
        session.add(schedule)
        await session.commit()
        await session.refresh(schedule)

        result = await add_job(schedule.id, session)
        assert result is True

    async def test_specific_time_schedule(self, db_with_script):
        session, script = db_with_script
        schedule = Schedule(
            script_id=script.id,
            schedule_type="specific_time",
            specific_time="14:30",
            enabled=True,
        )
        session.add(schedule)
        await session.commit()
        await session.refresh(schedule)

        result = await add_job(schedule.id, session)
        assert result is True

    async def test_disabled_schedule_returns_false(self, db_with_script):
        session, script = db_with_script
        schedule = Schedule(
            script_id=script.id,
            schedule_type="interval",
            interval_value=10,
            interval_unit="minutes",
            enabled=False,
        )
        session.add(schedule)
        await session.commit()
        await session.refresh(schedule)

        result = await add_job(schedule.id, session)
        assert result is False


# ── remove_job ──────────────────────────────────────────────────────────────


class TestRemoveJob:
    @pytest_asyncio.fixture(autouse=True)
    async def _setup_scheduler(self):
        import backend.scheduler as sched_mod

        self._original = sched_mod.scheduler
        sched_mod.scheduler = AsyncIOScheduler(
            jobstores={"default": MemoryJobStore()},
            job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 60},
        )
        sched_mod.scheduler.start()
        yield
        sched_mod.scheduler.shutdown(wait=False)
        sched_mod.scheduler = self._original

    async def test_remove_existing_job(self, db_with_script):
        session, script = db_with_script
        schedule = Schedule(
            script_id=script.id,
            schedule_type="interval",
            interval_value=5,
            interval_unit="minutes",
            enabled=True,
        )
        session.add(schedule)
        await session.commit()
        await session.refresh(schedule)

        await add_job(schedule.id, session)
        removed = await remove_job(schedule.id)
        assert removed is True

    async def test_remove_nonexistent_job(self):
        removed = await remove_job(99999)
        assert removed is False
