"""Market regime, daily and point in time: is this a market the signals work in?

Inputs at each day's close (21:30 UTC):
- FRED market series (macro table): a value dated d is public on d+1, so at t's
  close we use values through t-1;
- the stock market from our own prices: an equal-weight index of the liquid
  names (daily median return, robust to microcap outliers), and breadth = share of
  those names above their 200-day average.

Columns: vix, vix_pct (percentile in the trailing 5 years), hy_oas, hy_chg_3m,
curve_10y2y, curve_10y3m, mkt_trend (index vs its 200-day average), breadth,
mkt_vol (21-day, annualized), mkt_ret_24m, crash_state, points, regime
(calm / caution / stress), reasons.

How the monthly composite and momentum did in each regime (and in crash states)
is summarized from the out-of-sample record, so the dashboard can say whether
today's regime is one where the model has worked.

    python -m ddb.features.regime
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from ..config import DATA_DIR, load
from ..db.schema import connect
from . import bars as B

OUT = DATA_DIR / "db" / "regime"
SIG = DATA_DIR / "db" / "signals"
DB_PATH = DATA_DIR / "ddb.duckdb"
DECISION = pd.Timedelta(hours=21, minutes=30)


def market_frames(con, start: str = "2009-01-01") -> tuple[pd.Series, pd.Series]:
    """Equal-weight (median) daily return of liquid names, and breadth above the 200-day average."""
    px = con.execute(f"""
        SELECT symbol, date, close, close_raw, volume_raw FROM prices
        WHERE source = 'yahoo' AND date >= DATE '{start}' AND close IS NOT NULL
    """).df()
    if px.empty:
        return pd.Series(dtype=float), pd.Series(dtype=float)
    px["date"] = pd.to_datetime(px["date"])
    c = px.pivot_table(index="date", columns="symbol", values="close", aggfunc="last").sort_index()
    raw = px.pivot_table(index="date", columns="symbol", values="close_raw", aggfunc="last").reindex_like(c)
    dv = (raw * px.pivot_table(index="date", columns="symbol", values="volume_raw", aggfunc="last").reindex_like(c)) \
        .rolling(20, min_periods=10).mean()
    liquid = (raw >= 2) & (dv >= 1e6)
    r = c.pct_change(fill_method=None).where(liquid.shift(1, fill_value=False))
    mkt = r.median(axis=1).where(r.notna().sum(axis=1) >= 10)
    ma = c.rolling(200, min_periods=180).mean()
    above = (c > ma).where(ma.notna() & liquid)
    breadth = above.sum(axis=1) / above.notna().sum(axis=1).where(above.notna().sum(axis=1) >= 10)
    return mkt, breadth


def macro_daily(con, cal: pd.DatetimeIndex) -> pd.DataFrame:
    m = con.execute("SELECT series, date, value, knowable_at FROM macro").df()
    if m.empty:
        return pd.DataFrame(index=cal)
    m["k"] = pd.to_datetime(m["knowable_at"], utc=True).dt.tz_convert(None)
    w = m.pivot_table(index="k", columns="series", values="value", aggfunc="last").sort_index()
    decide = cal + DECISION
    w = w.reindex(w.index.union(decide)).ffill().reindex(decide)
    w.index = cal
    return w


def classify(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    pts = pd.Series(0, index=df.index)
    reasons = [[] for _ in range(len(df))]

    def add(mask, text):
        nonlocal pts
        mask = mask.fillna(False).to_numpy()
        pts = pts + mask
        for i in np.where(mask)[0]:
            reasons[i].append(text)
    add((df["vix"] >= cfg["vix_high"]) | (df["vix_pct"] >= cfg["vix_pct_high"]), "VIX high")
    hy = (df["hy_oas"] >= cfg["hy_oas_high"]) | (df["hy_chg_3m"] >= cfg["hy_oas_jump_3m"])
    if "baa" in df:   # long-history stand-in where the high-yield spread is missing
        baa = (df["baa"] >= cfg.get("baa_high", 3.5)) | (df["baa_chg_3m"] >= cfg.get("baa_jump_3m", 0.75))
        hy = hy.where(df["hy_oas"].notna(), baa)
    add(hy, "credit spreads wide or widening")
    add(df["mkt_trend"] < 0, "market below its 200-day average")
    add(df["breadth"] < cfg["breadth_low"], "few stocks above their 200-day average")
    inverted = (df["curve_10y3m"] < 0).fillna(False)
    out = df.copy()
    out["points"] = pts
    out["inverted"] = inverted
    out["regime"] = np.where(pts >= cfg["stress_points"], "stress",
                             np.where((pts >= cfg["caution_points"]) | ((pts >= 1) & inverted), "caution", "calm"))
    out["reasons"] = ["; ".join(r + (["yield curve inverted"] if inv else [])) for r, inv in zip(reasons, inverted)]
    return out


def build_frame(con, cfg: dict) -> pd.DataFrame:
    mkt, breadth = market_frames(con)
    if mkt.empty:
        return pd.DataFrame()
    cal = mkt.index
    M = macro_daily(con, cal)
    g = lambda s: M[s] if s in M else pd.Series(np.nan, index=cal)   # noqa: E731
    idx = (1 + mkt.fillna(0)).cumprod()
    df = pd.DataFrame(index=cal)
    df["vix"] = g("VIXCLS")
    df["vix_pct"] = df["vix"].rolling(1260, min_periods=250).rank(pct=True)
    df["hy_oas"] = g("BAMLH0A0HYM2")
    df["hy_chg_3m"] = df["hy_oas"] - df["hy_oas"].shift(63)
    df["baa"] = g("BAA10Y")
    df["baa_chg_3m"] = df["baa"] - df["baa"].shift(63)
    df["credit"] = df["hy_oas"].where(df["hy_oas"].notna(), df["baa"])   # whichever is available
    df["curve_10y2y"] = g("T10Y2Y")
    df["curve_10y3m"] = g("DGS10") - g("DGS3MO")
    df["mkt_ret_1d"] = mkt
    df["mkt_index"] = idx
    df["mkt_trend"] = idx / idx.rolling(200, min_periods=180).mean() - 1
    df["breadth"] = breadth
    df["mkt_vol"] = mkt.rolling(21, min_periods=15).std() * np.sqrt(252)
    df["mkt_ret_24m"] = idx / idx.shift(504) - 1
    vol_pct = df["mkt_vol"].rolling(1260, min_periods=250).rank(pct=True)
    df["crash_state"] = (df["mkt_ret_24m"] < cfg["crash_mkt_24m"]) & (vol_pct >= cfg["crash_vol_pct"])
    return classify(df, cfg)


def by_regime(reg: pd.DataFrame) -> dict:
    """Out-of-sample composite and momentum results grouped by the regime at each month-end."""
    out = {}
    f = SIG / "composite_quintiles.parquet"
    if not f.exists() or reg.empty:
        return out
    cq = pd.read_parquet(f).pivot_table(index="d", columns="quintile", values="excess_ret")
    cic = pd.read_parquet(SIG / "composite_ic.parquet").set_index("d")["ic_1m"]
    lab = reg[["regime", "crash_state"]].reindex(pd.to_datetime(cq.index), method="ffill")
    t = pd.DataFrame({"q5": cq[5].to_numpy(), "spread": (cq[5] - cq[1]).to_numpy(),
                      "ic": cic.reindex(cq.index).to_numpy(), "regime": lab["regime"].to_numpy(),
                      "crash": lab["crash_state"].fillna(False).to_numpy()}, index=cq.index)
    for k, g in t.groupby("regime"):
        out[str(k)] = {"months": int(len(g)), "top20_vs_avg": float(g["q5"].mean()), "ic": float(g["ic"].mean()),
                       "hit": float((g["ic"] > 0).mean())}
    icm = SIG / "ic_monthly.parquet"
    if icm.exists():
        im = pd.read_parquet(icm)
        mom = im[im["signal"] == "mom_12_1"].set_index("d")["ic_1m"]
        lab2 = reg[["crash_state"]].reindex(pd.to_datetime(mom.index), method="ffill")["crash_state"].fillna(False)
        out["momentum_in_crash_states"] = {"months": int(lab2.sum()), "ic": float(mom[lab2.to_numpy()].mean()) if lab2.any() else None,
                                           "ic_otherwise": float(mom[~lab2.to_numpy()].mean())}
    return B.clean(out)


def build(db_path=DB_PATH) -> dict:
    cfg = load("risk")["regime"]
    con = connect(db_path, read_only=True)
    reg = build_frame(con, cfg)
    con.close()
    OUT.mkdir(parents=True, exist_ok=True)
    if reg.empty:
        return {"days": 0}
    reg.index.name = "d"
    reg.reset_index().to_parquet(OUT / "regime.parquet", index=False)
    summary = {"built": pd.Timestamp.now(tz="UTC").isoformat(), "thresholds": cfg, "by_regime": by_regime(reg),
               "share_of_days": reg["regime"].value_counts(normalize=True).round(3).to_dict()}
    (OUT / "summary.json").write_text(json.dumps(B.clean(summary), default=str, indent=1))
    return {"days": len(reg), "last": str(reg.index[-1].date()), "regime": reg["regime"].iloc[-1]}


if __name__ == "__main__":
    print(build())
