"""Results screen — score display, per-question review, retry options."""

import copy

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QMenu
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QAction

from core.language_manager import LanguageManager
from core.progress_archive import validate_review_snapshot
from core.study_intent import (
    StudyAction,
    StudyIntent,
    continue_daily_queue_intent,
)
from models.progress import ProgressRecord, QuestionReviewSnapshot
from models.question import Question
from models.remediation import RemediationRequest, TopicSignal, answer_text
from ui.widgets.question_review_card import QuestionReviewCard
from ui.widgets.progress_summary_bar import ProgressSummaryBar
from utils.constants import Difficulty, QuestionType, topic_value
from core.topic_display import topic_display_name
from models.course_project import CourseProjectManager
from ui.archive_status_presenter import build_archive_status_view


def _question_source_ref_ids(question: Question) -> tuple[str, ...]:
    """Extract bounded, human-readable source identifiers from question metadata."""
    metadata = getattr(question, "metadata", {}) or {}
    raw_refs = metadata.get("source_refs", []) if isinstance(metadata, dict) else []
    values = []
    for ref in raw_refs or ():
        if isinstance(ref, dict):
            value = (
                ref.get("source_id")
                or ref.get("id")
                or ref.get("path")
                or ref.get("title")
            )
        else:
            value = ref
        text = str(value or "").strip()
        if text and text not in values:
            values.append(text[:180])
        if len(values) >= 4:
            break
    return tuple(values)


def _question_stem(question: Question) -> str:
    """Return a bounded stem hint for misconception-focused generation."""
    try:
        stem = question.get_stem("zh") or question.get_stem("en")
    except AttributeError:
        stem = ""
    return " ".join(str(stem or "").split())[:400]


class ResultsScreen(QWidget):
    """Shows quiz results with review and retry options."""

    retry_incorrect = pyqtSignal()
    retry_unsure = pyqtSignal()
    retry_review = pyqtSignal()
    retry_all = pyqtSignal()
    practice_topic_requested = pyqtSignal(str)
    review_topic_requested = pyqtSignal(str)
    study_requested = pyqtSignal(object)
    generate_reinforcement_requested = pyqtSignal(object)

    def __init__(self, parent=None, *, course_manager: CourseProjectManager):
        super().__init__(parent)
        self.current_record: ProgressRecord = None
        self._questions: dict = {}  # Compatibility alias for live retry questions.
        self._live_retry_questions: dict[str, Question] = {}
        self._historical_questions: dict[str, Question] = {}
        self._review_questions: dict[str, Question] = {}  # Compatibility alias.
        self._snapshot_question_ids: set[str] = set()
        self._lang: str = "zh"
        self.lang_manager = LanguageManager.instance()
        self.course_manager = course_manager
        self._historical_course_project = None
        self._live_course_project = None
        self._course_project = None
        self.current_study_intent: StudyIntent | None = None
        self._retry_question_ids: set[str] = set()
        self._can_retry_all = False
        self._setup_ui()
        self.lang_manager.language_changed.connect(self._on_language_changed)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        self.context_label = QLabel()
        self.context_label.setObjectName("resultsContextLabel")
        self.context_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.context_label.setWordWrap(True)
        self.context_label.hide()
        layout.addWidget(self.context_label)

        self.archive_notice_label = QLabel()
        self.archive_notice_label.setObjectName("archiveNoticeLabel")
        self.archive_notice_label.setWordWrap(True)
        self.archive_notice_label.hide()
        layout.addWidget(self.archive_notice_label)

        # Score header
        self.score_label = QLabel()
        self.score_label.setObjectName("resultsScoreLabel")
        self.score_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.score_label)

        # Summary bar
        self.summary_bar = ProgressSummaryBar()
        layout.addWidget(self.summary_bar)

        # Stats line
        self.stats_label = QLabel()
        self.stats_label.setObjectName("resultsStatsLabel")
        self.stats_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stats_label.setWordWrap(True)
        layout.addWidget(self.stats_label)

        self.topic_stats_label = QLabel()
        self.topic_stats_label.setWordWrap(True)
        self.topic_stats_label.setObjectName("resultsTopicStats")
        self.topic_stats_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.topic_stats_label)

        self.next_action_label = QLabel()
        self.next_action_label.setWordWrap(True)
        self.next_action_label.setObjectName("resultsNextActionLabel")
        self.next_action_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.next_action_label)

        self.next_action_btn = QPushButton()
        self.next_action_btn.setObjectName("secondaryButton")
        self.next_action_btn.setVisible(False)
        self.next_action_btn.clicked.connect(self._emit_next_action)
        layout.addWidget(self.next_action_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        self.reinforce_btn = QPushButton()
        self.reinforce_btn.setObjectName("secondaryButton")
        self.reinforce_btn.hide()
        self.reinforce_btn.clicked.connect(self._emit_reinforcement_request)
        layout.addWidget(
            self.reinforce_btn,
            alignment=Qt.AlignmentFlag.AlignCenter,
        )
        self.repeat_study_btn = QPushButton()
        self.repeat_study_btn.setObjectName("secondaryButton")
        self.repeat_study_btn.setMinimumHeight(40)
        self.repeat_study_btn.setMinimumWidth(180)
        self.repeat_study_btn.hide()
        self.repeat_study_btn.clicked.connect(self._emit_repeat_study)
        layout.addWidget(
            self.repeat_study_btn,
            alignment=Qt.AlignmentFlag.AlignCenter,
        )
        self._recommended_topic_id = ""
        self._recommended_action = ""
        self._reinforcement_topic_ids: tuple[str, ...] = ()

        # Divider
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(line)

        # Review label
        self.review_label = QLabel(self.lang_manager.get_text("回顾:", "Review:"))
        self.review_label.setObjectName("resultsReviewLabel")
        layout.addWidget(self.review_label)

        # Scrollable review list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self.review_container = QWidget()
        self.review_layout = QVBoxLayout(self.review_container)
        self.review_layout.setSpacing(8)
        self.review_layout.addStretch()

        scroll.setWidget(self.review_container)
        layout.addWidget(scroll, 1)

        # Action buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.retry_incorrect_btn = QPushButton(
            self.lang_manager.get_text("重做错题", "Retry Incorrect")
        )
        self.retry_incorrect_btn.setObjectName("primaryButton")
        self.retry_incorrect_btn.setMinimumHeight(40)
        self.retry_incorrect_btn.setMinimumWidth(150)
        self.retry_incorrect_btn.clicked.connect(self.retry_incorrect.emit)
        btn_layout.addWidget(self.retry_incorrect_btn)

        self.more_practice_btn = QPushButton()
        self.more_practice_btn.setObjectName("secondaryButton")
        self.more_practice_btn.setMinimumHeight(40)
        self.more_practice_btn.setMinimumWidth(130)
        self.more_practice_menu = QMenu(self.more_practice_btn)
        self.more_practice_menu.setObjectName("resultsMorePracticeMenu")
        self.retry_unsure_action = QAction(self.more_practice_menu)
        self.retry_unsure_action.triggered.connect(lambda _checked=False: self.retry_unsure.emit())
        self.more_practice_menu.addAction(self.retry_unsure_action)
        self.retry_review_action = QAction(self.more_practice_menu)
        self.retry_review_action.triggered.connect(lambda _checked=False: self.retry_review.emit())
        self.more_practice_menu.addAction(self.retry_review_action)
        self.more_practice_menu.addSeparator()
        self.retry_all_action = QAction(self.more_practice_menu)
        self.retry_all_action.triggered.connect(lambda _checked=False: self.retry_all.emit())
        self.more_practice_menu.addAction(self.retry_all_action)
        self.more_practice_btn.setMenu(self.more_practice_menu)
        btn_layout.addWidget(self.more_practice_btn)

        layout.addLayout(btn_layout)
        self._on_language_changed(self.lang_manager.current)

    def _on_language_changed(self, lang):
        """Update all labels when language changes."""
        self.review_label.setText(self.lang_manager.get_text("回顾:", "Review:"))
        self.retry_incorrect_btn.setText(
            self.lang_manager.get_text("重做错题", "Retry Incorrect")
        )
        self.more_practice_btn.setText(self.lang_manager.get_text("更多练习", "More Practice"))
        self.retry_unsure_action.setText(self.lang_manager.get_text("重做不确定题", "Retry Unsure"))
        self.retry_review_action.setText(self.lang_manager.get_text("重做复查题", "Retry Review"))
        self.retry_all_action.setText(self.lang_manager.get_text("重新练习全部", "Retry Entire Set"))
        self.reinforce_btn.setText(
            self.lang_manager.get_text(
                "生成补强练习",
                "Generate Reinforcement Practice",
            )
        )

        # Re-render results if a record is loaded
        if self.current_record is not None:
            retry_question_ids = set(self._retry_question_ids)
            can_retry_all = self._can_retry_all
            self.set_results(
                self.current_record,
                self._questions,
                self.lang_manager.current,
                study_intent=self.current_study_intent,
            )
            self.set_retry_availability(
                retry_question_ids,
                can_retry_all=can_retry_all,
            )

    def set_results(
        self,
        record: ProgressRecord,
        questions: dict = None,
        lang: str = "zh",
        *,
        study_intent: StudyIntent | None = None,
    ):
        """Display the results for a completed quiz session."""
        self.current_record = record
        self.current_study_intent = (
            study_intent if isinstance(study_intent, StudyIntent) else None
        )
        self._live_retry_questions = dict(questions or {})
        self._questions = self._live_retry_questions
        self._live_course_project = self._resolve_live_course_project()
        self._historical_course_project = self._resolve_historical_course_project(record)
        self._course_project = self._historical_course_project
        self._historical_questions = {}
        self._snapshot_question_ids = set()
        for snapshot in getattr(record, "question_snapshots", []) or []:
            if not isinstance(snapshot, QuestionReviewSnapshot):
                continue
            if not validate_review_snapshot(snapshot).valid:
                continue
            question_id = str(snapshot.question_id or "").strip()
            if not question_id:
                continue
            self._historical_questions[question_id] = self._question_from_snapshot(
                snapshot
            )
            self._snapshot_question_ids.add(question_id)
        if not self._uses_archived_history(record):
            self._historical_questions.update(self._live_retry_questions)
        self._review_questions = self._historical_questions
        self._retry_question_ids = set(self._live_retry_questions)
        self._can_retry_all = bool(self._live_retry_questions)
        self._lang = lang
        self._recommended_topic_id = ""
        self._recommended_action = ""
        self.next_action_btn.setVisible(False)
        self.reinforce_btn.setVisible(False)
        self.repeat_study_btn.setVisible(False)
        self._set_retry_action_state(False, False, False, False)
        context_parts = [
            str(value or "").strip()
            for value in (
                getattr(record, "course_title_snapshot", ""),
                getattr(record, "set_title_snapshot", ""),
            )
            if str(value or "").strip()
        ]
        self.context_label.setText(" · ".join(context_parts))
        self.context_label.setVisible(bool(context_parts))
        archive_view = build_archive_status_view(
            getattr(record, "archive_status", ""),
            missing_fields=getattr(record, "archive_missing_fields", ()),
            snapshot_count=len(self._historical_questions),
            answer_count=len(getattr(record, "answers", ()) or ()),
            language=lang,
        )
        self.archive_notice_label.setText(archive_view.notice)
        self.archive_notice_label.setVisible(bool(archive_view.notice))

        if record is None:
            self.score_label.setText(
                self.lang_manager.get_text("暂无结果。", "No results available.")
            )
            return

        summary = record.summary
        if summary is None:
            self.score_label.setText(
                self.lang_manager.get_text("无摘要数据。", "No summary data.")
            )
            return

        # Score
        score = summary.score_percentage
        if score >= 90:
            emoji = "🎉"
        elif score >= 70:
            emoji = "👍"
        elif score >= 50:
            emoji = "📚"
        else:
            emoji = "🔎"

        self.score_label.setText(f"{emoji} {score:.0f}%")

        # Derive outcomes from answer records so legacy summaries are corrected too.
        correct_count = sum(1 for answer in record.answers if answer.is_correct)
        skipped_count = sum(1 for answer in record.answers if answer.skipped)
        incorrect_count = sum(
            1 for answer in record.answers if not answer.skipped and not answer.is_correct
        )
        if not record.answers:
            correct_count = summary.correct
            incorrect_count = summary.incorrect
            skipped_count = getattr(summary, "skipped", 0)
        self.summary_bar.set_values(correct_count, incorrect_count, skipped_count)

        # Stats
        unsure_correct = sum(
            1
            for answer in record.answers
            if answer.is_correct and getattr(answer, "confidence", "sure") == "unsure"
        )
        review_count = len(getattr(record, "marked_review_question_ids", []))
        self.stats_label.setText(
            self.lang_manager.get_text(
                f"正确: {correct_count} | 错误: {incorrect_count} | 未答: {skipped_count} | "
                f"答对但不确定: {unsure_correct} | "
                f"复查: {review_count} | "
                f"总计: {summary.total_questions} | "
                f"用时: {summary.total_time_seconds:.0f}秒 | "
                f"平均: {summary.average_time_per_question:.1f}秒/题",
                f"Correct: {correct_count} | Incorrect: {incorrect_count} | Unanswered: {skipped_count} | "
                f"Correct but unsure: {unsure_correct} | "
                f"Review: {review_count} | "
                f"Total: {summary.total_questions} | "
                f"Time: {summary.total_time_seconds:.0f}s | "
                f"Avg: {summary.average_time_per_question:.1f}s/question"
            )
        )

        self.topic_stats_label.setText(self._build_topic_summary(record, lang))
        self.next_action_label.setText(self._build_next_action_text(record))
        self._configure_next_action(record, lang)
        self._configure_reinforcement(record)

        # Review cards
        self._clear_reviews()
        for i, answer in enumerate(record.answers):
            card = QuestionReviewCard()
            q = self._review_questions.get(answer.question_id)
            if q:
                card.set_result(
                    i,
                    q,
                    answer.user_answer,
                    answer.is_correct,
                    lang,
                    skipped=answer.skipped,
                    course_project=(
                        self._historical_course_project
                        if answer.question_id in self._snapshot_question_ids
                        else self._live_course_project
                    ),
                )
            else:
                # Minimal card without question data
                card.index_label.setText(f"Q{i + 1}")
                if answer.skipped:
                    card.icon_label.setText("—")
                    card.result_label.setText(self.lang_manager.get_text("未答", "Unanswered"))
                elif answer.is_correct:
                    card.icon_label.setText("✅")
                    card.result_label.setText(self.lang_manager.get_text("正确", "Correct"))
                else:
                    card.icon_label.setText("❌")
                    card.result_label.setText(self.lang_manager.get_text("错误", "Incorrect"))
                card.stem_label.setText(
                    self.lang_manager.get_text(
                        f"(题目 {answer.question_id})",
                        f"(Question {answer.question_id})"
                    )
                )
                card.answer_info.setText(
                    self.lang_manager.get_text(
                        f"你的答案: {answer.user_answer}",
                        f"Your answer: {answer.user_answer}"
                    )
                )
            self.review_layout.insertWidget(self.review_layout.count() - 1, card)

        self._refresh_retry_action_state()
        self._update_repeat_study_action()

    def set_retry_availability(
        self,
        question_ids,
        *,
        can_retry_all: bool,
    ) -> None:
        """Update retry actions without discarding the archived result display."""
        self._retry_question_ids = {
            str(question_id or "").strip()
            for question_id in (question_ids or ())
            if str(question_id or "").strip()
        }
        self._can_retry_all = bool(can_retry_all)
        self._refresh_retry_action_state()
        if self.current_record is not None and not (
            self._retry_question_ids or self._can_retry_all
        ):
            self.next_action_btn.hide()
            archive_view = build_archive_status_view(
                getattr(self.current_record, "archive_status", ""),
                missing_fields=getattr(
                    self.current_record,
                    "archive_missing_fields",
                    (),
                ),
                snapshot_count=len(self._historical_questions),
                answer_count=len(
                    getattr(self.current_record, "answers", ()) or ()
                ),
                language=self.lang_manager.current,
            )
            self.next_action_label.setText(archive_view.retry_unavailable)

    def _refresh_retry_action_state(self) -> None:
        record = self.current_record
        if record is None:
            self._set_retry_action_state(False, False, False, False)
            return
        available = self._retry_question_ids
        has_incorrect = any(
            answer.question_id in available
            and not answer.skipped
            and not answer.is_correct
            for answer in record.answers
        )
        has_unsure = any(
            answer.question_id in available
            and not answer.skipped
            and getattr(answer, "confidence", "sure") == "unsure"
            for answer in record.answers
        )
        has_review = bool(
            available.intersection(
                getattr(record, "marked_review_question_ids", []) or []
            )
        )
        self._set_retry_action_state(
            has_incorrect,
            has_unsure,
            has_review,
            self._can_retry_all,
        )

    def _update_repeat_study_action(self) -> None:
        intent = self.current_study_intent
        if intent is None:
            self.repeat_study_btn.hide()
            self._set_daily_primary_action(False)
            return
        if intent.action is StudyAction.DAILY_QUEUE:
            remaining = len(intent.remaining_question_ids)
            if remaining <= 0:
                self.repeat_study_btn.hide()
                self._set_daily_primary_action(False)
                return
            text = self.lang_manager.get_text(
                f"继续今日学习 · 剩余 {remaining} 题",
                f"Continue Today's Study · {remaining} left",
            )
            self._set_daily_primary_action(True)
        elif intent.action is StudyAction.PRACTICE_TOPIC:
            text = self.lang_manager.get_text(
                "再练该主题",
                "Practice This Topic Again",
            )
            self._set_daily_primary_action(False)
        elif intent.source == "today_plan":
            text = self.lang_manager.get_text(
                "继续今日计划",
                "Continue Today's Plan",
            )
            self._set_daily_primary_action(False)
        else:
            text = self.lang_manager.get_text(
                "再次练习",
                "Practice Again",
            )
            self._set_daily_primary_action(False)
        self.repeat_study_btn.setText(text)
        self.repeat_study_btn.show()

    def _emit_repeat_study(self) -> None:
        intent = self.current_study_intent
        if intent is None:
            return
        if intent.action is StudyAction.DAILY_QUEUE:
            continued = continue_daily_queue_intent(intent)
            if continued is not None:
                self.study_requested.emit(continued)
            return
        self.study_requested.emit(intent)

    def _configure_reinforcement(self, record: ProgressRecord) -> None:
        """Offer one bounded, source-backed generation action for weak topics."""
        self._reinforcement_topic_ids = ()
        project = self._live_course_project
        if project is None:
            self.reinforce_btn.hide()
            return
        available_topics = {
            topic_value(topic.topic_id)
            for topic in getattr(project, "topics", ()) or ()
            if topic_value(topic.topic_id)
        }
        signals: dict[str, dict] = {}
        for answer in getattr(record, "answers", ()) or ():
            if getattr(answer, "skipped", False):
                continue
            question = self._live_retry_questions.get(answer.question_id)
            if question is None:
                continue
            topic_id = topic_value(question.topic)
            if not topic_id or topic_id not in available_topics:
                continue
            score = 0
            if not getattr(answer, "is_correct", False):
                score += 2
            if getattr(answer, "confidence", "sure") == "unsure":
                score += 1
            if score:
                signal = signals.setdefault(topic_id, {
                    "score": 0,
                    "question_ids": [],
                    "observed_wrong_answers": [],
                    "unsure_question_ids": [],
                    "source_refs": [],
                    "observed_question_stems": [],
                })
                signal["score"] += score
                if answer.question_id and answer.question_id not in signal["question_ids"]:
                    signal["question_ids"].append(answer.question_id)
                if not getattr(answer, "is_correct", False):
                    signal["observed_wrong_answers"].append(
                        answer_text(getattr(answer, "user_answer", None))
                    )
                if getattr(answer, "confidence", "sure") == "unsure":
                    signal["unsure_question_ids"].append(answer.question_id)
                for source_ref in _question_source_ref_ids(question):
                    if source_ref not in signal["source_refs"]:
                        signal["source_refs"].append(source_ref)
                stem = _question_stem(question)
                if stem and stem not in signal["observed_question_stems"]:
                    signal["observed_question_stems"].append(stem)
        self._reinforcement_topic_ids = tuple(
            topic_id
            for topic_id, _signal in sorted(
                signals.items(),
                key=lambda item: (-item[1]["score"], item[0]),
            )[:3]
        )
        self._reinforcement_signals = tuple(
            TopicSignal(
                topic_id=topic_id,
                question_ids=signals[topic_id]["question_ids"],
                observed_wrong_answers=signals[topic_id]["observed_wrong_answers"],
                unsure_question_ids=signals[topic_id]["unsure_question_ids"],
                source_refs=signals[topic_id]["source_refs"],
                observed_question_stems=signals[topic_id]["observed_question_stems"],
            )
            for topic_id in self._reinforcement_topic_ids
        )
        self.reinforce_btn.setVisible(bool(self._reinforcement_topic_ids))

    def _emit_reinforcement_request(self) -> None:
        project = self._live_course_project
        if project is None or not self._reinforcement_topic_ids:
            return
        request = RemediationRequest(
            course_id=project.course_id,
            signals=getattr(self, "_reinforcement_signals", ()),
            max_questions=min(8, len(self._reinforcement_topic_ids) * 3),
        )
        self.generate_reinforcement_requested.emit(request.to_dict())

    def _set_daily_primary_action(self, active: bool) -> None:
        repeat_role = "primaryButton" if active else "secondaryButton"
        retry_role = "secondaryButton" if active else "primaryButton"
        for button, role in (
            (self.repeat_study_btn, repeat_role),
            (self.retry_incorrect_btn, retry_role),
        ):
            if button.objectName() == role:
                continue
            button.setObjectName(role)
            button.style().unpolish(button)
            button.style().polish(button)

    def _set_retry_action_state(
        self,
        has_incorrect: bool,
        has_unsure: bool,
        has_review: bool,
        has_questions: bool,
    ) -> None:
        self.retry_incorrect_btn.setEnabled(has_incorrect)
        self.retry_unsure_action.setEnabled(has_unsure)
        self.retry_review_action.setEnabled(has_review)
        self.retry_all_action.setEnabled(has_questions)
        self.more_practice_btn.setEnabled(has_unsure or has_review or has_questions)

    def _configure_next_action(self, record: ProgressRecord, lang: str) -> None:
        """Expose one topic-specific action for the most useful next step."""
        incorrect_topics: dict[str, dict] = {}
        unsure_topics: dict[str, dict] = {}
        for answer in record.answers:
            if answer.skipped:
                continue
            question = self._review_questions.get(answer.question_id)
            if question is None:
                continue
            topic_id = topic_value(question.topic)
            bucket = {
                "topic_id": topic_id,
                "label": topic_display_name(
                    question.topic,
                    language=lang,
                    fallback_title=question.topic_title(),
                ),
            }
            if not answer.is_correct:
                entry = incorrect_topics.setdefault(topic_id, {**bucket, "count": 0})
                entry["count"] += 1
            elif getattr(answer, "confidence", "sure") == "unsure":
                entry = unsure_topics.setdefault(topic_id, {**bucket, "count": 0})
                entry["count"] += 1

        recommendation = self._highest_priority_topic(incorrect_topics)
        action = "review" if recommendation else ""
        if recommendation is None:
            recommendation = self._highest_priority_topic(unsure_topics)
            action = "practice" if recommendation else ""

        self._recommended_topic_id = recommendation["topic_id"] if recommendation else ""
        self._recommended_action = action
        if recommendation is None:
            self.next_action_btn.setVisible(False)
            return

        label = recommendation["label"]
        if action == "review":
            text = self.lang_manager.get_text(
                f"复习 {label} 错题",
                f"Review Incorrect: {label}",
            )
        else:
            text = self.lang_manager.get_text(
                f"练习 {label}",
                f"Practice: {label}",
            )
        self.next_action_btn.setText(text)
        self.next_action_btn.setVisible(True)

    @staticmethod
    def _highest_priority_topic(stats: dict[str, dict]):
        if not stats:
            return None
        return sorted(
            stats.values(),
            key=lambda item: (-item["count"], item["topic_id"]),
        )[0]

    def _emit_next_action(self) -> None:
        if not self._recommended_topic_id:
            return
        if self._recommended_action == "review":
            self.review_topic_requested.emit(self._recommended_topic_id)
        elif self._recommended_action == "practice":
            self.practice_topic_requested.emit(self._recommended_topic_id)

    def _build_next_action_text(self, record: ProgressRecord) -> str:
        """Return a compact recommendation for the next learning action."""
        intent = self.current_study_intent
        if intent is not None and intent.action is StudyAction.DAILY_QUEUE:
            remaining = len(intent.remaining_question_ids)
            if remaining > 0:
                return self.lang_manager.get_text(
                    f"本组已完成，今日学习还剩 {remaining} 题。",
                    f"This group is complete; {remaining} question(s) remain today.",
                )
            return self.lang_manager.get_text(
                "今日任务完成。",
                "Today's study is complete.",
            )
        incorrect_count = sum(
            1 for answer in record.answers if not answer.skipped and not answer.is_correct
        )
        unsure_count = sum(
            1
            for answer in record.answers
            if not answer.skipped and getattr(answer, "confidence", "sure") == "unsure"
        )
        if incorrect_count > 0:
            return self.lang_manager.get_text(
                f"下一步建议：先重做错题（{incorrect_count} 题），再处理不确定题。",
                f"Recommended next step: retry incorrect questions first ({incorrect_count}), then review unsure ones.",
            )
        if unsure_count > 0:
            return self.lang_manager.get_text(
                f"下一步建议：重做不确定题（{unsure_count} 题），确认这些知识点不是靠猜对。",
                f"Recommended next step: retry unsure questions ({unsure_count}) to confirm they were not guesses.",
            )
        return self.lang_manager.get_text(
            "下一步建议：本次没有错题或不确定题，可以重新练习整套题或返回首页继续学习。",
            "Recommended next step: no incorrect or unsure questions; retry the set or return home to continue learning.",
        )

    def set_questions(self, questions: dict):
        """Provide question data for review rendering."""
        self._live_retry_questions = dict(questions or {})
        self._questions = self._live_retry_questions
        self._historical_questions = dict(self._live_retry_questions)
        self._review_questions = self._historical_questions
        self._snapshot_question_ids = set()

    def retryable_questions(self) -> dict[str, Question]:
        """Return live questions that can back a retry without a persisted set."""
        return dict(self._live_retry_questions)

    @staticmethod
    def _question_from_snapshot(snapshot: QuestionReviewSnapshot) -> Question:
        try:
            question_type = QuestionType(snapshot.question_type)
        except ValueError:
            question_type = QuestionType.MULTIPLE_CHOICE
        content = {
            "stem": snapshot.stem,
            "options": copy.deepcopy(snapshot.options),
            "explanation": snapshot.explanation,
        }
        return Question(
            question_id=snapshot.question_id,
            type=question_type,
            difficulty=Difficulty.MEDIUM,
            bilingual={
                "zh": copy.deepcopy(content),
                "en": copy.deepcopy(content),
            },
            correct_answer=copy.deepcopy(snapshot.correct_answer),
            topic=snapshot.topic_id or "general",
            metadata={
                "topic_title": snapshot.topic_title,
                "source_refs": copy.deepcopy(snapshot.source_refs),
            },
        )

    @staticmethod
    def _uses_archived_history(record: ProgressRecord | None) -> bool:
        if record is None:
            return False
        if getattr(record, "question_snapshots", None):
            return True
        return str(getattr(record, "archive_status", "") or "").strip() in {
            "complete",
            "incomplete",
            "legacy",
        }

    def _resolve_historical_course_project(
        self,
        record: ProgressRecord | None = None,
    ):
        if self.course_manager is None:
            return None
        if self._uses_archived_history(record):
            record_course_id = str(
                getattr(record, "course_id_snapshot", "") or ""
            ).strip()
            if record_course_id:
                return self.course_manager.get(record_course_id)
        return self._resolve_live_course_project(record)

    def _resolve_live_course_project(
        self,
        record: ProgressRecord | None = None,
    ):
        if self.course_manager is None:
            return None
        course_ids = {
            str((question.metadata or {}).get("course_id", "") or "").strip()
            for question in self._live_retry_questions.values()
        }
        course_ids.discard("")
        if len(course_ids) > 1:
            return None
        if len(course_ids) == 1:
            return self.course_manager.get(next(iter(course_ids)))
        record_course_id = str(
            getattr(record, "course_id_snapshot", "") or ""
        ).strip()
        if record_course_id:
            return self.course_manager.get(record_course_id)
        intent_course_id = str(
            getattr(self.current_study_intent, "course_id", "") or ""
        ).strip()
        if intent_course_id:
            return self.course_manager.get(intent_course_id)
        return None

    def _resolve_course_project(self, record: ProgressRecord | None = None):
        """Compatibility wrapper for the historical display context."""
        return self._resolve_historical_course_project(record)

    def _clear_reviews(self):
        """Remove all review cards from the layout."""
        while self.review_layout.count() > 1:  # Keep the stretch
            item = self.review_layout.takeAt(0)
            if item is not None:
                w = item.widget()
                if w is not None:
                    w.setParent(None)
                    w.deleteLater()

    def _build_topic_summary(self, record: ProgressRecord, lang: str) -> str:
        """Build a compact per-topic accuracy summary for the completed session."""
        if not self._review_questions:
            return self.lang_manager.get_text(
                "题目详情不可用于主题细分。",
                "Question details were not available for topic breakdown."
            )

        stats = {}
        for answer in record.answers:
            if answer.skipped:
                continue
            question = self._review_questions.get(answer.question_id)
            if not question:
                continue
            topic = question.topic
            if topic not in stats:
                stats[topic] = {"total": 0, "correct": 0}
            stats[topic]["total"] += 1
            if answer.is_correct:
                stats[topic]["correct"] += 1

        if not stats:
            return self.lang_manager.get_text(
                "无主题细分数据。",
                "No topic breakdown available."
            )

        parts = []
        for topic, value in sorted(stats.items(), key=lambda item: topic_value(item[0])):
            question = next(
                (
                    q
                    for q in self._review_questions.values()
                    if topic_value(q.topic) == topic_value(topic)
                ),
                None,
            )
            label = topic_display_name(
                topic,
                language=lang,
                fallback_title=question.topic_title() if question else "",
            )
            total = value["total"]
            correct = value["correct"]
            parts.append(f"{label}: {correct}/{total}")
        prefix = self.lang_manager.get_text("主题细分: ", "Topic breakdown: ")
        return prefix + " | ".join(parts)
