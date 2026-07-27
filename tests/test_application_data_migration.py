import types
import unittest
from unittest.mock import patch

from core.progress_archive import ProgressArchiveMigrationResult


class ApplicationDataMigrationTests(unittest.TestCase):
    def test_startup_migration_aggregates_archive_outcomes(self):
        from core.application_data_migration import ApplicationDataMigrator

        services = types.SimpleNamespace(
            progress_manager=object(),
            question_bank=object(),
            set_manager=object(),
            course_manager=object(),
        )
        outcomes = (
            ProgressArchiveMigrationResult("migrated", "complete", True),
            ProgressArchiveMigrationResult(
                "partial",
                "incomplete",
                True,
                ("question:q-lost",),
            ),
            ProgressArchiveMigrationResult("current", "complete", False),
            ProgressArchiveMigrationResult(
                "failed",
                "legacy",
                False,
                error="disk unavailable",
            ),
        )

        with patch(
            "core.application_data_migration.ProgressArchiveMigrator"
        ) as migrator_type:
            migrator_type.return_value.migrate_all.return_value = outcomes
            report = ApplicationDataMigrator(services).migrate()

        migrator_type.assert_called_once_with(
            progress_manager=services.progress_manager,
            question_bank=services.question_bank,
            set_manager=services.set_manager,
            course_manager=services.course_manager,
        )
        self.assertEqual(4, report.scanned)
        self.assertEqual(2, report.changed)
        self.assertEqual(2, report.complete)
        self.assertEqual(1, report.incomplete)
        self.assertEqual(("failed",), report.failed_progress_ids)
        self.assertTrue(report.has_failures)

    def test_startup_migration_converts_unexpected_failure_to_report(self):
        from core.application_data_migration import ApplicationDataMigrator

        services = types.SimpleNamespace(
            progress_manager=object(),
            question_bank=object(),
            set_manager=object(),
            course_manager=object(),
        )
        with patch(
            "core.application_data_migration.ProgressArchiveMigrator"
        ) as migrator_type:
            migrator_type.return_value.migrate_all.side_effect = OSError(
                "progress directory unavailable"
            )
            report = ApplicationDataMigrator(services).migrate()

        self.assertEqual(0, report.scanned)
        self.assertTrue(report.has_failures)
        self.assertIn("progress directory unavailable", report.errors[0])

if __name__ == "__main__":
    unittest.main()
