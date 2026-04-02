"""Canonical strategy and execution intent models for the runtime."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class SignalSide(StrEnum):
    """Allowed directional strategy intents."""

    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"


class OrderSide(StrEnum):
    """Canonical order submission directions."""

    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    """Canonical order types supported in Phase 4."""

    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderIntentStatus(StrEnum):
    """Lifecycle states for durable order intents."""

    CREATED = "CREATED"
    REJECTED = "REJECTED"
    SUBMITTED = "SUBMITTED"
    CANCELLED = "CANCELLED"
    FILLED = "FILLED"


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
        _validate_utc_timestamp("signal_ts", self.signal_ts)


@dataclass(frozen=True)
class OrderIntent:
    """A sized order request that must pass the safety stack before broker submission."""

    intent_id: str
    signal_intent: SignalIntent
    instrument_id: str
    side: OrderSide
    quantity: float
    order_type: OrderType
    limit_price: float | None
    created_at: datetime
    submitted_at: datetime | None = None
    status: OrderIntentStatus = OrderIntentStatus.CREATED
    reduce_only: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.intent_id.strip():
            raise ValueError("intent_id must be non-empty.")
        if self.instrument_id != self.signal_intent.instrument_id:
            raise ValueError("instrument_id must match signal_intent.instrument_id.")
        if self.quantity <= 0:
            raise ValueError("quantity must be positive.")
        _validate_utc_timestamp("created_at", self.created_at)
        if self.submitted_at is not None:
            _validate_utc_timestamp("submitted_at", self.submitted_at)
        if self.order_type is OrderType.LIMIT and self.limit_price is None:
            raise ValueError("limit_price is required for LIMIT orders.")
        if self.order_type is OrderType.MARKET and self.limit_price is not None:
            raise ValueError("limit_price must be None for MARKET orders.")
        if self.limit_price is not None and self.limit_price <= 0:
            raise ValueError("limit_price must be positive when provided.")

    @classmethod
    def create(
        cls,
        *,
        signal_intent: SignalIntent,
        side: OrderSide,
        quantity: float,
        order_type: OrderType,
        limit_price: float | None,
        created_at: datetime,
        reduce_only: bool = False,
        metadata: dict[str, Any] | None = None,
        bucket_seconds: int = 60,
    ) -> "OrderIntent":
        """Build an order intent with the deterministic Phase 4 intent key."""

        return cls(
            intent_id=build_intent_id(signal_intent=signal_intent, side=side, bucket_seconds=bucket_seconds),
            signal_intent=signal_intent,
            instrument_id=signal_intent.instrument_id,
            side=side,
            quantity=quantity,
            order_type=order_type,
            limit_price=limit_price,
            created_at=created_at,
            reduce_only=reduce_only,
            metadata=dict(metadata or {}),
        )


def build_intent_id(
    *,
    signal_intent: SignalIntent,
    side: OrderSide,
    bucket_seconds: int = 60,
) -> str:
    """Create the deterministic idempotency key required by the spec."""

    if bucket_seconds <= 0:
        raise ValueError("bucket_seconds must be positive.")
    epoch_seconds = int(signal_intent.signal_ts.timestamp())
    bucket = epoch_seconds - (epoch_seconds % bucket_seconds)
    raw_key = "|".join(
        (
            signal_intent.strategy_id,
            signal_intent.strategy_version,
            signal_intent.instrument_id,
            side.value,
            str(bucket),
        )
    )
    digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    return f"intent-{digest[:24]}"


def _validate_utc_timestamp(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValueError(f"{name} must be timezone-aware and in UTC.")
