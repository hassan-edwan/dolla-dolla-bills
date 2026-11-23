"""Daily prices for every ticker in the company database (Yahoo, free).

Yahoo's OHLC is adjusted for splits that happened LATER, which leaks the
future into price levels (a stock that reverse-split 1:50 in 2023 shows a
2021 price 50x too high). We store both:
  - open/high/low/close: split-adjusted (consistent returns)
  - close_raw / volume_raw: as actually traded on that day, reconstructed by
    undoing every split after the date. Use these for price/volume levels.

knowable_at = 21:00 UTC on the bar date (after the 16:00 ET close in both
EST and EDT).

    python -m ddb.db.build_prices [--limit N] [--only-missing]
"""
from __future__ import annotations

import argparse
import time

import numpy as np
import pandas as pd

from ..config import DATA_DIR
from ..data.http import RateLimitedSession
from ..data.prices import YAHOO_UA, fetch_yahoo_daily
from .schema import connect

DB_PATH = DATA_DIR / "ddb.duckdb"


def unadjust(bars: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """Add close_raw / volume_raw by undoing splits after each bar's date."""
    bars = bars.copy()
    splits = events[events["type"] == "split"].set_index("date")["value"] if not events.empty else pd.Series(dtype=float)
    factor = pd.Series(1.0, index=bars.index)
    for d, ratio in splits.items():
        factor[bars.index < d] *= ratio       # e.g. 4:1 split -> earlier raw prices were 4x higher
    bars["close_raw"] = bars["close"] * factor
    bars["volume_raw"] = bars["volume"] / factor
    return bars


def tickers_to_fetch(con, only_missing: bool) -> list[str]:
    q = """
        SELECT DISTINCT ticker FROM tickers
        WHERE ticker IS NOT NULL AND ticker <> ''
    """
    syms = con.execute(q).df()["ticker"].tolist()
    if only_missing:
        have = set(con.execute("SELECT DISTINCT symbol FROM prices").df()["symbol"])
        syms = [s for s in syms if s not in have]
    return sorted(syms)


PRICE_DIR = DATA_DIR / "db" / "prices"
ACTION_DIR = DATA_DIR / "db" / "corporate_actions"
LOG_PATH = DATA_DIR / "db" / "price_fetch_log.csv"
PRICE_COLS = ["symbol", "date", "open", "high", "low", "close", "adjclose", "volume",
              "close_raw", "volume_raw", "source", "knowable_at"]


def build(db_path=DB_PATH, start="2000-01-01", limit=None, only_missing=True, symbols=None):
    """One Parquet file per ticker (no long-held database lock)."""
    PRICE_DIR.mkdir(parents=True, exist_ok=True)
    ACTION_DIR.mkdir(parents=True, exist_ok=True)
    if symbols is None:
        con = connect(db_path, read_only=True)
        symbols = con.execute("SELECT DISTINCT upper(ticker) t FROM tickers "
                              "WHERE ticker IS NOT NULL AND ticker <> '' ORDER BY 1").df()["t"].tolist()
        con.close()
    log = pd.read_csv(LOG_PATH) if LOG_PATH.exists() else pd.DataFrame(
        columns=["symbol", "fetched_at", "status", "n_bars", "first_date", "last_date", "error"])
    if only_missing:
        symbols = [s for s in symbols if s not in set(log["symbol"])]
    if limit:
        symbols = symbols[:limit]
    session = RateLimitedSession(min_interval_s=0.4, user_agent=YAHOO_UA, retries=2)
    t0, ok, bad, new_log = time.time(), 0, 0, []
    for k, s in enumerate(symbols):
        now = pd.Timestamp.now(tz="UTC")
        fname = s.replace("/", "_")
        try:
            bars, events = fetch_yahoo_daily(s.replace(".", "-"), start=start, session=session)
            bars = unadjust(bars, events).reset_index()
            bars["symbol"] = s
            bars["source"] = "yahoo"
            bars["date"] = pd.to_datetime(bars["date"])
            bars["knowable_at"] = (bars["date"] + pd.Timedelta(hours=21)).dt.tz_localize("UTC")
            if "adjclose" not in bars:
                bars["adjclose"] = np.nan
            bars[PRICE_COLS].to_parquet(PRICE_DIR / f"{fname}.parquet", index=False)
            if not events.empty:
                ev = events.copy()
                ev["symbol"] = s
                ev["date"] = pd.to_datetime(ev["date"])
                # Announced before the ex-date; ex-date 13:00 UTC is conservative for a next-day trader.
                ev["knowable_at"] = (ev["date"] + pd.Timedelta(hours=13)).dt.tz_localize("UTC")
                ev[["symbol", "date", "type", "value", "knowable_at"]].to_parquet(
                    ACTION_DIR / f"{fname}.parquet", index=False)
            new_log.append([s, now, "ok", len(bars), bars["date"].min().date(), bars["date"].max().date(), ""])
            ok += 1
        except Exception as exc:  # noqa: BLE001
            new_log.append([s, now, "error", 0, None, None, repr(exc)[:300]])
            bad += 1
        if k % 100 == 0 or k == len(symbols) - 1:
            log = pd.concat([log, pd.DataFrame(new_log, columns=log.columns)], ignore_index=True)
            log.to_csv(LOG_PATH, index=False)
            new_log = []
            print(f"  {k + 1}/{len(symbols)} ok={ok} failed={bad} {time.time() - t0:.0f}s", flush=True)
    return {"ok": ok, "failed": bad, "seconds": round(time.time() - t0)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--all", action="store_true", help="refetch everything")
    a = ap.parse_args()
    print(build(limit=a.limit, only_missing=not a.all))
