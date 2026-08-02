from decimal import Decimal

from run_scan import is_tradeable_nested_market, normalise_market
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


def test_nested_market_uses_response_status_enum() -> None:
    assert is_tradeable_nested_market({"status": "active"}) is True
    assert is_tradeable_nested_market({"status": "open"}) is False
    assert is_tradeable_nested_market({"status": "inactive"}) is False
    assert is_tradeable_nested_market({}) is False


def test_normalise_market_derives_no_side_depth_from_yes_book() -> None:
    market = {
        "ticker": "TEST-MARKET",
        "status": "active",
        "yes_bid_size_fp": "17.00",
        "yes_ask_size_fp": "23.00",
        "volume_fp": "1200.00",
        "volume_24h_fp": "125.00",
        "open_interest_fp": "450.00",
    }
    event = {
        "title": "Test event",
        "sub_title": "Test subtitle",
        "category": "Economics",
        "series_ticker": "KXTEST",
        "available_on_brokers": True,
    }

    result = normalise_market(market, event)

    assert result["yes_bid_size"] == 17
    assert result["yes_ask_size"] == 23
    assert result["no_ask_size"] == 17
    assert result["no_bid_size"] == 23
    assert result["volume"] == 1200
    assert result["open_interest"] == 450
