"""Read-only table model for the question-bank workbench."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt


@dataclass(frozen=True)
class QuestionTableRow:
    """Presentation data for one question without exposing its JSON payload."""

    question_id: str
    stem: str
    topic: str
    question_type: str
    difficulty: str
    status: str
    tooltip: str = ""


class QuestionTableModel(QAbstractTableModel):
    """Stable five-column model with question IDs stored outside visible text."""

    _HEADERS = {
        "zh": ("题目", "主题", "题型", "难度", "状态"),
        "en": ("Question", "Topic", "Type", "Difficulty", "Status"),
    }

    def __init__(self, *, language: str = "zh", parent=None):
        super().__init__(parent)
        self._language = language
        self._rows: tuple[QuestionTableRow, ...] = ()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._HEADERS["zh"])

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        row = self._rows[index.row()]
        if role == Qt.ItemDataRole.UserRole:
            return row.question_id
        if role == Qt.ItemDataRole.ToolTipRole:
            return row.tooltip
        if role == Qt.ItemDataRole.TextAlignmentRole and index.column() >= 2:
            return int(Qt.AlignmentFlag.AlignCenter)
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        return (
            row.stem,
            row.topic,
            row.question_type,
            row.difficulty,
            row.status,
        )[index.column()]

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if (
            orientation != Qt.Orientation.Horizontal
            or role != Qt.ItemDataRole.DisplayRole
            or not 0 <= section < self.columnCount()
        ):
            return None
        language = "en" if self._language == "en" else "zh"
        return self._HEADERS[language][section]

    def set_rows(self, rows: list[QuestionTableRow]) -> None:
        self.beginResetModel()
        self._rows = tuple(rows)
        self.endResetModel()

    def set_language(self, language: str) -> None:
        normalized = "en" if language == "en" else "zh"
        if normalized == self._language:
            return
        self._language = normalized
        self.headerDataChanged.emit(
            Qt.Orientation.Horizontal,
            0,
            self.columnCount() - 1,
        )

    def row_for_question_id(self, question_id: str) -> int:
        return next(
            (
                index
                for index, row in enumerate(self._rows)
                if row.question_id == question_id
            ),
            -1,
        )
