"""Answer area widget — type-switched input widgets."""

from PyQt6.QtWidgets import (
    QWidget, QStackedWidget, QVBoxLayout, QHBoxLayout,
    QButtonGroup, QRadioButton, QCheckBox, QComboBox,
    QListWidget, QListWidgetItem, QPushButton, QLineEdit, QPlainTextEdit,
    QLabel, QFrame
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QFont

from utils.constants import QuestionType
from core.language_manager import LanguageManager
from ui.widgets.wheel_safe_controls import WheelSafeComboBox


def _option_id(option) -> str:
    """Return the stable ID for a question option, falling back to its label."""
    if isinstance(option, dict):
        value = option.get("id") or option.get("value") or option.get("key")
        if value is not None and str(value).strip():
            return str(value).strip()
    return _option_label(option)


def _option_label(option, lang: str | None = None) -> str:
    """Return the display label for a question option."""
    if isinstance(option, dict):
        candidates = []
        if lang:
            candidates.append(option.get(lang))
        candidates.extend([
            option.get("text"),
            option.get("label"),
            option.get("title"),
            option.get("name"),
            option.get("id"),
            option.get("value"),
        ])
        for candidate in candidates:
            if candidate is not None and str(candidate).strip():
                return str(candidate).strip()
    return str(option)


class AnswerArea(QWidget):
    """Container that switches between type-specific answer input widgets."""

    answer_submitted = pyqtSignal(object)  # raw answer value

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_type = None
        self.lang_manager = LanguageManager.instance()

        self.stack = QStackedWidget(self)

        # Create type-specific widgets
        self.choice_widget = MultipleChoiceWidget()
        self.true_false_widget = TrueFalseWidget()
        self.matching_widget = MatchingWidget()
        self.ordering_widget = OrderingWidget()
        self.fill_widget = FillInBlankWidget()
        self.short_widget = ShortAnswerWidget()

        self.stack.addWidget(self.choice_widget)       # 0
        self.stack.addWidget(self.true_false_widget)    # 1
        self.stack.addWidget(self.matching_widget)      # 2
        self.stack.addWidget(self.ordering_widget)      # 3
        self.stack.addWidget(self.fill_widget)          # 4
        self.stack.addWidget(self.short_widget)         # 5

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stack)

        # Connect signals
        self.choice_widget.answer_ready.connect(self.answer_submitted.emit)
        self.true_false_widget.answer_ready.connect(self.answer_submitted.emit)
        self.matching_widget.answer_ready.connect(self.answer_submitted.emit)
        self.ordering_widget.answer_ready.connect(self.answer_submitted.emit)
        self.fill_widget.answer_ready.connect(self.answer_submitted.emit)
        self.short_widget.answer_ready.connect(self.answer_submitted.emit)

        self.lang_manager.language_changed.connect(self._on_language_changed)

    def _on_language_changed(self, lang):
        """Update all child widget texts on language change."""
        self.true_false_widget._on_language_changed(lang)
        self.matching_widget._on_language_changed(lang)
        self.ordering_widget._on_language_changed(lang)
        self.fill_widget._on_language_changed(lang)
        self.short_widget._on_language_changed(lang)

    def set_question_type(self, qtype: QuestionType, options: list = None, preserve_answer: bool = False):
        """Switch to the correct answer input widget for the question type."""
        previous_answer = self.get_answer() if preserve_answer and qtype == self._current_type else None
        if not preserve_answer:
            self.clear()
        self._current_type = qtype

        if qtype in (QuestionType.MULTIPLE_CHOICE, QuestionType.SCENARIO_CHOICE):
            self.stack.setCurrentWidget(self.choice_widget)
            if options:
                self.choice_widget.set_options(options)
            self.choice_widget.set_answer(previous_answer)
        elif qtype == QuestionType.TRUE_FALSE:
            self.stack.setCurrentWidget(self.true_false_widget)
            if options:
                self.true_false_widget.set_options(options)
            self.true_false_widget.set_answer(previous_answer)
        elif qtype == QuestionType.MATCHING:
            self.stack.setCurrentWidget(self.matching_widget)
            if options:
                self.matching_widget.set_options(options)
            self.matching_widget.set_answer(previous_answer)
        elif qtype == QuestionType.ORDERING:
            self.stack.setCurrentWidget(self.ordering_widget)
            if options:
                self.ordering_widget.set_options(options)
            self.ordering_widget.set_answer(previous_answer)
        elif qtype == QuestionType.FILL_IN_BLANK:
            self.stack.setCurrentWidget(self.fill_widget)
            self.fill_widget.set_answer(previous_answer)
        elif qtype == QuestionType.SHORT_ANSWER:
            self.stack.setCurrentWidget(self.short_widget)
            self.short_widget.set_answer(previous_answer)

    def get_answer(self) -> object:
        """Get the current answer from the active widget."""
        widget = self.stack.currentWidget()
        if hasattr(widget, "get_answer"):
            return widget.get_answer()
        return None

    def set_answer(self, answer):
        """Restore an answer into the active type-specific widget."""
        widget = self.stack.currentWidget()
        if hasattr(widget, "set_answer"):
            widget.set_answer(answer)

    def has_answer(self) -> bool:
        """Return whether the active widget currently contains a meaningful answer."""
        answer = self.get_answer()
        if answer is None:
            return False
        if self._current_type == QuestionType.MATCHING:
            return self.matching_widget.is_complete()
        if isinstance(answer, str):
            return bool(answer.strip())
        if isinstance(answer, list):
            return len(answer) > 0
        return bool(answer)

    def clear(self):
        """Reset all answer widgets."""
        self.choice_widget.clear()
        self.true_false_widget.clear()
        self.matching_widget.clear()
        self.ordering_widget.clear()
        self.fill_widget.clear()
        self.short_widget.clear()

    def set_enabled(self, enabled: bool):
        """Enable or disable answer input."""
        for i in range(self.stack.count()):
            w = self.stack.widget(i)
            w.setEnabled(enabled)


class MultipleChoiceWidget(QWidget):
    """Radio buttons for single-choice questions."""

    answer_ready = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.lang_manager = LanguageManager.instance()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.group = QButtonGroup(self)
        self.buttons: list[QRadioButton] = []
        layout.addStretch()

        self.lang_manager.language_changed.connect(self._on_language_changed)

    def _on_language_changed(self, lang):
        """No translatable static strings in this widget."""
        pass

    def set_options(self, options: list):
        """Set option labels (e.g., ['A. ...', 'B. ...', ...])."""
        self.clear()
        for opt in options:
            btn = QRadioButton(opt)
            btn.setObjectName("answerOption")
            self.group.addButton(btn, len(self.buttons))
            self.layout().insertWidget(self.layout().count() - 1, btn)
            self.buttons.append(btn)
            btn.toggled.connect(self._on_selection)

    def _on_selection(self, checked):
        sender = self.sender()
        if sender is not None and sender not in self.buttons:
            return
        if checked:
            for i, btn in enumerate(self.buttons):
                if btn.isChecked():
                    label = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                    if i < len(label):
                        self.answer_ready.emit(label[i])

    def get_answer(self) -> str:
        label = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        for i, btn in enumerate(self.buttons):
            if btn.isChecked():
                return label[i] if i < len(label) else ""
        return ""

    def set_answer(self, answer):
        """Restore a selected option by answer letter."""
        if not answer:
            return
        label = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        try:
            index = label.index(str(answer).strip().upper())
        except ValueError:
            return
        if 0 <= index < len(self.buttons):
            self.buttons[index].setChecked(True)

    def clear(self):
        for btn in self.buttons:
            try:
                btn.toggled.disconnect(self._on_selection)
            except TypeError:
                pass
            self.group.removeButton(btn)
            self.layout().removeWidget(btn)
            btn.deleteLater()
        self.buttons.clear()


class TrueFalseWidget(QWidget):
    """True/False radio buttons."""

    answer_ready = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.lang_manager = LanguageManager.instance()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.true_btn = QRadioButton(self.lang_manager.get_text("正确", "True"))
        self.false_btn = QRadioButton(self.lang_manager.get_text("错误", "False"))
        self.true_btn.setObjectName("answerOption")
        self.false_btn.setObjectName("answerOption")

        layout.addWidget(self.true_btn)
        layout.addWidget(self.false_btn)
        layout.addStretch()

        self.true_btn.toggled.connect(self._on_toggle)
        self.false_btn.toggled.connect(self._on_toggle)

        self.lang_manager.language_changed.connect(self._on_language_changed)

    def _on_language_changed(self, lang):
        """Update True/False radio button labels."""
        self.true_btn.setText(self.lang_manager.get_text("正确", "True"))
        self.false_btn.setText(self.lang_manager.get_text("错误", "False"))

    def set_options(self, options: list):
        """Set bilingual labels for true/false."""
        if len(options) >= 1:
            self.true_btn.setText(options[0])
        if len(options) >= 2:
            self.false_btn.setText(options[1])

    def _on_toggle(self, checked):
        if checked:
            if self.true_btn.isChecked():
                self.answer_ready.emit("true")
            elif self.false_btn.isChecked():
                self.answer_ready.emit("false")

    def get_answer(self) -> str:
        if self.true_btn.isChecked():
            return "true"
        elif self.false_btn.isChecked():
            return "false"
        return ""

    def set_answer(self, answer):
        """Restore a true/false selection."""
        if str(answer).lower() == "true":
            self.true_btn.setChecked(True)
        elif str(answer).lower() == "false":
            self.false_btn.setChecked(True)

    def clear(self):
        for btn in (self.true_btn, self.false_btn):
            btn.setAutoExclusive(False)
            btn.setChecked(False)
            btn.setAutoExclusive(True)


class MatchingWidget(QWidget):
    """Matching exercise: left items fixed, right side uses QComboBox for pairing."""

    answer_ready = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.lang_manager = LanguageManager.instance()

        self._main_layout = QHBoxLayout(self)

        # Left items
        left_layout = QVBoxLayout()
        self.left_label = QLabel(self.lang_manager.get_text("项目:", "Items:"))
        left_layout.addWidget(self.left_label)
        self.left_list = QListWidget()
        self.left_list.setObjectName("matchingLeftList")
        left_layout.addWidget(self.left_list)

        # Right side: one combo per left item, built by set_options()
        self._right_layout = QVBoxLayout()
        self._right_label = QLabel(self.lang_manager.get_text("匹配:", "Matches:"))
        self._right_layout.addWidget(self._right_label)
        self._right_layout.addStretch()

        self._main_layout.addLayout(left_layout)
        self._main_layout.addLayout(self._right_layout)

        self.combos: list[QComboBox] = []
        self.left_item_labels: list[QLabel] = []
        self.right_items: list[str] = []

        self.lang_manager.language_changed.connect(self._on_language_changed)

    def _on_language_changed(self, lang):
        """Update matching widget labels."""
        self.left_label.setText(self.lang_manager.get_text("项目:", "Items:"))
        self._right_label.setText(self.lang_manager.get_text("匹配:", "Matches:"))

    def set_options(self, options: dict):
        """options = {"left": [...], "right": [...]}"""
        self.clear()
        right_opts = options.get("right", []) if isinstance(options, dict) else []
        lang = self.lang_manager.current
        right_records = [(_option_id(option), _option_label(option, lang)) for option in right_opts]
        self.right_items = [option_id for option_id, _label in right_records]

        if isinstance(options, dict) and "left" in options:
            import random
            shuffled_right = list(right_records)
            random.shuffle(shuffled_right)

            # Remove the stretch from right layout temporarily
            stretch = self._right_layout.takeAt(self._right_layout.count() - 1)

            for item in options["left"]:
                left_id = _option_id(item)
                left_text = _option_label(item, lang)
                list_item = QListWidgetItem(left_text)
                list_item.setData(Qt.ItemDataRole.UserRole, left_id)
                self.left_list.addItem(list_item)
                left_lbl = QLabel(left_text)
                left_lbl.setObjectName("matchingLeftItem")
                left_lbl.setMinimumWidth(120)
                combo = WheelSafeComboBox()
                combo.setObjectName("matchingCombo")
                combo.addItem("---", "")
                for right_id, right_label in shuffled_right:
                    combo.addItem(right_label, right_id)
                combo.currentIndexChanged.connect(lambda idx: self._emit_pairs())
                self.left_item_labels.append(left_lbl)
                self.combos.append(combo)

                row = QHBoxLayout()
                row.addWidget(left_lbl)
                row.addWidget(combo, 1)
                self._right_layout.addLayout(row)

            self._right_layout.addStretch()

    def _emit_pairs(self):
        pairs = self.get_answer()
        self.answer_ready.emit(pairs)

    def get_answer(self) -> list:
        """Return pairs as [[left_id, selected_right_id], ...]."""
        pairs = []
        for i in range(self.left_list.count()):
            item = self.left_list.item(i)
            left_id = item.data(Qt.ItemDataRole.UserRole) or item.text()
            right_id = self.combos[i].currentData() if i < len(self.combos) else ""
            pairs.append([str(left_id), str(right_id or "")])
        return pairs

    def is_complete(self) -> bool:
        """Return whether every left item has a selected right item."""
        pairs = self.get_answer()
        return bool(pairs) and all(
            len(pair) >= 2 and bool(str(pair[1]).strip())
            for pair in pairs
        )

    def set_answer(self, answer):
        """Restore matching selections when labels are still comparable."""
        if not isinstance(answer, list):
            return
        selected_by_left = {
            str(pair[0]): str(pair[1])
            for pair in answer
            if isinstance(pair, list) and len(pair) >= 2
        }
        for row in range(self.left_list.count()):
            item = self.left_list.item(row)
            left_id = str(item.data(Qt.ItemDataRole.UserRole) or item.text())
            left_text = item.text()
            selected = selected_by_left.get(left_id) or selected_by_left.get(left_text, "")
            if selected and row < len(self.combos):
                index = self.combos[row].findData(selected)
                if index < 0:
                    index = self.combos[row].findText(selected)
                if index >= 0:
                    self.combos[row].setCurrentIndex(index)

    def clear(self):
        self.left_list.clear()
        self.combos.clear()
        self.left_item_labels.clear()
        self.right_items.clear()
        # Remove all dynamic rows and the old stretch, then restore a single stretch.
        while self._right_layout.count() > 1:  # keep the static label
            item = self._right_layout.takeAt(1)
            self._delete_layout_item(item)
        self._right_layout.addStretch()

    def _delete_layout_item(self, item):
        """Delete a layout item and any child widgets/layouts it owns."""
        if item is None:
            return
        widget = item.widget()
        if widget:
            widget.deleteLater()
            return
        layout = item.layout()
        if layout:
            while layout.count():
                self._delete_layout_item(layout.takeAt(0))


class OrderingWidget(QWidget):
    """Ordering exercise with move-up/move-down buttons."""

    answer_ready = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.lang_manager = LanguageManager.instance()
        self._user_reordered = False

        layout = QVBoxLayout(self)

        self.list_widget = QListWidget()
        self.list_widget.setObjectName("orderingList")
        self.list_widget.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.list_widget.model().rowsMoved.connect(lambda *args: self._mark_user_reordered())

        btn_layout = QHBoxLayout()
        self.up_btn = QPushButton(self.lang_manager.get_text("上移", "Up"))
        self.up_btn.setObjectName("secondaryButton")
        self.down_btn = QPushButton(self.lang_manager.get_text("下移", "Down"))
        self.down_btn.setObjectName("secondaryButton")
        btn_layout.addStretch()
        btn_layout.addWidget(self.up_btn)
        btn_layout.addWidget(self.down_btn)
        btn_layout.addStretch()

        self.instruction_label = QLabel(self.lang_manager.get_text(
            "拖拽排序（正确顺序为从上到下）:",
            "Drag to reorder (correct order = top to bottom):"
        ))
        layout.addWidget(self.instruction_label)
        layout.addWidget(self.list_widget)
        layout.addLayout(btn_layout)

        self.up_btn.clicked.connect(self._move_up)
        self.down_btn.clicked.connect(self._move_down)

        self.lang_manager.language_changed.connect(self._on_language_changed)

    def _on_language_changed(self, lang):
        """Update ordering widget labels and buttons."""
        self.instruction_label.setText(self.lang_manager.get_text(
            "拖拽排序（正确顺序为从上到下）:",
            "Drag to reorder (correct order = top to bottom):"
        ))
        self.up_btn.setText(self.lang_manager.get_text("上移", "Up"))
        self.down_btn.setText(self.lang_manager.get_text("下移", "Down"))

    def set_options(self, options: list):
        self.clear()
        lang = self.lang_manager.current
        for opt in options:
            item = QListWidgetItem(_option_label(opt, lang))
            item.setData(Qt.ItemDataRole.UserRole, _option_id(opt))
            self.list_widget.addItem(item)
        self._user_reordered = False

    def _move_up(self):
        row = self.list_widget.currentRow()
        if row > 0:
            self._mark_user_reordered()
            item = self.list_widget.takeItem(row)
            self.list_widget.insertItem(row - 1, item)
            self.list_widget.setCurrentRow(row - 1)
            self._emit_order()

    def _move_down(self):
        row = self.list_widget.currentRow()
        if row < self.list_widget.count() - 1:
            self._mark_user_reordered()
            item = self.list_widget.takeItem(row)
            self.list_widget.insertItem(row + 1, item)
            self.list_widget.setCurrentRow(row + 1)
            self._emit_order()

    def _mark_user_reordered(self):
        self._user_reordered = True

    def has_user_reordered(self) -> bool:
        """Return whether the user has explicitly changed the default order."""
        return self._user_reordered

    def _emit_order(self):
        self.answer_ready.emit(self.get_answer())

    def get_answer(self) -> list:
        order = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            order.append(str(item.data(Qt.ItemDataRole.UserRole) or item.text()))
        return order

    def set_answer(self, answer):
        """Restore ordering by stable IDs, falling back to labels for legacy answers."""
        if not isinstance(answer, list):
            return
        available: dict[str, QListWidgetItem] = {}
        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)
            item_id = str(item.data(Qt.ItemDataRole.UserRole) or item.text())
            available[item_id] = item
            available[item.text()] = item
        selected_items = []
        for raw in answer:
            item = available.get(str(raw))
            if item is None or item in selected_items:
                return
            selected_items.append(item)
        if len(selected_items) != self.list_widget.count():
            return
        selected_payload = [
            (item.text(), item.data(Qt.ItemDataRole.UserRole) or item.text())
            for item in selected_items
        ]
        self.list_widget.clear()
        for text, item_id in selected_payload:
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, item_id)
            self.list_widget.addItem(item)
        self._user_reordered = True

    def clear(self):
        self.list_widget.clear()
        self._user_reordered = False


class FillInBlankWidget(QWidget):
    """Text input for fill-in-the-blank questions."""

    answer_ready = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.lang_manager = LanguageManager.instance()

        layout = QVBoxLayout(self)
        self.label = QLabel(self.lang_manager.get_text("输入答案:", "Enter your answer:"))
        layout.addWidget(self.label)
        self.input = QLineEdit()
        self.input.setObjectName("fillInput")
        self.input.setPlaceholderText(self.lang_manager.get_text("在此输入答案...", "Type your answer here..."))
        self.input.textChanged.connect(lambda t: self.answer_ready.emit(t))
        layout.addWidget(self.input)
        layout.addStretch()

        self.lang_manager.language_changed.connect(self._on_language_changed)

    def _on_language_changed(self, lang):
        """Update fill-in-the-blank label and placeholder."""
        self.label.setText(self.lang_manager.get_text("输入答案:", "Enter your answer:"))
        self.input.setPlaceholderText(self.lang_manager.get_text("在此输入答案...", "Type your answer here..."))

    def get_answer(self) -> str:
        return self.input.text().strip()

    def set_answer(self, answer):
        if answer:
            self.input.setText(str(answer))

    def clear(self):
        self.input.clear()


class ShortAnswerWidget(QWidget):
    """Multi-line input for short answer questions."""

    answer_ready = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.lang_manager = LanguageManager.instance()

        layout = QVBoxLayout(self)
        self.label = QLabel(self.lang_manager.get_text("写下你的答案:", "Write your answer:"))
        layout.addWidget(self.label)
        self.editor = QPlainTextEdit()
        self.editor.setObjectName("shortAnswerInput")
        self.editor.setPlaceholderText(self.lang_manager.get_text("在此输入答案...", "Type your answer here..."))
        self.editor.setMinimumHeight(120)
        self.editor.textChanged.connect(lambda: self.answer_ready.emit(self.get_answer()))
        layout.addWidget(self.editor)
        layout.addStretch()

        self.lang_manager.language_changed.connect(self._on_language_changed)

    def _on_language_changed(self, lang):
        """Update short answer label and placeholder."""
        self.label.setText(self.lang_manager.get_text("写下你的答案:", "Write your answer:"))
        self.editor.setPlaceholderText(self.lang_manager.get_text("在此输入答案...", "Type your answer here..."))

    def get_answer(self) -> str:
        return self.editor.toPlainText().strip()

    def set_answer(self, answer):
        if answer:
            self.editor.setPlainText(str(answer))

    def clear(self):
        self.editor.clear()
