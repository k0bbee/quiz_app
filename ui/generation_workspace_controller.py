"""Own the course generation workspace flow outside :mod:`ui.main_window`."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Callable

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QMessageBox, QWidget

from ai.course_summary_factory import provider_requires_api_key
from ai.settings_validation import ai_generation_settings_error
from core.question_set_builder import build_ai_question_set
from core.question_set_regenerator import persist_new_question_set
from core.past_exam_prediction import prediction_prefill_status
from core.study_intent import StudyAction, StudyIntent
from ui.generation_launch_controller import (
    GenerationLaunchController,
    generation_launch_copy,
)
from utils.logger import warning as log_warning


def find_generation_gap_topic_ids(course_project, question_bank) -> tuple[str, ...] | None:
    """Return exam-scope topics with no indexed questions.

    ``None`` means coverage could not be read and the dialog should keep its
    manual topic selection. An empty tuple is a valid, complete scope.
    """
    if course_project is None or question_bank is None:
        return None
    try:
        topic_index = question_bank.topic_index(
            course_id=str(getattr(course_project, "course_id", "") or "").strip()
        )
    except Exception:
        return None
    if not isinstance(topic_index, Mapping):
        return None
    covered = {
        str(row[0] or "").strip()
        for row in topic_index.values()
        if isinstance(row, (tuple, list)) and row and str(row[0] or "").strip()
    }
    scope = getattr(course_project, "exam_topics", None)
    topics = list(scope() if callable(scope) else getattr(course_project, "topics", ()) or ())
    return tuple(
        topic_id
        for topic in topics
        if (topic_id := str(getattr(topic, "topic_id", topic) or "").strip())
        and topic_id not in covered
    )


class GenerationWorkspaceController:
    """Coordinate validation, drafts, review and saving for one host window.

    The host deliberately provides application-wide services and route actions.
    This keeps the generation lifecycle cohesive without turning the controller
    into another service locator or exposing it to individual screens.
    """

    def __init__(
        self,
        host,
        *,
        workspace_provider: Callable[[], object] | None = None,
    ) -> None:
        self._host = host
        self._workspace_provider = workspace_provider

    def _workspace(self):
        if self._workspace_provider is not None:
            return self._workspace_provider()
        return getattr(self._host, "_generation_workspace", None)

    def prepare(
        self,
        *,
        course_override=None,
        material_pack=None,
        purpose: str = "create",
        allow_review_without_ai: bool = False,
        present_error: bool = True,
    ):
        """Prepare one validated generation dialog for create or regenerate."""
        host = self._host
        gm = host.lang_manager.get_text
        controller = GenerationLaunchController(
            settings_provider=host.settings_screen.settings_snapshot,
            course_context_provider=host.course_context.generation_context,
            task_center=getattr(host, "task_center", None),
            api_key_required=provider_requires_api_key,
            settings_validator=ai_generation_settings_error,
        )
        preparation = controller.prepare(
            host,
            course_override=course_override,
            material_pack=material_pack,
            allow_review_without_ai=allow_review_without_ai,
        )
        if preparation.ok:
            host._last_generation_launch_error = ""
            gap_topic_ids = find_generation_gap_topic_ids(
                preparation.course_project,
                getattr(host, "question_bank", None),
            )
            set_gap_topics = getattr(preparation.dialog, "set_generation_gap_topics", None)
            if gap_topic_ids is not None and callable(set_gap_topics):
                set_gap_topics(gap_topic_ids)
            return preparation
        copy = generation_launch_copy(preparation.issue, purpose=purpose)
        detail = preparation.message or gm(copy.detail_zh, copy.detail_en)
        host._last_generation_launch_error = detail
        if present_error:
            QMessageBox.warning(host, gm(copy.title_zh, copy.title_en), detail)
        return None

    def open(
        self,
        *,
        course_override=None,
        initial_plan=None,
        prediction=None,
        material_pack=None,
        recovery_context=None,
        auto_start: bool = False,
        start_after_save: bool = False,
        review_warnings_only: bool = False,
        question_set_title: str = "",
        draft_source: str = "manual",
        draft_id: str = "",
        present_error: bool = True,
    ) -> bool:
        """Open or resume AI generation in the persistent course workspace."""
        host = self._host
        existing_workspace = getattr(host, "_generation_workspace", None)
        if (
            existing_workspace is not None
            and existing_workspace.generation_widget() is not None
        ):
            requested_course_id = self._requested_course_id(course_override)
            active_widget = existing_workspace.generation_widget()
            existing_course_id = str(
                getattr(existing_workspace, "course_id", "") or ""
            ).strip()
            active_draft_id = str(
                getattr(active_widget, "_generation_draft_id", "") or ""
            ).strip()
            active_source = str(
                getattr(active_widget, "_draft_source", "") or ""
            ).strip()
            requested_draft_id = str(draft_id or "").strip()
            existing_session_course = ""
            session_course_id = getattr(
                existing_workspace,
                "session_course_id",
                None,
            )
            if requested_draft_id and callable(session_course_id):
                existing_session_course = str(
                    session_course_id(requested_draft_id) or ""
                ).strip()
            select_session = getattr(existing_workspace, "select_session", None)
            if (
                requested_draft_id
                and existing_session_course
                and (
                    not requested_course_id
                    or requested_course_id == existing_session_course
                )
                and callable(select_session)
                and select_session(requested_draft_id)
            ):
                host.navigate_to(
                    host.SCREEN_GENERATION,
                    allow_first_run_redirect=False,
                )
                return True
            new_session_request = (
                initial_plan is not None
                or prediction is not None
                or material_pack is not None
                or bool(recovery_context)
                or bool(str(question_set_title or "").strip())
            )
            same_course = (
                not requested_course_id
                or not existing_course_id
                or requested_course_id == existing_course_id
            )
            same_session = (
                same_course
                and requested_draft_id
                and requested_draft_id == active_draft_id
            ) or (
                not requested_draft_id
                and not new_session_request
                and same_course
                and (not active_source or active_source == draft_source)
            )
            if same_session:
                host.navigate_to(
                    host.SCREEN_GENERATION,
                    allow_first_run_redirect=False,
                )
                return True
        configured = self.configure(
            course_override=course_override,
            initial_plan=initial_plan,
            prediction=prediction,
            material_pack=material_pack,
            recovery_context=recovery_context,
            review_warnings_only=review_warnings_only,
            question_set_title=question_set_title,
            draft_source=draft_source,
            draft_id=draft_id,
            present_error=present_error,
        )
        if configured is None:
            return False
        dialog, course_project, restored_draft, draft_source = configured
        if start_after_save:
            set_publish_destination = getattr(dialog, "set_publish_destination", None)
            if callable(set_publish_destination):
                set_publish_destination("practice_now")
        dialog.accepted.connect(
            lambda: self.accept(
                dialog,
                course_project,
                draft_source=draft_source,
                material_pack=material_pack,
                start_after_save=start_after_save,
            )
        )
        dialog.rejected.connect(
            lambda: self.reject(
                dialog,
                course_project,
                draft_source=draft_source,
                material_pack=material_pack,
            )
        )
        workspace = self._workspace()
        workspace.show_generation_widget(
            dialog,
            course_id=str(getattr(course_project, "course_id", "") or ""),
            course_title=str(getattr(course_project, "title", "") or ""),
            draft_id=str(getattr(dialog, "_generation_draft_id", "") or ""),
        )
        host.navigate_to(
            host.SCREEN_GENERATION,
            allow_first_run_redirect=False,
        )
        if auto_start and not restored_draft:
            dialog.start_generation_when_shown()
        return True

    def _requested_course_id(self, course_override=None) -> str:
        if course_override is not None:
            return str(getattr(course_override, "course_id", "") or "").strip()
        course_manager = getattr(self._host, "course_manager", None)
        current = course_manager.current() if course_manager is not None else None
        return str(getattr(current, "course_id", "") or "").strip()

    def _show_course_conflict(
        self,
        existing_course_id: str,
        requested_course_id: str,
    ) -> None:
        host = self._host
        gm = getattr(getattr(host, "lang_manager", None), "get_text", None)
        if not callable(gm):
            gm = lambda zh_text, _en_text: zh_text
        detail = gm(
            f"当前生成工作区属于课程 {existing_course_id}，不能直接切换到 {requested_course_id}。请先完成、保存或取消当前任务。",
            f"The generation workspace belongs to course {existing_course_id} and cannot switch directly to {requested_course_id}. Finish, save, or cancel the current task first.",
        )
        host._last_generation_launch_error = detail
        QMessageBox.warning(
            host if isinstance(host, QWidget) else None,
            gm("生成任务属于其他课程", "Generation Belongs to Another Course"),
            detail,
        )

    def accept(
        self,
        dialog,
        course_project,
        *,
        draft_source: str,
        material_pack=None,
        start_after_save: bool = False,
    ) -> None:
        """Publish reviewed questions while retaining the surface on failure."""
        if material_pack is None:
            self.sync_draft(dialog, course_project, source=draft_source)
        publish_destination = str(
            getattr(dialog, "publish_destination", "library") or "library"
        ).strip()
        saved = self.save(
            dialog,
            course_project,
            material_pack=material_pack,
            start_after_save=(start_after_save or publish_destination == "practice_now"),
            present_error=False,
        )
        workspace = self._workspace()
        if not saved:
            workspace.show_generation_widget(
                dialog,
                course_id=str(getattr(course_project, "course_id", "") or ""),
                course_title=str(getattr(course_project, "title", "") or ""),
                draft_id=str(getattr(dialog, "_generation_draft_id", "") or ""),
            )
            return
        workspace.clear_generation_widget(dialog)
        dialog.deleteLater()

    def reject(
        self,
        dialog,
        course_project,
        *,
        draft_source: str,
        material_pack=None,
    ) -> None:
        """Leave generation without discarding a reviewable course draft."""
        host = self._host
        if material_pack is None:
            self.sync_draft(dialog, course_project, source=draft_source)
        workspace = self._workspace()
        workspace.clear_generation_widget(dialog)
        dialog.deleteLater()
        if bool(getattr(workspace, "_shutting_down", False)):
            if (
                bool(getattr(host, "_generation_close_pending", False))
                and workspace.generation_widget() is None
            ):
                host._generation_close_pending = False
                workspace._shutting_down = False
                QTimer.singleShot(0, host.close)
            return
        if bool(getattr(host, "_generation_close_pending", False)):
            host._generation_close_pending = False
            QTimer.singleShot(0, host.close)
            return
        host.navigate_to(
            host.SCREEN_COURSES,
            allow_first_run_redirect=False,
        )

    def configure(
        self,
        *,
        course_override=None,
        initial_plan=None,
        prediction=None,
        material_pack=None,
        recovery_context=None,
        review_warnings_only: bool = False,
        question_set_title: str = "",
        draft_source: str = "manual",
        draft_id: str = "",
        present_error: bool = True,
    ):
        """Configure one generation surface without deciding how it is shown."""
        host = self._host
        gm = host.lang_manager.get_text
        course_manager = getattr(host, "course_manager", None)
        draft_course = (
            course_override
            if course_override is not None
            else (course_manager.current() if course_manager is not None else None)
        )
        course_id = str(getattr(draft_course, "course_id", "") or "").strip()
        requested_draft_id = str(draft_id or "").strip()
        if requested_draft_id:
            if material_pack is not None:
                detail = gm(
                    "带材料包的任务不能恢复指定草稿，请从课程页重新开始。",
                    "A material-pack task cannot resume a specific draft. Start it again from the course page.",
                )
                host._last_generation_launch_error = detail
                if present_error:
                    QMessageBox.warning(
                        host if isinstance(host, QWidget) else None,
                        gm("无法恢复生成任务", "Cannot Resume Generation"),
                        detail,
                    )
                return None
            requested_draft = self.draft_by_id(requested_draft_id)
            if requested_draft is None:
                detail = gm(
                    "找不到指定的生成草稿，可能已被删除或已完成。请从课程页重新开始。",
                    "The requested generation draft was not found. It may have been deleted or completed. Start again from the course page.",
                )
                host._last_generation_launch_error = detail
                if present_error:
                    QMessageBox.warning(
                        host if isinstance(host, QWidget) else None,
                        gm("无法恢复生成任务", "Cannot Resume Generation"),
                        detail,
                    )
                return None
            if requested_draft.course_id != course_id:
                detail = gm(
                    "生成草稿与所选课程不匹配，未执行恢复。",
                    "The generation draft does not belong to the selected course and was not resumed.",
                )
                host._last_generation_launch_error = detail
                if present_error:
                    QMessageBox.warning(
                        host if isinstance(host, QWidget) else None,
                        gm("课程与草稿不匹配", "Course and Draft Do Not Match"),
                        detail,
                    )
                return None
        new_session_request = (
            initial_plan is not None
            or prediction is not None
            or material_pack is not None
            or bool(recovery_context)
            or bool(str(question_set_title or "").strip())
        )
        resume_latest = (
            not requested_draft_id
            and (
                not new_session_request
                or str(draft_source or "").strip() == "first_run"
            )
        )
        candidate_draft = (
            self.draft_by_id(requested_draft_id)
            if requested_draft_id and material_pack is None
            else self.draft(course_id)
            if material_pack is None and resume_latest
            else None
        )
        generation_draft = (
            candidate_draft
            if candidate_draft is not None
            and candidate_draft.course_id == course_id
            and (
                requested_draft_id
                or candidate_draft.source == draft_source
            )
            else None
        )
        preparation = self.prepare(
            course_override=course_override,
            material_pack=material_pack,
            purpose="create",
            allow_review_without_ai=generation_draft is not None,
            present_error=present_error,
        )
        if preparation is None:
            return None
        dialog = preparation.dialog
        course_project = preparation.course_project
        restored_draft = False
        if generation_draft is not None and hasattr(dialog, "restore_generation_draft"):
            dialog.restore_generation_draft(generation_draft)
            restored_draft = True
            draft_source = generation_draft.source
            draft_id = generation_draft.draft_id
        elif initial_plan is not None:
            try:
                dialog.apply_exam_plan(initial_plan)
            except ValueError as exc:
                QMessageBox.warning(
                    host,
                    gm("预测配置不可用", "Prediction Plan Unavailable"),
                    str(exc),
                )
                return None
            if prediction is not None and hasattr(dialog, "set_title_input"):
                course_title = str(getattr(course_project, "title", "") or "").strip()
                dialog.set_title_input.setText(gm(
                    f"{course_title}预测模拟卷" if course_title else "预测模拟卷",
                    f"{course_title} Predicted Mock Exam" if course_title else "Predicted Mock Exam",
                ))
            if prediction is not None and hasattr(dialog, "status_label"):
                dialog.status_label.setText(prediction_prefill_status(prediction, gm))
        if not restored_draft and question_set_title and hasattr(dialog, "set_title_input"):
            dialog.set_title_input.setText(str(question_set_title).strip())
        if not restored_draft and isinstance(recovery_context, dict):
            if hasattr(dialog, "set_title_input"):
                title = str(recovery_context.get("question_set_title", "") or "").strip()
                if title:
                    dialog.set_title_input.setText(title)
            if hasattr(dialog, "runtime_instruction_input"):
                instruction = str(recovery_context.get("runtime_instruction", "") or "").strip()
                dialog.runtime_instruction_input.setPlainText(instruction)
        if review_warnings_only and not restored_draft:
            dialog.set_review_warnings_only(True)
        set_draft_source = getattr(dialog, "set_draft_source", None)
        if callable(set_draft_source):
            set_draft_source(draft_source)
        if material_pack is None:
            if not str(draft_id or "").strip():
                store = getattr(host, "generation_draft_store", None)
                new_id = getattr(store, "new_draft_id", None)
                draft_id = new_id() if callable(new_id) else ""
            setattr(dialog, "_generation_draft_id", str(draft_id or "").strip())
        draft_signal = getattr(dialog, "draft_changed", None)
        if material_pack is None and draft_signal is not None and hasattr(draft_signal, "connect"):
            draft_signal.connect(
                lambda: self.sync_draft(dialog, course_project, source=draft_source)
            )
        return dialog, course_project, restored_draft, draft_source

    def save(
        self,
        dialog,
        course_project,
        *,
        material_pack=None,
        start_after_save: bool = False,
        present_error: bool = True,
    ) -> bool:
        """Persist accepted generation output from modal or embedded surfaces."""
        host = self._host
        questions = list(getattr(dialog, "generated_questions", ()) or ())
        if not questions:
            return False
        gm = host.lang_manager.get_text
        qset = build_ai_question_set(
            questions,
            selected_difficulty=dialog.diff_combo.currentData(),
            generation_config=dialog._build_generation_config(),
            lang=host.lang_manager.current,
            course_project=course_project,
            custom_title=dialog.question_set_title(),
            material_pack=material_pack,
        )
        try:
            qset, saved = persist_new_question_set(
                host.question_bank,
                host.set_manager,
                qset,
                questions,
            )
        except RuntimeError as exc:
            if present_error:
                QMessageBox.critical(
                    host if isinstance(host, QWidget) else None,
                    gm("保存失败", "Save Failed"),
                    str(exc),
                )
            else:
                show_save_error = getattr(dialog, "show_save_error", None)
                if callable(show_save_error):
                    show_save_error(str(exc))
            return False
        self.delete_draft(
            course_project.course_id,
            draft_id=str(getattr(dialog, "_generation_draft_id", "") or ""),
        )
        host.course_context.question_bank_changed()
        if start_after_save:
            host._on_study_quiz_start(
                StudyIntent(
                    course_id=course_project.course_id,
                    action=StudyAction.CUSTOM_PRACTICE,
                    set_id=qset.set_id,
                    question_ids=tuple(qset.questions),
                    question_count=len(qset.questions),
                    submission_mode="practice",
                    source="first_run_generation",
                ),
                list(qset.questions),
            )
            return True
        QMessageBox.information(
            host,
            gm("已保存", "Saved"),
            gm(
                f"已保存 {saved} 道题目并创建了题目集：\n{qset.get_title(host.lang_manager.current)}",
                f"Saved {saved} questions and created a question set:\n"
                f"{qset.get_title(host.lang_manager.current)}",
            ),
        )
        host.navigate_to(host.SCREEN_TOPIC_SELECTION)
        return True

    def draft(self, course_id: str):
        store = getattr(self._host, "generation_draft_store", None)
        if store is None or not course_id:
            return None
        try:
            return store.get(course_id)
        except (OSError, TypeError, ValueError) as exc:
            log_warning(f"Failed to load generation draft: {exc}")
            return None

    def draft_by_id(self, draft_id: str):
        store = getattr(self._host, "generation_draft_store", None)
        draft_id = str(draft_id or "").strip()
        if store is None or not draft_id:
            return None
        getter = getattr(store, "get_by_id", None)
        if not callable(getter):
            return None
        try:
            return getter(draft_id)
        except (OSError, TypeError, ValueError) as exc:
            log_warning(f"Failed to load generation draft {draft_id}: {exc}")
            return None

    def sync_draft(self, dialog, course_project, *, source: str) -> bool:
        store = getattr(self._host, "generation_draft_store", None)
        course_id = str(getattr(course_project, "course_id", "") or "").strip()
        if store is None or not course_id:
            return False
        questions = list(getattr(dialog, "generated_questions", ()) or ())
        draft_id = str(getattr(dialog, "_generation_draft_id", "") or "").strip()
        try:
            if not questions:
                if draft_id:
                    store.delete(course_id, draft_id=draft_id)
                else:
                    store.delete(course_id)
                return True
            store.save(
                course_id=course_id,
                draft_id=draft_id,
                questions=questions,
                question_set_title=dialog.question_set_title(),
                exam_plan=dialog.build_exam_plan(),
                review_warnings_only=bool(getattr(dialog, "_review_warnings_only", False)),
                publish_destination=str(
                    getattr(dialog, "publish_destination", "library") or "library"
                ),
                review_state=getattr(dialog, "review_state", {}),
                source=source,
                task_id=str(getattr(dialog, "_generation_task_id", "") or ""),
            )
            return True
        except (OSError, TypeError, ValueError) as exc:
            log_warning(f"Failed to persist generation draft: {exc}")
            return False

    def delete_draft(self, course_id: str, *, draft_id: str = "") -> None:
        store = getattr(self._host, "generation_draft_store", None)
        if store is None or not course_id:
            return
        try:
            if draft_id:
                store.delete(course_id, draft_id=draft_id)
            else:
                store.delete(course_id)
        except OSError as exc:
            log_warning(f"Failed to delete generation draft: {exc}")

    def resume_draft(
        self,
        course_id: str,
        _source: str = "",
        draft_id: str = "",
    ) -> bool:
        """Resume the authoritative stored draft in its owning course."""
        course = self._host.course_manager.get(str(course_id or "").strip())
        if course is None or getattr(course, "is_archived", False):
            return False
        draft = self.draft_by_id(draft_id) if draft_id else self.draft(course.course_id)
        if draft is None:
            return False
        return bool(
            self.open(
                course_override=course,
                draft_source=draft.source,
                draft_id=draft.draft_id,
            )
        )
