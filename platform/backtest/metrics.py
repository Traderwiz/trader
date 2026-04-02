"""Standard backtest metrics computed from completed trades and equity curves."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from platform.models.orders import SignalSide


@dataclass(frozen=True)
class CompletedTrade:
    """A completed trade used for backtest metrics."""

    instrument_id: str
    side: SignalSide
    entry_ts: datetime
    exit_ts: datetime
    entry_price: float
    exit_price: float
    quantity: float
    gross_pnl: float
    net_pnl: float
    fees_paid: float
    slippage_paid: float
    entry_reason: str = ""
    exit_reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EquityPoint:
    """One timestamped point on the simulated equity curve."""

    ts_utc: datetime
    equity: float


@dataclass(frozen=True)
class BacktestMetrics:
    """Typed summary of a backtest run."""

    cagr: float
    sharpe_ratio: float
    max_drawdown_pct: float
    win_rate: float
    profit_factor: float
    average_win: float
    average_loss: float
    trade_count: int
    exposure_time_pct: float
    total_fees_paid: float
    total_slippage_paid: float


def compute_backtest_metrics(
    trades: list[CompletedTrade],
    equity_curve: list[EquityPoint],
    risk_free_rate: float = 0.0,
) -> BacktestMetrics:
    """Compute the standard metrics required by Phase 2."""

    profits = [trade.net_pnl for trade in trades if trade.net_pnl > 0]
    losses = [trade.net_pnl for trade in trades if trade.net_pnl < 0]
    total_fees = sum(trade.fees_paid for trade in trades)
    total_slippage = sum(trade.slippage_paid for trade in trades)

    return BacktestMetrics(
        cagr=_compute_cagr(equity_curve),
        sharpe_ratio=_compute_sharpe_ratio(equity_curve, risk_free_rate=risk_free_rate),
        max_drawdown_pct=_compute_max_drawdown_pct(equity_curve),
        win_rate=(len(profits) / len(trades)) if trades else 0.0,
        profit_factor=_compute_profit_factor(profits, losses),
        average_win=(sum(profits) / len(profits)) if profits else 0.0,
        average_loss=(sum(losses) / len(losses)) if losses else 0.0,
        trade_count=len(trades),
        exposure_time_pct=_compute_exposure_time_pct(trades, equity_curve),
        total_fees_paid=total_fees,
        total_slippage_paid=total_slippage,
    )


def _compute_cagr(equity_curve: list[EquityPoint]) -> float:
    """Compute compound annual growth rate from an equity curve."""

    if len(equity_curve) < 2 or equity_curve[0].equity <= 0:
        return 0.0
    start = equity_curve[0]
    end = equity_curve[-1]
    total_years = (end.ts_utc - start.ts_utc).total_seconds() / (365.25 * 24 * 60 * 60)
    if total_years <= 0:
        return 0.0
    return (end.equity / start.equity) ** (1 / total_years) - 1


def _compute_sharpe_ratio(equity_curve: list[EquityPoint], risk_free_rate: float) -> float:
    """Compute annualized Sharpe ratio from periodic equity returns."""

    if len(equity_curve) < 3:
        return 0.0

    returns: list[float] = []
    deltas: list[float] = []
    for previous, current in zip(equity_curve, equity_curve[1:]):
        if previous.equity <= 0:
            continue
        returns.append((current.equity - previous.equity) / previous.equity)
        deltas.append((current.ts_utc - previous.ts_utc).total_seconds())

    if len(returns) < 2:
        return 0.0

    avg_delta_seconds = statistics.fmean(delta for delta in deltas if delta > 0)
    if avg_delta_seconds <= 0:
        return 0.0
    periods_per_year = (365.25 * 24 * 60 * 60) / avg_delta_seconds
    risk_free_per_period = risk_free_rate / periods_per_year
    excess_returns = [value - risk_free_per_period for value in returns]
    std_dev = statistics.stdev(excess_returns)
    if math.isclose(std_dev, 0.0):
        return 0.0
    return statistics.fmean(excess_returns) / std_dev * math.sqrt(periods_per_year)


def _compute_max_drawdown_pct(equity_curve: list[EquityPoint]) -> float:
    """Compute the maximum percentage drawdown."""

    if not equity_curve:
        return 0.0

    peak = equity_curve[0].equity
    max_drawdown = 0.0
    for point in equity_curve:
        peak = max(peak, point.equity)
        if peak <= 0:
            continue
        drawdown = (peak - point.equity) / peak
        max_drawdown = max(max_drawdown, drawdown)
    return max_drawdown


def _compute_profit_factor(profits: list[float], losses: list[float]) -> float:
    """Compute profit factor."""

    gross_profit = sum(profits)
    gross_loss = abs(sum(losses))
    if math.isclose(gross_loss, 0.0):
        return math.inf if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def _compute_exposure_time_pct(trades: list[CompletedTrade], equity_curve: list[EquityPoint]) -> float:
    """Compute the percentage of total backtest time spent in a position."""

    if len(equity_curve) < 2:
        return 0.0

    total_span = (equity_curve[-1].ts_utc - equity_curve[0].ts_utc).total_seconds()
    if total_span <= 0:
        return 0.0

    exposure_seconds = sum((trade.exit_ts - trade.entry_ts).total_seconds() for trade in trades)
    return max(0.0, min(1.0, exposure_seconds / total_span))
