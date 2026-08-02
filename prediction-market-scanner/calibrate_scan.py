from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any

import scanner
from run_scan import (
    ThrottledSession,
    calibrated_text_matches,
    fetch_open_event_markets,
)


def market_text(market: dict[str, Any]) -> str:
    return " ".join(
        str(market.get(k, ""))
        for k in (
            "ticker",
            "event_ticker",
            "title",
            "subtitle",
            "yes_sub_title",
            "no_sub_title",
            "rules_primary",
            "category",
            "series_ticker",
        )
    ).lower()


def _price_fields(market: dict[str, Any]) -> dict[str, int | None]:
    yes_bid = scanner.first_cents(market, "yes_bid_dollars", "yes_bid")
    yes_ask = scanner.first_cents(market, "yes_ask_dollars", "yes_ask")
    no_bid = scanner.first_cents(market, "no_bid_dollars", "no_bid")
    no_ask = scanner.first_cents(market, "no_ask_dollars", "no_ask")
    if yes_ask is None and no_bid is not None:
        yes_ask = 100 - no_bid
    if no_ask is None and yes_bid is not None:
        no_ask = 100 - yes_bid
    return {
        "yes_bid": yes_bid,
        "yes_ask": yes_ask,
        "no_bid": no_bid,
        "no_ask": no_ask,
    }


def _diagnostic_row(
    market: dict[str, Any],
    reason: str,
    close_raw: Any,
    close_utc: str,
    days: float | None,
) -> dict[str, Any]:
    prices = _price_fields(market)
    yes_bid = prices["yes_bid"]
    yes_ask = prices["yes_ask"]
    no_bid = prices["no_bid"]
    no_ask = prices["no_ask"]
    return {
        "ticker": str(market.get("ticker", "")),
        "event_ticker": str(market.get("event_ticker", "")),
        "series_ticker": str(market.get("series_ticker", "")),
        "title": str(market.get("title", "")),
        "subtitle": str(market.get("subtitle", "")),
        "status": str(market.get("status", "")),
        "reason": reason,
        "close_raw": "" if close_raw is None else str(close_raw),
        "close_utc": close_utc,
        "days": days,
        "volume": int(market.get("volume") or 0),
        "open_interest": int(market.get("open_interest") or 0),
        "yes_bid": yes_bid,
        "yes_ask": yes_ask,
        "no_bid": no_bid,
        "no_ask": no_ask,
        "yes_spread": yes_ask - yes_bid if yes_ask is not None and yes_bid is not None else None,
        "no_spread": no_ask - no_bid if no_ask is not None and no_bid is not None else None,
        "yes_depth": int(market.get("yes_ask_size") or 0) or None,
        "no_depth": int(market.get("no_ask_size") or 0) or None,
    }


def diagnose(markets: list[dict[str, Any]], retrieved_at: str, config: dict[str, Any]) -> tuple[Counter, list[dict[str, Any]]]:
    counts: Counter = Counter()
    diagnostics: list[dict[str, Any]] = []
    now = scanner.parse_utc(retrieved_at)
    filters = config["filters"]

    for market in markets:
        counts["markets_seen"] += 1
        if not calibrated_text_matches(market, config):
            counts["rejected_keyword_filter"] += 1
            diagnostics.append(_diagnostic_row(market, "keyword_filter", market.get("close_time"), "", None))
            continue
        counts["passed_keyword_filter"] += 1

        close_raw = market.get("close_time")
        if not close_raw:
            counts["rejected_missing_close_time"] += 1
            diagnostics.append(_diagnostic_row(market, "missing_close_time", close_raw, "", None))
            continue
        try:
            close_time = scanner.parse_utc(str(close_raw))
        except ValueError:
            counts["rejected_invalid_close_time"] += 1
            diagnostics.append(_diagnostic_row(market, "invalid_close_time", close_raw, "", None))
            continue

        days = (close_time - now).total_seconds() / 86400
        close_utc = close_time.isoformat().replace("+00:00", "Z")
        if days <= 0:
            counts["rejected_already_closed"] += 1
            diagnostics.append(_diagnostic_row(market, "already_closed", close_raw, close_utc, days))
            continue
        if days > filters["maximum_days_to_close"]:
            counts["rejected_too_far_out"] += 1
            diagnostics.append(_diagnostic_row(market, "too_far_out", close_raw, close_utc, days))
            continue
        counts["passed_date_filter"] += 1

        prices = _price_fields(market)
        yes_bid = prices["yes_bid"]
        yes_ask = prices["yes_ask"]
        no_bid = prices["no_bid"]
        no_ask = prices["no_ask"]

        if yes_bid is None and no_bid is None:
            counts["missing_both_bids"] += 1
        if yes_ask is None and no_ask is None:
            counts["missing_both_asks"] += 1

        volume = int(market.get("volume") or 0)
        if volume < filters["minimum_volume_contracts"]:
            counts["rejected_low_volume"] += 1
            diagnostics.append(_diagnostic_row(market, "low_volume", close_raw, close_utc, days))
            continue
        counts["passed_volume_filter"] += 1

        yes_spread = yes_ask - yes_bid if yes_ask is not None and yes_bid is not None else None
        no_spread = no_ask - no_bid if no_ask is not None and no_bid is not None else None
        if yes_spread is None and no_spread is None:
            counts["missing_spread"] += 1
            diagnostics.append(_diagnostic_row(market, "missing_spread", close_raw, close_utc, days))
            continue
        if min(x for x in (yes_spread, no_spread) if x is not None) > filters["maximum_spread_cents"]:
            counts["rejected_wide_spread"] += 1
            diagnostics.append(_diagnostic_row(market, "wide_spread", close_raw, close_utc, days))
            continue
        counts["passed_spread_filter"] += 1

        yes_depth = int(market.get("yes_ask_size") or 0) or None
        no_depth = int(market.get("no_ask_size") or 0) or None
        if yes_depth is None and no_depth is None:
            counts["missing_ask_depth_fields"] += 1
            diagnostics.append(_diagnostic_row(market, "missing_ask_depth", close_raw, close_utc, days))
            continue

        counts["passed_preliminary_diagnostics"] += 1
        diagnostics.append(_diagnostic_row(market, "passed_preliminary", close_raw, close_utc, days))

    diagnostics.sort(
        key=lambda row: (
            row["days"] is None,
            float("inf") if row["days"] is None else row["days"],
            -row["volume"],
        )
    )
    return counts, diagnostics[:25]


def write_diagnostics(counts: Counter, diagnostics: list[dict[str, Any]], output: Path, retrieved_at: str) -> None:
    output.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Scanner Calibration Report",
        "",
        f"- Retrieved: `{retrieved_at}`",
        f"- Markets seen: **{counts['markets_seen']:,}**",
        "",
        "## Rejection and field diagnostics",
        "",
        "| Diagnostic | Count |",
        "|---|---:|",
    ]
    for key, value in sorted(counts.items()):
        lines.append(f"| `{key}` | {value:,} |")

    lines.extend(
        [
            "",
            "## Nearest-closing diagnostic sample",
            "",
            "This table includes rejected markets so date and field mappings can be inspected directly.",
            "",
            "| Rank | Reason | Ticker | Event | Series | Status | Raw close time | Parsed UTC | Days | Volume/OI | Yes bid/ask | No bid/ask | Depth Y/N | Contract |",
            "|---:|---|---|---|---|---|---|---|---:|---|---|---|---|---|",
        ]
    )
    for i, row in enumerate(diagnostics, 1):
        days_text = "n/a" if row["days"] is None else f"{row['days']:.2f}"
        lines.append(
            f"| {i} | `{row['reason']}` | `{row['ticker']}` | `{row['event_ticker']}` | "
            f"`{row['series_ticker']}` | `{row['status']}` | `{row['close_raw']}` | `{row['close_utc']}` | "
            f"{days_text} | {row['volume']:,}/{row['open_interest']:,} | "
            f"{row['yes_bid']}/{row['yes_ask']} | {row['no_bid']}/{row['no_ask']} | "
            f"{row['yes_depth']}/{row['no_depth']} | "
            f"{row['title'].replace('|', '/')} — {row['subtitle'].replace('|', '/')} |"
        )
    (output / "calibration.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("config/scanner.yml"))
    parser.add_argument("--output", type=Path, default=Path("reports"))
    args = parser.parse_args()

    config = scanner.load_config(args.config)
    scanner.requests.Session = ThrottledSession
    scanner.fetch_open_markets = fetch_open_event_markets
    scanner.text_matches = calibrated_text_matches

    markets, retrieved_at = fetch_open_event_markets(config)
    counts, diagnostics = diagnose(markets, retrieved_at, config)
    candidates = scanner.build_candidates(markets, retrieved_at, config)
    scanner.write_reports(candidates, len(markets), retrieved_at, args.output, config)
    write_diagnostics(counts, diagnostics, args.output, retrieved_at)
    print(f"Calibration complete: {len(markets)} markets, {len(candidates)} strict candidates.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
