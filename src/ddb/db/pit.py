"""The only supported way for feature code to read the database.

    with AsOf(con, "2019-06-28 20:00") as db:
        db.query("SELECT * FROM fundamentals WHERE cik = 320193")

Inside an AsOf context, every FEATURE table name resolves to a temporary view
filtered to ``knowable_at <= t``. Label tables (outcomes) are not exposed, so a
query that touches them fails instead of leaking the future.
"""
from __future__ import annotations

import pandas as pd

from .schema import FEATURE_TABLES, LABEL_TABLES


class LookaheadError(RuntimeError):
    pass


class AsOf:
    def __init__(self, con, t):
        ts = pd.Timestamp(t)
        self.t = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
        self.con = con

    def __enter__(self):
        c = self.con
        existing = {r[0] for r in c.execute("SELECT table_name FROM information_schema.tables").fetchall()}
        self.tables = [t for t in FEATURE_TABLES if t in existing]
        for tbl in self.tables:
            c.execute(f"CREATE OR REPLACE TEMP VIEW {tbl}_pit AS "
                      f"SELECT * FROM main.{tbl} WHERE knowable_at <= TIMESTAMPTZ '{self.t.isoformat()}'")
        return self

    def query(self, sql: str, params=None) -> pd.DataFrame:
        low = sql.lower()
        for tbl in LABEL_TABLES + ["research_notes", "research_queue", "companies"]:
            if f" {tbl}" in low or f"\n{tbl}" in low or f".{tbl}" in low:
                if tbl == "companies":
                    # companies holds CURRENT-state columns (tickers, SIC, listing status).
                    raise LookaheadError("companies holds current (hindsight) state; "
                                         "use company_names / company_industries / tickers")
                raise LookaheadError(f"{tbl} is not available to point-in-time feature queries")
        rewritten = sql
        for tbl in sorted(self.tables, key=len, reverse=True):
            rewritten = _replace_table(rewritten, tbl, f"{tbl}_pit")
        return self.con.execute(rewritten, params or []).df()

    def __exit__(self, *exc):
        for tbl in self.tables:
            self.con.execute(f"DROP VIEW IF EXISTS {tbl}_pit")
        return False

    # -- convenience ----------------------------------------------------
    def universe(self, industries=None, active_months: int = 18, include_low_confidence: bool = False) -> pd.DataFrame:
        """Companies tagged to the industries at time t AND still active then
        (filed something with the SEC in the prior `active_months`), using only
        what was known at t."""
        d = self.t.date().isoformat()
        where = ""
        if industries:
            inds = ",".join(f"'{i}'" for i in industries)
            where = f"AND ci.industry IN ({inds})"
        return self.query(f"""
            SELECT DISTINCT ci.cik, ci.industry, ci.sub_industry, ci.method, ci.confidence
            FROM company_industries ci
            WHERE ci.valid_from <= DATE '{d}' AND (ci.valid_to IS NULL OR ci.valid_to > DATE '{d}') {where}
              {"" if include_low_confidence else "AND ci.confidence <> 'low'"}
              AND ci.cik IN (SELECT cik FROM filings
                             WHERE filing_date >= DATE '{d}' - INTERVAL {int(active_months)} MONTH)
        """)

    def tradable(self, industries=None, allow_review: bool = False) -> pd.DataFrame:
        """Universe at t that passes every investment screen (configs/screens.yaml):
        not Israeli, not a weapons maker, Sharia-compliant business, and the most
        recent quarterly Sharia ratio check known at t is `pass`. `review` and
        `unknown` are excluded unless allow_review=True (review only)."""
        ok = "('pass', 'review')" if allow_review else "('pass')"
        uni = self.universe(industries)
        if uni.empty:
            return uni
        ts = self.t.isoformat()
        st = self.con.execute(f"""
            SELECT cik, bool_and(status IN {ok}) AS static_ok
            FROM screen_static WHERE knowable_at <= TIMESTAMPTZ '{ts}' GROUP BY 1
        """).df()
        fin = self.con.execute(f"""
            SELECT cik, status AS fin_status FROM screen_sharia_financial
            WHERE knowable_at <= TIMESTAMPTZ '{ts}'
            QUALIFY row_number() OVER (PARTITION BY cik ORDER BY as_of DESC) = 1
        """).df()
        out = uni.merge(st, on="cik", how="left").merge(fin, on="cik", how="left")
        allowed = {"pass", "review"} if allow_review else {"pass"}
        out = out[out["static_ok"].fillna(True) & out["fin_status"].isin(allowed)]
        return out.drop(columns=["static_ok"])

    def latest_fact(self, cik: int, concept: str, unit: str = "USD") -> pd.DataFrame:
        """Latest-filed version of each period's value for a concept."""
        return self.query(f"""
            SELECT period_start, period_end, fp, form, value, knowable_at
            FROM fundamentals
            WHERE cik = {int(cik)} AND concept = '{concept}' AND unit = '{unit}'
            QUALIFY row_number() OVER (PARTITION BY period_start, period_end
                                       ORDER BY knowable_at DESC) = 1
            ORDER BY period_end
        """)


def _replace_table(sql: str, name: str, new: str) -> str:
    import re
    return re.sub(rf"(?<![\w.]){name}(?![\w])", new, sql)
