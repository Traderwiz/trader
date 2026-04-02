"""Promotion bundle generation and report persistence."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from platform.backtest.reports import DriftReport, DriftReportStore
from platform.models import PromotionBundle
from platform.persistence.repositories import StrategyRegistryRepository


@dataclass
class PromotionSelector:
    """Builds and persists a promotion artifact bundle."""

    repository: StrategyRegistryRepository
    report_root: Path

    def build_bundle(
        self,
        *,
        strategy_id: str,
        version: str,
        walkforward_results: dict[str, Any],
        crisis_results: dict[str, Any],
        regime_suppression_comparison: dict[str, Any],
        gate_results: dict[str, Any],
        drift_report: DriftReport | None = None,
    ) -> PromotionBundle:
        bundle_gate_results = dict(gate_results)
        serialized_drift_report: dict[str, Any] = {}
        if drift_report is not None:
            DriftReportStore(self.report_root).write(drift_report)
            serialized_drift_report = drift_report.to_dict()
            paper_readiness = dict(bundle_gate_results.get("paper_readiness") or {})
            paper_readiness.setdefault("drift_report", serialized_drift_report)
            bundle_gate_results["paper_readiness"] = paper_readiness

        bundle = PromotionBundle(
            strategy_id=strategy_id,
            version=version,
            walkforward_results=walkforward_results,
            crisis_results=crisis_results,
            regime_suppression_comparison=regime_suppression_comparison,
            gate_results=bundle_gate_results,
            drift_report=serialized_drift_report,
        )
        self.repository.store_bundle(bundle)

        output_path = self.report_root / strategy_id / version / "promotion_bundle.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(bundle.to_dict(), sort_keys=True, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        return bundle
