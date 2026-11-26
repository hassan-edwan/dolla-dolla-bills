"""Is the model still working, and is its data current?

1. Forecast log. `log_forecasts()` saves the latest month-end ranking (and the
   latest short-term ranking) the first time it is seen, with the time it was
   logged. Files are never overwritten, so the log is a true record of what the
   model said before the outcome was known. `track()` scores each logged forecast
   once its month is over: buy candidates vs the average screened name.
2. Walk-forward record: the composite's out-of-sample record by month (already
   computed by ddb.features.validate), with a rolling 12-month view.
3. Signal decay: for each signal the composite relies on, the recent IC (last 12
   months; last 120 days for daily data points) vs its earlier record. An alert
   fires when the recent IC is negative or its t-stat falls below `decay_t_min`.
4. Data freshness: age of the newest row in each source vs its expected cadence.

Run after each data update:

    python -m ddb.live.tracking
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import DATA_DIR, load
from ..db.schema import connect
from ..features import bars as B

OUT = DATA_DIR / "db" / "live"
SIG = DATA_DIR / "db" / "signals"
DB_PATH = DATA_DIR / "ddb.duckdb"
GOOD = ("predictive", "moderate")


# ------------------------------------------------------------------ forecast log
def log_forecasts(con, now: pd.Timestamp | None = None) -> list[str]:
    from ..app import queries as Q
    now = now or pd.Timestamp.now(tz="UTC")
    (OUT / "forecasts").mkdir(parents=True, exist_ok=True)
    written = []
    sig = Q.signals_overview(con)
    if sig.get("months"):
        m = sig["months"][-1]
        f = OUT / "forecasts" / f"monthly_{m}.parquet"
        if not f.exists():
            rows = Q.signal_month(con, m, limit=100_000)["rows"]
            df = pd.DataFrame([{k: r.get(k) for k in ("cik", "ticker", "composite_pct", "verdict")} for r in rows])
            df["month"], df["logged_at"] = m, now.isoformat()
            df.to_parquet(f, index=False)
            written.append(f.name)
    st = Q.short_term_overview(con).get("daily", {})
    if st.get("days"):
        d = st["days"][-1]
        f = OUT / "forecasts" / f"daily_{d}.parquet"
        if not f.exists():
            rows = Q.short_term_day(con, d, limit=100_000)["rows"]
            df = pd.DataFrame([{"cik": r["cik"], "ticker": r["ticker"], "composite_pct": r["composite_pct"],
                                "avoid": r["avoid"]} for r in rows])
            df["day"], df["logged_at"] = d, now.isoformat()
            df.to_parquet(f, index=False)
            written.append(f.name)
    return written


def _closes(con, ciks: list[int], start, end) -> pd.DataFrame:
    if not ciks:
        return pd.DataFrame()
    df = con.execute(f"""
        WITH prim AS (SELECT cik, upper(current_tickers[1]) AS sym FROM companies
                      WHERE cik IN ({','.join(str(int(c)) for c in ciks)}) AND len(current_tickers) > 0)
        SELECT prim.cik, p.date, p.close FROM prices p JOIN prim ON upper(p.symbol) = prim.sym
        WHERE p.date BETWEEN DATE '{pd.Timestamp(start).date()}' AND DATE '{pd.Timestamp(end).date()}'
    """).df()
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    return df.pivot_table(index="date", columns="cik", values="close", aggfunc="last").sort_index()


def score_monthly(con, f: Path) -> dict:
    fc = pd.read_parquet(f)
    m = pd.Timestamp(fc["month"].iloc[0])
    end = (m + pd.offsets.MonthEnd(1))
    px = _closes(con, fc["cik"].astype(int).tolist(), m - pd.Timedelta(days=7), end + pd.Timedelta(days=7))
    out = {"month": str(m.date()), "logged_at": fc["logged_at"].iloc[0], "names": int(len(fc))}
    if px.empty or px.index.max() < end - pd.Timedelta(days=3):
        return {**out, "status": "pending"}
    p0 = px.loc[:m].iloc[-1]
    p1 = px.loc[:end].iloc[-1]
    r = (p1 / p0 - 1).rename("ret")
    fc = fc.merge(r, left_on="cik", right_index=True, how="left")
    avg = fc["ret"].mean()
    buys = fc[fc["verdict"] == "buy candidate"]["ret"]
    avoid = fc[fc["verdict"] == "avoid"]["ret"]
    return B.clean({**out, "status": "scored", "avg": avg, "buy_candidates": buys.mean(), "buy_vs_avg": buys.mean() - avg,
                    "avoid": avoid.mean() if len(avoid) else None,
                    "avoid_vs_avg": (avoid.mean() - avg) if len(avoid) else None, "n_buy": int(buys.notna().sum())})


# ------------------------------------------------------------------ decay
def decay(cfg: dict) -> list[dict]:
    out = []
    v = json.loads((SIG / "validation.json").read_text()) if (SIG / "validation.json").exists() else {}
    f = SIG / "ic_monthly.parquet"
    if v and f.exists():
        ic = pd.read_parquet(f)
        used = set((v.get("composite_signals_by_month") or {}).get(max(v.get("composite_signals_by_month") or {"": 0}), []))
        lab = {s["signal"]: s for s in v["signals"]}
        n = cfg["decay_window_months"]
        for s, g in ic.groupby("signal"):
            if lab.get(s, {}).get("status") not in GOOD and s not in used:
                continue
            g = g.sort_values("d")
            recent, before = g["ic_1m"].iloc[-n:], g["ic_1m"].iloc[:-n]
            t = B.nw_tstat(recent.to_numpy(), 0) if len(recent) >= 12 else np.nan
            alert = bool(recent.mean() < 0 or (np.isfinite(t) and t < cfg["decay_t_min"]))
            out.append({"signal": s, "label": lab.get(s, {}).get("label", s), "kind": "monthly", "in_composite": s in used,
                        "recent_ic": float(recent.mean()), "recent_t": t, "earlier_ic": float(before.mean()) if len(before) else None,
                        "window": f"last {n} months", "alert": alert})
    dv = SIG / "daily" / "validation.json"
    fd = SIG / "daily" / "ic_daily.parquet"
    if dv.exists() and fd.exists():
        v2 = json.loads(dv.read_text())
        prim = v2.get("primary_horizon")
        ic = pd.read_parquet(fd)
        ic = ic[ic["horizon"] == prim]
        lab = {s["signal"]: s for s in v2["signals"]}
        n = cfg["decay_window_days"]
        for s, g in ic.groupby("signal"):
            if lab.get(s, {}).get("status") not in GOOD:
                continue
            g = g.dropna(subset=["ic"]).sort_values("d")
            recent, before = g["ic"].iloc[-n:], g["ic"].iloc[:-n]
            t = B.nw_tstat(recent.to_numpy(), 0)
            alert = bool(recent.mean() < 0 or (np.isfinite(t) and t < cfg["decay_t_min"]))
            out.append({"signal": s, "label": lab[s].get("label", s), "kind": "daily", "in_composite": None,
                        "recent_ic": float(recent.mean()), "recent_t": t, "earlier_ic": float(before.mean()) if len(before) else None,
                        "window": f"last {n} trading days", "alert": alert})
    return B.clean(out)


# ------------------------------------------------------------------ freshness
SOURCES = {   # name -> SQL for the newest public time
    "prices": "SELECT max(knowable_at) FROM prices",
    "filings": "SELECT max(knowable_at) FROM filings",
    "events": "SELECT max(knowable_at) FROM events",
    "insider_transactions": "SELECT max(knowable_at) FROM insider_transactions",
    "news_events": "SELECT max(knowable_at) FROM news_events",
    "macro": "SELECT max(knowable_at) FROM macro",
    "politician_trades": "SELECT max(knowable_at) FROM politician_trades",
    "gov_contracts": "SELECT max(knowable_at) FROM gov_contracts",
    "inst_holdings": "SELECT max(knowable_at) FROM inst_holdings",
}


def freshness(con, limits: dict, now: pd.Timestamp | None = None) -> list[dict]:
    now = now or pd.Timestamp.now(tz="UTC")
    out = []
    for name, sql in SOURCES.items():
        try:
            last = con.execute(sql).fetchone()[0]
        except Exception:  # noqa: BLE001 - table not loaded
            last = None
        out.append(_age(name, last, limits.get(name), now))
    for name, d in (("intraday", DATA_DIR / "db" / "intraday" / "1Min"), ("spreads", DATA_DIR / "db" / "spreads")):
        last = None
        if d.exists():
            files = sorted(d.rglob("*.parquet"), key=lambda p: p.stat().st_mtime)[-20:]
            col = "knowable_at"
            vals = []
            for f in files:
                try:
                    vals.append(pd.read_parquet(f, columns=[col])[col].max())
                except Exception:  # noqa: BLE001
                    pass
            last = max(vals) if vals else None
        out.append(_age(name, last, limits.get(name), now))
    return out


def _age(name, last, limit, now) -> dict:
    if last is None or pd.isna(last):
        return {"source": name, "last": None, "age_days": None, "limit_days": limit, "status": "missing"}
    last = pd.Timestamp(last)
    last = last.tz_localize("UTC") if last.tzinfo is None else last
    age = (now - last).total_seconds() / 86400
    return {"source": name, "last": last.isoformat(), "age_days": round(age, 1), "limit_days": limit,
            "status": "stale" if limit is not None and age > limit else "ok"}


def track(con, cfg: dict) -> dict:
    monthly = [score_monthly(con, f) for f in sorted((OUT / "forecasts").glob("monthly_*.parquet"))]
    record = []
    f = SIG / "composite_quintiles.parquet"
    if f.exists():
        cq = pd.read_parquet(f).pivot_table(index="d", columns="quintile", values="excess_ret").sort_index()
        roll = cq[5].rolling(12, min_periods=6).mean()
        record = [{"d": str(pd.Timestamp(d).date()), "k": (pd.Timestamp(d) + pd.Timedelta(days=31)).isoformat() + "Z",
                   "top20": float(cq.at[d, 5]), "bottom20": float(cq.at[d, 1]),
                   "top20_roll12": None if pd.isna(roll[d]) else float(roll[d])} for d in cq.index]
    alerts = []
    if record and record[-1]["top20_roll12"] is not None and record[-1]["top20_roll12"] < 0:
        alerts.append("The composite's top 20% has trailed the average name over the last 12 months.")
    return B.clean({"monthly_forecasts": monthly, "walk_forward": record, "alerts": alerts})


def build(db_path=DB_PATH) -> dict:
    cfg = load("risk")
    con = connect(db_path)
    written = log_forecasts(con)
    out = track(con, cfg["tracking"])
    out["decay"] = decay(cfg["tracking"])
    out["freshness"] = freshness(con, cfg["freshness"])
    out["config"] = cfg["tracking"]
    con.close()
    out["built"] = pd.Timestamp.now(tz="UTC").isoformat()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "tracking.json").write_text(json.dumps(B.clean(out), default=str, indent=1))
    return {"logged": written, "decay_alerts": sum(d["alert"] for d in out["decay"]),
            "stale": [f["source"] for f in out["freshness"] if f["status"] != "ok"]}


if __name__ == "__main__":
    print(build())
