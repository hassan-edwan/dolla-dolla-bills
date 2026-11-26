"""Validate every candidate signal on our own universe, and build a walk-forward composite.

Universe each month: active companies in tracked industries with an as-traded
price >= $2 and 20-day average dollar volume >= $1M (filters out untradeable
microcaps that dominate equal-weighted anomaly results).

Per signal (sign-adjusted so higher = expected better):
  rank IC vs next-month return (Spearman, monthly), mean / std / IC-IR /
  t-stat (Newey-West for 3m horizon) / hit rate, coverage; quintile mean returns,
  Q5-Q1 spread and LONG LEG (Q5 minus universe average: what a long-only
  portfolio can capture); rank autocorrelation (turnover proxy); subperiods
  2012-2019 and 2020+; 3-month IC (decay).

Composite (walk-forward, no hindsight): at month t, use signals whose IC t-stat
on months whose returns were fully known before t is >= 2 and positive, with
industry-neutral winsorized z-scores averaged equally. Its IC and quintiles are
therefore out-of-sample.

    python -m ddb.features.validate
"""
from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd
import yaml

from ..config import CONFIG_DIR, DATA_DIR

SIG_DIR = DATA_DIR / "db" / "signals"
MIN_NAMES = 30


def nw_tstat(x: np.ndarray, lags: int) -> float:
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 12:
        return np.nan
    e = x - x.mean()
    s = (e @ e) / n
    for L in range(1, lags + 1):
        w = 1 - L / (lags + 1)
        s += 2 * w * (e[L:] @ e[:-L]) / n
    return x.mean() / np.sqrt(s / n) if s > 0 else np.nan


def zscore_within(df: pd.DataFrame, col: str) -> pd.Series:
    """Industry-neutral, winsorized z-score per month."""
    def f(s):
        lo, hi = s.quantile(0.01), s.quantile(0.99)
        s = s.clip(lo, hi)
        sd = s.std()
        return (s - s.mean()) / sd if sd and sd > 0 else s * 0
    z = df.groupby(["d", "industry"])[col].transform(f)
    small = df.groupby(["d", "industry"])[col].transform("count") < 5   # tiny industries: use whole universe
    zall = df.groupby("d")[col].transform(f)
    return z.where(~small, zall)


def build() -> dict:
    t0 = time.time()
    cfg = yaml.safe_load((CONFIG_DIR / "signals.yaml").read_text())["signals"]
    p = pd.read_parquet(SIG_DIR / "panel.parquet")
    p = p[(p["price_raw"] >= 2) & (p["dollar_vol_20d"] >= 1e6)].copy()
    names = [s for s in cfg if s in p.columns]
    for s in names:
        p[f"{s}__x"] = p[s] * cfg[s]["sign"]

    # ---- per-signal monthly IC + quintiles
    ic_rows, q_rows = [], []
    for d, g in p.groupby("d"):
        f1, f3 = g["fwd_1m"], g["fwd_3m"]
        for s in names:
            x = g[f"{s}__x"]
            ok = x.notna() & f1.notna()
            if ok.sum() < MIN_NAMES or x[ok].nunique() < 5:
                continue
            ic1 = x[ok].rank().corr(f1[ok].rank())
            ok3 = x.notna() & f3.notna()
            ic3 = x[ok3].rank().corr(f3[ok3].rank()) if ok3.sum() >= MIN_NAMES else np.nan
            ic_rows.append((d, s, ic1, ic3, int(ok.sum())))
            try:
                qq = pd.qcut(x[ok].rank(method="first"), 5, labels=False) + 1
            except ValueError:
                continue
            m = f1[ok].groupby(qq).mean()
            for k, v in m.items():
                q_rows.append((d, s, int(k), v - f1[ok].mean()))
    ic = pd.DataFrame(ic_rows, columns=["d", "signal", "ic_1m", "ic_3m", "n"])
    qd = pd.DataFrame(q_rows, columns=["d", "signal", "quintile", "excess_ret"])

    # turnover proxy: month-to-month rank autocorrelation of the signal
    auto = {}
    for s in names:
        w = p.pivot_table(index="d", columns="cik", values=f"{s}__x")
        r = w.rank(axis=1)
        ac = [r.iloc[i].corr(r.iloc[i - 1]) for i in range(1, len(r)) if r.iloc[i].notna().sum() > MIN_NAMES]
        auto[s] = float(np.nanmean(ac)) if ac else np.nan

    def stats(sub):
        x = sub["ic_1m"].to_numpy()
        return {"ic_mean": float(np.nanmean(x)), "ic_std": float(np.nanstd(x)),
                "ic_ir": float(np.nanmean(x) / np.nanstd(x)) if np.nanstd(x) > 0 else None,
                "t_stat": float(nw_tstat(x, 0)), "hit_rate": float(np.nanmean(x > 0)), "months": int(len(x))}

    summary = []
    for s in names:
        g = ic[ic["signal"] == s]
        if g.empty:
            summary.append({"signal": s, **cfg[s], "months": 0, "status": "insufficient data"})
            continue
        st = stats(g)
        early, late = g[g["d"] < "2020-01-01"], g[g["d"] >= "2020-01-01"]
        qs = qd[qd["signal"] == s].groupby("quintile")["excess_ret"].mean()
        row = {"signal": s, **cfg[s], **st,
               "ic_3m": float(np.nanmean(g["ic_3m"])), "t_stat_3m": float(nw_tstat(g["ic_3m"].to_numpy(), 2)),
               "ic_2012_2019": float(np.nanmean(early["ic_1m"])) if len(early) else None,
               "ic_2020_on": float(np.nanmean(late["ic_1m"])) if len(late) else None,
               "q1": float(qs.get(1, np.nan)), "q5": float(qs.get(5, np.nan)),
               "spread_q5_q1": float(qs.get(5, np.nan) - qs.get(1, np.nan)),
               "long_leg": float(qs.get(5, np.nan)), "rank_autocorr": auto.get(s),
               "avg_names": float(g["n"].mean())}
        t = row["t_stat"]
        both = (row["ic_2012_2019"] or 0) > 0 and (row["ic_2020_on"] or 0) > 0
        if t >= 3 and both:
            row["status"] = "predictive"
        elif t >= 2 and both:
            row["status"] = "moderate"
        elif t >= 1:
            row["status"] = "weak"
        elif t <= -2:
            row["status"] = "wrong sign"
        else:
            row["status"] = "not predictive"
        summary.append(row)

    # ---- walk-forward composite
    ic = ic.sort_values("d")
    months = sorted(p["d"].unique())
    p["composite"] = np.nan
    used = {}
    zcache = {}
    for i, d in enumerate(months):
        # months whose 1m forward return was known by d: at least 1 month earlier
        hist = ic[ic["d"] < d - pd.Timedelta(days=31)]
        if hist["d"].nunique() < 24:
            continue
        sel = []
        for s, g in hist.groupby("signal"):
            t = nw_tstat(g["ic_1m"].to_numpy(), 0)
            if np.isfinite(t) and t >= 2 and g["ic_1m"].mean() > 0:
                sel.append(s)
        if not sel:
            continue
        used[str(pd.Timestamp(d).date())] = sel
        g = p[p["d"] == d]
        zs = []
        for s in sel:
            if s not in zcache:
                zcache[s] = zscore_within(p, f"{s}__x")
            zs.append(zcache[s].loc[g.index])
        p.loc[g.index, "composite"] = pd.concat(zs, axis=1).mean(axis=1, skipna=True)

    comp_rows, comp_q = [], []
    for d, g in p.groupby("d"):
        ok = g["composite"].notna() & g["fwd_1m"].notna()
        if ok.sum() < MIN_NAMES:
            continue
        comp_rows.append((d, g.loc[ok, "composite"].rank().corr(g.loc[ok, "fwd_1m"].rank()), int(ok.sum())))
        qq = pd.qcut(g.loc[ok, "composite"].rank(method="first"), 5, labels=False) + 1
        m = g.loc[ok, "fwd_1m"].groupby(qq).mean() - g.loc[ok, "fwd_1m"].mean()
        for k, v in m.items():
            comp_q.append((d, int(k), v))
    cic = pd.DataFrame(comp_rows, columns=["d", "ic_1m", "n"])
    cq = pd.DataFrame(comp_q, columns=["d", "quintile", "excess_ret"])
    comp = {"signal": "composite", "label": "Walk-forward composite", "family": "composite", "sign": 1,
            "desc": "Equal-weight industry-neutral z-scores of signals proven (t>=2) on data before each month",
            **stats(cic), "q5": float(cq[cq.quintile == 5]["excess_ret"].mean()) if len(cq) else None,
            "q1": float(cq[cq.quintile == 1]["excess_ret"].mean()) if len(cq) else None}
    comp["spread_q5_q1"] = (comp["q5"] or 0) - (comp["q1"] or 0)
    comp["long_leg"] = comp["q5"]

    # signal correlation (average monthly cross-sectional rank correlation)
    good = [r["signal"] for r in summary if r.get("status") in ("predictive", "moderate")]
    corr = {}
    if len(good) > 1:
        mats = []
        for d, g in p.groupby("d"):
            sub = g[[f"{s}__x" for s in good]].rank()
            if len(sub.dropna(how="all")) >= MIN_NAMES:
                mats.append(sub.corr().to_numpy())
        if mats:
            m = np.nanmean(np.stack(mats), axis=0)
            corr = {"signals": good, "matrix": np.round(m, 3).tolist()}

    SIG_DIR.mkdir(parents=True, exist_ok=True)
    ic.to_parquet(SIG_DIR / "ic_monthly.parquet", index=False)
    qd.to_parquet(SIG_DIR / "quintiles_monthly.parquet", index=False)
    cic.to_parquet(SIG_DIR / "composite_ic.parquet", index=False)
    cq.to_parquet(SIG_DIR / "composite_quintiles.parquet", index=False)
    # industry-neutral z-scores (what the composite averages) for decision attribution
    for s in names:
        if s not in zcache:
            zcache[s] = zscore_within(p, f"{s}__x")
        p[f"{s}__z"] = zcache[s]
    # percentile ranks (sign-adjusted: 100 = most favorable) within each month's universe
    for s in names + ["composite"]:
        col = f"{s}__x" if s != "composite" else "composite"
        p[f"{s}__pct"] = p.groupby("d")[col].rank(pct=True) * 100
    keep = (["d", "cik", "industry", "composite", "fwd_1m", "price_raw", "dollar_vol_20d", "mcap"] + names
            + [f"{s}__pct" for s in names + ["composite"]] + [f"{s}__z" for s in names])
    p[keep].to_parquet(SIG_DIR / "scores.parquet", index=False)
    out = {"built": pd.Timestamp.now(tz="UTC").isoformat(), "universe_rule": "price >= $2, 20d $volume >= $1M",
           "signals": summary, "composite": comp, "composite_signals_by_month": used, "correlation": corr}
    (SIG_DIR / "validation.json").write_text(json.dumps(out, default=str, indent=1))
    return {"signals": len(summary), "composite_months": len(used), "seconds": round(time.time() - t0)}


if __name__ == "__main__":
    print(build())
