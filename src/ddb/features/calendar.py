"""Expected next earnings date per company, from its own past results filings.

Free data has no forward earnings calendar, so the next date is estimated from
the company's history of results 8-Ks (item 2.02), using only filings public at
the as-of time:
- preferred: a year after the report three reports ago (companies report at
  about the same time each year), when that lands 40-140 days after the last one;
- otherwise: the last report plus the median gap between recent reports.
A date already passed without a report means "due any day" (overdue).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def expected_earnings(con, t, ciks=None) -> pd.DataFrame:
    """cik, last_report, next_expected, days_to (calendar days from t), overdue, method."""
    t = pd.Timestamp(t)
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    where = "" if ciks is None else f"AND cik IN ({','.join(str(int(c)) for c in ciks) or 'NULL'})"
    df = con.execute(f"""
        SELECT cik, CAST(timezone('America/New_York', acceptance) AS DATE) AS d
        FROM filings
        WHERE form LIKE '8-K%' AND items LIKE '%2.02%' AND acceptance IS NOT NULL
          AND knowable_at <= TIMESTAMPTZ '{t.isoformat()}'
          AND filing_date >= DATE '{(t - pd.Timedelta(days=4 * 365)).date()}' {where}
    """).df()
    return estimate_next(df, t)


def estimate_next(df: pd.DataFrame, t: pd.Timestamp) -> pd.DataFrame:
    cols = ["cik", "last_report", "next_expected", "days_to", "overdue", "method"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    t0 = pd.Timestamp(t).tz_localize(None).normalize() if pd.Timestamp(t).tzinfo else pd.Timestamp(t).normalize()
    rows = []
    for cik, g in df.groupby("cik"):
        d = sorted(pd.to_datetime(g["d"]).unique())
        keep = [d[0]]                     # one report per results window (drop amendments within 20 days)
        for x in d[1:]:
            if (x - keep[-1]).days > 20:
                keep.append(x)
        last = keep[-1]
        nxt, method = None, None
        if len(keep) >= 4:
            cand = keep[-4] + pd.Timedelta(days=364)
            if 40 <= (cand - last).days <= 140:
                nxt, method = cand, "same time last year"
        if nxt is None and len(keep) >= 2:
            gap = float(np.median(np.diff(keep[-5:]).astype("timedelta64[D]").astype(int)))
            nxt, method = last + pd.Timedelta(days=gap), "typical gap"
        if nxt is None:
            nxt, method = last + pd.Timedelta(days=91), "one report only"
        overdue = nxt < t0
        rows.append((int(cik), last, t0 if overdue else nxt, 0 if overdue else (nxt - t0).days, bool(overdue), method))
    return pd.DataFrame(rows, columns=cols)


def trading_days_between(a: pd.Timestamp, b: pd.Timestamp) -> int:
    return max(int(np.busday_count(pd.Timestamp(a).date(), pd.Timestamp(b).date())), 0)
