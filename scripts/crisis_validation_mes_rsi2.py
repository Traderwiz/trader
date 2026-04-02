"""Run crisis-period validation for MES RSI(2) mean reversion."""

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

from mes_rsi2_common import dt, format_metrics, run_backtest


PERIODS = {
    "financial_crisis_2008": (date(2008, 1, 1), date(2009, 3, 31)),
    "covid_crash_2020": (date(2020, 1, 1), date(2020, 12, 31)),
    "rate_rise_2022": (date(2022, 1, 1), date(2022, 12, 31)),
}


def main() -> None:
    print("MES RSI(2) Mean Reversion Crisis Validation")
    for label, (start_day, end_day) in PERIODS.items():
        result = run_backtest(dt(start_day), dt(end_day, end_of_day=True))
        print(f"period: {label} ({start_day.isoformat()} -> {end_day.isoformat()})")
        for line in format_metrics(result.metrics):
            print(line)
        print(f"  trades: {len(result.trades)}")
        print(f"  max_drawdown: {result.metrics.max_drawdown_pct:.6f}")
        print(f"  regime_filter_suppressed_any_signals: {'yes' if result.suppressed_signals else 'no'}")
        print(f"  suppressed_signal_count: {len(result.suppressed_signals)}")


if __name__ == "__main__":
    main()
