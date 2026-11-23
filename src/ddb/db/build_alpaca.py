"""Recover delisted companies' tickers and prices from Alpaca (free, 2016+).

1. Match Alpaca's inactive (delisted) securities to companies in the database
   that are no longer listed, by normalized name (all historical names).
2. Fetch daily bars per matched symbol, both as-traded ('raw') and
   split-adjusted, kept only inside the company's own filing window (symbols get
   reused by later companies).
3. Write per-symbol Parquet into data/db/prices (source='alpaca', with cik), and
   dated tickers (source='alpaca_asset').

    python -m ddb.db.build_alpaca
"""
from __future__ import annotations

import re
import time

import pandas as pd

from ..config import DATA_DIR
from ..data.alpaca import Alpaca
from .research import norm_name
from .schema import connect

DB_PATH = DATA_DIR / "ddb.duckdb"
PRICE_DIR = DATA_DIR / "db" / "prices"
ASSETS = DATA_DIR / "db" / "alpaca_assets.parquet"
NON_COMMON = re.compile(r"\b(?:unit|units|warrant|warrants|right|rights|preferred|notes|debentures?|"
                        r"depositary receipt|due \d{4})\b|%", re.I)
SHARE_WORDS = re.compile(r"\b(?:common stock|class [a-c]|ordinary shares?|american depositary shares?|ads|"
                         r"shares of beneficial interest|common shares?|capital stock|new)\b", re.I)


def match_dead(con, assets: pd.DataFrame) -> pd.DataFrame:
    a = assets[(assets["status"] == "inactive") & ~assets["name"].fillna("").str.contains(NON_COMMON)].copy()
    a["n"] = a["name"].fillna("").str.replace(SHARE_WORDS, " ", regex=True).map(norm_name)
    a = a[a["n"].str.len() >= 4]
    names = con.execute("""SELECT n.cik, n.name, c.first_filing, c.last_filing
                           FROM company_names n JOIN companies c USING (cik)
                           WHERE NOT c.is_current_listed""").df()
    names["n"] = names["name"].map(norm_name)
    names = names[names["n"].str.len() >= 4]
    # a normalized name must identify exactly one company
    uniq = names.groupby("n")["cik"].nunique()
    names = names[names["n"].isin(uniq[uniq == 1].index)]
    m = a.merge(names, on="n")[["cik", "symbol", "exchange", "name_x", "first_filing", "last_filing"]]
    per_sym = m.groupby("symbol")["cik"].nunique()
    m = m[m["symbol"].isin(per_sym[per_sym == 1].index)].drop_duplicates(["cik", "symbol"])
    return m.rename(columns={"name_x": "alpaca_name"})


def build(db_path=DB_PATH, batch: int = 40) -> dict:
    t0 = time.time()
    api = Alpaca()
    assets = api.assets()
    assets.to_parquet(ASSETS, index=False)
    con = connect(db_path)
    m = match_dead(con, assets)
    con.close()
    PRICE_DIR.mkdir(parents=True, exist_ok=True)
    m["query_symbol"] = m["symbol"].str.replace("_DELISTED", "", regex=False)
    windows = {r.symbol: r for r in m.itertuples(index=False)}
    syms = sorted(windows)
    tick_rows, n_bars, with_data = [], 0, 0
    for i in range(0, len(syms), batch):
        chunk = syms[i:i + batch]
        q = [windows[s].query_symbol for s in chunk]
        raw = api.daily_bars(q, "2016-01-01", adjustment="raw")
        adj = api.daily_bars(q, "2016-01-01", adjustment="split")
        if raw.empty:
            continue
        df = raw.merge(adj[["symbol", "date", "open", "high", "low", "close", "volume"]],
                       on=["symbol", "date"], suffixes=("_raw", ""))
        for s in chunk:
            w = windows[s]
            lo = pd.Timestamp(w.first_filing) - pd.Timedelta(days=30)
            hi = pd.Timestamp(w.last_filing) + pd.Timedelta(days=180)
            d = df[(df["symbol"] == w.query_symbol) & (df["date"] >= lo) & (df["date"] <= hi)].copy()
            if d.empty:
                continue
            d["symbol"] = w.query_symbol
            d["cik"] = int(w.cik)
            d["adjclose"] = float("nan")
            d["source"] = "alpaca"
            d["knowable_at"] = (d["date"] + pd.Timedelta(hours=21)).dt.tz_localize("UTC")
            cols = ["symbol", "date", "open", "high", "low", "close", "adjclose", "volume",
                    "close_raw", "volume_raw", "source", "knowable_at", "cik", "vwap"]
            d[cols].to_parquet(PRICE_DIR / f"alpaca__{s}__{int(w.cik)}.parquet", index=False)
            n_bars += len(d)
            with_data += 1
            tick_rows.append({"cik": int(w.cik), "ticker": w.query_symbol, "exchange": w.exchange,
                              "valid_from": d["date"].min(), "valid_to": d["date"].max(),
                              "source": "alpaca_asset", "knowable_at": d["knowable_at"].min()})
        print(f"  {min(i + batch, len(syms))}/{len(syms)} symbols, {with_data} with bars, "
              f"{n_bars:,} bars, {time.time() - t0:.0f}s", flush=True)
    con = connect(db_path)
    con.execute("DELETE FROM tickers WHERE source = 'alpaca_asset'")
    if tick_rows:
        t = pd.DataFrame(tick_rows)
        con.register("t", t)
        con.execute("INSERT INTO tickers (cik, ticker, exchange, valid_from, valid_to, source, knowable_at) "
                    "SELECT cik, ticker, exchange, valid_from, valid_to, source, knowable_at FROM t")
        con.unregister("t")
    con.close()
    return {"matched_symbols": len(syms), "matched_companies": int(m["cik"].nunique()),
            "symbols_with_bars": with_data, "bars": n_bars, "seconds": round(time.time() - t0)}


if __name__ == "__main__":
    print(build())
