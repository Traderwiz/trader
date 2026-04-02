"""Regime feature, state, and suppression decision models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def _require_utc(ts_utc: datetime) -> None:
    if ts_utc.tzinfo is None or ts_utc.utcoffset() != timezone.utc.utcoffset(ts_utc):
        raise ValueError("ts_utc must be timezone-aware and in UTC.")


@dataclass(frozen=True)
class RegimeFeatures:
    """Computed per-bar regime features."""

    instrument_id: str
    timeframe: str
    ts_utc: datetime
    adx_14: float
    ema_50: float
    ema_200: float
    ema_50_slope: float
    ema_200_slope: float
    normalized_ema_spread: float
    atr_14: float
    atr_percentile: float
    bollinger_width: float
    bollinger_width_percentile: float
    bollinger_width_median: float

    def __post_init__(self) -> None:
        if not self.instrument_id.strip():
            raise ValueError("instrument_id must be non-empty.")
        if not self.timeframe.strip():
            raise ValueError("timeframe must be non-empty.")
        _require_utc(self.ts_utc)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ts_utc"] = self.ts_utc.isoformat().replace("+00:00", "Z")
        return payload


@dataclass(frozen=True)
class RegimeState:
    """Stored regime state for one instrument/timeframe at one bar."""

    instrument_id: str
    timeframe: str
    ts_utc: datetime
    primary_regime: str
    volatile: bool
    features: RegimeFeatures
    reasons: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.instrument_id.strip():
            raise ValueError("instrument_id must be non-empty.")
        if not self.timeframe.strip():
            raise ValueError("timeframe must be non-empty.")
        if not self.primary_regime.strip():
            raise ValueError("primary_regime must be non-empty.")
        _require_utc(self.ts_utc)

    def to_dict(self) -> dict[str, Any]:
        return {
            "instrument_id": self.instrument_id,
            "timeframe": self.timeframe,
            "ts_utc": self.ts_utc.isoformat().replace("+00:00", "Z"),
            "primary_regime": self.primary_regime,
            "volatile": self.volatile,
            "features": self.features.to_dict(),
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class RegimeSuppressionDecision:
    """Auditable decision produced when a signal is blocked by regime rules."""

    strategy_id: str
    strategy_version: str
    instrument_id: str
    timeframe: str
    ts_utc: datetime
    requested_regimes: tuple[str, ...]
    disallowed_regimes: tuple[str, ...]
    active_primary_regime: str
    active_volatile: bool
    reason: str

    def __post_init__(self) -> None:
        for name, value in (
            ("strategy_id", self.strategy_id),
            ("strategy_version", self.strategy_version),
            ("instrument_id", self.instrument_id),
            ("timeframe", self.timeframe),
            ("reason", self.reason),
            ("active_primary_regime", self.active_primary_regime),
        ):
            if not value.strip():
                raise ValueError(f"{name} must be non-empty.")
        _require_utc(self.ts_utc)

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "instrument_id": self.instrument_id,
            "timeframe": self.timeframe,
            "ts_utc": self.ts_utc.isoformat().replace("+00:00", "Z"),
            "requested_regimes": list(self.requested_regimes),
            "disallowed_regimes": list(self.disallowed_regimes),
            "active_primary_regime": self.active_primary_regime,
            "active_volatile": self.active_volatile,
            "reason": self.reason,
        }
