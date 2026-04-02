"""Parquet-backed historical bar storage partitioned by instrument and date."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from platform.models.market_data import BarEvent


class ParquetStore:
    """Store and retrieve canonical bar events in Parquet files."""

    def __init__(self, root_path: str | Path = "var/data") -> None:
        self.root_path = Path(root_path).resolve()

    def write_bars(self, bars: list[BarEvent]) -> None:
        """Write a batch of bar events into partitioned Parquet files."""

        if not bars:
            return

        grouped: dict[tuple[str, int, int, str, str], list[BarEvent]] = defaultdict(list)
        for bar in bars:
            grouped[
                (
                    bar.instrument_id,
                    bar.ts_utc.year,
                    bar.ts_utc.month,
                    bar.ts_utc.strftime("%Y%m%d"),
                    bar.bar_size,
                )
            ].append(bar)

        for (instrument_id, year, month, trading_day, bar_size), batch in grouped.items():
            target_dir = self.root_path / instrument_id / f"{year:04d}" / f"{month:02d}"
            target_dir.mkdir(parents=True, exist_ok=True)
            filename = f"{trading_day}_{_sanitize_bar_size(bar_size)}.parquet"
            target_path = target_dir / filename
            new_table = _bars_to_table(sorted(batch, key=lambda item: item.ts_utc))

            if target_path.exists():
                existing_table = pq.read_table(target_path)
                combined = pa.concat_tables([existing_table, new_table])
                combined = combined.sort_by([("ts_utc", "ascending")])
                pq.write_table(combined, target_path)
            else:
                pq.write_table(new_table, target_path)

    def read_bars(
        self,
        instrument_id: str,
        start: datetime,
        end: datetime,
        bar_size: str,
    ) -> list[BarEvent]:
        """Read canonical bars for one instrument and bar size across a UTC date range."""

        _validate_utc(start)
        _validate_utc(end)
        if end < start:
            raise ValueError("end must be greater than or equal to start.")

        instrument_root = self.root_path / instrument_id
        if not instrument_root.exists():
            return []

        results: list[BarEvent] = []
        for file_path in sorted(instrument_root.rglob(f"*_{_sanitize_bar_size(bar_size)}.parquet")):
            table = pq.read_table(file_path)
            filtered = _filter_table(table, instrument_id=instrument_id, start=start, end=end, bar_size=bar_size)
            results.extend(_table_to_bars(filtered))

        return sorted(results, key=lambda bar: bar.ts_utc)


def _bars_to_table(bars: list[BarEvent]) -> pa.Table:
    """Convert canonical bars into a Parquet table."""

    return pa.table(
        {
            "instrument_id": pa.array([bar.instrument_id for bar in bars], type=pa.string()),
            "ts_utc": pa.array([bar.ts_utc for bar in bars], type=pa.timestamp("us", tz="UTC")),
            "event_type": pa.array([bar.event_type.value for bar in bars], type=pa.string()),
            "open": pa.array([bar.open for bar in bars], type=pa.float64()),
            "high": pa.array([bar.high for bar in bars], type=pa.float64()),
            "low": pa.array([bar.low for bar in bars], type=pa.float64()),
            "close": pa.array([bar.close for bar in bars], type=pa.float64()),
            "volume": pa.array([bar.volume for bar in bars], type=pa.float64()),
            "bar_size": pa.array([bar.bar_size for bar in bars], type=pa.string()),
        },
    )


def _table_to_bars(table: pa.Table) -> list[BarEvent]:
    """Convert a filtered Parquet table back into canonical bars."""

    if table.num_rows == 0:
        return []

    instrument_ids = table.column("instrument_id").to_pylist()
    timestamps_us = table.column("ts_utc").cast(pa.int64()).to_pylist()
    opens = table.column("open").to_pylist()
    highs = table.column("high").to_pylist()
    lows = table.column("low").to_pylist()
    closes = table.column("close").to_pylist()
    volumes = table.column("volume").to_pylist()
    bar_sizes = table.column("bar_size").to_pylist()

    return [
        BarEvent(
            instrument_id=str(instrument_id),
            ts_utc=_coerce_utc_timestamp(int(timestamp_us)),
            open=float(open_price),
            high=float(high_price),
            low=float(low_price),
            close=float(close_price),
            volume=float(volume),
            bar_size=str(bar_size),
        )
        for instrument_id, timestamp_us, open_price, high_price, low_price, close_price, volume, bar_size in zip(
            instrument_ids,
            timestamps_us,
            opens,
            highs,
            lows,
            closes,
            volumes,
            bar_sizes,
            strict=True,
        )
    ]


def _filter_table(
    table: pa.Table,
    *,
    instrument_id: str,
    start: datetime,
    end: datetime,
    bar_size: str,
) -> pa.Table:
    """Apply instrument, timestamp, and bar-size filters to a Parquet table."""

    predicate = pc.and_(
        pc.equal(table["instrument_id"], instrument_id),
        pc.and_(
            pc.greater_equal(table["ts_utc"], pa.scalar(start, type=pa.timestamp("us", tz="UTC"))),
            pc.and_(
                pc.less_equal(table["ts_utc"], pa.scalar(end, type=pa.timestamp("us", tz="UTC"))),
                pc.equal(table["bar_size"], bar_size),
            ),
        ),
    )
    return table.filter(predicate)


def _sanitize_bar_size(bar_size: str) -> str:
    """Make a bar-size identifier filesystem-safe."""

    return bar_size.replace("/", "_").replace(":", "_")


def _coerce_utc_timestamp(timestamp_us: int) -> datetime:
    """Convert a UTC microsecond timestamp into an aware UTC datetime."""

    return datetime.fromtimestamp(timestamp_us / 1_000_000, tz=timezone.utc)


def _validate_utc(ts_utc: datetime) -> None:
    """Require an aware UTC timestamp."""

    if ts_utc.tzinfo is None or ts_utc.utcoffset() != timezone.utc.utcoffset(ts_utc):
        raise ValueError("Timestamps must be timezone-aware and in UTC.")

