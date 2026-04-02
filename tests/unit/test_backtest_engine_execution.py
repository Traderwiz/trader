"""Execution-timing tests for the backtest engine."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from platform.backtest.engine import BacktestEngine
from platform.data.catalog import load_instrument_catalog
from platform.data.parquet_store import ParquetStore
from platform.models.market_data import BarEvent
from platform.models.orders import SignalIntent, SignalSide
from platform.strategy.base import Strategy


class NextOpenStopStrategy(Strategy):
    instrument_id = "MES"
    bar_size = "1m"
    warmup_bars = 1

    def initialize(self) -> None:
        pass

    def on_bar(self, bar: BarEvent) -> None:
        assert self.history is not None
        if self.history.count == 1:
            self.emit_signal(
                SignalIntent(
                    strategy_id=self.strategy_id,
                    strategy_version=self.strategy_version,
                    instrument_id=self.instrument_id,
                    side=SignalSide.LONG,
                    signal_ts=bar.ts_utc,
                    reason="entry",
                    metadata={"execution_timing": "next_open"},
                )
            )
        elif self.history.count == 2:
            self.emit_signal(
                SignalIntent(
                    strategy_id=self.strategy_id,
                    strategy_version=self.strategy_version,
                    instrument_id=self.instrument_id,
                    side=SignalSide.FLAT,
                    signal_ts=bar.ts_utc,
                    reason="stop_loss",
                    metadata={"execution_timing": "current_bar", "reference_price": 99.0},
                )
            )


def test_backtest_engine_executes_next_open_entry_and_same_bar_stop_exit(tmp_path) -> None:
    catalog = load_instrument_catalog(Path(__file__).resolve().parents[2] / "config" / "instruments.yaml")
    store = ParquetStore(tmp_path / "var" / "data")
    bars = _bars()
    store.write_bars(bars)
    engine = BacktestEngine(parquet_store=store, instrument_catalog=catalog, initial_capital=5_000.0)

    result = engine.run(NextOpenStopStrategy(), start=bars[0].ts_utc, end=bars[-1].ts_utc)

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.entry_reason == "entry"
    assert trade.exit_reason == "stop_loss"
    assert trade.entry_ts == bars[1].ts_utc
    assert trade.exit_ts == bars[1].ts_utc
    assert trade.entry_price == 101.375
    assert trade.exit_price == 98.625


def _bars() -> list[BarEvent]:
    start = datetime(2025, 1, 2, 14, 30, tzinfo=timezone.utc)
    return [
        BarEvent(
            instrument_id="MES",
            ts_utc=start,
            open=100.0,
            high=100.5,
            low=99.5,
            close=100.0,
            volume=0.0,
            bar_size="1m",
        ),
        BarEvent(
            instrument_id="MES",
            ts_utc=start + timedelta(minutes=1),
            open=101.0,
            high=101.5,
            low=98.0,
            close=100.0,
            volume=0.0,
            bar_size="1m",
        ),
    ]
