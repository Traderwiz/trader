"""Minimal broker-agnostic strategy base class for backtests and later runtimes."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Callable

from platform.models.orders import SignalIntent

if TYPE_CHECKING:
    from platform.backtest.frontier import HistoryView


class Strategy(ABC):
    """Backtesting.py-style strategy contract constrained to canonical signals."""

    supported_regimes: tuple[str, ...] = ()
    instrument_id: str = ""
    bar_size: str = ""
    warmup_bars: int = 0
    strategy_version: str = "1.0.0"

    def __init__(self) -> None:
        self.history: HistoryView | None = None
        self._emit: Callable[[SignalIntent], None] | None = None

    @property
    def strategy_id(self) -> str:
        """Return the stable strategy identifier."""

        return self.__class__.__name__

    @property
    def is_warm(self) -> bool:
        """Return whether the warm-up requirement has been met."""

        return self.history is not None and self.history.count >= self.warmup_bars

    def bind(self, history: HistoryView, emit: Callable[[SignalIntent], None]) -> None:
        """Attach runtime context before initialization."""

        self.history = history
        self._emit = emit

    @abstractmethod
    def initialize(self) -> None:
        """Initialize indicators and internal state before replay begins."""

    @abstractmethod
    def on_bar(self, bar) -> None:
        """Handle one canonical bar event in chronological order."""

    def emit_signal(self, intent: SignalIntent) -> None:
        """Emit a broker-agnostic signal intent through the engine."""

        if self._emit is None:
            raise RuntimeError("Strategy is not bound to an execution context.")
        self._emit(intent)

