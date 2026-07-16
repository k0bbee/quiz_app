import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QRectF
from PyQt6.QtWidgets import QApplication

from ui.widgets.progress_summary_bar import ProgressSummaryBar


_APP = QApplication.instance() or QApplication([])


class RecordingPainter:
    last = None

    class RenderHint:
        Antialiasing = object()

    def __init__(self, *_args, **_kwargs):
        self.records = []
        RecordingPainter.last = self

    def setRenderHint(self, *_args):
        self.records.append(("render_hint",))

    def fillRect(self, rect, _color):
        self.records.append(("fill", QRectF(rect)))

    def setPen(self, *_args):
        self.records.append(("pen",))

    def setFont(self, *_args):
        self.records.append(("font",))

    def save(self):
        self.records.append(("save",))

    def setClipRect(self, rect):
        self.records.append(("clip", QRectF(rect)))

    def restore(self):
        self.records.append(("restore",))

    def drawText(self, rect, _alignment, text):
        self.records.append(("text", QRectF(rect), text))

    def drawRect(self, *_args):
        self.records.append(("border",))

    def end(self):
        self.records.append(("end",))


class ProgressSummaryBarTests(unittest.TestCase):
    def test_empty_bar_ends_painter_before_returning(self):
        bar = ProgressSummaryBar()
        bar.set_values(0, 0, 0)

        with patch("ui.widgets.progress_summary_bar.QPainter", RecordingPainter):
            bar.paintEvent(None)

        self.assertEqual("end", RecordingPainter.last.records[-1][0])

    def test_labels_are_clipped_to_their_own_segments(self):
        bar = ProgressSummaryBar()
        bar.resize(120, 32)
        bar.set_values(10, 10, 10)

        with patch("ui.widgets.progress_summary_bar.QPainter", RecordingPainter):
            bar.paintEvent(None)

        records = RecordingPainter.last.records
        text_indices = [idx for idx, record in enumerate(records) if record[0] == "text"]
        self.assertGreaterEqual(len(text_indices), 2)
        for idx in text_indices:
            preceding = records[idx - 2:idx]
            self.assertEqual("save", preceding[0][0])
            self.assertEqual("clip", preceding[1][0])
            self.assertEqual(records[idx][1], preceding[1][1])


if __name__ == "__main__":
    unittest.main()
