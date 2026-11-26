"""Execution quality: what fills actually cost vs what the cost model assumed.

For each filled order in the Alpaca paper account (or any broker export with the
same columns):
- arrival price = the open of the first 1-minute bar at or after the order was
  submitted (from the intraday store, else fetched from Alpaca), or that day's
  open for orders placed before the open;
- realized slippage (bps) = how much worse the fill was than the arrival price
  (buys: fill above arrival; sells: fill below);
- model slippage (bps) = ddb.sim.costs.CostModel for the same order size, the
  name's 20-day dollar volume and volatility, and whether it filled at the open.

If realized costs run above the model, every backtest and every "pays after
costs" verdict on the dashboard is too optimistic, so this is checked first.

    python -m ddb.live.execution [--days 90]
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd

from ..config import DATA_DIR, load
from ..features import bars as B
from ..sim.costs import CostModel

OUT = DATA_DIR / "db" / "live"
MIN_DIR = DATA_DIR / "db" / "intraday" / "1Min"


def fetch_fills(days: int = 90) -> pd.DataFrame:
    from ..data.alpaca import TRADING, Alpaca
    api = Alpaca()
    after = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=days)).isoformat()
    rows, until = [], None
    while True:
        params = {"status": "closed", "limit": 500, "after": after, "direction": "desc"}
        if until:
            params["until"] = until
        batch = api.s.get(f"{TRADING}/v2/orders", params=params).json()
        rows += [o for o in batch if o.get("filled_at")]
        if len(batch) < 500:
            break
        until = batch[-1]["submitted_at"]
    df = pd.DataFrame([{"id": o["id"], "symbol": o["symbol"], "side": o["side"], "qty": float(o["filled_qty"]),
                        "fill": float(o["filled_avg_price"]), "submitted_at": o["submitted_at"],
                        "filled_at": o["filled_at"], "type": o.get("type")} for o in rows])
    return df


def arrival_prices(fills: pd.DataFrame, minute_bars: pd.DataFrame | None = None) -> pd.Series:
    """Open of the first minute bar at/after submission. minute_bars: symbol, t (UTC start), open."""
    if minute_bars is None:
        parts = []
        for s in fills["symbol"].unique():
            for y in pd.to_datetime(fills["submitted_at"], utc=True).dt.year.unique():
                f = MIN_DIR / s / f"{y}.parquet"
                if f.exists():
                    parts.append(pd.read_parquet(f, columns=["t", "open"]).assign(symbol=s))
        minute_bars = pd.concat(parts) if parts else pd.DataFrame(columns=["symbol", "t", "open"])
    out = {}
    for r in fills.itertuples():
        b = minute_bars[minute_bars["symbol"] == r.symbol].sort_values("t")
        t = pd.Timestamp(r.submitted_at)
        t = t.tz_localize("UTC") if t.tzinfo is None else t
        after = b[b["t"] >= t.floor("min")]
        out[r.Index] = float(after["open"].iloc[0]) if len(after) else np.nan
    return pd.Series(out)


def analyze(fills: pd.DataFrame, arrival: pd.Series, adv: dict, vol: dict, costs: CostModel) -> pd.DataFrame:
    """Realized vs model slippage per fill. adv/vol: symbol -> 20-day $ volume / daily volatility."""
    f = fills.copy()
    f["arrival"] = arrival.reindex(f.index)
    sign = np.where(f["side"] == "buy", 1, -1)
    f["realized_bps"] = sign * (f["fill"] / f["arrival"] - 1) * 1e4
    ny = pd.to_datetime(f["filled_at"], utc=True).dt.tz_convert("America/New_York")
    f["at_open"] = (ny.dt.hour == 9) & (ny.dt.minute < 35)
    f["value"] = f["qty"] * f["fill"]
    f["adv"] = f["symbol"].map(adv)
    f["model_bps"] = [costs.slippage_frac(v, a if a == a else 0.0, vol.get(s, np.nan), bool(o)) * 1e4
                      for v, a, s, o in zip(f["value"], f["adv"], f["symbol"], f["at_open"])]
    f["tier_bps"] = [costs.half_spread_bps(a if a == a else 0.0) for a in f["adv"]]
    f["excess_bps"] = f["realized_bps"] - f["model_bps"]
    return f


def summarize(f: pd.DataFrame) -> dict:
    if f.empty:
        return {"fills": 0}
    g = f.dropna(subset=["realized_bps"])
    by = g.groupby("tier_bps").agg(fills=("id", "count"), realized_bps=("realized_bps", "mean"),
                                   model_bps=("model_bps", "mean")).reset_index()
    return B.clean({"fills": int(len(f)), "with_arrival": int(len(g)),
                    "realized_bps": float(g["realized_bps"].mean()) if len(g) else None,
                    "model_bps": float(g["model_bps"].mean()) if len(g) else None,
                    "value_weighted_realized_bps": float(np.average(g["realized_bps"], weights=g["value"])) if len(g) else None,
                    "worse_than_model_share": float((g["excess_bps"] > 0).mean()) if len(g) else None,
                    "by_tier": by.to_dict(orient="records")})


def build(days: int = 90) -> dict:
    from ..db.schema import connect
    fills = fetch_fills(days)
    OUT.mkdir(parents=True, exist_ok=True)
    if fills.empty:
        (OUT / "execution.json").write_text(json.dumps({"fills": 0, "built": pd.Timestamp.now(tz="UTC").isoformat()}))
        return {"fills": 0}
    con = connect(DATA_DIR / "ddb.duckdb", read_only=True)
    syms = ",".join(f"'{s}'" for s in fills["symbol"].unique())
    st = con.execute(f"""SELECT upper(symbol) AS symbol, date, close_raw * volume_raw AS dv, close FROM prices
                        WHERE upper(symbol) IN ({syms}) AND date >= current_date - INTERVAL {days + 60} DAY""").df()
    con.close()
    adv, vol = {}, {}
    for s, g in st.sort_values("date").groupby("symbol"):
        adv[s] = float(g["dv"].tail(20).mean())
        vol[s] = float(g["close"].pct_change().tail(20).std())
    sim = load("sim")["costs"]
    f = analyze(fills, arrival_prices(fills), adv, vol, CostModel.from_config(sim))
    f.to_parquet(OUT / "fills.parquet", index=False)
    s = summarize(f)
    s["built"] = pd.Timestamp.now(tz="UTC").isoformat()
    s["recent"] = B.clean(f.sort_values("filled_at", ascending=False).head(100)[
        ["symbol", "side", "qty", "fill", "arrival", "filled_at", "realized_bps", "model_bps", "at_open"]].to_dict(orient="records"))
    (OUT / "execution.json").write_text(json.dumps(s, default=str, indent=1))
    return {k: s[k] for k in ("fills", "realized_bps", "model_bps")}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    print(build(ap.parse_args().days))
