import logging.handlers
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.logger import build_file_handler, sanitize_for_log


class LoggerTests(unittest.TestCase):
    def test_file_handler_rotates_instead_of_growing_without_bound(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            handler = build_file_handler(
                Path(tmpdir) / "app.log",
                max_bytes=1024,
                backup_count=2,
            )
            try:
                self.assertIsInstance(handler, logging.handlers.RotatingFileHandler)
                self.assertEqual(1024, handler.maxBytes)
                self.assertEqual(2, handler.backupCount)
                self.assertEqual("utf-8", handler.encoding.lower())
            finally:
                handler.close()

    def test_sanitizer_redacts_common_openai_compatible_api_keys(self):
        key = "sk-test-redacted-credential"

        sanitized = sanitize_for_log(f"request failed for api_key={key}")

        self.assertNotIn(key, sanitized)
        self.assertIn("[API_KEY_REDACTED]", sanitized)

    def test_rotation_lock_conflict_falls_back_to_process_log(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            handler = build_file_handler(
                Path(tmpdir) / "app.log",
                max_bytes=1024,
                backup_count=2,
            )
            try:
                with patch.object(
                    logging.handlers.RotatingFileHandler,
                    "doRollover",
                    side_effect=PermissionError("locked"),
                ):
                    handler.doRollover()

                self.assertEqual(
                    f"app.log.{os.getpid()}",
                    Path(handler.baseFilename).name,
                )
                self.assertIsNotNone(handler.stream)
            finally:
                handler.close()


if __name__ == "__main__":
    unittest.main()
