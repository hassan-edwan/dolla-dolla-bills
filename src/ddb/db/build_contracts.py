"""Federal contract transactions per company (USAspending.gov API, public domain, FY2008+).

TIMING / HINDSIGHT RULES
- Uses TRANSACTIONS (each obligation or modification with its own action date),
  never award totals, which include modifications made later.
- knowable_at: the Department of Defense delays public release of contract data
  by 90 days, so DoD = action_date + 90 days. Other agencies report within
  days, so they get action_date + 5 days. Later corrections to records can't be
  dated (no vintages), which is a known limitation.

Matching: recipient_search_text with the company's name(s) since 2007. A
recipient counts only if its normalized name equals the company name or starts
with it followed by a space (keeps "ROCKET LAB NATIONAL SECURITY LLC", drops
"LEAN ROCKET LAB").

Resumable: one Parquet file per company under data/db/gov_contracts/.

    python -m ddb.db.build_contracts [--limit N]
"""
from __future__ import annotations

import argparse
import json
import time

import pandas as pd
import requests

from ..config import DATA_DIR
from .research import norm_name
from .schema import connect

DB_PATH = DATA_DIR / "ddb.duckdb"
OUT = DATA_DIR / "db" / "gov_contracts"
DONE = OUT / "_done.json"
API = "https://api.usaspending.gov/api/v2/search/spending_by_transaction/"
FIELDS = ["Award ID", "Recipient Name", "Recipient UEI", "Action Date", "Transaction Amount",
          "Awarding Agency", "Awarding Sub Agency", "Transaction Description", "Mod",
          "generated_internal_id"]
PRIORITY = ["space", "nuclear", "quantum", "robotics_ai", "ev_battery", "energy", "tech",
            "crypto_adj", "gene_biotech"]
MAX_PAGES = 40   # 4,000 transactions per company; flagged if hit


def _post(session, payload, tries=4):
    for k in range(tries):
        try:
            r = session.post(API, json=payload, timeout=90)
            if r.status_code == 200:
                return r.json()
        except requests.RequestException:
            pass
        time.sleep(2 ** k)
    return None


def recipient_matches(recipient: str, targets) -> bool:
    """Exact match, or prefix match only for multi-word names ("rocket lab" ->
    "rocket lab national security"). One-word names ("quantum", "lucid") must match exactly."""
    rn = norm_name(recipient or "")
    return any(rn == t or (" " in t and rn.startswith(t + " ")) for t in targets)


def fetch_company(session, names: list[str]) -> tuple[pd.DataFrame, bool]:
    targets = {norm_name(n) for n in names if len(norm_name(n)) >= 4}
    if not targets:
        return pd.DataFrame(), False
    rows, truncated = [], False
    for search in sorted(targets):
        page = 1
        while True:
            d = _post(session, {"filters": {"recipient_search_text": [search],
                                            "award_type_codes": ["A", "B", "C", "D"],
                                            "time_period": [{"start_date": "2007-10-01",
                                                             "end_date": pd.Timestamp.now().strftime("%Y-%m-%d")}]},
                                "fields": FIELDS, "limit": 100, "page": page,
                                "sort": "Action Date", "order": "asc"})
            if not d:
                break
            for r in d.get("results", []):
                if recipient_matches(r.get("Recipient Name"), targets):
                    rows.append(r)
            if not d.get("page_metadata", {}).get("hasNext"):
                break
            page += 1
            if page > MAX_PAGES:
                truncated = True
                break
            time.sleep(0.2)
    df = pd.DataFrame(rows).drop_duplicates(subset=["generated_internal_id", "Mod", "Action Date",
                                                    "Transaction Amount"]) if rows else pd.DataFrame()
    return df, truncated


def build(db_path=DB_PATH, limit=None, workers: int = 4) -> dict:
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    done = json.loads(DONE.read_text()) if DONE.exists() else {}
    con = connect(db_path, read_only=True)
    comp = con.execute("""
        SELECT c.cik, list(DISTINCT n.name) AS names, min(ci.industry) AS industry
        FROM companies c
        JOIN company_names n USING (cik)
        LEFT JOIN company_industries ci USING (cik)
        WHERE c.last_filing >= DATE '2008-01-01'
          AND (n.valid_to IS NULL OR n.valid_to >= DATE '2007-10-01')
        GROUP BY 1
    """).df()
    con.close()
    comp["prio"] = comp["industry"].map({k: i for i, k in enumerate(PRIORITY)}).fillna(len(PRIORITY))
    comp = comp.sort_values(["prio", "cik"])
    todo = comp[~comp["cik"].astype(str).isin(done)]
    if limit:
        todo = todo.head(limit)
    from concurrent.futures import ThreadPoolExecutor
    import threading
    local = threading.local()

    def work(r):
        if not hasattr(local, "s"):
            local.s = requests.Session()
            local.s.headers["Content-Type"] = "application/json"
        return r, *fetch_company(local.s, list(r.names))

    n_rows = 0
    pool = ThreadPoolExecutor(workers)
    for k, (r, df, truncated) in enumerate(pool.map(work, list(todo.itertuples(index=False)))):
        if not df.empty:
            out = pd.DataFrame({
                "cik": int(r.cik),
                "award_id": df["Award ID"], "award_key": df["generated_internal_id"], "mod": df["Mod"],
                "recipient_name": df["Recipient Name"], "recipient_uei": df.get("Recipient UEI"),
                "action_date": pd.to_datetime(df["Action Date"], errors="coerce"),
                "amount": pd.to_numeric(df["Transaction Amount"], errors="coerce"),
                "agency": df["Awarding Agency"], "sub_agency": df["Awarding Sub Agency"],
                "description": df["Transaction Description"],
            })
            dod = out["agency"].fillna("").str.contains("Department of Defense", case=False)
            lag = pd.to_timedelta(dod.map({True: 90, False: 5}), unit="D")
            out["knowable_at"] = (out["action_date"] + lag).dt.tz_localize("UTC")
            out["release_lag_days"] = lag.dt.days
            out.to_parquet(OUT / f"{int(r.cik)}.parquet", index=False)
            n_rows += len(out)
        done[str(int(r.cik))] = {"rows": int(len(df)), "truncated": truncated}
        if k % 25 == 0 or k == len(todo) - 1:
            DONE.write_text(json.dumps(done))
            hits = sum(1 for v in done.values() if v["rows"])
            print(f"  {k + 1}/{len(todo)} companies, {hits} with contracts, +{n_rows:,} rows, "
                  f"{time.time() - t0:.0f}s", flush=True)
    DONE.write_text(json.dumps(done))
    return {"companies_checked": len(done), "with_contracts": sum(1 for v in done.values() if v["rows"]),
            "rows_this_run": n_rows, "seconds": round(time.time() - t0)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    print(build(limit=a.limit))
