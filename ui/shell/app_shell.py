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
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ui.navigation.routes import (
    Route,
    Workspace,
    route_spec,
    route_tab,
    workspace_label,
)


class AppShell(QWidget):
    """Present the shared sidebar, context header, and screen stack."""

    def __init__(
        self,
        stack: QStackedWidget,
        *,
        workspace_routes: Sequence[tuple[str, Workspace, Route]],
        context_routes: Sequence[tuple[str, Route]],
        navigate: Callable[[Route], object],
        open_settings: Callable[[], object],
        navigate_back: Callable[[], object],
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
        self.sidebar_title.setWordWrap(True)
        self.sidebar_title.setMinimumWidth(0)
        sidebar_layout.addWidget(self.sidebar_title)
        sidebar_layout.addSpacing(20)

        self._workspace_group = QButtonGroup(self)
        self._workspace_group.setExclusive(True)
        self._workspace_routes = {}
        self._navigation_buttons = tuple(
            self._create_sidebar_button(attribute, workspace, route, navigate)
            for attribute, workspace, route in workspace_routes
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
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Preferred,
        )
        header_layout.addWidget(self.context_title)

        self._context_routes = {}
        self._context_tabs = tuple(
            self._create_context_tab(attribute, route, navigate)
            for attribute, route in context_routes
        )
        self.context_tabs_scroll = QScrollArea(self.context_header)
        self.context_tabs_scroll.setObjectName("contextTabsScroll")
        self.context_tabs_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.context_tabs_scroll.setWidgetResizable(False)
        self.context_tabs_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.context_tabs_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.context_tabs_scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        self.context_tabs_container = QWidget()
        self.context_tabs_layout = QHBoxLayout(self.context_tabs_container)
        self.context_tabs_layout.setContentsMargins(0, 0, 0, 0)
        self.context_tabs_layout.setSpacing(8)
        for button in self._context_tabs:
            self.context_tabs_layout.addWidget(button)
        self.context_tabs_layout.addStretch(1)
        self.context_tabs_scroll.setWidget(self.context_tabs_container)
        header_layout.addWidget(self.context_tabs_scroll, 1)

        content_layout.addWidget(self.context_header)
        content_layout.addWidget(stack, 1)
        shell_layout.addWidget(self.navigation_sidebar)
        shell_layout.addWidget(content, 1)

    def _create_sidebar_button(
        self,
        attribute: str,
        workspace: Workspace,
        route: Route,
        navigate: Callable[[Route], object],
    ) -> QPushButton:
        button = QPushButton("")
        button.setObjectName("sidebarNavButton")
        button.setProperty("workspace", workspace.value)
        button.setCheckable(True)
        button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        button.clicked.connect(
            lambda _checked=False, destination=route: navigate(destination)
        )
        self._workspace_group.addButton(button)
        self._workspace_routes[button] = workspace
        setattr(self, attribute, button)
        return button

    def _create_context_tab(
        self,
        attribute: str,
        route: Route,
        navigate: Callable[[Route], object],
    ) -> QPushButton:
        button = QPushButton("")
        button.setObjectName("contextTabButton")
        button.setCheckable(True)
        button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        button.clicked.connect(
            lambda _checked=False, destination=route: navigate(destination)
        )
        self._context_routes[button] = route
        setattr(self, attribute, button)
        return button

    def render_language(self, get_text) -> None:
        for button, workspace in self._workspace_routes.items():
            zh, en = workspace_label(workspace)
            button.setText(get_text(zh, en))
        for button, route in self._context_routes.items():
            tab = route_tab(route)
            if tab is not None:
                button.setText(get_text(tab.label_zh, tab.label_en))
                button.updateGeometry()
        self._refresh_context_tabs_extent()
        self.context_back_btn.setText(get_text("返回", "Back"))
        self.settings_nav_btn.setText(get_text("设置", "Settings"))

    def apply_route(self, route: Route, *, can_go_back: bool, get_text) -> None:
        spec = route_spec(route)
        is_library_context = route.workspace is Workspace.LIBRARY
        for button, workspace in self._workspace_routes.items():
            button.setChecked(workspace is spec.workspace)
        for button, destination in self._context_routes.items():
            visible = (
                (not spec.focus or is_library_context)
                and destination.workspace is spec.workspace
            )
            button.setVisible(visible)
            button.setChecked(
                visible and destination.tab == route.tab
            )
        self._refresh_context_tabs_extent()
        self.context_title.setText(
            get_text(spec.title_zh, spec.title_en)
        )
        self.navigation_sidebar.setVisible(not spec.focus and not is_library_context)
        self.context_back_btn.setVisible(
            (spec.focus or is_library_context) and can_go_back
        )
        self.context_back_btn.setEnabled(can_go_back)

    def _refresh_context_tabs_extent(self) -> None:
        """Keep translated tab labels readable inside the scrollable strip."""
        visible_buttons = [
            button for button in self._context_tabs if button.isVisible()
        ]
        buttons = visible_buttons or list(self._context_tabs)
        margins = self.context_tabs_layout.contentsMargins()
        spacing = self.context_tabs_layout.spacing()
        content_width = (
            sum(button.sizeHint().width() for button in buttons)
            + max(0, len(buttons) - 1) * spacing
            + margins.left()
            + margins.right()
        )
        self.context_tabs_container.setFixedWidth(max(1, content_width))

    def navigation_buttons(self) -> tuple[QPushButton, ...]:
        return self._navigation_buttons

    def context_tabs(self) -> tuple[QPushButton, ...]:
        return tuple(button for button in self._context_tabs if not button.isHidden())
