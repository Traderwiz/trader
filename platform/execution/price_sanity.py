"""Order price and size validation against instrument metadata and quotes."""

from __future__ import annotations

from dataclasses import dataclass
from math import isclose
from typing import Callable

from platform.models import Instrument, OrderIntent, OrderSide, OrderType


@dataclass(frozen=True)
class QuoteSnapshot:
    """Minimal quote snapshot used by the price sanity gate."""

    bid: float | None
    ask: float | None
    last: float | None = None


class OrderPriceSanityValidator:
    """Rejects invalid price/size combinations before broker submission."""

    def __init__(
        self,
        *,
        quote_provider: Callable[[str], QuoteSnapshot | None],
        deviation_thresholds: dict[str, float] | None = None,
    ) -> None:
        self._quote_provider = quote_provider
        self._deviation_thresholds = {
            "EQUITY": 0.02,
            "STOCK": 0.02,
            "FUTURE": 0.01,
            "FUTURES": 0.01,
            "FX": 0.005,
            "FOREX": 0.005,
        }
        if deviation_thresholds:
            self._deviation_thresholds.update({key.upper(): value for key, value in deviation_thresholds.items()})

    def validate(self, intent: OrderIntent, instrument: Instrument) -> tuple[bool, str]:
        if intent.quantity < instrument.min_quantity:
            return False, "quantity below instrument minimum"
        if not _is_aligned(intent.quantity, instrument.quantity_increment):
            return False, "quantity is not aligned to quantity increment"
        if intent.order_type is OrderType.LIMIT:
            if intent.limit_price is None:
                return False, "limit order missing limit price"
            if not _is_aligned(intent.limit_price, instrument.price_increment):
                return False, "limit price is not aligned to tick size"
        quote = self._quote_provider(intent.instrument_id)
        if quote is None:
            return False, "no current quote available"
        reference_price = _reference_price(intent.side, quote)
        if reference_price is None or reference_price <= 0:
            return False, "quote is missing a trustworthy reference price"
        if intent.order_type is OrderType.MARKET:
            return True, "market order quote check passed"
        max_deviation = self._deviation_thresholds.get(instrument.asset_class.upper(), 0.02)
        deviation = abs(intent.limit_price - reference_price) / reference_price
        if deviation > max_deviation:
            return False, f"limit price deviates {deviation:.4f} from quote reference"
        return True, "price sanity checks passed"


def _reference_price(side: OrderSide, quote: QuoteSnapshot) -> float | None:
    if side is OrderSide.BUY:
        return quote.ask or quote.last or quote.bid
    return quote.bid or quote.last or quote.ask


def _is_aligned(value: float, increment: float) -> bool:
    scaled = value / increment
    return isclose(scaled, round(scaled), rel_tol=0.0, abs_tol=1e-9)
