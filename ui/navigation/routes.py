"""Typed application routes and their presentation metadata."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Workspace(str, Enum):
    STUDY = "learning"
    COURSE = "courses"
    LIBRARY = "library"
    FOCUS = "focus"


class ScreenKey(str, Enum):
    HOME = "home"
    TOPIC_SELECTION = "topic_selection"
    QUIZ = "quiz"
    RESULTS = "results"
    PROGRESS = "progress"
    COURSES = "courses"
    QUESTION_BANK = "question_bank"
    GENERATION = "generation"


_VALID_TABS = {
    Workspace.STUDY: frozenset({"today", "practice", "analysis"}),
    Workspace.COURSE: frozenset(
        {"overview", "sources", "knowledge", "generation"}
    ),
    Workspace.LIBRARY: frozenset({"questions", "sets"}),
    Workspace.FOCUS: frozenset({"quiz", "results"}),
}


@dataclass(frozen=True, slots=True)
class Route:
    """A stable logical destination independent of numeric stack indexes."""

    workspace: Workspace
    tab: str
    course_id: str = ""
    draft_id: str = ""

    def __post_init__(self) -> None:
        normalized_tab = str(self.tab or "").strip()
        if normalized_tab not in _VALID_TABS[self.workspace]:
            raise ValueError(
                f"unknown {self.workspace.value} route tab: {normalized_tab}"
            )
        object.__setattr__(self, "tab", normalized_tab)
        object.__setattr__(
            self,
            "course_id",
            str(self.course_id or "").strip(),
        )
        object.__setattr__(
            self,
            "draft_id",
            str(self.draft_id or "").strip(),
        )

    @classmethod
    def study(cls, tab: str = "today") -> "Route":
        return cls(Workspace.STUDY, tab)

    @classmethod
    def course(
        cls,
        course_id: str = "",
        *,
        tab: str = "overview",
        draft_id: str = "",
    ) -> "Route":
        return cls(
            Workspace.COURSE,
            tab,
            course_id=course_id,
            draft_id=draft_id,
        )

    @classmethod
    def library(cls, tab: str = "questions") -> "Route":
        return cls(Workspace.LIBRARY, tab)

    @classmethod
    def focus(cls, tab: str) -> "Route":
        return cls(Workspace.FOCUS, tab)

    @property
    def screen(self) -> ScreenKey:
        if self.workspace is Workspace.STUDY:
            return {
                "today": ScreenKey.HOME,
                "practice": ScreenKey.TOPIC_SELECTION,
                "analysis": ScreenKey.PROGRESS,
            }[self.tab]
        if self.workspace is Workspace.COURSE:
            return (
                ScreenKey.GENERATION
                if self.tab == "generation"
                else ScreenKey.COURSES
            )
        if self.workspace is Workspace.LIBRARY:
            return ScreenKey.QUESTION_BANK
        return {
            "quiz": ScreenKey.QUIZ,
            "results": ScreenKey.RESULTS,
        }[self.tab]


@dataclass(frozen=True, slots=True)
class RouteSpec:
    workspace: Workspace
    title_zh: str
    title_en: str
    focus: bool = False


@dataclass(frozen=True, slots=True)
class RouteTab:
    route: Route
    label_zh: str
    label_en: str


_WORKSPACE_TABS = {
    Workspace.STUDY: (
        RouteTab(Route.study("today"), "今日", "Today"),
        RouteTab(Route.study("practice"), "自由练习", "Free Practice"),
        RouteTab(Route.study("analysis"), "学习分析", "Learning Analysis"),
    ),
    Workspace.COURSE: (
        RouteTab(Route.course(tab="overview"), "概览", "Overview"),
        RouteTab(Route.course(tab="sources"), "资料", "Sources"),
        RouteTab(Route.course(tab="knowledge"), "知识点", "Knowledge"),
        RouteTab(Route.course(tab="generation"), "生成与审核", "Generate and Review"),
    ),
    Workspace.LIBRARY: (
        RouteTab(Route.library("questions"), "题目", "Questions"),
        RouteTab(Route.library("sets"), "题目集", "Question Sets"),
    ),
    Workspace.FOCUS: (),
}


def workspace_tabs(workspace: Workspace) -> tuple[RouteTab, ...]:
    return _WORKSPACE_TABS[Workspace(workspace)]


def workspace_label(workspace: Workspace) -> tuple[str, str]:
    return {
        Workspace.STUDY: ("学习", "Study"),
        Workspace.COURSE: ("课程", "Courses"),
        Workspace.LIBRARY: ("资料库", "Library"),
        Workspace.FOCUS: ("", ""),
    }[Workspace(workspace)]


def route_tab(route: Route) -> RouteTab | None:
    return next(
        (
            tab
            for tab in workspace_tabs(route.workspace)
            if tab.route.tab == route.tab
        ),
        None,
    )


def route_spec(route: Route) -> RouteSpec:
    if route.workspace is Workspace.STUDY:
        return RouteSpec(route.workspace, "学习", "Study")
    if route.workspace is Workspace.COURSE:
        return RouteSpec(route.workspace, "课程", "Courses")
    if route.workspace is Workspace.LIBRARY:
        return RouteSpec(route.workspace, "资料库", "Library")
    if route.tab == "quiz":
        return RouteSpec(route.workspace, "答题", "Quiz", focus=True)
    return RouteSpec(route.workspace, "练习结果", "Results", focus=True)
