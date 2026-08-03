"""Wheel-safe input controls for forms embedded in scroll areas.

Qt spin boxes, combo boxes, and sliders can consume mouse-wheel events while the
user is only trying to scroll the surrounding page. These subclasses only handle
wheel changes after the control has explicit focus; otherwise they ignore the
event so the parent scroll area can continue scrolling.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QComboBox, QSlider, QSpinBox


class _WheelSafeMixin:
    """Mixin that prevents accidental value changes from scroll-hover events."""

    def _init_wheel_safe(self) -> None:
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setProperty("wheelSafe", True)
        # Do not let an imported course title or topic label determine the
        # minimum width of every parent form. Long labels remain available in
        # the popup, while the closed control stays responsive on narrow
        # windows and with large fonts.
        if isinstance(self, QComboBox):
            self.setMinimumContentsLength(12)
            self.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
            )

    def wheelEvent(self, event):  # noqa: N802 - Qt method name
        if not self.hasFocus():
            event.ignore()
            return
        super().wheelEvent(event)


class WheelSafeSpinBox(_WheelSafeMixin, QSpinBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_wheel_safe()


class WheelSafeComboBox(_WheelSafeMixin, QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_wheel_safe()


class WheelSafeSlider(_WheelSafeMixin, QSlider):
    def __init__(self, orientation: Qt.Orientation, parent=None):
        super().__init__(orientation, parent)
        self._init_wheel_safe()
