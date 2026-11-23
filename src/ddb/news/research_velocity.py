"""Research velocity: arXiv papers per month per topic (free API, 2007+).

Counts come from the API's totalResults for each month's submittedDate
window. knowable_at = the first day after the month ends. Papers are
public on submission, but a whole month's count isn't known until it's over.
arXiv asks for one request every 3 seconds.

    python -m ddb.news.research_velocity [--start 2007]
"""
from __future__ import annotations

import argparse
import re
import time

import pandas as pd
import requests
import yaml

from ..config import CONFIG_DIR, DATA_DIR

OUT = DATA_DIR / "db" / "research_velocity"
API = "https://export.arxiv.org/api/query"


def count(session, query: str, month: pd.Period) -> int | None:
    a = month.start_time.strftime("%Y%m%d0000")
    b = month.end_time.strftime("%Y%m%d2359")
    q = f"({query}) AND submittedDate:[{a} TO {b}]"
    for k in range(4):
        try:
            # max_results=0 can trigger server errors; an error page also reports
            # totalResults=1, so detect it explicitly and retry.
            r = session.get(API, params={"search_query": q, "max_results": 1}, timeout=60)
            if r.status_code == 200 and "internal error" not in r.text and "<title>Error</title>" not in r.text:
                m = re.search(r"<opensearch:totalResults[^>]*>(\d+)<", r.text)
                if m:
                    return int(m.group(1))
        except requests.RequestException:
            pass
        time.sleep(5 * (k + 1))
    return None


def build(start: int = 2007) -> dict:
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    topics = yaml.safe_load((CONFIG_DIR / "news.yaml").read_text())["arxiv_topics"]
    s = requests.Session()
    s.headers["User-Agent"] = "ddb-research/0.1 (personal research project)"
    months = pd.period_range(f"{start}-01", (pd.Timestamp.now() - pd.offsets.MonthBegin(1)).to_period("M"), freq="M")
    total = 0
    for topic, query in topics.items():
        out = OUT / f"{topic}.parquet"
        if out.exists():
            continue
        rows = []
        for m in months:
            rows.append({"topic": topic, "month": m.start_time, "papers": count(s, query, m)})
            time.sleep(3)
        df = pd.DataFrame(rows)
        df["knowable_at"] = (df["month"] + pd.offsets.MonthBegin(1)).dt.tz_localize("UTC")
        df.to_parquet(out, index=False)
        total += len(df)
        print(f"  {topic}: {len(df)} months, latest {df['papers'].iloc[-1]} papers {time.time() - t0:.0f}s", flush=True)
    return {"rows": total, "seconds": round(time.time() - t0)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=2007)
    print(build(ap.parse_args().start))
