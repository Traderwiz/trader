"""Unit tests for the canonical instrument catalog."""

from __future__ import annotations

from pathlib import Path

from platform.data.catalog import load_instrument_catalog


def test_catalog_loads_mes_and_eurusd_with_expected_values() -> None:
    config_path = Path(__file__).resolve().parents[2] / "config" / "instruments.yaml"
    catalog = load_instrument_catalog(config_path)

    mes = catalog.get("MES")
    eurusd = catalog.get("EURUSD")

    assert mes.multiplier == 5
    assert mes.point_value == 5
    assert mes.price_increment == 0.25
    assert mes.tick_value == 1.25
    assert 50.0 <= mes.margin_profile.intraday_initial <= 100.0
    assert mes.cost_profile.commission_per_side == 0.62

    assert eurusd.instrument_id == "EURUSD"
    assert eurusd.broker_symbol == "EUR.USD"
    assert eurusd.min_quantity == 1000
    assert eurusd.quantity_increment == 1000
    assert eurusd.price_increment == 0.0001
    assert eurusd.tick_value * eurusd.min_quantity == 0.10
    assert eurusd.cost_profile.spread_ticks_for_session("regular") == 0.25

