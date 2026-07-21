"""Windows DPAPI-backed local secret persistence without extra dependencies."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path

from utils.logger import warning


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


class WindowsDPAPISecretStore:
    """Encrypt one API key for the current Windows user via CryptProtectData."""

    _CRYPTPROTECT_UI_FORBIDDEN = 0x1

    def __init__(self, path: str | Path):
        self.path = Path(path)

    @staticmethod
    def is_available() -> bool:
        return os.name == "nt" and hasattr(ctypes, "WinDLL")

    def get_key(self) -> str:
        if not self.path.exists() or not self.is_available():
            return ""
        try:
            encrypted = self.path.read_bytes()
            if not encrypted:
                return ""
            return self._unprotect(encrypted).decode("utf-8")
        except (OSError, UnicodeError, ValueError) as exc:
            warning(f"Failed to read Windows DPAPI API key: {exc}")
            return ""

    def set_key(self, key: str) -> bool:
        value = str(key or "").strip()
        if not value:
            return self.delete_key()
        if not self.is_available():
            return False
        try:
            encrypted = self._protect(value.encode("utf-8"))
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(f"{self.path.name}.tmp")
            with temporary.open("wb") as stream:
                stream.write(encrypted)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            return True
        except OSError as exc:
            warning(f"Failed to persist Windows DPAPI API key: {exc}")
            return False

    def delete_key(self) -> bool:
        try:
            self.path.unlink(missing_ok=True)
            temporary = self.path.with_name(f"{self.path.name}.tmp")
            temporary.unlink(missing_ok=True)
            return True
        except OSError as exc:
            warning(f"Failed to delete Windows DPAPI API key: {exc}")
            return False

    @classmethod
    def _protect(cls, plaintext: bytes) -> bytes:
        input_blob, input_buffer = cls._make_blob(plaintext)
        output_blob = _DataBlob()
        crypt32, kernel32 = cls._libraries()
        # Keep input_buffer alive until the native call returns.
        _ = input_buffer
        if not crypt32.CryptProtectData(
            ctypes.byref(input_blob),
            "AI课程刷题软件 API Key",
            None,
            None,
            None,
            cls._CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output_blob),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return ctypes.string_at(output_blob.pbData, output_blob.cbData)
        finally:
            kernel32.LocalFree(output_blob.pbData)

    @classmethod
    def _unprotect(cls, encrypted: bytes) -> bytes:
        input_blob, input_buffer = cls._make_blob(encrypted)
        output_blob = _DataBlob()
        crypt32, kernel32 = cls._libraries()
        _ = input_buffer
        if not crypt32.CryptUnprotectData(
            ctypes.byref(input_blob),
            None,
            None,
            None,
            None,
            cls._CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output_blob),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return ctypes.string_at(output_blob.pbData, output_blob.cbData)
        finally:
            kernel32.LocalFree(output_blob.pbData)

    @staticmethod
    def _make_blob(data: bytes) -> tuple[_DataBlob, object]:
        buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        blob = _DataBlob(
            len(data),
            ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)),
        )
        return blob, buffer

    @staticmethod
    def _libraries():
        crypt32 = ctypes.WinDLL("Crypt32.dll", use_last_error=True)
        kernel32 = ctypes.WinDLL("Kernel32.dll", use_last_error=True)
        crypt32.CryptProtectData.argtypes = [
            ctypes.POINTER(_DataBlob),
            wintypes.LPCWSTR,
            ctypes.POINTER(_DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(_DataBlob),
        ]
        crypt32.CryptProtectData.restype = wintypes.BOOL
        crypt32.CryptUnprotectData.argtypes = [
            ctypes.POINTER(_DataBlob),
            ctypes.POINTER(wintypes.LPWSTR),
            ctypes.POINTER(_DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(_DataBlob),
        ]
        crypt32.CryptUnprotectData.restype = wintypes.BOOL
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        return crypt32, kernel32
