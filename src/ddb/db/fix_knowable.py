"""Repair public times that are earlier than the official filing date by more than
the normal after-hours / weekend / holiday lag (4 days). Later is always safe.

The loaders apply the same rule (build_companies, build_fundamentals); this fixes a
database built before that rule. Idempotent.

    python -m ddb.db.fix_knowable
"""
from __future__ import annotations

from ..config import DATA_DIR
from .schema import connect

DB_PATH = DATA_DIR / "ddb.duckdb"
FUND = DATA_DIR / "db" / "fundamentals"


def run(db_path=DB_PATH) -> dict:
    con = connect(db_path)
    out = {}
    out["filings"] = con.execute("""
        UPDATE filings SET knowable_at = CAST(filing_date AS TIMESTAMPTZ) + INTERVAL 22 HOUR
        WHERE knowable_at < CAST(filing_date AS TIMESTAMPTZ) - INTERVAL 4 DAY""").fetchone()[0]
    out["events"] = con.execute("""
        UPDATE events SET knowable_at = CAST(event_date AS TIMESTAMPTZ) + INTERVAL 22 HOUR
        WHERE knowable_at < CAST(event_date AS TIMESTAMPTZ) - INTERVAL 4 DAY""").fetchone()[0]
    bad = con.execute("""SELECT count(*) FROM fundamentals
                         WHERE knowable_at < CAST(filed AS TIMESTAMPTZ) - INTERVAL 4 DAY""").fetchone()[0]
    out["fundamentals"] = bad
    if bad and FUND.exists():
        for f in sorted(FUND.glob("*.parquet")):
            n = con.execute(f"""SELECT count(*) FROM read_parquet('{f.as_posix()}')
                                WHERE knowable_at < CAST(filed AS TIMESTAMPTZ) - INTERVAL 4 DAY""").fetchone()[0]
            if not n:
                continue
            tmp = f.with_suffix(".tmp")
            con.execute(f"""COPY (SELECT * REPLACE (CASE WHEN knowable_at < CAST(filed AS TIMESTAMPTZ) - INTERVAL 4 DAY
                                      THEN CAST(filed + INTERVAL 1 DAY AS TIMESTAMPTZ) ELSE knowable_at END AS knowable_at)
                                  FROM read_parquet('{f.as_posix()}')) TO '{tmp.as_posix()}' (FORMAT parquet)""")
            tmp.replace(f)
    con.close()
    return out


if __name__ == "__main__":
    print(run())
