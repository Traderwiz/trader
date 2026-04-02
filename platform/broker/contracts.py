"""Translates canonical instruments into IBKR contract objects."""

from __future__ import annotations

from platform.models import Instrument


def instrument_to_ibkr_contract(instrument: Instrument):
    """Build an ib_insync contract object for the canonical instrument."""

    from ib_insync import Contract, Forex, Future, Stock

    asset_class = instrument.asset_class.upper()
    if asset_class in {"EQUITY", "STOCK"}:
        return Stock(symbol=instrument.broker_symbol, exchange=instrument.venue or "SMART", currency=instrument.currency)
    if asset_class in {"FUTURE", "FUTURES"}:
        return Future(symbol=instrument.broker_symbol, exchange=instrument.venue, currency=instrument.currency)
    if asset_class in {"FX", "FOREX"}:
        return Forex(pair=instrument.broker_symbol)
    return Contract(
        symbol=instrument.broker_symbol,
        secType=asset_class,
        exchange=instrument.venue,
        currency=instrument.currency,
    )
