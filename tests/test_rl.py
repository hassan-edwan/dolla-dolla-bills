"""RL: splits, the stepping engine, the allocator environment, baselines, readiness."""
import math

import numpy as np
import pandas as pd
import pytest

from ddb.rl import splits as S


def test_splits_embargo_lock_and_purge(tmp_path, monkeypatch):
    cfg = {"train": ["2016-01-01", "2019-12-31"], "validation": ["2020-01-01", "2020-12-31"],
           "test": ["2021-01-01", "2021-12-31"], "embargo_days": 30}
    monkeypatch.setattr(S, "OVERRIDE", cfg)
    monkeypatch.setattr(S, "LOG", tmp_path / "log")
    p = S.periods()
    assert p["validation"][0] == pd.Timestamp("2020-01-31") and p["train"][0] == pd.Timestamp("2016-01-01")
    with pytest.raises(PermissionError):
        S.open_split("test")
    assert S.test_accesses() == 0
    S.open_split("test", allow_test=True, who="final")
    assert S.test_accesses() == 1
    d = pd.DatetimeIndex(["2019-12-01", "2019-12-20", "2020-01-10", "2020-02-10"])
    lab = S.label(d)
    assert list(lab) == ["train", "train", None, "validation"]           # embargoed day has no split
    keep = S.purge(d, horizon_days=21)
    assert list(keep) == [True, False, False, True]                        # label window would cross into validation
    monkeypatch.setattr(S, "OVERRIDE", {**cfg, "validation": ["2019-06-01", "2020-12-31"]})
    with pytest.raises(ValueError):
        S.periods()


def test_engine_iterate_matches_run(flat_prices):
    from ddb.sim.engine import Backtester

    class Buy:
        def decide(self, view, pf):
            return {"AAA": 0.5} if view.date == view.history().index[0] or len(view.history()) == 3 else None
    a = Backtester(flat_prices, Buy()).run()
    bt = Backtester(flat_prices, Buy())
    gen = bt.iterate()
    view, pf = next(gen)
    try:
        while True:
            view, pf = gen.send(Buy().decide(view, pf))
    except StopIteration as stop:
        b = stop.value
    pd.testing.assert_series_equal(a.equity, b.equity)
    assert len(a.trades) == len(b.trades) > 0


def test_env_mechanics(synth):
    from ddb.rl.env import AllocatorEnv
    env = AllocatorEnv(split="train", episode_weeks=8, seed=1)
    obs, info = env.reset()
    assert obs.shape == (env.obs_dim,) and np.isfinite(obs).all()
    a = np.zeros(env.n_assets)
    a[env.assets.index("tbills")] = 0.5
    a[0] = 2.0                                   # sum > 1 -> scaled down; no leverage
    t = env.targets(a, env._d)
    assert sum(t.values()) <= 1 + 1e-9
    eq0 = env._eq
    obs, r, done, trunc, info = env.step(a)
    assert np.isfinite(r) and info["turnover"] > 0
    # holding (None) between steps: reward is the log return minus any drawdown deepening
    eq1 = env._eq
    peak = env._peak
    obs, r2, done, _, info = env.step(None)
    expected = math.log(env._eq / eq1) - 0.5 * max(0.0, (eq1 / peak - 1) - (env._eq / env._peak - 1))
    assert r2 == pytest.approx(expected, abs=1e-9) and info["turnover"] == 0
    steps = 2
    while not done:
        obs, r, done, _, info = env.step(None)
        steps += 1
    assert steps <= 8 and env.equity_curve().iloc[0] == pytest.approx(eq0)
    with pytest.raises(PermissionError):
        AllocatorEnv(split="test")


def test_baselines_and_tax_at_end(synth):
    from ddb.rl import baselines
    r_tb = baselines.evaluate(baselines.tbills_only, "validation")
    r_eq = baselines.evaluate(baselines.equal_industries, "validation")
    assert r_tb["steps"] > 20 and abs(r_tb["max_drawdown"]) < 0.02          # T-bills barely move
    assert r_eq["trades"] > r_tb["trades"] and r_eq["taxes_paid"] >= 0
    for name, pol in baselines.BASELINES.items():
        out = baselines.evaluate(pol, "validation")
        assert np.isfinite(out["total_reward"]), name


def test_readiness_flags_problems(synth):
    from ddb.db.schema import connect
    from ddb.rl import readiness
    root, db = synth
    r = readiness.run(db_path=db)
    names = {c["check"]: c for c in r["checks"]}
    assert not r["ready"]                                      # synthetic data is small and old
    assert not names["price coverage"]["ok"] and not names["core data current"]["ok"]
    assert names["no-hindsight timestamps"]["ok"] and names["clean prices"]["ok"]
    assert all(c["fix"] for c in r["checks"] if c["blocker"] and not c["ok"])
    # inject a hindsight row and a bad tick: both must be caught
    con = connect(db)
    con.execute("""INSERT INTO filings (cik, accession, form, filing_date, knowable_at)
                   VALUES (1001, 'bad', '10-Q', DATE '2019-05-01', TIMESTAMPTZ '2019-04-01 00:00:00+00')""")
    con.close()
    r2 = readiness.run(db_path=db)
    pit = next(c for c in r2["checks"] if c["check"] == "no-hindsight timestamps")
    assert not pit["ok"] and "filings public before their filing date: 1" in pit["detail"]
    con = connect(db)
    con.execute("DELETE FROM filings WHERE accession = 'bad'")
    con.close()
    assert (root / "db" / "rl" / "readiness.md").read_text().startswith("# Data readiness: NOT READY")
