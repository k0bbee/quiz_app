"""Small navigation-state boundary for the stacked application shell."""

from __future__ import annotations

from collections.abc import Iterable


class NavigationRouter:
    """Move a stack between screens while maintaining bounded back history."""

    def __init__(
        self,
        stack,
        *,
        history_limit: int = 50,
        skip_history_from: Iterable[int] = (),
    ):
        self._stack = stack
        self._history_limit = max(1, int(history_limit))
        self._skip_history_from = frozenset(skip_history_from)
        self.history: list[int] = []

    @property
    def can_go_back(self) -> bool:
        return bool(self.history)

    def navigate(self, screen_index: int, *, remember: bool = True) -> None:
        current_index = self._stack.currentIndex()
        if (
            remember
            and current_index >= 0
            and current_index != screen_index
            and current_index not in self._skip_history_from
        ):
            self.history.append(current_index)
            self.history[:] = self.history[-self._history_limit :]
        self._stack.setCurrentIndex(screen_index)

    def peek_back(self) -> int | None:
        return self.history[-1] if self.history else None

    def discard_back(self) -> None:
        if self.history:
            self.history.pop()
