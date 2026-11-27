"""Observation dataset for the RL allocator (Phase 3: one level, industries + haven).

What the allocator decides, each week: how much to put in each industry sleeve,
in gold, in T-bills, and in cash.

- Industry sleeve = that industry's current buy candidates (This month tab: pass
  every screen, top 20% on the walk-forward composite, no red flag), the top
  `names_per_sleeve` by composite, inverse-volatility weighted. Composition comes
  from the latest month-end on or before the decision date.
- Haven = the first available of the configured gold / T-bill ETFs.

Observation at each decision date (all public by that day's close):
- market regime (ddb.features.regime): VIX and its percentile, credit spread and its
  3-month change, yield curve, market trend, breadth, market volatility,
  24-month market return, crash state, stress points;
- per industry: equal-weight index return over 4 / 12 / 26 weeks, 12-week
  volatility, distance from the 200-day average, breadth; number of buy
  candidates and their average composite percentile; median composite of all
  screened names;
- per haven asset: 4 / 12-week return and trend; the 3-month T-bill yield.
Features are standardized with mean / std from the TRAIN period only.

Outputs, under data/db/rl/: obs.parquet, sleeves.parquet, prices_<field>.parquet,
meta.json.

    python -m ddb.rl.dataset
"""
from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd

from ..config import DATA_DIR, load
from ..db.schema import connect
from ..features import bars as B
from ..features.daily import load_bars, load_dividends
from .splits import periods

OUT = DATA_DIR / "db" / "rl"
SIG = DATA_DIR / "db" / "signals"
REGIME = DATA_DIR / "db" / "regime" / "regime.parquet"
DB_PATH = DATA_DIR / "ddb.duckdb"
REGIME_COLS = ["vix", "vix_pct", "credit", "baa", "baa_chg_3m", "curve_10y3m", "mkt_trend", "breadth", "mkt_vol",
               "mkt_ret_24m", "crash_state", "points"]


def symbol_bars(con, symbols: list[str], start: str) -> dict[str, pd.DataFrame]:
    px = con.execute(f"""
        SELECT upper(symbol) AS symbol, date, open, high, low, close, volume FROM prices
        WHERE source = 'yahoo' AND upper(symbol) IN ({','.join(f"'{s.upper()}'" for s in symbols)})
          AND date >= DATE '{start}' AND close IS NOT NULL
    """).df()
    px["date"] = pd.to_datetime(px["date"])
    return {f: px.pivot_table(index="date", columns="symbol", values=f, aggfunc="last").sort_index()
            for f in ("open", "high", "low", "close", "volume")}


def weekly_dates(cal: pd.DatetimeIndex, start, end=None) -> pd.DatetimeIndex:
    c = cal[(cal >= pd.Timestamp(start)) & ((cal <= pd.Timestamp(end)) if end is not None else True)]
    wk = pd.Series(c, index=c).groupby(c.to_period("W-FRI")).max()
    return pd.DatetimeIndex(wk.to_numpy())


def build(db_path=DB_PATH) -> dict:
    from ..app import queries as Q
    t0 = time.time()
    cfg = load("rl")
    dcfg = cfg["dataset"]
    con = connect(db_path)
    sig = Q.signals_overview(con)
    months = [m for m in (sig.get("months") or []) if m >= str(pd.Timestamp(dcfg["start"]) - pd.Timedelta(days=40))[:10]]
    print(f"sleeves for {len(months)} month-ends ...", flush=True)
    sleeve_rows, month_feats = [], []
    for m in months:
        sm = Q.signal_month(con, m, limit=100_000)
        rows = pd.DataFrame(sm["rows"])
        if rows.empty:
            continue
        for ind, g in rows.groupby("industry"):
            b = g[g["verdict"] == "buy candidate"].sort_values("composite_pct", ascending=False)
            month_feats.append({"month": m, "industry": ind, "n_candidates": len(b),
                                "cand_score": b["composite_pct"].mean() if len(b) else np.nan,
                                "median_score": g["composite_pct"].median()})
            for r in b.head(dcfg["names_per_sleeve"]).itertuples():
                sleeve_rows.append({"month": m, "industry": ind, "cik": int(r.cik), "ticker": r.ticker})
    sleeves = pd.DataFrame(sleeve_rows)
    mf = pd.DataFrame(month_feats)
    industries = sorted(mf["industry"].unique()) if len(mf) else []

    print("prices ...", flush=True)
    W = load_bars(con, dcfg["start"])
    haven_syms = [s for v in dcfg["haven"].values() for s in v]
    H = symbol_bars(con, haven_syms, dcfg["start"])
    macro = con.execute("SELECT date, value FROM macro WHERE series = 'DGS3MO'").df()
    ciks_all = sorted(sleeves["cik"].unique()) if len(sleeves) else []
    divs = load_dividends(con, dcfg["start"], ciks=ciks_all, symbols=haven_syms)
    con.close()
    cal = W["close"].index
    dates = weekly_dates(cal, dcfg["start"])

    # industry equal-weight indexes from the monthly liquid universe (scores.parquet)
    sc = pd.read_parquet(SIG / "scores.parquet", columns=["d", "cik", "industry"])
    sc["d"] = pd.to_datetime(sc["d"])
    member = sc.pivot_table(index="d", columns="cik", values="industry", aggfunc="first").reindex(cal, method="ffill")
    member = member.reindex(columns=[c for c in member.columns if c in W["close"].columns])
    close = W["close"][member.columns]
    ret = close.pct_change(fill_method=None)
    feats = {}
    ma = close.rolling(200, min_periods=150).mean()
    for ind in industries:
        m = member.eq(ind).shift(1, fill_value=False)     # membership known at the prior close
        r = ret.where(m).median(axis=1)
        idx = (1 + r.fillna(0)).cumprod()
        above = (close > ma).where(m & ma.notna())
        f = pd.DataFrame({"ret_4w": idx / idx.shift(20) - 1, "ret_12w": idx / idx.shift(60) - 1,
                          "ret_26w": idx / idx.shift(130) - 1,
                          "vol_12w": r.rolling(60, min_periods=40).std() * np.sqrt(252),
                          "trend": idx / idx.rolling(200, min_periods=150).mean() - 1,
                          "breadth": above.sum(axis=1) / above.notna().sum(axis=1).where(above.notna().sum(axis=1) > 0)})
        feats[ind] = f
    obs = pd.DataFrame(index=dates)
    if REGIME.exists():
        reg = pd.read_parquet(REGIME).set_index("d")
        reg.index = pd.to_datetime(reg.index)
        rr = reg[REGIME_COLS].astype(float).reindex(dates, method="ffill")
        obs = obs.join(rr.add_prefix("mkt__"))
    for ind, f in feats.items():
        obs = obs.join(f.reindex(dates).add_prefix(f"{ind}__"))
        g = mf[mf["industry"] == ind].assign(month=lambda x: pd.to_datetime(x["month"])).set_index("month")
        g = g[["n_candidates", "cand_score", "median_score"]].reindex(g.index.union(dates)).ffill().reindex(dates)
        obs = obs.join(g.add_prefix(f"{ind}__"))
    hc = H["close"]
    asset_of = {}
    for kind, syms in dcfg["haven"].items():
        # first symbol with a price on each date
        pick = pd.Series(np.nan, index=cal, dtype=object)
        for sym in reversed(syms):
            if sym in hc:
                pick[hc[sym].reindex(cal).notna().to_numpy()] = sym
        asset_of[kind] = pick
        px = pd.Series(np.nan, index=cal)
        for sym in syms:
            if sym in hc:
                px = px.fillna(hc[sym].reindex(cal))
        obs[f"{kind}__ret_4w"] = (px / px.shift(20) - 1).reindex(dates)
        obs[f"{kind}__ret_12w"] = (px / px.shift(60) - 1).reindex(dates)
        obs[f"{kind}__trend"] = (px / px.rolling(200, min_periods=150).mean() - 1).reindex(dates)
    if len(macro):
        tb = macro.assign(date=pd.to_datetime(macro["date"]) + pd.Timedelta(days=1)).set_index("date")["value"].sort_index()
        obs["tbill_yield"] = tb.reindex(tb.index.union(dates)).ffill().reindex(dates)
    obs = obs.astype(float)
    tr0, tr1 = periods()["train"]
    train = obs[(obs.index >= tr0) & (obs.index <= tr1)]
    mean, std = train.mean(), train.std().replace(0, 1).fillna(1)

    OUT.mkdir(parents=True, exist_ok=True)
    obs.index.name = "d"
    obs.reset_index().to_parquet(OUT / "obs.parquet", index=False)
    sleeves.to_parquet(OUT / "sleeves.parquet", index=False)
    ciks = sorted(sleeves["cik"].unique()) if len(sleeves) else []
    for f in ("open", "high", "low", "close", "volume"):
        a = W[f].reindex(columns=[c for c in ciks if c in W[f].columns])
        a.columns = [str(c) for c in a.columns]
        b = H[f].reindex(index=a.index) if len(H[f]) else pd.DataFrame(index=a.index)
        a.join(b).reset_index().rename(columns={"index": "date"}).to_parquet(OUT / f"prices_{f}.parquet", index=False)
    if len(divs):
        idx = pd.read_parquet(OUT / "prices_close.parquet", columns=["date"])["date"]
        dv = divs.reindex(pd.DatetimeIndex(pd.to_datetime(idx))).fillna(0.0)
        dv.index.name = "date"
        dv.reset_index().to_parquet(OUT / "prices_dividends.parquet", index=False)
    haven_pick = pd.DataFrame(asset_of).reindex(dates)
    haven_pick.index.name = "d"
    haven_pick.reset_index().to_parquet(OUT / "haven.parquet", index=False)
    missing = obs[(obs.index >= tr0)].isna().mean()
    meta = {"built": pd.Timestamp.now(tz="UTC").isoformat(), "industries": industries,
            "assets": industries + list(dcfg["haven"]), "features": list(obs.columns),
            "mean": mean.to_dict(), "std": std.to_dict(), "decision_dates": len(dates),
            "first": str(dates[0].date()) if len(dates) else None, "last": str(dates[-1].date()) if len(dates) else None,
            "missing_share_after_train_start": missing.round(4).to_dict(), "config": dcfg}
    (OUT / "meta.json").write_text(json.dumps(B.clean(meta), default=str, indent=1))
    return {"dates": len(dates), "features": obs.shape[1], "industries": len(industries),
            "sleeve_names": len(ciks), "seconds": round(time.time() - t0)}


if __name__ == "__main__":
    print(build())
