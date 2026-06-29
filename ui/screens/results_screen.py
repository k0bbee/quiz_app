"""Results screen — score display, per-question review, retry options."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame
)
from PyQt6.QtCore import pyqtSignal, Qt

from core.language_manager import LanguageManager
from models.progress import ProgressRecord, AnswerRecord
from ui.widgets.question_review_card import QuestionReviewCard
from ui.widgets.progress_summary_bar import ProgressSummaryBar
from utils.constants import topic_label, topic_value


class ResultsScreen(QWidget):
    """Shows quiz results with review and retry options."""

    retry_incorrect = pyqtSignal()
    retry_unsure = pyqtSignal()
    retry_all = pyqtSignal()
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_record: ProgressRecord = None
        self._questions: dict = {}  # question_id -> Question (set externally)
        self._lang: str = "zh"
        self.lang_manager = LanguageManager.instance()
        self._setup_ui()
        self.lang_manager.language_changed.connect(self._on_language_changed)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

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

        self.retry_incorrect_btn = QPushButton(
            self.lang_manager.get_text("只重做错题", "Retry Incorrect Only")
        )
        self.retry_incorrect_btn.setObjectName("primaryButton")
        self.retry_incorrect_btn.setMinimumHeight(40)
        self.retry_incorrect_btn.setMinimumWidth(150)
        self.retry_incorrect_btn.clicked.connect(self.retry_incorrect.emit)
        btn_layout.addWidget(self.retry_incorrect_btn)

        self.retry_unsure_btn = QPushButton(
            self.lang_manager.get_text("重做不确定题", "Retry Unsure")
        )
        self.retry_unsure_btn.setObjectName("secondaryButton")
        self.retry_unsure_btn.setMinimumHeight(40)
        self.retry_unsure_btn.setMinimumWidth(150)
        self.retry_unsure_btn.clicked.connect(self.retry_unsure.emit)
        btn_layout.addWidget(self.retry_unsure_btn)

        self.retry_all_btn = QPushButton(
            self.lang_manager.get_text("重新练习全部", "Retry Entire Set")
        )
        self.retry_all_btn.setObjectName("secondaryButton")
        self.retry_all_btn.setMinimumHeight(40)
        self.retry_all_btn.setMinimumWidth(150)
        self.retry_all_btn.clicked.connect(self.retry_all.emit)
        btn_layout.addWidget(self.retry_all_btn)

        layout.addLayout(btn_layout)

    def _on_language_changed(self, lang):
        """Update all labels when language changes."""
        self.review_label.setText(self.lang_manager.get_text("回顾:", "Review:"))
        self.retry_incorrect_btn.setText(
            self.lang_manager.get_text("只重做错题", "Retry Incorrect Only")
        )
        self.retry_unsure_btn.setText(
            self.lang_manager.get_text("重做不确定题", "Retry Unsure")
        )
        self.retry_all_btn.setText(
            self.lang_manager.get_text("重新练习全部", "Retry Entire Set")
        )

        # Re-render results if a record is loaded
        if self.current_record is not None:
            self.set_results(self.current_record, self._questions, self.lang_manager.current)

    def set_results(self, record: ProgressRecord, questions: dict = None, lang: str = "zh"):
        """Display the results for a completed quiz session."""
        self.current_record = record
        self._questions = questions or {}
        self._lang = lang

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
            emoji = "💪"

        self.score_label.setText(f"{emoji} {score:.0f}%")

        # Summary bar
        self.summary_bar.set_values(summary.correct, summary.incorrect, 0)

        # Stats
        unsure_correct = sum(
            1
            for answer in record.answers
            if answer.is_correct and getattr(answer, "confidence", "sure") == "unsure"
        )
        self.stats_label.setText(
            self.lang_manager.get_text(
                f"正确: {summary.correct} | 错误: {summary.incorrect} | "
                f"答对但不确定: {unsure_correct} | "
                f"总计: {summary.total_questions} | "
                f"用时: {summary.total_time_seconds:.0f}秒 | "
                f"平均: {summary.average_time_per_question:.1f}秒/题",
                f"Correct: {summary.correct} | Incorrect: {summary.incorrect} | "
                f"Correct but unsure: {unsure_correct} | "
                f"Total: {summary.total_questions} | "
                f"Time: {summary.total_time_seconds:.0f}s | "
                f"Avg: {summary.average_time_per_question:.1f}s/question"
            )
        )

        self.topic_stats_label.setText(self._build_topic_summary(record, lang))
        self.next_action_label.setText(self._build_next_action_text(record))

        # Review cards
        self._clear_reviews()
        for i, answer in enumerate(record.answers):
            card = QuestionReviewCard()
            q = self._questions.get(answer.question_id)
            if q:
                card.set_result(i, q, answer.user_answer, answer.is_correct, lang)
            else:
                # Minimal card without question data
                card.index_label.setText(f"Q{i + 1}")
                if answer.is_correct:
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

        # Update retry buttons
        has_incorrect = any(not a.is_correct for a in record.answers)
        has_unsure = any(getattr(a, "confidence", "sure") == "unsure" for a in record.answers)
        self.retry_incorrect_btn.setEnabled(has_incorrect)
        self.retry_unsure_btn.setEnabled(has_unsure)

    def _build_next_action_text(self, record: ProgressRecord) -> str:
        """Return a compact recommendation for the next learning action."""
        incorrect_count = sum(1 for answer in record.answers if not answer.is_correct)
        unsure_count = sum(
            1
            for answer in record.answers
            if getattr(answer, "confidence", "sure") == "unsure"
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
        self._questions = questions

    def _clear_reviews(self):
        """Remove all review cards from the layout."""
        while self.review_layout.count() > 1:  # Keep the stretch
            item = self.review_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _build_topic_summary(self, record: ProgressRecord, lang: str) -> str:
        """Build a compact per-topic accuracy summary for the completed session."""
        if not self._questions:
            return self.lang_manager.get_text(
                "题目详情不可用于主题细分。",
                "Question details were not available for topic breakdown."
            )

        stats = {}
        for answer in record.answers:
            question = self._questions.get(answer.question_id)
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
            label = topic_label(topic, lang)
            total = value["total"]
            correct = value["correct"]
            parts.append(f"{label}: {correct}/{total}")
        prefix = self.lang_manager.get_text("主题细分: ", "Topic breakdown: ")
        return prefix + " | ".join(parts)
