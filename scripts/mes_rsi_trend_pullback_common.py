"""Shared utilities for MES RSI trend-pullback validation scripts."""

from __future__ import annotations

import csv
import json
import sys
from dataclasses import asdict, replace
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
stdlib_platform = sys.modules.get("platform")
if stdlib_platform is not None and not hasattr(stdlib_platform, "__path__"):
    sys.modules.pop("platform", None)

from platform.backtest.engine import BacktestEngine, BacktestResult
from platform.backtest.metrics import BacktestMetrics, EquityPoint, compute_backtest_metrics
from platform.data.catalog import InstrumentCatalog, load_instrument_catalog
from platform.data.parquet_store import ParquetStore
from strategies.mes_rsi_trend_pullback import MESRSITrendPullbackStrategy

UTC = timezone.utc
INITIAL_CAPITAL = 10_000.0
BACKFILL_DAYS = 400
STRATEGY_ID = "mes_rsi_trend_pullback"
VERSION = "1.0.0"
FULL_START = datetime(2000, 9, 18, tzinfo=UTC)
REPORT_DIR = PROJECT_ROOT / "var" / "reports" / STRATEGY_ID / VERSION
TRADE_LOG_PATH = REPORT_DIR / "trade_log.csv"
METRICS_PATH = REPORT_DIR / "backtest_metrics.json"
WALKFORWARD_PATH = REPORT_DIR / "walkforward_results.json"


def parquet_store() -> ParquetStore:
    return ParquetStore(PROJECT_ROOT / "var" / "data")


def instrument_catalog() -> InstrumentCatalog:
    catalog = load_instrument_catalog(PROJECT_ROOT / "config" / "instruments.yaml")
    mes = catalog.get("MES")
    spread_half_ticks = dict(mes.cost_profile.spread_half_ticks)
    if spread_half_ticks:
        spread_half_ticks = {session: 1.0 for session in spread_half_ticks}
    else:
        spread_half_ticks = {"default": 1.0}
    spread_half_ticks.setdefault("default", 1.0)
    adjusted_mes = replace(
        mes,
        cost_profile=replace(
            mes.cost_profile,
            commission_per_side=0.62,
            spread_half_ticks=spread_half_ticks,
            minimum_slippage_ticks=1.0,
            additional_impact_per_unit=0.0,
        ),
    )
    instruments = dict(catalog.instruments)
    instruments["MES"] = adjusted_mes
    return InstrumentCatalog(instruments=instruments)


def backtest_engine(initial_capital: float = INITIAL_CAPITAL) -> BacktestEngine:
    return BacktestEngine(
        parquet_store=parquet_store(),
        instrument_catalog=instrument_catalog(),
        initial_capital=initial_capital,
    )


def latest_bar_timestamp() -> datetime:
    bars = parquet_store().read_bars(
        instrument_id="MES",
        start=FULL_START,
        end=datetime(2100, 1, 1, tzinfo=UTC),
        bar_size="1D",
    )
    if not bars:
        raise ValueError("No MES daily bars found in Parquet store.")
    return max(bar.ts_utc for bar in bars)


def run_backtest(start: datetime, end: datetime, initial_capital: float = INITIAL_CAPITAL) -> BacktestResult:
    engine = backtest_engine(initial_capital=initial_capital)
    return engine.run(MESRSITrendPullbackStrategy(), start=start, end=end)


def run_backtest_with_backfill(
    start: datetime,
    end: datetime,
    initial_capital: float = INITIAL_CAPITAL,
    backfill_days: int = BACKFILL_DAYS,
) -> BacktestResult:
    engine = backtest_engine(initial_capital=initial_capital)
    backfill_start = max(FULL_START, start - timedelta(days=backfill_days))
    result = engine.run(MESRSITrendPullbackStrategy(), start=backfill_start, end=end)
    return slice_result(result, start=start, end=end, initial_equity=initial_capital)


def slice_result(
    result: BacktestResult,
    *,
    start: datetime,
    end: datetime,
    initial_equity: float = INITIAL_CAPITAL,
) -> BacktestResult:
    trades = [trade for trade in result.trades if trade.entry_ts >= start and trade.exit_ts <= end]
    equity_points = [point for point in result.equity_curve if start <= point.ts_utc <= end]
    rebased_curve = _rebase_window_equity_curve(equity_points, initial_equity=initial_equity)
    metrics = compute_backtest_metrics(trades=trades, equity_curve=rebased_curve)
    signals = [signal for signal in result.signals if start <= signal.signal_ts <= end]
    suppressed = [signal for signal in result.suppressed_signals if start <= signal.ts_utc <= end]
    return BacktestResult(
        metrics=metrics,
        trades=trades,
        equity_curve=rebased_curve,
        signals=signals,
        suppressed_signals=suppressed,
    )


def metrics_to_dict(metrics: BacktestMetrics) -> dict[str, Any]:
    return asdict(metrics)


def format_metrics(metrics: BacktestMetrics) -> list[str]:
    return [
        f"  cagr: {metrics.cagr:.6f}",
        f"  sharpe_ratio: {metrics.sharpe_ratio:.6f}",
        f"  max_drawdown_pct: {metrics.max_drawdown_pct:.6f}",
        f"  win_rate: {metrics.win_rate:.6f}",
        f"  profit_factor: {metrics.profit_factor:.6f}",
        f"  average_win: {metrics.average_win:.6f}",
        f"  average_loss: {metrics.average_loss:.6f}",
        f"  trade_count: {metrics.trade_count}",
        f"  exposure_time_pct: {metrics.exposure_time_pct:.6f}",
        f"  total_fees_paid: {metrics.total_fees_paid:.6f}",
        f"  total_slippage_paid: {metrics.total_slippage_paid:.6f}",
    ]


def save_trade_log(result: BacktestResult, path: Path = TRADE_LOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cumulative_pnl = 0.0
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "entry_date",
                "exit_date",
                "entry_price",
                "exit_price",
                "exit_reason",
                "pnl_points",
                "pnl_dollars",
                "cumulative_pnl",
            ],
        )
        writer.writeheader()
        for trade in result.trades:
            direction = 1.0 if trade.side.value == "LONG" else -1.0
            pnl_points = (trade.exit_price - trade.entry_price) * direction
            cumulative_pnl += trade.net_pnl
            writer.writerow(
                {
                    "entry_date": trade.entry_ts.date().isoformat(),
                    "exit_date": trade.exit_ts.date().isoformat(),
                    "entry_price": f"{trade.entry_price:.4f}",
                    "exit_price": f"{trade.exit_price:.4f}",
                    "exit_reason": trade.exit_reason,
                    "pnl_points": f"{pnl_points:.4f}",
                    "pnl_dollars": f"{trade.net_pnl:.4f}",
                    "cumulative_pnl": f"{cumulative_pnl:.4f}",
                }
            )


def save_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def rebase_equity_curve(points: list[EquityPoint], starting_equity: float) -> list[EquityPoint]:
    if not points:
        return []
    anchor = points[0].equity
    return [EquityPoint(ts_utc=point.ts_utc, equity=starting_equity + (point.equity - anchor)) for point in points]


def combine_equity_curves(curves: list[list[EquityPoint]], initial_equity: float = INITIAL_CAPITAL) -> list[EquityPoint]:
    combined: list[EquityPoint] = []
    current_equity = initial_equity
    for curve in curves:
        rebased = rebase_equity_curve(curve, current_equity)
        if not rebased:
            continue
        if combined and rebased[0].ts_utc == combined[-1].ts_utc:
            combined.extend(rebased[1:])
        else:
            combined.extend(rebased)
        current_equity = rebased[-1].equity
    return combined


def dt(day: date, end_of_day: bool = False) -> datetime:
    clock = time.max if end_of_day else time.min
    return datetime.combine(day, clock, tzinfo=UTC)


def _rebase_window_equity_curve(points: list[EquityPoint], *, initial_equity: float) -> list[EquityPoint]:
    if not points:
        return []
    anchor = points[0].equity
    return [EquityPoint(ts_utc=point.ts_utc, equity=initial_equity + (point.equity - anchor)) for point in points]
