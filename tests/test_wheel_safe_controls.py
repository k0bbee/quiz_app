import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QApplication

from ui.dialogs.ai_generation_dialog import AIGenerationDialog
from ui.screens.question_bank_screen import QuestionBankScreen
from ui.screens.settings_screen import SettingsScreen
from ui.screens.topic_selection_screen import TopicSelectionScreen
from ui.widgets.answer_area import MatchingWidget
from ui.widgets.wheel_safe_controls import (
    WheelSafeComboBox,
    WheelSafeSlider,
    WheelSafeSpinBox,
)
from models.question import QuestionBank
from models.question_set import SetManager


_APP = QApplication.instance() or QApplication([])


def _wheel_event(delta: int = 120) -> QWheelEvent:
    return QWheelEvent(
        QPointF(4, 4),
        QPointF(4, 4),
        QPoint(0, 0),
        QPoint(0, delta),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )


class WheelSafeControlTests(unittest.TestCase):
    def test_spinbox_ignores_wheel_until_it_has_focus(self):
        spinbox = WheelSafeSpinBox()
        spinbox.setRange(0, 100)
        spinbox.setValue(40)
        spinbox.clearFocus()

        _APP.sendEvent(spinbox, _wheel_event())

        self.assertEqual(40, spinbox.value())
        self.assertTrue(spinbox.property("wheelSafe"))
        self.assertNotEqual(Qt.FocusPolicy.WheelFocus, spinbox.focusPolicy())

    def test_combobox_ignores_wheel_until_it_has_focus(self):
        combo = WheelSafeComboBox()
        combo.addItems(["first", "second", "third"])
        combo.setCurrentIndex(1)
        combo.clearFocus()

        _APP.sendEvent(combo, _wheel_event())

        self.assertEqual(1, combo.currentIndex())
        self.assertTrue(combo.property("wheelSafe"))
        self.assertNotEqual(Qt.FocusPolicy.WheelFocus, combo.focusPolicy())

    def test_slider_ignores_wheel_until_it_has_focus(self):
        slider = WheelSafeSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(80)
        slider.clearFocus()

        _APP.sendEvent(slider, _wheel_event())

        self.assertEqual(80, slider.value())
        self.assertTrue(slider.property("wheelSafe"))
        self.assertNotEqual(Qt.FocusPolicy.WheelFocus, slider.focusPolicy())

    def test_generation_dialog_weight_controls_are_wheel_safe(self):
        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
            available_topics=["cache", "process"],
        )

        controls = [
            dialog.count_spin,
            dialog.diff_combo,
            dialog.template_combo,
            dialog.mc_slider,
            dialog.scenario_slider,
            dialog.true_false_slider,
            dialog.fill_blank_slider,
            dialog.easy_slider,
            dialog.medium_slider,
            dialog.hard_slider,
            *dialog.topic_weight_sliders.values(),
        ]

        self.assertTrue(all(control.property("wheelSafe") for control in controls))

    def test_settings_default_controls_are_wheel_safe(self):
        screen = SettingsScreen()
        controls = [
            screen.lang_combo,
            screen.provider_combo,
            screen.model_combo,
            screen.default_question_count_input,
            screen.default_difficulty_combo,
            screen.default_template_combo,
            screen.default_mc_weight_input,
            screen.default_scenario_weight_input,
            screen.default_true_false_weight_input,
            screen.default_fill_blank_weight_input,
            screen.default_easy_weight_input,
            screen.default_medium_weight_input,
            screen.default_hard_weight_input,
        ]

        self.assertTrue(all(control.property("wheelSafe") for control in controls))

    def test_topic_selection_filters_are_wheel_safe(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            screen = TopicSelectionScreen(SetManager(tmpdir))

            self.assertIsInstance(screen.topic_filter, WheelSafeComboBox)
            self.assertIsInstance(screen.difficulty_filter, WheelSafeComboBox)
            self.assertTrue(screen.topic_filter.property("wheelSafe"))
            self.assertTrue(screen.difficulty_filter.property("wheelSafe"))

    def test_question_bank_filters_are_wheel_safe(self):
        with tempfile.TemporaryDirectory() as questions_dir, tempfile.TemporaryDirectory() as sets_dir:
            screen = QuestionBankScreen(QuestionBank(questions_dir), SetManager(sets_dir))

            self.assertIsInstance(screen.set_filter, WheelSafeComboBox)
            self.assertIsInstance(screen.difficulty_filter, WheelSafeComboBox)
            self.assertTrue(screen.set_filter.property("wheelSafe"))
            self.assertTrue(screen.difficulty_filter.property("wheelSafe"))

    def test_matching_answer_combos_are_wheel_safe(self):
        widget = MatchingWidget()
        widget.set_options({"left": ["CPU", "RAM"], "right": ["Processor", "Memory"]})

        self.assertTrue(widget.combos)
        self.assertTrue(all(isinstance(combo, WheelSafeComboBox) for combo in widget.combos))
        self.assertTrue(all(combo.property("wheelSafe") for combo in widget.combos))


if __name__ == "__main__":
    unittest.main()
