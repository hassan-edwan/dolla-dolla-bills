"""FRED macro data (free, no API key).

Market-priced series (rates, spreads, VIX) are never revised, so their
observation date plus one day works as ``knowable_at``. REVISED series (GDP, CPI,
payrolls) must come from ALFRED vintages instead, or backtests will see revised
numbers that did not exist at the time. Those are refused here on purpose.
"""
from __future__ import annotations

import io

import pandas as pd

from .http import RateLimitedSession

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"

# Market-observed, unrevised series that are safe to use with a 1-day lag.
MARKET_SERIES = {
    "DGS3MO": "3-month Treasury yield",
    "DGS2": "2-year Treasury yield",
    "DGS10": "10-year Treasury yield",
    "T10Y2Y": "10y-2y spread",
    "VIXCLS": "VIX close",
    "BAMLH0A0HYM2": "High-yield OAS",
    "DTWEXBGS": "Broad dollar index",
    "DCOILWTICO": "WTI crude spot",
    "DHHNGSP": "Henry Hub natural gas spot",
}


def fetch_series(series_id: str, session: RateLimitedSession | None = None) -> pd.DataFrame:
    """Return a PIT-format frame for a market series."""
    if series_id not in MARKET_SERIES:
        raise ValueError(f"{series_id} is not whitelisted as unrevised; use ALFRED vintages for revised data")
    session = session or RateLimitedSession(min_interval_s=0.5)
    text = session.get(FRED_CSV, params={"id": series_id}).text
    df = pd.read_csv(io.StringIO(text))
    date_col = df.columns[0]
    df = df.rename(columns={date_col: "period_end", series_id: "value"})
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["value"])
    df["period_end"] = pd.to_datetime(df["period_end"])
    # Published after the close; usable from the next day.
    df["knowable_at"] = (df["period_end"] + pd.Timedelta(days=1)).dt.tz_localize("UTC")
    df["entity"] = "MACRO"
    df["field"] = series_id
    df["source"] = "fred"
    return df[["entity", "field", "period_end", "value", "knowable_at", "source"]]
