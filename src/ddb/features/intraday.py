"""Intraday (minute / 5-minute / 15-minute / hourly) data points: build, test, serve.

Input: 1-minute bars from ddb.db.build_intraday. Bars are resampled to each
timeframe in configs/short_term.yaml, aligned to the 09:30 open; each bar is
labeled by its END time (New York) and is public then.

Test (per timeframe, most recent `validate_months` months, month by month):
- universe at each bar: names with a price >= $2 and prior-20-session dollar
  volume above the intraday threshold;
- each data point's cross-sectional rank IC vs the next-bar(s) return, entered at
  the next bar's open and never held past the session close; quintile returns vs
  the bar average, and the top quintile after round-trip spread costs;
- statistics aggregate per trading day, then across days;
- a walk-forward composite: each month uses only the data points that were
  predictive (t >= 3) in earlier months, so its record is out-of-sample.

Outputs, under data/db/signals/intraday/<timeframe>/:
  validation.json   scorecard + composite
  daily_ic.parquet  per day x data point x horizon
  recent.parquet    every bar of the last `recent_sessions` sessions, with values,
                    percentiles and composite, for the dashboard

For the model (learning on bars), `load_pricedata()` returns a PriceData the
backtester can step through bar by bar (ddb.sim.engine with intraday=True).

    python -m ddb.features.intraday [--timeframes 15Min 1Hour]
"""
from __future__ import annotations

import argparse
import json
import time
import warnings

import numpy as np
import pandas as pd

from ..config import DATA_DIR, load
from ..data.prices import PriceData
from . import bars as B

MIN_DIR = DATA_DIR / "db" / "intraday" / "1Min"
MANIFEST = DATA_DIR / "db" / "intraday" / "symbols.parquet"
OUT = DATA_DIR / "db" / "signals" / "intraday"
TF_MINUTES = {"1Min": 1, "5Min": 5, "15Min": 15, "30Min": 30, "1Hour": 60}


# ------------------------------------------------------------------ load + resample
def load_minutes(symbols: list[str] | None, start, end) -> pd.DataFrame:
    """Long frame of 1-minute bars: symbol, t (UTC start), open, high, low, close, volume."""
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    if not MIN_DIR.exists():
        return pd.DataFrame(columns=["symbol", "t", "open", "high", "low", "close", "volume"])
    syms = symbols or sorted(p.name for p in MIN_DIR.iterdir() if p.is_dir())
    parts = []
    for s in syms:
        for y in range(start.year, end.year + 1):
            f = MIN_DIR / s / f"{y}.parquet"
            if f.exists():
                d = pd.read_parquet(f, columns=["t", "open", "high", "low", "close", "volume"])
                d["symbol"] = s
                parts.append(d)
    if not parts:
        return pd.DataFrame(columns=["symbol", "t", "open", "high", "low", "close", "volume"])
    df = pd.concat(parts, ignore_index=True)
    ny = df["t"].dt.tz_convert("America/New_York").dt.tz_localize(None)
    df["t_ny"] = ny
    return df[(ny >= start) & (ny < end + pd.Timedelta(days=1))]


def resample(df: pd.DataFrame, timeframe: str) -> dict[str, pd.DataFrame]:
    """Long 1-minute bars -> wide o/h/l/c/v at `timeframe`, labeled by bar END (NY time).
    A symbol with no trades in a bar gets the previous close (same session) and zero volume."""
    m = TF_MINUTES[timeframe]
    t = df["t_ny"]
    day = t.dt.normalize()
    since_open = ((t - day).dt.total_seconds() // 60 - 570).astype(int)
    end_min = np.minimum((since_open // m + 1) * m, 390)
    df = df.assign(end=day + pd.to_timedelta(570 + end_min, unit="m"))
    g = df.sort_values("t").groupby(["end", "symbol"], sort=True)
    agg = g.agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
                close=("close", "last"), volume=("volume", "sum")).reset_index()
    wide = {f: agg.pivot(index="end", columns="symbol", values=f).sort_index() for f in
            ("open", "high", "low", "close", "volume")}
    c = wide["close"]
    s = B.sessions(c.index)
    c_f = c.groupby(s).ffill()
    missing = c.isna() & c_f.notna()
    for f in ("open", "high", "low"):
        wide[f] = wide[f].where(~missing, c_f)
    wide["close"] = c_f
    wide["volume"] = wide["volume"].where(~missing, 0.0)
    return wide


def load_pricedata(symbols: list[str], timeframe: str, start, end) -> PriceData:
    """PriceData of intraday bars for ddb.sim.engine (SimSettings(intraday=True))."""
    w = resample(load_minutes(symbols, start, end), timeframe)
    return PriceData(open=w["open"], high=w["high"], low=w["low"], close=w["close"], volume=w["volume"])


# ------------------------------------------------------------------ test
def _month_chunks(end: pd.Timestamp, months: int) -> list[pd.Period]:
    last = end.to_period("M")
    return [last - k for k in range(months - 1, -1, -1)]


def build(timeframes: list[str] | None = None) -> dict:
    st = load("short_term")
    cfg = st["intraday"]
    tiers = load("sim")["costs"]["spread_tiers"]
    open_mult = load("sim")["costs"].get("open_spread_multiplier", 1.5)
    sigs = cfg["signals"]
    manifest = pd.read_parquet(MANIFEST) if MANIFEST.exists() else pd.DataFrame(columns=["symbol", "cik"])
    syms = sorted(p.name for p in MIN_DIR.iterdir() if p.is_dir()) if MIN_DIR.exists() else []
    if not syms:
        raise SystemExit("No minute bars yet: run python -m ddb.db.build_intraday first")
    latest = []
    for sym in syms[:50]:
        files = sorted((MIN_DIR / sym).glob("*.parquet"))
        if files:
            latest.append(pd.read_parquet(files[-1], columns=["t"])["t"].max())
    end = max(latest).tz_convert("America/New_York").tz_localize(None).normalize()
    min_dv = cfg["min_dollar_volume_20d"]
    from ..db.build_spreads import align, load_measured
    spreads = load_measured()
    results = {}
    for tf in timeframes or list(cfg["timeframes"]):
        t0 = time.time()
        tcfg = cfg["timeframes"][tf]
        horizons = tcfg["horizons"]
        primary = next(iter(horizons))
        day_rows, comp_rows, tod_rows, used, recent = [], [], [], {}, None
        hist_ic = pd.DataFrame()
        chunks = _month_chunks(end, cfg["validate_months"])
        for p in chunks:
            lo = p.start_time - pd.Timedelta(days=40)       # warm-up for 20-session averages
            raw = load_minutes(syms, lo, min(p.end_time, end + pd.Timedelta(days=1)))
            if raw.empty:
                continue
            w = resample(raw, tf)
            o, h, l, c, v = (w[f] for f in ("open", "high", "low", "close", "volume"))
            feats = B.intraday_features(o, h, l, c, v, tcfg["short"], tcfg["long"])
            dv = B.session_dollar_volume(c, v)
            mask = (c >= cfg["liquidity"]["min_price"]) & (dv >= min_dv)
            measured = align(spreads, c.index, c.columns)
            cost = B.round_trip_cost(dv, tiers, open_mult, entry_at_open=False,   # entries are never at the session open
                                     measured_half_bps=measured)
            fwd = {hn: B.forward_intraday(o, c, hv) for hn, hv in horizons.items()}
            keep = (c.index >= p.start_time) & (c.index <= p.end_time)
            every = int(tcfg.get("validate_every", 1))
            sample = keep & (np.arange(len(c.index)) % every == 0)
            signed, n_before = {}, len(day_rows)
            for s, sc in sigs.items():
                x = (feats[s] * sc["sign"]).where(mask)
                signed[s] = x
                for hn, y in fwd.items():
                    bar_rows = B.cross_section(x.loc[sample], y.loc[sample], cost.loc[sample])
                    r = B.per_day(bar_rows)
                    r["signal"], r["horizon"] = s, hn
                    day_rows.append(r)
                    if hn == primary:      # when during the day does it work?
                        t = bar_rows.dropna(subset=["ic"])
                        tod_rows.append(t.groupby(t.index.strftime("%H:%M"))["ic"].agg(["sum", "count"]).assign(signal=s))
            # walk-forward composite: only data points proven (t >= 3) in EARLIER months
            sel = [x for x in sigs if x in hist_ic and hist_ic[x].notna().sum() >= 40
                   and hist_ic[x].mean() > 0 and B.nw_tstat(hist_ic[x].to_numpy(), 0) >= 3]
            comp = None
            if sel:
                used[str(p)] = sel
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", RuntimeWarning)
                    zs = np.stack([B.zscore_rows(signed[x]).to_numpy() for x in sel])
                    comp = pd.DataFrame(np.nanmean(zs, axis=0), index=c.index, columns=c.columns)
                for hn, y in fwd.items():
                    r = B.per_day(B.cross_section(comp.loc[sample], y.loc[sample], cost.loc[sample]))
                    r["horizon"] = hn
                    comp_rows.append(r)
            this_month = pd.concat([r for r in day_rows[n_before:] if len(r) and r["horizon"].iat[0] == primary]) \
                if any(len(r) for r in day_rows[n_before:]) else pd.DataFrame()
            if len(this_month):
                hist_ic = pd.concat([hist_ic, this_month.pivot_table(index=this_month.index, columns="signal", values="ic")])
            if p == chunks[-1]:
                n_recent = max(1, min(10, int(10 * TF_MINUTES[tf] / 15)))   # 10 sessions of 15-min+ bars, fewer for 1-5 min
                recent = _recent_frame(c, v, dv, mask, feats, sigs, comp, n_recent, manifest)
            print(f"  {tf} {p}: {len(c.columns)} symbols, {keep.sum()} bars, composite uses {len(sel)}", flush=True)
        if not day_rows:
            continue
        dd = pd.concat(day_rows)
        dd.index.name = "day"
        out_dir = OUT / tf
        out_dir.mkdir(parents=True, exist_ok=True)
        dd.reset_index().to_parquet(out_dir / "daily_ic.parquet", index=False)
        tod = pd.concat([t.rename_axis("tod").reset_index() for t in tod_rows]) \
            .groupby(["signal", "tod"])[["sum", "count"]].sum() if tod_rows else pd.DataFrame()
        summary = []
        for s, sc in sigs.items():
            row = {"signal": s, **sc, "horizons": {}}
            if len(tod) and s in tod.index.get_level_values(0):
                t = tod.loc[s]
                row["by_time"] = {str(k): round(float(v), 4) for k, v in (t["sum"] / t["count"]).items()}
            for hn in horizons:
                sub = dd[(dd["signal"] == s) & (dd["horizon"] == hn)].drop(columns=["signal", "horizon"])
                row["horizons"][hn] = B.summarize(sub, role=sc.get("role", "pick"))
            row.update({k: row["horizons"][primary].get(k) for k in ("status", "ic_mean", "t_stat", "pays_after_costs", "edge_net")})
            summary.append(row)
        comp_sum = {}
        if comp_rows:
            cd = pd.concat(comp_rows)
            for hn in horizons:
                comp_sum[hn] = B.summarize(cd[cd["horizon"] == hn].drop(columns=["horizon"]))
            cd.index.name = "day"
            cd.reset_index().to_parquet(out_dir / "composite_daily.parquet", index=False)
        if recent is not None:
            recent.to_parquet(out_dir / "recent.parquet", index=False)
        meta = {"built": pd.Timestamp.now(tz="UTC").isoformat(), "timeframe": tf, "horizons": horizons,
                "primary_horizon": primary, "universe_rule": f"price >= ${cfg['liquidity']['min_price']:g}, "
                f"prior-20-session $volume >= ${min_dv / 1e6:g}M; enter next bar's open, exit by the close",
                "signals": summary, "composite": comp_sum, "composite_signals_by_month": used,
                "bars_per_day": int(390 / TF_MINUTES[tf] + (390 % TF_MINUTES[tf] > 0))}
        (out_dir / "validation.json").write_text(json.dumps(B.clean(meta), default=str, indent=1))
        results[tf] = {"months": len(chunks), "seconds": round(time.time() - t0)}
    return results


def _recent_frame(c, v, dv, mask, feats, sigs, comp, sessions_n, manifest) -> pd.DataFrame:
    s = B.sessions(c.index)
    keep_days = np.unique(s)[-sessions_n:]
    rows = np.isin(s, keep_days)
    out = {"close": c, "volume": v, "dollar_vol": dv}
    out.update({k: feats[k] for k in sigs})
    pct = {f"{k}__pct": (feats[k] * sc["sign"]).where(mask).rank(axis=1, pct=True) * 100 for k, sc in sigs.items()}
    out.update(pct)
    if comp is not None:
        out["composite"] = comp
        out["composite__pct"] = comp.where(mask).rank(axis=1, pct=True) * 100
    long = pd.concat({k: f.loc[rows].stack(future_stack=True) for k, f in out.items()}, axis=1)
    long.index.names = ["ts", "symbol"]
    long = long.reset_index().dropna(subset=["close"])
    if "cik" in manifest:
        long = long.merge(manifest[["symbol", "cik"]].drop_duplicates("symbol"), on="symbol", how="left")
    return long


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeframes", nargs="*")
    a = ap.parse_args()
    print(build(a.timeframes))
