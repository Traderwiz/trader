"""Canonical market event types for broker-agnostic data handling."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class MarketEventType(StrEnum):
    """Supported canonical market event types."""

    BAR = "BAR"
    QUOTE = "QUOTE"
    TRADE = "TRADE"
    SESSION = "SESSION"
    INSTRUMENT = "INSTRUMENT"


def _validate_utc_timestamp(ts_utc: datetime) -> None:
    """Require an aware UTC timestamp."""

    if ts_utc.tzinfo is None or ts_utc.utcoffset() != timezone.utc.utcoffset(ts_utc):
        raise ValueError("ts_utc must be timezone-aware and in UTC.")


@dataclass(frozen=True)
class MarketEvent:
    """Base class for canonical market data events."""

    instrument_id: str
    ts_utc: datetime
    event_type: MarketEventType

    def __post_init__(self) -> None:
        if not self.instrument_id.strip():
            raise ValueError("instrument_id must be non-empty.")
        _validate_utc_timestamp(self.ts_utc)


@dataclass(frozen=True)
class BarEvent(MarketEvent):
    """Canonical OHLCV bar event."""

    open: float
    high: float
    low: float
    close: float
    volume: float
    bar_size: str
    event_type: MarketEventType = field(default=MarketEventType.BAR, init=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("BarEvent high/low must bound open and close.")
        if self.volume < 0:
            raise ValueError("volume cannot be negative.")
        if not self.bar_size.strip():
            raise ValueError("bar_size must be non-empty.")


@dataclass(frozen=True)
class QuoteEvent(MarketEvent):
    """Canonical bid-ask quote event."""

    bid: float
    ask: float
    bid_size: float | None = None
    ask_size: float | None = None
    event_type: MarketEventType = field(default=MarketEventType.QUOTE, init=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.ask < self.bid:
            raise ValueError("ask must be greater than or equal to bid.")


@dataclass(frozen=True)
class TradeEvent(MarketEvent):
    """Canonical trade print event."""

    price: float
    quantity: float
    trade_id: str | None = None
    event_type: MarketEventType = field(default=MarketEventType.TRADE, init=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.price <= 0:
            raise ValueError("price must be positive.")
        if self.quantity <= 0:
            raise ValueError("quantity must be positive.")


@dataclass(frozen=True)
class SessionEvent(MarketEvent):
    """Canonical session status event."""

    session_state: str
    session_label: str
    event_type: MarketEventType = field(default=MarketEventType.SESSION, init=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.session_state.strip():
            raise ValueError("session_state must be non-empty.")
        if not self.session_label.strip():
            raise ValueError("session_label must be non-empty.")


@dataclass(frozen=True)
class InstrumentEvent(MarketEvent):
    """Canonical instrument lifecycle event."""

    action: str
    payload: dict[str, Any] = field(default_factory=dict)
    event_type: MarketEventType = field(default=MarketEventType.INSTRUMENT, init=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.action.strip():
            raise ValueError("action must be non-empty.")

