"""Unit tests for transaction cost model behavior."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from platform.backtest.costs import default_cost_model_bundle
from platform.data.catalog import load_instrument_catalog
from platform.models.market_data import BarEvent
from platform.models.orders import SignalSide


def test_default_cost_bundle_applies_non_zero_slippage_to_every_fill() -> None:
    catalog = load_instrument_catalog(Path(__file__).resolve().parents[2] / "config" / "instruments.yaml")
    instrument = catalog.get("MES")
    bar = BarEvent(
        instrument_id="MES",
        ts_utc=datetime(2025, 1, 2, 14, 30, tzinfo=timezone.utc),
        open=6000.0,
        high=6001.0,
        low=5999.0,
        close=6000.0,
        volume=1_000.0,
        bar_size="1m",
    )

    fill = default_cost_model_bundle().estimate_fill(
        instrument=instrument,
        bar=bar,
        side=SignalSide.LONG,
        quantity=1,
    )

    assert fill.fill_price > bar.close
    assert fill.commission_paid == 0.62
    assert fill.slippage_paid >= instrument.tick_value

