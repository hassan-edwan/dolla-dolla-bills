"""Measured bid-ask spreads from sampled Alpaca quotes (free account, SIP feed).

The cost model otherwise guesses the spread from a liquidity tier (configs/sim.yaml).
This samples real quotes: for each symbol and month, 3 trading days (the 4th, 10th
and 16th of the month) x 3 one-minute windows (10:00, 12:30 and 15:30 New York),
and keeps the median quoted spread, (ask - bid) / midpoint, over valid quotes.

Point in time: a month's spread is public after that month ends, and the cost
model applies it from the next month on (ddb.sim.costs.CostModel.measured).

Storage: data/db/spreads/<YEAR>.parquet with symbol, month (month-end), spread_bps
(full spread), n_quotes, windows, knowable_at.

    python -m ddb.db.build_spreads [--start 2019-01] [--max-symbols 300]
"""
from __future__ import annotations

import argparse
import time

import numpy as np
import pandas as pd

from ..config import DATA_DIR
from ..data.alpaca import DATA, Alpaca

OUT = DATA_DIR / "db" / "spreads"
MANIFEST = DATA_DIR / "db" / "intraday" / "symbols.parquet"
WINDOWS = ["10:00", "12:30", "15:30"]
DAY_IDX = [3, 9, 15]


def sample_times(month: pd.Period) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    days = pd.bdate_range(month.start_time, month.end_time)
    out = []
    for i in DAY_IDX:
        if i < len(days):
            for w in WINDOWS:
                s = pd.Timestamp(f"{days[i].date()} {w}").tz_localize("America/New_York")
                out.append((s, s + pd.Timedelta(minutes=1)))
    return out


def spread_stats(quotes: pd.DataFrame) -> pd.DataFrame:
    """quotes: symbol, window, bp, ap -> per symbol median spread per window, then across windows."""
    q = quotes[(quotes["bp"] > 0) & (quotes["ap"] > quotes["bp"])].copy()
    q["bps"] = (q["ap"] - q["bp"]) / ((q["ap"] + q["bp"]) / 2) * 1e4
    q = q[q["bps"] < 2000]
    w = q.groupby(["symbol", "window"]).agg(bps=("bps", "median"), n=("bps", "size")).reset_index()
    return w.groupby("symbol").agg(spread_bps=("bps", "median"), n_quotes=("n", "sum"), windows=("window", "nunique")).reset_index()


def fetch_quotes(api: Alpaca, symbols: list[str], start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    params = {"symbols": ",".join(symbols), "start": start.tz_convert("UTC").isoformat(),
              "end": end.tz_convert("UTC").isoformat(), "limit": 10000, "feed": "sip"}
    rows = []
    while True:
        d = api.s.get(f"{DATA}/v2/stocks/quotes", params=params).json()
        for sym, qs in (d.get("quotes") or {}).items():
            rows += [(sym, q.get("bp"), q.get("ap")) for q in qs]
        tok = d.get("next_page_token")
        if not tok:
            break
        params["page_token"] = tok
    return pd.DataFrame(rows, columns=["symbol", "bp", "ap"])


def build(start: str = "2019-01", max_symbols: int = 300, batch: int = 25) -> dict:
    t0 = time.time()
    if not MANIFEST.exists():
        raise SystemExit("Run python -m ddb.db.build_intraday first (it picks the symbols)")
    syms = pd.read_parquet(MANIFEST)["symbol"].head(max_symbols).tolist()
    api = Alpaca()
    OUT.mkdir(parents=True, exist_ok=True)
    last = (pd.Timestamp.now() - pd.offsets.MonthEnd(1)).to_period("M")
    n = 0
    for month in pd.period_range(start, last, freq="M"):
        f = OUT / f"{month.year}.parquet"
        old = pd.read_parquet(f) if f.exists() else pd.DataFrame(columns=["month"])
        if (pd.to_datetime(old["month"]) == month.end_time.normalize()).any():
            continue
        parts = []
        for s, e in sample_times(month):
            for i in range(0, len(syms), batch):
                q = fetch_quotes(api, syms[i:i + batch], s, e)
                if len(q):
                    parts.append(q.assign(window=f"{s:%Y-%m-%d %H:%M}"))
        if not parts:
            continue
        st = spread_stats(pd.concat(parts))
        st["month"] = month.end_time.normalize()
        st["knowable_at"] = (month.end_time.normalize() + pd.Timedelta(days=1)).tz_localize("UTC")
        pd.concat([old, st], ignore_index=True).to_parquet(f, index=False)
        n += len(st)
        print(f"  {month}: {len(st)} symbols, median spread {st['spread_bps'].median():.1f} bp, {time.time() - t0:.0f}s", flush=True)
    return {"rows": n, "seconds": round(time.time() - t0)}


def load_measured(symbols_to_key: dict | None = None) -> pd.DataFrame:
    """Wide frame: index = first day each value may be used (the month after it was
    measured), columns = symbol (or mapped key), values = HALF spread in bps."""
    if not OUT.exists() or not any(OUT.glob("*.parquet")):
        return pd.DataFrame()
    df = pd.concat([pd.read_parquet(f) for f in OUT.glob("*.parquet")], ignore_index=True)
    df["use_from"] = pd.to_datetime(df["month"]) + pd.Timedelta(days=1)
    if symbols_to_key:
        df["symbol"] = df["symbol"].map(symbols_to_key)
        df = df.dropna(subset=["symbol"])
    return df.pivot_table(index="use_from", columns="symbol", values="spread_bps", aggfunc="median").sort_index() / 2


def align(measured: pd.DataFrame, index: pd.DatetimeIndex, columns, max_age_days: int = 100) -> pd.DataFrame:
    """Measured half-spreads on a bar index (latest value usable at each bar, at most
    `max_age_days` old); NaN where none."""
    if measured.empty:
        return pd.DataFrame(np.nan, index=index, columns=columns)
    m = measured.reindex(columns=columns)
    stamp = pd.DataFrame(np.repeat(m.index.to_numpy()[:, None], m.shape[1], axis=1), index=m.index, columns=m.columns).where(m.notna())
    allidx = m.index.union(index)
    v = m.reindex(allidx).ffill().reindex(index)
    age = (index.to_numpy()[:, None] - stamp.reindex(allidx).ffill().reindex(index).to_numpy()).astype("timedelta64[D]").astype(float)
    return v.where(age <= max_age_days)
