"""Daily short-term data points (next-day and 5-day horizons): build, test, serve.

For every trading day t since `start`, for companies in tracked industries
(membership from the latest month-end <= t) that are liquid at t, compute the
data points in configs/short_term.yaml -> daily from information public by
t's close (21:30 UTC), and their forward returns entered at t+1's OPEN.

Fresh-event data points use rows whose knowable_at falls in the last
`fresh_days` trading days: an event becomes usable on the first trading day
whose decision time (close + 30 min) is at or after it was public.

Tested like the monthly signals, but per day and after costs (sim.yaml spread
tiers; buying at the open pays the wider opening spread). A walk-forward
composite uses, each month, only the data points with t >= 3 on earlier days.

Outputs, under data/db/signals/daily/:
  validation.json    scorecard, composite, composite inputs per month
  ic_daily.parquet   day x data point x horizon: IC, quintiles, top-quintile cost
  scores.parquet     the last `keep_scores_days` days: values, percentiles
                     (100 = most favorable), composite, liquidity, cost per name

Survivorship: forward returns of names that stop trading inside the window are
missing (no delisting return here), a small effect at 1-5 day horizons.

    python -m ddb.features.daily
"""
from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd

from ..config import DATA_DIR, load
from ..db.schema import connect
from . import bars as B
from .panel import universe_by_month

OUT = DATA_DIR / "db" / "signals" / "daily"
DB_PATH = DATA_DIR / "ddb.duckdb"
DECISION = pd.Timedelta(hours=21, minutes=30)     # decisions at t's close, as in the monthly panel


def load_bars(con, start: str) -> dict[str, pd.DataFrame]:
    """Wide daily frames by cik: split-adjusted o/h/l/c, volume, as-traded close/volume."""
    px = con.execute(f"""
        WITH prim AS (SELECT cik, upper(current_tickers[1]) AS sym FROM companies WHERE len(current_tickers) > 0),
        y AS (SELECT prim.cik, p.date, p.open, p.high, p.low, p.close, p.volume, p.close_raw, p.volume_raw
              FROM prices p JOIN prim ON upper(p.symbol) = prim.sym
              WHERE p.source = 'yahoo' AND p.date >= DATE '{start}' - INTERVAL 400 DAY),
        a AS (SELECT p.cik, p.date, p.open, p.high, p.low, p.close, p.volume, p.close_raw, p.volume_raw
              FROM prices p WHERE p.source = 'alpaca' AND p.cik IS NOT NULL
                AND p.date >= DATE '{start}' - INTERVAL 400 DAY AND p.cik NOT IN (SELECT DISTINCT cik FROM y))
        SELECT * FROM y UNION ALL SELECT * FROM a
    """).df()
    px["date"] = pd.to_datetime(px["date"])
    px = px.dropna(subset=["close"])
    out = {}
    for f in ("open", "high", "low", "close", "volume", "close_raw", "volume_raw"):
        out[f] = px.pivot_table(index="date", columns="cik", values=f, aggfunc="last").sort_index()
    return out


def place(cal: pd.DatetimeIndex, cols, ev: pd.DataFrame, value: str | None = None) -> pd.DataFrame:
    """Sum (or count) events onto the first trading day whose decision time is >= knowable_at.
    ev: cik, k (knowable_at, tz-aware or UTC-naive) [, value]."""
    out = pd.DataFrame(0.0, index=cal, columns=cols)
    if ev.empty:
        return out
    ev = ev.dropna(subset=["k"]).copy()
    k = pd.to_datetime(ev["k"], utc=True).dt.tz_convert(None)
    decide = (cal + DECISION).to_numpy()
    ev["i"] = np.searchsorted(decide, k.to_numpy(), side="left")
    ev = ev[(ev["i"] < len(cal)) & ev["cik"].isin(cols)]
    ev["v"] = ev[value].astype(float) if value else 1.0
    g = ev.groupby(["i", "cik"])["v"].sum().unstack("cik")
    g.index = cal[g.index.to_numpy()]
    return out.add(g.reindex(index=cal, columns=cols).fillna(0.0))


def event_features(con, cal, cols, ret: pd.DataFrame, fresh: int) -> dict[str, pd.DataFrame]:
    q = lambda sql: con.execute(sql).df()   # noqa: E731
    out = {}
    ev = q("SELECT cik, event_type, knowable_at AS k FROM events WHERE event_date >= DATE '2009-01-01'")
    offer = place(cal, cols, ev[ev["event_type"].isin(["shelf_registration", "offering_prospectus"])])
    out["offering_fresh"] = offer.rolling(fresh, min_periods=1).sum()
    late = place(cal, cols, ev[ev["event_type"].isin(["late_annual_report", "late_quarterly_report"])])
    try:
        fts = q("SELECT cik, knowable_at AS k FROM filing_text_signals WHERE phrase ILIKE '%going concern%'")
    except Exception:  # noqa: BLE001
        fts = pd.DataFrame(columns=["cik", "k"])
    out["distress_fresh"] = (late + place(cal, cols, fts)).rolling(fresh, min_periods=1).sum()

    # earnings: market-adjusted return over the 3 days around a results 8-K (item 2.02),
    # public after the day following the filing; kept for `fresh` days
    ea = q("""SELECT cik, acceptance FROM filings WHERE form LIKE '8-K%' AND items LIKE '%2.02%'
              AND acceptance IS NOT NULL AND filing_date >= DATE '2010-01-01'""")
    ex = ret.sub(ret.median(axis=1), axis=0)
    ear = pd.DataFrame(np.nan, index=cal, columns=cols)
    if len(ea):
        et = pd.to_datetime(ea["acceptance"], utc=True).dt.tz_convert("America/New_York")
        d0 = et.dt.tz_localize(None).dt.normalize() + pd.to_timedelta((et.dt.hour >= 16).astype(int), unit="D")
        i0 = cal.searchsorted(d0)
        exn, cpos = ex.to_numpy(), {c: j for j, c in enumerate(cols)}
        E = ear.to_numpy(copy=True)
        for cik, i in zip(ea["cik"], i0):
            j = cpos.get(cik)
            if j is None or i < 1 or i + 1 >= len(cal):
                continue
            w = exn[i - 1:i + 2, j]
            if np.isfinite(w).sum() >= 2:
                E[i + 1, j] = np.nansum(w)          # known at the close of day i+1
        ear = pd.DataFrame(E, index=cal, columns=cols).ffill(limit=fresh - 1)
    out["earnings_fresh"] = ear

    it = q("""SELECT cik, knowable_at AS k, shares * price AS value FROM insider_transactions
              WHERE NOT is_derivative AND trans_code = 'P' AND NOT trans_date_suspect
                AND NOT coalesce(is_10b5_1_plan, FALSE) AND coalesce(shares * price, 0) BETWEEN 1 AND 2e9""")
    out["insider_buy_fresh"] = np.log1p(place(cal, cols, it, "value").rolling(fresh, min_periods=1).sum())

    try:
        nw = q("SELECT unnest(ciks) AS cik, knowable_at AS k FROM news_events WHERE len(ciks) > 0")
    except Exception:  # noqa: BLE001
        nw = pd.DataFrame(columns=["cik", "k"])
    if len(nw):
        n = place(cal, cols, nw)
        base = n.shift(2).rolling(30, min_periods=20).mean()
        spike = np.log1p(n.rolling(2).sum() / 2) - np.log1p(base)
        start = pd.to_datetime(nw["k"], utc=True).min().tz_convert(None) + pd.Timedelta(days=45)
        spike.loc[spike.index < start] = np.nan
        out["news_spike"] = spike
    else:
        out["news_spike"] = pd.DataFrame(np.nan, index=cal, columns=cols)

    import glob
    wsrc = "data/db/wiki_pageviews/*.parquet" if glob.glob("data/db/wiki_pageviews/*.parquet") \
        else "data/db/wiki_pageviews/parts/*.parquet"
    try:
        wk = q(f"""SELECT cik, CAST(date AS TIMESTAMPTZ) + INTERVAL 1 DAY AS k, views
                   FROM read_parquet('{wsrc}', union_by_name=true)
                   WHERE entity_type = 'company' AND views IS NOT NULL AND cik IS NOT NULL""")
    except Exception:  # noqa: BLE001
        wk = pd.DataFrame()
    if len(wk):
        v = place(cal, cols, wk, "views")
        has = v.gt(0).cumsum() > 0
        out["wiki_spike"] = (np.log1p(v) - np.log1p(v.shift(1).rolling(30, min_periods=20).mean())).where(has)
    else:
        out["wiki_spike"] = pd.DataFrame(np.nan, index=cal, columns=cols)
    return out


def build(db_path=DB_PATH) -> dict:
    t0 = time.time()
    cfg = load("short_term")["daily"]
    sim = load("sim")["costs"]
    sigs = cfg["signals"]
    con = connect(db_path, read_only=True)
    print("prices ...", flush=True)
    W = load_bars(con, cfg["start"])
    c, c_raw = W["close"], W["close_raw"]
    cal_all = c.index

    # universe: membership from the latest month-end on or before each day
    month_ends = sorted({cal_all[cal_all <= m.end_time][-1] for m in
                         pd.period_range(cal_all[0], cal_all[-1], freq="M") if (cal_all <= m.end_time).any()})
    uni = universe_by_month(con, month_ends)
    uni = uni[uni["cik"].isin(c.columns)]
    member = uni.pivot_table(index="d", columns="cik", values="industry", aggfunc="first")
    industry = member.reindex(cal_all, method="ffill")
    cols = industry.columns[industry.notna().any()]
    W = {k: v.reindex(columns=cols) for k, v in W.items()}
    o, h, l, c, v, c_raw, v_raw = (W[k] for k in ("open", "high", "low", "close", "volume", "close_raw", "volume_raw"))
    industry = industry[cols]
    dv20 = (c_raw * v_raw).rolling(20, min_periods=10).mean()
    liq = cfg["liquidity"]
    mask = industry.notna() & (c_raw.ffill(limit=5) >= liq["min_price"]) & (dv20 >= liq["min_dollar_volume_20d"])

    print("features ...", flush=True)
    feats = B.daily_price_features(o, h, l, c, v)
    ret = c.pct_change(fill_method=None)
    feats.update(event_features(con, cal_all, cols, ret, cfg["fresh_days"]))
    con.close()

    keep = cal_all >= pd.Timestamp(cfg["start"])
    cal = cal_all[keep]
    sl = lambda f: f.loc[keep]   # noqa: E731
    mask = sl(mask)
    fwd = {hn: sl(B.forward_daily(o, c, hv)) for hn, hv in cfg["horizons"].items()}
    cost = B.round_trip_cost(sl(dv20), sim["spread_tiers"], sim.get("open_spread_multiplier", 1.5), True)
    signed = {s: (sl(feats[s]) * sc["sign"]).where(mask) for s, sc in sigs.items()}

    print("testing ...", flush=True)
    rows = []
    for s in sigs:
        for hn, y in fwd.items():
            r = B.cross_section(signed[s], y, cost)
            r["signal"], r["horizon"] = s, hn
            rows.append(r)
    ic = pd.concat(rows)
    ic.index.name = "d"
    primary = cfg["primary_horizon"]
    hz = cfg["horizons"]
    summary = []
    for s, sc in sigs.items():
        row = {"signal": s, **sc, "horizons": {}}
        for hn, hv in hz.items():
            sub = ic[(ic["signal"] == s) & (ic["horizon"] == hn)].drop(columns=["signal", "horizon"])
            row["horizons"][hn] = B.summarize(sub, overlap_days=hv - 1, role=sc.get("role", "pick"))
        p = row["horizons"][primary]
        row.update({k: p.get(k) for k in ("status", "ic_mean", "t_stat", "pays_after_costs", "edge_net")})
        row["turnover"] = B.top_turnover(signed[s])
        summary.append(row)

    print("composite ...", flush=True)
    prim_ic = ic[ic["horizon"] == primary].pivot_table(index=ic.index[ic["horizon"] == primary], columns="signal", values="ic")
    comp, used = B.walk_forward_composite(signed, prim_ic, hz[primary], min_days=250, t_min=3.0)
    comp = comp.where(mask)
    comp_sum, comp_rows = {}, []
    for hn, hv in hz.items():
        r = B.cross_section(comp, fwd[hn], cost)
        comp_sum[hn] = B.summarize(r, overlap_days=hv - 1)
        r["horizon"] = hn
        comp_rows.append(r)

    OUT.mkdir(parents=True, exist_ok=True)
    ic.reset_index().to_parquet(OUT / "ic_daily.parquet", index=False)
    cr = pd.concat(comp_rows)
    cr.index.name = "d"
    cr.reset_index().to_parquet(OUT / "composite_daily.parquet", index=False)

    # recent per-name scores for the dashboard
    last = cal[-cfg["keep_scores_days"]:]
    parts = {"industry": industry.loc[last], "price_raw": c_raw.loc[last], "dollar_vol": dv20.loc[last],
             "cost_rt": cost.loc[last], "composite": comp.loc[last],
             "composite__pct": comp.loc[last].rank(axis=1, pct=True) * 100}
    for s in sigs:
        parts[s] = sl(feats[s]).loc[last]
        parts[f"{s}__pct"] = signed[s].loc[last].rank(axis=1, pct=True) * 100
    m = mask.loc[last]
    long = pd.concat({k: f.where(m).stack(future_stack=True) for k, f in parts.items()}, axis=1)
    long.index.names = ["d", "cik"]
    long = long.reset_index().dropna(subset=["industry"])
    long.to_parquet(OUT / "scores.parquet", index=False)

    out = {"built": pd.Timestamp.now(tz="UTC").isoformat(), "horizons": hz, "primary_horizon": primary,
           "universe_rule": f"tracked industries, price >= ${liq['min_price']:g}, 20d $volume >= "
                            f"${liq['min_dollar_volume_20d'] / 1e6:g}M; enter at the next open",
           "signals": summary, "composite": comp_sum, "composite_signals_by_month": used,
           "fresh_days": cfg["fresh_days"]}
    (OUT / "validation.json").write_text(json.dumps(B.clean(out), default=str, indent=1))
    return {"days": len(cal), "companies": len(cols), "rows_scores": len(long), "seconds": round(time.time() - t0)}


if __name__ == "__main__":
    print(build())
