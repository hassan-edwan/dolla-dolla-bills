"""Clean Alpaca price series matched to companies by name or filing symbol.

Exchanges reuse tickers. Alpaca returns a symbol's full history, which can include
an earlier company that used the same ticker and placeholder bars (flat price,
zero volume) between the two. Example: Civitas Solutions (CIVI, acquired March 2019
at $17.75) and Civitas Resources (CIVI from November 2021): the stored series showed
the first company, 2.5 years of $17.76 placeholders, then a fake +216% day.

Rules, for every Alpaca-sourced series:
1. drop zero-volume bars (placeholders, not trades);
2. split the series at gaps of more than 45 days without trades and keep only the
   last continuous run: the matched company is the one trading up to its delisting
   (or today), so an earlier run after a long silence is a previous user of the ticker.

Yahoo series come from each company's current ticker and are not touched; their
zero-volume days are illiquid days at an unchanged price.

    python -m ddb.db.clean_prices
"""
from __future__ import annotations

import pandas as pd

from ..config import DATA_DIR

PRICE_DIR = DATA_DIR / "db" / "prices"
MAX_GAP_DAYS = 45


def clean(df: pd.DataFrame) -> pd.DataFrame:
    vol = df["volume_raw"] if "volume_raw" in df else df["volume"]
    d = df[vol.fillna(0) > 0].sort_values("date")
    if d.empty:
        return d
    dates = pd.to_datetime(d["date"])
    breaks = dates.diff().dt.days > MAX_GAP_DAYS
    if breaks.any():
        start = dates[breaks].iloc[-1]
        d = d[dates >= start]
    return d


def run() -> dict:
    files = sorted(PRICE_DIR.glob("alpaca*.parquet"))
    changed = dropped = emptied = 0
    for f in files:
        df = pd.read_parquet(f)
        c = clean(df)
        if len(c) == len(df):
            continue
        dropped += len(df) - len(c)
        changed += 1
        if c.empty:
            f.unlink()
            emptied += 1
        else:
            c.to_parquet(f, index=False)
    return {"files": len(files), "changed": changed, "bars_dropped": dropped, "files_emptied": emptied}


if __name__ == "__main__":
    print(run())
