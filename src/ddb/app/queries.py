"""Read-only queries behind the dashboard. Every function returns plain JSON-able data.

Point-in-time contract with the frontend: every row or bucket carries `k`, the
moment it became public (ISO timestamp). The dashboard's "as of" control hides
anything with k > as-of, so the same data serves both the live app and the
static snapshot, and the view always matches what a model could have known.

Outcome labels (how a listing ended) are hindsight. They are returned
separately as `labels` and only shown when the user switches hindsight on.
"""
from __future__ import annotations

import math

import pandas as pd
import yaml

from ..config import CONFIG_DIR

INDUSTRY_ARXIV = {"quantum": ["quantum"], "tech": ["ai", "semiconductors"], "robotics_ai": ["robotics", "ai"],
                  "ev_battery": ["batteries"], "nuclear": ["nuclear_fission", "fusion"], "energy": ["solar"],
                  "space": ["space"], "crypto_adj": ["crypto"], "gene_biotech": []}


def _records(df: pd.DataFrame) -> list[dict]:
    out = []
    for r in df.to_dict(orient="records"):
        for k, v in r.items():
            if v is None or (not hasattr(v, "__len__") and pd.isna(v)):
                r[k] = None
                continue
            if isinstance(v, pd.Timestamp):
                r[k] = None if pd.isna(v) else v.isoformat()
            elif hasattr(v, "isoformat") and not isinstance(v, str):
                r[k] = v.isoformat()
            elif isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                r[k] = None
            elif hasattr(v, "tolist"):
                r[k] = v.tolist()
        out.append(r)
    return out


def _q(con, sql: str, params=None) -> pd.DataFrame:
    try:
        return con.execute(sql, params or []).df()
    except Exception:  # noqa: BLE001 - a table may not be loaded yet
        return pd.DataFrame()


def _has(con, table: str) -> bool:
    return bool(con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [table]).fetchone()[0])


# ------------------------------------------------------------------ overview
SOURCES = [
    ("companies", "Companies (incl. failed/delisted)", None, "SEC EDGAR"),
    ("filings", "SEC filings", "knowable_at", "SEC EDGAR"),
    ("events", "Filing events (distress, dilution, M&A)", "knowable_at", "SEC EDGAR"),
    ("fundamentals", "Financial facts (every version)", "knowable_at", "SEC XBRL"),
    ("prices", "Daily price bars", "knowable_at", "Yahoo, Alpaca"),
    ("insider_transactions", "Insider trades (Forms 3/4/5)", "knowable_at", "SEC"),
    ("politician_trades", "Congressional trades", "knowable_at", "House Clerk, Senate eFD"),
    ("committee_seats", "Committee seats", "knowable_at", "congress-legislators"),
    ("gov_contracts", "Federal contract transactions", "knowable_at", "USAspending"),
    ("regulatory_documents", "Federal Register documents", "knowable_at", "Federal Register"),
    ("news_events", "News articles (filtered)", "knowable_at", "GDELT"),
    ("filing_text_signals", "Bottleneck/development/stagnation phrases in filings", "knowable_at", "EDGAR full-text search"),
    ("wiki_pageviews", "Wikipedia daily views", "knowable_at", "Wikimedia"),
    ("research_velocity", "arXiv papers per month", "knowable_at", "arXiv"),
    ("macro", "Market/macro series", "knowable_at", "FRED"),
    ("outcomes", "Outcome labels (hindsight)", None, "filings + research"),
]


def overview(con) -> dict:
    rows = []
    for table, label, kcol, src in SOURCES:
        if not _has(con, table):
            rows.append({"table": table, "label": label, "source": src, "rows": 0, "first": None, "last": None})
            continue
        sel = f"count(*) AS n" + (f", min({kcol}) AS first, max({kcol}) AS last" if kcol else "")
        df = _q(con, f"SELECT {sel} FROM {table}")
        r = df.iloc[0].to_dict() if len(df) else {"n": 0}
        rows.append({"table": table, "label": label, "source": src, "rows": int(r.get("n") or 0),
                     "first": str(r.get("first"))[:10] if r.get("first") is not None else None,
                     "last": str(r.get("last"))[:10] if r.get("last") is not None else None})
    return {"sources": rows}


# ------------------------------------------------------------------ universe over time
def universe_series(con) -> dict:
    df = _q(con, """
        WITH months AS (
            SELECT CAST(last_day(m) AS DATE) AS d
            FROM generate_series(TIMESTAMP '2010-01-01', CAST(current_date AS TIMESTAMP), INTERVAL 1 MONTH) g(m)
        ),
        fm AS (SELECT DISTINCT cik, CAST(date_trunc('month', filing_date) AS DATE) AS m FROM filings),
        tagged AS (
            SELECT DISTINCT mo.d, ci.industry, ci.cik
            FROM months mo JOIN company_industries ci
              ON ci.valid_from <= mo.d AND (ci.valid_to IS NULL OR ci.valid_to > mo.d)
             AND ci.confidence <> 'low'          -- name-keyword-only guesses don't define membership
        ),
        act AS (
            SELECT t.* FROM tagged t
            WHERE EXISTS (SELECT 1 FROM fm WHERE fm.cik = t.cik AND fm.m > t.d - INTERVAL 18 MONTH AND fm.m <= t.d)
        ),
        st AS (SELECT cik, bool_and(status = 'pass') AS ok FROM screen_static GROUP BY 1),
        fin AS (SELECT cik, as_of, status FROM screen_sharia_financial),
        joined AS (
            SELECT a.d, a.industry, a.cik, COALESCE(st.ok, TRUE) AS static_ok, f.status AS fin_status
            FROM act a LEFT JOIN st USING (cik)
            ASOF LEFT JOIN fin f ON f.cik = a.cik AND a.d >= f.as_of
        )
        SELECT d, industry, count(DISTINCT cik) AS active,
               count(DISTINCT CASE WHEN static_ok AND fin_status = 'pass' THEN cik END) AS tradable
        FROM joined GROUP BY 1, 2 ORDER BY 1, 2
    """)
    out = {}
    for ind, g in df.groupby("industry"):
        out[ind] = [{"d": str(r.d)[:10], "k": str(r.d)[:10] + "T23:59:59+00:00",
                     "active": int(r.active), "tradable": int(r.tradable)} for r in g.itertuples()]
    return out


# ------------------------------------------------------------------ screens
def screens(con) -> dict:
    counts = _q(con, """SELECT screen, status, count(*) AS n FROM screen_static
                        WHERE cik IN (SELECT cik FROM companies WHERE is_current_listed) GROUP BY 1, 2""")
    fin_now = _q(con, """
        SELECT status, count(*) AS n FROM (
            SELECT f.status FROM screen_sharia_financial f JOIN companies c USING (cik)
            WHERE c.is_current_listed
            QUALIFY row_number() OVER (PARTITION BY f.cik ORDER BY f.as_of DESC) = 1) GROUP BY 1""")
    excluded = _q(con, """
        SELECT s.cik, c.name, c.current_tickers[1] AS ticker, s.screen, s.status, s.reasons,
               string_agg(DISTINCT ci.industry, ', ') AS industries
        FROM screen_static s JOIN companies c USING (cik)
        LEFT JOIN company_industries ci ON ci.cik = s.cik
        WHERE s.status <> 'pass' AND c.is_current_listed
        GROUP BY 1, 2, 3, 4, 5, 6 ORDER BY s.screen, c.name
    """)
    monitored = _q(con, """SELECT m.cik, any_value(c.name) AS name, any_value(c.current_tickers[1]) AS ticker,
                                  string_agg(DISTINCT m.reasons, '; ') AS reasons
                           FROM monitored_companies m JOIN companies c USING (cik) GROUP BY 1 ORDER BY 2""")
    cfg = yaml.safe_load((CONFIG_DIR / "screens.yaml").read_text())
    return {"counts": _records(counts), "financial_now": _records(fin_now), "excluded": _records(excluded),
            "monitored": _records(monitored), "thresholds": cfg["sharia_financial"], "decisions": cfg.get("decisions", {})}


# ------------------------------------------------------------------ search
def search(con, q: str, limit: int = 25) -> list[dict]:
    q = (q or "").strip()
    if not q:
        return []
    df = _q(con, """
        SELECT c.cik, c.name, c.current_tickers[1] AS ticker, c.is_current_listed AS listed,
               c.last_filing, string_agg(DISTINCT ci.industry, ', ') AS industries
        FROM companies c LEFT JOIN company_industries ci USING (cik)
        WHERE c.name ILIKE ? OR list_contains(c.current_tickers, upper(?))
           OR c.cik IN (SELECT cik FROM tickers WHERE upper(ticker) = upper(?))
        GROUP BY 1, 2, 3, 4, 5
        ORDER BY (upper(c.current_tickers[1]) = upper(?)) DESC, c.is_current_listed DESC, c.last_filing DESC
        LIMIT ?""", [f"%{q}%", q, q, q, limit])
    return _records(df)


# ------------------------------------------------------------------ company
def company(con, cik: int) -> dict:
    cik = int(cik)
    prof = _q(con, "SELECT * FROM companies WHERE cik = ?", [cik])
    if prof.empty:
        return {}
    p = _records(prof)[0]
    tickers = p.get("current_tickers") or []
    primary = (tickers[0] if tickers else None)
    research_t = _q(con, "SELECT DISTINCT upper(ticker) AS t FROM tickers WHERE cik = ? AND source IN ('research', 'alpaca_asset')", [cik])
    syms = [primary] if primary else list(research_t["t"]) if len(research_t) else []
    out = {"profile": p, "primary_ticker": primary}
    out["names"] = _records(_q(con, "SELECT name, valid_from, valid_to, knowable_at AS k FROM company_names WHERE cik = ? ORDER BY valid_from", [cik]))
    out["industries"] = _records(_q(con, """SELECT industry, sub_industry, method, matched, confidence, valid_from, valid_to,
                                            knowable_at AS k FROM company_industries WHERE cik = ? ORDER BY valid_from""", [cik]))
    out["screens"] = _records(_q(con, "SELECT screen, status, reasons, knowable_at AS k FROM screen_static WHERE cik = ?", [cik]))
    out["sharia"] = _records(_q(con, """SELECT as_of, market_cap_avg, debt, cash_securities, interest_income, revenue,
                                        debt_ratio, cash_ratio, impermissible_share, status, knowable_at AS k
                                        FROM screen_sharia_financial WHERE cik = ? ORDER BY as_of""", [cik]))
    if syms:
        ph = ",".join("?" * len(syms))
        out["prices"] = _records(_q(con, f"""
            SELECT date_trunc('week', date) AS w, arg_max(close, date) AS close, arg_max(close_raw, date) AS close_raw,
                   sum(volume_raw * close_raw) / count(*) AS dollar_vol, max(knowable_at) AS k
            FROM prices WHERE (upper(symbol) IN ({ph}) AND (cik IS NULL OR cik = ?)) GROUP BY 1 ORDER BY 1""", syms + [cik]))
    else:
        out["prices"] = []
    out["events"] = _records(_q(con, """SELECT event_type, event_date, form, accession, knowable_at AS k FROM events
                                        WHERE cik = ? ORDER BY knowable_at DESC LIMIT 600""", [cik]))
    out["insider"] = _records(_q(con, """
        SELECT trans_date, knowable_at AS k, owner_name, coalesce(title, relationship) AS role, trans_code,
               shares, price, shares * price AS value, filing_lag_days, is_10b5_1_plan
        FROM insider_transactions WHERE cik = ? AND NOT is_derivative AND trans_code IN ('P', 'S')
          AND NOT trans_date_suspect AND coalesce(shares * price, 0) < 2e9   -- larger = filer typo
        ORDER BY knowable_at DESC LIMIT 1500""", [cik]))
    tick_all = list(set(tickers) | set(research_t["t"]) if len(research_t) else set(tickers))
    if tick_all and _has(con, "politician_trades"):
        ph = ",".join("?" * len(tick_all))
        out["politicians"] = _records(_q(con, f"""
            SELECT member, chamber, transaction_type, trans_date, amount_min, amount_max, filing_date,
                   disclosure_lag_days, knowable_at AS k, source_url, ticker
            FROM politician_trades WHERE upper(ticker) IN ({ph}) ORDER BY knowable_at DESC""", [t.upper() for t in tick_all]))
    else:
        out["politicians"] = []
    out["contracts"] = _records(_q(con, """
        SELECT date_trunc('quarter', knowable_at) AS q, agency ILIKE '%Department of Defense%' AS dod,
               sum(amount) AS amount, count(*) AS n, max(knowable_at) AS k
        FROM gov_contracts WHERE cik = ? GROUP BY 1, 2 ORDER BY 1""", [cik]))
    out["news_weekly"] = _records(_q(con, """
        SELECT date_trunc('week', knowable_at) AS w, count(*) AS n, avg(tone) AS tone,
               sum(list_contains(signals, 'bottleneck')::INT) AS bottleneck,
               sum(list_contains(signals, 'development')::INT) AS development,
               sum(list_contains(signals, 'stagnation')::INT) AS stagnation, max(knowable_at) AS k
        FROM news_events WHERE list_contains(ciks, ?) GROUP BY 1 ORDER BY 1""", [cik]))
    out["headlines"] = _records(_q(con, """
        SELECT published, source, url, tone, signals, knowable_at AS k FROM news_events
        WHERE list_contains(ciks, ?) ORDER BY knowable_at DESC LIMIT 60""", [cik]))
    out["wiki"] = _records(_q(con, """
        SELECT date_trunc('week', date) AS w, sum(views) AS views, max(knowable_at) AS k
        FROM wiki_pageviews WHERE cik = ? GROUP BY 1 ORDER BY 1""", [cik]))
    out["filing_signals"] = _records(_q(con, """
        SELECT file_date, form, signal, phrase, accession, document, knowable_at AS k
        FROM filing_text_signals WHERE cik = ? ORDER BY knowable_at DESC LIMIT 400""", [cik]))
    out["signals"] = company_signals(con, cik)
    out["labels"] = _records(_q(con, """SELECT outcome, exit_date, method, confidence, consideration, source_url,
                                        event_known_at AS k FROM outcomes WHERE cik = ?""", [cik]))
    return out


# ------------------------------------------------------------------ industry
def industry(con, ind: str, uni: dict | None = None) -> dict:
    out = {"industry": ind}
    out["universe"] = (uni or universe_series(con)).get(ind, [])
    members = f"SELECT DISTINCT cik FROM company_industries WHERE industry = '{ind}'"
    out["filing_signals"] = _records(_q(con, f"""
        SELECT date_trunc('quarter', f.knowable_at) AS q, f.signal, count(DISTINCT f.accession) AS n, max(f.knowable_at) AS k
        FROM filing_text_signals f JOIN company_industries ci
          ON ci.cik = f.cik AND ci.industry = '{ind}' AND ci.valid_from <= f.file_date
         AND (ci.valid_to IS NULL OR ci.valid_to > f.file_date)
        GROUP BY 1, 2 ORDER BY 1"""))
    out["news_signals"] = _records(_q(con, f"""
        SELECT date_trunc('week', knowable_at) AS w, count(*) AS n, avg(tone) AS tone,
               sum(list_contains(signals, 'bottleneck')::INT) AS bottleneck,
               sum(list_contains(signals, 'development')::INT) AS development,
               sum(list_contains(signals, 'stagnation')::INT) AS stagnation, max(knowable_at) AS k
        FROM news_events
        WHERE list_contains(industries, '{ind}')
           OR len(list_intersect(ciks, (SELECT list(cik) FROM ({members})))) > 0
        GROUP BY 1 ORDER BY 1"""))
    topics = INDUSTRY_ARXIV.get(ind, [])
    if topics:
        out["arxiv"] = _records(_q(con, f"""SELECT topic, month, papers, knowable_at AS k FROM research_velocity
                                            WHERE topic IN ({','.join(repr(t) for t in topics)}) ORDER BY month"""))
    else:
        out["arxiv"] = []
    out["wiki_topics"] = _records(_q(con, f"""
        SELECT article, date_trunc('week', date) AS w, sum(views) AS views, max(knowable_at) AS k
        FROM wiki_pageviews WHERE entity_type = 'topic' AND industry = '{ind}' GROUP BY 1, 2 ORDER BY 2"""))
    out["exits"] = _records(_q(con, f"""
        SELECT year(exit_date) AS year, outcome, count(DISTINCT cik) AS n, max(event_known_at) AS k
        FROM (SELECT * FROM outcomes QUALIFY row_number() OVER (PARTITION BY cik ORDER BY method = 'research' DESC) = 1)
        WHERE cik IN ({members}) AND outcome IN ('bankrupt', 'acquired', 'delisted_exchange', 'deregistered', 'went_private')
          AND exit_date >= DATE '2005-01-01'
        GROUP BY 1, 2 ORDER BY 1"""))
    out["insider_net"] = _records(_q(con, f"""
        SELECT date_trunc('month', knowable_at) AS m,
               sum(CASE WHEN trans_code = 'P' THEN shares * price ELSE 0 END) AS buys,
               sum(CASE WHEN trans_code = 'S' THEN shares * price ELSE 0 END) AS sales, max(knowable_at) AS k
        FROM insider_transactions
        WHERE cik IN ({members}) AND NOT is_derivative AND trans_code IN ('P', 'S') AND NOT trans_date_suspect
          AND coalesce(shares * price, 0) < 2e9   -- larger = filer typo (price/shares units)
          AND knowable_at >= TIMESTAMPTZ '2006-01-01'
        GROUP BY 1 ORDER BY 1"""))
    out["regulatory"] = _records(_q(con, f"""
        SELECT date_trunc('month', publication_date) AS m, type, count(*) AS n, max(knowable_at) AS k
        FROM regulatory_documents WHERE list_contains(industries, '{ind}') GROUP BY 1, 2 ORDER BY 1"""))
    out["contracts"] = _records(_q(con, f"""
        SELECT date_trunc('quarter', knowable_at) AS q, sum(amount) AS amount, max(knowable_at) AS k
        FROM gov_contracts WHERE cik IN ({members}) GROUP BY 1 ORDER BY 1"""))
    out["politicians"] = _records(_q(con, f"""
        SELECT date_trunc('quarter', p.knowable_at) AS q, p.transaction_type, count(*) AS n, max(p.knowable_at) AS k
        FROM politician_trades p
        JOIN (SELECT DISTINCT upper(ticker) AS t FROM tickers WHERE cik IN ({members})) x ON x.t = upper(p.ticker)
        GROUP BY 1, 2 ORDER BY 1"""))
    out["committees"] = _records(_q(con, f"""
        SELECT ci.committee_id, ci.committee_name, l.official_full AS member, s.title, s.party, s.valid_from, s.valid_to,
               s.knowable_at AS k
        FROM committee_industries ci JOIN committee_seats s ON s.committee_id = ci.committee_id
        JOIN legislators l USING (bioguide)
        WHERE ci.industry = '{ind}' AND s.title IN ('Chairman', 'Chair', 'Ranking Member', 'Vice Chairman')
        ORDER BY s.valid_from"""))
    return out


# ------------------------------------------------------------------ decisions
def runs(con) -> list[dict]:
    if not _has(con, "decision_runs"):
        return []
    return _records(_q(con, """SELECT r.*, count(d.decision_id) AS n_decisions, min(d.as_of) AS first, max(d.as_of) AS last
                               FROM decision_runs r LEFT JOIN decisions d USING (run_id)
                               GROUP BY ALL ORDER BY r.created_at DESC"""))


def decisions(con, run_id: str) -> dict:
    d = _q(con, """SELECT d.*, c.name FROM decisions d LEFT JOIN companies c USING (cik)
                   WHERE run_id = ? ORDER BY as_of, action, score DESC NULLS LAST""", [run_id])
    f = _q(con, """SELECT f.* FROM decision_factors f JOIN decisions d USING (decision_id) WHERE d.run_id = ?""", [run_id])
    if len(f):
        chk = f.merge(d[["decision_id", "as_of"]], on="decision_id")
        chk["late"] = chk["knowable_at"].notna() & (chk["knowable_at"] > chk["as_of"])
        late = chk.groupby("decision_id")["late"].any().to_dict()
        latest = chk.groupby("decision_id")["knowable_at"].max().to_dict()
    else:
        late, latest = {}, {}
    d["evidence_ok"] = d["decision_id"].map(lambda x: not late.get(x, False))
    d["latest_evidence"] = d["decision_id"].map(lambda x: latest.get(x))
    return {"decisions": _records(d), "factors": _records(f.rename(columns={"knowable_at": "k"}))}


# ------------------------------------------------------------------ signals (validated predictors)
SIG = "data/db/signals"
AVOID_RULES = {   # long-only exclusion flags from short-leg signals (percentiles are sign-adjusted: low = bad)
    "vol_60d": "very volatile", "max_ret_21d": "lottery spike", "net_issuance": "heavy dilution",
    "offerings_12m": "raising equity", "days_to_cover": "crowded short", "short_pct": "heavily shorted",
    "asset_growth": "rapid asset growth", "going_concern": "going-concern warning", "late_filings_12m": "late filings",
}


def _validation() -> dict:
    import json
    from pathlib import Path
    from ..config import ROOT
    f = Path(ROOT) / SIG / "validation.json"
    return json.loads(f.read_text()) if f.exists() else {}


def signals_overview(con) -> dict:
    """Scorecard + time series for the Signals tab. IC for month d is public once its
    1-month forward window has ended, so k = d + 31 days."""
    v = _validation()
    if not v:
        return {}
    ic = _q(con, f"SELECT * FROM read_parquet('{SIG}/ic_monthly.parquet') ORDER BY d")
    series = {}
    for s, g in ic.groupby("signal"):
        g = g.sort_values("d")
        series[s] = [{"d": str(r.d)[:10], "k": (pd.Timestamp(r.d) + pd.Timedelta(days=31)).isoformat() + "Z",
                      "ic": None if pd.isna(r.ic_1m) else round(float(r.ic_1m), 4),
                      "roll12": None if pd.isna(x) else round(float(x), 4)}
                     for r, x in zip(g.itertuples(), g["ic_1m"].rolling(12, min_periods=6).mean())]
    qd = _q(con, f"SELECT signal, quintile, avg(excess_ret) AS r FROM read_parquet('{SIG}/quintiles_monthly.parquet') GROUP BY 1, 2")
    quint = {s: [round(float(x), 5) for x in g.sort_values("quintile")["r"]] for s, g in qd.groupby("signal")}
    cq = _q(con, f"SELECT * FROM read_parquet('{SIG}/composite_quintiles.parquet') ORDER BY d")
    comp_series = []
    if len(cq):
        w = cq.pivot_table(index="d", columns="quintile", values="excess_ret").sort_index()
        cum5 = (1 + w[5]).cumprod() - 1
        cumsp = (1 + (w[5] - w[1])).cumprod() - 1
        cic = _q(con, f"SELECT * FROM read_parquet('{SIG}/composite_ic.parquet') ORDER BY d").set_index("d")["ic_1m"]
        for d in w.index:
            comp_series.append({"d": str(d)[:10], "k": (pd.Timestamp(d) + pd.Timedelta(days=31)).isoformat() + "Z",
                                "q5": round(float(w.at[d, 5]), 5), "cum_q5": round(float(cum5[d]), 5),
                                "cum_spread": round(float(cumsp[d]), 5),
                                "ic": None if d not in cic.index or pd.isna(cic[d]) else round(float(cic[d]), 4)})
    months = _q(con, f"SELECT DISTINCT d FROM read_parquet('{SIG}/scores.parquet') ORDER BY d")
    return {"built": v.get("built"), "universe_rule": v.get("universe_rule"), "signals": v["signals"],
            "composite": v["composite"], "composite_quintiles": quint.get("composite") or
            [round(float(x), 5) for x in cq.groupby("quintile")["excess_ret"].mean()] if len(cq) else [],
            "quintiles": quint, "ic_series": series, "composite_series": comp_series,
            "composite_signals_by_month": v.get("composite_signals_by_month", {}),
            "correlation": v.get("correlation", {}), "avoid_rules": AVOID_RULES,
            "months": [str(m)[:10] for m in months["d"]]}


def signal_month(con, month: str, limit: int = 200) -> dict:
    """Ranked candidates for one month-end: companies passing every investment screen
    as of that date, with signal percentiles and avoid flags."""
    from ..db.pit import AsOf
    v = _validation()
    used = (v.get("composite_signals_by_month") or {}).get(month[:10], [])
    sc = _q(con, f"SELECT * FROM read_parquet('{SIG}/scores.parquet') WHERE CAST(d AS DATE) = CAST(? AS DATE)", [month[:10]])
    if sc.empty:
        return {"month": month[:10], "rows": [], "used": used}
    t = pd.Timestamp(month[:10]) + pd.Timedelta(hours=21, minutes=30)
    with AsOf(con, t) as db:
        trad = set(db.tradable()["cik"].astype(int))
    universe_n = len(sc)
    sc = sc[sc["cik"].astype(int).isin(trad)]
    names = _q(con, "SELECT cik, name, current_tickers[1] AS ticker FROM companies")
    sc = sc.merge(names, on="cik", how="left")
    rows = []
    for r in sc.sort_values("composite", ascending=False).itertuples(index=False):
        d = r._asdict()
        flags = [lab for s, lab in AVOID_RULES.items()
                 if f"{s}__pct" in d and d[f"{s}__pct"] is not None and not pd.isna(d[f"{s}__pct"])
                 and d[f"{s}__pct"] <= (5 if s in ("going_concern", "late_filings_12m") else 10)
                 and not (s in ("going_concern", "late_filings_12m", "offerings_12m") and (d.get(s) or 0) == 0)]
        rows.append({"cik": int(r.cik), "ticker": d.get("ticker"), "name": d.get("name"), "industry": d.get("industry"),
                     "composite_pct": None if pd.isna(d.get("composite__pct")) else round(float(d["composite__pct"]), 1),
                     "pct": {s: (None if pd.isna(d.get(f"{s}__pct")) else round(float(d[f"{s}__pct"]), 1))
                             for s in [x["signal"] for x in v["signals"]] if f"{s}__pct" in d},
                     "flags": flags, "price": d.get("price_raw"), "dollar_vol": d.get("dollar_vol_20d"),
                     "mcap": d.get("mcap")})
    return {"month": month[:10], "k": (t + pd.Timedelta(minutes=1)).isoformat() + "Z", "used": used,
            "universe_n": universe_n, "tradable_n": len(rows), "rows": _records(pd.DataFrame(rows))[:limit]}


def company_signals(con, cik: int) -> list[dict]:
    df = _q(con, f"SELECT * FROM read_parquet('{SIG}/scores.parquet') WHERE cik = ? ORDER BY d", [int(cik)])
    if df.empty:
        return []
    pcols = [c for c in df.columns if c.endswith("__pct")]
    out = []
    for r in df.to_dict(orient="records"):
        out.append({"d": str(r["d"])[:10], "k": (pd.Timestamp(r["d"]) + pd.Timedelta(hours=21, minutes=30)).isoformat() + "Z",
                    "pct": {c[:-5]: (None if pd.isna(r[c]) else round(float(r[c]), 1)) for c in pcols}})
    return out
