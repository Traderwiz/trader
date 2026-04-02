"""Run rolling walk-forward validation for MES RSI(2) mean reversion."""

from __future__ import annotations

from datetime import date
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
stdlib_platform = sys.modules.get("platform")
if stdlib_platform is not None and not hasattr(stdlib_platform, "__path__"):
    sys.modules.pop("platform", None)

from platform.backtest.metrics import compute_backtest_metrics
from mes_rsi2_common import (
    FULL_START,
    WALKFORWARD_PATH,
    combine_equity_curves,
    dt,
    format_metrics,
    latest_bar_timestamp,
    metrics_to_dict,
    run_backtest,
    save_json,
)


def main() -> None:
    latest = latest_bar_timestamp().date()
    windows: list[dict[str, object]] = []
    oos_trades = []
    oos_curves = []

    print("MES RSI(2) Mean Reversion Walk-Forward")
    for test_year in range(2003, latest.year + 1):
        test_start_day = date(test_year, 1, 1)
        if test_start_day > latest:
            break
        train_start_day = max(FULL_START.date(), date(test_year - 3, 1, 1))
        train_end_day = date(test_year - 1, 12, 31)
        test_end_day = min(date(test_year, 12, 31), latest)

        train_result = run_backtest(dt(train_start_day), dt(train_end_day, end_of_day=True))
        test_result = run_backtest(dt(test_start_day), dt(test_end_day, end_of_day=True))
        oos_trades.extend(test_result.trades)
        oos_curves.append(test_result.equity_curve)

        window_payload = {
            "train_start": train_start_day.isoformat(),
            "train_end": train_end_day.isoformat(),
            "test_start": test_start_day.isoformat(),
            "test_end": test_end_day.isoformat(),
            "train_metrics": metrics_to_dict(train_result.metrics),
            "test_metrics": metrics_to_dict(test_result.metrics),
        }
        windows.append(window_payload)

        print(f"window: train {train_start_day.isoformat()} -> {train_end_day.isoformat()} | test {test_start_day.isoformat()} -> {test_end_day.isoformat()}")
        print("  train_metrics:")
        for line in format_metrics(train_result.metrics):
            print(line)
        print("  test_metrics:")
        for line in format_metrics(test_result.metrics):
            print(line)

    aggregate_metrics = compute_backtest_metrics(trades=oos_trades, equity_curve=combine_equity_curves(oos_curves))
    print("aggregate_oos_metrics:")
    for line in format_metrics(aggregate_metrics):
        print(line)

    save_json(
        {
            "mode": "rolling_calendar",
            "train_window_years": 3,
            "test_window_years": 1,
            "windows": windows,
            "aggregate_oos_metrics": metrics_to_dict(aggregate_metrics),
        },
        WALKFORWARD_PATH,
    )
    print(f"walkforward_json: {WALKFORWARD_PATH}")


if __name__ == "__main__":
    main()
