"""Unit tests for the walk-forward validation runner."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

from platform.backtest.engine import BacktestEngine
from platform.backtest.walkforward import WalkForwardMode, WalkForwardRunner
from platform.data.catalog import load_instrument_catalog
from platform.data.parquet_store import ParquetStore
from platform.models.market_data import BarEvent
from platform.models.orders import SignalIntent, SignalSide
from platform.strategy.base import Strategy


class WalkForwardMeanReversionStrategy(Strategy):
    instrument_id = "MES"
    bar_size = "1m"
    warmup_bars = 5
    supported_regimes = ("ranging",)

    def initialize(self) -> None:
        pass

    def on_bar(self, bar: BarEvent) -> None:
        assert self.history is not None
        visible = self.history.window(min(self.history.count, 5))
        mean_close = sum(item.close for item in visible) / len(visible)
        if not self.is_warm:
            return
        if bar.close < mean_close - 0.5:
            side = SignalSide.LONG
        elif bar.close > mean_close + 0.5:
            side = SignalSide.SHORT
        else:
            side = SignalSide.FLAT
        self.emit_signal(
            SignalIntent(
                strategy_id=self.strategy_id,
                strategy_version=self.strategy_version,
                instrument_id=self.instrument_id,
                side=side,
                signal_ts=bar.ts_utc,
                reason="walkforward",
            )
        )


def test_walkforward_runner_outputs_window_and_aggregate_metrics(tmp_path) -> None:
    catalog = load_instrument_catalog(Path(__file__).resolve().parents[2] / "config" / "instruments.yaml")
    store = ParquetStore(tmp_path / "var" / "data")
    store.write_bars(_make_session_bars())
    engine = BacktestEngine(parquet_store=store, instrument_catalog=catalog, initial_capital=5_000.0)
    runner = WalkForwardRunner(backtest_engine=engine, parquet_store=store)

    result = runner.run(
        strategy_factory=WalkForwardMeanReversionStrategy,
        instrument_id="MES",
        bar_size="1m",
        train_sessions=4,
        test_sessions=2,
        mode=WalkForwardMode.ROLLING,
        parameter_set={"lookback": 5},
    )

    assert result.windows
    assert result.parameter_set["lookback"] == 5
    assert "trade_count" in result.aggregate_oos_metrics
    assert all("train_metrics" in window and "test_metrics" in window for window in result.windows)


def _make_session_bars(session_count: int = 12, bars_per_session: int = 24) -> list[BarEvent]:
    start = datetime(2025, 1, 2, 14, 30, tzinfo=timezone.utc)
    bars: list[BarEvent] = []
    for session_index in range(session_count):
        session_start = start + timedelta(days=session_index)
        base = 6000.0 + session_index * 2.0
        for minute in range(bars_per_session):
            close = base + math.sin(minute / 2) * 1.4
            ts_utc = session_start + timedelta(minutes=minute)
            bars.append(
                BarEvent(
                    instrument_id="MES",
                    ts_utc=ts_utc,
                    open=close - 0.25,
                    high=close + 0.6,
                    low=close - 0.6,
                    close=close,
                    volume=2200.0,
                    bar_size="1m",
                )
            )
    return bars
