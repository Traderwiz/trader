from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable

import requests
import yaml


@dataclass(frozen=True)
class Candidate:
    ticker: str
    event_ticker: str
    title: str
    subtitle: str
    close_time_utc: str
    days_to_close: float
    volume: int
    open_interest: int
    yes_bid_cents: int | None
    yes_ask_cents: int | None
    no_bid_cents: int | None
    no_ask_cents: int | None
    yes_ask_size: int | None
    no_ask_size: int | None
    spread_cents: int | None
    side: str
    live_ask_cents: int
    ask_depth_contracts: int | None
    estimated_fee_usd: str
    estimated_break_even_pct: str
    technical_score: float
    retrieved_at_utc: str


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def parse_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def dollars_to_cents(value: Any) -> int | None:
    parsed = parse_decimal(value)
    if parsed is None:
        return None
    return int((parsed * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def first_cents(market: dict[str, Any], *names: str) -> int | None:
    for name in names:
        if name in market and market[name] is not None:
            if name.endswith("_dollars"):
                result = dollars_to_cents(market[name])
            else:
                try:
                    result = int(market[name])
                except (TypeError, ValueError):
                    result = None
            if result is not None:
                return result
    return None


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def fetch_open_markets(config: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    base_url = config["api_base_url"].rstrip("/")
    timeout = int(config["request_timeout_seconds"])
    limit = int(config["page_limit"])
    cursor: str | None = None
    markets: list[dict[str, Any]] = []
    retrieved_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    session = requests.Session()
    session.headers.update({"User-Agent": "wealthsimple-prediction-scanner/0.1"})

    while True:
        params: dict[str, Any] = {"status": "open", "limit": limit}
        if cursor:
            params["cursor"] = cursor
        response = session.get(f"{base_url}/markets", params=params, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        page = payload.get("markets", [])
        if not isinstance(page, list):
            raise RuntimeError("Kalshi response did not contain a markets list")
        markets.extend(page)
        cursor = payload.get("cursor")
        if not cursor:
            break

    return markets, retrieved_at


def text_matches(market: dict[str, Any], config: dict[str, Any]) -> bool:
    text = " ".join(
        str(market.get(key, ""))
        for key in ("title", "subtitle", "yes_sub_title", "no_sub_title", "rules_primary")
    ).lower()
    excluded = [str(item).lower() for item in config.get("exclude_keywords", [])]
    included = [str(item).lower() for item in config.get("include_keywords", [])]
    if any(term in text for term in excluded):
        return False
    return not included or any(term in text for term in included)


def estimate_fee(cost: Decimal, fee_config: dict[str, Any]) -> Decimal:
    pct = Decimal(str(fee_config["percent_of_contract_cost"]))
    minimum = Decimal(str(fee_config["minimum_fee_usd"]))
    fee = max(cost * pct, minimum)
    return fee.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def candidate_for_side(
    market: dict[str, Any],
    side: str,
    ask_cents: int | None,
    ask_depth: int | None,
    spread_cents: int | None,
    days_to_close: float,
    retrieved_at: str,
    config: dict[str, Any],
) -> Candidate | None:
    filters = config["filters"]
    if ask_cents is None:
        return None
    if not filters["allowed_price_min_cents"] <= ask_cents <= filters["allowed_price_max_cents"]:
        return None
    if spread_cents is None or spread_cents > filters["maximum_spread_cents"]:
        return None
    if ask_depth is not None and ask_depth < filters["minimum_ask_depth_contracts"]:
        return None

    volume = int(market.get("volume") or 0)
    open_interest = int(market.get("open_interest") or 0)
    if volume < filters["minimum_volume_contracts"]:
        return None

    order_usd = Decimal(str(config["estimated_wealthsimple_fee"]["test_order_usd"]))
    ask_dollars = Decimal(ask_cents) / Decimal(100)
    contract_cost = order_usd / (Decimal(1) + Decimal(str(config["estimated_wealthsimple_fee"]["percent_of_contract_cost"])))
    estimated_fee = estimate_fee(contract_cost, config["estimated_wealthsimple_fee"])
    contracts = contract_cost / ask_dollars
    payout = contracts
    break_even = order_usd / payout if payout > 0 else Decimal(1)

    liquidity_score = min(40.0, math.log10(max(volume, 1)) * 8.0)
    spread_score = max(0.0, 24.0 - spread_cents * 4.0)
    depth_score = 10.0 if ask_depth is None else min(16.0, math.log10(max(ask_depth, 1)) * 6.0)
    time_score = max(0.0, 20.0 * (1.0 - days_to_close / filters["maximum_days_to_close"]))
    extreme_penalty = abs(50 - ask_cents) * 0.12
    technical_score = round(liquidity_score + spread_score + depth_score + time_score - extreme_penalty, 2)

    return Candidate(
        ticker=str(market.get("ticker", "")),
        event_ticker=str(market.get("event_ticker", "")),
        title=str(market.get("title", "")),
        subtitle=str(market.get("subtitle", "")),
        close_time_utc=str(market.get("close_time", "")),
        days_to_close=round(days_to_close, 2),
        volume=volume,
        open_interest=open_interest,
        yes_bid_cents=first_cents(market, "yes_bid_dollars", "yes_bid"),
        yes_ask_cents=first_cents(market, "yes_ask_dollars", "yes_ask"),
        no_bid_cents=first_cents(market, "no_bid_dollars", "no_bid"),
        no_ask_cents=first_cents(market, "no_ask_dollars", "no_ask"),
        yes_ask_size=int(market.get("yes_ask_size") or 0) or None,
        no_ask_size=int(market.get("no_ask_size") or 0) or None,
        spread_cents=spread_cents,
        side=side,
        live_ask_cents=ask_cents,
        ask_depth_contracts=ask_depth,
        estimated_fee_usd=f"{estimated_fee:.2f}",
        estimated_break_even_pct=f"{(break_even * 100):.2f}",
        technical_score=technical_score,
        retrieved_at_utc=retrieved_at,
    )


def build_candidates(markets: Iterable[dict[str, Any]], retrieved_at: str, config: dict[str, Any]) -> list[Candidate]:
    now = parse_utc(retrieved_at)
    filters = config["filters"]
    results: list[Candidate] = []

    for market in markets:
        if not text_matches(market, config):
            continue
        close_raw = market.get("close_time")
        if not close_raw:
            continue
        try:
            close_time = parse_utc(str(close_raw))
        except ValueError:
            continue
        days_to_close = (close_time - now).total_seconds() / 86400
        if days_to_close <= 0 or days_to_close > filters["maximum_days_to_close"]:
            continue

        yes_bid = first_cents(market, "yes_bid_dollars", "yes_bid")
        yes_ask = first_cents(market, "yes_ask_dollars", "yes_ask")
        no_bid = first_cents(market, "no_bid_dollars", "no_bid")
        no_ask = first_cents(market, "no_ask_dollars", "no_ask")

        # Derive asks from the opposite bid when the direct ask field is absent.
        if yes_ask is None and no_bid is not None:
            yes_ask = 100 - no_bid
        if no_ask is None and yes_bid is not None:
            no_ask = 100 - yes_bid

        yes_spread = yes_ask - yes_bid if yes_ask is not None and yes_bid is not None else None
        no_spread = no_ask - no_bid if no_ask is not None and no_bid is not None else None
        yes_depth = int(market.get("yes_ask_size") or 0) or None
        no_depth = int(market.get("no_ask_size") or 0) or None

        for item in (
            candidate_for_side(market, "YES", yes_ask, yes_depth, yes_spread, days_to_close, retrieved_at, config),
            candidate_for_side(market, "NO", no_ask, no_depth, no_spread, days_to_close, retrieved_at, config),
        ):
            if item:
                results.append(item)

    results.sort(key=lambda candidate: (-candidate.technical_score, candidate.days_to_close, -candidate.volume))
    return results[: int(filters["shortlist_size"])]


def write_reports(candidates: list[Candidate], markets_count: int, retrieved_at: str, output_dir: Path, config: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = retrieved_at.replace(":", "-").replace("Z", "Z")
    json_path = output_dir / f"scan-{stamp}.json"
    csv_path = output_dir / f"scan-{stamp}.csv"
    latest_md = output_dir / "latest.md"

    payload = {
        "retrieved_at_utc": retrieved_at,
        "source": f"{config['api_base_url'].rstrip('/')}/markets",
        "markets_retrieved": markets_count,
        "candidate_count": len(candidates),
        "warning": "Technical shortlist only. It does not estimate true probabilities or guarantee Wealthsimple availability.",
        "candidates": [asdict(candidate) for candidate in candidates],
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(candidates[0]).keys()) if candidates else ["retrieved_at_utc"])
        writer.writeheader()
        for candidate in candidates:
            writer.writerow(asdict(candidate))

    lines = [
        "# Live Prediction-Market Technical Shortlist",
        "",
        f"- Retrieved: `{retrieved_at}`",
        f"- Source: `{config['api_base_url'].rstrip('/')}/markets`",
        f"- Open markets retrieved: **{markets_count:,}**",
        f"- Candidates passing technical filters: **{len(candidates)}**",
        "",
        "> This is candidate discovery only. It does not estimate the true probability of an outcome. Every finalist must be researched independently and verified with a live Wealthsimple order preview.",
        "",
        "| Rank | Ticker | Side | Live ask | Spread | Ask depth | Volume | Days | Est. WS break-even | Score | Contract |",
        "|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for rank, candidate in enumerate(candidates, start=1):
        lines.append(
            f"| {rank} | `{candidate.ticker}` | {candidate.side} | {candidate.live_ask_cents}¢ | "
            f"{candidate.spread_cents if candidate.spread_cents is not None else 'n/a'}¢ | "
            f"{candidate.ask_depth_contracts if candidate.ask_depth_contracts is not None else 'n/a'} | "
            f"{candidate.volume:,} | {candidate.days_to_close:.1f} | "
            f"{candidate.estimated_break_even_pct}% | {candidate.technical_score:.2f} | "
            f"{candidate.title.replace('|', '/')} — {candidate.subtitle.replace('|', '/')} |"
        )

    latest_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a timestamped technical shortlist from live Kalshi market data.")
    parser.add_argument("--config", type=Path, default=Path("config/scanner.yml"))
    parser.add_argument("--output", type=Path, default=Path("reports"))
    args = parser.parse_args()

    try:
        config = load_config(args.config)
        markets, retrieved_at = fetch_open_markets(config)
        candidates = build_candidates(markets, retrieved_at, config)
        write_reports(candidates, len(markets), retrieved_at, args.output, config)
    except requests.RequestException as exc:
        print(f"Live market request failed: {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print(f"Scanner failed: {exc}", file=sys.stderr)
        return 3

    print(f"Retrieved {len(markets)} open markets; wrote {len(candidates)} candidates to {args.output}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
