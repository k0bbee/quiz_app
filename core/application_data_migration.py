"""Application-level compatibility migrations run before mutable UI workflows."""

from __future__ import annotations

from dataclasses import dataclass

from core.progress_archive import ProgressArchiveMigrator


@dataclass(frozen=True)
class StartupDataMigrationReport:
    """Compact startup summary suitable for UI presentation and diagnostics."""

    scanned: int = 0
    changed: int = 0
    complete: int = 0
    incomplete: int = 0
    failed_progress_ids: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def has_failures(self) -> bool:
        return bool(self.errors)


class ApplicationDataMigrator:
    """Protect legacy completed sessions before users can mutate live assets."""

    def __init__(self, services):
        self.services = services

    def migrate(self) -> StartupDataMigrationReport:
        migrator = ProgressArchiveMigrator(
            progress_manager=self.services.progress_manager,
            question_bank=self.services.question_bank,
            set_manager=self.services.set_manager,
            course_manager=self.services.course_manager,
        )
        try:
            outcomes = migrator.migrate_all()
        except Exception as exc:
            return StartupDataMigrationReport(
                failed_progress_ids=("startup",),
                errors=(f"Startup progress migration failed: {exc}",),
            )

        failed = tuple(
            outcome.progress_id for outcome in outcomes if outcome.error
        )
        errors = tuple(
            f"{outcome.progress_id}: {outcome.error}"
            for outcome in outcomes
            if outcome.error
        )
        successful = tuple(outcome for outcome in outcomes if not outcome.error)
        return StartupDataMigrationReport(
            scanned=len(outcomes),
            changed=sum(1 for outcome in successful if outcome.changed),
            complete=sum(
                1 for outcome in successful if outcome.status == "complete"
            ),
            incomplete=sum(
                1 for outcome in successful if outcome.status == "incomplete"
            ),
            failed_progress_ids=failed,
            errors=errors,
        )
