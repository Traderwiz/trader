"""Unit tests for deterministic regime feature classification."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from platform.regime.detector import RegimeDetector


def test_trending_sequence_is_classified_as_trending() -> None:
    detector = RegimeDetector()
    bars = _make_trending_bars()

    state = None
    for bar in bars:
        state = detector.update(bar)

    assert state is not None
    assert state.primary_regime == "trending"
    assert state.features.adx_14 >= 25.0


def test_ranging_sequence_is_classified_as_ranging() -> None:
    detector = RegimeDetector()
    bars = _make_ranging_bars()

    state = None
    for bar in bars:
        state = detector.update(bar)

    assert state is not None
    assert state.primary_regime == "ranging"
    assert state.features.adx_14 <= 20.0


def test_high_volatility_sequence_sets_volatile_flag() -> None:
    detector = RegimeDetector()
    bars = _make_high_volatility_bars()

    state = None
    for bar in bars:
        state = detector.update(bar)

    assert state is not None
    assert state.volatile is True
    assert state.features.atr_percentile > 80.0


def _make_trending_bars(count: int = 260) -> list:
    start = datetime(2025, 1, 2, 14, 30, tzinfo=timezone.utc)
    price = 100.0
    bars = []
    for index in range(count):
        price += 0.55 + math.sin(index / 12) * 0.05
        bars.append(_bar(start + timedelta(minutes=index), price, width=0.9))
    return bars


def _make_ranging_bars(count: int = 260) -> list:
    start = datetime(2025, 1, 3, 14, 30, tzinfo=timezone.utc)
    bars = []
    for index in range(count):
        close = 100.0 + (0.18 if index % 2 == 0 else -0.18)
        bars.append(_bar(start + timedelta(minutes=index), close, width=0.35))
    return bars


def _make_high_volatility_bars(count: int = 260) -> list:
    start = datetime(2025, 1, 6, 14, 30, tzinfo=timezone.utc)
    price = 100.0
    bars = []
    for index in range(count):
        width = 1.0 if index < 180 else 4.0 + ((index - 180) / 10)
        price += math.sin(index / 2) * (0.2 if index < 180 else 3.8)
        bars.append(_bar(start + timedelta(minutes=index), price, width=width))
    return bars


def _bar(ts_utc: datetime, close: float, *, width: float):
    from platform.models.market_data import BarEvent

    open_price = close - 0.1
    high = max(open_price, close) + width / 2
    low = min(open_price, close) - width / 2
    return BarEvent(
        instrument_id="MES",
        ts_utc=ts_utc,
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=2500.0,
        bar_size="1m",
    )
