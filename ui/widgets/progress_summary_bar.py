"""Progress summary bar — custom painted horizontal bar."""

from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QPainter, QColor, QFont, QPen


def _draw_clipped_label(
    painter: QPainter,
    rect: QRectF,
    text: str,
    minimum_width: float = 30,
) -> None:
    if rect.width() <= minimum_width:
        return
    painter.save()
    painter.setClipRect(rect)
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
    painter.restore()


class ProgressSummaryBar(QWidget):
    """Horizontal bar showing correct/incorrect/unanswered proportions."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._correct = 0
        self._incorrect = 0
        self._unanswered = 0
        self.setMinimumHeight(32)
        self.setMinimumWidth(200)

    def set_values(self, correct: int, incorrect: int, unanswered: int):
        self._correct = correct
        self._incorrect = incorrect
        self._unanswered = unanswered
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        total = self._correct + self._incorrect + self._unanswered
        if total == 0:
            return

        w = self.width()
        h = self.height()
        rect = QRectF(0, 0, w, h)

        # Proportions
        correct_w = (self._correct / total) * w
        incorrect_w = (self._incorrect / total) * w
        unanswered_w = (self._unanswered / total) * w

        # Colors
        green = QColor("#4CAF50")
        red = QColor("#F44336")
        grey = QColor("#BDBDBD")
        label_font = QFont("Arial", 10, QFont.Weight.Bold)

        x = 0.0

        # Correct segment
        if correct_w > 0:
            painter.fillRect(QRectF(x, 0, correct_w, h), green)
            painter.setPen(Qt.GlobalColor.white)
            painter.setFont(label_font)
            _draw_clipped_label(painter, QRectF(x, 0, correct_w, h), str(self._correct))
            x += correct_w

        # Incorrect segment
        if incorrect_w > 0:
            painter.fillRect(QRectF(x, 0, incorrect_w, h), red)
            painter.setPen(Qt.GlobalColor.white)
            painter.setFont(label_font)
            _draw_clipped_label(painter, QRectF(x, 0, incorrect_w, h), str(self._incorrect))
            x += incorrect_w

        # Unanswered segment
        if unanswered_w > 0:
            painter.fillRect(QRectF(x, 0, unanswered_w, h), grey)

        # Border
        painter.setPen(QPen(QColor("#DDD"), 1))
        painter.drawRect(rect.adjusted(0, 0, -1, -1))
        painter.end()

    def sizeHint(self):
        return self.minimumSizeHint()

    def minimumSizeHint(self):
        from PyQt6.QtCore import QSize
        return QSize(200, 32)
