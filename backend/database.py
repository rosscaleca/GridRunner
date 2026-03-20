"""Database setup and session management."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from .config import settings


class Base(DeclarativeBase):
    """Base class for all database models."""
    pass


# Create async engine
engine = create_async_engine(
    settings.database_url,
    echo=False,
    future=True,
)

# Create async session factory
async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def migrate_db() -> None:
    """Run lightweight migrations for existing databases."""
    async with engine.connect() as conn:
        result = await conn.execute(text("PRAGMA table_info(scripts)"))
        existing = {row[1] for row in result.fetchall()}
        if "venv_path" not in existing:
            await conn.execute(text("ALTER TABLE scripts ADD COLUMN venv_path VARCHAR(1000)"))
        if "interpreter_version" not in existing:
            await conn.execute(text("ALTER TABLE scripts ADD COLUMN interpreter_version VARCHAR(100)"))
        await conn.commit()


async def init_db() -> None:
    """Initialize the database, creating all tables."""
    settings.ensure_directories()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await migrate_db()


async def get_session() -> AsyncSession:
    """Get a database session for dependency injection."""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
