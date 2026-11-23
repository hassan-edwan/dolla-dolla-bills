"""Bottleneck / development / stagnation language in SEC filing text.

EDGAR full-text search (efts.sec.gov, 2001+) for each phrase in
configs/news.yaml, per quarter. Keeps hits for companies in the database.
One row per (filing document, phrase). knowable_at = SEC acceptance time of
the filing (joined from `filings`), else the file date + 22h.

    python -m ddb.news.filing_signals [--start 2001]
"""
from __future__ import annotations

import argparse
import re
import time

import pandas as pd
import yaml

from ..config import CONFIG_DIR, DATA_DIR
from ..data.http import RateLimitedSession, sec_user_agent
from ..db.schema import connect

OUT = DATA_DIR / "db" / "filing_text_signals"
API = "https://efts.sec.gov/LATEST/search-index"
FORMS = "10-K,10-Q,8-K,20-F,40-F,6-K,S-1,424B4"
DB_PATH = DATA_DIR / "ddb.duckdb"


def _quarters(start_year: int):
    for q in pd.period_range(f"{start_year}Q1", pd.Timestamp.now().to_period("Q"), freq="Q"):
        yield q.start_time.strftime("%Y-%m-%d"), q.end_time.strftime("%Y-%m-%d")


def _search(session, phrase: str, start: str, end: str, ciks: set[int]) -> tuple[list[dict], int]:
    rows, offset, total = [], 0, 0
    while True:
        params = {"q": f'"{phrase}"', "forms": FORMS, "startdt": start, "enddt": end, "from": offset}
        d = None
        for k in range(5):
            try:
                d = session.get(API, params=params).json()
                break
            except Exception:  # noqa: BLE001 - transient errors / non-JSON
                time.sleep(2 ** k)
        if d is None or "hits" not in d:
            break
        hits = d["hits"]["hits"]
        total = d["hits"]["total"]["value"]
        for h in hits:
            src = h["_source"]
            for c in src.get("ciks", []):
                c = int(c)
                if c in ciks:
                    rows.append({"cik": c, "accession": src.get("adsh"), "document": h["_id"].split(":", 1)[-1],
                                 "form": src.get("form"), "file_date": src.get("file_date"),
                                 "period_ending": src.get("period_ending")})
        offset += len(hits)
        if not hits or offset >= min(total, 10000):
            break
    return rows, total


def build(start_year: int = 2001, db_path=DB_PATH) -> dict:
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    cfg = yaml.safe_load((CONFIG_DIR / "news.yaml").read_text())["filing_phrases"]
    con = connect(db_path, read_only=True)
    ciks = set(con.execute("SELECT cik FROM companies").df()["cik"].astype(int))
    acc = con.execute("SELECT accession, min(acceptance) AS acceptance FROM filings GROUP BY 1").df()
    con.close()
    s = RateLimitedSession(min_interval_s=0.12, user_agent=sec_user_agent())
    summary = {}
    for signal, phrases in cfg.items():
        for phrase in phrases:
            out = OUT / f"{signal}__{re.sub(r'[^a-z0-9]+', '_', phrase.lower()).strip('_')}.parquet"
            if out.exists():
                continue
            rows, capped = [], 0
            for a, b in _quarters(start_year):
                r, total = _search(s, phrase, a, b, ciks)
                rows += r
                capped += total > 10000
            df = pd.DataFrame(rows, columns=["cik", "accession", "document", "form", "file_date", "period_ending"])
            df["signal"], df["phrase"] = signal, phrase
            df["file_date"] = pd.to_datetime(df["file_date"], errors="coerce")
            df = df.merge(acc, on="accession", how="left")
            df["knowable_at"] = df["acceptance"].fillna(
                (df["file_date"] + pd.Timedelta(hours=22)).dt.tz_localize("UTC"))
            df.drop(columns="acceptance").to_parquet(out, index=False)
            summary[phrase] = len(df)
            print(f"  [{signal}] {phrase!r}: {len(df):,} filings (quarters capped at 10k: {capped}) "
                  f"{time.time() - t0:.0f}s", flush=True)
    return {"phrases": len(summary), "rows": sum(summary.values()), "seconds": round(time.time() - t0)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=2001)
    print(build(ap.parse_args().start))
