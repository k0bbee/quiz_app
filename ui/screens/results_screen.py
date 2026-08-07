"""Results screen — score display, per-question review, retry options."""

import copy

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame,
)
from PyQt6.QtCore import pyqtSignal, Qt

from core.language_manager import LanguageManager
from core.progress_archive import validate_review_snapshot
from core.study_intent import StudyIntent
from core.topic_display import topic_display_name
from models.progress import ProgressRecord, QuestionReviewSnapshot
from models.question import Question
from ui.widgets.question_review_card import QuestionReviewCard
from ui.widgets.progress_summary_bar import ProgressSummaryBar
from utils.constants import Difficulty, QuestionType, topic_value
from models.course_project import CourseProjectManager
from ui.archive_status_presenter import build_archive_status_view


class ResultsScreen(QWidget):
    """Shows quiz results with review and retry options."""

    retry_incorrect = pyqtSignal()
    reinforcement_requested = pyqtSignal()
    return_home_requested = pyqtSignal()

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

        # Divider
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(line)

        # Review label
        self.review_label = QLabel(
            self.lang_manager.get_text("错题回顾:", "Review incorrect:")
        )
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
            self.lang_manager.get_text("复习错题", "Review Incorrect")
        )
        self.retry_incorrect_btn.setObjectName("primaryButton")
        self.retry_incorrect_btn.setMinimumHeight(40)
        self.retry_incorrect_btn.setMinimumWidth(150)
        self.retry_incorrect_btn.clicked.connect(self.retry_incorrect.emit)
        btn_layout.addWidget(self.retry_incorrect_btn)

        self.reinforce_btn = QPushButton()
        self.reinforce_btn.setObjectName("secondaryButton")
        self.reinforce_btn.setMinimumHeight(40)
        self.reinforce_btn.setMinimumWidth(170)
        self.reinforce_btn.clicked.connect(self.reinforcement_requested.emit)
        self.reinforce_btn.hide()
        btn_layout.addWidget(self.reinforce_btn)

        self.return_home_btn = QPushButton()
        self.return_home_btn.setObjectName("secondaryButton")
        self.return_home_btn.setMinimumHeight(40)
        self.return_home_btn.setMinimumWidth(150)
        self.return_home_btn.clicked.connect(self.return_home_requested.emit)
        btn_layout.addWidget(self.return_home_btn)

        layout.addLayout(btn_layout)
        self._on_language_changed(self.lang_manager.current)

    def _on_language_changed(self, lang):
        """Update all labels when language changes."""
        self.review_label.setText(
            self.lang_manager.get_text("错题回顾:", "Review incorrect:")
        )
        self.retry_incorrect_btn.setText(
            self.lang_manager.get_text("复习错题", "Review Incorrect")
        )
        self.reinforce_btn.setText(
            self.lang_manager.get_text("生成强化题", "Generate Reinforcement")
        )
        self.return_home_btn.setText(
            self.lang_manager.get_text("返回首页", "Return Home")
        )

        # Re-render results if a record is loaded
        if self.current_record is not None:
            retry_question_ids = set(self._retry_question_ids)
            self.set_results(
                self.current_record,
                self._questions,
                self.lang_manager.current,
                study_intent=self.current_study_intent,
            )
            self.set_retry_availability(retry_question_ids)

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
        self._lang = lang
        self.retry_incorrect_btn.setToolTip("")
        self._set_retry_action_state(False)
        self._set_reinforcement_action_state(False)
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
        self.score_label.setText(
            f"{self.lang_manager.get_text('得分', 'Score')} {score:.0f}%"
        )

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

        # Keep this summary focused on correctness; detail belongs in review cards.
        self.stats_label.setText(
            self.lang_manager.get_text(
                f"正确 {correct_count}/{summary.total_questions} · 错误 {incorrect_count} · 未答 {skipped_count}",
                f"Correct {correct_count}/{summary.total_questions} · Incorrect {incorrect_count} · Unanswered {skipped_count}",
            )
        )

        self.topic_stats_label.setText(self._build_topic_summary(record, lang))

        # Review cards
        self._clear_reviews()
        review_count = 0
        for i, answer in enumerate(record.answers):
            card = QuestionReviewCard()
            needs_review = (
                bool(answer.skipped)
                or not bool(answer.is_correct)
                or str(getattr(answer, "confidence", "sure") or "sure")
                == "unsure"
            )
            if needs_review:
                review_count += 1
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
            card.setVisible(needs_review)
            self.review_layout.insertWidget(self.review_layout.count() - 1, card)

        self.review_label.setText(
            self.lang_manager.get_text("错题回顾:", "Review incorrect:")
            if review_count
            else self.lang_manager.get_text("本次没有需要复习的题目。", "No questions need review.")
        )

        self._refresh_retry_action_state()
        self._refresh_reinforcement_action_state()

    def reinforcement_topic_ids(self, limit: int = 2) -> tuple[str, ...]:
        """Return the weakest topics represented by this result for reinforcement."""
        record = self.current_record
        if record is None:
            return ()
        counts: dict[str, int] = {}
        for answer in getattr(record, "answers", ()) or ():
            needs_reinforcement = (
                bool(answer.skipped)
                or not bool(answer.is_correct)
                or str(getattr(answer, "confidence", "sure") or "sure") == "unsure"
            )
            if not needs_reinforcement:
                continue
            question = self._review_questions.get(answer.question_id)
            if question is None:
                continue
            topic_id = topic_value(question.topic)
            if topic_id:
                counts[topic_id] = counts.get(topic_id, 0) + 1
        return tuple(
            topic_id
            for topic_id, _count in sorted(
                counts.items(), key=lambda item: (-item[1], item[0])
            )[: max(1, int(limit or 1))]
        )

    def _refresh_reinforcement_action_state(self) -> None:
        """Show reinforcement only when a course-backed weak topic is available."""
        topics = self.reinforcement_topic_ids()
        has_course = self._course_project is not None
        self._set_reinforcement_action_state(bool(topics and has_course))

    def _set_reinforcement_action_state(self, available: bool) -> None:
        self.reinforce_btn.setVisible(bool(available))
        self.reinforce_btn.setEnabled(bool(available))

    def set_retry_availability(
        self,
        question_ids,
    ) -> None:
        """Update the single wrong-answer action without discarding history."""
        self._retry_question_ids = {
            str(question_id or "").strip()
            for question_id in (question_ids or ())
            if str(question_id or "").strip()
        }
        self._refresh_retry_action_state()
        if self.current_record is not None and not self._retry_question_ids:
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
            self.retry_incorrect_btn.setToolTip(archive_view.retry_unavailable)

    def _refresh_retry_action_state(self) -> None:
        record = self.current_record
        if record is None:
            self._set_retry_action_state(False)
            return
        available = self._retry_question_ids
        has_incorrect = any(
            answer.question_id in available
            and not answer.skipped
            and not answer.is_correct
            for answer in record.answers
        )
        self._set_retry_action_state(has_incorrect)

    def _set_retry_action_state(self, has_incorrect: bool) -> None:
        self.retry_incorrect_btn.setEnabled(has_incorrect)

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
        weakest = sorted(
            stats.items(),
            key=lambda item: (
                item[1]["correct"] / item[1]["total"],
                -item[1]["total"],
                topic_value(item[0]),
            ),
        )[:2]
        for topic, value in weakest:
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
        prefix = self.lang_manager.get_text("最薄弱主题: ", "Weakest topics: ")
        return prefix + " | ".join(parts)
