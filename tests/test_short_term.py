"""Short-term (daily) and intraday data points, the intraday backtester, and the
decision queries, end to end on a synthetic database."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ddb.data.prices import PriceData
from ddb.features import bars as B
from ddb.sim.engine import Backtester, SimSettings

sys.path.insert(0, str(Path(__file__).parent))


def intraday_frames(n_days=30, n_sym=40, step=15, seed=0, drift=0.0):
    """Wide intraday bars labeled by bar END (09:45 ... 16:00)."""
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2024-03-04", periods=n_days)
    per = 390 // step
    idx = pd.DatetimeIndex([d + pd.Timedelta(hours=9, minutes=30 + step * (k + 1)) for d in days for k in range(per)])
    mu = np.repeat(rng.normal(0, drift, (n_days, n_sym)), per, axis=0) if drift else 0.0
    r = rng.normal(0, 0.003, (len(idx), n_sym)) + mu
    c = pd.DataFrame(50 * np.exp(np.cumsum(r, axis=0)), index=idx, columns=[f"S{j}" for j in range(n_sym)])
    o = c.shift(1).fillna(c)
    return o, c * 1.001, c * 0.999, c, pd.DataFrame(1e4, index=idx, columns=c.columns)


# ------------------------------------------------------------------ bars
def test_features_use_only_past_bars():
    o, h, l, c, v = intraday_frames()
    base = B.intraday_features(o, h, l, c, v, short=2, long=8)
    i = 200
    c2, o2 = c.copy(), o.copy()
    c2.iloc[i + 1:] *= 1.5              # change the future only
    o2.iloc[i + 1:] *= 1.5
    after = B.intraday_features(o2, h, l, c2, v, short=2, long=8)
    for k in base:
        pd.testing.assert_frame_equal(base[k].iloc[:i + 1], after[k].iloc[:i + 1], check_exact=False)
    d = B.daily_price_features(o, h, l, c, v)
    d2 = B.daily_price_features(o2, h, l, c2, v)
    for k in d:
        pd.testing.assert_frame_equal(d[k].iloc[:i + 1], d2[k].iloc[:i + 1])


def test_intraday_targets_enter_next_open_and_stay_in_session():
    o, h, l, c, v = intraday_frames(n_days=3)
    y = B.forward_intraday(o, c, 2)
    s = B.sessions(c.index)
    last2 = np.r_[s[2:] != s[:-2], True, True]          # windows that would cross the close
    assert y[last2].isna().all().all()
    i = 5
    assert y.iloc[i, 0] == pytest.approx(c.iloc[i + 2, 0] / o.iloc[i + 1, 0] - 1)
    yc = B.forward_intraday(o, c, "close")
    assert yc.iloc[3, 0] == pytest.approx(c.iloc[25, 0] / o.iloc[4, 0] - 1)   # 26 bars a day
    assert yc.iloc[25].isna().all()                     # no entry after the last bar
    yd = B.forward_daily(o, c, 1)
    assert yd.iloc[0, 0] == pytest.approx(c.iloc[1, 0] / o.iloc[1, 0] - 1)


def test_round_trip_cost_by_tier_and_open():
    dv = pd.DataFrame({"big": [2e9], "mid": [3e7], "tiny": [1e5]})
    tiers = [[1e9, 1.0], [1e8, 3.0], [2e7, 8.0], [5e6, 20.0], [0, 50.0]]
    at_open = B.round_trip_cost(dv, tiers, 1.5, True).iloc[0]
    mid_day = B.round_trip_cost(dv, tiers, 1.5, False).iloc[0]
    assert at_open["big"] == pytest.approx(2.5e-4) and mid_day["big"] == pytest.approx(2e-4)
    assert at_open["mid"] == pytest.approx(8e-4 * 2.5) and at_open["tiny"] == pytest.approx(50e-4 * 2.5)


def test_evaluation_finds_planted_effect_and_not_noise():
    o, h, l, c, v = intraday_frames(drift=0.0006, seed=1)
    f = B.intraday_features(o, h, l, c, v, 2, 8)
    y = B.forward_intraday(o, c, 1)
    s = B.summarize(B.per_day(B.cross_section(f["ret_open"], y)))
    assert s["status"] == "predictive" and s["ic_mean"] > 0.1
    o, h, l, c, v = intraday_frames(seed=2)
    f = B.intraday_features(o, h, l, c, v, 2, 8)
    noise = B.summarize(B.per_day(B.cross_section(f["ret_open"], B.forward_intraday(o, c, 1))))
    assert noise["status"] in ("not predictive", "weak", "wrong sign") and abs(noise["ic_mean"]) < 0.05


def test_costs_decide_whether_it_pays_and_avoid_edge_is_free():
    idx = pd.bdate_range("2024-01-01", periods=40)
    rng = np.random.default_rng(0)
    x = pd.DataFrame(rng.normal(size=(40, 50)), index=idx)
    y = x * 0.001 + rng.normal(0, 0.002, (40, 50))       # top quintile earns ~+14 bp vs average
    cheap = B.summarize(B.cross_section(x, y, pd.DataFrame(0.0005, index=idx, columns=x.columns)))
    dear = B.summarize(B.cross_section(x, y, pd.DataFrame(0.005, index=idx, columns=x.columns)))
    assert cheap["pays_after_costs"] and not dear["pays_after_costs"]
    avoid = B.summarize(B.cross_section(x, y, pd.DataFrame(0.005, index=idx, columns=x.columns)), role="avoid")
    assert avoid["edge_net"] == pytest.approx(-avoid["quintiles"][0]) and avoid["pays_after_costs"]
    json.dumps(avoid)                                     # NaN-free


def test_walk_forward_composite_uses_only_earlier_months():
    idx = pd.bdate_range("2024-01-01", "2024-06-28")
    x = pd.DataFrame(np.random.default_rng(0).normal(size=(len(idx), 40)), index=idx)
    ic = pd.DataFrame({"good": 0.1 + 0.01 * np.sin(np.arange(len(idx)))}, index=idx)
    comp, used = B.walk_forward_composite({"good": x}, ic, horizon_days=1, min_days=40)
    first = min(used)
    hist_end = pd.Period(first).start_time
    assert (ic.index < hist_end).sum() >= 40              # enough history strictly before that month
    assert comp.loc[: hist_end - pd.Timedelta(days=1)].isna().all().all()


# ------------------------------------------------------------------ intraday backtester
def hourly_pricedata(days=3):
    d0 = pd.bdate_range("2025-03-03", periods=days)
    idx = pd.DatetimeIndex(sorted([d + pd.Timedelta(hours=10, minutes=30) + pd.Timedelta(hours=k) for d in d0 for k in range(6)]
                                  + [d + pd.Timedelta(hours=16) for d in d0]))
    c = pd.DataFrame({"AAA": np.linspace(100, 110, len(idx))}, index=idx)
    return PriceData(open=c.shift(1).fillna(100), high=c * 1.001, low=c * 0.999, close=c, volume=c * 0 + 1e6)


class DayTrader:
    def decide(self, view, pf):
        left = view.bars_left_in_session()
        if left == 1:
            return {}                   # sell at the last bar's open: flat by the close
        if left == 6:
            return {"AAA": 1.0}
        return None


def test_intraday_backtest_day_trades_under_cash_rules():
    data = hourly_pricedata()
    r = Backtester(data, DayTrader(), settings=SimSettings(intraday=True, pay_taxes=False)).run()
    t = r.trades
    # day 1: no prior-session liquidity yet -> the participation cap blocks the order
    assert (r.cancelled["reason"] == "participation_cap").any()
    assert list(t["side"]) == ["buy", "sell", "buy", "sell"]
    assert all(t["date"].dt.normalize() == t["date"].dt.normalize().iloc[[0, 0, 2, 2]].to_numpy())
    # each day's sale settles T+1, so the next day's buy uses settled cash (no good-faith block)
    assert "good_faith" not in set(r.cancelled["reason"])
    # only the session's first bar pays the opening spread; these fills are mid-session
    assert (t["slippage_bps"] < 5).all()


def test_intraday_settlement_counts_trading_days():
    data = hourly_pricedata(days=4)
    bt = Backtester(data, DayTrader(), settings=SimSettings(intraday=True))
    i = 3                                   # a bar on day 1
    assert bt._settle_date(i) == pd.Timestamp("2025-03-04")


# ------------------------------------------------------------------ end to end on a synthetic database
@pytest.fixture(scope="module")
def synth(tmp_path_factory):
    from synth import make_db
    from ddb.app import queries as Q
    from ddb.features import daily, panel, validate
    root = tmp_path_factory.mktemp("synth")
    db = make_db(root, n=40, start="2016-01-04", end="2019-12-31")
    sig = root / "db" / "signals"
    old = (panel.OUT, validate.SIG_DIR, daily.OUT, Q.SIG)
    panel.OUT, validate.SIG_DIR, daily.OUT, Q.SIG = sig, sig, sig / "daily", sig.as_posix()
    import os
    cwd = os.getcwd()
    os.chdir(root)
    try:
        panel.build("2016-01", db_path=db)
        validate.build()
        daily.build(db_path=db)
        yield root, db
    finally:
        os.chdir(cwd)
        panel.OUT, validate.SIG_DIR, daily.OUT, Q.SIG = old


def test_daily_pipeline_finds_planted_effects(synth):
    root, _ = synth
    v = json.loads((root / "db" / "signals" / "daily" / "validation.json").read_text())
    st = {s["signal"]: s for s in v["signals"]}
    assert st["ret_1d"]["status"] == "predictive"            # planted next-day reversal
    assert st["offering_fresh"]["status"] in ("predictive", "moderate")
    assert st["offering_fresh"]["edge_net"] > 0               # flagged names lag
    assert set(v["composite"]) == {"fwd_1d", "fwd_5d"}


def test_decision_queries(synth):
    from ddb.app import queries as Q
    from ddb.db.schema import connect
    root, db = synth
    con = connect(db)
    sig = Q.signals_overview(con)
    m = Q.signal_month(con, sig["months"][-1])
    assert m["rows"] and {"verdict", "questions", "flags", "drivers", "change"} <= set(m["rows"][0])
    assert set(m["questions"]) == {"business", "trend", "distress", "speculation", "flows"}
    assert all(r["verdict"] != "buy candidate" or (r["composite_pct"] >= 80 and not r["flags"]) for r in m["rows"])
    assert {"entered", "left", "new_flags", "prev_month"} <= set(m["changes"])
    t = Q.short_term_day(con, "2019-12-31")
    assert t["day"] == "2019-12-31" and t["rows"]
    late = Q.short_term_day(con, "2019-06-15")      # a Saturday -> latest trading day before it
    assert late["day"] == "2019-06-14"
    ov = Q.short_term_overview(con)
    assert ov["daily"]["signals"] and ov["daily"]["days"][-1] == "2019-12-31"
    c = Q.company(con, 1001)
    assert c["short_term"]["daily"] and c["signals"][-1]["verdict"]
    json.dumps([sig, m, t, ov, c])
    con.close()


def test_intraday_pipeline(tmp_path, monkeypatch):
    from ddb.features import intraday as I
    rng = np.random.default_rng(4)
    days = pd.bdate_range("2025-01-02", "2025-03-31")
    monkeypatch.setattr(I, "MIN_DIR", tmp_path / "1Min")
    monkeypatch.setattr(I, "MANIFEST", tmp_path / "symbols.parquet")
    monkeypatch.setattr(I, "OUT", tmp_path / "out")
    for j in range(35):
        rows, px = [], 40.0
        for d in days:
            t = pd.date_range(d + pd.Timedelta(hours=9, minutes=30), periods=390, freq="1min").tz_localize("America/New_York").tz_convert("UTC")
            r = rng.normal(0, 0.0008, 390) + rng.normal(0, 0.00015)      # per-name daily drift
            c = px * np.exp(np.cumsum(r))
            o = np.r_[px, c[:-1]]
            px = c[-1]
            rows.append(pd.DataFrame({"t": t, "open": o, "high": np.maximum(o, c), "low": np.minimum(o, c), "close": c,
                                      "volume": np.full(390, 5000.0)}))
        (tmp_path / "1Min" / f"S{j}").mkdir(parents=True)
        pd.concat(rows).to_parquet(tmp_path / "1Min" / f"S{j}" / "2025.parquet", index=False)
    pd.DataFrame({"symbol": [f"S{j}" for j in range(35)], "cik": range(35)}).to_parquet(tmp_path / "symbols.parquet")
    orig = I.load

    def fake(name):
        c = orig(name)
        if name == "short_term":
            c["intraday"]["validate_months"] = 3
            c["intraday"]["min_dollar_volume_20d"] = 1e5
        return c
    monkeypatch.setattr(I, "load", fake)
    I.build(["1Hour"])
    v = json.loads((tmp_path / "out" / "1Hour" / "validation.json").read_text())
    st = {s["signal"]: s for s in v["signals"]}
    assert st["ret_open"]["status"] == "predictive"            # the planted daily drift
    assert set(st["ret_open"]["by_time"]) <= {"10:30", "11:30", "12:30", "13:30", "14:30", "15:30", "16:00"}
    w = I.resample(I.load_minutes(["S0"], "2025-01-02", "2025-01-02"), "1Hour")
    assert list(w["close"].index.strftime("%H:%M")) == ["10:30", "11:30", "12:30", "13:30", "14:30", "15:30", "16:00"]
    m = I.load_minutes(["S0"], "2025-01-02", "2025-01-02")
    assert w["open"].iloc[0, 0] == pytest.approx(m["open"].iloc[0]) and w["close"].iloc[-1, 0] == pytest.approx(m["close"].iloc[-1])
