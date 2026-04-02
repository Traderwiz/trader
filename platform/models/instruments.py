"""Canonical instrument models used across research, backtest, and live flows."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MarginProfile:
    """Margin schedules for an instrument."""

    intraday_initial: float
    intraday_maintenance: float
    overnight_initial: float
    overnight_maintenance: float

    def __post_init__(self) -> None:
        for name, value in (
            ("intraday_initial", self.intraday_initial),
            ("intraday_maintenance", self.intraday_maintenance),
            ("overnight_initial", self.overnight_initial),
            ("overnight_maintenance", self.overnight_maintenance),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be positive.")


@dataclass(frozen=True)
class CostProfile:
    """Per-instrument transaction cost configuration."""

    commission_per_side: float
    spread_half_ticks: dict[str, float] = field(default_factory=dict)
    minimum_slippage_ticks: float = 1.0
    additional_impact_per_unit: float = 0.0

    def __post_init__(self) -> None:
        if self.commission_per_side < 0:
            raise ValueError("commission_per_side cannot be negative.")
        if self.minimum_slippage_ticks < 1.0:
            raise ValueError("minimum_slippage_ticks must be at least one tick.")
        if self.additional_impact_per_unit < 0:
            raise ValueError("additional_impact_per_unit cannot be negative.")
        for session, ticks in self.spread_half_ticks.items():
            if ticks < 0:
                raise ValueError(f"spread_half_ticks for session '{session}' cannot be negative.")

    def spread_ticks_for_session(self, session: str | None = None) -> float:
        """Return the configured half-spread in ticks for a session."""

        if session and session in self.spread_half_ticks:
            return self.spread_half_ticks[session]
        return self.spread_half_ticks.get("default", 0.0)


@dataclass(frozen=True)
class MarketDataProfile:
    """Market data defaults and symbol mapping metadata."""

    default_bar_size: str
    timezone: str = "UTC"
    history_source: str | None = None

    def __post_init__(self) -> None:
        if not self.default_bar_size.strip():
            raise ValueError("default_bar_size must be non-empty.")
        if not self.timezone.strip():
            raise ValueError("timezone must be non-empty.")


@dataclass(frozen=True)
class Instrument:
    """Canonical instrument metadata required by the architecture spec."""

    instrument_id: str
    broker_symbol: str
    asset_class: str
    venue: str
    currency: str
    multiplier: float
    point_value: float
    price_increment: float
    quantity_increment: float
    min_quantity: float
    session_calendar: str
    margin_profile: MarginProfile
    cost_profile: CostProfile
    market_data_profile: MarketDataProfile

    def __post_init__(self) -> None:
        for name, value in (
            ("instrument_id", self.instrument_id),
            ("broker_symbol", self.broker_symbol),
            ("asset_class", self.asset_class),
            ("venue", self.venue),
            ("currency", self.currency),
            ("session_calendar", self.session_calendar),
        ):
            if not value.strip():
                raise ValueError(f"{name} must be non-empty.")

        for name, value in (
            ("multiplier", self.multiplier),
            ("point_value", self.point_value),
            ("price_increment", self.price_increment),
            ("quantity_increment", self.quantity_increment),
            ("min_quantity", self.min_quantity),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be positive.")

    @property
    def tick_value(self) -> float:
        """Return the monetary value of one tick."""

        return self.point_value * self.price_increment

