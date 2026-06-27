import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QApplication

from ui.dialogs.ai_generation_dialog import AIGenerationDialog
from ui.screens.settings_screen import SettingsScreen
from ui.widgets.wheel_safe_controls import (
    WheelSafeComboBox,
    WheelSafeSlider,
    WheelSafeSpinBox,
)


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


if __name__ == "__main__":
    unittest.main()
