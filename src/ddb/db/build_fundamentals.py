"""Load XBRL company facts for every company in the database (SEC bulk
``companyfacts.zip``) into Parquet, one row per fact VERSION.

Each filing re-reports prior periods. We keep every (period, accession) row,
so a restated number only appears from the date its amending filing was
accepted. knowable_at = acceptance time of the filing (joined from the
filings table) or, if unknown, the filed date + 1 day.

    python -m ddb.db.build_fundamentals
"""
from __future__ import annotations

import json
import time
import zipfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from ..config import DATA_DIR
from .schema import connect

FACTS_ZIP = DATA_DIR / "raw" / "sec" / "companyfacts.zip"
OUT_DIR = DATA_DIR / "db" / "fundamentals"
DB_PATH = DATA_DIR / "ddb.duckdb"

SCHEMA = pa.schema([
    ("cik", pa.int64()), ("taxonomy", pa.string()), ("concept", pa.string()), ("unit", pa.string()),
    ("value", pa.float64()), ("period_start", pa.date32()), ("period_end", pa.date32()),
    ("fy", pa.int32()), ("fp", pa.string()), ("form", pa.string()), ("accession", pa.string()),
    ("filed", pa.date32()), ("frame", pa.string()),
])


def _rows(d: dict):
    cik = int(d["cik"])
    for tax, concepts in d.get("facts", {}).items():
        for concept, body in concepts.items():
            for unit, obs in body.get("units", {}).items():
                for o in obs:
                    if "filed" not in o or "end" not in o:
                        continue
                    yield (cik, tax, concept, unit, o.get("val"), o.get("start"), o["end"],
                           o.get("fy"), o.get("fp"), o.get("form"), o.get("accn"), o["filed"],
                           o.get("frame"))


def _process(args):
    names, part, zip_path, out_dir = args
    z = zipfile.ZipFile(zip_path)
    cols = [f.name for f in SCHEMA]
    buf = []
    for n in names:
        buf.extend(_rows(json.loads(z.read(n))))
    if not buf:
        return 0
    df = pd.DataFrame(buf, columns=cols)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    for c in ("period_start", "period_end", "filed"):
        df[c] = pd.to_datetime(df[c], errors="coerce").dt.date
    df["fy"] = pd.to_numeric(df["fy"], errors="coerce").astype("Int32")
    pq.write_table(pa.Table.from_pandas(df, schema=SCHEMA, preserve_index=False),
                   Path(out_dir) / f"part-{part:05d}.parquet", compression="zstd")
    return len(df)


def build(zip_path: Path = FACTS_ZIP, db_path: Path = DB_PATH, out_dir: Path = OUT_DIR,
          workers: int = 4, chunk: int = 150) -> dict:
    t0 = time.time()
    con = connect(db_path, read_only=True)
    ciks = set(con.execute("SELECT cik FROM companies").df()["cik"].astype(int))
    con.close()
    z = zipfile.ZipFile(zip_path)
    names = [n for n in z.namelist() if n.endswith(".json")
             and n.startswith("CIK") and int(n[3:13]) in ciks]
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.parquet"):
        old.unlink()
    jobs = [(names[i:i + chunk], k, str(zip_path), str(out_dir))
            for k, i in enumerate(range(0, len(names), chunk))]
    raw_dir = out_dir.parent / "fundamentals_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    for old in raw_dir.glob("part-*.parquet"):
        old.unlink()
    jobs = [(j[0], j[1], j[2], str(raw_dir)) for j in jobs]
    total = 0
    with ProcessPoolExecutor(workers) as ex:
        for k, n in enumerate(ex.map(_process, jobs)):
            total += n
            if k % 10 == 0:
                print(f"  part {k + 1}/{len(jobs)}  rows={total:,}  {time.time() - t0:.0f}s", flush=True)

    # knowable_at = acceptance time of the reporting filing (fallback: filed + 1 day).
    print("  joining acceptance times ...", flush=True)
    con = connect(db_path)
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"""
        COPY (
            SELECT f.*, CASE WHEN fl.acceptance IS NULL OR fl.acceptance < CAST(f.filed AS TIMESTAMPTZ) - INTERVAL 4 DAY
                             THEN CAST(f.filed + INTERVAL 1 DAY AS TIMESTAMPTZ) ELSE fl.acceptance END AS knowable_at
            FROM read_parquet('{raw_dir}/*.parquet') f
            LEFT JOIN (SELECT accession, min(acceptance) AS acceptance FROM filings GROUP BY 1) fl
              USING (accession)
        ) TO '{out_dir}' (FORMAT parquet, COMPRESSION zstd, PER_THREAD_OUTPUT true, OVERWRITE_OR_IGNORE true)
    """)
    con.close()
    for old in raw_dir.glob("part-*.parquet"):
        old.unlink()
    raw_dir.rmdir()
    return {"companies_with_xbrl": len(names), "fact_rows": total, "seconds": round(time.time() - t0)}


if __name__ == "__main__":
    print(build())
