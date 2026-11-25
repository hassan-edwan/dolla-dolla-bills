"""Export a self-contained dashboard snapshot (one HTML file, data embedded).

Includes overview, universe, screens, every industry, all model runs and
decisions, and a selection of companies: those in model decisions, the
configured candidates, and the monitored list. Per-company lists are capped to
keep the file small. The as-of control still works: the data carries public
timestamps.

    python scripts/export_dashboard.py [--out data/results/dashboard.html]
"""
import argparse
import json
from pathlib import Path

import pandas as pd

from ddb.app import queries as Q
from ddb.config import DATA_DIR, universe_symbols
from ddb.db.schema import connect

STATIC = Path(__file__).resolve().parents[1] / "src" / "ddb" / "app" / "static"
CAPS = {"insider": 150, "events": 250, "politicians": 120, "filing_signals": 120, "headlines": 25}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DATA_DIR / "results" / "dashboard.html"))
    ap.add_argument("--max-companies", type=int, default=120)
    ap.add_argument("--artifact", help="write a publishable page + per-view data files into this directory")
    a = ap.parse_args()
    con = connect(DATA_DIR / "ddb.duckdb")
    snap = {"_built": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H:%M UTC")}
    snap["/overview"] = Q.overview(con)
    uni = Q.universe_series(con)
    snap["/universe"] = uni
    snap["/screens"] = Q.screens(con)
    for ind in uni:
        snap[f"/industry/{ind}"] = Q.industry(con, ind, uni)
    runs = Q.runs(con)
    snap["/runs"] = runs
    dec_ciks = []
    for r in runs:
        d = Q.decisions(con, r["run_id"])
        snap[f"/decisions/{r['run_id']}"] = d
        dec_ciks += [x["cik"] for x in d["decisions"]]
    cands = sorted({t for g, v in universe_symbols().items() if g not in ("benchmarks", "haven") for t in v})
    cand_ciks = con.execute(
        f"SELECT DISTINCT cik FROM companies WHERE list_has_any(current_tickers, [{','.join(repr(t) for t in cands)}])").df()["cik"].tolist()
    mon = con.execute("SELECT DISTINCT cik FROM monitored_companies").df()["cik"].tolist()
    ciks = list(dict.fromkeys([int(c) for c in cand_ciks + dec_ciks + mon]))[: a.max_companies]
    index = []
    for k, cik in enumerate(ciks):
        c = Q.company(con, cik)
        if not c:
            continue
        for key, cap in CAPS.items():
            c[key] = c.get(key, [])[:cap]
        # Snapshot only: weekly prices from 2015, 4 significant figures, short timestamps.
        c["prices"] = [{"w": p["w"][:10], "k": (p["k"] or "")[:19] + "Z",
                        "close": float(f"{p['close']:.4g}") if p.get("close") is not None else None,
                        "close_raw": float(f"{p['close_raw']:.4g}") if p.get("close_raw") is not None else None}
                       for p in c["prices"] if (p.get("w") or "") >= "2015"]
        snap[f"/company/{cik}"] = c
        inds = sorted({i["industry"] for i in c["industries"]})
        index.append({"cik": cik, "name": c["profile"]["name"], "ticker": c["primary_ticker"],
                      "listed": c["profile"]["is_current_listed"], "last_filing": c["profile"]["last_filing"],
                      "industries": ", ".join(inds)})
        if k % 20 == 0:
            print(f"  companies {k + 1}/{len(ciks)}", flush=True)
    snap["/search_index"] = sorted(index, key=lambda r: (not r["listed"], r["name"] or ""))
    con.close()

    if a.artifact:
        write_artifact(Path(a.artifact), snap)
        return
    html = (STATIC / "index.html").read_text()
    data = json.dumps(snap, separators=(",", ":"), default=str).replace("</", "<\\/")
    html = html.replace("<!--SNAPSHOT_DATA-->", f"<script>window.DDB_SNAPSHOT={data};</script>")
    html = html.replace('<link rel="stylesheet" href="/static/styles.css">', f"<style>{(STATIC / 'styles.css').read_text()}</style>")
    html = html.replace('<script src="/static/app.js"></script>', f"<script>{(STATIC / 'app.js').read_text()}</script>")
    html = html.replace("<title>Research Dashboard</title>", "<title>Research Dashboard (snapshot)</title>")
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html)
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB, {len(index)} companies)")


CORE = ("_built", "/overview", "/universe", "/screens", "/runs", "/search_index")


def write_artifact(out: Path, snap: dict) -> None:
    """Page body for a claude.ai Artifact (the host adds <!doctype>/<head>/<body>):
    core data inline, every company/industry/decision view as its own JSON file."""
    import re
    out.mkdir(parents=True, exist_ok=True)
    core = {k: snap[k] for k in CORE if k in snap}
    n_files = 0
    for k, v in snap.items():
        if k in CORE:
            continue
        f = out / "data" / (re.sub(r"[^A-Za-z0-9/_-]", "_", k[1:]) + ".json")
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(v, separators=(",", ":"), default=str))
        n_files += 1
    index = (STATIC / "index.html").read_text()
    body = index[index.index("<header"):index.index("<script src=")]
    data = json.dumps(core, separators=(",", ":"), default=str).replace("</", "<\\/")
    page = (
        "<title>dolla-dolla-bills Research</title>\n"
        '<meta name="claude:viewport-fit-sides" content="cover">\n'
        f"<style>{(STATIC / 'styles.css').read_text()}</style>\n"
        f'<script>window.DDB_SNAPSHOT={data};window.DDB_FILES="data/";</script>\n'
        f"{body}"
        '<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js"></script>\n'
        f"<script>{(STATIC / 'app.js').read_text()}</script>\n")
    (out / "index.html").write_text(page)
    total = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(f"artifact: {out / 'index.html'} ({(out / 'index.html').stat().st_size / 1e6:.2f} MB) + {n_files} data files, "
          f"{total / 1e6:.1f} MB total")


if __name__ == "__main__":
    main()
