"""Institutional holdings from SEC Form 13F data sets (free, quarterly, 2013+).

Managers with $100M+ in US equities file Form 13F within 45 days of each
quarter-end, listing their holdings. The SEC publishes them as bulk data sets
(SUBMISSION, COVERPAGE, INFOTABLE tables) on its "Form 13F Data Sets" page.

What is kept:
- original 13F-HR reports (amendments are skipped: restatements are rare, and
  dropping them never adds information that wasn't public at the time);
- share positions (not principal amounts, not options);
- positions in companies of our database: the issuer's 6-character CUSIP prefix
  is mapped to a company by matching the issuer name to our name history (a name
  must identify exactly one company; the most common company per prefix wins).

Point in time: a holding is public the day after the filing date
(knowable_at = filing date + 1 day, 00:00 UTC), since the data set has no
acceptance time.

Tables (Parquet views): inst_holdings (cik, filer_cik, period, shares, value,
accession, knowable_at) and inst_filers (filer_cik, period, knowable_at: every
13F-HR filer, to normalize ownership breadth).

    python -m ddb.db.build_13f [--since 2015]
"""
from __future__ import annotations

import argparse
import io
import re
import time
import zipfile

import pandas as pd

from ..config import DATA_DIR
from ..data.http import RateLimitedSession, sec_user_agent
from .research import norm_name
from .schema import connect

INDEX = "https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets"
OUT = DATA_DIR / "db" / "inst_holdings"
FILERS = DATA_DIR / "db" / "inst_filers"
RAW = DATA_DIR / "raw" / "13f"
DB_PATH = DATA_DIR / "ddb.duckdb"


def list_datasets(session) -> list[str]:
    html = session.get(INDEX).text
    links = sorted(set(re.findall(r'href="([^"]+_form13f\.zip)"', html)))
    return [l if l.startswith("http") else "https://www.sec.gov" + l for l in links]


def read_tables(raw: bytes) -> dict[str, pd.DataFrame]:
    z = zipfile.ZipFile(io.BytesIO(raw))
    out = {}
    for name in z.namelist():
        base = name.rsplit("/", 1)[-1].upper()
        for t, cols in (("SUBMISSION.TSV", ["ACCESSION_NUMBER", "FILING_DATE", "SUBMISSIONTYPE", "CIK", "PERIODOFREPORT"]),
                        ("INFOTABLE.TSV", ["ACCESSION_NUMBER", "NAMEOFISSUER", "TITLEOFCLASS", "CUSIP", "VALUE",
                                           "SSHPRNAMT", "SSHPRNAMTTYPE", "PUTCALL"])):
            if base == t:
                out[t.split(".")[0].lower()] = pd.read_csv(z.open(name), sep="\t", usecols=lambda c: c in cols,
                                                           dtype=str, quoting=3, on_bad_lines="skip")
    return out


def name_map(con) -> dict:
    """normalized name -> cik, only names that identify exactly one company."""
    n = con.execute("SELECT DISTINCT cik, name FROM company_names UNION SELECT cik, name FROM companies").df()
    n["k"] = n["name"].map(norm_name)
    n = n[n["k"].str.len() >= 3]
    u = n.groupby("k")["cik"].nunique()
    n = n[n["k"].isin(u[u == 1].index)].drop_duplicates("k")
    return dict(zip(n["k"], n["cik"]))


def cusip_map(info: pd.DataFrame, names: dict) -> dict:
    """6-char CUSIP issuer prefix -> cik, by the most common name match."""
    i = info[["CUSIP", "NAMEOFISSUER"]].dropna().copy()
    i["p6"] = i["CUSIP"].str.upper().str[:6]
    i["cik"] = i["NAMEOFISSUER"].map(norm_name).map(names)
    m = i.dropna(subset=["cik"]).groupby(["p6", "cik"]).size().reset_index(name="n")
    m = m.sort_values("n", ascending=False).drop_duplicates("p6")
    return dict(zip(m["p6"], m["cik"].astype(int)))


def process(tables: dict, names: dict, prior_map: dict | None = None) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    sub = tables["submission"]
    sub = sub[sub["SUBMISSIONTYPE"].str.upper() == "13F-HR"].copy()
    sub["filing_date"] = pd.to_datetime(sub["FILING_DATE"], format="mixed", dayfirst=False, errors="coerce")
    sub["period"] = pd.to_datetime(sub["PERIODOFREPORT"], format="mixed", errors="coerce")
    sub["knowable_at"] = (sub["filing_date"] + pd.Timedelta(days=1)).dt.tz_localize("UTC")
    sub = sub.dropna(subset=["filing_date", "period"])
    filers = pd.DataFrame({"filer_cik": sub["CIK"].astype(int), "period": sub["period"].dt.date,
                           "knowable_at": sub["knowable_at"]})
    info = tables["infotable"]
    info = info[(info["SSHPRNAMTTYPE"].str.upper() == "SH") & info["PUTCALL"].isna()]
    cmap = dict(prior_map or {})
    cmap.update(cusip_map(info, names))
    info = info.assign(cik=info["CUSIP"].str.upper().str[:6].map(cmap)).dropna(subset=["cik"])
    h = info.merge(sub[["ACCESSION_NUMBER", "CIK", "period", "knowable_at"]], on="ACCESSION_NUMBER")
    h = pd.DataFrame({"cik": h["cik"].astype(int), "filer_cik": h["CIK"].astype(int), "period": h["period"].dt.date,
                      "shares": pd.to_numeric(h["SSHPRNAMT"], errors="coerce"),
                      "value": pd.to_numeric(h["VALUE"], errors="coerce"),
                      "accession": h["ACCESSION_NUMBER"], "knowable_at": h["knowable_at"]})
    h = h.groupby(["cik", "filer_cik", "period", "accession", "knowable_at"], as_index=False)[["shares", "value"]].sum()
    return h, filers, cmap


def build(since: int = 2013, db_path=DB_PATH) -> dict:
    t0 = time.time()
    s = RateLimitedSession(min_interval_s=0.15, user_agent=sec_user_agent(), timeout_s=300)
    con = connect(db_path, read_only=True)
    names = name_map(con)
    con.close()
    OUT.mkdir(parents=True, exist_ok=True)
    FILERS.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    links = list_datasets(s)
    n_rows, cmap = 0, {}
    for url in links:
        stem = url.rsplit("/", 1)[-1].replace(".zip", "")
        yr = re.search(r"(20\d\d)", stem)
        if yr and int(yr.group(1)) < since:
            continue
        out = OUT / f"{stem}.parquet"
        if out.exists():
            continue
        cache = RAW / f"{stem}.zip"
        if not cache.exists():
            cache.write_bytes(s.get(url).content)
        h, f, cmap = process(read_tables(cache.read_bytes()), names, cmap)
        h.to_parquet(out, index=False)
        f.to_parquet(FILERS / f"{stem}.parquet", index=False)
        n_rows += len(h)
        print(f"  {stem}: {len(h):,} holdings in our companies, {f['filer_cik'].nunique():,} filers, {time.time() - t0:.0f}s", flush=True)
    return {"datasets": len(links), "rows": n_rows, "seconds": round(time.time() - t0)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", type=int, default=2013)
    print(build(ap.parse_args().since))
