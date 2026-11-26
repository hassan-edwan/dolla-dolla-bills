"""FINRA consolidated short interest (free), twice a month, all exchange-listed + OTC stocks.

Files: https://cdn.finra.org/equity/otcmarket/biweekly/shrtYYYYMMDD.csv keyed by
settlement date (mid-month and month-end). FINRA publishes about 7 business days
after settlement, so knowable_at = settlement + 8 business days (22:00 UTC).

    python -m ddb.db.build_short_interest [--start 2014]
"""
from __future__ import annotations

import argparse
import io
import time

import pandas as pd
import requests

from ..config import DATA_DIR

OUT = DATA_DIR / "db" / "short_interest"
URL = "https://cdn.finra.org/equity/otcmarket/biweekly/shrt{d}.csv"


def candidates(month: pd.Period):
    mid = [month.start_time + pd.Timedelta(days=d) for d in (14, 13, 12, 11, 10)]
    end = [month.end_time.normalize() - pd.Timedelta(days=d) for d in range(0, 6)]
    return [mid, end]


def build(start: int = 2014) -> dict:
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers["User-Agent"] = "python-requests (research)"
    n_files = n_rows = 0
    for m in pd.period_range(f"{start}-01", pd.Timestamp.now().to_period("M"), freq="M"):
        for group in candidates(m):
            for d in group:
                if d.weekday() >= 5 or d > pd.Timestamp.now():
                    continue
                out = OUT / f"{d:%Y%m%d}.parquet"
                if out.exists():
                    n_files += 1
                    break
                try:
                    r = s.get(URL.format(d=f"{d:%Y%m%d}"), timeout=60)
                except requests.RequestException:
                    continue
                if r.status_code != 200 or len(r.content) < 1000:
                    continue
                df = pd.read_csv(io.BytesIO(r.content), sep="|", dtype=str, quoting=3, on_bad_lines="skip")
                df.columns = [c.strip('"') for c in df.columns]          # newer files quote every field
                df = df.apply(lambda col: col.str.strip('"'))
                df = pd.DataFrame({
                    "symbol": df["symbolCode"].str.upper(),
                    "settlement_date": pd.to_datetime(df["settlementDate"], errors="coerce"),
                    "short_interest": pd.to_numeric(df["currentShortPositionQuantity"], errors="coerce"),
                    "avg_daily_volume": pd.to_numeric(df["averageDailyVolumeQuantity"], errors="coerce"),
                    "days_to_cover": pd.to_numeric(df["daysToCoverQuantity"], errors="coerce"),
                    "market": df.get("marketClassCode"),
                })
                df["knowable_at"] = (df["settlement_date"] + pd.offsets.BDay(8) + pd.Timedelta(hours=22)).dt.tz_localize("UTC")
                df.to_parquet(out, index=False)
                n_files += 1
                n_rows += len(df)
                break
        if m.month == 12:
            print(f"  through {m}: {n_files} files, {n_rows:,} rows, {time.time() - t0:.0f}s", flush=True)
    return {"files": n_files, "rows": n_rows, "seconds": round(time.time() - t0)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=2014)
    print(build(ap.parse_args().start))
