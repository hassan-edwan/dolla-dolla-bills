"""Download unrevised FRED market series into the point-in-time store."""
from ddb.config import DATA_DIR
from ddb.data.http import RateLimitedSession
from ddb.data.fred import MARKET_SERIES, fetch_series
from ddb.data.store import PointInTimeStore


def main():
    store = PointInTimeStore(DATA_DIR / "pit")
    session = RateLimitedSession(min_interval_s=1.0, timeout_s=30, retries=2)
    for sid in MARKET_SERIES:
        try:
            df = fetch_series(sid, session)
        except Exception as exc:  # noqa: BLE001
            print(f"{sid:14s} FAILED: {exc!r}")
            continue
        store.write("macro", df)
        print(f"{sid:14s} {len(df):6d} rows  {df['period_end'].min().date()} .. {df['period_end'].max().date()}")


if __name__ == "__main__":
    main()
