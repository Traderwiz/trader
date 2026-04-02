"""Run the authoritative full-history backtest for MES RSI(2) mean reversion."""

from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
stdlib_platform = sys.modules.get("platform")
if stdlib_platform is not None and not hasattr(stdlib_platform, "__path__"):
    sys.modules.pop("platform", None)

from mes_rsi2_common import (
    FULL_START,
    METRICS_PATH,
    TRADE_LOG_PATH,
    format_metrics,
    latest_bar_timestamp,
    metrics_to_dict,
    run_backtest,
    save_json,
    save_trade_log,
)


ALLOWED_EXIT_REASONS = {"stop_loss", "profit_target", "time_stop"}


def main() -> None:
    end = latest_bar_timestamp()
    result = run_backtest(FULL_START, end)

    checks = {
        "no_overlapping_positions": _no_overlaps(result),
        "all_entries_adx_le_20": all(float(trade.metadata.get("signal_adx_14", 999.0)) <= 20.0 for trade in result.trades),
        "all_entries_above_sma_200": all(float(trade.metadata.get("signal_close", 0.0)) > float(trade.metadata.get("signal_sma_200", 0.0)) for trade in result.trades),
        "all_exit_reasons_valid": all(trade.exit_reason in ALLOWED_EXIT_REASONS for trade in result.trades),
        "trade_count_gte_50": result.metrics.trade_count >= 50,
    }

    print("MES RSI(2) Mean Reversion Backtest")
    print(f"window: {FULL_START.date().isoformat()} -> {end.date().isoformat()}")
    print(f"suppressed_signals: {len(result.suppressed_signals)}")
    print("metrics:")
    for line in format_metrics(result.metrics):
        print(line)
    print("sanity_checks:")
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")

    if not all(checks.values()):
        raise SystemExit("One or more backtest sanity checks failed.")

    save_trade_log(result, TRADE_LOG_PATH)
    save_json(metrics_to_dict(result.metrics), METRICS_PATH)
    print(f"trade_log: {TRADE_LOG_PATH}")
    print(f"metrics_json: {METRICS_PATH}")


def _no_overlaps(result) -> bool:
    previous_exit = None
    for trade in result.trades:
        if previous_exit is not None and trade.entry_ts < previous_exit:
            return False
        previous_exit = trade.exit_ts
    return True


if __name__ == "__main__":
    main()
