"""Small navigation-state boundary for the stacked application shell."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any


class NavigationRouter:
    """Move a stack between screens while maintaining bounded back history."""

    def __init__(
        self,
        stack,
        *,
        history_limit: int = 50,
        skip_history_from: Iterable[int] = (),
        resolve_destination: Callable[[Any], int] | None = None,
        initial_destination: Any = None,
    ):
        self._stack = stack
        self._history_limit = max(1, int(history_limit))
        self._skip_history_from = frozenset(skip_history_from)
        self._resolve_destination = resolve_destination or int
        self.current_destination = initial_destination
        self.history: list[Any] = []

    @property
    def can_go_back(self) -> bool:
        return bool(self.history)

    def navigate(self, destination, *, remember: bool = True) -> None:
        screen_index = self._resolve_destination(destination)
        current_index = self._stack.currentIndex()
        current_destination = (
            self.current_destination
            if self.current_destination is not None
            else current_index
        )
        if (
            remember
            and current_index >= 0
            and current_index != screen_index
            and current_index not in self._skip_history_from
        ):
            self.history.append(current_destination)
            self.history[:] = self.history[-self._history_limit :]
        self._stack.setCurrentIndex(screen_index)
        self.current_destination = destination

    def peek_back(self):
        return self.history[-1] if self.history else None

    def discard_back(self) -> None:
        if self.history:
            self.history.pop()
