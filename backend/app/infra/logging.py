"""Structured JSON logging with request_id context var + daily rotation.

Configures root logger on import; safe to call multiple times.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.config import get_settings
from app.infra.context import get_request_id

LOG_FORMAT = "%(message)s"
LOGGER_NAME = "aidaily"


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per record with stable field set."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.now(tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": get_request_id(),
        }
        # Optional fields from logger extra={...}
        for key in ("source", "issue_id", "exception_type", "user", "module"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _ensure_log_dir() -> Path:
    log_dir = Path(__file__).resolve().parent.parent.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def configure_logging() -> None:
    """Configure root + app loggers. Idempotent."""
    settings = get_settings()
    root = logging.getLogger()
    # Avoid duplicate handlers on reconfigure.
    if root.handlers and any(
        isinstance(h, logging.StreamHandler) and getattr(h, "_aidaily", False)
        for h in root.handlers
    ):
        return

    formatter = JsonFormatter()

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    stream_handler._aidaily = True  # type: ignore[attr-defined]

    handlers: list[logging.Handler] = [stream_handler]

    # Rotating file handler (10 MB × 5 files).
    try:
        log_path = _ensure_log_dir() / "aidaily.log"
        file_handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler._aidaily = True  # type: ignore[attr-defined]
        handlers.append(file_handler)
    except OSError:
        # File logging unavailable (e.g. read-only fs) — keep stream only.
        pass

    # Reset root handlers and reattach.
    for h in list(root.handlers):
        root.removeHandler(h)
    for h in handlers:
        root.addHandler(h)
    root.setLevel(getattr(logging, settings.log_level.upper() if hasattr(settings, "log_level") else "INFO"))

    # App logger
    app_logger = logging.getLogger(LOGGER_NAME)
    app_logger.setLevel(logging.INFO)


def get_logger(name: str = LOGGER_NAME) -> logging.Logger:
    """Return a logger under the app namespace."""
    configure_logging()
    return logging.getLogger(name)


__all__ = ["configure_logging", "get_logger"]
