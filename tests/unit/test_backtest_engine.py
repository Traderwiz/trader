"""Unit tests for the frontier-driven backtest engine."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from platform.backtest.engine import BacktestEngine
from platform.backtest.frontier import LookAheadBiasError
from platform.backtest.metrics import BacktestMetrics
from platform.data.catalog import load_instrument_catalog
from platform.data.parquet_store import ParquetStore
from platform.models.market_data import BarEvent
from platform.models.orders import SignalIntent, SignalSide
from platform.strategy.base import Strategy


class SimpleMeanReversionStrategy(Strategy):
    """Simple strategy used to validate replay ordering and metrics output."""

    instrument_id = "MES"
    bar_size = "1m"
    warmup_bars = 5
    supported_regimes = ("ranging", "volatile")

    def initialize(self) -> None:
        self.lookahead_checks = 0

    def on_bar(self, bar: BarEvent) -> None:
        assert self.history is not None
        visible = self.history.window(min(self.history.count, 5))
        assert visible[-1].ts_utc == bar.ts_utc
        self.lookahead_checks += 1
        if not self.is_warm:
            return

        mean_close = sum(item.close for item in visible) / len(visible)
        if bar.close <= mean_close - 0.8:
            self.emit_signal(
                SignalIntent(
                    strategy_id=self.strategy_id,
                    strategy_version=self.strategy_version,
                    instrument_id=self.instrument_id,
                    side=SignalSide.LONG,
                    signal_ts=bar.ts_utc,
                    reason="below_mean",
                ),
            )
        elif bar.close >= mean_close + 0.8:
            self.emit_signal(
                SignalIntent(
                    strategy_id=self.strategy_id,
                    strategy_version=self.strategy_version,
                    instrument_id=self.instrument_id,
                    side=SignalSide.SHORT,
                    signal_ts=bar.ts_utc,
                    reason="above_mean",
                ),
            )
        else:
            self.emit_signal(
                SignalIntent(
                    strategy_id=self.strategy_id,
                    strategy_version=self.strategy_version,
                    instrument_id=self.instrument_id,
                    side=SignalSide.FLAT,
                    signal_ts=bar.ts_utc,
                    reason="mean_reversion_exit",
                ),
            )


class FuturePeekingStrategy(Strategy):
    """Malicious strategy that attempts to read future data."""

    instrument_id = "MES"
    bar_size = "1m"
    warmup_bars = 1

    def initialize(self) -> None:
        pass

    def on_bar(self, bar: BarEvent) -> None:
        assert self.history is not None
        self.history.bar_at(1)


def test_backtest_engine_runs_simple_strategy_and_returns_metrics(tmp_path) -> None:
    catalog = load_instrument_catalog(Path(__file__).resolve().parents[2] / "config" / "instruments.yaml")
    store = ParquetStore(tmp_path / "var" / "data")
    bars = _make_oscillating_bars()
    store.write_bars(bars)
    engine = BacktestEngine(parquet_store=store, instrument_catalog=catalog, initial_capital=5_000.0)
    strategy = SimpleMeanReversionStrategy()

    result = engine.run(strategy, start=bars[0].ts_utc, end=bars[-1].ts_utc)

    assert isinstance(result.metrics, BacktestMetrics)
    assert result.metrics.trade_count >= 1
    assert result.metrics.total_slippage_paid > 0.0
    assert strategy.lookahead_checks == len(bars)


def test_backtest_engine_rejects_future_data_access(tmp_path) -> None:
    catalog = load_instrument_catalog(Path(__file__).resolve().parents[2] / "config" / "instruments.yaml")
    store = ParquetStore(tmp_path / "var" / "data")
    bars = _make_oscillating_bars()
    store.write_bars(bars)
    engine = BacktestEngine(parquet_store=store, instrument_catalog=catalog, initial_capital=5_000.0)

    with pytest.raises(LookAheadBiasError):
        engine.run(FuturePeekingStrategy(), start=bars[0].ts_utc, end=bars[-1].ts_utc)


def _make_oscillating_bars(count: int = 60) -> list[BarEvent]:
    """Create deterministic bars that trigger a mean-reversion strategy."""

    start = datetime(2025, 1, 2, 14, 30, tzinfo=timezone.utc)
    closes = [6000.0 + ((index % 6) - 3) * 0.9 for index in range(count)]
    bars: list[BarEvent] = []
    for index, close in enumerate(closes):
        ts_utc = start + timedelta(minutes=index)
        bars.append(
            BarEvent(
                instrument_id="MES",
                ts_utc=ts_utc,
                open=close - 0.25,
                high=close + 0.5,
                low=close - 0.5,
                close=close,
                volume=2_000.0,
                bar_size="1m",
            ),
        )
    return bars

