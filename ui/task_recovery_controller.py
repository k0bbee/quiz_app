"""Route persisted background tasks back to their owning workflow."""

from __future__ import annotations

from collections.abc import Callable

from core.background_task_recovery import (
    generation_plan_from_task_metadata,
    task_destination,
    task_retry_assessment,
)


class TaskRecoveryController:
    """Open or safely restore task context without owning any Qt widgets."""

    def __init__(
        self,
        *,
        task_center,
        course_manager,
        current_language: Callable[[], str],
        navigate: Callable[[int], object],
        open_settings: Callable[[str], object],
        course_changed: Callable[[], object],
        get_course_screen: Callable[[], object],
        get_past_exam_screen: Callable[[], object],
        generate_questions: Callable[..., object],
        courses_screen_index: int,
        past_exams_screen_index: int,
        question_bank_screen_index: int,
    ) -> None:
        self.task_center = task_center
        self.course_manager = course_manager
        self._current_language = current_language
        self._navigate = navigate
        self._open_settings = open_settings
        self._course_changed = course_changed
        self._get_course_screen = get_course_screen
        self._get_past_exam_screen = get_past_exam_screen
        self._generate_questions = generate_questions
        self._courses_screen_index = courses_screen_index
        self._past_exams_screen_index = past_exams_screen_index
        self._question_bank_screen_index = question_bank_screen_index

    def open_page(self, task_id: str) -> bool:
        """Navigate to the task owner without restoring persisted inputs."""
        snapshot = self._snapshot(task_id)
        if snapshot is None:
            return False
        destination = task_destination(snapshot.kind)
        metadata = self._metadata(snapshot)
        course_id = self._activate_course(metadata)

        if destination == "settings_data":
            self._open_settings("data")
            return True
        if destination == "generation":
            course = (
                self.course_manager.get(course_id)
                if course_id
                else self.course_manager.current()
            )
            if course is None:
                return self._navigate(self._courses_screen_index) is not False
            return self._generate_questions(
                course_override=course,
                recovery_context=metadata,
                draft_source=str(metadata.get("draft_source", "") or "manual"),
                present_error=False,
            ) is not False
        screens = {
            "courses": self._courses_screen_index,
            "past_exams": self._past_exams_screen_index,
            "question_bank": self._question_bank_screen_index,
        }
        screen = screens.get(destination)
        return screen is not None and self._navigate(screen) is not False

    def retry(self, task_id: str) -> bool:
        """Restore inputs only after the persisted metadata is revalidated."""
        snapshot = self._snapshot(task_id)
        if snapshot is None:
            return False
        assessment = task_retry_assessment(
            snapshot,
            self._current_language(),
        )
        if not assessment.can_retry:
            return False
        return self.restore(task_id, snapshot=snapshot)

    def restore(self, task_id: str, *, snapshot=None) -> bool:
        """Restore safe task inputs without automatically starting the task."""
        snapshot = snapshot or self._snapshot(task_id)
        if snapshot is None:
            return False
        destination = task_destination(snapshot.kind)
        metadata = self._metadata(snapshot)
        course_id = self._activate_course(metadata)

        if destination == "courses":
            if self._navigate(self._courses_screen_index) is False:
                return False
            self._get_course_screen().restore_task_context(snapshot)
            return True
        if destination == "past_exams":
            if self._navigate(self._past_exams_screen_index) is False:
                return False
            self._get_past_exam_screen().restore_task_context(snapshot)
            return True
        if destination == "question_bank":
            return self._navigate(self._question_bank_screen_index) is not False
        if destination == "settings_data":
            self._open_settings("data")
            return True
        if destination == "generation":
            course = (
                self.course_manager.get(course_id)
                if course_id
                else self.course_manager.current()
            )
            if course is None:
                return self._navigate(self._courses_screen_index) is not False
            return self._generate_questions(
                course_override=course,
                initial_plan=generation_plan_from_task_metadata(metadata),
                recovery_context=metadata,
                draft_source=str(metadata.get("draft_source", "") or "manual"),
            ) is not False
        return False

    def _snapshot(self, task_id: str):
        try:
            return self.task_center.get(task_id)
        except (KeyError, OSError, ValueError):
            return None

    @staticmethod
    def _metadata(snapshot) -> dict:
        metadata = getattr(snapshot, "metadata", {}) or {}
        return metadata if isinstance(metadata, dict) else {}

    def _activate_course(self, metadata: dict) -> str:
        course_id = str(metadata.get("course_id", "") or "")
        if (
            course_id
            and self.course_manager.get(course_id) is not None
            and self.course_manager.set_current(course_id)
        ):
            self._course_changed()
        return course_id
