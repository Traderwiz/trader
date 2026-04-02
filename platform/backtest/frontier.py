"""Frontier clock and history view that prevent look-ahead access during replay."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from platform.models.market_data import BarEvent


class LookAheadBiasError(RuntimeError):
    """Raised when a strategy attempts to access data beyond the active frontier."""


@dataclass
class FrontierClock:
    """Mutable replay frontier advanced one bar at a time."""

    current_ts: datetime | None = None
    current_index: int = -1

    def advance(self, index: int, ts_utc: datetime) -> None:
        """Move the frontier to the next bar."""

        if index < self.current_index:
            raise ValueError("FrontierClock cannot move backwards.")
        self.current_index = index
        self.current_ts = ts_utc


class HistoryView:
    """Frontier-bounded access to replay bars."""

    def __init__(self, bars: list[BarEvent], frontier: FrontierClock) -> None:
        self._bars = bars
        self._frontier = frontier

    @property
    def count(self) -> int:
        """Return the number of bars visible at the frontier."""

        return self._frontier.current_index + 1

    @property
    def frontier_ts(self) -> datetime | None:
        """Return the active frontier timestamp."""

        return self._frontier.current_ts

    def bars(self, limit: int | None = None) -> list[BarEvent]:
        """Return the visible bars up to and including the frontier."""

        visible = self._bars[: self.count]
        if limit is None:
            return list(visible)
        if limit <= 0:
            raise ValueError("limit must be positive when provided.")
        return list(visible[-limit:])

    def window(self, size: int) -> list[BarEvent]:
        """Return the most recent visible bars."""

        if size <= 0:
            raise ValueError("size must be positive.")
        return self.bars(limit=size)

    def bar_at(self, offset: int) -> BarEvent:
        """Return a bar relative to the current frontier, rejecting future offsets."""

        target_index = self._frontier.current_index + offset
        if target_index > self._frontier.current_index:
            raise LookAheadBiasError("Attempted to access a future bar beyond the frontier.")
        if target_index < 0 or target_index >= self.count:
            raise IndexError("Requested bar is outside the visible history.")
        return self._bars[target_index]

    def between(self, start: datetime, end: datetime) -> list[BarEvent]:
        """Return visible bars in a bounded time range."""

        frontier_ts = self.frontier_ts
        if frontier_ts is None:
            return []
        if end > frontier_ts:
            raise LookAheadBiasError("Attempted to access bars beyond the active frontier.")
        return [bar for bar in self._bars[: self.count] if start <= bar.ts_utc <= end]

