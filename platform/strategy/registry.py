"""Versioned strategy registry operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from platform.models import StrategyStage, StrategyVersionRecord
from platform.persistence.repositories import StrategyRegistryRepository
from platform.strategy.base import Strategy


@dataclass
class StrategyRegistry:
    """High-level registry wrapper around the persistent repository."""

    repository: StrategyRegistryRepository

    def register_strategy(
        self,
        *,
        strategy_id: str,
        version: str,
        description: str,
        parameters: dict[str, Any],
        allowed_instruments: tuple[str, ...],
        bar_sizes: tuple[str, ...],
        required_data: tuple[str, ...],
        supported_regimes: tuple[str, ...],
        hard_disallowed_regimes: tuple[str, ...] = (),
        volatility_cap: float | None = None,
        metadata: dict[str, Any] | None = None,
        current_stage: StrategyStage = StrategyStage.RESEARCH,
    ) -> StrategyVersionRecord:
        """Register or update one versioned strategy artifact."""

        now = _utc_now()
        return self.repository.upsert(
            StrategyVersionRecord(
                strategy_id=strategy_id,
                version=version,
                description=description,
                parameters=dict(parameters),
                allowed_instruments=tuple(allowed_instruments),
                bar_sizes=tuple(bar_sizes),
                required_data=tuple(required_data),
                supported_regimes=tuple(supported_regimes),
                hard_disallowed_regimes=tuple(hard_disallowed_regimes),
                volatility_cap=volatility_cap,
                metadata=dict(metadata or {}),
                current_stage=current_stage,
                created_at=now,
                updated_at=now,
            )
        )

    def register_strategy_class(
        self,
        strategy: type[Strategy],
        *,
        description: str,
        parameters: dict[str, Any] | None = None,
        required_data: tuple[str, ...] = (),
        current_stage: StrategyStage = StrategyStage.RESEARCH,
        metadata: dict[str, Any] | None = None,
    ) -> StrategyVersionRecord:
        """Register a Strategy subclass using its declared contract."""

        return self.register_strategy(
            strategy_id=strategy.__name__,
            version=strategy.strategy_version,
            description=description,
            parameters=dict(parameters or {}),
            allowed_instruments=(strategy.instrument_id,),
            bar_sizes=(strategy.bar_size,),
            required_data=required_data,
            supported_regimes=tuple(strategy.supported_regimes),
            hard_disallowed_regimes=tuple(strategy.hard_disallowed_regimes),
            volatility_cap=strategy.volatility_cap,
            metadata=dict(metadata or {}),
            current_stage=current_stage,
        )

    def get(self, strategy_id: str, version: str) -> StrategyVersionRecord:
        return self.repository.get(strategy_id, version)

    def list_all(self) -> list[StrategyVersionRecord]:
        return self.repository.list_all()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
