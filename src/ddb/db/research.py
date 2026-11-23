"""Outcome labels and web-research ingestion.

1. ``rule_outcomes``: label how each non-listed company's public life ended,
   using its final filings (bankruptcy 8-K, merger proxy / tender offer,
   Form 25 delisting, Form 15 deregistration). Medium confidence.
2. ``ingest_seeds``: load researcher CSVs (data/research/seeds_*.csv), match
   rows to SEC CIKs by ticker or name, and record:
     - research_notes (every fact, with source URL + confidence)
     - company_industries (method='research', dated from entered_industry_date)
     - tickers (source='research')
     - outcomes (method='research', overriding rule labels)
   Unmatched rows go to research_queue.
3. ``build_queue``: open lookups for the most important gaps.

Outcomes are LABELS: never visible through AsOf feature queries.
"""
from __future__ import annotations

import glob
import re

import pandas as pd

from ..config import DATA_DIR
from .schema import connect

DB_PATH = DATA_DIR / "ddb.duckdb"
SEED_GLOB = str(DATA_DIR / "research" / "seeds_*.csv")
_SUFFIX = re.compile(r"\b(inc|corp|corporation|co|company|ltd|limited|plc|holdings?|group|sa|nv|ag|lp|llc|the)\b")


def norm_name(s: str) -> str:
    s = str(s).lower()
    s = re.sub(r"/[a-z]{2,4}/?", " ", s)          # EDGAR state tags: "CORP /CA/"
    s = re.sub(r"\([^)]*\)", " ", s)              # parentheticals: "(tZERO era)"
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = _SUFFIX.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def rule_outcomes(con) -> int:
    con.execute("DELETE FROM outcomes WHERE method = 'rule'")
    con.execute("""
        INSERT INTO outcomes (cik, outcome, exit_date, method, confidence, notes, event_known_at)
        WITH last AS (
            SELECT cik, last_filing, is_current_listed FROM companies
        ),
        ev AS (
            SELECT e.cik, e.event_type, e.event_date, e.knowable_at
            FROM events e JOIN last l USING (cik)
            WHERE e.event_date >= l.last_filing - INTERVAL 3 YEAR
        ),
        flags AS (
            SELECT l.cik, l.last_filing, l.is_current_listed,
                   max(CASE WHEN event_type = 'bankruptcy' THEN knowable_at END) AS bk,
                   max(CASE WHEN event_type IN ('merger_proxy', 'tender_offer') THEN knowable_at END) AS mg,
                   max(CASE WHEN event_type = 'delisting_exchange' THEN knowable_at END) AS dl,
                   max(CASE WHEN event_type = 'delisting_voluntary' THEN knowable_at END) AS dv,
                   max(CASE WHEN event_type = 'deregistration' THEN knowable_at END) AS dr
            FROM last l LEFT JOIN ev USING (cik)
            GROUP BY 1, 2, 3
        )
        SELECT cik,
               CASE WHEN is_current_listed THEN 'active'
                    WHEN bk IS NOT NULL THEN 'bankrupt'
                    WHEN mg IS NOT NULL AND (dv IS NOT NULL OR dr IS NOT NULL OR dl IS NOT NULL) THEN 'acquired'
                    WHEN dl IS NOT NULL THEN 'delisted_exchange'
                    WHEN dr IS NOT NULL OR dv IS NOT NULL THEN 'deregistered'
                    ELSE 'unknown' END,
               CASE WHEN is_current_listed THEN NULL ELSE last_filing END,
               'rule',
               CASE WHEN is_current_listed THEN 'high' WHEN bk IS NOT NULL OR mg IS NOT NULL THEN 'medium' ELSE 'low' END,
               'from final 3 years of filings',
               CASE WHEN is_current_listed THEN NULL
                    ELSE COALESCE(bk, mg, dl, dr, dv, CAST(last_filing + INTERVAL 1 DAY AS TIMESTAMPTZ)) END
        FROM flags
    """)
    return con.execute("SELECT count(*) FROM outcomes WHERE method='rule'").fetchone()[0]


def _parse_date(s):
    if not isinstance(s, str) or not s.strip():
        return None
    s = s.strip()
    for fmt_len, pad in ((10, ""), (7, "-01"), (4, "-01-01")):
        if len(s) == fmt_len:
            try:
                return pd.Timestamp(s + pad)
            except ValueError:
                return None
    try:
        return pd.Timestamp(s)
    except ValueError:
        return None


# Researcher labels -> database industries (sub_industry keeps the detail).
INDUSTRY_MAP = {"clean_energy": "energy", "ai_semis": "tech"}

STATUS_TO_OUTCOME = {"active": "active", "acquired": "acquired", "merged": "acquired",
                     "bankrupt": "bankrupt", "delisted": "delisted_exchange",
                     "went_private": "went_private", "renamed": "active"}


def ingest_seeds(con, pattern: str = SEED_GLOB, name_map: dict | None = None) -> dict:
    files = sorted(glob.glob(pattern))
    if not files:
        return {"files": 0}
    seeds = pd.concat([pd.read_csv(f, dtype=str, on_bad_lines="warn").assign(_file=f) for f in files],
                      ignore_index=True).fillna("")
    tick = con.execute("SELECT upper(ticker) AS t, cik FROM tickers").df()
    t2c = tick.groupby("t")["cik"].agg(lambda x: sorted(set(x))).to_dict()
    names = con.execute("SELECT cik, name FROM company_names").df()
    names["n"] = names["name"].map(norm_name)
    n2c = names.groupby("n")["cik"].agg(lambda x: sorted(set(x))).to_dict()

    for tbl, cond in (("research_notes", "method = 'web_lookup'"),
                      ("company_industries", "method = 'research'"),
                      ("tickers", "source = 'research'"),
                      ("outcomes", "method = 'research'")):
        con.execute(f"DELETE FROM {tbl} WHERE {cond}")
    con.execute("DELETE FROM research_queue WHERE task = 'match_seed'")

    now = pd.Timestamp.now(tz="UTC")
    notes, inds, ticks, outs, queue = [], [], [], [], []
    matched = 0
    name_map = name_map or {}
    for r in seeds.itertuples(index=False):
        cands = [name_map[r.company_name]] if r.company_name in name_map else []
        if not cands:
            for t in [r.ticker] + r.other_tickers.split(";"):
                t = t.strip().upper()
                if t and t in t2c:
                    cands = t2c[t]
                    break
        if not cands:
            cands = n2c.get(norm_name(r.company_name), [])
        if len(cands) != 1:
            queue.append({"cik": None, "task": "match_seed", "priority": 1.0, "status": "open",
                          "reason": f"{'ambiguous' if cands else 'no match'}: {r.company_name} ({r.ticker}) "
                                    f"[{r.industry}] {r.status} {r.exit_date}".strip(),
                          "created_at": now})
            continue
        cik = int(cands[0])
        matched += 1
        entered = _parse_date(r.entered_industry_date)
        exit_d = _parse_date(r.exit_date)
        base = {"cik": cik, "source_url": r.source_url, "method": "web_lookup",
                "confidence": r.confidence or "medium", "retrieved_at": now}
        for field, value, d in (("industry", f"{r.industry}/{r.sub_industry}", entered),
                                ("ticker", r.ticker, entered),
                                ("status", r.status, exit_d),
                                ("exit_details", r.exit_details, exit_d),
                                ("listing_route", r.listing_route, entered)):
            if value and value != "/":
                notes.append({**base, "field": field, "value": value,
                              "as_of_date": d.date() if d is not None else None, "notes": r.notes})
        if entered is not None:
            inds.append({"cik": cik, "industry": INDUSTRY_MAP.get(r.industry, r.industry),
                         "sub_industry": f"{r.industry}:{r.sub_industry}",
                         "method": "research", "matched": r.source_url[:200],
                         "confidence": r.confidence or "medium", "valid_from": entered,
                         "valid_to": exit_d, "knowable_at": entered})
        if r.ticker:
            ticks.append({"cik": cik, "ticker": r.ticker.strip().upper(), "exchange": r.exchange,
                          "valid_from": entered, "valid_to": exit_d, "source": "research",
                          "knowable_at": entered})
        outcome = STATUS_TO_OUTCOME.get(r.status.strip().lower())
        if outcome:
            outs.append({"cik": cik, "outcome": outcome, "exit_date": exit_d,
                         "terminal_value": None, "acquirer": None, "consideration": r.exit_details,
                         "method": "research", "confidence": r.confidence or "medium",
                         "source_url": r.source_url, "notes": r.notes,
                         "event_known_at": exit_d.tz_localize("UTC") if exit_d is not None else None})

    def ins(table, rows, cols):
        if not rows:
            return
        df = pd.DataFrame(rows)[cols]
        con.register("x", df)
        con.execute(f"INSERT INTO {table} ({', '.join(cols)}) SELECT {', '.join(cols)} FROM x")
        con.unregister("x")

    ins("research_notes", notes, ["cik", "field", "value", "as_of_date", "source_url", "method",
                                  "confidence", "retrieved_at", "notes"])
    ins("company_industries", inds, ["cik", "industry", "sub_industry", "method", "matched", "confidence",
                                     "valid_from", "valid_to", "knowable_at"])
    ins("tickers", ticks, ["cik", "ticker", "exchange", "valid_from", "valid_to", "source", "knowable_at"])
    ins("outcomes", outs, ["cik", "outcome", "exit_date", "terminal_value", "acquirer", "consideration",
                           "method", "confidence", "source_url", "notes", "event_known_at"])
    ins("research_queue", queue, ["cik", "task", "priority", "status", "reason", "created_at"])
    return {"files": len(files), "rows": len(seeds), "matched": matched, "unmatched": len(queue)}


def match_seeds_to_index(index: pd.DataFrame, pattern: str = SEED_GLOB) -> dict:
    """CIKs for research seeds found anywhere in EDGAR (not just our filtered set)."""
    seeds = pd.concat([pd.read_csv(f, dtype=str, on_bad_lines="warn") for f in sorted(glob.glob(pattern))],
                      ignore_index=True).fillna("")
    t2c, n2c = {}, {}
    quality = {r.cik: (r.entity_type == "operating", bool(r.sic)) for r in index.itertuples(index=False)}
    for r in index.itertuples(index=False):
        for t in r.tickers:
            t2c.setdefault(str(t).upper(), set()).add(r.cik)
        for n in [r.name] + list(r.former_names):
            n2c.setdefault(norm_name(n), set()).add(r.cik)
    found, missing = {}, []
    for r in seeds.itertuples(index=False):
        cands = set()
        for t in [r.ticker] + r.other_tickers.split(";"):
            t = t.strip().upper()
            if t in t2c:
                cands = t2c[t]
                break
        if not cands:
            cands = n2c.get(norm_name(r.company_name), set())
        if len(cands) > 1:   # prefer operating companies with an industry code
            best = max(quality[c] for c in cands)
            cands = {c for c in cands if quality[c] == best}
        if len(cands) == 1:
            found[r.company_name] = int(next(iter(cands)))
        else:
            missing.append(f"{r.company_name} ({r.ticker}) {'ambiguous' if cands else 'not in EDGAR'}")
    return {"ciks": sorted(set(found.values())), "name_map": found, "missing": missing}


def build_queue(con) -> int:
    """Open lookups: dead companies in core industries with unknown outcome or no ticker."""
    con.execute("DELETE FROM research_queue WHERE task IN ('resolve_outcome', 'resolve_ticker')")
    con.execute("""
        INSERT INTO research_queue
        SELECT c.cik,
               CASE WHEN t.cik IS NULL THEN 'resolve_ticker' ELSE 'resolve_outcome' END,
               c.n_annual_reports + CASE WHEN ci.industry IN ('tech', 'energy') THEN 5 ELSE 0 END,
               'open',
               c.name || ' | last filing ' || CAST(c.last_filing AS VARCHAR) || ' | ' || o.outcome,
               now()
        FROM companies c
        JOIN outcomes o ON o.cik = c.cik AND o.method = 'rule'
        LEFT JOIN (SELECT DISTINCT cik FROM tickers) t ON t.cik = c.cik
        LEFT JOIN (SELECT cik, min(industry) AS industry FROM company_industries GROUP BY 1) ci ON ci.cik = c.cik
        WHERE NOT c.is_current_listed
          AND c.last_filing >= DATE '2005-01-01'
          AND c.n_annual_reports >= 3
          AND (o.outcome = 'unknown' OR t.cik IS NULL)
          AND c.cik NOT IN (SELECT cik FROM outcomes WHERE method = 'research')
    """)
    return con.execute("SELECT count(*) FROM research_queue WHERE status='open'").fetchone()[0]


def run(db_path=DB_PATH) -> dict:
    """Match seeds across all of EDGAR, force-add missing companies, then ingest."""
    from .build_companies import add_companies, build_index
    idx_path = DATA_DIR / "db" / "sec_index.parquet"
    index = pd.read_parquet(idx_path) if idx_path.exists() else build_index()
    m = match_seeds_to_index(index)
    added = add_companies(m["ciks"], db_path=db_path)
    con = connect(db_path)
    out = {"added_companies": added.get("added", 0), "rule_outcomes": rule_outcomes(con),
           "seeds": ingest_seeds(con, name_map=m["name_map"]), "seeds_not_in_edgar": len(m["missing"]),
           "queue": build_queue(con)}
    con.close()
    return out


if __name__ == "__main__":
    print(run())
