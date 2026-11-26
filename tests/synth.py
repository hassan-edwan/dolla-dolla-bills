"""A small synthetic database with the real schema, for end-to-end tests of the
signal pipelines and the dashboard queries (no network, no real data).

Planted effects, so tests can check the pipelines find them:
- each company has a slow-moving drift (monthly momentum works);
- daily returns partly reverse the next day (1-day reversal works);
- a fifth of companies file an offering every ~4 months and drop ~6% over the next week.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ddb.db.schema import connect

INDUSTRIES = ["tech", "energy", "nuclear", "quantum"]


def make_db(root: Path, n: int = 60, start: str = "2016-01-04", end: str = "2020-12-31", seed: int = 3) -> Path:
    rng = np.random.default_rng(seed)
    root = Path(root)
    (root / "db").mkdir(parents=True, exist_ok=True)
    days = pd.bdate_range(start, end)
    T = len(days)
    ciks = np.arange(1001, 1001 + n)
    syms = [f"S{c}" for c in ciks]
    ind = [INDUSTRIES[i % len(INDUSTRIES)] for i in range(n)]

    # ---- prices
    drift = np.zeros((T, n))
    d = rng.normal(0, 0.0012, n)
    for t in range(T):
        if t % 63 == 0:
            d = 0.7 * d + rng.normal(0, 0.0008, n)
        drift[t] = d
    mkt = rng.normal(0.0003, 0.01, T)
    eps = rng.normal(0, 0.022, (T, n))
    r = drift + mkt[:, None] + eps
    r[1:] -= 0.12 * eps[:-1]                       # next-day reversal
    offer_days = {}
    for j in range(0, n, 5):
        for t0 in range(40, T - 10, 84):
            offer_days.setdefault(j, []).append(t0)
            r[t0 + 1:t0 + 6, j] -= 0.012
    c = 30 * np.exp(np.cumsum(r, axis=0))
    o = c * np.exp(rng.normal(0, 0.004, (T, n)))
    o[1:] = c[:-1] * np.exp(0.3 * (np.log(c[1:] / c[:-1])) + rng.normal(0, 0.003, (T - 1, n)))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.008, (T, n))))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.008, (T, n))))
    vol = rng.lognormal(13.5, 0.4, (T, n)) * (1 + 3 * (np.abs(eps) > 0.04))
    px = []
    for j, s in enumerate(syms):
        px.append(pd.DataFrame({
            "symbol": s, "date": days.date, "open": o[:, j], "high": h[:, j], "low": lo[:, j], "close": c[:, j],
            "adjclose": c[:, j], "volume": vol[:, j], "close_raw": c[:, j], "volume_raw": vol[:, j],
            "source": "yahoo", "knowable_at": (days + pd.Timedelta(hours=21)).tz_localize("UTC"), "cik": np.nan,
            "vwap": np.nan}))
    (root / "db" / "prices").mkdir(exist_ok=True)
    pd.concat(px).to_parquet(root / "db" / "prices" / "yahoo.parquet", index=False)

    # ---- fundamentals (first-published values; quarterly instants, annual flows)
    rows = []
    q_ends = pd.date_range(pd.Timestamp(start) - pd.DateOffset(years=2), end, freq="QE")
    for j, cik in enumerate(ciks):
        assets = rng.uniform(2e8, 5e9)
        shares = rng.uniform(5e7, 4e8)
        gp_margin, ocf_m = rng.uniform(0.1, 0.6), rng.uniform(-0.3, 0.3)
        for pe in q_ends:
            k = (pe + pd.Timedelta(days=45)).tz_localize("UTC")
            assets *= np.exp(rng.normal(0.01, 0.03))
            shares *= 1.03 if j % 5 == 0 else 1.0
            for concept, val, unit in (("Assets", assets, "USD"), ("StockholdersEquity", assets * 0.5, "USD"),
                                       ("CashAndCashEquivalentsAtCarryingValue", assets * 0.1, "USD"),
                                       ("EntityCommonStockSharesOutstanding", shares, "shares")):
                rows.append((cik, concept, unit, None, pe, val, k, "Q", "10-Q"))
            eps = rng.normal(0.2, 0.3)
            rows.append((cik, "EarningsPerShareDiluted", "USD/shares", (pe - pd.DateOffset(months=3) + pd.Timedelta(days=1)),
                         pe, eps, k, "Q", "10-Q"))
            if pe.month == 12:
                ps = pe - pd.DateOffset(years=1) + pd.Timedelta(days=1)
                rev = assets * 0.4
                for concept, val in (("Revenues", rev), ("GrossProfit", rev * gp_margin),
                                     ("NetIncomeLoss", rev * ocf_m * 0.8),
                                     ("NetCashProvidedByUsedInOperatingActivities", rev * ocf_m)):
                    rows.append((cik, concept, "USD", ps, pe, val, k + pd.Timedelta(days=30), "FY", "10-K"))
    f = pd.DataFrame(rows, columns=["cik", "concept", "unit", "period_start", "period_end", "value",
                                    "knowable_at", "fp", "form"])
    f["period_start"] = pd.to_datetime(f["period_start"]).dt.date
    f["period_end"] = pd.to_datetime(f["period_end"]).dt.date
    (root / "db" / "fundamentals").mkdir(exist_ok=True)
    f.to_parquet(root / "db" / "fundamentals" / "f.parquet", index=False)

    # ---- insiders, news (feature tables as Parquet views)
    it = []
    for j, cik in enumerate(ciks):
        for t in rng.choice(T - 5, 6, replace=False):
            it.append({"cik": cik, "owner_cik": int(cik * 10 + rng.integers(3)), "owner_name": "Insider",
                       "title": "Director", "relationship": "director", "trans_date": days[t].date(),
                       "knowable_at": (days[t + 2] + pd.Timedelta(hours=20)).tz_localize("UTC"),
                       "trans_code": "P" if rng.random() < 0.4 else "S", "shares": float(rng.integers(1e3, 5e4)),
                       "price": float(c[t, j]), "is_10b5_1_plan": False, "is_derivative": False,
                       "trans_date_suspect": False, "filing_lag_days": 2})
    (root / "db" / "insider_transactions").mkdir(exist_ok=True)
    pd.DataFrame(it).to_parquet(root / "db" / "insider_transactions" / "i.parquet", index=False)
    nw = []
    for t in range(T - 400, T):
        for j in rng.choice(n, 4, replace=False):
            nw.append({"ciks": [int(ciks[j])], "tone": float(rng.normal(0, 3)), "signals": ["development"],
                       "published": days[t], "source": "example.com", "url": "https://example.com",
                       "knowable_at": (days[t] + pd.Timedelta(hours=15)).tz_localize("UTC")})
    (root / "db" / "news_events").mkdir(exist_ok=True)
    pd.DataFrame(nw).to_parquet(root / "db" / "news_events" / "n.parquet", index=False)

    con = connect(root / "ddb.duckdb")
    comp = pd.DataFrame({"cik": ciks, "name": [f"Synthetic {s} Corp" for s in syms], "sic": 3674,
                         "current_tickers": [[s] for s in syms], "is_current_listed": True,
                         "first_filing": pd.Timestamp("2010-01-01").date(), "last_filing": days[-1].date(),
                         "n_filings": 40})
    con.register("comp", comp)
    con.execute("INSERT INTO companies (cik, name, sic, current_tickers, is_current_listed, first_filing, last_filing, n_filings) "
                "SELECT cik, name, sic, current_tickers, is_current_listed, first_filing, last_filing, n_filings FROM comp")
    con.execute("INSERT INTO company_names (cik, name, valid_from, knowable_at) "
                "SELECT cik, name, DATE '2010-01-01', TIMESTAMPTZ '2010-01-01 00:00:00+00' FROM comp")
    ci = pd.DataFrame({"cik": ciks, "industry": ind})
    con.register("ci", ci)
    con.execute("""INSERT INTO company_industries SELECT cik, industry, 'synthetic', 'sic', '3674', 'high',
                   DATE '2010-01-01', NULL, TIMESTAMPTZ '2010-01-01 00:00:00+00' FROM ci""")
    fl, ev = [], []
    for j, cik in enumerate(ciks):
        for t in range(10, T, 63):           # quarterly report + results 8-K
            k = (days[t] + pd.Timedelta(hours=21, minutes=10)).tz_localize("UTC")
            fl.append((cik, f"q{cik}-{t}", "10-Q", days[t].date(), None, k, None, k))
            fl.append((cik, f"e{cik}-{t}", "8-K", days[t].date(), None, k, "2.02,9.01", k))
        for t0 in offer_days.get(j, []):
            k = (days[t0] + pd.Timedelta(hours=20)).tz_localize("UTC")
            ev.append((cik, "offering_prospectus", days[t0].date(), "424B5", f"o{cik}-{t0}", k))
    fl = pd.DataFrame(fl, columns=["cik", "accession", "form", "filing_date", "report_date", "acceptance", "items", "knowable_at"])
    con.register("fl", fl)
    con.execute("INSERT INTO filings (cik, accession, form, filing_date, report_date, acceptance, items, knowable_at) SELECT * FROM fl")
    ev = pd.DataFrame(ev, columns=["cik", "event_type", "event_date", "form", "accession", "knowable_at"])
    con.register("ev", ev)
    con.execute("INSERT INTO events SELECT * FROM ev")
    con.execute("""CREATE TABLE screen_static AS SELECT cik, 'israel' AS screen,
                   CASE WHEN cik % 17 = 0 THEN 'fail' ELSE 'pass' END AS status, '' AS reasons,
                   TIMESTAMPTZ '2010-01-01 00:00:00+00' AS knowable_at FROM ci""")
    con.execute("""CREATE TABLE screen_sharia_financial AS SELECT cik, DATE '2015-12-31' AS as_of, 1e9 AS market_cap_avg,
                   1e8 AS debt, 1e8 AS cash_securities, 1e6 AS interest_income, 1e8 AS revenue, 0.1 AS debt_ratio,
                   0.1 AS cash_ratio, 0.01 AS impermissible_share, 'pass' AS status,
                   TIMESTAMPTZ '2016-01-01 00:00:00+00' AS knowable_at FROM ci""")
    con.execute("CREATE TABLE IF NOT EXISTS filing_text_signals (cik BIGINT, phrase VARCHAR, signal VARCHAR, "
                "file_date DATE, form VARCHAR, accession VARCHAR, document VARCHAR, knowable_at TIMESTAMPTZ)")
    con.execute("CREATE TABLE IF NOT EXISTS politician_trades (ticker VARCHAR, transaction_type VARCHAR, knowable_at TIMESTAMPTZ)")
    con.execute("CREATE TABLE IF NOT EXISTS gov_contracts (cik BIGINT, amount DOUBLE, agency VARCHAR, knowable_at TIMESTAMPTZ)")
    con.close()
    return root / "ddb.duckdb"
