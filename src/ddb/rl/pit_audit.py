"""Time-travel test: would every signal have looked the same on the day itself?

For each cutoff date t, build a copy of the database that contains ONLY what was
public by t's close (every row with knowable_at <= t; dated tables by their
validity), rebuild the monthly signal panel from that copy, and compare its row for
month-end t with the stored panel's row for t. Any feature that used a row from
after t changes; a point-in-time-correct pipeline gives identical values.

Labels (forward returns) are excluded from the comparison: they are the future by
design. Static identity (company names, current tickers used to look up prices) is
copied as is.

    python -m ddb.rl.pit_audit [--cutoffs 2018-06-29 2021-03-31]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import DATA_DIR

DB_PATH = DATA_DIR / "ddb.duckdb"
WORK = DATA_DIR / "audit"
LABELS = {"fwd_1m", "fwd_3m", "fwd_1m_excess"}

PARQUET_BY_KNOWABLE = ["prices", "fundamentals", "insider_transactions", "filing_text_signals", "inst_holdings",
                       "inst_filers", "short_interest", "corporate_actions", "politician_trades", "gov_contracts",
                       "news_events", "regulatory_documents", "research_velocity"]


def truncated_copy(t: pd.Timestamp, root: Path, src_db: Path = DB_PATH) -> Path:
    """A database root under `root` with only rows public by t (UTC)."""
    import duckdb
    if root.exists():
        shutil.rmtree(root)
    (root / "data" / "db").mkdir(parents=True)
    ts = t.tz_localize("UTC").isoformat() if t.tzinfo is None else t.isoformat()
    con = duckdb.connect(str(root / "data" / "ddb.duckdb"))
    con.execute("SET TimeZone='UTC'")
    con.execute(f"ATTACH '{src_db.as_posix()}' AS src (READ_ONLY)")
    src_tables = {r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_catalog = 'src' AND table_type = 'BASE TABLE'").fetchall()}
    for tb in sorted(src_tables):
        cols = {r[0] for r in con.execute(f"SELECT column_name FROM information_schema.columns "
                                          f"WHERE table_catalog = 'src' AND table_name = '{tb}'").fetchall()}
        if tb in ("companies", "outcomes", "research_notes", "research_queue"):
            where = ""                     # identity / labels (labels are only used for forward returns)
        elif tb in ("company_names", "company_industries", "tickers"):
            where = f"WHERE coalesce(valid_from, DATE '1900-01-01') <= CAST(TIMESTAMPTZ '{ts}' AS DATE)"
            if "knowable_at" in cols:
                where += f" AND (knowable_at IS NULL OR knowable_at <= TIMESTAMPTZ '{ts}')"
        elif "knowable_at" in cols:
            where = f"WHERE knowable_at <= TIMESTAMPTZ '{ts}'"
        else:
            where = ""
        con.execute(f"CREATE TABLE main.{tb} AS SELECT * FROM src.{tb} {where}")
    for name in PARQUET_BY_KNOWABLE:
        d = src_db.parent / "db" / name
        if not d.exists() or not any(d.glob("*.parquet")):
            continue
        (root / "data" / "db" / name).mkdir(parents=True, exist_ok=True)
        con.execute(f"""COPY (SELECT * FROM read_parquet('{d.as_posix()}/*.parquet', union_by_name=true)
                              WHERE knowable_at <= TIMESTAMPTZ '{ts}')
                        TO '{(root / "data" / "db" / name / "part.parquet").as_posix()}' (FORMAT parquet)""")
    con.close()
    from ..db.schema import connect
    connect(root / "data" / "ddb.duckdb").close()          # register the Parquet-backed views
    return root / "data" / "ddb.duckdb"


def compare(stored: pd.DataFrame, rebuilt: pd.DataFrame, month: pd.Timestamp) -> dict:
    a = stored[pd.to_datetime(stored["d"]) == month].set_index("cik")
    b = rebuilt[pd.to_datetime(rebuilt["d"]) == month].set_index("cik")
    common = a.index.intersection(b.index)
    feats = [c for c in a.columns if c in b.columns and c not in LABELS and c not in ("d", "t", "industry")
             and pd.api.types.is_numeric_dtype(a[c])]
    bad = {}
    for c in feats:
        x, y = a.loc[common, c].astype(float), b.loc[common, c].astype(float)
        same = (np.isclose(x, y, rtol=1e-6, atol=1e-9) | (x.isna() & y.isna()))
        if not same.all():
            bad[c] = int((~same).sum())
    if "industry" in a and "industry" in b:
        diff = (a.loc[common, "industry"].astype(str) != b.loc[common, "industry"].astype(str)).sum()
        if diff:
            bad["industry"] = int(diff)
    return {"month": str(month.date()), "companies_stored": int(len(a)), "companies_rebuilt": int(len(b)),
            "companies_compared": int(len(common)), "only_in_stored": int(len(a.index.difference(b.index))),
            "only_in_rebuilt": int(len(b.index.difference(a.index))), "features_compared": len(feats),
            "features_differing": bad, "identical": not bad and len(a) == len(b)}


def _build_panel(db: Path, out: Path, cwd_root: Path | None) -> pd.DataFrame:
    from ..features import panel
    old_out, here = panel.OUT, os.getcwd()
    panel.OUT = out
    if cwd_root is not None:
        os.chdir(cwd_root)                                      # panel reads a few Parquet sources by relative path
    try:
        panel.build("2011-01", db_path=db)
    finally:
        os.chdir(here)
        panel.OUT = old_out
    return pd.read_parquet(out / "panel.parquet")


def run(cutoffs: list[str], reference: str = "rebuild") -> dict:
    """reference='rebuild': compare against a panel rebuilt now from the full database
    with the same code (tests the code); 'stored': against data/db/signals/panel.parquet
    (tests the stored file as well, so it must be rebuilt after code changes)."""
    if reference == "stored":
        stored = pd.read_parquet(DATA_DIR / "db" / "signals" / "panel.parquet")
    else:
        stored = _build_panel(DB_PATH, WORK / "full" / "signals", None)
    months = pd.DatetimeIndex(sorted(pd.to_datetime(stored["d"]).unique()))
    out = []
    for c in cutoffs:
        t0 = time.time()
        m = months[months <= pd.Timestamp(c)][-1]                   # the month-end row to check
        t = m + pd.Timedelta(hours=21, minutes=30)                  # its decision time
        root = WORK / f"cut_{m.date()}"
        db = truncated_copy(t, root)
        rebuilt = _build_panel(db, root / "signals", root)
        res = compare(stored, rebuilt, m)
        res["seconds"] = round(time.time() - t0)
        out.append(res)
        print(res, flush=True)
        if not os.environ.get("DDB_AUDIT_KEEP"):
            shutil.rmtree(root, ignore_errors=True)
    rep = {"built": pd.Timestamp.now(tz="UTC").isoformat(), "reference": reference, "checks": out, "passed": all(r["identical"] for r in out)}
    (DATA_DIR / "db" / "rl").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "db" / "rl" / "pit_audit.json").write_text(json.dumps(rep, indent=1, default=str))
    return rep


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cutoffs", nargs="*", default=["2018-06-29", "2021-03-31", "2024-09-30"])
    ap.add_argument("--reference", default="rebuild", choices=["rebuild", "stored"])
    a = ap.parse_args()
    print(run(a.cutoffs, a.reference)["passed"])
