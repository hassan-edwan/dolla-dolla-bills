"""Alpaca market data (free account): asset list incl. delisted, daily bars since 2016.

Credentials come from the environment (APCA_API_KEY_ID / APCA_API_SECRET_KEY)
or from ~/.config/ddb/alpaca.env. Never put them in the repo.
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from .http import RateLimitedSession

TRADING = "https://paper-api.alpaca.markets"
DATA = "https://data.alpaca.markets"
CRED_FILE = Path.home() / ".config" / "ddb" / "alpaca.env"


def _creds() -> dict:
    key, secret = os.environ.get("APCA_API_KEY_ID"), os.environ.get("APCA_API_SECRET_KEY")
    if not (key and secret) and CRED_FILE.exists():
        vals = dict(line.strip().split("=", 1) for line in CRED_FILE.read_text().splitlines() if "=" in line)
        key, secret = vals.get("APCA_API_KEY_ID"), vals.get("APCA_API_SECRET_KEY")
    if not (key and secret):
        raise RuntimeError(f"Alpaca credentials missing: set APCA_API_KEY_ID/APCA_API_SECRET_KEY or {CRED_FILE}")
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


class Alpaca:
    def __init__(self, min_interval_s: float = 0.31):   # free tier: 200 requests/minute
        self.s = RateLimitedSession(min_interval_s=min_interval_s, retries=4, timeout_s=60)
        self.s.session.headers.update(_creds())

    def assets(self, status: str = "all") -> pd.DataFrame:
        out = []
        for st in (["active", "inactive"] if status == "all" else [status]):
            r = self.s.get(f"{TRADING}/v2/assets", params={"status": st, "asset_class": "us_equity"})
            out.append(pd.DataFrame(r.json()))
        return pd.concat(out, ignore_index=True)

    def daily_bars(self, symbols: list[str], start: str, end: str | None = None,
                   adjustment: str = "raw") -> pd.DataFrame:
        """adjustment='raw' = as traded; 'split' = split-adjusted."""
        params = {"symbols": ",".join(symbols), "timeframe": "1Day", "start": start,
                  "adjustment": adjustment, "feed": "sip", "limit": 10000}
        if end:
            params["end"] = end
        rows = []
        while True:
            d = self.s.get(f"{DATA}/v2/stocks/bars", params=params).json()
            for sym, bars in (d.get("bars") or {}).items():
                for b in bars:
                    rows.append((sym, b["t"], b["o"], b["h"], b["l"], b["c"], b["v"], b.get("vw"), b.get("n")))
            tok = d.get("next_page_token")
            if not tok:
                break
            params["page_token"] = tok
        df = pd.DataFrame(rows, columns=["symbol", "t", "open", "high", "low", "close", "volume", "vwap", "trades"])
        if not df.empty:
            df["date"] = pd.to_datetime(df["t"], utc=True).dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize()
            df = df.drop(columns="t")
        return df
