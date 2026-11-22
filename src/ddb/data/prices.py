"""Daily price data: free Yahoo chart endpoint + local Parquet cache + panel container.

Yahoo's ``quote`` OHLC is split-adjusted but NOT dividend-adjusted, so the
simulator trades on these prices and credits dividends as cash. Yahoo is an
unofficial source with gaps, and delisted tickers are usually missing
(survivorship bias). The failure ledger (failures.py) exists to compensate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .http import RateLimitedSession

YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
YAHOO_UA = "Mozilla/5.0"
FIELDS = ["open", "high", "low", "close", "volume"]


def fetch_yahoo_daily(symbol: str, start: str = "2000-01-01", end: str | None = None,
                      session: RateLimitedSession | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (bars, events). bars: date-indexed OHLCV + adjclose. events: dividends/splits."""
    session = session or RateLimitedSession(min_interval_s=0.5, user_agent=YAHOO_UA)
    p1 = int(pd.Timestamp(start, tz="UTC").timestamp())
    p2 = int((pd.Timestamp(end, tz="UTC") if end else pd.Timestamp.now(tz="UTC")).timestamp())
    resp = session.get(YAHOO_CHART.format(symbol=symbol), params={
        "period1": p1, "period2": p2, "interval": "1d",
        "events": "div,splits", "includeAdjustedClose": "true"})
    result = resp.json()["chart"]["result"]
    if not result:
        raise ValueError(f"no data for {symbol}")
    r = result[0]
    ts = r.get("timestamp") or []
    q = r["indicators"]["quote"][0]
    tz = r.get("meta", {}).get("exchangeTimezoneName", "America/New_York")
    idx = pd.to_datetime(ts, unit="s", utc=True).tz_convert(tz).tz_localize(None).normalize()
    bars = pd.DataFrame({f: q.get(f) for f in FIELDS}, index=idx, dtype="float64")
    adj = r["indicators"].get("adjclose")
    if adj:
        bars["adjclose"] = np.asarray(adj[0]["adjclose"], dtype="float64")
    bars.index.name = "date"
    bars = bars[~bars.index.duplicated(keep="last")].dropna(subset=["close"])

    ev_rows = []
    for kind, key in (("dividend", "dividends"), ("split", "splits")):
        for e in (r.get("events", {}).get(key) or {}).values():
            d = pd.to_datetime(e["date"], unit="s", utc=True).tz_convert(tz).tz_localize(None).normalize()
            if kind == "dividend":
                ev_rows.append({"date": d, "symbol": symbol, "type": kind, "value": float(e["amount"])})
            else:
                ev_rows.append({"date": d, "symbol": symbol, "type": kind,
                                "value": float(e["numerator"]) / float(e["denominator"])})
    events = pd.DataFrame(ev_rows, columns=["date", "symbol", "type", "value"])
    return bars, events


def cache_symbols(symbols, root: str | Path, start: str = "2000-01-01", end: str | None = None) -> dict:
    """Download and cache each symbol under root/prices. Returns {symbol: error} for failures."""
    root = Path(root)
    (root / "prices").mkdir(parents=True, exist_ok=True)
    (root / "events").mkdir(parents=True, exist_ok=True)
    session = RateLimitedSession(min_interval_s=0.5, user_agent=YAHOO_UA)
    errors = {}
    for s in symbols:
        try:
            bars, events = fetch_yahoo_daily(s, start, end, session)
            bars.to_parquet(root / "prices" / f"{s}.parquet")
            events.to_parquet(root / "events" / f"{s}.parquet", index=False)
        except Exception as exc:  # noqa: BLE001 - record and continue
            errors[s] = repr(exc)
    return errors


@dataclass
class PriceData:
    """Wide panels (index=trading dates, columns=symbols)."""
    open: pd.DataFrame
    high: pd.DataFrame
    low: pd.DataFrame
    close: pd.DataFrame
    volume: pd.DataFrame
    dividends: pd.DataFrame = field(default_factory=pd.DataFrame)  # same shape, per-share cash

    def __post_init__(self):
        idx = self.close.index
        cols = self.close.columns
        for name in ("open", "high", "low", "volume"):
            setattr(self, name, getattr(self, name).reindex(index=idx, columns=cols))
        self.dividends = (self.dividends.reindex(index=idx, columns=cols).fillna(0.0)
                          if not self.dividends.empty else pd.DataFrame(0.0, index=idx, columns=cols))

    @property
    def calendar(self) -> pd.DatetimeIndex:
        return self.close.index

    @property
    def symbols(self) -> list[str]:
        return list(self.close.columns)

    def last_valid_date(self, symbol: str):
        return self.close[symbol].last_valid_index()

    @classmethod
    def from_long(cls, df: pd.DataFrame, dividends: pd.DataFrame | None = None) -> "PriceData":
        """df columns: date, symbol, open, high, low, close, volume."""
        panels = {f: df.pivot(index="date", columns="symbol", values=f).sort_index() for f in FIELDS}
        div = pd.DataFrame()
        if dividends is not None and not dividends.empty:
            div = dividends.pivot_table(index="date", columns="symbol", values="value", aggfunc="sum")
        return cls(**panels, dividends=div)

    @classmethod
    def from_cache(cls, root: str | Path, symbols) -> "PriceData":
        root = Path(root)
        frames, divs = [], []
        for s in symbols:
            p = root / "prices" / f"{s}.parquet"
            if not p.exists():
                continue
            b = pd.read_parquet(p)[FIELDS].reset_index()
            b["symbol"] = s
            frames.append(b)
            e = root / "events" / f"{s}.parquet"
            if e.exists():
                ev = pd.read_parquet(e)
                divs.append(ev[ev["type"] == "dividend"])
        if not frames:
            raise FileNotFoundError(f"no cached prices under {root}")
        long = pd.concat(frames, ignore_index=True)
        div = pd.concat(divs, ignore_index=True) if divs else None
        return cls.from_long(long, div)
