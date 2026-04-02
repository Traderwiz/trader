"""Canonical broker adapter interfaces and normalized broker-side models."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone

from platform.models import OrderIntent, OrderSide, OrderType

OrderId = str


@dataclass(frozen=True)
class AccountSummary:
    """Normalized account summary values used by reconciliation and limits."""

    cash: float
    net_liquidation_value: float
    buying_power: float


@dataclass(frozen=True)
class BrokerPosition:
    """A canonical broker position snapshot."""

    instrument_id: str
    quantity: float
    average_price: float
    market_price: float | None = None

    def __post_init__(self) -> None:
        if not self.instrument_id.strip():
            raise ValueError("instrument_id must be non-empty.")


@dataclass(frozen=True)
class BrokerOrder:
    """A canonical broker order snapshot."""

    order_id: OrderId
    instrument_id: str
    side: OrderSide
    quantity: float
    order_type: OrderType
    limit_price: float | None
    status: str
    intent_id: str | None = None
    reduce_only: bool = False
    submitted_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.order_id.strip():
            raise ValueError("order_id must be non-empty.")
        if not self.instrument_id.strip():
            raise ValueError("instrument_id must be non-empty.")
        if self.quantity <= 0:
            raise ValueError("quantity must be positive.")
        if not self.status.strip():
            raise ValueError("status must be non-empty.")
        if self.submitted_at is not None and (
            self.submitted_at.tzinfo is None
            or self.submitted_at.utcoffset() != timezone.utc.utcoffset(self.submitted_at)
        ):
            raise ValueError("submitted_at must be timezone-aware and in UTC.")


@dataclass(frozen=True)
class BrokerExecution:
    """A canonical fill/execution event emitted by the broker adapter."""

    execution_id: str
    order_id: OrderId
    instrument_id: str
    side: OrderSide
    quantity: float
    price: float
    ts_utc: datetime
    intent_id: str | None = None

    def __post_init__(self) -> None:
        if not self.execution_id.strip():
            raise ValueError("execution_id must be non-empty.")
        if not self.order_id.strip():
            raise ValueError("order_id must be non-empty.")
        if not self.instrument_id.strip():
            raise ValueError("instrument_id must be non-empty.")
        if self.quantity <= 0:
            raise ValueError("quantity must be positive.")
        if self.price <= 0:
            raise ValueError("price must be positive.")
        if self.ts_utc.tzinfo is None or self.ts_utc.utcoffset() != timezone.utc.utcoffset(self.ts_utc):
            raise ValueError("ts_utc must be timezone-aware and in UTC.")


class BrokerAdapter(ABC):
    """Abstract transport boundary between runtime logic and broker-specific APIs."""

    @abstractmethod
    def connect(self) -> None:
        """Establish the broker transport connection."""

    @abstractmethod
    def disconnect(self) -> None:
        """Close the broker transport connection."""

    @abstractmethod
    def is_connected(self) -> bool:
        """Return whether the broker transport is currently healthy."""

    @abstractmethod
    def get_account_summary(self) -> AccountSummary:
        """Return cash, NLV, and buying power from the broker."""

    @abstractmethod
    def get_positions(self) -> list[BrokerPosition]:
        """Return current broker positions."""

    @abstractmethod
    def get_open_orders(self) -> list[BrokerOrder]:
        """Return open broker orders."""

    @abstractmethod
    def get_executions(self) -> list[BrokerExecution]:
        """Return recent broker executions."""

    @abstractmethod
    def submit_order(self, intent: OrderIntent) -> OrderId:
        """Submit one canonical order intent to the broker."""

    @abstractmethod
    def cancel_order(self, order_id: OrderId) -> None:
        """Cancel one open broker order."""

    @abstractmethod
    def flatten_all(self) -> None:
        """Cancel all open orders and close all positions."""
