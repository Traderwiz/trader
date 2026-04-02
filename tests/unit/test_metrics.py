"""Unit tests for standard backtest metric calculations."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from platform.backtest.metrics import CompletedTrade, EquityPoint, compute_backtest_metrics
from platform.models.orders import SignalSide


def test_compute_backtest_metrics_returns_expected_core_fields() -> None:
    trades = [
        CompletedTrade(
            instrument_id="MES",
            side=SignalSide.LONG,
            entry_ts=datetime(2025, 1, 1, tzinfo=timezone.utc),
            exit_ts=datetime(2025, 1, 6, tzinfo=timezone.utc),
            entry_price=6000.0,
            exit_price=6005.0,
            quantity=1,
            gross_pnl=25.0,
            net_pnl=23.76,
            fees_paid=1.24,
            slippage_paid=2.50,
        ),
        CompletedTrade(
            instrument_id="MES",
            side=SignalSide.SHORT,
            entry_ts=datetime(2025, 1, 7, tzinfo=timezone.utc),
            exit_ts=datetime(2025, 1, 12, tzinfo=timezone.utc),
            entry_price=5995.0,
            exit_price=6001.0,
            quantity=1,
            gross_pnl=-30.0,
            net_pnl=-31.24,
            fees_paid=1.24,
            slippage_paid=2.50,
        ),
    ]
    equity_curve = [
        EquityPoint(ts_utc=datetime(2025, 1, 1, tzinfo=timezone.utc), equity=10_000.0),
        EquityPoint(ts_utc=datetime(2025, 1, 6, tzinfo=timezone.utc), equity=10_023.76),
        EquityPoint(ts_utc=datetime(2025, 1, 12, tzinfo=timezone.utc), equity=9_992.52),
        EquityPoint(ts_utc=datetime(2026, 1, 1, tzinfo=timezone.utc), equity=10_100.0),
    ]

    metrics = compute_backtest_metrics(trades=trades, equity_curve=equity_curve)

    assert metrics.trade_count == 2
    assert metrics.win_rate == 0.5
    assert metrics.profit_factor == pytest.approx(23.76 / 31.24)
    assert metrics.average_win == pytest.approx(23.76)
    assert metrics.average_loss == pytest.approx(-31.24)
    assert metrics.total_fees_paid == pytest.approx(2.48)
    assert metrics.total_slippage_paid == pytest.approx(5.0)
    assert metrics.exposure_time_pct == pytest.approx(10 / 365, rel=1e-2)
    assert metrics.cagr > 0.0

