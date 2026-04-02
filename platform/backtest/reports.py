"""Computes and stores paper-vs-model drift reports for promotion evidence."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from platform.models import OrderSide


@dataclass(frozen=True)
class DriftFillComparison:
    """One expected paper fill compared to its model fill estimate."""

    fill_id: str
    side: OrderSide
    model_fill_price: float
    actual_fill_price: float | None

    def slippage_delta(self) -> float | None:
        if self.actual_fill_price is None:
            return None
        if self.side is OrderSide.BUY:
            return self.actual_fill_price - self.model_fill_price
        return self.model_fill_price - self.actual_fill_price


@dataclass(frozen=True)
class DriftReport:
    """Summary of paper-vs-model fill drift for one strategy version."""

    strategy_id: str
    version: str
    generated_at: str
    expected_fill_count: int
    matched_fill_count: int
    fill_rate: float
    mean_slippage_delta: float
    worst_case_slippage_delta: float
    comparisons: tuple[dict[str, object], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "DriftReport":
        return cls(
            strategy_id=str(payload["strategy_id"]),
            version=str(payload["version"]),
            generated_at=str(payload["generated_at"]),
            expected_fill_count=int(payload["expected_fill_count"]),
            matched_fill_count=int(payload["matched_fill_count"]),
            fill_rate=float(payload["fill_rate"]),
            mean_slippage_delta=float(payload["mean_slippage_delta"]),
            worst_case_slippage_delta=float(payload["worst_case_slippage_delta"]),
            comparisons=tuple(payload.get("comparisons") or ()),
        )


def build_drift_report(
    *,
    strategy_id: str,
    version: str,
    comparisons: list[DriftFillComparison],
) -> DriftReport:
    """Compute the paper-vs-model drift summary required for live promotion evidence."""

    deltas = [delta for delta in (comparison.slippage_delta() for comparison in comparisons) if delta is not None]
    expected_fill_count = len(comparisons)
    matched_fill_count = len(deltas)
    fill_rate = 0.0 if expected_fill_count == 0 else matched_fill_count / expected_fill_count
    mean_slippage_delta = 0.0 if not deltas else sum(deltas) / len(deltas)
    worst_case_slippage_delta = 0.0 if not deltas else max(deltas)
    return DriftReport(
        strategy_id=strategy_id,
        version=version,
        generated_at=_utc_now(),
        expected_fill_count=expected_fill_count,
        matched_fill_count=matched_fill_count,
        fill_rate=fill_rate,
        mean_slippage_delta=mean_slippage_delta,
        worst_case_slippage_delta=worst_case_slippage_delta,
        comparisons=tuple(
            {
                "fill_id": comparison.fill_id,
                "side": comparison.side.value,
                "model_fill_price": comparison.model_fill_price,
                "actual_fill_price": comparison.actual_fill_price,
                "slippage_delta": comparison.slippage_delta(),
            }
            for comparison in comparisons
        ),
    )


@dataclass
class DriftReportStore:
    """Reads and writes drift reports beneath the runtime report root."""

    report_root: Path

    def write(self, report: DriftReport) -> Path:
        path = self.path_for(report.strategy_id, report.version)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report.to_dict(), sort_keys=True, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        return path

    def read(self, strategy_id: str, version: str) -> DriftReport:
        path = self.path_for(strategy_id, version)
        if not path.is_file():
            raise FileNotFoundError(f"Drift report not found for {strategy_id}@{version}")
        return DriftReport.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def path_for(self, strategy_id: str, version: str) -> Path:
        return (self.report_root / strategy_id / version / "drift_report.json").resolve()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
