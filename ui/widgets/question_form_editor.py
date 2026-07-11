"""Structured editor for every supported question type."""

from __future__ import annotations

from copy import deepcopy

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QFrame,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.language_manager import LanguageManager
from ui.widgets.wheel_safe_controls import WheelSafeComboBox
from utils.constants import Difficulty, QuestionType


_TYPE_LABELS = {
    QuestionType.MULTIPLE_CHOICE: ("单选题", "Single Choice"),
    QuestionType.SCENARIO_CHOICE: ("情景选择题", "Scenario Choice"),
    QuestionType.TRUE_FALSE: ("判断题", "True / False"),
    QuestionType.MATCHING: ("配对题", "Matching"),
    QuestionType.ORDERING: ("排序题", "Ordering"),
    QuestionType.FILL_IN_BLANK: ("填空题", "Fill in the Blank"),
    QuestionType.SHORT_ANSWER: ("简答题", "Short Answer"),
}

_DIFFICULTY_LABELS = {
    Difficulty.EASY: ("简单", "Easy"),
    Difficulty.MEDIUM: ("中等", "Medium"),
    Difficulty.HARD: ("困难", "Hard"),
}


class QuestionFormEditor(QWidget):
    """Edit question payloads without exposing their JSON representation."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.lang_manager = LanguageManager.instance()
        self._question_id = ""
        self._metadata: dict = {}
        self._topic_title = ""
        self._setup_ui()
        self.lang_manager.language_changed.connect(self._update_texts)

    def _setup_ui(self):
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("questionFormScrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.form_content = QWidget()
        layout = QVBoxLayout(self.form_content)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(10)

        common_form = QFormLayout()
        self.type_label = QLabel()
        self.type_combo = WheelSafeComboBox()
        for question_type in QuestionType:
            labels = _TYPE_LABELS[question_type]
            self.type_combo.addItem(self.lang_manager.get_text(*labels), question_type.value)
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        common_form.addRow(self.type_label, self.type_combo)

        self.difficulty_label = QLabel()
        self.difficulty_combo = WheelSafeComboBox()
        for difficulty in Difficulty:
            self.difficulty_combo.addItem(difficulty.value, difficulty.value)
        common_form.addRow(self.difficulty_label, self.difficulty_combo)

        self.topic_label = QLabel()
        self.topic_combo = WheelSafeComboBox()
        common_form.addRow(self.topic_label, self.topic_combo)

        self.subtopic_label = QLabel()
        self.subtopic_editor = QLineEdit()
        common_form.addRow(self.subtopic_label, self.subtopic_editor)
        layout.addLayout(common_form)

        self.language_tabs = QTabWidget()
        self._language_field_labels = {}
        self.zh_stem_editor, self.zh_explanation_editor = self._add_language_tab("zh")
        self.en_stem_editor, self.en_explanation_editor = self._add_language_tab("en")
        layout.addWidget(self.language_tabs)

        self.answer_label = QLabel(self.lang_manager.get_text("选项与答案", "Options and Answer"))
        self.answer_label.setObjectName("sectionLabel")
        layout.addWidget(self.answer_label)
        self.answer_stack = QStackedWidget()
        self.choice_panel = self._build_choice_panel()
        self.answer_stack.addWidget(self.choice_panel)
        self.true_false_panel = self._build_true_false_panel()
        self.answer_stack.addWidget(self.true_false_panel)
        self.matching_panel = self._build_matching_panel()
        self.answer_stack.addWidget(self.matching_panel)
        self.ordering_panel = self._build_ordering_panel()
        self.answer_stack.addWidget(self.ordering_panel)
        self.fill_panel = self._build_fill_panel()
        self.answer_stack.addWidget(self.fill_panel)
        self.short_answer_panel = self._build_short_answer_panel()
        self.answer_stack.addWidget(self.short_answer_panel)
        layout.addWidget(self.answer_stack, 1)

        self.set_topics([])
        self.start_new()
        self._update_texts()
        self.scroll_area.setWidget(self.form_content)
        outer_layout.addWidget(self.scroll_area)

    def _add_language_tab(self, language: str):
        page = QWidget()
        form = QFormLayout(page)
        stem = QTextEdit()
        stem.setMaximumHeight(88)
        explanation = QTextEdit()
        explanation.setMaximumHeight(88)
        stem_label = QLabel()
        explanation_label = QLabel()
        form.addRow(stem_label, stem)
        form.addRow(explanation_label, explanation)
        self._language_field_labels[language] = (stem_label, explanation_label)
        title = "中文" if language == "zh" else "English"
        self.language_tabs.addTab(page, title)
        return stem, explanation

    def _build_choice_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        self.choice_table = QTableWidget(4, 3)
        self.choice_table.setHorizontalHeaderLabels(["", "中文", "English"])
        self.choice_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.choice_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.choice_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for row, label in enumerate("ABCD"):
            item = QTableWidgetItem(label)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.choice_table.setItem(row, 0, item)
            self.choice_table.setItem(row, 1, QTableWidgetItem(""))
            self.choice_table.setItem(row, 2, QTableWidgetItem(""))
        layout.addWidget(self.choice_table)

        answer_row = QHBoxLayout()
        self.choice_answer_label = QLabel()
        answer_row.addWidget(self.choice_answer_label)
        self.choice_answer_combo = QComboBox()
        for label in "ABCD":
            self.choice_answer_combo.addItem(label, label)
        answer_row.addWidget(self.choice_answer_combo)
        answer_row.addStretch()
        layout.addLayout(answer_row)
        return panel

    def _build_true_false_panel(self) -> QWidget:
        panel = QWidget()
        layout = QFormLayout(panel)
        self.true_false_options_text = QLabel()
        self.true_false_answer_combo = QComboBox()
        self.true_false_answer_combo.addItem(self.lang_manager.get_text("正确", "True"), "true")
        self.true_false_answer_combo.addItem(self.lang_manager.get_text("错误", "False"), "false")
        self.true_false_options_label = QLabel()
        self.true_false_answer_label = QLabel()
        layout.addRow(self.true_false_options_label, self.true_false_options_text)
        layout.addRow(self.true_false_answer_label, self.true_false_answer_combo)
        return panel

    def _build_matching_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        self.matching_table = QTableWidget(0, 5)
        self.matching_table.setHorizontalHeaderLabels([
            "ID",
            self.lang_manager.get_text("左项（中文）", "Left (ZH)"),
            self.lang_manager.get_text("左项（英文）", "Left (EN)"),
            self.lang_manager.get_text("右项（中文）", "Right (ZH)"),
            self.lang_manager.get_text("右项（英文）", "Right (EN)"),
        ])
        self.matching_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        for column in range(1, 5):
            self.matching_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.matching_table)
        actions = QHBoxLayout()
        self.add_matching_row_btn = QPushButton(self.lang_manager.get_text("添加配对", "Add Pair"))
        self.add_matching_row_btn.setObjectName("secondaryButton")
        self.add_matching_row_btn.clicked.connect(lambda: self._add_matching_row())
        actions.addWidget(self.add_matching_row_btn)
        self.remove_matching_row_btn = QPushButton(self.lang_manager.get_text("移除配对", "Remove Pair"))
        self.remove_matching_row_btn.setObjectName("secondaryButton")
        self.remove_matching_row_btn.clicked.connect(self._remove_matching_row)
        actions.addWidget(self.remove_matching_row_btn)
        actions.addStretch()
        layout.addLayout(actions)
        return panel

    def _build_ordering_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        self.ordering_table = QTableWidget(0, 3)
        self.ordering_table.setHorizontalHeaderLabels([
            "ID",
            self.lang_manager.get_text("步骤（中文）", "Step (ZH)"),
            self.lang_manager.get_text("步骤（英文）", "Step (EN)"),
        ])
        self.ordering_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.ordering_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.ordering_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.ordering_table)
        actions = QHBoxLayout()
        self.add_ordering_row_btn = QPushButton(self.lang_manager.get_text("添加步骤", "Add Step"))
        self.add_ordering_row_btn.setObjectName("secondaryButton")
        self.add_ordering_row_btn.clicked.connect(lambda: self._add_ordering_row())
        actions.addWidget(self.add_ordering_row_btn)
        self.remove_ordering_row_btn = QPushButton(self.lang_manager.get_text("移除步骤", "Remove Step"))
        self.remove_ordering_row_btn.setObjectName("secondaryButton")
        self.remove_ordering_row_btn.clicked.connect(self._remove_ordering_row)
        actions.addWidget(self.remove_ordering_row_btn)
        self.move_ordering_up_btn = QPushButton(self.lang_manager.get_text("上移", "Move Up"))
        self.move_ordering_up_btn.setObjectName("secondaryButton")
        self.move_ordering_up_btn.clicked.connect(lambda: self._move_ordering_row(-1))
        actions.addWidget(self.move_ordering_up_btn)
        self.move_ordering_down_btn = QPushButton(self.lang_manager.get_text("下移", "Move Down"))
        self.move_ordering_down_btn.setObjectName("secondaryButton")
        self.move_ordering_down_btn.clicked.connect(lambda: self._move_ordering_row(1))
        actions.addWidget(self.move_ordering_down_btn)
        actions.addStretch()
        layout.addLayout(actions)
        return panel

    def _build_fill_panel(self) -> QWidget:
        panel = QWidget()
        layout = QFormLayout(panel)
        self.fill_answers_editor = QTextEdit()
        self.fill_answers_editor.setPlaceholderText(self.lang_manager.get_text(
            "每行一个可接受答案",
            "One acceptable answer per line",
        ))
        self.fill_answers_label = QLabel()
        layout.addRow(self.fill_answers_label, self.fill_answers_editor)
        return panel

    def _build_short_answer_panel(self) -> QWidget:
        panel = QWidget()
        layout = QFormLayout(panel)
        self.short_answer_editor = QTextEdit()
        self.short_answer_editor.setPlaceholderText(self.lang_manager.get_text(
            "填写供人工评分参考的答案要点",
            "Enter reference points for manual grading",
        ))
        self.short_answer_label = QLabel()
        layout.addRow(self.short_answer_label, self.short_answer_editor)
        return panel

    def set_topics(self, topics):
        """Replace topic choices while preserving stable topic IDs."""
        selected = self.topic_combo.currentData() if self.topic_combo.count() else "general"
        self.topic_combo.clear()
        self.topic_combo.addItem(self.lang_manager.get_text("通用", "General"), "general")
        for topic in topics or []:
            topic_id = str(getattr(topic, "topic_id", "") or "").strip()
            title = str(getattr(topic, "title", "") or topic_id).strip()
            if topic_id:
                self.topic_combo.addItem(title, topic_id)
        index = self.topic_combo.findData(selected)
        self.topic_combo.setCurrentIndex(index if index >= 0 else 0)

    def start_new(self):
        """Reset to a new multiple-choice question."""
        self._question_id = ""
        self._metadata = {"source": "manual", "version": 1}
        self._topic_title = ""
        self.type_combo.setCurrentIndex(self.type_combo.findData(QuestionType.MULTIPLE_CHOICE.value))
        self.difficulty_combo.setCurrentIndex(self.difficulty_combo.findData(Difficulty.MEDIUM.value))
        self.topic_combo.setCurrentIndex(max(0, self.topic_combo.findData("general")))
        self.subtopic_editor.clear()
        for editor in (
            self.zh_stem_editor,
            self.zh_explanation_editor,
            self.en_stem_editor,
            self.en_explanation_editor,
        ):
            editor.clear()
        for row in range(4):
            self.choice_table.item(row, 1).setText("")
            self.choice_table.item(row, 2).setText("")
        self.choice_answer_combo.setCurrentIndex(0)
        self.true_false_answer_combo.setCurrentIndex(0)
        self.matching_table.setRowCount(0)
        self._add_matching_row()
        self.ordering_table.setRowCount(0)
        self._add_ordering_row()
        self.fill_answers_editor.clear()
        self.short_answer_editor.clear()

    def load_payload(self, payload: dict):
        """Load a serialized question payload into the form."""
        payload = deepcopy(payload or {})
        self._question_id = str(payload.get("question_id", "") or "")
        self._metadata = dict(payload.get("metadata", {}) or {})
        self._topic_title = str(
            payload.get("topic_title", "")
            or self._metadata.get("topic_title", "")
            or ""
        ).strip()
        question_type = str(payload.get("type", QuestionType.MULTIPLE_CHOICE.value))
        type_index = self.type_combo.findData(question_type)
        self.type_combo.setCurrentIndex(type_index if type_index >= 0 else 0)
        difficulty = str(payload.get("difficulty", Difficulty.MEDIUM.value))
        diff_index = self.difficulty_combo.findData(difficulty)
        self.difficulty_combo.setCurrentIndex(diff_index if diff_index >= 0 else 0)
        topic_id = str(payload.get("topic_id") or payload.get("topic") or "general")
        topic_index = self.topic_combo.findData(topic_id)
        if topic_index < 0:
            self.topic_combo.addItem(self._topic_title or topic_id, topic_id)
            topic_index = self.topic_combo.count() - 1
        self.topic_combo.setCurrentIndex(topic_index)
        self.subtopic_editor.setText(str(payload.get("subtopic", "") or ""))

        bilingual = payload.get("bilingual", {}) or {}
        zh = bilingual.get("zh", {}) or {}
        en = bilingual.get("en", {}) or {}
        self.zh_stem_editor.setPlainText(str(zh.get("stem", "") or ""))
        self.zh_explanation_editor.setPlainText(str(zh.get("explanation", "") or ""))
        self.en_stem_editor.setPlainText(str(en.get("stem", "") or ""))
        self.en_explanation_editor.setPlainText(str(en.get("explanation", "") or ""))
        if question_type in {QuestionType.MULTIPLE_CHOICE.value, QuestionType.SCENARIO_CHOICE.value}:
            self._load_choice_options(zh.get("options", []), en.get("options", []))
            answer_index = self.choice_answer_combo.findData(str(payload.get("correct_answer", "A")).upper())
            self.choice_answer_combo.setCurrentIndex(answer_index if answer_index >= 0 else 0)
        elif question_type == QuestionType.TRUE_FALSE.value:
            answer_index = self.true_false_answer_combo.findData(
                str(payload.get("correct_answer", "true")).lower()
            )
            self.true_false_answer_combo.setCurrentIndex(answer_index if answer_index >= 0 else 0)
        elif question_type == QuestionType.MATCHING.value:
            self._load_matching_options(
                zh.get("options", {}),
                en.get("options", {}),
                payload.get("correct_answer", []),
            )
        elif question_type == QuestionType.ORDERING.value:
            self._load_ordering_options(
                zh.get("options", []),
                en.get("options", []),
                payload.get("correct_answer", []),
            )
        elif question_type == QuestionType.FILL_IN_BLANK.value:
            answers = payload.get("correct_answer", [])
            if not isinstance(answers, list):
                answers = [answers] if str(answers or "").strip() else []
            self.fill_answers_editor.setPlainText("\n".join(str(answer) for answer in answers))
        elif question_type == QuestionType.SHORT_ANSWER.value:
            self.short_answer_editor.setPlainText(str(payload.get("correct_answer", "") or ""))

    def to_payload(self) -> dict:
        """Serialize the form without discarding metadata unknown to the editor."""
        question_type = self.type_combo.currentData()
        topic_id = str(self.topic_combo.currentData() or "general")
        topic_title = self.topic_combo.currentText().strip() or topic_id
        if question_type in {QuestionType.MULTIPLE_CHOICE.value, QuestionType.SCENARIO_CHOICE.value}:
            zh_options = self._choice_options(1)
            en_options = self._choice_options(2)
            correct_answer = self.choice_answer_combo.currentData()
        elif question_type == QuestionType.TRUE_FALSE.value:
            zh_options = ["正确", "错误"]
            en_options = ["True", "False"]
            correct_answer = self.true_false_answer_combo.currentData()
        elif question_type == QuestionType.MATCHING.value:
            zh_options, en_options, correct_answer = self._matching_payload()
        elif question_type == QuestionType.ORDERING.value:
            zh_options, en_options, correct_answer = self._ordering_payload()
        elif question_type == QuestionType.FILL_IN_BLANK.value:
            zh_options = []
            en_options = []
            correct_answer = [
                line.strip()
                for line in self.fill_answers_editor.toPlainText().splitlines()
                if line.strip()
            ]
        elif question_type == QuestionType.SHORT_ANSWER.value:
            zh_options = []
            en_options = []
            correct_answer = self.short_answer_editor.toPlainText().strip()
        else:
            zh_options = []
            en_options = []
            correct_answer = ""
        metadata = deepcopy(self._metadata)
        if topic_title and topic_title != topic_id:
            metadata["topic_title"] = topic_title
        return {
            "question_id": self._question_id,
            "type": question_type,
            "difficulty": self.difficulty_combo.currentData(),
            "topic": topic_id,
            "topic_id": topic_id,
            "topic_title": topic_title,
            "subtopic": self.subtopic_editor.text().strip(),
            "correct_answer": correct_answer,
            "bilingual": {
                "zh": {
                    "stem": self.zh_stem_editor.toPlainText().strip(),
                    "options": zh_options,
                    "explanation": self.zh_explanation_editor.toPlainText().strip(),
                },
                "en": {
                    "stem": self.en_stem_editor.toPlainText().strip(),
                    "options": en_options,
                    "explanation": self.en_explanation_editor.toPlainText().strip(),
                },
            },
            "metadata": metadata,
        }

    def _load_choice_options(self, zh_options, en_options):
        for row in range(4):
            self.choice_table.item(row, 1).setText(self._option_text(zh_options, row))
            self.choice_table.item(row, 2).setText(self._option_text(en_options, row))

    @staticmethod
    def _option_text(options, index: int) -> str:
        if not isinstance(options, list) or index >= len(options):
            return ""
        option = options[index]
        if isinstance(option, dict):
            return str(option.get("text") or option.get("label") or "")
        return str(option or "")

    def _choice_options(self, column: int) -> list[str]:
        values = []
        for row, label in enumerate("ABCD"):
            text = self.choice_table.item(row, column).text().strip()
            values.append(text if text.upper().startswith(f"{label}.") else f"{label}. {text}")
        return values

    def _add_matching_row(self, values=None):
        row = self.matching_table.rowCount()
        self.matching_table.insertRow(row)
        if values is None:
            left_ids = set()
            right_ids = set()
            for existing_row in range(row):
                left_id, right_id = self.matching_table.item(existing_row, 0).data(Qt.ItemDataRole.UserRole)
                left_ids.add(left_id)
                right_ids.add(right_id)
            values = (
                self._next_id("match", left_ids),
                "",
                "",
                self._next_id("answer", right_ids),
                "",
                "",
            )
        left_id, zh_left, en_left, right_id, zh_right, en_right = values
        id_item = QTableWidgetItem(f"{left_id} → {right_id}")
        id_item.setData(Qt.ItemDataRole.UserRole, (str(left_id), str(right_id)))
        id_item.setFlags(id_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.matching_table.setItem(row, 0, id_item)
        for column, text in enumerate((zh_left, en_left, zh_right, en_right), start=1):
            self.matching_table.setItem(row, column, QTableWidgetItem(str(text or "")))

    def _remove_matching_row(self):
        row = self.matching_table.currentRow()
        if row >= 0 and self.matching_table.rowCount() > 1:
            self.matching_table.removeRow(row)

    def _load_matching_options(self, zh_options, en_options, correct_answer):
        zh_left = self._option_map((zh_options or {}).get("left", []), "left")
        zh_right = self._option_map((zh_options or {}).get("right", []), "right")
        en_left = self._option_map((en_options or {}).get("left", []), "left")
        en_right = self._option_map((en_options or {}).get("right", []), "right")
        pairs = [
            (str(pair[0]), str(pair[1]))
            for pair in (correct_answer or [])
            if isinstance(pair, (list, tuple)) and len(pair) == 2
        ]
        if not pairs:
            pairs = list(zip(zh_left, zh_right))
        self.matching_table.setRowCount(0)
        for left_id, right_id in pairs:
            self._add_matching_row((
                left_id,
                zh_left.get(left_id, ""),
                en_left.get(left_id, zh_left.get(left_id, "")),
                right_id,
                zh_right.get(right_id, ""),
                en_right.get(right_id, zh_right.get(right_id, "")),
            ))
        if not pairs:
            self._add_matching_row()

    @staticmethod
    def _option_map(options, prefix: str) -> dict[str, str]:
        result = {}
        for index, option in enumerate(options or []):
            if isinstance(option, dict):
                option_id = str(option.get("id") or option.get("value") or f"{prefix}_{index + 1}")
                text = str(option.get("text") or option.get("label") or "")
            else:
                option_id = f"{prefix}_{index + 1}"
                text = str(option or "")
            result[option_id] = text
        return result

    def _matching_payload(self):
        zh_left = []
        en_left = []
        zh_right = []
        en_right = []
        answer = []
        for row in range(self.matching_table.rowCount()):
            left_id, right_id = self.matching_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            zh_left.append({"id": left_id, "text": self.matching_table.item(row, 1).text().strip()})
            en_left.append({"id": left_id, "text": self.matching_table.item(row, 2).text().strip()})
            zh_right.append({"id": right_id, "text": self.matching_table.item(row, 3).text().strip()})
            en_right.append({"id": right_id, "text": self.matching_table.item(row, 4).text().strip()})
            answer.append([left_id, right_id])
        return (
            {"left": zh_left, "right": zh_right},
            {"left": en_left, "right": en_right},
            answer,
        )

    def _add_ordering_row(self, values=None):
        row = self.ordering_table.rowCount()
        self.ordering_table.insertRow(row)
        if values is None:
            existing_ids = {
                self.ordering_table.item(existing_row, 0).text()
                for existing_row in range(row)
            }
            values = (self._next_id("step", existing_ids), "", "")
        option_id, zh_text, en_text = values
        id_item = QTableWidgetItem(str(option_id))
        id_item.setFlags(id_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.ordering_table.setItem(row, 0, id_item)
        self.ordering_table.setItem(row, 1, QTableWidgetItem(str(zh_text or "")))
        self.ordering_table.setItem(row, 2, QTableWidgetItem(str(en_text or "")))

    def _remove_ordering_row(self):
        row = self.ordering_table.currentRow()
        if row >= 0 and self.ordering_table.rowCount() > 1:
            self.ordering_table.removeRow(row)

    def _move_ordering_row(self, offset: int):
        row = self.ordering_table.currentRow()
        target = row + offset
        if row < 0 or target < 0 or target >= self.ordering_table.rowCount():
            return
        current_items = [self.ordering_table.takeItem(row, column) for column in range(3)]
        target_items = [self.ordering_table.takeItem(target, column) for column in range(3)]
        for column in range(3):
            self.ordering_table.setItem(row, column, target_items[column])
            self.ordering_table.setItem(target, column, current_items[column])
        self.ordering_table.selectRow(target)

    def _load_ordering_options(self, zh_options, en_options, correct_answer):
        zh_map = self._option_map(zh_options, "step")
        en_map = self._option_map(en_options, "step")
        order = [str(value) for value in (correct_answer or []) if str(value).strip()]
        if not order:
            order = list(zh_map)
        self.ordering_table.setRowCount(0)
        for option_id in order:
            self._add_ordering_row((
                option_id,
                zh_map.get(option_id, ""),
                en_map.get(option_id, zh_map.get(option_id, "")),
            ))
        if not order:
            self._add_ordering_row()

    def _ordering_payload(self):
        zh_options = []
        en_options = []
        answer = []
        for row in range(self.ordering_table.rowCount()):
            option_id = self.ordering_table.item(row, 0).text().strip()
            answer.append(option_id)
            zh_options.append({"id": option_id, "text": self.ordering_table.item(row, 1).text().strip()})
            en_options.append({"id": option_id, "text": self.ordering_table.item(row, 2).text().strip()})
        return zh_options, en_options, answer

    @staticmethod
    def _next_id(prefix: str, existing_ids) -> str:
        index = 1
        while f"{prefix}_{index}" in existing_ids:
            index += 1
        return f"{prefix}_{index}"

    def _on_type_changed(self):
        question_type = self.type_combo.currentData()
        if question_type in {QuestionType.MULTIPLE_CHOICE.value, QuestionType.SCENARIO_CHOICE.value}:
            self.answer_stack.setCurrentWidget(self.choice_panel)
        elif question_type == QuestionType.TRUE_FALSE.value:
            self.answer_stack.setCurrentWidget(self.true_false_panel)
        elif question_type == QuestionType.MATCHING.value:
            self.answer_stack.setCurrentWidget(self.matching_panel)
        elif question_type == QuestionType.ORDERING.value:
            self.answer_stack.setCurrentWidget(self.ordering_panel)
        elif question_type == QuestionType.FILL_IN_BLANK.value:
            self.answer_stack.setCurrentWidget(self.fill_panel)
        elif question_type == QuestionType.SHORT_ANSWER.value:
            self.answer_stack.setCurrentWidget(self.short_answer_panel)
        else:
            self.answer_stack.setCurrentWidget(self.choice_panel)

    def _update_texts(self, _lang=None):
        for index, question_type in enumerate(QuestionType):
            self.type_combo.setItemText(index, self.lang_manager.get_text(*_TYPE_LABELS[question_type]))
        for difficulty in Difficulty:
            index = self.difficulty_combo.findData(difficulty.value)
            if index >= 0:
                self.difficulty_combo.setItemText(
                    index,
                    self.lang_manager.get_text(*_DIFFICULTY_LABELS[difficulty]),
                )
        self.type_label.setText(self.lang_manager.get_text("题型", "Type"))
        self.difficulty_label.setText(self.lang_manager.get_text("难度", "Difficulty"))
        self.topic_label.setText(self.lang_manager.get_text("知识点", "Topic"))
        self.subtopic_label.setText(self.lang_manager.get_text("子主题", "Subtopic"))
        if self.topic_combo.count() and self.topic_combo.itemData(0) == "general":
            self.topic_combo.setItemText(0, self.lang_manager.get_text("通用", "General"))
        for stem_label, explanation_label in self._language_field_labels.values():
            stem_label.setText(self.lang_manager.get_text("题干", "Stem"))
            explanation_label.setText(self.lang_manager.get_text("解析", "Explanation"))
        self.language_tabs.setTabText(0, self.lang_manager.get_text("中文", "Chinese"))
        self.language_tabs.setTabText(1, "English")
        self.answer_label.setText(self.lang_manager.get_text("选项与答案", "Options and Answer"))
        self.choice_table.setHorizontalHeaderLabels([
            "",
            self.lang_manager.get_text("中文", "Chinese"),
            "English",
        ])
        self.choice_answer_label.setText(self.lang_manager.get_text("正确选项", "Correct option"))
        self.true_false_options_label.setText(self.lang_manager.get_text("选项", "Options"))
        self.true_false_answer_label.setText(self.lang_manager.get_text("正确答案", "Correct answer"))
        self.true_false_options_text.setText(self.lang_manager.get_text(
            "选项固定为：正确 / 错误",
            "Options are fixed: True / False",
        ))
        self.true_false_answer_combo.setItemText(0, self.lang_manager.get_text("正确", "True"))
        self.true_false_answer_combo.setItemText(1, self.lang_manager.get_text("错误", "False"))
        self.matching_table.setHorizontalHeaderLabels([
            "ID",
            self.lang_manager.get_text("左项（中文）", "Left (ZH)"),
            self.lang_manager.get_text("左项（英文）", "Left (EN)"),
            self.lang_manager.get_text("右项（中文）", "Right (ZH)"),
            self.lang_manager.get_text("右项（英文）", "Right (EN)"),
        ])
        self.add_matching_row_btn.setText(self.lang_manager.get_text("添加配对", "Add Pair"))
        self.remove_matching_row_btn.setText(self.lang_manager.get_text("移除配对", "Remove Pair"))
        self.ordering_table.setHorizontalHeaderLabels([
            "ID",
            self.lang_manager.get_text("步骤（中文）", "Step (ZH)"),
            self.lang_manager.get_text("步骤（英文）", "Step (EN)"),
        ])
        self.add_ordering_row_btn.setText(self.lang_manager.get_text("添加步骤", "Add Step"))
        self.remove_ordering_row_btn.setText(self.lang_manager.get_text("移除步骤", "Remove Step"))
        self.move_ordering_up_btn.setText(self.lang_manager.get_text("上移", "Move Up"))
        self.move_ordering_down_btn.setText(self.lang_manager.get_text("下移", "Move Down"))
        self.fill_answers_label.setText(self.lang_manager.get_text("可接受答案", "Accepted answers"))
        self.fill_answers_editor.setPlaceholderText(self.lang_manager.get_text(
            "每行一个可接受答案",
            "One acceptable answer per line",
        ))
        self.short_answer_label.setText(self.lang_manager.get_text("参考答案", "Reference answer"))
        self.short_answer_editor.setPlaceholderText(self.lang_manager.get_text(
            "填写供人工评分参考的答案要点",
            "Enter reference points for manual grading",
        ))
        self._on_type_changed()
