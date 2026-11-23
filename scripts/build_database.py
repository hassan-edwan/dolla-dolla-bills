"""Build the full company database from free sources.

    export DDB_SEC_USER_AGENT="dolla-dolla-bills you@example.com"
    python scripts/build_database.py --download          # first time: fetch SEC bulk files (~3GB)
    python scripts/build_database.py                     # rebuild everything from the bulk files
    python scripts/build_database.py --steps prices      # one step

Steps: companies -> fundamentals -> macro -> research -> prices -> alpaca -> insiders
(congress is separate and opt-in: see docs/RESEARCH_TRACKS.md #9)
"""
import argparse
import subprocess

from ddb.config import DATA_DIR
from ddb.data.http import sec_user_agent

STEPS = ["companies", "fundamentals", "macro", "research", "prices", "alpaca", "insiders"]
BULK = {"submissions.zip": "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip",
        "companyfacts.zip": "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip"}


def download():
    out = DATA_DIR / "raw" / "sec"
    out.mkdir(parents=True, exist_ok=True)
    for name, url in BULK.items():
        print(f"downloading {name} ...", flush=True)
        subprocess.run(["curl", "-s", "--retry", "5", "-C", "-", "-A", sec_user_agent(),
                        "-o", str(out / name), url], check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--steps", nargs="*", default=STEPS, choices=STEPS)
    a = ap.parse_args()
    if a.download:
        download()
    for step in a.steps:
        print(f"== {step}", flush=True)
        if step == "companies":
            from ddb.db.build_companies import build
            print(build())
        elif step == "fundamentals":
            from ddb.db.build_fundamentals import build
            print(build())
        elif step == "macro":
            from ddb.db.build_macro import build
            print(build())
        elif step == "research":
            from ddb.db.research import run
            print(run())
        elif step == "prices":
            from ddb.db.build_prices import build
            print(build())
        elif step == "alpaca":
            from ddb.db.build_alpaca import build   # needs a free Alpaca key (~/.config/ddb/alpaca.env)
            print(build())
        elif step == "insiders":
            from ddb.db.build_insiders import build
            print(build())


if __name__ == "__main__":
    main()
