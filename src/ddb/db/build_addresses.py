"""SEC business and mailing addresses for every company in the database.

Used by the investment screens (Israel: EDGAR state/country code L3). Source:
the `addresses` block of each company's EDGAR submissions JSON (the bulk file
downloaded by scripts/build_database.py --download). These are the CURRENT
addresses, like the SIC code; the screens treat them as identity data.

Output: data/db/company_addresses.parquet with cik, state_of_inc, business_city,
business_country_code, mailing_city, mailing_country_code (EDGAR codes: US
states as two letters, other countries as EDGAR codes, e.g. L3 = Israel).

    python -m ddb.db.build_addresses
"""
from __future__ import annotations

import json
import zipfile

import pandas as pd

from ..config import DATA_DIR
from .schema import connect

SUBMISSIONS_ZIP = DATA_DIR / "raw" / "sec" / "submissions.zip"
OUT = DATA_DIR / "db" / "company_addresses.parquet"
DB_PATH = DATA_DIR / "ddb.duckdb"


def extract(sub: dict) -> dict:
    a = sub.get("addresses") or {}
    b, m = a.get("business") or {}, a.get("mailing") or {}
    return {"state_of_inc": sub.get("stateOfIncorporation") or None,
            "business_city": b.get("city"), "business_country_code": b.get("stateOrCountry"),
            "mailing_city": m.get("city"), "mailing_country_code": m.get("stateOrCountry")}


def build(zip_path=SUBMISSIONS_ZIP, db_path=DB_PATH) -> dict:
    con = connect(db_path, read_only=True)
    ciks = set(con.execute("SELECT cik FROM companies").df()["cik"].astype(int))
    con.close()
    z = zipfile.ZipFile(zip_path)
    present = set(z.namelist())
    rows = []
    for cik in sorted(ciks):
        name = f"CIK{cik:010d}.json"
        if name in present:
            rows.append({"cik": cik, **extract(json.loads(z.read(name)))})
    df = pd.DataFrame(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT, index=False)
    return {"companies": len(ciks), "with_address": len(df),
            "israel_business": int((df["business_country_code"] == "L3").sum()) if len(df) else 0}


if __name__ == "__main__":
    print(build())
