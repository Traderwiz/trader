"""Pluggable transaction cost and margin models for backtests."""

from __future__ import annotations

from dataclasses import dataclass

from platform.models.instruments import Instrument
from platform.models.market_data import BarEvent
from platform.models.orders import SignalSide


@dataclass(frozen=True)
class FillCostBreakdown:
    """Detailed fill costs for one simulated execution."""

    fill_price: float
    commission_paid: float
    spread_paid: float
    slippage_paid: float

    @property
    def total_friction(self) -> float:
        """Return the total transaction friction for the fill."""

        return self.commission_paid + self.spread_paid + self.slippage_paid


class CommissionModel:
    """Per-contract commission model."""

    def commission(self, instrument: Instrument, quantity: float) -> float:
        """Return commission paid for one side of a fill."""

        return instrument.cost_profile.commission_per_side * quantity


class SpreadModel:
    """Session-aware fixed half-spread model measured in ticks."""

    def half_spread_ticks(self, instrument: Instrument, session: str | None = None) -> float:
        """Return the adverse half-spread in ticks."""

        return instrument.cost_profile.spread_ticks_for_session(session)


class SlippageModel:
    """Mandatory slippage model with a minimum one-tick floor."""

    def slippage_ticks(
        self,
        instrument: Instrument,
        quantity: float,
        bar_volume: float,
    ) -> float:
        """Return slippage in ticks for a marketable fill."""

        floor = max(1.0, instrument.cost_profile.minimum_slippage_ticks)
        impact = instrument.cost_profile.additional_impact_per_unit * quantity
        if bar_volume > 0:
            impact += quantity / bar_volume
        return max(floor, floor + impact)


class MarginModel:
    """Intraday and overnight margin requirement model."""

    def requirement(self, instrument: Instrument, session: str = "intraday") -> float:
        """Return initial margin required for one position unit."""

        if session == "overnight":
            return instrument.margin_profile.overnight_initial
        return instrument.margin_profile.intraday_initial


@dataclass(frozen=True)
class CostModelBundle:
    """Container for pluggable transaction cost and margin models."""

    commission_model: CommissionModel
    spread_model: SpreadModel
    slippage_model: SlippageModel
    margin_model: MarginModel

    def estimate_fill(
        self,
        instrument: Instrument,
        bar: BarEvent,
        side: SignalSide,
        quantity: float,
        session: str = "default",
        reference_price: float | None = None,
    ) -> FillCostBreakdown:
        """Estimate the fill price and costs for a simulated marketable fill."""

        if side is SignalSide.FLAT:
            raise ValueError("FLAT is not a valid execution side.")

        base_price = float(reference_price) if reference_price is not None else bar.close
        if base_price <= 0:
            raise ValueError("reference price must be positive.")

        spread_ticks = self.spread_model.half_spread_ticks(instrument, session)
        slippage_ticks = self.slippage_model.slippage_ticks(instrument, quantity=quantity, bar_volume=bar.volume)
        adverse_ticks = spread_ticks + slippage_ticks
        adverse_price = adverse_ticks * instrument.price_increment
        signed_price = base_price + adverse_price if side is SignalSide.LONG else base_price - adverse_price

        return FillCostBreakdown(
            fill_price=signed_price,
            commission_paid=self.commission_model.commission(instrument, quantity),
            spread_paid=spread_ticks * instrument.tick_value * quantity,
            slippage_paid=slippage_ticks * instrument.tick_value * quantity,
        )


def default_cost_model_bundle() -> CostModelBundle:
    """Return the default Phase 2 cost model bundle."""

    return CostModelBundle(
        commission_model=CommissionModel(),
        spread_model=SpreadModel(),
        slippage_model=SlippageModel(),
        margin_model=MarginModel(),
    )
