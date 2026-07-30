"""Coordinate the first-run course-to-practice flow outside MainWindow."""

from __future__ import annotations

from PyQt6.QtWidgets import QFileDialog

from ai.course_summary_factory import provider_requires_api_key
from ai.settings_validation import ai_generation_settings_error
from core.first_run_flow import build_first_run_exam_plan, resolve_first_run_state
from core.study_intent import StudyAction, StudyIntent


class FirstRunController:
    """Own onboarding state, imports, generation review and first practice."""

    def __init__(self, host) -> None:
        self._host = host

    def settings_saved(self) -> None:
        host = self._host
        if (
            host._last_generation_launch_error
            and host._first_run_error == host._last_generation_launch_error
        ):
            host._first_run_error = ""
        host._last_generation_launch_error = ""
        self.refresh()

    def ai_error(self) -> str:
        host = self._host
        settings = host.settings_screen.settings_snapshot()
        api_key = ""
        if provider_requires_api_key(settings):
            from core.secrets_manager import SecretsManager

            api_key = SecretsManager.instance().get_key()
        return ai_generation_settings_error(settings, api_key)

    def practice_candidates(self):
        host = self._host
        course_id = host._current_course_id()
        if not course_id:
            return []
        candidates = []
        for question_set in host.set_manager.load_all():
            set_course_id = str(
                (getattr(question_set, "metadata", {}) or {}).get(
                    "course_id",
                    "",
                )
                or ""
            )
            if set_course_id and set_course_id != course_id:
                continue
            question_ids = [
                question.question_id
                for question in host.question_bank.get_many(
                    question_set.questions,
                    course_id=course_id,
                )
            ]
            if question_ids:
                candidates.append((question_set, question_ids))
        return candidates

    def question_count(self) -> int:
        return sum(
            len(question_ids)
            for _question_set, question_ids in self.practice_candidates()
        )

    def has_completed_practice(self) -> bool:
        return any(
            getattr(record, "status", "") == "completed"
            for record in self._host.progress_manager.load_all()
        )

    def required(self) -> bool:
        host = self._host
        if host._first_run_operation:
            return True
        if not host._current_course_id():
            return True
        if self.question_count() <= 0:
            return True
        return not self.has_completed_practice()

    def archived_course_count(self) -> int:
        return sum(
            1
            for course in self._host.course_manager.load_all(
                include_archived=True
            )
            if getattr(course, "is_archived", False)
        )

    def open_archived_courses(self) -> None:
        host = self._host
        host._get_course_screen().show_archived_courses()
        host.navigate_to(
            host.SCREEN_COURSES,
            allow_first_run_redirect=False,
        )

    def refresh(self) -> None:
        host = self._host
        if not hasattr(host, "first_run_screen"):
            return
        progress = host._first_run_progress
        course_id = host._current_course_id()
        has_course = bool(course_id)
        question_count = self.question_count()
        generation_draft = host.generation_flow.draft(course_id)
        first_run_required = (
            bool(host._first_run_operation)
            or not has_course
            or question_count <= 0
            or not self.has_completed_practice()
        )
        state = resolve_first_run_state(
            ai_error=host._first_run_ai_error(),
            has_course=has_course,
            question_count=question_count,
            operation=host._first_run_operation,
            error=host._first_run_error,
            progress_text=str(getattr(progress, "detail", "") or ""),
            progress_current=int(getattr(progress, "current", 0) or 0),
            progress_total=int(getattr(progress, "total", 0) or 0),
            draft_question_count=(
                len(generation_draft.questions)
                if generation_draft is not None
                else 0
            ),
            archived_course_count=self.archived_course_count(),
        )
        host.first_run_screen.set_state(state)
        host.home_workspace.setCurrentWidget(
            host.first_run_screen if first_run_required else host.home_screen
        )

    def choose_materials(self) -> None:
        host = self._host
        folder = QFileDialog.getExistingDirectory(
            host,
            host.lang_manager.get_text(
                "选择课程资料文件夹",
                "Choose Course Materials Folder",
            ),
        )
        if not folder:
            return
        course_screen = host._get_course_screen()
        host._first_run_operation = "importing"
        host._first_run_error = ""
        host._first_run_progress = None
        self.refresh()
        if not course_screen.start_import(folder, "", present_result=False):
            host._first_run_operation = ""
            host._first_run_error = host.lang_manager.get_text(
                "课程导入任务未能启动，请检查当前后台任务。",
                "The course import could not start. Check the current background task.",
            )
            self.refresh()

    def import_started(self) -> None:
        host = self._host
        host._first_run_operation = "importing"
        host._first_run_error = ""
        host._first_run_progress = None
        self.refresh()

    def import_progress(self, progress) -> None:
        self._host._first_run_progress = progress
        self.refresh()

    def import_completed(self, _project) -> None:
        host = self._host
        host._first_run_operation = ""
        host._first_run_error = ""
        host._first_run_progress = None
        self.refresh()

    def import_failed(self, message: str) -> None:
        host = self._host
        host._first_run_operation = ""
        host._first_run_error = str(message or "")
        host._first_run_progress = None
        self.refresh()

    def import_cancelled(self) -> None:
        host = self._host
        host._first_run_operation = ""
        host._first_run_error = host.lang_manager.get_text(
            "课程导入已停止，未完成内容没有保存。",
            "Course import stopped; incomplete content was not saved.",
        )
        host._first_run_progress = None
        self.refresh()

    def generate(self) -> None:
        host = self._host
        course_project = host.course_manager.current()
        if course_project is None:
            host._first_run_error = host.lang_manager.get_text(
                "当前课程已不存在，请重新导入课程资料。",
                "The current course no longer exists. Import the materials again.",
            )
            self.refresh()
            return
        try:
            plan = build_first_run_exam_plan(course_project)
        except ValueError:
            host._first_run_error = host.lang_manager.get_text(
                "课程中没有可用于出题的知识点，请重新解析课程资料。",
                "The course has no topics available for generation. "
                "Parse the materials again.",
            )
            self.refresh()
            return
        title = host.lang_manager.get_text(
            f"{course_project.title}快速复习",
            f"{course_project.title} Quick Review",
        )
        host._first_run_operation = "generating"
        host._first_run_error = ""
        self.refresh()
        configured = host.generation_flow.configure(
            course_override=course_project,
            initial_plan=plan,
            review_warnings_only=True,
            question_set_title=title,
            draft_source="first_run",
            present_error=False,
        )
        if configured is None:
            host._first_run_operation = ""
            host._first_run_error = host._last_generation_launch_error
            self.refresh()
            return
        dialog, course_project, restored_draft, draft_source = configured
        dialog.accepted.connect(
            lambda: self.generation_accepted(
                dialog,
                course_project,
                draft_source,
            )
        )
        dialog.rejected.connect(
            lambda: self.generation_rejected(
                dialog,
                course_project,
                draft_source,
            )
        )
        host.first_run_screen.show_generation_widget(dialog)
        if not restored_draft:
            dialog.start_generation_when_shown()

    def generation_accepted(
        self,
        dialog,
        course_project,
        draft_source: str,
    ) -> None:
        host = self._host
        host.generation_flow.sync_draft(
            dialog,
            course_project,
            source=draft_source,
        )
        saved = host.generation_flow.save(
            dialog,
            course_project,
            start_after_save=True,
            present_error=False,
        )
        if not saved:
            host.first_run_screen.show_generation_widget(dialog)
            return
        host.first_run_screen.clear_generation_widget(dialog)
        dialog.deleteLater()
        host._first_run_operation = ""
        host._first_run_progress = None
        self.refresh()

    def generation_rejected(
        self,
        dialog,
        course_project,
        draft_source: str,
    ) -> None:
        host = self._host
        host.generation_flow.sync_draft(
            dialog,
            course_project,
            source=draft_source,
        )
        host.first_run_screen.clear_generation_widget(dialog)
        dialog.deleteLater()
        host._first_run_operation = ""
        host._first_run_progress = None
        self.refresh()

    def start(self) -> None:
        host = self._host
        candidates = self.practice_candidates()
        if not candidates:
            host._first_run_error = host.lang_manager.get_text(
                "尚未找到可开始的题目集，请先生成快速复习题。",
                "No ready question set was found. Generate quick-review questions first.",
            )
            self.refresh()
            return
        question_set, question_ids = candidates[0]
        host._on_study_quiz_start(
            StudyIntent(
                course_id=host._current_course_id(),
                action=StudyAction.CUSTOM_PRACTICE,
                set_id=question_set.set_id,
                question_ids=tuple(question_ids),
                question_count=len(question_ids),
                submission_mode="practice",
                source="first_run_ready",
            ),
            question_ids,
        )

    def cancel(self) -> None:
        course_screen = getattr(self._host, "_course_screen", None)
        if course_screen is not None:
            course_screen.cancel_active_task()
