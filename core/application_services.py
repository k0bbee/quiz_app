"""Default application data services, independent of the Qt window layer."""

from __future__ import annotations

from dataclasses import dataclass

from config import (
    BACKGROUND_TASKS_FILE,
    COURSES_DIR,
    GENERATION_DRAFTS_FILE,
    MASTERY_OVERRIDES_FILE,
    PROGRESS_DIR,
    QUESTIONS_DIR,
    QUESTION_SETS_DIR,
    QUIZ_SNAPSHOTS_DIR,
)
from core.background_task_center import BackgroundTaskCenter
from core.generation_draft_store import GenerationDraftStore
from core.mastery_overrides import MasteryOverrideStore
from core.progress_tracker import ProgressManager
from core.quiz_snapshot_manager import QuizSnapshotManager
from models.course_project import CourseProjectManager
from models.question import QuestionBank
from models.question_set import SetManager


@dataclass(frozen=True)
class ApplicationServices:
    """Long-lived persistence services shared by application screens."""

    question_bank: QuestionBank
    set_manager: SetManager
    progress_manager: ProgressManager
    snapshot_manager: QuizSnapshotManager
    mastery_overrides: MasteryOverrideStore
    course_manager: CourseProjectManager
    task_center: BackgroundTaskCenter
    generation_draft_store: GenerationDraftStore | None = None

    @classmethod
    def default(cls) -> "ApplicationServices":
        """Build services using the configured application data locations."""
        return cls(
            question_bank=QuestionBank(QUESTIONS_DIR),
            set_manager=SetManager(QUESTION_SETS_DIR),
            progress_manager=ProgressManager(PROGRESS_DIR),
            snapshot_manager=QuizSnapshotManager(QUIZ_SNAPSHOTS_DIR),
            mastery_overrides=MasteryOverrideStore(MASTERY_OVERRIDES_FILE),
            course_manager=CourseProjectManager(COURSES_DIR),
            task_center=BackgroundTaskCenter(BACKGROUND_TASKS_FILE),
            generation_draft_store=GenerationDraftStore(
                GENERATION_DRAFTS_FILE
            ),
        )
