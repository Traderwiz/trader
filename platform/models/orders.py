"""Canonical strategy output models used before sizing and execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class SignalSide(StrEnum):
    """Allowed directional strategy intents."""

    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"


@dataclass(frozen=True)
class SignalIntent:
    """A broker-agnostic strategy signal emitted into the sizing stack."""

    strategy_id: str
    strategy_version: str
    instrument_id: str
    side: SignalSide
    signal_ts: datetime
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name, value in (
            ("strategy_id", self.strategy_id),
            ("strategy_version", self.strategy_version),
            ("instrument_id", self.instrument_id),
            ("reason", self.reason),
        ):
            if not value.strip():
                raise ValueError(f"{name} must be non-empty.")
        if self.signal_ts.tzinfo is None or self.signal_ts.utcoffset() != timezone.utc.utcoffset(self.signal_ts):
            raise ValueError("signal_ts must be timezone-aware and in UTC.")

