"""Logging utility — writes to data/app.log, never to stdout."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import re
import os
from pathlib import Path

from config import DATA_DIR

_LOG_PATH = os.environ.get("QUIZ_APP_LOG_PATH") or os.path.join(DATA_DIR, "app.log")
_MAX_LOG_BYTES = 1 * 1024 * 1024
_LOG_BACKUP_COUNT = 3

_logger = None


class ResilientRotatingFileHandler(RotatingFileHandler):
    """Rotate normally, but tolerate another Windows process holding the file."""

    def doRollover(self) -> None:  # noqa: N802 - logging API name
        try:
            super().doRollover()
        except PermissionError:
            if self.stream:
                self.stream.close()
                self.stream = None
            current = Path(self.baseFilename)
            self.baseFilename = str(
                current.with_name(f"{current.name}.{os.getpid()}")
            )
            if not self.delay:
                self.stream = self._open()


def _get_logger() -> logging.Logger:
    global _logger
    if _logger is None:
        _logger = logging.getLogger("quiz_app")
        _logger.setLevel(logging.DEBUG)
        # Ensure data directory exists before creating file handler
        os.makedirs(os.path.dirname(_LOG_PATH), exist_ok=True)
        # Rotating file handler — never stdout and never grows without bound.
        fh = build_file_handler(_LOG_PATH)
        _logger.addHandler(fh)
    return _logger


def build_file_handler(
    path: str | Path,
    *,
    max_bytes: int = _MAX_LOG_BYTES,
    backup_count: int = _LOG_BACKUP_COUNT,
) -> ResilientRotatingFileHandler:
    """Create the bounded UTF-8 handler used by the application logger."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = ResilientRotatingFileHandler(
        path,
        maxBytes=max(1, int(max_bytes)),
        backupCount=max(1, int(backup_count)),
        encoding="utf-8",
    )
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    return handler


def sanitize_for_log(text: str) -> str:
    """Remove common API key patterns from log text."""
    if not text:
        return text
    text = re.sub(r'sk-ant-[a-zA-Z0-9_-]{20,}', '[API_KEY_REDACTED]', text)
    text = re.sub(r'(?<![a-zA-Z0-9_-])sk-[a-zA-Z0-9_-]{16,}', '[API_KEY_REDACTED]', text)
    text = re.sub(r'Bearer\s+[a-zA-Z0-9_-]{20,}', 'Bearer [API_KEY_REDACTED]', text)
    text = re.sub(r'x-api-key:\s*\S+', 'x-api-key: [REDACTED]', text, flags=re.IGNORECASE)
    return text


def debug(msg: str, *args):
    _get_logger().debug(sanitize_for_log(msg), *args)


def info(msg: str, *args):
    _get_logger().info(sanitize_for_log(msg), *args)


def warning(msg: str, *args):
    _get_logger().warning(sanitize_for_log(msg), *args)


def error(msg: str, *args):
    _get_logger().error(sanitize_for_log(msg), *args)
