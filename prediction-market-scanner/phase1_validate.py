from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import scanner
from run_scan import ThrottledSession, normalise_market


DEFAULT_SERIES = ("KXCPI", "KXECONSTATU3", "KXFEDDECISION")


def fetch_series_events(base_url: str, series_ticker: str, timeout: int) -> list[dict[str, Any]]:
    session = ThrottledSession()
    response = session.get(
        f"{base_url.rstrip('/')}/events",
        params={
            "series_ticker": series_ticker,
            "status": "open",
            "with_nested_markets": "true",
            "limit": 200,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    events = payload.get("events", [])
    if not isinstance(events, list):
        raise RuntimeError(f"Kalshi response for {series_ticker} did not contain an events list")
    return [event for event in events if isinstance(event, dict)]


def validate_series(config: dict[str, Any], series_ticker: str, retrieved_at: str) -> dict[str, Any]:
    now = scanner.parse_utc(retrieved_at)
    events = fetch_series_events(
        config["api_base_url"],
        series_ticker,
        min(int(config["request_timeout_seconds"]), 20),
    )

    rows: list[dict[str, Any]] = []
    for event in events:
        nested = event.get("markets", [])
        if not isinstance(nested, list):
            continue
        for raw_market in nested:
            if not isinstance(raw_market, dict):
                continue
            normalized = normalise_market(raw_market, event)
            close_raw = normalized.get("close_time")
            parsed_close = None
            days_to_close = None
            if close_raw:
                try:
                    parsed = scanner.parse_utc(str(close_raw))
                    parsed_close = parsed.isoformat().replace("+00:00", "Z")
                    days_to_close = round((parsed - now).total_seconds() / 86400, 3)
                except ValueError:
                    pass

            yes_bid = scanner.first_cents(normalized, "yes_bid_dollars", "yes_bid")
            yes_ask = scanner.first_cents(normalized, "yes_ask_dollars", "yes_ask")
            no_bid = scanner.first_cents(normalized, "no_bid_dollars", "no_bid")
            no_ask = scanner.first_cents(normalized, "no_ask_dollars", "no_ask")
            if yes_ask is None and no_bid is not None:
                yes_ask = 100 - no_bid
            if no_ask is None and yes_bid is not None:
                no_ask = 100 - yes_bid

            rows.append(
                {
                    "series_ticker": series_ticker,
                    "event_ticker": str(event.get("event_ticker") or event.get("ticker") or ""),
                    "event_title": str(event.get("title") or ""),
                    "available_on_brokers": bool(event.get("available_on_brokers", False)),
                    "ticker": str(normalized.get("ticker") or ""),
                    "status": str(normalized.get("status") or ""),
                    "close_time_raw": str(close_raw or ""),
                    "close_time_utc": parsed_close,
                    "days_to_close": days_to_close,
                    "volume": int(normalized.get("volume") or 0),
                    "open_interest": int(normalized.get("open_interest") or 0),
                    "yes_bid_cents": yes_bid,
                    "yes_ask_cents": yes_ask,
                    "no_bid_cents": no_bid,
                    "no_ask_cents": no_ask,
                    "yes_ask_size": normalized.get("yes_ask_size"),
                    "no_ask_size": normalized.get("no_ask_size"),
                    "market_subtitle": str(normalized.get("subtitle") or normalized.get("yes_sub_title") or ""),
                }
            )

    rows.sort(
        key=lambda row: (
            row["days_to_close"] is None,
            row["days_to_close"] if row["days_to_close"] is not None else float("inf"),
            -row["volume"],
        )
    )
    return {
        "series_ticker": series_ticker,
        "events_returned": len(events),
        "markets_returned": len(rows),
        "nearest_markets": rows[:10],
    }


def write_reports(results: list[dict[str, Any]], retrieved_at: str, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    payload = {"retrieved_at_utc": retrieved_at, "series": results}
    (output / "phase1-validation.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "# Phase 1 Targeted Series Validation",
        "",
        f"- Retrieved: `{retrieved_at}`",
        "- Purpose: verify exact series-scoped retrieval and live field normalization before broad discovery.",
        "",
    ]
    for result in results:
        lines.extend(
            [
                f"## `{result['series_ticker']}`",
                "",
                f"- Open events returned: **{result['events_returned']}**",
                f"- Nested markets returned: **{result['markets_returned']}**",
                "",
                "| Ticker | Event | Status | Broker | Close UTC | Days | Volume | OI | Yes bid/ask | No bid/ask | Depth Y/N | Contract |",
                "|---|---|---|---|---|---:|---:|---:|---|---|---|---|",
            ]
        )
        for row in result["nearest_markets"]:
            days = "n/a" if row["days_to_close"] is None else f"{row['days_to_close']:.2f}"
            lines.append(
                f"| `{row['ticker']}` | `{row['event_ticker']}` | {row['status']} | "
                f"{row['available_on_brokers']} | {row['close_time_utc'] or row['close_time_raw'] or 'n/a'} | "
                f"{days} | {row['volume']:,} | {row['open_interest']:,} | "
                f"{row['yes_bid_cents']}/{row['yes_ask_cents']} | "
                f"{row['no_bid_cents']}/{row['no_ask_cents']} | "
                f"{row['yes_ask_size']}/{row['no_ask_size']} | "
                f"{row['event_title'].replace('|', '/')} — {row['market_subtitle'].replace('|', '/')} |"
            )
        lines.append("")

    (output / "phase1-validation.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate current CPI, unemployment, and Fed series.")
    parser.add_argument("--config", type=Path, default=Path("config/scanner.yml"))
    parser.add_argument("--output", type=Path, default=Path("reports"))
    parser.add_argument("--series", nargs="*", default=list(DEFAULT_SERIES))
    args = parser.parse_args()

    config = scanner.load_config(args.config)
    retrieved_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    results = [validate_series(config, ticker, retrieved_at) for ticker in args.series]
    write_reports(results, retrieved_at, args.output)
    print(
        "Phase 1 validation complete: "
        + ", ".join(
            f"{result['series_ticker']}={result['events_returned']} event(s)/{result['markets_returned']} market(s)"
            for result in results
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
