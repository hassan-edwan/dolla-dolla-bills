"""Copy FRED market series into the macro table (point-in-time)."""
from __future__ import annotations

import pandas as pd

from ..config import DATA_DIR
from ..data.fred import MARKET_SERIES, fetch_series
from ..data.http import RateLimitedSession
from .schema import connect

DB_PATH = DATA_DIR / "ddb.duckdb"


def build(db_path=DB_PATH) -> dict:
    con = connect(db_path)
    session = RateLimitedSession(min_interval_s=1.0, timeout_s=30, retries=2)
    out = {}
    for sid in MARKET_SERIES:
        try:
            df = fetch_series(sid, session)
        except Exception as exc:  # noqa: BLE001
            out[sid] = f"failed: {exc!r}"
            continue
        m = pd.DataFrame({"series": sid, "date": df["period_end"].dt.date, "value": df["value"],
                          "source": "fred", "knowable_at": df["knowable_at"]})
        con.execute("DELETE FROM macro WHERE series = ?", [sid])
        con.register("m", m)
        con.execute("INSERT INTO macro SELECT * FROM m")
        con.unregister("m")
        out[sid] = len(m)
    con.close()
    return out
