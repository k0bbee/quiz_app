import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import config


class ApplicationMetadataTests(unittest.TestCase):
    def test_registered_name_is_the_canonical_application_name(self):
        self.assertEqual("AI课程刷题软件", config.APP_NAME)
        self.assertEqual(config.APP_NAME, config.APP_NAME_ZH)

    def test_english_name_is_only_a_localized_display_name(self):
        self.assertEqual("AI Course Quiz", config.APP_NAME_EN)

    def test_registered_version_is_explicit(self):
        self.assertEqual("1.0.0", config.APP_VERSION)

    def test_frozen_app_writes_data_beside_the_portable_executable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            executable = Path(tmpdir) / "AI课程刷题软件.exe"
            config_path = Path(config.__file__)
            spec = importlib.util.spec_from_file_location(
                "frozen_config_contract",
                config_path,
            )
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)

            module = importlib.util.module_from_spec(spec)
            with patch.object(sys, "frozen", True, create=True), patch.object(
                sys,
                "executable",
                str(executable),
            ):
                spec.loader.exec_module(module)

            self.assertEqual(str(executable.parent), module.BASE_DIR)
            self.assertEqual(
                str(executable.parent / "data"),
                module.DATA_DIR,
            )


if __name__ == "__main__":
    unittest.main()
