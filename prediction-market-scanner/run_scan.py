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
    """Paced public-data session with bounded retry behaviour."""

    def __init__(self) -> None:
        super().__init__()
        retry = Retry(
            total=3,
            connect=2,
            read=2,
            status=3,
            backoff_factor=1.0,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        self.mount("https://", HTTPAdapter(max_retries=retry))
        self.mount("http://", HTTPAdapter(max_retries=retry))
        self.headers.update({"User-Agent": "wealthsimple-prediction-scanner/0.3"})

    def get(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        time.sleep(float(os.getenv("KALSHI_REQUEST_DELAY_SECONDS", "0.60")))
        response = super().get(*args, **kwargs)
        response.raise_for_status()
        return response


def fp_to_int(value: Any) -> int:
    """Convert Kalshi fixed-point string fields to whole-contract integers."""
    if value in (None, ""):
        return 0
    try:
        return max(0, int(Decimal(str(value))))
    except (InvalidOperation, ValueError, TypeError):
        return 0


def normalise_market(market: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    """Map current Kalshi event/market fields onto the scanner's stable shape."""
    item = dict(market)
    event_title = str(event.get("title") or "")
    event_subtitle = str(event.get("sub_title") or "")
    yes_subtitle = str(market.get("yes_sub_title") or "")

    item["title"] = event_title
    item["subtitle"] = " — ".join(part for part in (event_subtitle, yes_subtitle) if part)
    item["category"] = str(event.get("category") or "")
    item["series_ticker"] = str(event.get("series_ticker") or "")
    item["available_on_brokers"] = bool(event.get("available_on_brokers", False))

    item["volume"] = fp_to_int(market.get("volume_fp", market.get("volume")))
    item["open_interest"] = fp_to_int(market.get("open_interest_fp", market.get("open_interest")))
    item["yes_ask_size"] = fp_to_int(market.get("yes_ask_size_fp", market.get("yes_ask_size")))
    item["no_ask_size"] = fp_to_int(market.get("no_ask_size_fp", market.get("no_ask_size")))
    return item


def fetch_open_event_markets(config: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    """Fetch ordinary open events with nested markets.

    Unlike the raw /markets feed, /events excludes multivariate combination
    events. That prevents the first pages from being dominated by sports parlays
    and lets categories, broker availability, and event titles drive discovery.
    """
    base_url = config["api_base_url"].rstrip("/")
    timeout = int(config["request_timeout_seconds"])
    max_pages = int(os.getenv("KALSHI_MAX_EVENT_PAGES", "10"))
    cursor: str | None = None
    page_count = 0
    markets: list[dict[str, Any]] = []
    retrieved_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    session = ThrottledSession()

    while page_count < max_pages:
        params: dict[str, Any] = {
            "status": "open",
            "with_nested_markets": "true",
            "limit": 200,
        }
        if cursor:
            params["cursor"] = cursor
        response = session.get(f"{base_url}/events", params=params, timeout=timeout)
        payload = response.json()
        events = payload.get("events", [])
        if not isinstance(events, list):
            raise RuntimeError("Kalshi response did not contain an events list")

        for event in events:
            if not isinstance(event, dict):
                continue
            # Wealthsimple is a broker integration, so broker-ineligible events
            # are poor candidates even when they trade directly on Kalshi.
            if event.get("available_on_brokers") is False:
                continue
            nested = event.get("markets", [])
            if not isinstance(nested, list):
                continue
            for market in nested:
                if isinstance(market, dict) and market.get("status") == "open":
                    markets.append(normalise_market(market, event))

        page_count += 1
        cursor = payload.get("cursor")
        if not cursor:
            break

    return markets, retrieved_at


def phrase_matches(text: str, phrase: str) -> bool:
    """Match complete words/phrases instead of arbitrary substrings."""
    words = re.findall(r"[a-z0-9]+", phrase.lower())
    if not words:
        return False
    pattern = r"\b" + r"\W+".join(re.escape(word) for word in words) + r"\b"
    return re.search(pattern, text) is not None


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


def main() -> int:
    scanner.requests.Session = ThrottledSession
    scanner.fetch_open_markets = fetch_open_event_markets
    scanner.text_matches = calibrated_text_matches
    return scanner.main()


if __name__ == "__main__":
    raise SystemExit(main())
