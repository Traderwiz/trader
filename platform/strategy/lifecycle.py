"""Manual lifecycle promotion and demotion rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from platform.models import PromotionBundle, StrategyStage, StrategyVersionRecord


class LifecycleError(RuntimeError):
    """Raised when a promotion or demotion request is invalid."""


@dataclass(frozen=True)
class GateEvaluation:
    """Structured gate evaluation result."""

    allowed: bool
    gate_results: dict[str, Any]
    next_stage: StrategyStage


@dataclass
class StrategyLifecycleManager:
    """Applies spec-defined lifecycle rules to a strategy version."""

    def evaluate_promotion(self, record: StrategyVersionRecord, bundle: PromotionBundle) -> GateEvaluation:
        """Evaluate the next-stage promotion request against the provided bundle."""

        next_stage = _next_stage(record.current_stage)
        if next_stage is StrategyStage.BACKTEST:
            gate_results = {"manual_review_required": True}
            return GateEvaluation(allowed=True, gate_results=gate_results, next_stage=next_stage)
        if next_stage is StrategyStage.PAPER:
            gate_results = self._backtest_to_paper_gates(bundle)
            return GateEvaluation(
                allowed=all(bool(result["passed"]) for result in gate_results.values()),
                gate_results=gate_results,
                next_stage=next_stage,
            )
        if next_stage is StrategyStage.LIVE:
            gate_results = self._paper_to_live_gates(bundle)
            return GateEvaluation(
                allowed=all(bool(result["passed"]) for result in gate_results.values()),
                gate_results=gate_results,
                next_stage=next_stage,
            )
        raise LifecycleError(f"Unsupported promotion target from {record.current_stage.value}")

    def demote(self, record: StrategyVersionRecord, target_stage: StrategyStage) -> StrategyStage:
        """Validate a manual demotion request."""

        stage_order = list(StrategyStage)
        if stage_order.index(target_stage) > stage_order.index(record.current_stage):
            raise LifecycleError("Demotion target must not be a higher lifecycle stage.")
        return target_stage

    def _backtest_to_paper_gates(self, bundle: PromotionBundle) -> dict[str, Any]:
        aggregate = dict(bundle.walkforward_results.get("aggregate_oos_metrics") or {})
        suppression = dict(bundle.regime_suppression_comparison or {})
        crisis = dict(bundle.crisis_results or {})
        return {
            "walkforward_completed": {"passed": bool(bundle.walkforward_results.get("windows"))},
            "crisis_suite_passed": {
                "passed": all(crisis.get(year, {}).get("passed", False) for year in ("2008", "2020", "2022"))
            },
            "profit_factor": {"passed": float(aggregate.get("profit_factor", 0.0)) > 1.20},
            "sharpe_ratio": {"passed": float(aggregate.get("sharpe_ratio", 0.0)) > 1.00},
            "max_drawdown_pct": {"passed": float(aggregate.get("max_drawdown_pct", 1.0)) < 0.12},
            "win_rate": {"passed": float(aggregate.get("win_rate", 0.0)) > 0.55},
            "minimum_trades": {"passed": int(aggregate.get("trade_count", 0)) >= 100},
            "regime_suppression_reduces_losses": {
                "passed": float(suppression.get("loss_delta", 0.0)) > 0.0
            },
        }

    def _paper_to_live_gates(self, bundle: PromotionBundle) -> dict[str, Any]:
        paper = dict(bundle.gate_results.get("paper_readiness") or {})
        return {
            "minimum_20_sessions": {"passed": int(paper.get("paper_sessions", 0)) >= 20},
            "no_unresolved_reconciliation_mismatches": {
                "passed": int(paper.get("unresolved_reconciliation_mismatches", 1)) == 0
            },
            "slippage_within_tolerance": {"passed": bool(paper.get("slippage_within_tolerance", False))},
            "no_repeated_broker_rejections": {"passed": bool(paper.get("no_repeated_broker_rejections", False))},
            "operator_signoff": {"passed": bool(paper.get("operator_signoff", False))},
        }


def _next_stage(stage: StrategyStage) -> StrategyStage:
    if stage is StrategyStage.RESEARCH:
        return StrategyStage.BACKTEST
    if stage is StrategyStage.BACKTEST:
        return StrategyStage.PAPER
    if stage is StrategyStage.PAPER:
        return StrategyStage.LIVE
    raise LifecycleError("Strategies in LIVE cannot be auto-promoted to another stage.")
