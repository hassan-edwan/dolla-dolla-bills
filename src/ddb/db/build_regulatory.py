"""Federal Register documents for industry-relevant agencies (free API, 1994+).

Rules, proposed rules, notices and presidential documents, with title and
abstract. knowable_at = 06:00 ET on the publication date (the Federal Register
is posted early morning), i.e. 11:00 UTC. Documents put on "public inspection"
a day earlier are ignored, which errs safe.

The API caps a query at 10,000 results, so we query per agency per year.

    python -m ddb.db.build_regulatory [--start 2005]
"""
from __future__ import annotations

import argparse
import time

import pandas as pd
import requests
import yaml

from ..config import CONFIG_DIR, DATA_DIR

OUT = DATA_DIR / "db" / "regulatory_documents"
API = "https://www.federalregister.gov/api/v1/documents.json"
FIELDS = ["document_number", "publication_date", "type", "title", "abstract", "agencies",
          "action", "significant", "html_url", "docket_ids", "effective_on", "comments_close_on"]


def fetch(session, agency: str, year: int) -> list[dict]:
    rows, page = [], 1
    while True:
        params = [("per_page", 1000), ("page", page), ("order", "oldest"),
                  ("conditions[agencies][]", agency),
                  ("conditions[publication_date][gte]", f"{year}-01-01"),
                  ("conditions[publication_date][lte]", f"{year}-12-31")] + [("fields[]", f) for f in FIELDS]
        d = None
        for k in range(6):   # rate limits come back as HTML: back off and retry
            try:
                r = session.get(API, params=params, timeout=90)
                if r.status_code == 200:
                    d = r.json()
                    break
            except (requests.RequestException, ValueError):
                pass
            time.sleep(5 * 2 ** k)
        if d is None:
            raise RuntimeError(f"Federal Register: gave up on {agency} {year} page {page}")
        rows.extend(d.get("results") or [])
        if not d.get("next_page_url"):
            return rows
        page += 1
        time.sleep(0.3)


def build(start: int = 2005) -> dict:
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    agencies = yaml.safe_load((CONFIG_DIR / "regulators.yaml").read_text())["agencies"]
    s = requests.Session()
    s.headers["User-Agent"] = "python-requests (research)"
    total = 0
    for agency, inds in agencies.items():
        out = OUT / f"{agency}.parquet"
        if out.exists():
            total += len(pd.read_parquet(out, columns=["document_number"]))
            continue
        rows = []
        for y in range(start, pd.Timestamp.now().year + 1):
            rows += fetch(s, agency, y)
        df = pd.DataFrame(rows)
        if df.empty:
            continue
        df["agency"] = agency
        df["industries"] = [inds] * len(df)
        df["publication_date"] = pd.to_datetime(df["publication_date"])
        df["knowable_at"] = (df["publication_date"] + pd.Timedelta(hours=11)).dt.tz_localize("UTC")
        df["agencies"] = df["agencies"].map(lambda a: ";".join(x.get("name") or x.get("raw_name") or "" for x in (a or [])))
        df["docket_ids"] = df["docket_ids"].map(lambda a: ";".join(a or []))
        for c in ("effective_on", "comments_close_on"):
            df[c] = pd.to_datetime(df[c], errors="coerce")
        df.to_parquet(out, index=False)
        total += len(df)
        print(f"  {agency}: {len(df):,} docs (total {total:,}) {time.time() - t0:.0f}s", flush=True)
    return {"documents": total, "seconds": round(time.time() - t0)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=2005)
    print(build(ap.parse_args().start))
