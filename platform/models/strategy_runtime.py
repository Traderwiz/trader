"""Persistent strategy runtime state and paper trade models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class StrategyRuntimeRecord:
    """One persisted strategy runtime snapshot."""

    strategy_id: str
    version: str
    stage: str
    state: dict[str, Any] = field(default_factory=dict)
    updated_at: str = ""

    def __post_init__(self) -> None:
        for name, value in (("strategy_id", self.strategy_id), ("version", self.version), ("stage", self.stage)):
            if not value.strip():
                raise ValueError(f"{name} must be non-empty.")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StrategyTradeRecord:
    """One persisted closed paper trade for a strategy."""

    strategy_id: str
    version: str
    instrument_id: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    exit_reason: str
    pnl: float
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def __post_init__(self) -> None:
        for name, value in (
            ("strategy_id", self.strategy_id),
            ("version", self.version),
            ("instrument_id", self.instrument_id),
            ("entry_date", self.entry_date),
            ("exit_date", self.exit_date),
            ("exit_reason", self.exit_reason),
        ):
            if not value.strip():
                raise ValueError(f"{name} must be non-empty.")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
