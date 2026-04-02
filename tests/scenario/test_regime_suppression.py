"""Scenario test proving regime suppression changes strategy outcomes."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

from platform.backtest.engine import BacktestEngine
from platform.data.catalog import load_instrument_catalog
from platform.data.parquet_store import ParquetStore
from platform.models.market_data import BarEvent
from platform.models.orders import SignalIntent, SignalSide
from platform.regime.detector import RegimeDetector
from platform.strategy.base import Strategy


class TrendingMeanReversionStrategy(Strategy):
    instrument_id = "MES"
    bar_size = "1m"
    warmup_bars = 8
    supported_regimes = ("ranging",)

    def initialize(self) -> None:
        pass

    def on_bar(self, bar: BarEvent) -> None:
        assert self.history is not None
        visible = self.history.window(min(self.history.count, 8))
        if not self.is_warm:
            return
        mean_close = sum(item.close for item in visible) / len(visible)
        if bar.close >= mean_close + 0.7:
            side = SignalSide.SHORT
        elif bar.close <= mean_close - 0.7:
            side = SignalSide.LONG
        else:
            side = SignalSide.FLAT
        self.emit_signal(
            SignalIntent(
                strategy_id=self.strategy_id,
                strategy_version=self.strategy_version,
                instrument_id=self.instrument_id,
                side=side,
                signal_ts=bar.ts_utc,
                reason="mean_revert",
            )
        )


def test_regime_suppression_reduces_losses_on_trending_dataset(tmp_path) -> None:
    catalog = load_instrument_catalog(Path(__file__).resolve().parents[2] / "config" / "instruments.yaml")
    store = ParquetStore(tmp_path / "var" / "data")
    bars = _make_trending_dataset()
    store.write_bars(bars)
    engine = BacktestEngine(parquet_store=store, instrument_catalog=catalog, initial_capital=5_000.0)

    unsuppressed = engine.run(TrendingMeanReversionStrategy(), start=bars[0].ts_utc, end=bars[-1].ts_utc)
    suppressed = engine.run(
        TrendingMeanReversionStrategy(),
        start=bars[0].ts_utc,
        end=bars[-1].ts_utc,
        regime_detector=RegimeDetector(),
    )

    unsuppressed_pnl = sum(trade.net_pnl for trade in unsuppressed.trades)
    suppressed_pnl = sum(trade.net_pnl for trade in suppressed.trades)

    assert suppressed.suppressed_signals
    assert unsuppressed_pnl < 0.0
    assert suppressed_pnl > unsuppressed_pnl


def _make_trending_dataset(count: int = 260) -> list[BarEvent]:
    start = datetime(2025, 2, 3, 14, 30, tzinfo=timezone.utc)
    price = 6000.0
    bars: list[BarEvent] = []
    for index in range(count):
        price += 1.1 + math.sin(index / 10) * 0.15
        close = price
        bars.append(
            BarEvent(
                instrument_id="MES",
                ts_utc=start + timedelta(minutes=index),
                open=close - 0.15,
                high=close + 0.6,
                low=close - 0.6,
                close=close,
                volume=2600.0,
                bar_size="1m",
            )
        )
    return bars
