"""Unit tests for frontier-bounded history access."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from platform.backtest.frontier import FrontierClock, HistoryView, LookAheadBiasError
from platform.models.market_data import BarEvent


def test_history_view_rejects_future_bar_access() -> None:
    bars = [
        BarEvent(
            instrument_id="MES",
            ts_utc=datetime(2025, 1, 2, 14, minute, tzinfo=timezone.utc),
            open=6000.0 + minute,
            high=6001.0 + minute,
            low=5999.0 + minute,
            close=6000.5 + minute,
            volume=100.0,
            bar_size="1m",
        )
        for minute in range(3)
    ]
    frontier = FrontierClock()
    history = HistoryView(bars, frontier)
    frontier.advance(1, bars[1].ts_utc)

    assert [bar.ts_utc for bar in history.bars()] == [bars[0].ts_utc, bars[1].ts_utc]

    with pytest.raises(LookAheadBiasError):
        history.bar_at(1)

