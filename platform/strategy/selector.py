"""Promotion bundle generation and report persistence."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
    ) -> PromotionBundle:
        bundle = PromotionBundle(
            strategy_id=strategy_id,
            version=version,
            walkforward_results=walkforward_results,
            crisis_results=crisis_results,
            regime_suppression_comparison=regime_suppression_comparison,
            gate_results=gate_results,
        )
        self.repository.store_bundle(bundle)

        output_path = self.report_root / strategy_id / version / "promotion_bundle.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(bundle.to_dict(), sort_keys=True, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        return bundle
