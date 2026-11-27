"""Build everything from free sources, in dependency order, then check readiness.

    export DDB_SEC_USER_AGENT="dolla-dolla-bills you@example.com"   # SEC requires contact info
    # Alpaca steps need a free key in ~/.config/ddb/alpaca.env
    python scripts/build_all.py                 # everything except the slow optional downloads
    python scripts/build_all.py --download      # first run: also fetch the SEC bulk files (~3 GB)
    python scripts/build_all.py --full          # also 13F, intraday, spreads, congress, contracts, news
    python scripts/build_all.py --from panel    # resume from a step
    python scripts/build_all.py --list          # show the steps

A required step that fails stops the build (everything after depends on it);
an optional step that fails is reported and skipped. A log goes to
data/results/build_<time>.log, and the run ends with python -m ddb.rl.readiness.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable

# (name, command, required, in default run, what it needs)
STEPS = [
    # "--steps" with nothing after it: download only (without it, build_database.py also runs every step)
    ("download", [PY, "scripts/build_database.py", "--download", "--steps"], True, False, "network: sec.gov (~3 GB)"),
    ("database", [PY, "scripts/build_database.py", "--steps", "companies", "fundamentals", "macro", "research", "prices"],
     True, True, "SEC bulk files, Yahoo, FRED"),
    ("alpaca", [PY, "scripts/build_database.py", "--steps", "alpaca"], False, True, "Alpaca key (delisted prices)"),
    ("insiders", [PY, "scripts/build_database.py", "--steps", "insiders"], True, True, "sec.gov"),
    ("addresses", [PY, "-m", "ddb.db.build_addresses"], True, True, "SEC bulk files"),
    ("screens", [PY, "-m", "ddb.db.build_screens"], True, True, ""),
    ("short_interest", [PY, "-m", "ddb.db.build_short_interest"], False, True, "finra.org"),
    ("filing_signals", [PY, "-m", "ddb.news.filing_signals"], False, True, "efts.sec.gov (slow)"),
    ("congress", [PY, "-m", "ddb.db.build_congress"], False, False, "House Clerk, Senate eFD"),
    ("committees", [PY, "-m", "ddb.db.build_committees"], False, False, "GitHub congress-legislators"),
    ("contracts", [PY, "-m", "ddb.db.build_contracts"], False, False, "USAspending"),
    ("regulatory", [PY, "-m", "ddb.db.build_regulatory"], False, False, "Federal Register"),
    ("attention", [PY, "-m", "ddb.news.attention"], False, False, "Wikimedia"),
    ("research_velocity", [PY, "-m", "ddb.news.research_velocity"], False, False, "arXiv"),
    ("inst_holdings", [PY, "-m", "ddb.db.build_13f", "--since", "2015"], False, False, "sec.gov 13F data sets"),
    # register tables that loaders added as Parquet folders (read-only connections don't)
    ("views", [PY, "-c", "from ddb.db.schema import connect; from ddb.config import DATA_DIR; "
                          "connect(DATA_DIR / 'ddb.duckdb').close(); print('views refreshed')"], True, True, ""),
    ("panel", [PY, "-m", "ddb.features.panel"], True, True, ""),
    ("validate", [PY, "-m", "ddb.features.validate"], True, True, ""),
    ("daily", [PY, "-m", "ddb.features.daily"], True, True, ""),
    ("intraday_download", [PY, "-m", "ddb.db.build_intraday", "--max-symbols", "100"], False, False, "Alpaca key (hours)"),
    ("intraday", [PY, "-m", "ddb.features.intraday"], False, False, "minute bars"),
    ("spreads", [PY, "-m", "ddb.db.build_spreads"], False, False, "Alpaca key, intraday symbols"),
    ("regime", [PY, "-m", "ddb.features.regime"], True, True, ""),
    ("portfolio", [PY, "-m", "ddb.portfolio.model"], True, True, ""),
    ("rl_dataset", [PY, "-m", "ddb.rl.dataset"], True, True, ""),
    ("tracking", [PY, "-m", "ddb.live.tracking"], False, True, ""),
    ("baselines", [PY, "-m", "ddb.rl.baselines", "--split", "validation"], False, True, ""),
    ("readiness", [PY, "-m", "ddb.rl.readiness"], False, True, ""),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true", help="fetch SEC bulk files first")
    ap.add_argument("--full", action="store_true", help="include the slow optional sources")
    ap.add_argument("--from", dest="start", help="resume from this step")
    ap.add_argument("--only", nargs="*", help="run only these steps")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        for n, cmd, req, default, needs in STEPS:
            print(f"{n:18s} {'required' if req else 'optional':9s} {'default' if default else '--full':8s} {needs}")
        return
    steps = [s for s in STEPS if (s[3] or a.full or (s[0] == "download" and a.download))]
    if a.only:
        steps = [s for s in STEPS if s[0] in a.only]
    if a.start:
        names = [s[0] for s in steps]
        steps = steps[names.index(a.start):]
    log_dir = ROOT / "data" / "results"
    log_dir.mkdir(parents=True, exist_ok=True)
    log = log_dir / f"build_{time.strftime('%Y%m%d_%H%M%S')}.log"
    env = dict(os.environ, PYTHONWARNINGS="ignore")
    results = []
    with log.open("w") as lf:
        for name, cmd, required, _, needs in steps:
            t0 = time.time()
            print(f"\n=== {name} ({'required' if required else 'optional'}{'; ' + needs if needs else ''})", flush=True)
            lf.write(f"\n=== {name}: {' '.join(cmd)}\n")
            lf.flush()
            p = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            tail = []
            for line in p.stdout:
                sys.stdout.write(line)
                lf.write(line)
                tail = (tail + [line])[-5:]
            code = p.wait()
            dt = time.time() - t0
            ok = code == 0 or name == "readiness"     # readiness exits 1 when not ready; that's a result, not a crash
            results.append((name, ok, required, dt, code))
            lf.write(f"--- {name}: exit {code}, {dt:.0f}s\n")
            if not ok and required:
                print(f"\nRequired step '{name}' failed (exit {code}); stopping. Fix it, then: "
                      f"python scripts/build_all.py --from {name}", flush=True)
                break
    print("\n=== summary")
    for name, ok, required, dt, code in results:
        print(f"  {'ok  ' if ok else 'FAIL'} {name:18s} {dt:7.0f}s{'' if ok else f'  (exit {code}, {'required' if required else 'optional'})'}")
    print(f"log: {log}")
    ready = ROOT / "data" / "db" / "rl" / "readiness.md"
    if ready.exists() and any(r[0] == "readiness" for r in results):
        print("\n" + ready.read_text().splitlines()[0])


if __name__ == "__main__":
    main()
