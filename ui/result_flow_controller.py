"""Coordinate completed-session results and follow-up practice flows."""

from __future__ import annotations

from PyQt6.QtWidgets import QMessageBox, QWidget

from core.session_retry import session_retry_question_ids
from core.study_intent import StudyAction, StudyIntent


class ResultFlowController:
    """Own result persistence, history display, and retry orchestration."""

    def __init__(self, host, *, message_box=QMessageBox):
        self.host = host
        self.message_box = message_box

    def quiz_finished(self, progress_record) -> None:
        """Persist a completed session and present its immutable result."""
        host = self.host
        if progress_record:
            host.progress_manager.save(progress_record)
            snapshot_manager = getattr(host, "snapshot_manager", None)
            if snapshot_manager is not None:
                snapshot_manager.delete_for_set(progress_record.set_id)
        host._refresh_first_run()

        study_intent = host.study_flow.take_active_intent()

        host.results_screen.set_results(
            progress_record,
            questions=dict(host.study_flow.active_questions),
            lang=host.lang_manager.current,
            study_intent=study_intent,
        )
        host.navigate_to(host.SCREEN_RESULTS)

    def open_progress_record(self, progress_id: str) -> None:
        """Open a persisted result, retaining archived question snapshots."""
        host = self.host
        record = host.progress_manager.get(progress_id)
        if record is None:
            self.message_box.warning(
                self._parent(),
                host.lang_manager.get_text(
                    "记录不可用",
                    "Record Unavailable",
                ),
                host.lang_manager.get_text(
                    "该练习记录已不存在，请刷新进度页。",
                    "This practice record no longer exists. Refresh the progress page.",
                ),
            )
            return

        question_ids = list(
            dict.fromkeys(
                answer.question_id
                for answer in record.answers
                if answer.question_id
            )
        )
        questions = host.question_bank.get_many(question_ids)
        result_questions = {
            question.question_id: question for question in questions
        }
        host.results_screen.set_results(
            record,
            questions=result_questions,
            lang=host.lang_manager.current,
            study_intent=None,
        )
        host.course_context.refresh_results_retry_availability()
        host.navigate_to(host.SCREEN_RESULTS)

    def retry_incorrect(self) -> None:
        """Start practice from incorrectly answered questions in this result."""
        host = self.host
        gm = host.lang_manager.get_text
        record = host.results_screen.current_record
        if not record:
            return

        question_ids = session_retry_question_ids(record)
        if not question_ids:
            self.message_box.information(
                self._parent(),
                gm("全部正确！", "All Correct!"),
                gm("你答对了所有题目！", "You answered all questions correctly!"),
            )
            return

        course_id = host.course_context.current_course_id()
        questions = host.question_bank.get_many(
            question_ids,
            course_id=course_id,
        )
        if not questions:
            self.message_box.warning(
                self._parent(),
                gm("题目不可用", "Questions Unavailable"),
                gm(
                    "这些题目已被删除，或不属于当前课程。请返回结果页选择其他练习。",
                    "These questions were deleted or do not belong to the current "
                    "course. Choose another practice action from Results.",
                ),
            )
            return

        intent = StudyIntent(
            course_id=course_id,
            action=StudyAction.CUSTOM_PRACTICE,
            question_ids=tuple(
                question.question_id for question in questions
            ),
            question_count=len(questions),
            submission_mode="practice",
            source="results_incorrect",
        )
        host.study_flow.start_questions(
            intent,
            questions,
            label=gm("错题复习", "Incorrect Review"),
        )

    def practice_incorrect(self, intent: StudyIntent | None = None) -> None:
        """Start a session from prioritized historical incorrect questions."""
        host = self.host
        gm = host.lang_manager.get_text
        incorrect_ids = (
            list(intent.question_ids)
            if isinstance(intent, StudyIntent) and intent.question_ids
            else host.progress_manager.get_prioritized_review_question_ids()
        )
        if not incorrect_ids:
            self.message_box.information(
                self._parent(),
                gm("没有错题", "No Incorrect Questions"),
                gm(
                    "还没有错题记录。",
                    "No incorrect questions recorded yet.",
                ),
            )
            return

        course_id = host.course_context.current_course_id()
        questions = host.question_bank.get_many(
            incorrect_ids,
            course_id=course_id,
        )
        mastery_overrides = getattr(host, "mastery_overrides", None)
        if mastery_overrides is not None:
            questions = [
                question
                for question in questions
                if not mastery_overrides.is_topic_mastered(
                    course_id,
                    question.topic,
                )
            ]
        if isinstance(intent, StudyIntent) and intent.question_count > 0:
            questions = questions[: intent.question_count]
        if not questions:
            self.message_box.warning(
                self._parent(),
                gm("没有题目", "No Questions"),
                gm(
                    "存在错题记录，但题目文件缺失，或相关主题已标记为已掌握。",
                    "Incorrect records exist, but question files are missing or "
                    "their topics are marked mastered.",
                ),
            )
            return

        resolved_intent = StudyIntent(
            course_id=course_id,
            action=(
                intent.action
                if isinstance(intent, StudyIntent)
                else StudyAction.REVIEW_QUESTIONS
            ),
            topic_ids=(
                intent.topic_ids if isinstance(intent, StudyIntent) else ()
            ),
            question_ids=tuple(
                question.question_id for question in questions
            ),
            question_count=len(questions),
            submission_mode=(
                intent.submission_mode
                if isinstance(intent, StudyIntent)
                else "practice"
            ),
            source=(
                intent.source
                if isinstance(intent, StudyIntent)
                else "incorrect_history"
            ),
            plan_id=intent.plan_id if isinstance(intent, StudyIntent) else "",
        )
        host.study_flow.start_questions(
            resolved_intent,
            questions,
            label=gm("历史错题复习", "Incorrect Review"),
        )

    def _parent(self):
        return self.host if isinstance(self.host, QWidget) else None
