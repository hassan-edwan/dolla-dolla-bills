"""Short-horizon data points on bar data (daily, hourly, minute) and how to test them.

Everything here works on WIDE frames: index = bar time, columns = symbols.

Point-in-time contract
- Daily frames are indexed by trading date; a bar is public after that day's close.
- Intraday frames are indexed by the bar's END time in New York local time (naive):
  the 09:30-09:35 bar is labeled 09:35 and is public at 09:35.
- A feature at bar i uses bars <= i only.
- Forward returns (targets, never inputs) enter at the OPEN of bar i+1, never at
  bar i's close, and exit at the close of bar i+h. Intraday targets never cross
  into the next session: a window that would is left empty.

Evaluation is cross-sectional: at each bar, rank names by the (sign-adjusted)
feature and compare with their forward returns (rank IC), plus quintile returns
with and without trading costs. Statistics are aggregated per trading day first,
so thousands of minute bars on one day count as one observation for t-stats.
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

MIN_NAMES = 30


# ------------------------------------------------------------------ sessions
def sessions(idx: pd.DatetimeIndex) -> np.ndarray:
    """Trading-day label of each bar."""
    return idx.normalize().to_numpy()


def _first_of_session(idx: pd.DatetimeIndex) -> np.ndarray:
    s = sessions(idx)
    return np.r_[True, s[1:] != s[:-1]]


def _last_of_session(idx: pd.DatetimeIndex) -> np.ndarray:
    s = sessions(idx)
    return np.r_[s[1:] != s[:-1], True]


def _same_session_shift(frame: pd.DataFrame, k: int) -> pd.DataFrame:
    """frame.shift(k), but empty where bar i-k (or i+k for k < 0) is in another session."""
    s = pd.Series(sessions(frame.index))
    same = (s.shift(k) == s).to_numpy()
    out = frame.shift(k)
    out.iloc[~same] = np.nan
    return out


def session_dollar_volume(c: pd.DataFrame, v: pd.DataFrame, days: int = 20) -> pd.DataFrame:
    """Average daily dollar volume over the PRIOR `days` sessions, mapped onto each bar
    (today's volume isn't known until the close, so it is excluded)."""
    s = sessions(c.index)
    daily = (c * v).groupby(s).sum(min_count=1)
    avg = daily.rolling(days, min_periods=max(3, days // 2)).mean().shift(1)
    return avg.reindex(s).set_axis(c.index)


# ------------------------------------------------------------------ features
def daily_price_features(o, h, l, c, v) -> dict[str, pd.DataFrame]:
    """Daily bars (split-adjusted). Values at day t use bars through t's close."""
    prev_c = c.shift(1)
    tr = np.fmax(np.fmax(h - l, (h - prev_c).abs()), (l - prev_c).abs())
    rng = (h - l).where(h > l)
    return {
        "ret_1d": c / prev_c - 1,
        "ret_5d": c / c.shift(5) - 1,
        "gap": o / prev_c - 1,
        "rel_volume": v / v.shift(1).rolling(20, min_periods=10).mean(),
        "close_loc": (c - l) / rng,
        "breakout_20d": c / c.shift(1).rolling(20, min_periods=15).max(),
        "atr_pct": tr.rolling(14, min_periods=10).mean() / c,
    }


def intraday_features(o, h, l, c, v, short: int, long: int) -> dict[str, pd.DataFrame]:
    """Intraday bars (index = bar end, NY time). Window returns stay inside the session;
    a window reaching back past the open starts from the session open instead."""
    s = sessions(c.index)
    first = _first_of_session(c.index)
    sess_open = o.groupby(s).transform("first")
    prev = c.shift(1)
    prev.iloc[first] = o.iloc[first].to_numpy()
    ret_bar = c / prev - 1

    def window(k):
        base = _same_session_shift(c, k)
        return c / base.fillna(sess_open) - 1

    tp = (h + l + c) / 3
    cum_v = v.groupby(s).cumsum()
    vwap = (tp * v).groupby(s).cumsum() / cum_v.where(cum_v > 0)
    hi, lo = h.groupby(s).cummax(), l.groupby(s).cummin()
    tod = c.index.strftime("%H:%M").to_numpy()
    rel_vol = v / v.groupby(tod).transform(lambda x: x.shift(1).rolling(20, min_periods=5).mean())
    last_close = c.groupby(s).last()
    prev_close = last_close.shift(1).reindex(s).set_axis(c.index)
    return {
        "ret_bar": ret_bar,
        "ret_short": window(short),
        "ret_long": window(long),
        "ret_open": c / sess_open - 1,
        "vwap_dist": c / vwap - 1,
        "rel_vol_tod": rel_vol,
        "range_pos": (c - lo) / (hi - lo).where(hi > lo),
        "gap": sess_open / prev_close - 1,
        "bar_vol": ret_bar.rolling(long, min_periods=max(3, long // 2)).std(),
    }


# ------------------------------------------------------------------ targets
def forward_daily(o: pd.DataFrame, c: pd.DataFrame, h: int) -> pd.DataFrame:
    """Enter at the next day's open, exit at the close h days later."""
    return c.shift(-h) / o.shift(-1) - 1


def forward_intraday(o: pd.DataFrame, c: pd.DataFrame, h) -> pd.DataFrame:
    """Enter at bar i+1's open, exit at bar i+h's close (h='close': the session's last bar).
    Empty if the window would leave the session."""
    entry = _same_session_shift(o, -1)
    if h == "close":
        s = sessions(c.index)
        exit_ = c.groupby(s).transform("last")
    else:
        exit_ = _same_session_shift(c, -int(h))
    return exit_ / entry - 1


# ------------------------------------------------------------------ costs
def round_trip_cost(dollar_vol: pd.DataFrame, tiers, open_mult: float = 1.5,
                    entry_at_open: np.ndarray | bool = True) -> pd.DataFrame:
    """Fraction of price lost to spreads on a buy-then-sell, by liquidity tier (sim.yaml).
    The entry pays the wider opening spread when it fills at the session open."""
    tiers = sorted(([float(a), float(b)] for a, b in tiers), key=lambda t: -t[0])
    dv = dollar_vol.to_numpy()
    half = np.full(dv.shape, tiers[-1][1])
    for min_adv, bps in reversed(tiers):
        half = np.where(dv >= min_adv, bps, half)
    half = np.where(np.isfinite(dv), half, np.nan) / 1e4
    mult = np.where(np.asarray(entry_at_open, dtype=bool), open_mult, 1.0)
    if mult.ndim == 1:
        mult = mult[:, None]
    return pd.DataFrame(half * mult + half, index=dollar_vol.index, columns=dollar_vol.columns)


# ------------------------------------------------------------------ evaluation
def _row_rank(x: np.ndarray) -> np.ndarray:
    return pd.DataFrame(x).rank(axis=1).to_numpy()


def cross_section(x: pd.DataFrame, y: pd.DataFrame, cost: pd.DataFrame | None = None,
                  min_names: int = MIN_NAMES) -> pd.DataFrame:
    """Per bar: rank IC of x vs y, number of names, quintile returns vs the bar's average,
    the top quintile's gross return and its average round-trip cost.
    x is already sign-adjusted (higher = expected better) and masked to the universe."""
    X, Y = x.to_numpy(dtype=float), y.reindex_like(x).to_numpy(dtype=float)
    ok = np.isfinite(X) & np.isfinite(Y)
    X, Y = np.where(ok, X, np.nan), np.where(ok, Y, np.nan)
    n = ok.sum(axis=1)
    rx, ry = _row_rank(X), _row_rank(Y)
    with np.errstate(invalid="ignore", divide="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        dx = rx - np.nanmean(rx, axis=1, keepdims=True)
        dy = ry - np.nanmean(ry, axis=1, keepdims=True)
        ic = np.nansum(dx * dy, axis=1) / np.sqrt(np.nansum(dx * dx, axis=1) * np.nansum(dy * dy, axis=1))
        q = np.ceil(rx / n[:, None] * 5)
        ymean = np.nanmean(Y, axis=1)
        out = {"ic": ic, "n": n}
        for k in range(1, 6):
            m = q == k
            cnt = m.sum(axis=1)
            out[f"q{k}"] = np.where(cnt > 0, np.nansum(np.where(m, Y, 0), axis=1) / np.maximum(cnt, 1), np.nan) - ymean
        top = q == 5
        cnt5 = np.maximum(top.sum(axis=1), 1)
        out["q5_gross"] = np.nansum(np.where(top, Y, 0), axis=1) / cnt5
        if cost is not None:
            C = cost.reindex_like(x).to_numpy(dtype=float)
            out["q5_cost"] = np.nansum(np.where(top & np.isfinite(C), C, 0), axis=1) / cnt5
        else:
            out["q5_cost"] = np.zeros(len(n))
    df = pd.DataFrame(out, index=x.index)
    df.loc[df["n"] < min_names, ["ic", "q1", "q2", "q3", "q4", "q5", "q5_gross", "q5_cost"]] = np.nan
    return df


def nw_tstat(x: np.ndarray, lags: int = 0) -> float:
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 12:
        return float("nan")
    e = x - x.mean()
    s = (e @ e) / n
    for L in range(1, lags + 1):
        s += 2 * (1 - L / (lags + 1)) * (e[L:] @ e[:-L]) / n
    return float(x.mean() / np.sqrt(s / n)) if s > 0 else float("nan")


def per_day(rows: pd.DataFrame) -> pd.DataFrame:
    """Average bar-level results within each trading day (one observation per day)."""
    r = rows.dropna(subset=["ic"])
    return r.groupby(r.index.normalize()).mean()


def status_of(t: float, first: float | None, second: float | None) -> str:
    both = (first or 0) > 0 and (second or 0) > 0
    if not np.isfinite(t):
        return "insufficient data"
    if t >= 3 and both:
        return "predictive"
    if t >= 2 and both:
        return "moderate"
    if t >= 1:
        return "weak"
    if t <= -2:
        return "wrong sign"
    return "not predictive"


def summarize(daily: pd.DataFrame, overlap_days: int = 0, role: str = "pick") -> dict:
    """Headline stats from per-day results. overlap_days: Newey-West lags for
    horizons longer than a day (overlapping windows).

    edge_net: what the data point is worth after costs, per trade/holding period.
    - pick/context: top quintile minus the average name, minus the round-trip cost;
    - avoid: how far the worst quintile (the flagged names) lags the average name.
      Avoiding them costs no trades."""
    d = daily.dropna(subset=["ic"])
    if len(d) < 12:
        return {"days": int(len(d)), "status": "insufficient data"}
    mid = d.index[len(d) // 2]
    a, b = d[d.index < mid], d[d.index >= mid]
    t = nw_tstat(d["ic"].to_numpy(), overlap_days)
    long_leg = float(d["q5"].mean())
    cost = float(d["q5_cost"].mean())
    q1 = float(d["q1"].mean())
    out = {
        "days": int(len(d)), "first_day": str(d.index[0].date()), "last_day": str(d.index[-1].date()),
        "ic_mean": float(d["ic"].mean()), "t_stat": t, "hit_rate": float((d["ic"] > 0).mean()),
        "ic_first_half": float(a["ic"].mean()), "ic_second_half": float(b["ic"].mean()), "split": str(mid.date()),
        "quintiles": [float(d[f"q{k}"].mean()) for k in range(1, 6)],
        "long_leg": long_leg, "cost": cost, "long_leg_net": long_leg - cost,
        "top_trade_net": float((d["q5_gross"] - d["q5_cost"]).mean()), "avg_names": float(d["n"].mean()),
    }
    out["status"] = status_of(t, out["ic_first_half"], out["ic_second_half"])
    out["edge_net"] = -q1 if role == "avoid" else out["long_leg_net"]
    out["pays_after_costs"] = bool(np.isfinite(out["edge_net"]) and out["edge_net"] > 0)
    return clean(out)


def clean(o):
    """JSON-safe: NaN/inf -> None, numpy scalars -> Python."""
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return float(o) if np.isfinite(o) else None
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def top_turnover(x: pd.DataFrame, last: int = 250) -> float | None:
    """Share of the top quintile replaced from one bar to the next (recent `last` bars)."""
    top = x.iloc[-last - 1:].rank(axis=1, pct=True) > 0.8
    prev = top.shift(1)
    kept = (top & prev.fillna(False).astype(bool)).sum(axis=1)
    n = top.sum(axis=1)
    rate = 1 - kept / n.where(n > 0)
    v = rate.iloc[1:].mean()
    return float(v) if np.isfinite(v) else None


# ------------------------------------------------------------------ composite
def zscore_rows(x: pd.DataFrame) -> pd.DataFrame:
    lo, hi = x.quantile(0.01, axis=1), x.quantile(0.99, axis=1)
    w = x.clip(lo, hi, axis=0)
    sd = w.std(axis=1)
    return w.sub(w.mean(axis=1), axis=0).div(sd.where(sd > 0), axis=0)


def walk_forward_composite(signed: dict[str, pd.DataFrame], daily_ic: pd.DataFrame, horizon_days: int,
                           min_days: int = 120, t_min: float = 3.0) -> tuple[pd.DataFrame, dict]:
    """At the start of each month, keep the data points whose IC was positive with t >= t_min
    on days whose forward window had ended (more than horizon_days earlier); the composite
    for that month's bars is the average of their row z-scores. Out-of-sample by construction.
    daily_ic: index = day, columns = signal names."""
    any_x = next(iter(signed.values()))
    idx = any_x.index
    months = idx.to_period("M")
    comp = pd.DataFrame(np.nan, index=idx, columns=any_x.columns)
    used: dict[str, list[str]] = {}
    z_cache: dict[str, pd.DataFrame] = {}
    for m in months.unique():
        start = m.start_time
        cutoff = start - pd.tseries.offsets.BDay(horizon_days + 1)
        hist = daily_ic[daily_ic.index < cutoff]
        sel = [s for s in signed if s in hist and hist[s].notna().sum() >= min_days
               and hist[s].mean() > 0 and nw_tstat(hist[s].to_numpy(), max(horizon_days - 1, 0)) >= t_min]
        if not sel:
            continue
        used[str(m)] = sel
        rows = months == m
        zs = []
        for s in sel:
            if s not in z_cache:
                z_cache[s] = zscore_rows(signed[s])
            zs.append(z_cache[s].loc[rows].to_numpy())
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            comp.loc[rows] = np.nanmean(np.stack(zs), axis=0)
    return comp, used
