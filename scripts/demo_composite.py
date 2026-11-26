"""Explained decisions for the walk-forward composite (demo model for the dashboard).

Monthly from 2018: among companies passing every investment screen as of the
month-end (AsOf.tradable) and in the liquid universe, hold the top N by the
walk-forward composite, skipping names with an avoid flag (signals that predict
losers). Each decision records every signal in the composite with its
contribution = industry-neutral z-score / number of signals in use (the composite
is their average), plus avoid-flag checks and screen status.

    python scripts/demo_composite.py [--start 2018-01] [--top 10]
"""
import argparse
import json

import numpy as np
import pandas as pd
import yaml

from ddb.app.queries import AVOID_RULES
from ddb.config import CONFIG_DIR, DATA_DIR
from ddb.db.pit import AsOf
from ddb.db.schema import connect
from ddb.decisions import DecisionLog, Factor

MODEL = "composite-walkforward-demo"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2018-01")
    ap.add_argument("--top", type=int, default=10)
    a = ap.parse_args()
    cfg = yaml.safe_load((CONFIG_DIR / "signals.yaml").read_text())["signals"]
    val = json.loads((DATA_DIR / "db" / "signals" / "validation.json").read_text())
    used_by_month = val["composite_signals_by_month"]
    sc = pd.read_parquet(DATA_DIR / "db" / "signals" / "scores.parquet")
    sc = sc[sc["d"] >= pd.Timestamp(a.start)]
    con = connect(DATA_DIR / "ddb.duckdb")
    log = DecisionLog(con)
    old = con.execute("SELECT run_id FROM decision_runs WHERE model = ?", [MODEL]).df()["run_id"].tolist()
    for r in old:
        con.execute("DELETE FROM decision_factors WHERE decision_id IN (SELECT decision_id FROM decisions WHERE run_id = ?)", [r])
        con.execute("DELETE FROM decisions WHERE run_id = ?", [r])
        con.execute("DELETE FROM decision_runs WHERE run_id = ?", [r])
    names = con.execute("SELECT cik, current_tickers[1] AS ticker FROM companies").df().set_index("cik")["ticker"].to_dict()
    run = log.new_run(MODEL, params={"top": a.top, "universe": val["universe_rule"], "selection": "walk-forward t>=2"},
                      description="Demo: each month, hold the top-N screened companies by the walk-forward composite of "
                                  "signals that had predicted returns on earlier data, skipping names with avoid flags. "
                                  "Contribution = each signal's industry-neutral z-score / number of signals in use.")
    held: dict[int, float] = {}
    n = 0
    for d, g in sc.groupby("d"):
        m = str(pd.Timestamp(d).date())
        used = used_by_month.get(m, [])
        if not used:
            continue
        as_of = (pd.Timestamp(d) + pd.Timedelta(hours=21, minutes=30)).tz_localize("UTC")
        with AsOf(con, as_of) as db:
            trad = set(db.tradable()["cik"].astype(int))
        g = g[g["cik"].astype(int).isin(trad) & g["composite"].notna()].copy()
        def flags(r):
            out = []
            for s, lab in AVOID_RULES.items():
                v = r.get(f"{s}__pct")
                if v is None or pd.isna(v):
                    continue
                if s in ("going_concern", "late_filings_12m", "offerings_12m") and not (r.get(s) or 0) > 0:
                    continue
                if v <= (5 if s in ("going_concern", "late_filings_12m") else 10):
                    out.append(lab)
            return out
        g["flags"] = [flags(r) for r in g.to_dict(orient="records")]
        ranked = g.sort_values("composite", ascending=False)
        top = ranked[ranked["flags"].map(len) == 0].head(a.top)
        top_ciks = set(top["cik"].astype(int))
        w = 1.0 / a.top
        rows = {int(r["cik"]): r for r in g.to_dict(orient="records")}
        for cik in sorted(top_ciks | set(held)):
            r = rows.get(cik)
            action = "hold" if (cik in top_ciks and cik in held) else ("buy" if cik in top_ciks else "sell")
            fac = []
            if r is not None:
                for s in used:
                    z = r.get(f"{s}__z")
                    if z is None or pd.isna(z):
                        continue
                    raw = r.get(s)
                    fac.append(Factor(cfg[s]["label"], float(z) / len(used), value=None if pd.isna(raw) else float(raw),
                                      value_text=f"{r.get(s + '__pct', float('nan')):.0f}th percentile (raw {raw:.3g})" if raw is not None and not pd.isna(raw) else "n/a",
                                      group=cfg[s].get("role", "thesis"), description=cfg[s]["desc"],
                                      source_table="signal panel", source_ref=m, knowable_at=as_of))
                fac.append(Factor("avoid flags", 0.0, value_text=", ".join(r["flags"]) or "none", group="screen",
                                  description="Signals that predict losers; any flag excludes the name",
                                  source_table="signal panel", knowable_at=as_of))
                rank = int((ranked["composite"] > r["composite"]).sum()) + 1
                rationale = (f"Composite rank {rank} of {len(ranked)} screened companies "
                             f"({r.get('composite__pct', 0):.0f}th percentile in the liquid universe) using {len(used)} proven signals.")
                score = float(r["composite"])
            else:
                rationale, score = "Left the screened, liquid universe (failed a screen or became illiquid).", None
                fac.append(Factor("universe", 0.0, value_text="not in the screened liquid universe this month", group="screen",
                                  knowable_at=as_of))
            if cik in held and cik not in top_ciks and r is not None:
                rationale += " Sold: " + ("avoid flag (" + ", ".join(r["flags"]) + ")." if r["flags"] else "fell out of the top ranks.")
            log.record(run, as_of, cik, names.get(cik) or "", action, target_weight=w if cik in top_ciks else 0.0,
                       prev_weight=held.get(cik, 0.0), score=score, rationale=rationale, factors=fac)
            n += 1
        held = {c: w for c in top_ciks}
        print(f"  {m}: {len(used)} signals, {len(g)} screened, top: {', '.join(str(names.get(c)) for c in top['cik'])}", flush=True)
    log.flush()
    con.close()
    print(f"run {run}: {n} decisions")


if __name__ == "__main__":
    main()
