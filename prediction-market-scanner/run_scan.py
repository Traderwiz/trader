from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import scanner


_ORIGINAL_SESSION = requests.Session


class ThrottledSession(_ORIGINAL_SESSION):
    """Paced public-data session with short, bounded retry behaviour."""

    def __init__(self) -> None:
        super().__init__()
        retry = Retry(
            total=1,
            connect=1,
            read=1,
            status=0,
            backoff_factor=0.5,
            allowed_methods=frozenset({"GET"}),
            respect_retry_after_header=False,
            raise_on_status=False,
        )
        self.mount("https://", HTTPAdapter(max_retries=retry))
        self.mount("http://", HTTPAdapter(max_retries=retry))
        self.headers.update({"User-Agent": "wealthsimple-prediction-scanner/0.5"})

    def get(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        time.sleep(float(os.getenv("KALSHI_REQUEST_DELAY_SECONDS", "0.75")))
        return super().get(*args, **kwargs)


def fp_to_int(value: Any) -> int:
    if value in (None, ""):
        return 0
    try:
        return max(0, int(Decimal(str(value))))
    except (InvalidOperation, ValueError, TypeError):
        return 0


def phrase_matches(text: str, phrase: str) -> bool:
    words = re.findall(r"[a-z0-9]+", phrase.lower())
    if not words:
        return False
    pattern = r"\b" + r"\W+".join(re.escape(word) for word in words) + r"\b"
    return re.search(pattern, text.lower()) is not None


def calibrated_text_matches(market: dict[str, Any], config: dict[str, Any]) -> bool:
    text = " ".join(
        str(market.get(key, ""))
        for key in (
            "title",
            "subtitle",
            "yes_sub_title",
            "no_sub_title",
            "rules_primary",
            "category",
            "series_ticker",
        )
    ).lower()
    excluded = [str(item) for item in config.get("exclude_keywords", [])]
    included = [str(item) for item in config.get("include_keywords", [])]
    if any(phrase_matches(text, term) for term in excluded):
        return False
    return not included or any(phrase_matches(text, term) for term in included)


def event_is_relevant(event: dict[str, Any], config: dict[str, Any]) -> bool:
    synthetic = {
        "title": event.get("title", ""),
        "subtitle": event.get("sub_title", ""),
        "category": event.get("category", ""),
        "series_ticker": event.get("series_ticker", ""),
    }
    return calibrated_text_matches(synthetic, config)


def normalise_market(market: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    item = dict(market)
    event_title = str(event.get("title") or market.get("title") or "")
    event_subtitle = str(event.get("sub_title") or "")
    market_subtitle = str(market.get("subtitle") or market.get("yes_sub_title") or "")

    item["title"] = event_title
    item["subtitle"] = " — ".join(part for part in (event_subtitle, market_subtitle) if part)
    item["category"] = str(event.get("category") or "")
    item["series_ticker"] = str(event.get("series_ticker") or "")
    item["available_on_brokers"] = bool(event.get("available_on_brokers", False))

    # Nested event payloads are not always consistent across market families.
    # Use the strongest available activity measure for technical filtering while
    # preserving open interest separately in the report.
    total_volume = fp_to_int(market.get("volume_fp", market.get("volume")))
    recent_volume = fp_to_int(market.get("volume_24h_fp"))
    open_interest = fp_to_int(market.get("open_interest_fp", market.get("open_interest")))
    item["volume"] = max(total_volume, recent_volume, open_interest)
    item["open_interest"] = open_interest
    item["yes_ask_size"] = fp_to_int(market.get("yes_ask_size_fp", market.get("yes_ask_size")))
    item["no_ask_size"] = fp_to_int(market.get("no_ask_size_fp", market.get("no_ask_size")))
    return item


def fetch_open_event_markets(config: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    """Fetch a bounded, deduplicated set of relevant ordinary open events."""
    base_url = config["api_base_url"].rstrip("/")
    timeout = min(int(config["request_timeout_seconds"]), 20)
    max_pages = int(os.getenv("KALSHI_MAX_EVENT_PAGES", "4"))
    cursor: str | None = None
    page_count = 0
    markets: list[dict[str, Any]] = []
    retrieved_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    session = ThrottledSession()

    seen_cursors: set[str] = set()
    seen_events: set[str] = set()
    seen_markets: set[str] = set()
    relevant_events = 0

    while page_count < max_pages:
        if cursor and cursor in seen_cursors:
            print("Kalshi returned a repeated event cursor; stopping partial crawl.")
            break
        if cursor:
            seen_cursors.add(cursor)

        params: dict[str, Any] = {
            "status": "open",
            "with_nested_markets": "true",
            "limit": 200,
        }
        if cursor:
            params["cursor"] = cursor

        response = session.get(f"{base_url}/events", params=params, timeout=timeout)
        if response.status_code == 429:
            if markets:
                print(f"Kalshi rate-limited page {page_count + 1}; using partial event crawl.")
                break
            response.raise_for_status()
        response.raise_for_status()

        payload = response.json()
        events = payload.get("events", [])
        if not isinstance(events, list):
            raise RuntimeError("Kalshi response did not contain an events list")

        new_events_this_page = 0
        for event in events:
            if not isinstance(event, dict):
                continue
            event_ticker = str(event.get("event_ticker") or event.get("ticker") or "")
            if event_ticker and event_ticker in seen_events:
                continue
            if event_ticker:
                seen_events.add(event_ticker)
            new_events_this_page += 1

            if event.get("available_on_brokers") is False:
                continue
            if not event_is_relevant(event, config):
                continue
            relevant_events += 1

            nested = event.get("markets", [])
            if not isinstance(nested, list):
                continue
            for market in nested:
                if not isinstance(market, dict) or market.get("status") != "open":
                    continue
                ticker = str(market.get("ticker") or "")
                if not ticker or ticker in seen_markets:
                    continue
                seen_markets.add(ticker)
                markets.append(normalise_market(market, event))

        page_count += 1
        next_cursor = payload.get("cursor")
        if not next_cursor or new_events_this_page == 0:
            break
        cursor = str(next_cursor)

    if not markets:
        raise RuntimeError("No relevant broker-eligible open markets were retrieved")
    print(
        f"Fetched {page_count} event page(s), {len(seen_events)} unique events, "
        f"{relevant_events} relevant events, and {len(markets)} unique nested markets."
    )
    return markets, retrieved_at


def main() -> int:
    scanner.requests.Session = ThrottledSession
    scanner.fetch_open_markets = fetch_open_event_markets
    scanner.text_matches = calibrated_text_matches
    return scanner.main()


if __name__ == "__main__":
    raise SystemExit(main())
