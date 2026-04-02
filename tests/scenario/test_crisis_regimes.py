"""Scenario tests for crisis-like regime validation with deterministic synthetic bars."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

from platform.backtest.engine import BacktestEngine
from platform.data.catalog import load_instrument_catalog
from platform.data.parquet_store import ParquetStore
from platform.models.market_data import BarEvent
from platform.models.orders import SignalIntent, SignalSide
from platform.strategy.base import Strategy


class CrisisMeanReversionStrategy(Strategy):
    """Mean-reversion stub that validates frontier-bounded access in scenario runs."""

    instrument_id = "MES"
    bar_size = "1m"
    warmup_bars = 8
    supported_regimes = ("ranging", "volatile")

    def initialize(self) -> None:
        self.lookahead_violations = 0
        self.frontier_checks = 0

    def on_bar(self, bar: BarEvent) -> None:
        assert self.history is not None
        visible = self.history.window(min(self.history.count, 8))
        self.frontier_checks += 1
        if visible[-1].ts_utc != bar.ts_utc:
            self.lookahead_violations += 1
        if not self.is_warm:
            return

        average_close = sum(item.close for item in visible) / len(visible)
        distance = bar.close - average_close
        if distance <= -4.0:
            side = SignalSide.LONG
            reason = "oversold"
        elif distance >= 4.0:
            side = SignalSide.SHORT
            reason = "overbought"
        else:
            side = SignalSide.FLAT
            reason = "mean_exit"

        self.emit_signal(
            SignalIntent(
                strategy_id=self.strategy_id,
                strategy_version=self.strategy_version,
                instrument_id=self.instrument_id,
                side=side,
                signal_ts=bar.ts_utc,
                reason=reason,
                metadata={"distance": round(distance, 4)},
            ),
        )


def test_crisis_regime_scenarios_produce_metrics_without_lookahead(tmp_path) -> None:
    catalog = load_instrument_catalog(Path(__file__).resolve().parents[2] / "config" / "instruments.yaml")

    scenarios = {
        "financial_crisis_2008": _make_2008_crisis_bars(),
        "covid_crash_2020": _make_2020_crash_recovery_bars(),
        "rate_rise_2022": _make_2022_rate_rise_bars(),
    }

    for name, bars in scenarios.items():
        store = ParquetStore(tmp_path / name / "var" / "data")
        store.write_bars(bars)
        engine = BacktestEngine(parquet_store=store, instrument_catalog=catalog, initial_capital=5_000.0)
        strategy = CrisisMeanReversionStrategy()

        result = engine.run(strategy, start=bars[0].ts_utc, end=bars[-1].ts_utc)

        assert strategy.lookahead_violations == 0
        assert strategy.frontier_checks == len(bars)
        assert result.metrics.trade_count >= 1
        assert result.metrics.total_slippage_paid > 0.0
        assert result.metrics.max_drawdown_pct >= 0.0
        assert math.isfinite(result.metrics.cagr) or math.isinf(result.metrics.cagr)


def _make_2008_crisis_bars() -> list[BarEvent]:
    """Create a high-volatility, strong-downtrend path."""

    start = datetime(2008, 9, 15, 13, 30, tzinfo=timezone.utc)
    bars: list[BarEvent] = []
    price = 1200.0
    for index in range(140):
        drift = -2.2
        shock = math.sin(index / 2) * 5.5
        close = price + drift + shock
        bars.append(_bar_from_close(start + timedelta(minutes=index), close, width=6.0, volume=4_000.0))
        price = close
    return bars


def _make_2020_crash_recovery_bars() -> list[BarEvent]:
    """Create a fast crash followed by a fast recovery."""

    start = datetime(2020, 3, 16, 13, 30, tzinfo=timezone.utc)
    bars: list[BarEvent] = []
    price = 2900.0
    for index in range(150):
        if index < 50:
            drift = -7.5
        elif index < 100:
            drift = 8.0
        else:
            drift = math.sin(index / 3) * 1.5
        shock = math.cos(index / 2) * 6.0
        close = price + drift + shock
        bars.append(_bar_from_close(start + timedelta(minutes=index), close, width=8.0, volume=5_500.0))
        price = close
    return bars


def _make_2022_rate_rise_bars() -> list[BarEvent]:
    """Create a persistent grind lower with elevated volatility."""

    start = datetime(2022, 6, 13, 13, 30, tzinfo=timezone.utc)
    bars: list[BarEvent] = []
    price = 4100.0
    for index in range(160):
        drift = -1.0
        shock = math.sin(index / 4) * 3.0 + math.cos(index / 7) * 2.0
        close = price + drift + shock
        bars.append(_bar_from_close(start + timedelta(minutes=index), close, width=5.0, volume=3_500.0))
        price = close
    return bars


def _bar_from_close(ts_utc: datetime, close: float, *, width: float, volume: float) -> BarEvent:
    """Create one deterministic bar around a closing price."""

    open_price = close - 0.5
    high = max(open_price, close) + width / 2
    low = min(open_price, close) - width / 2
    return BarEvent(
        instrument_id="MES",
        ts_utc=ts_utc,
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=volume,
        bar_size="1m",
    )

