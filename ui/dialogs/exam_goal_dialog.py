"""Compact editor for one course exam goal."""

from __future__ import annotations

from datetime import date, timedelta

from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import (
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QSpinBox,
    QVBoxLayout,
)

from core.exam_goal_store import ExamGoal
from core.language_manager import LanguageManager


class ExamGoalDialog(QDialog):
    def __init__(self, course_id: str, current: ExamGoal | None = None, parent=None):
        super().__init__(parent)
        self.course_id = str(course_id or "").strip()
        gm = LanguageManager.instance().get_text
        self.setWindowTitle(gm("考试目标", "Exam Goal"))

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.exam_date = QDateEdit()
        self.exam_date.setCalendarPopup(True)
        initial_date = (
            date.fromisoformat(current.exam_date)
            if current is not None
            else date.today() + timedelta(days=30)
        )
        self.exam_date.setDate(
            QDate(initial_date.year, initial_date.month, initial_date.day)
        )
        form.addRow(gm("考试日期", "Exam date"), self.exam_date)

        self.daily_minutes = QSpinBox()
        self.daily_minutes.setRange(10, 480)
        self.daily_minutes.setSuffix(gm(" 分钟", " min"))
        self.daily_minutes.setValue(current.daily_minutes if current else 30)
        form.addRow(gm("每日可投入", "Daily time"), self.daily_minutes)

        self.target_mastery = QDoubleSpinBox()
        self.target_mastery.setRange(50, 100)
        self.target_mastery.setSuffix("%")
        self.target_mastery.setValue(
            current.target_mastery * 100 if current else 80
        )
        form.addRow(gm("目标掌握度", "Target mastery"), self.target_mastery)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def goal(self, topic_ids=()) -> ExamGoal:
        selected = self.exam_date.date()
        return ExamGoal(
            course_id=self.course_id,
            exam_date=date(
                selected.year(),
                selected.month(),
                selected.day(),
            ).isoformat(),
            daily_minutes=self.daily_minutes.value(),
            target_mastery=self.target_mastery.value() / 100,
            included_topic_ids=tuple(topic_ids or ()),
        )
