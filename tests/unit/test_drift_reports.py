"""Unit tests for paper-vs-model drift reporting."""

from __future__ import annotations

from platform.backtest.reports import DriftFillComparison, DriftReportStore, build_drift_report
from platform.models import OrderSide


def test_drift_report_computes_mean_worst_case_and_fill_rate(tmp_path) -> None:
    report = build_drift_report(
        strategy_id="TrendFollower",
        version="3.1.0",
        comparisons=[
            DriftFillComparison(fill_id="1", side=OrderSide.BUY, model_fill_price=100.0, actual_fill_price=101.0),
            DriftFillComparison(fill_id="2", side=OrderSide.SELL, model_fill_price=100.0, actual_fill_price=99.5),
            DriftFillComparison(fill_id="3", side=OrderSide.BUY, model_fill_price=102.0, actual_fill_price=None),
        ],
    )

    assert report.fill_rate == 2 / 3
    assert report.mean_slippage_delta == 0.75
    assert report.worst_case_slippage_delta == 1.0

    path = DriftReportStore(tmp_path / "var" / "reports").write(report)
    assert path.name == "drift_report.json"
    loaded = DriftReportStore(tmp_path / "var" / "reports").read("TrendFollower", "3.1.0")
    assert loaded.mean_slippage_delta == 0.75
    assert loaded.worst_case_slippage_delta == 1.0
