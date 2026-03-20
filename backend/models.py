"""SQLAlchemy database models."""

from datetime import datetime
from typing import Optional, List
from sqlalchemy import (
    String, Integer, Float, Text, Boolean, DateTime, ForeignKey, JSON
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Category(Base):
    """Category for organizing scripts."""
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    color: Mapped[str] = mapped_column(String(7), default="#6366f1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )

    # Relationships
    scripts: Mapped[List["Script"]] = relationship(
        back_populates="category", cascade="all, delete-orphan"
    )


class Script(Base):
    """A script to be managed and scheduled."""
    __tablename__ = "scripts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    script_type: Mapped[str] = mapped_column(
        String(20), default="python"
    )  # python, bash, node, ruby, executable, other
    path: Mapped[str] = mapped_column(String(1000), nullable=False)
    interpreter_path: Mapped[Optional[str]] = mapped_column(
        String(500), default=None
    )  # Custom interpreter override (optional)
    working_directory: Mapped[Optional[str]] = mapped_column(String(1000))
    env_vars: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    args: Mapped[Optional[str]] = mapped_column(Text)
    timeout: Mapped[int] = mapped_column(Integer, default=3600)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    retry_delay: Mapped[int] = mapped_column(Integer, default=60)
    category_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL")
    )
    notification_setting: Mapped[str] = mapped_column(
        String(20), default="on_failure"
    )  # never, on_failure, always
    webhook_url: Mapped[Optional[str]] = mapped_column(String(1000))
    venv_path: Mapped[Optional[str]] = mapped_column(String(1000), default=None)
    interpreter_version: Mapped[Optional[str]] = mapped_column(String(100), default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    category: Mapped[Optional["Category"]] = relationship(
        back_populates="scripts"
    )
    schedules: Mapped[List["Schedule"]] = relationship(
        back_populates="script", cascade="all, delete-orphan"
    )
    runs: Mapped[List["Run"]] = relationship(
        back_populates="script", cascade="all, delete-orphan"
    )

    @property
    def health_score(self) -> float:
        """Calculate health score based on recent runs (0-100)."""
        recent_runs = sorted(self.runs, key=lambda r: r.started_at, reverse=True)[:10]
        if not recent_runs:
            return 100.0
        successful = sum(1 for r in recent_runs if r.status == "success")
        return (successful / len(recent_runs)) * 100


class Schedule(Base):
    """A schedule for running a script."""
    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(primary_key=True)
    script_id: Mapped[int] = mapped_column(
        ForeignKey("scripts.id", ondelete="CASCADE"), nullable=False
    )
    schedule_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # interval, cron, specific_time
    interval_value: Mapped[Optional[int]] = mapped_column(Integer)
    interval_unit: Mapped[Optional[str]] = mapped_column(
        String(20)
    )  # minutes, hours, days
    cron_expression: Mapped[Optional[str]] = mapped_column(String(100))
    specific_time: Mapped[Optional[str]] = mapped_column(
        String(5)
    )  # HH:MM format
    days_of_week: Mapped[Optional[list]] = mapped_column(
        JSON
    )  # [0-6] where 0=Monday
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    next_run: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )

    # Relationships
    script: Mapped["Script"] = relationship(back_populates="schedules")
    runs: Mapped[List["Run"]] = relationship(back_populates="schedule")


class Run(Base):
    """A record of a script execution."""
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    script_id: Mapped[int] = mapped_column(
        ForeignKey("scripts.id", ondelete="CASCADE"), nullable=False
    )
    schedule_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("schedules.id", ondelete="SET NULL")
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    duration: Mapped[Optional[float]] = mapped_column(Float)
    exit_code: Mapped[Optional[int]] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="running"
    )  # running, success, failed, timeout, killed
    stdout: Mapped[Optional[str]] = mapped_column(Text)
    stderr: Mapped[Optional[str]] = mapped_column(Text)
    trigger_type: Mapped[str] = mapped_column(
        String(20), default="manual"
    )  # scheduled, manual

    # Relationships
    script: Mapped["Script"] = relationship(back_populates="runs")
    schedule: Mapped[Optional["Schedule"]] = relationship(back_populates="runs")


class AppSetting(Base):
    """Application settings stored in database."""
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Optional[str]] = mapped_column(Text)
