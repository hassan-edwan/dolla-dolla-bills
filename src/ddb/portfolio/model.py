"""The model portfolio: what the monthly system would actually hold, and its risk.

At every month-end since `start`:
- candidates = that month's buy candidates (This month tab: pass every screen,
  top 20% on the walk-forward composite, no red flag), best first;
- sized with ddb.portfolio.sizing using only returns up to that day, and the
  regime known at that day's close;
- a risk snapshot: volatility, beta to the market, each name's share of risk,
  clusters of correlated names, effective number of independent bets, industry
  weights, factor tilts (weighted z-scores), expected excess return from the
  composite's out-of-sample record BEFORE that month, after costs and after tax.

The targets are then traded through the backtester (ddb.sim.engine): next-day
fills at the open, spread + impact costs, T+1 cash settlement, good-faith rule,
FIFO lots, wash sales and yearly taxes. The equity curve gives the drawdown and the
"model is broken" line (99th-percentile 18-month drawdown of the backtest up to
each date).

Outputs, under data/db/portfolio/: targets.parquet, equity.parquet,
snapshots.json (one per month-end), summary.json.

    python -m ddb.portfolio.model
"""
from __future__ import annotations

import json
import time
import warnings

import numpy as np
import pandas as pd

from ..config import DATA_DIR, load
from ..data.prices import PriceData
from ..db.schema import connect
from ..features import bars as B
from ..features.daily import load_bars, load_dividends
from ..metrics import drawdown, drawdown_quantile, summary
from ..sim.costs import CostModel
from ..sim.engine import Backtester, SimSettings
from .sizing import risk, size

OUT = DATA_DIR / "db" / "portfolio"
SIG = DATA_DIR / "db" / "signals"
REGIME = DATA_DIR / "db" / "regime" / "regime.parquet"
DB_PATH = DATA_DIR / "ddb.duckdb"
TILTS = ["size", "mom_12_1", "vol_60d", "book_to_market", "gross_prof", "high_52w"]


class Targets:
    """Strategy that trades to the stored target weights on each month-end."""

    def __init__(self, targets: dict):
        self.targets = targets

    def decide(self, view, pf):
        return self.targets.get(view.date)


def expected_by_quintile(month: pd.Timestamp) -> dict:
    """Average excess return of each composite quintile over months whose results were
    public before `month` (out-of-sample record only)."""
    f = SIG / "composite_quintiles.parquet"
    if not f.exists():
        return {}
    cq = pd.read_parquet(f)
    cq = cq[pd.to_datetime(cq["d"]) < month - pd.Timedelta(days=31)]
    return cq.groupby("quintile")["excess_ret"].mean().to_dict()


def build(db_path=DB_PATH) -> dict:
    from ..app import queries as Q
    t0 = time.time()
    cfg = load("risk")["portfolio"]
    sim_cfg = load("sim")
    st_rate = sim_cfg["account"].get("short_term_tax_rate", 0.32)
    con = connect(db_path)
    sig = Q.signals_overview(con)
    months = [m for m in (sig.get("months") or []) if m >= cfg["start"]]
    reg = pd.read_parquet(REGIME).set_index("d") if REGIME.exists() else pd.DataFrame()
    print(f"candidates for {len(months)} month-ends ...", flush=True)
    cand = {m: Q.signal_month(con, m, limit=10_000) for m in months}
    keep_ciks = sorted({r["cik"] for m in cand.values() for r in m["rows"] if r["verdict"] == "buy candidate"})
    W = load_bars(con, str(pd.Timestamp(cfg["start"]) - pd.Timedelta(days=400))[:10])
    divs = load_dividends(con, cfg["start"], ciks=keep_ciks)
    scores = pd.read_parquet(SIG / "scores.parquet")
    con.close()
    cols = [c for c in keep_ciks if c in W["close"].columns]
    px = {k: W[k][cols] for k in ("open", "high", "low", "close", "volume")}
    rets = px["close"].pct_change(fill_method=None)
    mkt = reg["mkt_ret_1d"] if "mkt_ret_1d" in reg else W["close"].pct_change(fill_method=None).median(axis=1)
    cal = px["close"].index

    targets, rows, snaps = {}, [], {}
    for m in months:
        d = cal[cal <= pd.Timestamp(m)]
        if not len(d):
            continue
        d = d[-1]
        mrows = cand[m]["rows"]
        buys = pd.DataFrame([r for r in mrows if r["verdict"] == "buy candidate" and r["cik"] in cols])
        regime_now = reg["regime"].asof(d) if len(reg) else None
        if buys.empty:
            targets[d] = {}
            snaps[m] = {"month": m, "regime": regime_now, "holdings": [], "risk": {}}
            continue
        buys = buys.sort_values("composite_pct", ascending=False).assign(key=lambda x: x["cik"])
        past = rets.loc[:d]
        w, notes = size(buys, past, cfg, stress=regime_now == "stress")
        targets[d] = {str(k): float(v) for k, v in w.items()}
        rk = risk(w, past.iloc[-cfg["risk_lookback_days"]:], mkt.loc[:d].iloc[-cfg["risk_lookback_days"]:] if len(mkt) else None)
        eq = expected_by_quintile(pd.Timestamp(m))
        sc = scores[pd.to_datetime(scores["d"]) == pd.Timestamp(m)].set_index("cik")
        info = buys.set_index("cik")
        hold = []
        for cik, wt in w.sort_values(ascending=False).items():
            r = info.loc[cik]
            q = min(5, int(np.ceil((r["composite_pct"] or 1) / 20)))
            hold.append({"cik": int(cik), "ticker": r.get("ticker"), "name": r.get("name"), "industry": r.get("industry"),
                         "weight": round(float(wt), 4), "composite_pct": r["composite_pct"],
                         "vol": round(float(notes["vol"].get(cik, np.nan)), 4),
                         "beta": (rk.get("beta_by_name") or {}).get(cik),
                         "risk_share": rk["risk_share"].get(cik), "cluster": int(notes["clusters"].get(cik, -1)),
                         "expected_excess": eq.get(q), "drivers": [x["label"] for x in r.get("drivers") or []]})
            rows.append({"month": m, "d": d, "cik": int(cik), "weight": float(wt)})
        held = list(w.index)
        tilt = {}
        for s in TILTS:
            col = f"{s}__z"
            if col in sc:
                z = sc[col].reindex(held)
                if z.notna().any():
                    tilt[s] = float((z.fillna(0) * w.reindex(held)).sum() / max(w.sum(), 1e-9))
        ind_w = pd.Series({h["industry"]: 0.0 for h in hold})
        for h in hold:
            ind_w[h["industry"]] += h["weight"]
        cl_sizes = pd.Series([h["cluster"] for h in hold]).value_counts()
        groups = [[h["ticker"] for h in hold if h["cluster"] == c] for c in cl_sizes[cl_sizes > 1].index]
        exp_gross = float(sum(h["weight"] * (h["expected_excess"] or 0) for h in hold))
        snaps[m] = B.clean({"month": m, "d": str(d.date()), "regime": regime_now, "holdings": hold,
                            "risk": {k: v for k, v in rk.items() if k not in ("beta_by_name", "risk_share")},
                            "labels": [h["ticker"] for h in hold], "industry_weights": ind_w.round(4).to_dict(),
                            "tilts": tilt, "correlated_groups": groups, "scale": notes["scale"],
                            "expected_excess_month": exp_gross, "candidates": len(buys)})

    print("backtest ...", flush=True)
    names = [str(c) for c in cols]
    data = PriceData(**{k: v.set_axis(names, axis=1) for k, v in px.items()},
                     dividends=divs.reindex(columns=names) if len(divs) else pd.DataFrame())
    settings = SimSettings.from_config(sim_cfg)
    from ..db.build_spreads import load_measured
    con = connect(db_path, read_only=True)
    t = con.execute("SELECT cik, upper(current_tickers[1]) AS s FROM companies WHERE len(current_tickers) > 0").df()
    con.close()
    costs = CostModel.from_config(sim_cfg["costs"])
    costs.measured = load_measured({s: str(c) for s, c in zip(t["s"], t["cik"])})
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res = Backtester(data, Targets(targets), costs, settings) \
            .run(start=min(targets) if targets else None)
    eqs = res.equity
    dd = drawdown(eqs)
    # "model broken" line at each date: from history that ENDS 18 months earlier (so the current
    # drawdown can't move its own threshold), once at least two 18-month windows of trading exist
    halt = pd.Series(np.nan, index=eqs.index)
    moved = eqs.ne(eqs.iloc[0])
    first = int(np.argmax(moved.to_numpy())) if moved.any() else len(eqs)
    for i in range(first + 2 * 378, len(eqs), 21):
        halt.iloc[i:i + 21] = drawdown_quantile(eqs.iloc[first:i - 378])
    bench = (1 + mkt.reindex(eqs.index).fillna(0)).cumprod() * eqs.iloc[0]
    eq_df = pd.DataFrame({"d": eqs.index, "equity": eqs.to_numpy(), "drawdown": dd.to_numpy(),
                          "halt_line": halt.to_numpy(), "benchmark": bench.to_numpy()})
    trades = res.trades
    costs = float((trades["slippage_bps"] / 1e4 * trades["shares"] * trades["ref"]).sum()) if len(trades) else 0.0
    years = max(len(eqs) / 252, 1e-9)
    # realized monthly cost drag, and expected after-cost / after-tax for each snapshot (costs known before it)
    if len(trades):
        tc = trades.assign(cost=trades["slippage_bps"] / 1e4 * trades["shares"] * trades["ref"])
        tc["m"] = pd.to_datetime(tc["date"]).dt.to_period("M")
        mcost = tc.groupby("m")["cost"].sum() / eqs.resample("ME").mean().to_period("M").reindex(tc["m"].unique())
    else:
        mcost = pd.Series(dtype=float)
    for m, sn in snaps.items():
        prior = mcost[mcost.index < pd.Period(m, "M")]
        c = float(prior.mean()) if len(prior) else None
        g = sn.get("expected_excess_month")
        sn["expected_cost_month"] = c
        if g is not None:
            net = g - (c or 0)
            sn["expected_net_month"] = net
            sn["expected_after_tax_month"] = net * (1 - st_rate) if net > 0 else net
    OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(OUT / "targets.parquet", index=False)
    eq_df.to_parquet(OUT / "equity.parquet", index=False)
    (OUT / "snapshots.json").write_text(json.dumps(B.clean(snaps), default=str))
    summ = {k: (str(v) if hasattr(v, "isoformat") else v) for k, v in summary(eqs).items()}
    summ.update({"built": pd.Timestamp.now(tz="UTC").isoformat(), "halt_line": drawdown_quantile(eqs.iloc[first:]),
                 "costs_paid": costs, "costs_per_year_pct": costs / float(eqs.mean()) / years,
                 "taxes_paid": float(res.taxes_paid.sum()), "trades": int(len(trades)),
                 "wash_disallowed": float(res.wash_disallowed_total), "config": cfg,
                 "benchmark": "equal-weight liquid stocks (median daily return)"})
    (OUT / "summary.json").write_text(json.dumps(B.clean(summ), default=str, indent=1))
    return {"months": len(snaps), "trades": len(trades), "final_equity": float(eqs.iloc[-1]), "seconds": round(time.time() - t0)}


if __name__ == "__main__":
    print(build())
