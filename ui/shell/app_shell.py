"""Reusable application shell for workspace and contextual navigation."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


class AppShell(QWidget):
    """Present the shared sidebar, context header, and screen stack."""

    def __init__(
        self,
        stack: QStackedWidget,
        *,
        workspace_routes: Sequence[tuple[str, str, int]],
        context_routes: Sequence[tuple[str, int]],
        navigate: Callable[[int], object],
        open_settings: Callable[[], object],
        navigate_back: Callable[[], object],
        practice_incorrect: Callable[[], object],
        open_task_center: Callable[[], object],
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("applicationShell")

        shell_layout = QHBoxLayout(self)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        self.navigation_sidebar = QFrame()
        self.navigation_sidebar.setObjectName("applicationSidebar")
        self.navigation_sidebar.setMinimumWidth(168)
        self.navigation_sidebar.setMaximumWidth(168)
        sidebar_layout = QVBoxLayout(self.navigation_sidebar)
        sidebar_layout.setContentsMargins(14, 20, 14, 20)
        sidebar_layout.setSpacing(6)

        self.sidebar_title = QLabel("")
        self.sidebar_title.setObjectName("sidebarTitle")
        sidebar_layout.addWidget(self.sidebar_title)
        sidebar_layout.addSpacing(20)

        self._workspace_group = QButtonGroup(self)
        self._workspace_group.setExclusive(True)
        self._navigation_buttons = tuple(
            self._create_sidebar_button(attribute, workspace, screen_index, navigate)
            for attribute, workspace, screen_index in workspace_routes
        )
        for button in self._navigation_buttons:
            sidebar_layout.addWidget(button)
        sidebar_layout.addStretch(1)

        self.sidebar_utility_separator = QFrame()
        self.sidebar_utility_separator.setObjectName("sidebarUtilitySeparator")
        self.sidebar_utility_separator.setFrameShape(QFrame.Shape.HLine)
        sidebar_layout.addWidget(self.sidebar_utility_separator)

        self.settings_nav_btn = QPushButton("")
        self.settings_nav_btn.setObjectName("sidebarUtilityButton")
        self.settings_nav_btn.setProperty("workspace", "settings")
        self.settings_nav_btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.settings_nav_btn.clicked.connect(open_settings)
        sidebar_layout.addWidget(self.settings_nav_btn)

        content = QWidget()
        content.setObjectName("applicationContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        self.context_header = QFrame()
        self.context_header.setObjectName("contextHeader")
        header_layout = QHBoxLayout(self.context_header)
        header_layout.setContentsMargins(24, 12, 24, 12)
        header_layout.setSpacing(8)

        self.context_back_btn = QPushButton("")
        self.context_back_btn.setObjectName("contextBackButton")
        self.context_back_btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.context_back_btn.clicked.connect(navigate_back)
        header_layout.addWidget(self.context_back_btn)

        self.context_title = QLabel("")
        self.context_title.setObjectName("contextTitle")
        self.context_title.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        header_layout.addWidget(self.context_title)

        self._context_tabs = tuple(
            self._create_context_tab(attribute, screen_index, navigate)
            for attribute, screen_index in context_routes
        )
        for button in self._context_tabs:
            header_layout.addWidget(button)

        self.incorrect_review_btn = QPushButton("")
        self.incorrect_review_btn.setObjectName("contextActionButton")
        self.incorrect_review_btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.incorrect_review_btn.clicked.connect(practice_incorrect)
        header_layout.addWidget(self.incorrect_review_btn)

        self.task_center_btn = QPushButton("")
        self.task_center_btn.setObjectName("contextActionButton")
        self.task_center_btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.task_center_btn.clicked.connect(open_task_center)
        header_layout.addWidget(self.task_center_btn)

        content_layout.addWidget(self.context_header)
        content_layout.addWidget(stack, 1)
        shell_layout.addWidget(self.navigation_sidebar)
        shell_layout.addWidget(content, 1)

    def _create_sidebar_button(
        self,
        attribute: str,
        workspace: str,
        screen_index: int,
        navigate: Callable[[int], object],
    ) -> QPushButton:
        button = QPushButton("")
        button.setObjectName("sidebarNavButton")
        button.setProperty("workspace", workspace)
        button.setCheckable(True)
        button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        button.clicked.connect(
            lambda _checked=False, index=screen_index: navigate(index)
        )
        self._workspace_group.addButton(button)
        setattr(self, attribute, button)
        return button

    def _create_context_tab(
        self,
        attribute: str,
        screen_index: int,
        navigate: Callable[[int], object],
    ) -> QPushButton:
        button = QPushButton("")
        button.setObjectName("contextTabButton")
        button.setCheckable(True)
        button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        button.clicked.connect(
            lambda _checked=False, index=screen_index: navigate(index)
        )
        setattr(self, attribute, button)
        return button

    def navigation_buttons(self) -> tuple[QPushButton, ...]:
        return self._navigation_buttons

    def all_context_tabs(self) -> tuple[QPushButton, ...]:
        return self._context_tabs

    def context_tabs(self) -> tuple[QPushButton, ...]:
        return tuple(button for button in self._context_tabs if not button.isHidden())
