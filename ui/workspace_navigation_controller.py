"""Coordinate semantic workspace navigation outside the application shell."""

from __future__ import annotations

from ui.navigation import Route, Workspace


class WorkspaceNavigationController:
    """Resolve routes, enforce flow guards and refresh destination workspaces."""

    def __init__(self, host) -> None:
        self._host = host

    def navigate_index(
        self,
        screen_index: int,
        remember: bool = True,
        confirm_current: bool = True,
        *,
        allow_first_run_redirect: bool = True,
    ) -> bool:
        return self.navigate(
            self.default_route(screen_index),
            remember=remember,
            confirm_current=confirm_current,
            allow_first_run_redirect=allow_first_run_redirect,
        )

    def current_route(self) -> Route:
        host = self._host
        destination = host.navigation_router.current_destination
        if isinstance(destination, Route):
            return destination
        return self.default_route(host.stack.currentIndex())

    def screen_index(self, route) -> int:
        if isinstance(route, Route):
            return self._host.SCREEN_INDEX_BY_KEY[route.screen]
        return int(route)

    def default_route(self, screen_index: int) -> Route:
        host = self._host
        routes = {
            host.SCREEN_HOME: Route.study("today"),
            host.SCREEN_TOPIC_SELECTION: Route.study("practice"),
            host.SCREEN_QUIZ: Route.focus("quiz"),
            host.SCREEN_RESULTS: Route.focus("results"),
            host.SCREEN_PROGRESS: Route.study("analysis"),
            host.SCREEN_COURSES: Route.course(),
            host.SCREEN_QUESTION_BANK: Route.library("questions"),
            host.SCREEN_GENERATION: Route.course(
                host.course_context.current_course_id(),
                tab="generation",
            ),
        }
        try:
            return routes[int(screen_index)]
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"unknown screen index: {screen_index}") from exc

    def course_context_id(self) -> str:
        host = self._host
        course_screen = getattr(host, "_course_screen", None)
        if course_screen is not None:
            selected = course_screen.selected_course_id()
            if selected:
                return selected
        return host.course_context.current_course_id()

    def navigate(
        self,
        route: Route,
        remember: bool = True,
        confirm_current: bool = True,
        *,
        allow_first_run_redirect: bool = True,
    ) -> bool:
        host = self._host
        if not isinstance(route, Route):
            raise TypeError("route must be a Route")
        if route.workspace is Workspace.COURSE and not route.course_id:
            route = Route.course(
                self.course_context_id(),
                tab=route.tab,
                draft_id=route.draft_id,
            )
        screen_index = self.screen_index(route)
        if not host.history_protection.confirm_navigation(screen_index):
            self.update_actions()
            return False
        if (
            allow_first_run_redirect
            and host._first_run_required()
            and route == Route.study("practice")
        ):
            route = Route.study("today")
        elif (
            allow_first_run_redirect
            and host._first_run_required()
            and route.workspace is Workspace.COURSE
            and route.tab != "generation"
            and host._course_screen is None
            and host.first_run.archived_course_count() <= 0
            and not self._has_active_courses()
        ):
            route = Route.study("today")
        screen_index = self.screen_index(route)
        if confirm_current and not self.confirm_current(screen_index):
            self.update_actions()
            return False
        active_generation_workspace = vars(host).get("_generation_workspace")
        if (
            route.tab == "generation"
            and active_generation_workspace is not None
            and active_generation_workspace.generation_widget() is not None
            and active_generation_workspace.course_id
        ):
            active_course_id = str(active_generation_workspace.course_id or "").strip()
            requested_course_id = str(route.course_id or "").strip()
            requested_draft_id = str(route.draft_id or "").strip()
            session_course_id = getattr(
                active_generation_workspace, "session_course_id", None
            )
            requested_session_course = (
                str(session_course_id(requested_draft_id) or "").strip()
                if requested_draft_id and callable(session_course_id)
                else ""
            )
            select_session = getattr(active_generation_workspace, "select_session", None)
            if (
                requested_draft_id
                and requested_session_course
                and callable(select_session)
                and (
                    not requested_course_id
                    or requested_course_id == requested_session_course
                )
                and select_session(requested_draft_id)
            ):
                selected_course_id = str(
                    active_generation_workspace.course_id or ""
                ).strip()
                route = Route.course(
                    selected_course_id,
                    tab="generation",
                    draft_id=requested_draft_id,
                )
            elif requested_course_id and requested_course_id != active_course_id:
                requested_course = host.course_manager.get(requested_course_id)
                if requested_course is None:
                    return False
                return bool(
                    host.generation_flow.open(
                        course_override=requested_course,
                        draft_id=requested_draft_id,
                    )
                )
            else:
                route = Route.course(
                    active_course_id,
                    tab="generation",
                    draft_id=requested_draft_id,
                )
        if (
            route.workspace is Workspace.COURSE
            and route.tab == "generation"
            and route.course_id
            and host.course_manager.get(route.course_id) is not None
            and host.course_context.current_course_id() != route.course_id
            and host.course_manager.set_current(route.course_id)
        ):
            host.course_context.course_changed()
        if screen_index == host.SCREEN_COURSES:
            host._get_course_screen()
        elif screen_index == host.SCREEN_QUESTION_BANK:
            host._get_question_bank_screen()
        elif screen_index == host.SCREEN_GENERATION:
            generation_workspace = host._get_generation_workspace()
            if route.course_id and generation_workspace.generation_widget() is None:
                project = host.course_manager.get(route.course_id)
                if project is not None:
                    return bool(
                        host.generation_flow.open(
                            course_override=project,
                            draft_id=route.draft_id,
                        )
                    )
        host.navigation_router.navigate(route, remember=remember)
        if screen_index == host.SCREEN_TOPIC_SELECTION:
            host.course_context.sync_topic_screen()
            host.topic_screen.refresh()
        elif screen_index == host.SCREEN_PROGRESS:
            host.course_context.sync_progress()
            host.progress_screen.refresh()
        elif screen_index == host.SCREEN_HOME:
            host.course_context.sync_home()
            host.home_screen.refresh()
        elif screen_index == host.SCREEN_COURSES:
            host._get_course_screen().show_course(route.course_id, route.tab)
        elif screen_index == host.SCREEN_QUESTION_BANK:
            host.course_context.sync_question_bank()
            library = host._get_question_bank_screen()
            if route.tab == "sets":
                library.show_question_sets()
            elif route.tab == "drafts":
                library.show_generation_drafts()
            else:
                library.show_questions()
            library.refresh()
        self.update_actions()
        return True

    def _has_active_courses(self) -> bool:
        """Keep course management reachable during onboarding with seed data."""
        try:
            return bool(self._host.course_manager.load_all())
        except (OSError, TypeError, ValueError):
            return False

    def back(self) -> None:
        host = self._host
        previous = host.navigation_router.peek_back()
        if previous is None:
            self.update_actions()
            return
        target_screen = self.screen_index(previous)
        if not self.confirm_current(target_screen):
            self.update_actions()
            return
        host.navigation_router.discard_back()
        if isinstance(previous, Route):
            self.navigate(
                previous,
                remember=False,
                confirm_current=False,
            )
        else:
            self.navigate_index(
                previous,
                remember=False,
                confirm_current=False,
            )

    def confirm_current(self, target_screen: int) -> bool:
        host = self._host
        if (
            host.stack.currentIndex() == host.SCREEN_QUIZ
            and target_screen != host.SCREEN_QUIZ
        ):
            return host.quiz_screen.confirm_exit()
        return True

    def update_actions(self) -> None:
        host = self._host
        if not hasattr(host, "context_back_btn"):
            return
        host.app_shell.apply_route(
            self.current_route(),
            can_go_back=host.navigation_router.can_go_back,
            get_text=host.lang_manager.get_text,
        )
