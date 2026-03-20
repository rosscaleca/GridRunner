"""Configuration management for GridRunner."""

import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings with environment variable support."""

    # Paths
    data_dir: Path = Field(
        default_factory=lambda: Path.home() / ".gridrunner"
    )

    # Timezone
    timezone: str = "America/Los_Angeles"  # Pacific time

    # Server
    host: str = "127.0.0.1"
    port: int = 8420

    # Security
    secret_key: str = Field(
        default="change-me-in-production-use-a-real-secret-key"
    )
    session_expire_hours: int = 24
    auth_enabled: bool = False

    # Database
    @property
    def database_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.data_dir / 'gridrunner.db'}"

    # Logging
    log_retention_days: int = 30
    max_log_entries_per_script: int = 100

    # Execution
    default_timeout: int = 3600  # 1 hour
    max_concurrent_runs: int = 10

    # Notifications
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True

    # Daily digest
    daily_digest_enabled: bool = False
    daily_digest_time: str = "08:00"
    daily_digest_recipients: str = ""  # Comma-separated emails

    class Config:
        env_prefix = "GRIDRUNNER_"
        env_file = ".env"

    def ensure_directories(self) -> None:
        """Create necessary directories if they don't exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "logs").mkdir(exist_ok=True)
        (self.data_dir / "backups").mkdir(exist_ok=True)


# Global settings instance
settings = Settings()


def get_local_now() -> datetime:
    """Get current time in the configured timezone."""
    tz = ZoneInfo(settings.timezone)
    return datetime.now(tz).replace(tzinfo=None)  # Return naive datetime in local time
