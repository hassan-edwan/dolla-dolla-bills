"""Is the real data ready (and good enough) to train on? One report, one verdict.

Checks (thresholds in configs/rl.yaml -> readiness). Each failed check is a
BLOCKER with the command that fixes it; optional data shows as a warning.

1. Every required build output exists (panel, validation, daily, regime,
   portfolio, RL dataset).
2. Price coverage: tracked-industry companies with prices in the liquid universe,
   per year since the train start.
3. Survivorship: of the companies in tracked industries that failed or were
   delisted since the train start, the share that have prices. Without them,
   models learn that risky stocks always survive.
4. Missing values in core signals within the liquid universe.
5. Out-of-sample composite history (months).
6. Regime inputs: share of trading days with VIX, credit spread and breadth.
7. Point-in-time violations: rows whose public time is earlier than the event they
   describe (a filing public before it was filed, a price before the close, ...).
8. Bad prices: daily moves beyond +300% / -95%, zero or negative prices,
   duplicate bars.
9. Freshness of the core sources (stale = the latest data is missing).
10. RL dataset: decision dates per split, missing features, empty sleeves.
11. Test-set hygiene: how many times the locked test period was opened.

    python -m ddb.rl.readiness       # writes data/db/rl/readiness.{json,md}; exit code 1 if not ready
"""
from __future__ import annotations

import json
import sys

import pandas as pd

from ..config import DATA_DIR, load
from ..db.schema import connect
from ..features import bars as B
from . import splits as S

DB_PATH = DATA_DIR / "ddb.duckdb"
DB = DATA_DIR / "db"
OUT = DB / "rl"

FIX = {
    "panel": "python -m ddb.features.panel",
    "validation": "python -m ddb.features.validate",
    "daily": "python -m ddb.features.daily",
    "regime": "python -m ddb.db.build_macro && python -m ddb.features.regime",
    "portfolio": "python -m ddb.portfolio.model",
    "rl_dataset": "python -m ddb.rl.dataset",
    "inst_holdings": "python -m ddb.db.build_13f",
    "intraday": "python -m ddb.db.build_intraday && python -m ddb.features.intraday",
    "spreads": "python -m ddb.db.build_spreads",
    "news": "python -m ddb.news.gdelt (backfill: hpc/gdelt_backfill.sbatch)",
}
ARTIFACTS = {
    "panel": "signals/panel.parquet", "validation": "signals/validation.json", "daily": "signals/daily/validation.json",
    "regime": "regime/regime.parquet", "portfolio": "portfolio/summary.json", "rl_dataset": "rl/meta.json",
}

PIT_CHECKS = {   # name -> SQL counting rows public before they could have been
    "filings public before their filing date":
        "SELECT count(*) FROM filings WHERE knowable_at < CAST(filing_date AS TIMESTAMPTZ)",
    "financial facts public before their period ended":
        "SELECT count(*) FROM fundamentals WHERE knowable_at < CAST(period_end AS TIMESTAMPTZ)",
    "prices public before that day's close":
        "SELECT count(*) FROM prices WHERE knowable_at < CAST(date AS TIMESTAMPTZ) + INTERVAL 20 HOUR",
    "insider trades public before the trade":
        "SELECT count(*) FROM insider_transactions WHERE knowable_at < CAST(trans_date AS TIMESTAMPTZ)",
    "events public before they happened":
        "SELECT count(*) FROM events WHERE knowable_at < CAST(event_date AS TIMESTAMPTZ)",
    "macro values public on their own date":
        "SELECT count(*) FROM macro WHERE knowable_at < CAST(date AS TIMESTAMPTZ) + INTERVAL 1 DAY",
    "congressional trades public before the trade":
        "SELECT count(*) FROM politician_trades WHERE knowable_at < CAST(trans_date AS TIMESTAMPTZ)",
    "13F holdings public before the quarter ended":
        "SELECT count(*) FROM inst_holdings WHERE knowable_at < CAST(period AS TIMESTAMPTZ)",
}


def _check(name, ok, detail, fix=None, blocker=True) -> dict:
    return {"check": name, "ok": bool(ok), "blocker": blocker, "detail": detail, "fix": fix}


def run(db_path=DB_PATH) -> dict:
    cfg = load("rl")["readiness"]
    tr0 = S.periods()["train"][0]
    checks = []
    # 1. artifacts
    for k in cfg["required"]:
        f = DB / ARTIFACTS[k]
        checks.append(_check(f"built: {k}", f.exists(), str(f.relative_to(DATA_DIR)) + (" ok" if f.exists() else " missing"), FIX[k]))
    if not db_path.exists():
        checks.append(_check("database", False, f"{db_path} not found",
                             "python scripts/build_database.py --download && python scripts/build_database.py"))
        return _finish(checks, {})
    con = connect(db_path, read_only=True)
    q = lambda sql: con.execute(sql).fetchone()[0]   # noqa: E731
    stats = {}

    # 2. price coverage per year (liquid universe in tracked industries)
    panel_f = DB / "signals" / "panel.parquet"
    if panel_f.exists():
        p = pd.read_parquet(panel_f, columns=["d", "cik", "price_raw", "dollar_vol_20d"] + [
            c for c in cfg["core_signals"] if c not in ("ret_1d",)])
        p["d"] = pd.to_datetime(p["d"])
        liq = p[(p["price_raw"] >= 2) & (p["dollar_vol_20d"] >= 1e6)]
        per_year = liq.groupby(liq["d"].dt.year)["cik"].nunique()
        since = per_year[per_year.index >= tr0.year]
        good = int((since >= cfg["min_names_per_year"]).sum())
        stats["names_per_year"] = {int(k): int(v) for k, v in per_year.items()}
        checks.append(_check("price coverage", good >= cfg["min_years_prices"],
                             f"{good} years since {tr0.year} with >= {cfg['min_names_per_year']} liquid tracked-industry names "
                             f"(need {cfg['min_years_prices']}); per year: " + ", ".join(f"{int(k)}: {int(v)}" for k, v in since.items()),
                             "python scripts/build_database.py --steps prices alpaca"))
        # 4. missing core signals
        rec = liq[liq["d"] >= tr0]
        miss = {c: float(rec[c].isna().mean()) for c in cfg["core_signals"] if c in rec}
        bad = {c: round(v, 3) for c, v in miss.items() if v > cfg["max_missing_core"]}
        stats["missing_core"] = {c: round(v, 3) for c, v in miss.items()}
        checks.append(_check("core signals filled", not bad,
                             "missing share within the liquid universe: " + ", ".join(f"{c} {v:.0%}" for c, v in miss.items())
                             + (f"; above {cfg['max_missing_core']:.0%}: {bad}" if bad else ""),
                             "python scripts/build_database.py --steps fundamentals && python -m ddb.features.panel"))

    # 3. survivorship
    try:
        dead = con.execute(f"""
            WITH gone AS (
                SELECT DISTINCT o.cik FROM outcomes o JOIN company_industries ci USING (cik)
                WHERE o.outcome IN ('bankrupt', 'delisted_exchange', 'deregistered')
                  AND o.exit_date >= DATE '{tr0.date()}' AND ci.confidence <> 'low'),
            priced AS (
                SELECT DISTINCT cik FROM prices WHERE cik IS NOT NULL
                UNION SELECT DISTINCT t.cik FROM tickers t JOIN prices p ON upper(p.symbol) = upper(t.ticker)
                    AND p.date BETWEEN coalesce(t.valid_from, DATE '1900-01-01') AND coalesce(t.valid_to, DATE '2100-01-01'))
            SELECT count(*) AS n, count(*) FILTER (WHERE cik IN (SELECT cik FROM priced)) AS with_px FROM gone""").fetchone()
        share = dead[1] / dead[0] if dead[0] else 0.0
        stats["dead_since_train_start"] = {"companies": dead[0], "with_prices": dead[1]}
        checks.append(_check("failed companies have prices", dead[0] > 0 and share >= cfg["min_dead_with_prices_share"],
                             (f"{dead[1]:,} of {dead[0]:,} companies that failed or delisted since {tr0.date()} have prices "
                              f"({share:.0%}; need {cfg['min_dead_with_prices_share']:.0%})") if dead[0] else
                             "no failed or delisted companies recorded since the train start: outcome labels are missing",
                             "python -m ddb.db.build_alpaca (free key), then a second source for the rest"))
    except Exception as exc:  # noqa: BLE001
        checks.append(_check("failed companies have prices", False, f"could not check: {exc}", "build outcomes + prices"))

    # 5. composite history
    vf = DB / "signals" / "validation.json"
    if vf.exists():
        v = json.loads(vf.read_text())
        n = len(v.get("composite_signals_by_month") or {})
        good = [s["signal"] for s in v.get("signals", []) if s.get("status") in ("predictive", "moderate")]
        stats["proven_monthly_signals"] = good
        checks.append(_check("out-of-sample composite history", n >= cfg["min_composite_months"],
                             f"{n} months (need {cfg['min_composite_months']}); {len(good)} proven signals", FIX["validation"]))

    # 6. regime coverage
    rf = DB / "regime" / "regime.parquet"
    if rf.exists():
        r = pd.read_parquet(rf)
        r = r[pd.to_datetime(r["d"]) >= tr0]
        cov = float(r[["vix", "hy_oas", "breadth"]].notna().all(axis=1).mean()) if len(r) else 0.0
        checks.append(_check("regime inputs", cov >= cfg["min_regime_coverage"],
                             f"{cov:.1%} of trading days since {tr0.date()} have VIX, credit spread and breadth", FIX["regime"]))

    # 7. point-in-time violations
    viol = {}
    for name, sql in PIT_CHECKS.items():
        try:
            viol[name] = int(q(sql))
        except Exception:  # noqa: BLE001 - table not loaded
            continue
    stats["pit_violations"] = viol
    total = sum(viol.values())
    checks.append(_check("no-hindsight timestamps", total <= cfg["max_pit_violations"],
                         "; ".join(f"{k}: {v:,}" for k, v in viol.items() if v) or f"0 violations in {len(viol)} tables",
                         "fix the loader that wrote those rows (knowable_at must be >= the event time)"))

    # 8. bad prices
    try:
        bad = con.execute("""
            WITH x AS (SELECT symbol, date, close, lag(close) OVER (PARTITION BY symbol, source ORDER BY date) AS prev
                       FROM prices WHERE close IS NOT NULL)
            SELECT count(*) FILTER (WHERE close <= 0),
                   count(*) FILTER (WHERE prev > 0 AND (close / prev > 4 OR close / prev < 0.05)),
                   count(*) FROM x""").fetchone()
        dup = q("SELECT count(*) FROM (SELECT symbol, date, source, count(*) n FROM prices GROUP BY ALL HAVING n > 1)")
        share = (bad[0] + bad[1]) / max(bad[2], 1)
        stats["bad_prices"] = {"non_positive": bad[0], "jumps": bad[1], "duplicates": dup, "bars": bad[2]}
        checks.append(_check("clean prices", share < 5e-4 and dup == 0,
                             f"{bad[0]:,} zero/negative, {bad[1]:,} daily moves beyond +300%/-95%, {dup:,} duplicate bars, of {bad[2]:,}",
                             "inspect with python scripts/db_report.py; refetch bad symbols with build_prices --only-missing"))
    except Exception as exc:  # noqa: BLE001
        checks.append(_check("clean prices", False, f"could not check: {exc}", "build prices"))

    # 9. freshness
    try:
        from ..live.tracking import freshness
        fr = {f["source"]: f for f in freshness(con, load("risk")["freshness"])}
        core = ["prices", "filings", "macro"]
        stale = [s for s in core if fr.get(s, {}).get("status") != "ok"]
        checks.append(_check("core data current", not stale,
                             "; ".join(f"{s}: {fr[s]['status']} ({fr[s]['age_days']} days)" for s in core if s in fr),
                             "rerun the database build (scripts/build_all.py)"))
        for s in ("inst_holdings", "intraday", "spreads", "news_events"):
            f = fr.get(s)
            if f:
                checks.append(_check(f"optional: {s}", f["status"] == "ok", f"{f['status']}" + (f", {f['age_days']} days old" if f["age_days"] else ""),
                                     FIX.get(s.replace("_events", ""), ""), blocker=False))
    except Exception as exc:  # noqa: BLE001
        checks.append(_check("core data current", False, f"could not check: {exc}", None))
    con.close()

    # 10. RL dataset
    mf = OUT / "meta.json"
    if mf.exists():
        meta = json.loads(mf.read_text())
        obs = pd.read_parquet(OUT / "obs.parquet")
        obs["d"] = pd.to_datetime(obs["d"])
        per = {k: int(((obs["d"] >= a) & (obs["d"] <= b)).sum()) for k, (a, b) in S.periods().items()}
        sl = pd.read_parquet(OUT / "sleeves.parquet")
        months = pd.to_datetime(sl["month"]).dt.to_period("M").nunique() if len(sl) else 0
        miss = {k: v for k, v in (meta.get("missing_share_after_train_start") or {}).items() if v > 0.5}
        stats["rl_dates_per_split"] = per
        checks.append(_check("RL dataset", per["train"] >= 150 and per["validation"] >= 40 and not miss,
                             f"weekly decisions per split {per}; {len(meta['industries'])} industry sleeves over {months} months"
                             + (f"; features more than half missing: {list(miss)}" if miss else ""), FIX["rl_dataset"]))
    n_test = S.test_accesses()
    checks.append(_check("test period untouched", n_test == 0, f"opened {n_test} times", "pick a new test period after many looks",
                         blocker=False))
    return _finish(checks, stats)


def _finish(checks, stats) -> dict:
    blockers = [c for c in checks if c["blocker"] and not c["ok"]]
    out = {"built": pd.Timestamp.now(tz="UTC").isoformat(), "ready": not blockers, "blockers": len(blockers),
           "checks": checks, "stats": stats, "splits": {k: [str(a.date()), str(b.date())] for k, (a, b) in S.periods().items()}}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "readiness.json").write_text(json.dumps(B.clean(out), default=str, indent=1))
    lines = [f"# Data readiness: {'READY' if out['ready'] else 'NOT READY'} ({len(blockers)} blockers)", "",
             f"Checked {out['built'][:16]} UTC. Splits: " + ", ".join(f"{k} {a} → {b}" for k, (a, b) in out["splits"].items()), "",
             "| | Check | Detail | Fix |", "|---|---|---|---|"]
    for c in checks:
        mark = "✅" if c["ok"] else ("❌" if c["blocker"] else "⚠️")
        lines.append(f"| {mark} | {c['check']} | {c['detail']} | {'' if c['ok'] else (c['fix'] or '')} |")
    (OUT / "readiness.md").write_text("\n".join(lines) + "\n")
    return out


if __name__ == "__main__":
    r = run()
    print((OUT / "readiness.md").read_text())
    sys.exit(0 if r["ready"] else 1)
