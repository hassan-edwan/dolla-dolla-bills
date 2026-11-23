"""Insider transactions (SEC Forms 3/4/5 structured data sets, 2006 -> now, free).

One row per reported transaction for issuers in the company database.
TIMING: trans_date is when the insider traded. knowable_at is when the
filing became public (SEC acceptance time). Features must use knowable_at.
Late filings (sometimes months later) are common, so the gap is kept as filing_lag_days.

Transaction codes (TRANS_CODE): P open-market purchase, S open-market sale,
A grant/award, M option exercise, F tax withholding, G gift, D disposition to
issuer, C conversion, X exercise of in/at-the-money derivative, J other.
Open-market P and S are the informative ones.

    python -m ddb.db.build_insiders
"""
from __future__ import annotations

import io
import re
import time
import zipfile
from pathlib import Path

import pandas as pd

from ..config import DATA_DIR
from ..data.http import RateLimitedSession, sec_user_agent
from .schema import connect

DB_PATH = DATA_DIR / "ddb.duckdb"
RAW = DATA_DIR / "raw" / "sec" / "form345"
OUT = DATA_DIR / "db" / "insider_transactions"
INDEX_URL = "https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets"


def list_quarters(session) -> list[str]:
    html = session.get(INDEX_URL).text
    links = sorted(set(re.findall(r'href="([^"]*?(\d{4}q\d)_form345\.zip)"', html)), key=lambda x: x[1])
    return [("https://www.sec.gov" + h if h.startswith("/") else h) for h, _ in links]


def _date(s):
    return pd.to_datetime(s, format="%d-%b-%Y", errors="coerce")


def process_quarter(path: Path, ciks: set[int], acceptance: pd.DataFrame) -> pd.DataFrame:
    z = zipfile.ZipFile(path)
    rd = lambda n, cols: pd.read_csv(io.BytesIO(z.read(n)), sep="\t", dtype=str, usecols=cols,
                                     quoting=3, on_bad_lines="skip")
    sub = rd("SUBMISSION.tsv", ["ACCESSION_NUMBER", "FILING_DATE", "DOCUMENT_TYPE", "ISSUERCIK",
                                "ISSUERTRADINGSYMBOL"] + (["AFF10B5ONE"] if "AFF10B5ONE" in
                                pd.read_csv(io.BytesIO(z.read("SUBMISSION.tsv")), sep="\t", nrows=0).columns else []))
    sub["cik"] = pd.to_numeric(sub["ISSUERCIK"], errors="coerce")
    sub = sub[sub["cik"].isin(ciks)]
    if sub.empty:
        return pd.DataFrame()
    own = rd("REPORTINGOWNER.tsv", ["ACCESSION_NUMBER", "RPTOWNERCIK", "RPTOWNERNAME",
                                    "RPTOWNER_RELATIONSHIP", "RPTOWNER_TITLE"])
    own = own.groupby("ACCESSION_NUMBER").agg(
        owner_cik=("RPTOWNERCIK", "first"), owner_name=("RPTOWNERNAME", "first"),
        relationship=("RPTOWNER_RELATIONSHIP", lambda x: ";".join(sorted(set(x.dropna())))),
        title=("RPTOWNER_TITLE", "first"), n_owners=("RPTOWNERCIK", "nunique")).reset_index()
    frames = []
    for fname, deriv in (("NONDERIV_TRANS.tsv", False), ("DERIV_TRANS.tsv", True)):
        cols = ["ACCESSION_NUMBER", "SECURITY_TITLE", "TRANS_DATE", "TRANS_CODE", "TRANS_SHARES",
                "TRANS_PRICEPERSHARE", "TRANS_ACQUIRED_DISP_CD", "SHRS_OWND_FOLWNG_TRANS",
                "DIRECT_INDIRECT_OWNERSHIP"]
        t = rd(fname, cols)
        t["is_derivative"] = deriv
        frames.append(t)
    tr = pd.concat(frames, ignore_index=True).merge(sub, on="ACCESSION_NUMBER").merge(own, on="ACCESSION_NUMBER", how="left")
    out = pd.DataFrame({
        "cik": tr["cik"].astype("int64"),
        "accession": tr["ACCESSION_NUMBER"],
        "form": tr["DOCUMENT_TYPE"],
        "issuer_symbol": tr["ISSUERTRADINGSYMBOL"],
        "owner_cik": pd.to_numeric(tr["owner_cik"], errors="coerce").astype("Int64"),
        "owner_name": tr["owner_name"],
        "relationship": tr["relationship"],
        "title": tr["title"],
        "n_owners": tr["n_owners"].astype("Int64"),
        "security_title": tr["SECURITY_TITLE"],
        "is_derivative": tr["is_derivative"],
        "trans_date": _date(tr["TRANS_DATE"]),
        "trans_code": tr["TRANS_CODE"],
        "shares": pd.to_numeric(tr["TRANS_SHARES"], errors="coerce"),
        "price": pd.to_numeric(tr["TRANS_PRICEPERSHARE"], errors="coerce"),
        "acquired_disposed": tr["TRANS_ACQUIRED_DISP_CD"],
        "shares_after": pd.to_numeric(tr["SHRS_OWND_FOLWNG_TRANS"], errors="coerce"),
        "direct_indirect": tr["DIRECT_INDIRECT_OWNERSHIP"],
        "is_10b5_1_plan": tr["AFF10B5ONE"].map({"1": True, "0": False}) if "AFF10B5ONE" in tr else None,
        "filing_date": _date(tr["FILING_DATE"]),
    })
    out = out.merge(acceptance, on="accession", how="left")
    fallback = (out["filing_date"] + pd.Timedelta(hours=22)).dt.tz_localize("UTC")
    out["knowable_at"] = out["acceptance"].fillna(fallback)
    out["filing_lag_days"] = (out["filing_date"] - out["trans_date"]).dt.days
    # Filer typos (year 0013, 2044 ...): trade dated after filing or >10 years before it.
    out["trans_date_suspect"] = out["trans_date"].isna() | (out["filing_lag_days"] < 0) | (out["filing_lag_days"] > 3650)
    return out.drop(columns="acceptance")


def build(db_path=DB_PATH) -> dict:
    t0 = time.time()
    session = RateLimitedSession(min_interval_s=0.2, user_agent=sec_user_agent())
    RAW.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    con = connect(db_path, read_only=True)
    ciks = set(con.execute("SELECT cik FROM companies").df()["cik"].astype(int))
    acceptance = con.execute("SELECT accession, min(acceptance) AS acceptance FROM filings "
                             "WHERE form IN ('3','4','5','3/A','4/A','5/A') GROUP BY 1").df()
    con.close()
    total = 0
    for url in list_quarters(session):
        q = re.search(r"(\d{4}q\d)", url).group(1)
        zpath = RAW / f"{q}_form345.zip"
        if not zpath.exists():
            zpath.write_bytes(session.get(url).content)
        df = process_quarter(zpath, ciks, acceptance)
        if not df.empty:
            df.to_parquet(OUT / f"{q}.parquet", index=False)
        total += len(df)
        print(f"  {q}: {len(df):,} rows (total {total:,}) {time.time() - t0:.0f}s", flush=True)
    return {"rows": total, "seconds": round(time.time() - t0)}


if __name__ == "__main__":
    print(build())
