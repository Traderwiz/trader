"""Unit tests for Parquet bar storage round-trips."""

from __future__ import annotations

from datetime import datetime, timezone

from platform.data.parquet_store import ParquetStore
from platform.models.market_data import BarEvent


def test_parquet_store_round_trip_preserves_values_and_utc_timestamps(tmp_path) -> None:
    store = ParquetStore(tmp_path / "var" / "data")
    bars = [
        BarEvent(
            instrument_id="MES",
            ts_utc=datetime(2025, 1, 2, 14, minute, tzinfo=timezone.utc),
            open=6000.0 + minute,
            high=6001.0 + minute,
            low=5999.5 + minute,
            close=6000.5 + minute,
            volume=100 + minute,
            bar_size="1m",
        )
        for minute in range(3)
    ]

    store.write_bars(bars)
    reloaded = store.read_bars(
        instrument_id="MES",
        start=datetime(2025, 1, 2, 14, 0, tzinfo=timezone.utc),
        end=datetime(2025, 1, 2, 14, 2, tzinfo=timezone.utc),
        bar_size="1m",
    )

    assert len(reloaded) == 3
    assert reloaded[0].close == bars[0].close
    assert reloaded[-1].ts_utc.tzinfo is not None
    assert reloaded[-1].ts_utc.utcoffset() == timezone.utc.utcoffset(reloaded[-1].ts_utc)
    assert (tmp_path / "var" / "data" / "MES" / "2025" / "01" / "20250102_1m.parquet").exists()

