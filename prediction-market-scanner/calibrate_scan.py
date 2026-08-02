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


def diagnose(markets: list[dict[str, Any]], retrieved_at: str, config: dict[str, Any]) -> tuple[Counter, list[dict[str, Any]]]:
    counts: Counter = Counter()
    fallback: list[dict[str, Any]] = []
    now = scanner.parse_utc(retrieved_at)
    filters = config["filters"]

    for market in markets:
        counts["markets_seen"] += 1
        if not calibrated_text_matches(market, config):
            counts["rejected_keyword_filter"] += 1
            continue
        counts["passed_keyword_filter"] += 1

        close_raw = market.get("close_time")
        if not close_raw:
            counts["rejected_missing_close_time"] += 1
            continue
        try:
            close_time = scanner.parse_utc(str(close_raw))
        except ValueError:
            counts["rejected_invalid_close_time"] += 1
            continue
        days = (close_time - now).total_seconds() / 86400
        if days <= 0:
            counts["rejected_already_closed"] += 1
            continue
        if days > filters["maximum_days_to_close"]:
            counts["rejected_too_far_out"] += 1
            continue
        counts["passed_date_filter"] += 1

        yes_bid = scanner.first_cents(market, "yes_bid_dollars", "yes_bid")
        yes_ask = scanner.first_cents(market, "yes_ask_dollars", "yes_ask")
        no_bid = scanner.first_cents(market, "no_bid_dollars", "no_bid")
        no_ask = scanner.first_cents(market, "no_ask_dollars", "no_ask")
        if yes_ask is None and no_bid is not None:
            yes_ask = 100 - no_bid
        if no_ask is None and yes_bid is not None:
            no_ask = 100 - yes_bid

        if yes_bid is None and no_bid is None:
            counts["missing_both_bids"] += 1
        if yes_ask is None and no_ask is None:
            counts["missing_both_asks"] += 1

        volume = int(market.get("volume") or 0)
        if volume < filters["minimum_volume_contracts"]:
            counts["rejected_low_volume"] += 1
        else:
            counts["passed_volume_filter"] += 1

        yes_spread = yes_ask - yes_bid if yes_ask is not None and yes_bid is not None else None
        no_spread = no_ask - no_bid if no_ask is not None and no_bid is not None else None
        if yes_spread is None and no_spread is None:
            counts["missing_spread"] += 1
        elif min(x for x in (yes_spread, no_spread) if x is not None) > filters["maximum_spread_cents"]:
            counts["rejected_wide_spread"] += 1
        else:
            counts["passed_spread_filter"] += 1

        yes_depth = int(market.get("yes_ask_size") or 0) or None
        no_depth = int(market.get("no_ask_size") or 0) or None
        if yes_depth is None and no_depth is None:
            counts["missing_ask_depth_fields"] += 1

        fallback.append(
            {
                "ticker": str(market.get("ticker", "")),
                "title": str(market.get("title", "")),
                "subtitle": str(market.get("subtitle", "")),
                "volume": volume,
                "days": round(days, 2),
                "yes_bid": yes_bid,
                "yes_ask": yes_ask,
                "no_bid": no_bid,
                "no_ask": no_ask,
                "yes_spread": yes_spread,
                "no_spread": no_spread,
                "yes_depth": yes_depth,
                "no_depth": no_depth,
            }
        )

    fallback.sort(key=lambda x: (-x["volume"], x["days"]))
    return counts, fallback[:25]


def write_diagnostics(counts: Counter, fallback: list[dict[str, Any]], output: Path, retrieved_at: str) -> None:
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
            "## Top relevant markets before strict candidate filtering",
            "",
            "| Rank | Ticker | Volume | Days | Yes bid/ask | No bid/ask | Spread Y/N | Depth Y/N | Contract |",
            "|---:|---|---:|---:|---|---|---|---|---|",
        ]
    )
    for i, row in enumerate(fallback, 1):
        lines.append(
            f"| {i} | `{row['ticker']}` | {row['volume']:,} | {row['days']:.1f} | "
            f"{row['yes_bid']}/{row['yes_ask']} | {row['no_bid']}/{row['no_ask']} | "
            f"{row['yes_spread']}/{row['no_spread']} | {row['yes_depth']}/{row['no_depth']} | "
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
    counts, fallback = diagnose(markets, retrieved_at, config)
    candidates = scanner.build_candidates(markets, retrieved_at, config)
    scanner.write_reports(candidates, len(markets), retrieved_at, args.output, config)
    write_diagnostics(counts, fallback, args.output, retrieved_at)
    print(f"Calibration complete: {len(markets)} markets, {len(candidates)} strict candidates.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
