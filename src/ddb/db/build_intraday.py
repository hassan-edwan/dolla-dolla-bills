"""Download 1-minute bars from Alpaca (free account, SIP feed) for the intraday layer.

Which symbols (configs/short_term.yaml -> intraday):
- liquid companies in tracked industries: any month since `start` in the monthly
  signal universe (data/db/signals/scores.parquet) with 20-day dollar volume >=
  `min_dollar_volume_20d`, most liquid first, capped at `max_symbols`. Companies
  that later delisted are included (via their Alpaca symbol and only inside
  their own listing window), so tests don't suffer survivorship bias;
- plus the configured candidates, safe havens and benchmarks (configs/universe.yaml).

Storage: data/db/intraday/1Min/<SYMBOL>/<YEAR>.parquet, split-adjusted, regular
session only (09:30-16:00 New York). Columns: t (bar start, UTC), open, high, low,
close, volume, vwap, trades, knowable_at (bar end = t + 1 minute). Past years are
skipped when already downloaded, so the job can be stopped and resumed; the
current year is refreshed.

Volume: ~98k bars per symbol-year, 10k bars per request, 200 requests/minute on
the free plan: about 1 minute per symbol-year, so 600 symbols x 6 years is ~2.5 days.
Run it on a machine that stays on (or the HPC), e.g. with --max-symbols 100 first.

    python -m ddb.db.build_intraday [--max-symbols N] [--start 2019-01-01] [--symbols NVDA AMD]
"""
from __future__ import annotations

import argparse
import time

import pandas as pd

from ..config import DATA_DIR, load, universe_symbols
from ..data.alpaca import Alpaca
from .schema import connect

DB_PATH = DATA_DIR / "ddb.duckdb"
OUT = DATA_DIR / "db" / "intraday" / "1Min"
MANIFEST = DATA_DIR / "db" / "intraday" / "symbols.parquet"
SCORES = DATA_DIR / "db" / "signals" / "scores.parquet"


def regular_session(df: pd.DataFrame) -> pd.DataFrame:
    """Keep bars starting 09:30-15:59 New York time."""
    ny = df["t"].dt.tz_convert("America/New_York")
    mins = ny.dt.hour * 60 + ny.dt.minute
    return df[(mins >= 570) & (mins < 960)]


def pick_symbols(con, cfg: dict) -> pd.DataFrame:
    """symbol, cik, valid_from, valid_to, dollar_vol (median when liquid)."""
    start = pd.Timestamp(cfg["start"])
    rows = []
    if SCORES.exists():
        sc = pd.read_parquet(SCORES, columns=["d", "cik", "dollar_vol_20d"])
        sc = sc[(pd.to_datetime(sc["d"]) >= start) & (sc["dollar_vol_20d"] >= cfg["min_dollar_volume_20d"])]
        liq = sc.groupby("cik")["dollar_vol_20d"].median().sort_values(ascending=False)
        tick = con.execute("""
            SELECT cik, upper(current_tickers[1]) AS symbol, NULL::DATE AS valid_from, NULL::DATE AS valid_to, 0 AS pri
            FROM companies WHERE len(current_tickers) > 0
            UNION ALL
            SELECT cik, upper(ticker), valid_from, valid_to, 1 FROM tickers WHERE source = 'alpaca_asset'
        """).df().sort_values("pri").drop_duplicates("cik")
        m = tick[tick["cik"].isin(liq.index)].copy()
        m["dollar_vol"] = m["cik"].map(liq)
        rows.append(m.sort_values("dollar_vol", ascending=False).head(cfg["max_symbols"]))
    extra = sorted({s for v in universe_symbols().values() for s in v})
    rows.append(pd.DataFrame({"symbol": extra, "cik": pd.NA, "valid_from": pd.NaT, "valid_to": pd.NaT,
                              "dollar_vol": float("nan")}))
    out = pd.concat(rows, ignore_index=True).drop_duplicates("symbol")
    return out[["symbol", "cik", "valid_from", "valid_to", "dollar_vol"]].reset_index(drop=True)


def build(max_symbols: int | None = None, start: str | None = None, symbols: list[str] | None = None,
          db_path=DB_PATH) -> dict:
    cfg = dict(load("short_term")["intraday"])
    if max_symbols:
        cfg["max_symbols"] = max_symbols
    if start:
        cfg["start"] = start
    t0 = time.time()
    if symbols:
        pick = pd.DataFrame({"symbol": [s.upper() for s in symbols], "cik": pd.NA,
                             "valid_from": pd.NaT, "valid_to": pd.NaT, "dollar_vol": float("nan")})
    else:
        con = connect(db_path, read_only=True)
        pick = pick_symbols(con, cfg)
        con.close()
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    if MANIFEST.exists():   # keep earlier symbols in the manifest
        old = pd.read_parquet(MANIFEST)
        pick = pd.concat([pick, old[~old["symbol"].isin(pick["symbol"])]], ignore_index=True)
    pick.to_parquet(MANIFEST, index=False)

    api = Alpaca()
    this_year = pd.Timestamp.now(tz="UTC").year
    first_year = pd.Timestamp(cfg["start"]).year
    n_bars = n_files = 0
    todo = pick if not symbols else pick[pick["symbol"].isin([s.upper() for s in symbols])]
    for k, r in enumerate(todo.itertuples(index=False)):
        lo = max(first_year, pd.Timestamp(r.valid_from).year if pd.notna(r.valid_from) else first_year)
        hi = min(this_year, pd.Timestamp(r.valid_to).year if pd.notna(r.valid_to) else this_year)
        for y in range(lo, hi + 1):
            f = OUT / r.symbol / f"{y}.parquet"
            if f.exists() and y < this_year:
                continue
            s = max(pd.Timestamp(f"{y}-01-01"), pd.Timestamp(cfg["start"]),
                    pd.Timestamp(r.valid_from) if pd.notna(r.valid_from) else pd.Timestamp("1900-01-01"))
            e = pd.Timestamp(f"{y}-12-31 23:59")
            if pd.notna(r.valid_to):
                e = min(e, pd.Timestamp(r.valid_to) + pd.Timedelta(hours=23, minutes=59))
            # the free plan cannot query the most recent 15 minutes
            e = min(e.tz_localize("UTC"), pd.Timestamp.now(tz="UTC") - pd.Timedelta(minutes=16))
            try:
                df = api.bars([r.symbol], "1Min", s.tz_localize("UTC").isoformat(), e.isoformat(), adjustment="split")
            except Exception as exc:  # noqa: BLE001 - record and move on
                print(f"  {r.symbol} {y}: {exc}", flush=True)
                continue
            if df.empty:
                continue
            if cfg.get("regular_session_only", True):
                df = regular_session(df)
            df = df.drop(columns="symbol")
            df["knowable_at"] = df["t"] + pd.Timedelta(minutes=1)
            f.parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(f, index=False)
            n_bars += len(df)
            n_files += 1
        if k % 10 == 0:
            print(f"  {k + 1}/{len(todo)} symbols, {n_files} files, {n_bars:,} bars, {time.time() - t0:.0f}s", flush=True)
    return {"symbols": len(todo), "files": n_files, "bars": n_bars, "seconds": round(time.time() - t0)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-symbols", type=int)
    ap.add_argument("--start")
    ap.add_argument("--symbols", nargs="*")
    a = ap.parse_args()
    print(build(a.max_symbols, a.start, a.symbols))
