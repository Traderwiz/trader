"""Unit tests for the MES RSI trend-pullback strategy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from platform.models.market_data import BarEvent
from platform.models.orders import SignalSide
from strategies.mes_rsi_trend_pullback import MESRSITrendPullbackStrategy


@dataclass
class DummyHistory:
    count: int


class StubIndicator:
    def __init__(self, values: list[float | None]) -> None:
        self._values = list(values)

    def update(self, _bar: BarEvent) -> float | None:
        if not self._values:
            raise AssertionError("StubIndicator exhausted.")
        return self._values.pop(0)


def test_entry_requires_price_above_sma_and_adx_at_or_above_20() -> None:
    strategy = MESRSITrendPullbackStrategy()
    strategy.initialize()
    history = DummyHistory(count=200)
    signals = []
    strategy.bind(history, signals.append)

    strategy.rsi_2 = StubIndicator([5.0, 5.0, 30.0])
    strategy.sma_100 = StubIndicator([100.0, 100.0, 100.0])
    strategy.adx_14 = StubIndicator([19.0, 20.0, 25.0])

    strategy.on_bar(_bar(close=105.0))
    assert signals == []

    valid_bar = _bar(close=105.0, ts=datetime(2025, 1, 3, tzinfo=timezone.utc))
    strategy.on_bar(valid_bar)

    assert len(signals) == 1
    signal = signals[0]
    assert signal.side is SignalSide.LONG
    assert signal.metadata["execution_timing"] == "next_open"
    assert signal.metadata["signal_adx_14"] == 20.0

    strategy.pending_entry = False
    strategy.on_bar(_bar(close=105.0, ts=datetime(2025, 1, 4, tzinfo=timezone.utc)))
    assert len(signals) == 1


def test_stop_loss_has_priority_over_profit_target_and_time_stop() -> None:
    strategy = MESRSITrendPullbackStrategy()
    strategy.initialize()
    history = DummyHistory(count=250)
    signals = []
    strategy.bind(history, signals.append)
    strategy.position_open = True
    strategy.entry_price = 100.0
    strategy.entry_date = datetime(2025, 1, 1, tzinfo=timezone.utc).date()

    strategy.rsi_2 = StubIndicator([80.0])
    strategy.sma_100 = StubIndicator([101.0])
    strategy.adx_14 = StubIndicator([25.0])

    strategy.on_bar(_bar(close=102.0, low=98.5, ts=datetime(2025, 1, 12, tzinfo=timezone.utc)))

    assert len(signals) == 1
    signal = signals[0]
    assert signal.side is SignalSide.FLAT
    assert signal.reason == "stop_loss"
    assert signal.metadata["execution_timing"] == "current_bar"
    assert strategy.position_open is False


def test_profit_target_precedes_time_stop_when_both_are_true() -> None:
    strategy = MESRSITrendPullbackStrategy()
    strategy.initialize()
    history = DummyHistory(count=250)
    signals = []
    strategy.bind(history, signals.append)
    strategy.position_open = True
    strategy.entry_price = 100.0
    strategy.entry_date = datetime(2025, 1, 1, tzinfo=timezone.utc).date()

    strategy.rsi_2 = StubIndicator([80.0])
    strategy.sma_100 = StubIndicator([101.0])
    strategy.adx_14 = StubIndicator([25.0])

    strategy.on_bar(_bar(close=102.0, low=100.2, ts=datetime(2025, 1, 12, tzinfo=timezone.utc)))

    assert len(signals) == 1
    signal = signals[0]
    assert signal.reason == "profit_target"
    assert signal.metadata["execution_timing"] == "next_open"
    assert strategy.pending_exit_reason == "profit_target"


def test_time_stop_triggers_after_ten_calendar_days() -> None:
    strategy = MESRSITrendPullbackStrategy()
    strategy.initialize()
    history = DummyHistory(count=250)
    signals = []
    strategy.bind(history, signals.append)
    strategy.position_open = True
    strategy.entry_price = 100.0
    strategy.entry_date = datetime(2025, 1, 1, tzinfo=timezone.utc).date()

    strategy.rsi_2 = StubIndicator([60.0])
    strategy.sma_100 = StubIndicator([101.0])
    strategy.adx_14 = StubIndicator([25.0])

    strategy.on_bar(_bar(close=101.0, low=100.2, ts=datetime(2025, 1, 11, tzinfo=timezone.utc)))

    assert len(signals) == 1
    signal = signals[0]
    assert signal.reason == "time_stop"
    assert signal.metadata["execution_timing"] == "next_open"


def _bar(*, close: float, low: float | None = None, ts: datetime | None = None) -> BarEvent:
    price_low = close - 0.5 if low is None else low
    return BarEvent(
        instrument_id="MES",
        ts_utc=ts or datetime(2025, 1, 2, tzinfo=timezone.utc),
        open=close - 0.25,
        high=close + 0.75,
        low=price_low,
        close=close,
        volume=1000.0,
        bar_size="1D",
    )
