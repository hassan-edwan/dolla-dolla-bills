"""Portfolio sizing and risk, market regime, earnings calendar, 13F, measured spreads,
live tracking and execution quality."""
import json

import numpy as np
import pandas as pd
import pytest

from ddb.features import calendar, regime
from ddb.portfolio.sizing import cap_groups, clusters, risk, size

CFG = {"max_names": 15, "sizing": "inverse_vol", "vol_lookback_days": 63, "max_weight": 0.10, "max_industry": 0.40,
       "cluster_corr": 0.70, "max_cluster": 0.25, "target_vol": 0.25, "min_weight": 0.02, "stress_exposure": 0.5,
       "risk_lookback_days": 126}


def returns(n_days=200, vols=(0.01, 0.02, 0.03), seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2024-01-01", periods=n_days)
    return pd.DataFrame({f"N{i}": rng.normal(0, v, n_days) for i, v in enumerate(vols)}, index=idx)


# ------------------------------------------------------------------ sizing + risk
def test_cap_groups_respects_caps_and_redistributes():
    w = pd.Series([0.5, 0.3, 0.1, 0.1], index=list("abcd"))
    out = cap_groups(w, pd.Series(list("abcd"), index=list("abcd")), 0.3)
    assert out.max() <= 0.3 + 1e-9 and out.sum() == pytest.approx(1.0)
    ind = pd.Series(["x", "x", "y", "y"], index=list("abcd"))
    out = cap_groups(w, ind, 0.4)
    assert out.groupby(ind).sum().max() <= 0.4 + 1e-9
    assert out.sum() == pytest.approx(0.8)          # nowhere to put the excess -> cash


def test_size_inverse_vol_caps_target_vol_and_stress():
    r = returns(vols=[0.01 * (1 + i % 4) for i in range(12)])
    cands = pd.DataFrame({"key": r.columns, "industry": ["a", "b", "c"] * 4})
    w, notes = size(cands, r, CFG)
    assert w.sum() <= 1 + 1e-9 and w.max() <= CFG["max_weight"] + 1e-9
    assert w["N0"] >= w["N3"]                       # calmer name gets at least as much
    hot = {**CFG, "target_vol": 0.05}
    w2, n2 = size(cands, r, hot)
    assert n2["scale"] < 1 and w2.sum() < w.sum()   # scaled down to the volatility target -> cash
    w3, _ = size(cands, r, CFG, stress=True)
    assert w3.sum() == pytest.approx(w.sum() * 0.5, rel=1e-6)


def test_correlated_names_form_a_capped_cluster():
    rng = np.random.default_rng(1)
    idx = pd.bdate_range("2024-01-01", periods=200)
    base = rng.normal(0, 0.02, 200)
    r = pd.DataFrame({f"T{i}": base + rng.normal(0, 0.004, 200) for i in range(4)} |
                     {f"U{i}": rng.normal(0, 0.02, 200) for i in range(8)}, index=idx)
    cl = clusters(r.corr(), 0.7)
    assert len({cl[f"T{i}"] for i in range(4)}) == 1 and len({cl[f"U{i}"] for i in range(8)}) == 8
    cands = pd.DataFrame({"key": r.columns, "industry": [f"i{i}" for i in range(12)]})
    w, _ = size(cands, r, {**CFG, "max_weight": 0.2})
    assert sum(w.get(f"T{i}", 0) for i in range(4)) <= CFG["max_cluster"] + 1e-9


def test_risk_effective_bets():
    rng = np.random.default_rng(2)
    idx = pd.bdate_range("2024-01-01", periods=250)
    indep = pd.DataFrame(rng.normal(0, 0.02, (250, 5)), index=idx, columns=list("abcde"))
    same = pd.DataFrame(np.repeat(rng.normal(0, 0.02, (250, 1)), 5, axis=1) + rng.normal(0, 1e-4, (250, 5)), index=idx, columns=list("abcde"))
    w = pd.Series(0.2, index=list("abcde"))
    assert risk(w, indep)["effective_bets"] > 4
    assert risk(w, same)["effective_bets"] == pytest.approx(5, rel=0.05)    # equal risk shares, but ...
    assert risk(w, same)["diversification"] == pytest.approx(1.0, abs=0.01)  # ... no diversification at all
    mkt = indep.mean(axis=1)
    assert risk(w, indep, mkt)["beta"] == pytest.approx(1.0, abs=0.05)


# ------------------------------------------------------------------ regime
def test_regime_points_and_labels():
    cfg = {"stress_points": 3, "caution_points": 2, "vix_high": 30, "vix_pct_high": 0.9, "hy_oas_high": 6,
           "hy_oas_jump_3m": 1.5, "breadth_low": 0.35}
    df = pd.DataFrame({"vix": [15, 35, 35, 15], "vix_pct": [0.5, 0.95, 0.95, 0.5], "hy_oas": [3, 7, 3, 3],
                       "hy_chg_3m": [0, 2, 0, 0], "mkt_trend": [0.05, -0.1, -0.1, -0.02], "breadth": [0.6, 0.2, 0.5, 0.5],
                       "curve_10y3m": [1, 1, 1, -0.5]})
    out = regime.classify(df, cfg)
    assert list(out["points"]) == [0, 4, 2, 1]
    assert list(out["regime"]) == ["calm", "stress", "caution", "caution"]   # last: 1 point + inverted curve
    assert "yield curve inverted" in out["reasons"].iloc[3]


# ------------------------------------------------------------------ earnings calendar
def test_earnings_estimate_and_overdue():
    reports = pd.to_datetime(["2023-02-10", "2023-05-09", "2023-08-08", "2023-11-07", "2024-02-09", "2024-05-08"])
    df = pd.DataFrame({"cik": 1, "d": reports})
    e = calendar.estimate_next(df, pd.Timestamp("2024-06-01"))
    nxt = e.iloc[0]["next_expected"]
    assert pd.Timestamp("2024-08-01") <= nxt <= pd.Timestamp("2024-08-15") and e.iloc[0]["method"] == "same time last year"
    late = calendar.estimate_next(df, pd.Timestamp("2024-09-01"))
    assert late.iloc[0]["overdue"] and late.iloc[0]["days_to"] == 0


def test_earnings_calendar_is_point_in_time(synth):
    from ddb.db.schema import connect
    root, db = synth
    con = connect(db, read_only=True)
    e1 = calendar.expected_earnings(con, "2018-06-01")
    later = con.execute("""SELECT count(*) FROM filings WHERE items LIKE '%2.02%' AND knowable_at > TIMESTAMPTZ '2018-06-01'""").fetchone()[0]
    assert later > 0 and (pd.to_datetime(e1["last_report"]) <= pd.Timestamp("2018-06-01")).all()
    con.close()


# ------------------------------------------------------------------ 13F
def test_13f_processing_keeps_originals_shares_and_matches_names():
    from ddb.db import build_13f as F
    sub = pd.DataFrame({"ACCESSION_NUMBER": ["A1", "A2", "A3"], "FILING_DATE": ["14-FEB-2024", "15-FEB-2024", "20-MAR-2024"],
                        "SUBMISSIONTYPE": ["13F-HR", "13F-HR", "13F-HR/A"], "CIK": ["111", "222", "111"],
                        "PERIODOFREPORT": ["31-DEC-2023"] * 3})
    info = pd.DataFrame({"ACCESSION_NUMBER": ["A1", "A1", "A2", "A2", "A3"],
                         "NAMEOFISSUER": ["ACME ROCKETS INC", "ACME ROCKETS INC", "Acme Rockets Inc.", "OTHER CO", "ACME ROCKETS INC"],
                         "TITLEOFCLASS": ["COM"] * 5, "CUSIP": ["123456101", "123456101", "123456101", "999999101", "123456101"],
                         "VALUE": ["10", "5", "20", "1", "99"], "SSHPRNAMT": ["100", "50", "200", "10", "999"],
                         "SSHPRNAMTTYPE": ["SH", "SH", "SH", "SH", "SH"], "PUTCALL": [None, "Call", None, None, None]})
    h, filers, cmap = F.process({"submission": sub, "infotable": info}, {"acme rockets": 42})
    assert cmap == {"123456": 42}
    assert set(h["filer_cik"]) == {111, 222}                      # amendment A3 skipped
    assert h.loc[h["filer_cik"] == 111, "shares"].iloc[0] == 100   # the call option row is dropped
    assert (h["knowable_at"] == pd.Timestamp("2024-02-15", tz="UTC")).any()   # filing date + 1 day
    assert len(filers) == 2


def test_inst_features_are_point_in_time(synth):
    root, _ = synth
    p = pd.read_parquet(root / "db" / "signals" / "panel.parquet")
    assert p["inst_breadth_chg"].notna().mean() > 0.5
    assert p["inst_breadth_chg"].abs().max() < 0.3              # no jump from a missing earlier quarter


# ------------------------------------------------------------------ spreads
def test_spread_stats_and_point_in_time_use():
    from ddb.db import build_spreads as SP
    from ddb.sim.costs import CostModel
    q = pd.DataFrame({"symbol": ["A"] * 4 + ["B"] * 2, "window": ["w1", "w1", "w2", "w2", "w1", "w1"],
                      "bp": [10.0, 10.0, 10.0, 0.0, 50.0, 50.0], "ap": [10.02, 10.02, 10.04, 10.0, 50.5, 50.5]})
    st = SP.spread_stats(q).set_index("symbol")
    assert st.loc["A", "spread_bps"] == pytest.approx(np.median([20 / 10.01 * 10, 40 / 10.02 * 10]), rel=1e-3)
    measured = pd.DataFrame({"A": [10.0]}, index=pd.to_datetime(["2024-02-01"]))     # half-spread, usable from Feb 1
    idx = pd.to_datetime(["2024-01-31", "2024-02-15", "2024-07-01"])
    a = SP.align(measured, idx, ["A"])
    assert np.isnan(a.iloc[0, 0]) and a.iloc[1, 0] == 10.0 and np.isnan(a.iloc[2, 0])   # not before, not too old
    cm = CostModel()
    cm.measured = measured
    tier = cm.slippage_frac(0, 2e9, 0.02, at_open=False)
    meas = cm.slippage_frac(0, 2e9, 0.02, at_open=False, symbol="A", date=pd.Timestamp("2024-02-15"))
    assert tier == pytest.approx(1e-4) and meas == pytest.approx(10e-4)


# ------------------------------------------------------------------ portfolio + tracking end to end
def test_model_portfolio_end_to_end(synth):
    root, _ = synth
    s = json.loads((root / "db" / "portfolio" / "summary.json").read_text())
    snaps = json.loads((root / "db" / "portfolio" / "snapshots.json").read_text())
    eq = pd.read_parquet(root / "db" / "portfolio" / "equity.parquet")
    held = [sn for sn in snaps.values() if sn["holdings"]]
    assert held and s["trades"] > 0 and s["costs_paid"] > 0
    for sn in held:
        w = [h["weight"] for h in sn["holdings"]]
        assert sum(w) <= 1 + 1e-6 and max(w) <= 0.10 + 1e-6
        assert sum(sn["industry_weights"].values()) <= 1 + 1e-6 and max(sn["industry_weights"].values()) <= 0.40 + 1e-6
    # the halt line at each date only uses history that ended 18 months earlier
    first_line = eq.dropna(subset=["halt_line"])
    assert first_line.empty or (pd.to_datetime(first_line["d"].iloc[0]) - pd.to_datetime(eq.loc[eq["equity"] != eq["equity"].iloc[0], "d"].iloc[0])).days > 700


def test_tracking_logs_once_and_flags(synth, tmp_path):
    from ddb.db.schema import connect
    from ddb.live import tracking as T
    root, db = synth
    t = json.loads((root / "db" / "live" / "tracking.json").read_text())
    assert t["monthly_forecasts"] and t["walk_forward"]
    assert {f["source"] for f in t["freshness"]} >= {"prices", "filings", "macro"}
    assert next(f for f in t["freshness"] if f["source"] == "prices")["status"] == "stale"   # synthetic data ends 2019
    f = sorted((root / "db" / "live" / "forecasts").glob("monthly_*.parquet"))[0]
    before = pd.read_parquet(f)["logged_at"].iloc[0]
    con = connect(db)
    assert T.log_forecasts(con) == []                             # already logged: never overwritten
    con.close()
    assert pd.read_parquet(f)["logged_at"].iloc[0] == before
    # decay: a signal whose recent IC turned negative raises an alert
    sig = tmp_path / "sig"
    sig.mkdir()
    ic = pd.DataFrame({"d": pd.date_range("2015-01-31", periods=60, freq="ME"), "signal": "x",
                       "ic_1m": [0.05] * 48 + [-0.03] * 12, "ic_3m": 0.0, "n": 50})
    ic.to_parquet(sig / "ic_monthly.parquet")
    (sig / "validation.json").write_text(json.dumps({"signals": [{"signal": "x", "label": "X", "status": "predictive"}],
                                                     "composite_signals_by_month": {"2019-12-31": ["x"]}}))
    old = T.SIG
    T.SIG = sig
    try:
        d = T.decay({"decay_window_months": 12, "decay_window_days": 120, "decay_t_min": 1.0})
    finally:
        T.SIG = old
    assert d[0]["alert"] and d[0]["recent_ic"] < 0


def test_execution_slippage_vs_model():
    from ddb.live.execution import analyze, summarize
    from ddb.sim.costs import CostModel
    fills = pd.DataFrame({"id": ["a", "b"], "symbol": ["X", "X"], "side": ["buy", "sell"], "qty": [10.0, 10.0],
                          "fill": [100.2, 99.9], "submitted_at": ["2024-03-04T15:00:00Z"] * 2,
                          "filled_at": ["2024-03-04T15:00:01Z"] * 2})
    f = analyze(fills, pd.Series([100.0, 100.0]), {"X": 3e7}, {"X": 0.02}, CostModel())
    assert f["realized_bps"].round(6).tolist() == [20.0, 10.0]       # buy paid up 20 bp, sell gave up 10 bp
    assert (f["model_bps"] > 0).all() and not f["at_open"].any()
    s = summarize(f)
    assert s["realized_bps"] == pytest.approx(15.0) and s["worse_than_model_share"] == 1.0


def test_dashboard_queries_for_new_views(synth):
    from ddb.app import queries as Q
    from ddb.db.schema import connect
    root, db = synth
    con = connect(db)
    po = Q.portfolio_overview(con)
    pm = Q.portfolio_month(con, po["months"][-1])
    mk = Q.market_overview(con)
    tr = Q.tracking_overview(con)
    sm = Q.signal_month(con, po["months"][-1])
    assert po["equity"] and "holdings" in pm and mk["days"][-1]["regime"] in ("calm", "caution", "stress")
    assert tr["tracking"]["decay"] is not None and any(r.get("earnings") for r in sm["rows"])
    json.dumps([po, pm, mk, tr, sm])
    con.close()
