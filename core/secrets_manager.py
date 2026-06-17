"""Unified secrets management for API keys.

Priority chain:
  1. Environment variable QUIZ_APP_API_KEY
  2. System keychain (via keyring library)
  3. settings.json (plaintext fallback, warns user)

All code that needs the API key should call SecretsManager.get_key().
"""

from __future__ import annotations

import os
import sys
import threading

KEYRING_AVAILABLE = False
try:
    import keyring
    KEYRING_AVAILABLE = True
except ImportError:
    keyring = None  # type: ignore

from config import SETTINGS_FILE
from utils.json_io import read_json, write_json

_SERVICE_NAME = "course_quiz_studio"
_ACCOUNT_NAME = "ai_api_key"


class SecretsManager:
    """Singleton manager for API key storage and retrieval."""

    _instance: SecretsManager | None = None
    _lock = threading.Lock()

    def __init__(self):
        if SecretsManager._instance is not None:
            raise RuntimeError("Use SecretsManager.instance() instead of direct construction")
        SecretsManager._instance = self

    @classmethod
    def instance(cls) -> SecretsManager:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── Public API ──────────────────────────────────────────

    def get_key(self) -> str:
        """Return the API key using the priority chain. Empty string if none set."""
        # 1. Environment variable
        env_key = os.environ.get("QUIZ_APP_API_KEY", "")
        if env_key:
            return env_key

        # 2. System keychain
        if KEYRING_AVAILABLE:
            try:
                stored = keyring.get_password(_SERVICE_NAME, _ACCOUNT_NAME)
                if stored:
                    return stored
            except Exception:
                pass  # keychain read failed, fall through

        # 3. settings.json (plaintext fallback)
        settings = read_json(SETTINGS_FILE) or {}
        return settings.get("ai_api_key", "")

    def set_key(self, key: str):
        """Store the API key. Prefers keychain; falls back to settings.json with warning."""
        key = key.strip()

        # Always set environment variable for current session
        if key:
            os.environ["QUIZ_APP_API_KEY"] = key
        elif "QUIZ_APP_API_KEY" in os.environ:
            del os.environ["QUIZ_APP_API_KEY"]

        # Try keychain first
        stored_in_keychain = False
        if KEYRING_AVAILABLE:
            try:
                if key:
                    keyring.set_password(_SERVICE_NAME, _ACCOUNT_NAME, key)
                else:
                    try:
                        keyring.delete_password(_SERVICE_NAME, _ACCOUNT_NAME)
                    except Exception:
                        pass
                stored_in_keychain = True
            except Exception:
                pass  # keychain write failed, fall through

        # Fallback: settings.json
        settings = read_json(SETTINGS_FILE) or {}
        if stored_in_keychain:
            # Clear plaintext from settings.json if it was there
            settings.pop("ai_api_key", None)
            settings["ai_api_key_stored_in_plaintext"] = False
        else:
            settings["ai_api_key"] = key
            settings["ai_api_key_stored_in_plaintext"] = True

        write_json(SETTINGS_FILE, settings)

    def is_keychain_available(self) -> bool:
        return KEYRING_AVAILABLE

    def is_plaintext_fallback(self) -> bool:
        """Check if the current key is stored in plaintext settings.json."""
        settings = read_json(SETTINGS_FILE) or {}
        return settings.get("ai_api_key_stored_in_plaintext", False)

    def get_storage_location(self) -> str:
        """Return a human-readable description of where the key is stored."""
        if os.environ.get("QUIZ_APP_API_KEY"):
            return "environment variable"
        if KEYRING_AVAILABLE:
            try:
                if keyring.get_password(_SERVICE_NAME, _ACCOUNT_NAME):
                    return "system keychain"
            except Exception:
                pass
        settings = read_json(SETTINGS_FILE) or {}
        if settings.get("ai_api_key"):
            return "settings.json (⚠ plaintext)"
        return "not set"
