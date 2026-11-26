"""Polite HTTP client shared by all free data sources (rate limiting, retries)."""
from __future__ import annotations

import os
import time

import requests

# The SEC requires a descriptive User-Agent that includes contact information.
# Set DDB_SEC_USER_AGENT="your-project-name your-email@example.com".
SEC_UA_ENV = "DDB_SEC_USER_AGENT"


SEC_UA_FILE = os.path.expanduser("~/.config/ddb/sec_user_agent")


def sec_user_agent() -> str:
    """'project-name contact@email' from $DDB_SEC_USER_AGENT, else ~/.config/ddb/sec_user_agent."""
    ua = os.environ.get(SEC_UA_ENV)
    if not ua and os.path.exists(SEC_UA_FILE):
        with open(SEC_UA_FILE) as f:
            ua = f.read().strip()
    if not ua:
        raise RuntimeError(
            f"Set {SEC_UA_ENV} (or write {SEC_UA_FILE}) to 'project-name contact@email' before calling "
            "SEC EDGAR (required by SEC fair-access rules)."
        )
    return ua


class RateLimitedSession:
    def __init__(self, min_interval_s: float = 0.15, user_agent: str | None = None,
                 retries: int = 4, timeout_s: float = 30.0):
        self.session = requests.Session()
        if user_agent:  # otherwise keep the requests default (some hosts stall on others)
            self.session.headers["User-Agent"] = user_agent
        self.min_interval_s = min_interval_s
        self.retries = retries
        self.timeout_s = timeout_s
        self._last = 0.0

    def get(self, url: str, **kwargs) -> requests.Response:
        for attempt in range(self.retries + 1):
            wait = self.min_interval_s - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                resp = self.session.get(url, timeout=self.timeout_s, **kwargs)
            except requests.RequestException:
                if attempt == self.retries:
                    raise
                time.sleep(2 ** attempt)
                continue
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < self.retries:
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            return resp
        raise RuntimeError("unreachable")
