"""Save the training-ready outputs to the `data` branch (separate history, no code).

What is saved (whatever exists): the RL dataset (data/db/rl), signal outputs
(data/db/signals: panel, scores, validation, IC series; daily layer), regime,
model portfolio, tracking, intraday scorecards. The full database (several GB)
is not saved; rebuild it with scripts/build_all.py.

    python scripts/save_outputs.py [--push] [--message "..."]

Files over 95 MB are skipped and listed (GitHub rejects files over 100 MB).
Restore on another machine:  git fetch origin data && git worktree add ../ddb-data data
then copy its db/ folder to data/db/.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "db"
WT = ROOT / "data" / "_data_branch"
BRANCH = "data"
INCLUDE = ["rl", "signals", "regime", "portfolio", "live/tracking.json", "live/execution.json"]
EXCLUDE_SUFFIX = (".log",)
MAX_BYTES = 95 * 1024 * 1024


def git(*args, cwd=ROOT, check=True):
    return subprocess.run(["git", *args], cwd=cwd, check=check, text=True, capture_output=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--message", default=None)
    a = ap.parse_args()
    exists_remote = git("ls-remote", "--heads", "origin", BRANCH, check=False).stdout.strip() != ""
    if not WT.exists():
        if exists_remote:
            git("fetch", "origin", BRANCH)
            git("worktree", "add", str(WT), f"origin/{BRANCH}")
            git("checkout", "-B", BRANCH, cwd=WT)
        else:
            git("worktree", "add", "--detach", str(WT))
            git("checkout", "--orphan", BRANCH, cwd=WT)
            git("rm", "-rf", "--quiet", ".", cwd=WT, check=False)
    dest = WT / "db"
    if dest.exists():
        shutil.rmtree(dest)
    saved, skipped, total = [], [], 0
    for inc in INCLUDE:
        src = DB / inc
        files = [src] if src.is_file() else sorted(p for p in src.rglob("*") if p.is_file()) if src.exists() else []
        for f in files:
            if f.suffix in EXCLUDE_SUFFIX:
                continue
            rel = f.relative_to(DB)
            size = f.stat().st_size
            if size > MAX_BYTES:
                skipped.append((str(rel), size))
                continue
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest / rel)
            saved.append((str(rel), size))
            total += size
    head = git("rev-parse", "--short", "HEAD").stdout.strip()
    manifest = {"saved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "code_commit": head,
                "files": [{"path": p, "bytes": s} for p, s in saved],
                "skipped_too_large": [{"path": p, "bytes": s} for p, s in skipped], "total_bytes": total}
    rd = DB / "rl" / "readiness.json"
    if rd.exists():
        r = json.loads(rd.read_text())
        manifest["readiness"] = {"ready": r.get("ready"), "blockers": r.get("blockers")}
    (WT / "MANIFEST.json").write_text(json.dumps(manifest, indent=1))
    (WT / "README.md").write_text(
        "# dolla-dolla-bills: training-ready data\n\n"
        f"Built by code commit `{head}` on {manifest['saved_at']}. Files in `db/` go to `data/db/` in the code checkout.\n"
        "See `db/rl/readiness.md` for the data-quality verdict and MANIFEST.json for the file list.\n"
        "The full database is not here; rebuild it with `python scripts/build_all.py`.\n")
    git("add", "-A", cwd=WT)
    msg = a.message or f"Data outputs from {head} ({total / 1e6:.0f} MB, {len(saved)} files)"
    c = git("commit", "-q", "-m", msg, cwd=WT, check=False)
    print(f"saved {len(saved)} files, {total / 1e6:.1f} MB" + (f"; skipped (too large): {skipped}" if skipped else ""))
    if c.returncode != 0:
        print("nothing changed since the last save")
    if a.push:
        for i in range(4):
            p = git("push", "-u", "origin", BRANCH, cwd=WT, check=False)
            if p.returncode == 0:
                print(f"pushed to origin/{BRANCH}")
                break
            print(p.stderr.strip()[-300:])
            time.sleep(2 ** (i + 1))


if __name__ == "__main__":
    main()
