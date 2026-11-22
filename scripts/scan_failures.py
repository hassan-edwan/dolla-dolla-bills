"""Build/extend the failure ledger from SEC EDGAR's quarterly full index.

Finds every delisting (Form 25 / 25-NSE) and deregistration (Form 15) filing,
which covers companies that no longer exist in free price sources. Then, for
companies in the configured universe, adds 8-K bankruptcy, delisting-notice
and dilution signals from their submissions history.

    export DDB_SEC_USER_AGENT="dolla-dolla-bills you@example.com"
    python scripts/scan_failures.py --years 2015 2026
"""
import argparse

import pandas as pd

from ddb.config import DATA_DIR, universe_symbols
from ddb.data import edgar
from ddb.data.failures import FailureLedger

LEDGER = DATA_DIR / "failures" / "ledger.csv"
EVENTS = DATA_DIR / "failures" / "universe_events.parquet"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", nargs=2, type=int, default=[2015, 2026])
    ap.add_argument("--skip-universe", action="store_true")
    args = ap.parse_args()

    ledger = FailureLedger.load(LEDGER)
    exits = edgar.exit_filings(range(args.years[0], args.years[1] + 1))
    print(f"exit filings found: {len(exits)}")
    print(exits["event_type"].value_counts().to_string())

    tickers = edgar.current_tickers()
    added = ledger.merge_edgar_exits(exits, still_listed_ciks=tickers["cik"])
    ledger.save(LEDGER)
    print(f"ledger: +{added} rows -> {LEDGER}")

    if args.skip_universe:
        return
    sym_to_cik = dict(zip(tickers["ticker"], tickers["cik"]))
    syms = sorted({s for g, v in universe_symbols().items() if g not in ("haven", "benchmarks") for s in v})
    frames = []
    for s in syms:
        cik = sym_to_cik.get(s)
        if cik is None:
            print(f"  {s}: no CIK in SEC ticker map")
            continue
        ev = edgar.filing_events(edgar.submissions(cik))
        ev["symbol"] = s
        frames.append(ev)
    events = pd.concat(frames, ignore_index=True)
    events.to_parquet(EVENTS, index=False)
    print(f"universe events: {len(events)} -> {EVENTS}")
    print(events.groupby("event_type").size().to_string())


if __name__ == "__main__":
    main()
