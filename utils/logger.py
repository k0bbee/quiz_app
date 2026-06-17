"""Logging utility — writes to data/app.log, never to stdout."""

from __future__ import annotations

import logging
import re
import os

from config import DATA_DIR

_LOG_PATH = os.path.join(DATA_DIR, "app.log")

_logger = None


def _get_logger() -> logging.Logger:
    global _logger
    if _logger is None:
        _logger = logging.getLogger("quiz_app")
        _logger.setLevel(logging.DEBUG)
        # Ensure data directory exists before creating file handler
        os.makedirs(os.path.dirname(_LOG_PATH), exist_ok=True)
        # File handler — never stdout
        fh = logging.FileHandler(_LOG_PATH, encoding="utf-8", mode="a")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        ))
        _logger.addHandler(fh)
    return _logger


def sanitize_for_log(text: str) -> str:
    """Remove common API key patterns from log text."""
    if not text:
        return text
    text = re.sub(r'sk-ant-[a-zA-Z0-9_-]{20,}', '[API_KEY_REDACTED]', text)
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
