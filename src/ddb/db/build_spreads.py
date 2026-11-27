"""Measured bid-ask spreads from sampled Alpaca quotes (free account, SIP feed, 2016+).

The cost model otherwise guesses each stock's spread from its trading volume
(configs/sim.yaml tiers). This measures it: for every month, every company in that
month's liquid universe (data/db/signals/scores.parquet), under the ticker it traded
under at the time, plus the safe-haven ETFs. Sample: 3 trading days (the 4th, 10th
and 16th of the month) x 2 one-minute windows (10:30 and 14:30 New York). Spread =
median of (ask - bid) / midpoint over valid quotes per window, then the median
across windows.

Ticker reuse guard: a measurement is kept only if the quoted midpoint is within 15%
of the company's own close that day (data/db/prices), so a ticker that belonged to
someone else at the time is rejected.

Point in time: a month's spread is public after the month ends, and the cost model
uses it from the next month on (for at most 100 days).

Storage: data/db/spreads/<YEAR>.parquet: month, cik (or none for ETFs), symbol,
spread_bps (full spread), n_quotes, windows, mid, knowable_at. Resumable by month.

    python -m ddb.db.build_spreads [--start 2016-01] [--end 2026-10]
"""
from __future__ import annotations

import argparse
import time

import numpy as np
import pandas as pd

from ..config import DATA_DIR, universe_symbols
from ..data.alpaca import DATA, Alpaca
from .schema import connect

OUT = DATA_DIR / "db" / "spreads"
SCORES = DATA_DIR / "db" / "signals" / "scores.parquet"
DB_PATH = DATA_DIR / "ddb.duckdb"
WINDOWS = ["10:30", "14:30"]
DAY_IDX = [3, 9, 15]
WINDOW_SECONDS = 60
MAX_MID_GAP = 0.15


def sample_times(month: pd.Period) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    days = pd.bdate_range(month.start_time, month.end_time)
    out = []
    for i in DAY_IDX:
        if i < len(days):
            for w in WINDOWS:
                s = pd.Timestamp(f"{days[i].date()} {w}").tz_localize("America/New_York")
                out.append((s, s + pd.Timedelta(seconds=WINDOW_SECONDS)))
    return out


def spread_stats(quotes: pd.DataFrame) -> pd.DataFrame:
    """quotes: symbol, window, bp, ap -> per symbol: median spread (bps) across windows,
    quote count, windows seen, median midpoint."""
    q = quotes[(quotes["bp"] > 0) & (quotes["ap"] > quotes["bp"])].copy()
    q["mid"] = (q["ap"] + q["bp"]) / 2
    q["bps"] = (q["ap"] - q["bp"]) / q["mid"] * 1e4
    q = q[q["bps"] < 2000]
    w = q.groupby(["symbol", "window"]).agg(bps=("bps", "median"), n=("bps", "size"), mid=("mid", "median")).reset_index()
    return w.groupby("symbol").agg(spread_bps=("bps", "median"), n_quotes=("n", "sum"),
                                   windows=("window", "nunique"), mid=("mid", "median")).reset_index()


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


def fetch_safe(api: Alpaca, symbols: list[str], start, end, bad: set) -> pd.DataFrame:
    """fetch_quotes, splitting the batch when Alpaca rejects it (one unknown or malformed
    symbol fails the whole request); symbols rejected on their own are remembered in `bad`."""
    if not symbols:
        return pd.DataFrame(columns=["symbol", "bp", "ap"])
    try:
        return fetch_quotes(api, symbols, start, end)
    except Exception:  # noqa: BLE001
        if len(symbols) == 1:
            bad.add(symbols[0])
            return pd.DataFrame(columns=["symbol", "bp", "ap"])
        h = len(symbols) // 2
        return pd.concat([fetch_safe(api, symbols[:h], start, end, bad), fetch_safe(api, symbols[h:], start, end, bad)])


def month_symbols(con, month: pd.Period, sc: pd.DataFrame) -> pd.DataFrame:
    """cik -> the ticker it traded under at the end of `month`, for that month's liquid universe."""
    end = month.end_time.normalize()
    ciks = sc.loc[sc["d"].dt.to_period("M") == month, "cik"].astype(int).unique()
    if not len(ciks):
        return pd.DataFrame(columns=["cik", "symbol"])
    con.register("cc", pd.DataFrame({"cik": ciks}))
    t = con.execute(f"""
        SELECT cik, upper(ticker) AS symbol, source,
               CASE source WHEN 'xbrl_dei' THEN 0 WHEN 'alpaca_asset' THEN 1 WHEN 'sec_current' THEN 2 ELSE 3 END AS pri
        FROM tickers WHERE cik IN (SELECT cik FROM cc)
          AND coalesce(valid_from, DATE '1900-01-01') <= DATE '{end.date()}' + INTERVAL 400 DAY
          AND coalesce(valid_to, DATE '2100-01-01') >= DATE '{end.date()}' - INTERVAL 31 DAY""").df()
    con.unregister("cc")
    # current tickers have valid_from = the current name's start; earlier months may have used
    # another symbol: the midpoint check below rejects a symbol that wasn't this company's then
    return t.sort_values("pri").drop_duplicates("cik")[["cik", "symbol"]]


def closes(con, month: pd.Period) -> pd.DataFrame:
    """As-traded closes on the sampled days, keyed by (cik or symbol)."""
    days = [s.tz_convert("America/New_York").date() for s, _ in sample_times(month)][::len(WINDOWS)]
    if not days:
        return pd.DataFrame(columns=["cik", "symbol", "close_raw"])
    ds = ",".join(f"DATE '{d}'" for d in days)
    return con.execute(f"""
        WITH prim AS (SELECT cik, upper(current_tickers[1]) AS sym FROM companies WHERE len(current_tickers) > 0)
        SELECT coalesce(p.cik, prim.cik) AS cik, upper(p.symbol) AS symbol, median(p.close_raw) AS close_raw
        FROM prices p LEFT JOIN prim ON upper(p.symbol) = prim.sym
        WHERE p.date IN ({ds}) GROUP BY 1, 2""").df()


def build(start: str = "2016-01", end: str | None = None, batch: int = 50, db_path=DB_PATH) -> dict:
    t0 = time.time()
    api = Alpaca()
    OUT.mkdir(parents=True, exist_ok=True)
    sc = pd.read_parquet(SCORES, columns=["d", "cik"])
    sc["d"] = pd.to_datetime(sc["d"])
    etfs = sorted({t.upper() for g, v in universe_symbols().items() if g in ("haven", "benchmarks") for t in v})
    last = pd.Period(end, "M") if end else (pd.Timestamp.now() - pd.offsets.MonthEnd(1)).to_period("M")
    n_rows = n_rej = 0
    con = connect(db_path, read_only=True)
    for month in pd.period_range(start, last, freq="M"):
        f = OUT / f"{month.year}.parquet"
        old = pd.read_parquet(f) if f.exists() else pd.DataFrame(columns=["month"])
        if (pd.to_datetime(old["month"]) == month.end_time.normalize()).any():
            continue
        ms = month_symbols(con, month, sc)
        syms = sorted(set(ms["symbol"]) | set(etfs))
        parts = []
        bad: set[str] = set()
        for s, e in sample_times(month):
            for i in range(0, len(syms), batch):
                chunk = [x for x in syms[i:i + batch] if x not in bad]
                q = fetch_safe(api, chunk, s, e, bad)
                if len(q):
                    parts.append(q.assign(window=f"{s:%Y-%m-%d %H:%M}"))
        if not parts:
            continue
        st = spread_stats(pd.concat(parts))
        st = st.merge(ms, on="symbol", how="left")
        cl = closes(con, month)
        by_cik = cl.dropna(subset=["cik"]).groupby("cik")["close_raw"].median()
        by_sym = cl.groupby("symbol")["close_raw"].median()
        ref = pd.to_numeric(st["cik"].map(by_cik), errors="coerce").fillna(
            pd.to_numeric(st["symbol"].map(by_sym), errors="coerce")).to_numpy(float)
        gap = np.abs(st["mid"].to_numpy(float) / ref - 1)
        ok = np.isfinite(gap) & (gap <= MAX_MID_GAP)
        n_rej += int((~ok).sum())
        st = st[ok].copy()
        st["month"] = month.end_time.normalize()
        st["knowable_at"] = (month.end_time.normalize() + pd.Timedelta(days=1)).tz_localize("UTC")
        pd.concat([old, st], ignore_index=True).to_parquet(f, index=False)
        n_rows += len(st)
        print(f"  {month}: {len(st)} measured ({int((~ok).sum())} rejected by the price check), median "
              f"{st['spread_bps'].median():.1f} bp, {time.time() - t0:.0f}s", flush=True)
    con.close()
    return {"rows": n_rows, "rejected": n_rej, "seconds": round(time.time() - t0)}


def load_measured(key: str = "symbol", symbols_to_key: dict | None = None) -> pd.DataFrame:
    """Wide frame of HALF spreads in bps: index = first day each value may be used (the
    day after the measured month ends), columns = symbol, or cik as a string (key='cik';
    ETFs stay keyed by symbol)."""
    if not OUT.exists() or not any(OUT.glob("*.parquet")):
        return pd.DataFrame()
    df = pd.concat([pd.read_parquet(f) for f in OUT.glob("*.parquet")], ignore_index=True)
    df["use_from"] = pd.to_datetime(df["month"]) + pd.Timedelta(days=1)
    if key == "cik" and "cik" in df:
        df["k"] = np.where(df["cik"].notna(), df["cik"].map(lambda x: str(int(x)) if pd.notna(x) else None), df["symbol"])
    else:
        df["k"] = df["symbol"].map(symbols_to_key) if symbols_to_key else df["symbol"]
    df = df.dropna(subset=["k"])
    return df.pivot_table(index="use_from", columns="k", values="spread_bps", aggfunc="median").sort_index() / 2


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


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2016-01")
    ap.add_argument("--end")
    a = ap.parse_args()
    print(build(a.start, a.end))
