"""Default application data services, independent of the Qt window layer."""

from __future__ import annotations

from dataclasses import dataclass

from config import (
    BACKGROUND_TASKS_FILE,
    COURSES_DIR,
    DAILY_STUDY_PLANS_FILE,
    GENERATION_DRAFTS_FILE,
    MASTERY_OVERRIDES_FILE,
    PAST_EXAMS_DIR,
    PROGRESS_DIR,
    QUESTIONS_DIR,
    QUESTION_SETS_DIR,
    QUIZ_SNAPSHOTS_DIR,
)
from core.background_task_center import BackgroundTaskCenter
from core.daily_study_plan_store import DailyStudyPlanStore
from core.generation_draft_store import GenerationDraftStore
from core.mastery_overrides import MasteryOverrideStore
from core.progress_tracker import ProgressManager
from core.quiz_snapshot_manager import QuizSnapshotManager
from models.course_project import CourseProjectManager
from models.past_exam import PastExamManager
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
    past_exam_manager: PastExamManager
    task_center: BackgroundTaskCenter
    daily_plan_store: DailyStudyPlanStore | None = None
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
            past_exam_manager=PastExamManager(PAST_EXAMS_DIR),
            task_center=BackgroundTaskCenter(BACKGROUND_TASKS_FILE),
            daily_plan_store=DailyStudyPlanStore(DAILY_STUDY_PLANS_FILE),
            generation_draft_store=GenerationDraftStore(
                GENERATION_DRAFTS_FILE
            ),
        )
