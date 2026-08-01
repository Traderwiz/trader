from __future__ import annotations

import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import scanner


_ORIGINAL_SESSION = requests.Session


class ThrottledSession(_ORIGINAL_SESSION):
    """Requests session with conservative pacing and automatic 429 retries."""

    def __init__(self) -> None:
        super().__init__()
        retry = Retry(
            total=7,
            connect=3,
            read=3,
            status=7,
            backoff_factor=2.0,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        self.mount("https://", HTTPAdapter(max_retries=retry))
        self.mount("http://", HTTPAdapter(max_retries=retry))

    def get(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        # Public market pagination is deliberately paced to avoid Kalshi's
        # anonymous API rate limit on shared GitHub-hosted runner addresses.
        time.sleep(1.25)
        response = super().get(*args, **kwargs)
        response.raise_for_status()
        return response


def main() -> int:
    scanner.requests.Session = ThrottledSession
    return scanner.main()


if __name__ == "__main__":
    raise SystemExit(main())
