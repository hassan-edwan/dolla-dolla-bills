"""Public attention: Wikipedia daily pageviews (2015-07+), free Wikimedia API.

Company articles come from Wikidata, via the SEC CIK property (P5531) ->
English Wikipedia article. Industry topic articles come from configs/news.yaml.
knowable_at = the day after the date (daily counts are published after the day ends).

    python -m ddb.news.attention
"""
from __future__ import annotations

import time
from urllib.parse import quote, unquote

import pandas as pd
import requests
import yaml

from ..config import CONFIG_DIR, DATA_DIR
from ..db.schema import connect

OUT = DATA_DIR / "db" / "wiki_pageviews"
DB_PATH = DATA_DIR / "ddb.duckdb"
SPARQL = "https://query.wikidata.org/sparql"
PV = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/"
      "{title}/daily/20150701/{end}")
HEADERS = {"User-Agent": "ddb-research/0.1 (personal research project)"}


def cik_articles() -> pd.DataFrame:
    q = """SELECT ?item ?cik ?article WHERE {
             ?item wdt:P5531 ?cik .
             ?article schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> . }"""
    r = requests.get(SPARQL, params={"query": q}, headers={**HEADERS, "Accept": "application/sparql-results+json"},
                     timeout=300)
    b = [x for x in r.json()["results"]["bindings"] if x["cik"]["value"].strip().isdigit()]   # skip "unknown value" nodes
    df = pd.DataFrame({"cik": [int(x["cik"]["value"]) for x in b],
                       "article": [unquote(x["article"]["value"].rsplit("/wiki/", 1)[-1]) for x in b],
                       "wikidata": [x["item"]["value"].rsplit("/", 1)[-1] for x in b]})
    return df.drop_duplicates(["cik", "article"])


def pageviews(session, title: str) -> pd.DataFrame:
    end = (pd.Timestamp.now() - pd.Timedelta(days=1)).strftime("%Y%m%d")
    for k in range(4):
        r = session.get(PV.format(title=quote(title, safe=""), end=end), timeout=60)
        if r.status_code == 200:
            items = r.json().get("items", [])
            return pd.DataFrame({"date": pd.to_datetime([i["timestamp"][:8] for i in items]),
                                 "views": [i["views"] for i in items]})
        if r.status_code == 404:
            return pd.DataFrame(columns=["date", "views"])
        time.sleep(2 ** k)
    return pd.DataFrame(columns=["date", "views"])


def build(db_path=DB_PATH) -> dict:
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    con = connect(db_path, read_only=True)
    ours = set(con.execute("SELECT cik FROM companies").df()["cik"].astype(int))
    con.close()
    arts = cik_articles()
    arts = arts[arts["cik"].isin(ours)]
    topics = yaml.safe_load((CONFIG_DIR / "news.yaml").read_text())["wikipedia_topics"]
    jobs = [("company", int(r.cik), None, r.article) for r in arts.itertuples(index=False)]
    jobs += [("topic", None, ind, t) for ind, ts in topics.items() for t in ts]
    s = requests.Session()
    s.headers.update(HEADERS)
    frames, n = [], 0
    for k, (kind, cik, ind, title) in enumerate(jobs):
        pv = pageviews(s, title)
        if not pv.empty:
            pv["entity_type"], pv["cik"], pv["industry"], pv["article"] = kind, cik, ind, title
            frames.append(pv)
            n += len(pv)
        time.sleep(0.05)
        if k % 250 == 0:
            print(f"  {k + 1}/{len(jobs)} articles, {n:,} daily rows, {time.time() - t0:.0f}s", flush=True)
    df = pd.concat(frames, ignore_index=True)
    df["cik"] = df["cik"].astype("Int64")
    df["knowable_at"] = (df["date"] + pd.Timedelta(days=1)).dt.tz_localize("UTC")
    df.to_parquet(OUT / "pageviews.parquet", index=False)
    return {"company_articles": len(arts), "topic_articles": len(jobs) - len(arts), "rows": len(df),
            "seconds": round(time.time() - t0)}


if __name__ == "__main__":
    print(build())
