from __future__ import annotations

import json
import os
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import scanner


_ORIGINAL_SESSION = requests.Session


class ThrottledSession(_ORIGINAL_SESSION):
    """Paced session that avoids endless anonymous-API pagination.

    GitHub-hosted runners share public IP addresses, so a complete anonymous
    crawl can be rate-limited for long periods. We deliberately cap the number
    of market pages and turn the final fetched page into a terminal page. The
    generated report therefore remains useful, but clearly represents a
    timestamped partial crawl rather than every open Kalshi market.
    """

    def __init__(self) -> None:
        super().__init__()
        self.market_pages = 0
        self.max_market_pages = int(os.getenv("KALSHI_MAX_MARKET_PAGES", "6"))
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

    def get(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        time.sleep(0.75)
        response = super().get(*args, **kwargs)
        response.raise_for_status()

        url = str(getattr(response, "url", ""))
        if "/markets" in url:
            self.market_pages += 1
            if self.market_pages >= self.max_market_pages:
                payload = response.json()
                if isinstance(payload, dict):
                    payload["cursor"] = ""
                    response._content = json.dumps(payload).encode("utf-8")
                    response.headers["Content-Length"] = str(len(response._content))
        return response


def main() -> int:
    scanner.requests.Session = ThrottledSession
    return scanner.main()


if __name__ == "__main__":
    raise SystemExit(main())
