from decimal import Decimal

from scanner import dollars_to_cents, estimate_fee, first_cents


def test_dollars_to_cents_rounding() -> None:
    assert dollars_to_cents("0.57") == 57
    assert dollars_to_cents(0.575) == 58
    assert dollars_to_cents(None) is None


def test_first_cents_prefers_dollar_field() -> None:
    market = {"yes_ask_dollars": "0.61", "yes_ask": 60}
    assert first_cents(market, "yes_ask_dollars", "yes_ask") == 61


def test_fee_has_minimum() -> None:
    config = {"percent_of_contract_cost": 0.035, "minimum_fee_usd": 0.01}
    assert estimate_fee(Decimal("0.10"), config) == Decimal("0.01")
    assert estimate_fee(Decimal("5.00"), config) == Decimal("0.18")
