"""Structured logging configuration for GridRunner."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import settings


def setup_logging() -> None:
    """Configure the root gridrunner logger with console and file handlers."""
    logger = logging.getLogger("gridrunner")
    logger.setLevel(logging.DEBUG)

    # Don't propagate to root logger
    logger.propagate = False

    # Skip if already configured (e.g. during tests)
    if logger.handlers:
        return

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    # Console handler
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)
    logger.addHandler(console)

    # Rotating file handler
    log_path = settings.data_dir / "logs" / "gridrunner.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=3,
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the gridrunner namespace."""
    return logging.getLogger(f"gridrunner.{name}")
