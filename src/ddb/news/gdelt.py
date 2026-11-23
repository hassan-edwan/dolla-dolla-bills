"""GDELT 2.0 Global Knowledge Graph -> filtered news events (2015-02-18 -> now).

Each 15-minute GKG file (~5-10MB zipped) is streamed, never stored. An article
is kept if
  (a) one of its organizations exactly matches a tracked company alias, or
  (b) it carries an industry theme AND a bottleneck/development/stagnation theme.
One output row per kept article: time, source, url, matched CIKs, industries,
signals, tone. knowable_at = the file's timestamp + 15 minutes.

Full history is ~2.5TB of downloads, so run the backfill on the HPC
(hpc/gdelt_backfill.sbatch, one job per month). Here: recent windows and
live updates.

    python -m ddb.news.gdelt --start 2026-11-01 --end 2026-11-23 [--aliases data/reference/gdelt_aliases.csv]
    python -m ddb.news.gdelt --make-aliases      # (re)build the alias file from the database
"""
from __future__ import annotations

import argparse
import io
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import requests
import yaml

from ..config import CONFIG_DIR, DATA_DIR, ROOT
from ..db.research import norm_name

OUT = DATA_DIR / "db" / "news_events"
ALIASES = ROOT / "data" / "reference" / "gdelt_aliases.csv"
BASE = "http://data.gdeltproject.org/gdeltv2/{ts}.gkg.csv.zip"
# Single-word names that are ordinary words would match unrelated news.
COMMON = set("""
energy power solar quantum space matrix frontier pioneer summit apex vertex atlas titan phoenix eagle liberty
patriot global united national american first general nova orbit fusion spark element vector signal beacon
horizon genesis catalyst velocity momentum mobile digital target alpha omega prime core focus impact vista
constellation enterprise venture capital resources natural electric precision advanced applied integrated
universal pacific atlantic western eastern northern southern central international standard premier
""".split())


def make_aliases(db_path=DATA_DIR / "ddb.duckdb", out: Path = ALIASES) -> pd.DataFrame:
    from ..db.schema import connect
    con = connect(db_path, read_only=True)
    df = con.execute("""
        SELECT DISTINCT n.cik, n.name, c.is_current_listed
        FROM company_names n JOIN companies c USING (cik)
        WHERE c.last_filing >= DATE '2014-01-01'
          AND (n.valid_to IS NULL OR n.valid_to >= DATE '2015-01-01')
    """).df()
    con.close()
    df["alias"] = df["name"].map(norm_name)
    single = ~df["alias"].str.contains(" ")
    df = df[(df["alias"].str.len() >= 4)
            & ~(single & (df["alias"].str.len() < 5))
            & ~(single & df["alias"].isin(COMMON))]
    uniq = df.groupby("alias")["cik"].nunique()
    df = df[df["alias"].isin(uniq[uniq == 1].index)][["alias", "cik"]].drop_duplicates()
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    return df


def _load_cfg():
    c = yaml.safe_load((CONFIG_DIR / "news.yaml").read_text())["gdelt"]
    theme_ind = {t: ind for ind, ts in c["themes"].items() for t in ts}
    theme_sig = {t: sig for sig, ts in c["signal_themes"].items() for t in ts}
    return theme_ind, theme_sig


def process_file(ts: str, session, aliases: dict, theme_ind: dict, theme_sig: dict) -> list[dict] | None:
    for k in range(3):
        try:
            r = session.get(BASE.format(ts=ts), timeout=120)
            if r.status_code == 404:
                return []           # GDELT has occasional gaps
            if r.status_code == 200:
                break
        except requests.RequestException:
            pass
        time.sleep(3 * (k + 1))
    else:
        return None
    try:
        z = zipfile.ZipFile(io.BytesIO(r.content))
    except zipfile.BadZipFile:
        return []
    known = pd.Timestamp(ts, tz="UTC") + pd.Timedelta(minutes=15)
    rows = []
    for line in io.TextIOWrapper(z.open(z.namelist()[0]), encoding="utf-8", errors="ignore"):
        f = line.rstrip("\n").split("\t")
        if len(f) < 16:
            continue
        themes = {t for t in f[7].split(";") if t}
        orgs = {norm_name(o) for o in f[13].split(";") if o}
        ciks = sorted({aliases[o] for o in orgs if o in aliases})
        inds = sorted({theme_ind[t] for t in themes if t in theme_ind})
        sigs = sorted({theme_sig[t] for t in themes if t in theme_sig})
        if not ciks and not (inds and sigs):
            continue
        try:
            tone = float(f[15].split(",")[0])
        except ValueError:
            tone = None
        rows.append({"published": pd.to_datetime(f[1], format="%Y%m%d%H%M%S", utc=True, errors="coerce"),
                     "source": f[3], "url": f[4], "ciks": ciks, "industries": inds, "signals": sigs,
                     "tone": tone, "n_orgs": len(orgs), "knowable_at": known})
    return rows


def run(start: str, end: str, aliases_path: Path = ALIASES, workers: int = 4, every: int = 1,
        newest_first: bool = False) -> dict:
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    al = pd.read_csv(aliases_path)
    aliases = dict(zip(al["alias"], al["cik"].astype(int)))
    theme_ind, theme_sig = _load_cfg()
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0 (ddb research)"
    total, days = 0, 0
    days_list = list(pd.date_range(start, end, freq="D"))
    for day in (reversed(days_list) if newest_first else days_list):
        out = OUT / f"gdelt_{day:%Y%m%d}.parquet"
        if out.exists():
            continue
        stamps = [t.strftime("%Y%m%d%H%M%S") for t in pd.date_range(day, day + pd.Timedelta(hours=23, minutes=45),
                                                                     freq="15min")][::every]
        if day < pd.Timestamp("2015-02-18"):
            continue
        with ThreadPoolExecutor(workers) as ex:
            results = list(ex.map(lambda ts: process_file(ts, s, aliases, theme_ind, theme_sig), stamps))
        if any(r is None for r in results):
            print(f"  {day:%Y-%m-%d}: download failures, will retry next run", flush=True)
            continue
        rows = [x for r in results for x in r]
        df = pd.DataFrame(rows, columns=["published", "source", "url", "ciks", "industries", "signals",
                                         "tone", "n_orgs", "knowable_at"])
        df["files_sampled"] = len(stamps)
        df.to_parquet(out, index=False)
        total += len(df)
        days += 1
        print(f"  {day:%Y-%m-%d}: {len(df):,} articles kept ({sum(len(c) > 0 for c in df['ciks']):,} name a company) "
              f"{time.time() - t0:.0f}s", flush=True)
    return {"days": days, "articles": total, "seconds": round(time.time() - t0)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--aliases", type=Path, default=ALIASES)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--every", type=int, default=1, help="sample every Nth 15-minute file")
    ap.add_argument("--make-aliases", action="store_true")
    ap.add_argument("--newest-first", action="store_true")
    a = ap.parse_args()
    if a.make_aliases:
        print(len(make_aliases()), "aliases")
    else:
        print(run(a.start, a.end, a.aliases, a.workers, a.every, a.newest_first))
