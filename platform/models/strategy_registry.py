"""Versioned strategy registry and promotion bundle models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from platform.models.strategy_stage import StrategyStage


@dataclass(frozen=True)
class StrategyVersionRecord:
    """One immutable strategy version with mutable lifecycle stage."""

    strategy_id: str
    version: str
    description: str
    parameters: dict[str, Any]
    allowed_instruments: tuple[str, ...]
    bar_sizes: tuple[str, ...]
    required_data: tuple[str, ...]
    supported_regimes: tuple[str, ...]
    hard_disallowed_regimes: tuple[str, ...] = field(default_factory=tuple)
    volatility_cap: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    current_stage: StrategyStage = StrategyStage.RESEARCH
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        for name, value in (
            ("strategy_id", self.strategy_id),
            ("version", self.version),
            ("description", self.description),
        ):
            if not value.strip():
                raise ValueError(f"{name} must be non-empty.")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["current_stage"] = self.current_stage.value
        return payload


@dataclass(frozen=True)
class PromotionBundle:
    """Serialized promotion evidence used by lifecycle gate checks."""

    strategy_id: str
    version: str
    walkforward_results: dict[str, Any]
    crisis_results: dict[str, Any]
    regime_suppression_comparison: dict[str, Any]
    gate_results: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)
    drift_report: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.strategy_id.strip():
            raise ValueError("strategy_id must be non-empty.")
        if not self.version.strip():
            raise ValueError("version must be non-empty.")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
