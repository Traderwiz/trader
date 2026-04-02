"""Ingest ES continuous daily bars from yfinance into the canonical Parquet store as MES bars."""

from __future__ import annotations

import sys
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
stdlib_platform = sys.modules.get("platform")
if stdlib_platform is not None and not hasattr(stdlib_platform, "__path__"):
    sys.modules.pop("platform", None)

import pandas as pd
import yfinance as yf

from platform.data.parquet_store import ParquetStore
from platform.models.market_data import BarEvent

UTC = timezone.utc
INSTRUMENT_ID = "MES"
BAR_SIZE = "1D"
TICKER = "ES=F"
START_DATE = date(2000, 9, 18)


def _as_utc_timestamp(ts: pd.Timestamp) -> datetime:
    if ts.tz is None:
        ts = ts.tz_localize("America/New_York")
    ts_utc = ts.tz_convert("UTC")
    return ts_utc.to_pydatetime()


def _download_history() -> pd.DataFrame:
    ticker = yf.Ticker(TICKER)
    history = ticker.history(period="max", interval="1d", auto_adjust=False)
    if history.empty:
        raise RuntimeError(f"No data returned for {TICKER}")
    return history[["Open", "High", "Low", "Close", "Volume"]].copy()



def _to_bar_events(history: pd.DataFrame) -> tuple[list[BarEvent], int]:
    bars: list[BarEvent] = []
    skipped_rows = 0
    for ts, row in history.iterrows():
        open_price = float(row["Open"])
        high_price = float(row["High"])
        low_price = float(row["Low"])
        close = row["Close"]
        if pd.isna(close) or float(close) == 0.0:
            skipped_rows += 1
            continue
        close_price = float(close)
        if high_price < max(open_price, close_price) or low_price > min(open_price, close_price):
            skipped_rows += 1
            continue
        bars.append(
            BarEvent(
                instrument_id=INSTRUMENT_ID,
                ts_utc=_as_utc_timestamp(pd.Timestamp(ts)),
                open=open_price,
                high=high_price,
                low=low_price,
                close=close_price,
                volume=float(row["Volume"]),
                bar_size=BAR_SIZE,
            )
        )
    return bars, skipped_rows


def _read_all_bars(store: ParquetStore, end_day: date) -> list[BarEvent]:
    return store.read_bars(
        instrument_id=INSTRUMENT_ID,
        start=datetime.combine(START_DATE, dtime.min, tzinfo=UTC),
        end=datetime.combine(end_day + timedelta(days=1), dtime.max, tzinfo=UTC),
        bar_size=BAR_SIZE,
    )


def _count_between(bars: list[BarEvent], start_day: date, end_day: date) -> int:
    return sum(1 for bar in bars if start_day <= bar.ts_utc.date() <= end_day)


def _print_assertion(name: str, condition: bool, detail: str) -> bool:
    status = "PASS" if condition else "FAIL"
    print(f"{status}: {name} ({detail})")
    return condition


def main() -> None:
    store = ParquetStore(PROJECT_ROOT / "var" / "data")

    history = _download_history()
    downloaded_earliest = pd.Timestamp(history.index.min())
    downloaded_latest = pd.Timestamp(history.index.max())
    print(f"Downloaded {len(history)} bars for {TICKER}")
    print(f"Earliest downloaded date: {downloaded_earliest}")
    print(f"Latest downloaded date: {downloaded_latest}")

    fetched_bars, skipped_rows = _to_bar_events(history)
    existing_bars = _read_all_bars(store, datetime.now(UTC).date())
    existing_dates = {bar.ts_utc.date() for bar in existing_bars}
    bars_to_write = [bar for bar in fetched_bars if bar.ts_utc.date() not in existing_dates]

    if bars_to_write:
        store.write_bars(bars_to_write)

    all_dates = sorted({bar.ts_utc.date() for bar in existing_bars} | {bar.ts_utc.date() for bar in fetched_bars})
    date_range = f"{all_dates[0]} -> {all_dates[-1]}" if all_dates else "n/a"
    print(f"Skipped malformed rows: {skipped_rows}")
    print("Write summary:")
    print(f"  total bars fetched: {len(fetched_bars)}")
    print(f"  total bars written: {len(bars_to_write)}")
    print(f"  date range: {date_range}")

    stored_bars = _read_all_bars(store, datetime.now(UTC).date())
    if not stored_bars:
        raise AssertionError("No bars found in store after ingestion.")

    earliest = stored_bars[0].ts_utc.date()
    latest = stored_bars[-1].ts_utc.date()
    bars_2008 = _count_between(stored_bars, date(2008, 1, 1), date(2008, 12, 31))
    bars_2020_covid = _count_between(stored_bars, date(2020, 3, 1), date(2020, 4, 30))
    bars_2022 = _count_between(stored_bars, date(2022, 1, 1), date(2022, 12, 31))

    print("Verification:")
    print(f"  total bars in store: {len(stored_bars)}")
    print(f"  earliest date: {earliest}")
    print(f"  latest date: {latest}")
    print(f"  bars in 2008: {bars_2008}")
    print(f"  bars in 2020-03-01 through 2020-04-30: {bars_2020_covid}")
    print(f"  bars in 2022: {bars_2022}")

    checks = [
        _print_assertion("at least 6000 bars exist", len(stored_bars) >= 6000, f"found {len(stored_bars)}"),
        _print_assertion("earliest bar is on or before 2001-01-01", earliest <= date(2001, 1, 1), f"found {earliest}"),
        _print_assertion("2008 has at least 200 bars", bars_2008 >= 200, f"found {bars_2008}"),
        _print_assertion("2020 March-April has at least 30 bars", bars_2020_covid >= 30, f"found {bars_2020_covid}"),
        _print_assertion("2022 has at least 200 bars", bars_2022 >= 200, f"found {bars_2022}"),
    ]

    if not all(checks):
        raise AssertionError("One or more verification checks failed.")


if __name__ == "__main__":
    main()
