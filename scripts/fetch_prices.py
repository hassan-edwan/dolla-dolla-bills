"""Download daily prices for the configured universe into data/prices (Yahoo, free).

    python scripts/fetch_prices.py [--start 2010-01-01] [--groups tech energy haven benchmarks]
"""
import argparse
import json

from ddb.config import DATA_DIR, universe_symbols
from ddb.data.prices import cache_symbols


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2010-01-01")
    ap.add_argument("--groups", nargs="*", help="subset of groups (default: all)")
    args = ap.parse_args()
    groups = universe_symbols()
    chosen = {g: s for g, s in groups.items() if not args.groups or g in args.groups}
    symbols = sorted({s for v in chosen.values() for s in v})
    print(f"fetching {len(symbols)} symbols from {args.start}")
    errors = cache_symbols(symbols, DATA_DIR, start=args.start)
    print(f"ok: {len(symbols) - len(errors)}  failed: {len(errors)}")
    if errors:
        print(json.dumps(errors, indent=2))


if __name__ == "__main__":
    main()
