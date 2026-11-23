"""Legislators and dated committee seats (public domain: unitedstates/congress-legislators).

- legislators: every member with bioguide id, name, and terms (chamber, state,
  district, party, start/end).
- committee_seats: built from the git history of committee-membership-current.yaml
  (211+ snapshots since Nov 2012). A seat is valid from the first snapshot
  that shows it until the first snapshot where it is gone. knowable_at = that
  snapshot's commit date, which is a little after the real assignment, so it errs safe.
- committee_industries: config mapping committee -> industries overseen.

    python -m ddb.db.build_committees
"""
from __future__ import annotations

import subprocess
import time

import pandas as pd
import yaml

from ..config import CONFIG_DIR, DATA_DIR
from .schema import connect

RAW = DATA_DIR / "raw" / "congress"
REPO = RAW / "cl-repo"
DB_PATH = DATA_DIR / "ddb.duckdb"
SNAP_FILE = "committee-membership-current.yaml"
YAML_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def _git(*args) -> str:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, check=True).stdout


def legislators() -> tuple[pd.DataFrame, pd.DataFrame]:
    people, terms = [], []
    for f in ("legislators-historical.yaml", "legislators-current.yaml"):
        for p in yaml.load((RAW / f).read_text(), Loader=YAML_LOADER):
            bid = p["id"].get("bioguide")
            last_term_end = p["terms"][-1].get("end", "")
            if last_term_end and last_term_end < "2005-01-01":
                continue
            n = p.get("name", {})
            people.append({"bioguide": bid, "first": n.get("first"), "last": n.get("last"),
                           "official_full": n.get("official_full"), "nickname": n.get("nickname")})
            for t in p["terms"]:
                terms.append({"bioguide": bid, "chamber": "house" if t["type"] == "rep" else "senate",
                              "state": t.get("state"), "district": t.get("district"), "party": t.get("party"),
                              "start": pd.Timestamp(t["start"]), "end": pd.Timestamp(t["end"])})
    return pd.DataFrame(people).drop_duplicates("bioguide"), pd.DataFrame(terms)


def committee_seats() -> pd.DataFrame:
    commits = [line.split() for line in _git("log", "--reverse", "--format=%H %cI", "--", SNAP_FILE).splitlines()]
    snaps = []
    for sha, when in commits:
        try:
            doc = yaml.load(_git("show", f"{sha}:{SNAP_FILE}"), Loader=YAML_LOADER) or {}
        except subprocess.CalledProcessError:
            continue
        seats = set()
        for cid, members in doc.items():
            for m in members or []:
                seats.add((cid, m.get("bioguide"), m.get("party"), m.get("rank"), m.get("title") or ""))
        snaps.append((pd.Timestamp(when).tz_convert("UTC"), seats))
    rows, open_ = [], {}
    for when, seats in snaps:
        for s in seats - set(open_):
            open_[s] = when
        for s in [s for s in open_ if s not in seats]:
            rows.append((*s, open_.pop(s), when))
    for s, start in open_.items():
        rows.append((*s, start, pd.NaT))
    df = pd.DataFrame(rows, columns=["committee_id", "bioguide", "party", "rank", "title", "valid_from", "valid_to"])
    df["parent_committee"] = df["committee_id"].str[:4]
    df["is_subcommittee"] = df["committee_id"].str.len() > 4
    df["knowable_at"] = df["valid_from"]
    # Rank changes inside a seat create a new row. Collapse to the (member, committee) level too.
    return df


def build(db_path=DB_PATH) -> dict:
    t0 = time.time()
    people, terms = legislators()
    seats = committee_seats()
    cfg = yaml.safe_load((CONFIG_DIR / "committees.yaml").read_text())["committees"]
    cmap = pd.DataFrame([{"committee_id": k, "committee_name": v["name"], "industry": ind}
                         for k, v in cfg.items() for ind in v["industries"]])
    con = connect(db_path)
    for name, df in (("legislators", people), ("legislator_terms", terms),
                     ("committee_seats", seats), ("committee_industries", cmap)):
        con.register("x", df)
        con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM x")
        con.unregister("x")
    con.close()
    return {"legislators": len(people), "terms": len(terms), "seat_rows": len(seats),
            "snapshots": int(seats["valid_from"].nunique()), "seconds": round(time.time() - t0)}


if __name__ == "__main__":
    print(build())
