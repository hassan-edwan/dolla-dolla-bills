"""Prices for exchange-listed companies that failed, found through their own filings.

Survivorship is the main way price data lies: stocks that went to zero drop out of
free sources, so models learn that risky stocks always recover. Yahoo has no
delisted tickers, and Alpaca's delisted-asset list matches only some companies by
name (ddb.db.build_alpaca). This recovers more:

1. Companies in tracked industries that failed (bankrupt, delisted, deregistered)
   since `since`, were exchange-listed (they have a Form 25 / 25-NSE delisting
   notice), and still have no prices.
2. Their trading symbol, from the `dei:TradingSymbol` tag in the XBRL of their
   last annual or quarterly reports before the delisting.
3. Alpaca daily bars (free account, SIP, 2016+) for that symbol, both as traded
   and split-adjusted, kept only inside the company's own window: from 2 years
   before the filing that named the symbol (but not before its first filing) to
   5 days after the delisting notice. Exchanges reuse symbols after a company
   leaves, so nothing after that window is used.
4. Accepted only when the bars end within a year before the notice (stocks often
   stop trading on the exchange months earlier: OTC move, halt).

Writes data/db/prices/alpaca_dei__<SYMBOL>__<CIK>.parquet (source 'alpaca', with
cik) and dated rows in `tickers` (source 'xbrl_dei').

    python -m ddb.db.build_dead_prices [--since 2016-01-01] [--limit N]
"""
from __future__ import annotations

import argparse
import re
import time

import pandas as pd

from ..config import DATA_DIR
from ..data.alpaca import Alpaca
from ..data.http import RateLimitedSession, sec_user_agent
from .schema import connect

DB_PATH = DATA_DIR / "ddb.duckdb"
PRICE_DIR = DATA_DIR / "db" / "prices"
SYM = re.compile(r"<dei:TradingSymbol[^>]*>\s*([A-Za-z][A-Za-z.\-]{0,6})\s*<")


def targets(con, since: str) -> pd.DataFrame:
    return con.execute(f"""
        WITH gone AS (SELECT o.cik, max(o.exit_date) AS exit_date FROM outcomes o JOIN company_industries ci USING (cik)
                      WHERE o.outcome IN ('bankrupt', 'delisted_exchange', 'deregistered')
                        AND o.exit_date >= DATE '{since}' AND ci.confidence <> 'low' GROUP BY 1),
             listed AS (SELECT cik, max(filing_date) AS d25 FROM filings WHERE form IN ('25', '25-NSE') GROUP BY 1),
             priced AS (SELECT DISTINCT cik FROM prices WHERE cik IS NOT NULL
                        UNION SELECT DISTINCT t.cik FROM tickers t JOIN prices p ON upper(p.symbol) = upper(t.ticker))
        SELECT g.cik, g.exit_date, l.d25, c.first_filing, c.name
        FROM gone g JOIN listed l USING (cik) JOIN companies c USING (cik)
        WHERE g.cik NOT IN (SELECT cik FROM priced)
        ORDER BY g.cik""").df()


def trading_symbol(con, s: RateLimitedSession, cik: int, before) -> tuple[str | None, pd.Timestamp | None]:
    """dei:TradingSymbol from the latest periodic reports filed before `before`."""
    fl = con.execute(f"""SELECT accession, filing_date FROM filings WHERE cik = {int(cik)}
                         AND form IN ('10-K', '10-Q', '20-F', '10-K/A', '40-F') AND filing_date <= DATE '{pd.Timestamp(before).date()}'
                         ORDER BY filing_date DESC LIMIT 3""").fetchall()
    for acc, fdate in fl:
        base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/"
        try:
            items = s.get(base + "index.json").json()["directory"]["item"]
        except Exception:  # noqa: BLE001
            continue
        names = [i["name"] for i in items]
        inst = [n for n in names if n.endswith("_htm.xml")] or \
               [n for n in names if n.endswith(".xml") and not n.lower().startswith(("filingsummary", "metalink"))
                and not re.search(r"_(cal|def|lab|pre)\.xml$", n)]
        for n in inst[:2]:
            try:
                m = SYM.findall(s.get(base + n).text)
            except Exception:  # noqa: BLE001
                continue
            if m:
                return m[0].upper(), pd.Timestamp(fdate)
    return None, None


def build(since: str = "2016-01-01", limit: int | None = None, db_path=DB_PATH) -> dict:
    t0 = time.time()
    con = connect(db_path, read_only=True)
    tg = targets(con, since)
    if limit:
        tg = tg.head(limit)
    s = RateLimitedSession(min_interval_s=0.12, user_agent=sec_user_agent(), retries=3)
    api = Alpaca()
    PRICE_DIR.mkdir(parents=True, exist_ok=True)
    found = accepted = bars_n = 0
    tick_rows, rejected = [], []
    for k, r in enumerate(tg.itertuples(index=False)):
        end = pd.Timestamp(r.d25)
        sym, sym_date = trading_symbol(con, s, r.cik, end)
        if not sym:
            continue
        found += 1
        start = max(pd.Timestamp(r.first_filing) if pd.notna(r.first_filing) else pd.Timestamp("2016-01-01"),
                    sym_date - pd.Timedelta(days=730), pd.Timestamp("2016-01-01"))
        stop = end + pd.Timedelta(days=5)
        try:
            raw = api.daily_bars([sym], str(start.date()), str(stop.date()), adjustment="raw")
            adj = api.daily_bars([sym], str(start.date()), str(stop.date()), adjustment="split")
        except Exception as exc:  # noqa: BLE001
            rejected.append((r.cik, sym, f"error {exc}"[:80]))
            continue
        if raw.empty or adj.empty:
            rejected.append((r.cik, sym, "no bars"))
            continue
        last = raw["date"].max()
        if last < end - pd.Timedelta(days=365):
            rejected.append((r.cik, sym, f"bars end {last.date()}, notice {end.date()}"))
            continue
        d = adj.merge(raw[["date", "close", "volume"]].rename(columns={"close": "close_raw", "volume": "volume_raw"}), on="date")
        d = d[(d["date"] >= start) & (d["date"] <= stop)]
        d["symbol"], d["cik"], d["adjclose"], d["source"] = sym, int(r.cik), float("nan"), "alpaca"
        d["knowable_at"] = (d["date"] + pd.Timedelta(hours=21)).dt.tz_localize("UTC")
        cols = ["symbol", "date", "open", "high", "low", "close", "adjclose", "volume", "close_raw", "volume_raw",
                "source", "knowable_at", "cik", "vwap"]
        d[cols].to_parquet(PRICE_DIR / f"alpaca_dei__{sym}__{int(r.cik)}.parquet", index=False)
        accepted += 1
        bars_n += len(d)
        tick_rows.append({"cik": int(r.cik), "ticker": sym, "exchange": None, "valid_from": d["date"].min().date(),
                          "valid_to": d["date"].max().date(), "source": "xbrl_dei", "knowable_at": d["knowable_at"].min()})
        if k % 25 == 0:
            print(f"  {k + 1}/{len(tg)}: symbols {found}, priced {accepted}, {bars_n:,} bars, {time.time() - t0:.0f}s", flush=True)
    con.close()
    con = connect(db_path)
    con.execute("DELETE FROM tickers WHERE source = 'xbrl_dei'")
    if tick_rows:
        t = pd.DataFrame(tick_rows)
        con.register("t", t)
        con.execute("INSERT INTO tickers (cik, ticker, exchange, valid_from, valid_to, source, knowable_at) "
                    "SELECT cik, ticker, exchange, valid_from, valid_to, source, knowable_at FROM t")
    con.close()
    return {"targets": len(tg), "symbols_found": found, "priced": accepted, "bars": bars_n,
            "rejected": len(rejected), "rejected_sample": rejected[:8], "seconds": round(time.time() - t0)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2016-01-01")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    print(build(a.since, a.limit))
