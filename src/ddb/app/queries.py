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
    out["short_term"] = company_short_term(con, cik)
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
from ..config import DATA_DIR  # noqa: E402

SIG = (DATA_DIR / "db" / "signals").as_posix()   # absolute, so the app works from any directory
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
            "questions": _signal_cfg().get("questions", {}),
            "months": [str(m)[:10] for m in months["d"]]}


def _signal_cfg() -> dict:
    return yaml.safe_load((CONFIG_DIR / "signals.yaml").read_text())


def _proven_avoid() -> set:
    """Avoid signals that predicted losers in our tests (predictive or moderate)."""
    return {x["signal"] for x in (_validation().get("signals") or []) if x.get("status") in ("predictive", "moderate")}


def _flags(d: dict, proven: set | None = None) -> list[str]:
    """Avoid flags: the name sits in the worst decile (5% for rare distress events) of an
    avoid signal that predicted losers in our tests (`proven`; all avoid rules if None)."""
    out = []
    for s, lab in AVOID_RULES.items():
        if proven is not None and s not in proven:
            continue
        v = d.get(f"{s}__pct")
        if v is None or pd.isna(v):
            continue
        if v <= (5 if s in ("going_concern", "late_filings_12m") else 10) and \
                not (s in ("going_concern", "late_filings_12m", "offerings_12m") and (d.get(s) or 0) == 0):
            out.append(lab)
    return out


def _month_scores(con, month: str) -> pd.DataFrame:
    return _q(con, f"SELECT * FROM read_parquet('{SIG}/scores.parquet') WHERE CAST(d AS DATE) = CAST(? AS DATE)", [month[:10]])


def signal_month(con, month: str, limit: int = 250) -> dict:
    """The monthly decision view: companies passing every investment screen at a month-end,
    ranked by the walk-forward composite and organized by the questions in signals.yaml.

    Per row: composite percentile, a verdict (buy candidate / avoid / hold), a score per
    question (average percentile of that question's signals in use that month), avoid flags,
    the biggest drivers of the composite, and what changed since the previous month-end.
    Only signals the composite used that month (proven on earlier data) count."""
    from ..db.pit import AsOf
    v = _validation()
    cfg = _signal_cfg()
    qcfg, scfg = cfg.get("questions", {}), cfg["signals"]
    used = (v.get("composite_signals_by_month") or {}).get(month[:10], [])
    sc = _month_scores(con, month)
    base = {"month": month[:10], "used": used, "questions": qcfg,
            "question_signals": {q: [s for s in used if scfg.get(s, {}).get("question") == q] for q in qcfg}}
    if sc.empty:
        return {**base, "rows": [], "changes": {}}
    t = pd.Timestamp(month[:10]) + pd.Timedelta(hours=21, minutes=30)
    with AsOf(con, t) as db:
        trad = set(db.tradable()["cik"].astype(int))
    universe_n = len(sc)
    months = _q(con, f"SELECT DISTINCT CAST(d AS DATE) AS d FROM read_parquet('{SIG}/scores.parquet') "
                     "WHERE CAST(d AS DATE) < CAST(? AS DATE) ORDER BY 1 DESC LIMIT 1", [month[:10]])
    prev = _month_scores(con, str(months["d"].iloc[0])) if len(months) else pd.DataFrame()
    proven = _proven_avoid()
    prev_state = {}
    for r in prev.to_dict(orient="records"):
        prev_state[int(r["cik"])] = {"pct": None if pd.isna(r.get("composite__pct")) else float(r["composite__pct"]),
                                     "flags": _flags(r, proven)}
    names = _q(con, "SELECT cik, name, current_tickers[1] AS ticker FROM companies")
    sc = sc.merge(names, on="cik", how="left")
    label = {s: c.get("label", s) for s, c in scfg.items()}
    earn = _earnings(con, t, sc["cik"].astype(int).tolist())
    rows = []
    for r in sc.sort_values("composite", ascending=False).to_dict(orient="records"):
        cik = int(r["cik"])
        flags = _flags(r, proven)
        cp = None if pd.isna(r.get("composite__pct")) else round(float(r["composite__pct"]), 1)
        qs = {}
        for q in qcfg:
            vals = [r.get(f"{s}__pct") for s in base["question_signals"][q]]
            vals = [float(x) for x in vals if x is not None and not pd.isna(x)]
            qs[q] = round(sum(vals) / len(vals), 1) if vals else None
        contrib = sorted(((float(r[f"{s}__z"]), s) for s in used if f"{s}__z" in r and r[f"{s}__z"] is not None
                          and not pd.isna(r[f"{s}__z"])), reverse=True)
        drivers = [{"signal": s, "label": label.get(s, s), "z": round(z, 2)} for z, s in contrib[:2] if z > 0.5]
        drags = [{"signal": s, "label": label.get(s, s), "z": round(z, 2)} for z, s in contrib[::-1][:2] if z < -0.5]
        verdict = "avoid" if flags else "buy candidate" if (cp or 0) >= 80 else "hold" if (cp or 0) >= 40 else "weak"
        pv = prev_state.get(cik)
        change = None
        if pv is None:
            change = "new in universe"
        elif (cp or 0) >= 80 and (pv["pct"] or 0) < 80:
            change = "entered top 20%"
        elif (cp or 0) < 80 and (pv["pct"] or 0) >= 80:
            change = "left top 20%"
        new_flags = [f for f in flags if pv is None or f not in pv["flags"]]
        rows.append({"cik": cik, "ticker": r.get("ticker"), "name": r.get("name"), "industry": r.get("industry"),
                     "tradable": cik in trad, "composite_pct": cp, "prev_pct": pv["pct"] if pv else None,
                     "verdict": verdict, "questions": qs, "flags": flags, "new_flags": new_flags,
                     "drivers": drivers, "drags": drags, "change": change,
                     "pct": {s: (None if pd.isna(r.get(f"{s}__pct")) else round(float(r[f"{s}__pct"]), 1))
                             for s in [x["signal"] for x in v.get("signals", [])] if f"{s}__pct" in r},
                     "price": r.get("price_raw"), "dollar_vol": r.get("dollar_vol_20d"), "mcap": r.get("mcap"),
                     "earnings": earn.get(cik)})
    trad_rows = [x for x in rows if x["tradable"]]
    # names that were top-20% last month and fell out (or left the tradable universe)
    now = {x["cik"]: x for x in trad_rows}
    left = []
    for cik, pv in prev_state.items():
        if (pv["pct"] or 0) >= 80 and (cik not in now or (now[cik]["composite_pct"] or 0) < 80):
            x = now.get(cik)
            nm = names[names["cik"] == cik]
            left.append({"cik": cik, "ticker": nm["ticker"].iloc[0] if len(nm) else None,
                         "name": nm["name"].iloc[0] if len(nm) else None, "prev_pct": pv["pct"],
                         "composite_pct": x["composite_pct"] if x else None,
                         "why": ("no longer passes screens or liquidity" if x is None else
                                 "flagged: " + ", ".join(x["new_flags"] or x["flags"]) if x["flags"] else
                                 "score fell")})
    changes = {
        "entered": [x for x in trad_rows if x["change"] == "entered top 20%"],
        "left": sorted(left, key=lambda x: -(x["prev_pct"] or 0)),
        "new_flags": [x for x in trad_rows if x["new_flags"]],
        "prev_month": str(months["d"].iloc[0])[:10] if len(months) else None,
    }
    return {**base, "k": (t + pd.Timedelta(minutes=1)).isoformat() + "Z", "universe_n": universe_n,
            "tradable_n": len(trad_rows), "rows": _records(pd.DataFrame(trad_rows))[:limit] if trad_rows else [],
            "changes": {k: (_records(pd.DataFrame(v))[:60] if isinstance(v, list) and v else v) for k, v in changes.items()}}


# ------------------------------------------------------------------ short-term (daily + intraday)
def _short_cfg() -> dict:
    return yaml.safe_load((CONFIG_DIR / "short_term.yaml").read_text())


def _read_json(path: str) -> dict:
    import json
    from pathlib import Path
    f = Path(path)
    return json.loads(f.read_text()) if f.exists() else {}


def _alerts(r: dict) -> list[dict]:
    """Plain-language short-term alerts for one name-day. `signal` links each alert to
    its data point, so the page can show whether that data point paid in our tests."""
    a = []
    g = lambda k: (None if r.get(k) is None or pd.isna(r.get(k)) else float(r[k]))   # noqa: E731
    if (g("offering_fresh") or 0) > 0:
        a.append({"signal": "offering_fresh", "text": "offering filed", "tone": "bad"})
    if (g("distress_fresh") or 0) > 0:
        a.append({"signal": "distress_fresh", "text": "distress filing", "tone": "bad"})
    if g("earnings_fresh") is not None:
        a.append({"signal": "earnings_fresh", "text": f"earnings reaction {g('earnings_fresh') * 100:+.1f}%",
                  "tone": "good" if g("earnings_fresh") > 0 else "bad"})
    if (g("insider_buy_fresh") or 0) > 0:
        a.append({"signal": "insider_buy_fresh", "text": f"insider buying ${math.expm1(g('insider_buy_fresh')) / 1e3:,.0f}K",
                  "tone": "good"})
    if abs(g("gap") or 0) >= 0.05:
        a.append({"signal": "gap", "text": f"gapped {g('gap') * 100:+.1f}%", "tone": "info"})
    if abs(g("ret_1d") or 0) >= 0.08:
        a.append({"signal": "ret_1d", "text": f"moved {g('ret_1d') * 100:+.1f}% today", "tone": "info"})
    if (g("rel_volume") or 0) >= 3:
        a.append({"signal": "rel_volume", "text": f"volume {g('rel_volume'):.1f}x normal", "tone": "info"})
    if (g("news_spike") or 0) >= math.log(3):
        a.append({"signal": "news_spike", "text": "news spike", "tone": "info"})
    if (g("wiki_spike") or 0) >= math.log(3):
        a.append({"signal": "wiki_spike", "text": "attention spike", "tone": "info"})
    return a


def _earnings(con, t, ciks) -> dict:
    """cik -> expected next results date (estimated from the company's own history, as of t)."""
    from ..features.calendar import expected_earnings, trading_days_between
    try:
        e = expected_earnings(con, t, ciks)
    except Exception:  # noqa: BLE001
        return {}
    t0 = pd.Timestamp(t).tz_localize(None) if pd.Timestamp(t).tzinfo else pd.Timestamp(t)
    return {int(r.cik): {"next": str(r.next_expected)[:10], "last": str(r.last_report)[:10], "overdue": bool(r.overdue),
                         "days": int(r.days_to), "trading_days": trading_days_between(t0, r.next_expected), "method": r.method}
            for r in e.itertuples()}


# ------------------------------------------------------------------ portfolio, market, tracking
def portfolio_overview(con) -> dict:
    """Backtest summary, equity/drawdown/halt line, and the month-ends with a snapshot."""
    s = _read_json(f"{SIG}/../portfolio/summary.json")
    if not s:
        return {}
    eq = _q(con, f"SELECT * FROM read_parquet('{SIG}/../portfolio/equity.parquet') ORDER BY d")
    eq["d"] = pd.to_datetime(eq["d"])
    w = eq.set_index("d").resample("W").last().dropna(subset=["equity"])
    series = [{"d": str(i)[:10], "k": (i + pd.Timedelta(hours=21, minutes=30)).isoformat() + "Z",
               "equity": round(float(r.equity), 2), "benchmark": round(float(r.benchmark), 2),
               "drawdown": round(float(r.drawdown), 4), "halt_line": None if pd.isna(r.halt_line) else round(float(r.halt_line), 4)}
              for i, r in w.iterrows()]
    snaps = _read_json(f"{SIG}/../portfolio/snapshots.json")
    return {"summary": s, "equity": series, "months": sorted(snaps)}


def portfolio_month(con, month: str) -> dict:
    """The model portfolio at one month-end: holdings, sizes, risk, expected return, earnings."""
    snaps = _read_json(f"{SIG}/../portfolio/snapshots.json")
    sn = snaps.get(month[:10])
    if not sn:
        return {}
    t = pd.Timestamp(month[:10]) + pd.Timedelta(hours=21, minutes=30)
    earn = _earnings(con, t, [h["cik"] for h in sn["holdings"]])
    warn = yaml.safe_load((CONFIG_DIR / "risk.yaml").read_text())["portfolio"]
    for h in sn["holdings"]:
        h["earnings"] = earn.get(h["cik"])
        h["earnings_soon"] = bool(h["earnings"] and h["earnings"]["trading_days"] is not None
                                  and h["earnings"]["trading_days"] <= warn["earnings_warning_days"])
    sn["k"] = t.isoformat() + "Z"
    sn["config"] = warn
    return sn


def market_overview(con) -> dict:
    """Daily regime table (point in time) and how the model did in each regime."""
    from pathlib import Path
    f = Path(SIG).parent / "regime" / "regime.parquet"
    if not f.exists():
        return {}
    r = _q(con, f"SELECT * FROM read_parquet('{f.as_posix()}') ORDER BY d")
    cols = ["vix", "vix_pct", "hy_oas", "hy_chg_3m", "baa", "baa_chg_3m", "credit", "curve_10y2y", "curve_10y3m", "mkt_index", "mkt_trend", "breadth",
            "mkt_vol", "mkt_ret_24m", "crash_state", "points", "regime", "reasons"]
    rows = []
    for x in r.to_dict(orient="records"):
        d = pd.Timestamp(x["d"])
        o = {"d": str(d)[:10], "k": (d + pd.Timedelta(hours=21, minutes=30)).isoformat() + "Z"}
        for c in cols:
            v = x.get(c)
            o[c] = None if v is None or (isinstance(v, float) and not math.isfinite(v)) else (round(v, 4) if isinstance(v, float) else v)
        o["crash_state"] = bool(o["crash_state"]) if o["crash_state"] is not None else None
        rows.append(o)
    return {"days": rows, "summary": _read_json((Path(SIG).parent / "regime" / "summary.json").as_posix())}


def tracking_overview(con) -> dict:
    from pathlib import Path
    live = Path(SIG).parent / "live"
    return {"tracking": _read_json((live / "tracking.json").as_posix()),
            "execution": _read_json((live / "execution.json").as_posix()),
            "readiness": _read_json((Path(SIG).parent / "rl" / "readiness.json").as_posix())}


def short_term_overview(con) -> dict:
    """Daily + intraday scorecards and their track records (for the Today tab and the lab)."""
    v = _read_json(f"{SIG}/daily/validation.json")
    out = {"daily": {}, "intraday": {}}
    if v:
        ic = _q(con, f"""SELECT date_trunc('month', d) AS m, signal, horizon, avg(ic) AS ic, count(*) AS n
                         FROM read_parquet('{SIG}/daily/ic_daily.parquet') GROUP BY ALL ORDER BY m""")
        series = {}
        for (s, h), g in ic.groupby(["signal", "horizon"]):
            series.setdefault(s, {})[h] = [{"m": str(r.m)[:10], "k": (pd.Timestamp(r.m) + pd.DateOffset(months=1, days=7)).isoformat() + "Z",
                                            "ic": None if pd.isna(r.ic) else round(float(r.ic), 4)} for r in g.itertuples()]
        cd = _q(con, f"SELECT * FROM read_parquet('{SIG}/daily/composite_daily.parquet') ORDER BY d")
        comp = {}
        for h, g in cd.groupby("horizon"):
            g = g.dropna(subset=["ic"]).copy()
            hv = (v.get("horizons") or {}).get(h, 1)
            g = g.iloc[::max(int(hv), 1)]                     # non-overlapping holding periods
            g["net"] = g["q5"] - g["q5_cost"]
            g["cum_gross"] = (1 + g["q5"]).cumprod() - 1
            g["cum_net"] = (1 + g["net"]).cumprod() - 1
            w = g.set_index("d").resample("W").last().dropna(subset=["cum_net"])
            comp[h] = [{"d": str(i)[:10], "k": (i + pd.Timedelta(days=7)).isoformat() + "Z",
                        "cum_gross": round(float(r.cum_gross), 5), "cum_net": round(float(r.cum_net), 5)}
                       for i, r in w.iterrows()]
        days = _q(con, f"SELECT DISTINCT CAST(d AS DATE) AS d FROM read_parquet('{SIG}/daily/scores.parquet') ORDER BY 1")
        out["daily"] = {**v, "ic_series": series, "composite_series": comp, "days": [str(x)[:10] for x in days["d"]]}
    from pathlib import Path
    idir = Path(SIG) / "intraday"
    if idir.exists():
        for tf in sorted(p.name for p in idir.iterdir() if (p / "validation.json").exists()):
            iv = _read_json(f"{SIG}/intraday/{tf}/validation.json")
            ic = _q(con, f"""SELECT date_trunc('week', day) AS w, signal, avg(ic) AS ic FROM read_parquet('{SIG}/intraday/{tf}/daily_ic.parquet')
                             WHERE horizon = ? GROUP BY ALL ORDER BY w""", [iv.get("primary_horizon")])
            iv["ic_series"] = {s: [{"w": str(r.w)[:10], "k": (pd.Timestamp(r.w) + pd.Timedelta(days=7)).isoformat() + "Z",
                                    "ic": None if pd.isna(r.ic) else round(float(r.ic), 4)} for r in g.itertuples()]
                               for s, g in ic.groupby("signal")}
            out["intraday"][tf] = iv
    return out


def short_term_day(con, day: str, limit: int = 300) -> dict:
    """The Today view: for the latest trading day on or before `day`, screened names with
    short-term data points, the short-term composite, plain-language alerts, the daily
    range (for stops/sizing) and the monthly verdict for context."""
    from ..db.pit import AsOf
    days = _q(con, f"""SELECT max(CAST(d AS DATE)) AS d FROM read_parquet('{SIG}/daily/scores.parquet')
                       WHERE CAST(d AS DATE) <= CAST(? AS DATE)""", [day[:10]])
    if days.empty or days["d"].iloc[0] is None or pd.isna(days["d"].iloc[0]):
        return {"day": None, "rows": []}
    d = str(days["d"].iloc[0])[:10]
    sc = _q(con, f"SELECT * FROM read_parquet('{SIG}/daily/scores.parquet') WHERE CAST(d AS DATE) = CAST(? AS DATE)", [d])
    t = pd.Timestamp(d) + pd.Timedelta(hours=21, minutes=30)
    with AsOf(con, t) as db:
        trad = set(db.tradable()["cik"].astype(int))
    universe_n = len(sc)
    sc = sc[sc["cik"].astype(int).isin(trad)]
    names = _q(con, "SELECT cik, name, current_tickers[1] AS ticker FROM companies")
    sc = sc.merge(names, on="cik", how="left")
    # monthly verdict known on this day (latest month-end before it)
    mm = _q(con, f"""SELECT * FROM read_parquet('{SIG}/scores.parquet') WHERE CAST(d AS DATE) = (
                     SELECT max(CAST(d AS DATE)) FROM read_parquet('{SIG}/scores.parquet') WHERE CAST(d AS DATE) <= CAST(? AS DATE))""", [d])
    proven = _proven_avoid()
    monthly = {int(r["cik"]): {"pct": None if pd.isna(r.get("composite__pct")) else round(float(r["composite__pct"]), 1),
                               "flags": _flags(r, proven)} for r in mm.to_dict(orient="records")}
    cfg = _short_cfg()["daily"]["signals"]
    val = {s["signal"]: s for s in (_read_json(f"{SIG}/daily/validation.json").get("signals") or [])}
    earn = _earnings(con, t, sc["cik"].astype(int).tolist())
    warn = yaml.safe_load((CONFIG_DIR / "risk.yaml").read_text())["portfolio"]["earnings_warning_days"]
    keys = list(cfg)
    rows = []
    for r in sc.sort_values("composite", ascending=False, na_position="last").to_dict(orient="records"):
        al = _alerts(r)
        e = earn.get(int(r["cik"]))
        if e and e["trading_days"] is not None and e["trading_days"] <= warn:
            al.append({"signal": None, "text": "earnings due now" if e["overdue"] or e["trading_days"] == 0
                       else f"earnings in ~{e['trading_days']}d", "tone": "info"})
        for x in al:
            vv = val.get(x["signal"], {})
            x["status"], x["pays"] = vv.get("status"), vv.get("pays_after_costs")
        m = monthly.get(int(r["cik"]))
        rows.append({"cik": int(r["cik"]), "ticker": r.get("ticker"), "name": r.get("name"), "industry": r.get("industry"),
                     "composite_pct": None if pd.isna(r.get("composite__pct")) else round(float(r["composite__pct"]), 1),
                     "values": {k: (None if pd.isna(r.get(k)) else float(r[k])) for k in keys},
                     "pct": {k: (None if pd.isna(r.get(f"{k}__pct")) else round(float(r[f"{k}__pct"]), 1)) for k in keys},
                     "alerts": al,   # avoid: a bad alert from a PROVEN data point, or a monthly red flag
                     "avoid": any(x["tone"] == "bad" and x.get("status") in ("predictive", "moderate") for x in al)
                     or bool(m and m["flags"]),
                     "monthly": m, "price": r.get("price_raw"), "dollar_vol": r.get("dollar_vol"),
                     "cost_bps": None if pd.isna(r.get("cost_rt")) else round(float(r["cost_rt"]) * 1e4, 1),
                     "atr_pct": None if pd.isna(r.get("atr_pct")) else float(r["atr_pct"]), "earnings": e})
    return {"day": d, "k": t.isoformat(), "universe_n": universe_n, "tradable_n": len(rows),
            "rows": _records(pd.DataFrame(rows))[:limit] if rows else []}


def company_short_term(con, cik: int) -> dict:
    """Recent short-term scores for one company (daily) and its latest intraday bars."""
    from pathlib import Path
    out = {"daily": [], "intraday": {}}
    f = Path(SIG) / "daily" / "scores.parquet"
    keys = list(_short_cfg()["daily"]["signals"])
    if f.exists():
        df = _q(con, f"SELECT * FROM read_parquet('{SIG}/daily/scores.parquet') WHERE cik = ? ORDER BY d", [int(cik)])
        for r in df.to_dict(orient="records"):
            out["daily"].append({"d": str(r["d"])[:10], "k": (pd.Timestamp(r["d"]) + pd.Timedelta(hours=21, minutes=30)).isoformat() + "Z",
                                 "composite_pct": None if pd.isna(r.get("composite__pct")) else round(float(r["composite__pct"]), 1),
                                 "atr_pct": None if pd.isna(r.get("atr_pct")) else float(r["atr_pct"]),
                                 "cost_bps": None if pd.isna(r.get("cost_rt")) else round(float(r["cost_rt"]) * 1e4, 1),
                                 "alerts": [x["text"] for x in _alerts(r)],
                                 "pct": {k: (None if pd.isna(r.get(f"{k}__pct")) else round(float(r[f"{k}__pct"]), 1)) for k in keys}})
    idir = Path(SIG) / "intraday"
    for tf in ("1Hour", "15Min"):
        p = idir / tf / "recent.parquet"
        if p.exists():
            df = _q(con, f"SELECT * FROM read_parquet('{p.as_posix()}') WHERE cik = ? ORDER BY ts", [int(cik)])
            if len(df):
                out["intraday"][tf] = [{"ts": str(r["ts"])[:16], "k": pd.Timestamp(r["ts"]).tz_localize("America/New_York").tz_convert("UTC").isoformat(),
                                        "close": float(r["close"]), "volume": float(r["volume"]),
                                        "composite_pct": None if pd.isna(r.get("composite__pct")) else round(float(r["composite__pct"]), 1),
                                        "vwap_dist": None if pd.isna(r.get("vwap_dist")) else float(r["vwap_dist"]),
                                        "rel_vol_tod": None if pd.isna(r.get("rel_vol_tod")) else float(r["rel_vol_tod"])}
                                       for r in df.to_dict(orient="records")]
    return out


def company_signals(con, cik: int) -> list[dict]:
    """Monthly percentiles for one company, with that month's red flags and verdict."""
    df = _q(con, f"SELECT * FROM read_parquet('{SIG}/scores.parquet') WHERE cik = ? ORDER BY d", [int(cik)])
    if df.empty:
        return []
    pcols = [c for c in df.columns if c.endswith("__pct")]
    proven = _proven_avoid()
    out = []
    for r in df.to_dict(orient="records"):
        flags = _flags(r, proven)
        cp = None if pd.isna(r.get("composite__pct")) else float(r["composite__pct"])
        out.append({"d": str(r["d"])[:10], "k": (pd.Timestamp(r["d"]) + pd.Timedelta(hours=21, minutes=30)).isoformat() + "Z",
                    "pct": {c[:-5]: (None if pd.isna(r[c]) else round(float(r[c]), 1)) for c in pcols},
                    "flags": flags,
                    "verdict": "avoid" if flags else "buy candidate" if (cp or 0) >= 80 else "hold" if (cp or 0) >= 40 else "weak"})
    return out
