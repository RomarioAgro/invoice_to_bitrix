"""Application logging without secret or document payload filters."""

from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path


def configure_logging(log_dir: Path, level: str, retention_days: int) -> None:
    """Configure UTF-8 console and daily file logging."""

    log_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    file_handler = TimedRotatingFileHandler(
        log_dir / "invoice-bot.log", when="midnight", backupCount=retention_days, encoding="utf-8"
    )
    file_handler.suffix = "%Y-%m-%d"
    file_handler.setFormatter(formatter)
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO), handlers=[file_handler, console])
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
