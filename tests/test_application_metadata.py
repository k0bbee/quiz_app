import unittest

import config


class ApplicationMetadataTests(unittest.TestCase):
    def test_registered_name_is_the_canonical_application_name(self):
        self.assertEqual("AI课程刷题软件", config.APP_NAME)
        self.assertEqual(config.APP_NAME, config.APP_NAME_ZH)

    def test_english_name_is_only_a_localized_display_name(self):
        self.assertEqual("AI Course Quiz", config.APP_NAME_EN)

    def test_registered_version_is_explicit(self):
        self.assertEqual("1.0.0", config.APP_VERSION)


if __name__ == "__main__":
    unittest.main()
