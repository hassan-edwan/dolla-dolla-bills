"""Model-ready store, event index and the fast environment."""
import time

import numpy as np
import pandas as pd
import pytest


def test_store_matches_panel_and_splits(synth):
    from ddb.store import Store
    root, _ = synth
    st = Store(root / "db" / "store")
    m, d = st.month, st.day
    T, N, F = m.X.shape
    assert N == len(st.ids) and m.y.shape == (T, N, 2) and d.X.shape[1] == N      # one company list everywhere
    p = pd.read_parquet(root / "db" / "signals" / "panel.parquet")
    r = p.dropna(subset=["mom_12_1"]).iloc[123]
    t = int(np.where(m.dates == pd.Timestamp(r["d"]))[0][0])
    j = m.features.index("mom_12_1")
    assert m.X[t, st.column(r["cik"]), j] == pytest.approx(r["mom_12_1"], rel=1e-5)
    assert m.liquid.sum() > 0 and m.tradable.sum() > 0
    R = np.asarray(m.R)
    assert np.nanmin(R) >= -0.5 and np.nanmax(R) <= 0.5
    idx = st.split_index("month", "train", horizon_days=31)
    a, b = pd.Timestamp("2017-01-01"), pd.Timestamp("2018-06-30")
    assert (m.dates[idx] >= a).all() and (m.dates[idx] + pd.Timedelta(days=31) <= b).all()   # purged at the end
    Xn = st.normalize("month", m.X[idx])
    assert np.nanmax(np.abs(Xn)) <= 5
    with pytest.raises(PermissionError):
        st.split_index("month", "test")


def test_event_index_is_point_in_time(synth):
    from ddb.db.schema import connect
    from ddb.store import Store
    root, db = synth
    st = Store(root / "db" / "store")
    ev = st.events
    cik = int(st.ids[0])
    t = pd.Timestamp("2018-06-01")
    ty, va, ti = ev.before(cik, t)
    assert len(ty) > 0 and (ti <= np.datetime64(t)).all()
    con = connect(db, read_only=True)
    n_db = con.execute(f"""SELECT count(*) FROM events WHERE cik = {cik} AND knowable_at <= TIMESTAMPTZ '{t.isoformat()}+00:00'""").fetchone()[0]
    con.close()
    names = [ev.vocab[x] for x in ty]
    assert sum(x.startswith("filing:") for x in names) == n_db
    ty3, _, ti3 = ev.before(cik, t, k=3)
    assert len(ty3) == min(3, len(ty)) and (ti3 == ti[-len(ty3):]).all()
    b = ev.batch_before([cik, 999999], t, k=8)
    assert b["types"].shape == (2, 8) and not b["mask"][1].any() and (b["age_days"][0][b["mask"][0]] >= 0).all()


def test_fast_env_matches_full_env(synth):
    from ddb.rl import baselines
    from ddb.rl.env import AllocatorEnv
    from ddb.rl.fast import FastAllocatorEnv
    root, _ = synth
    full = baselines.evaluate(baselines.equal_industries, "validation",
                              env=AllocatorEnv(split="validation", episode_weeks=None, data_dir=root / "db" / "rl"))
    fe = FastAllocatorEnv(split="validation", n_envs=1, episode_weeks=None, root=root / "db" / "rl" / "fast")
    obs, _ = fe.reset()
    assert obs.shape == (1, fe.obs_dim)
    eq = np.ones(fe.n_assets)
    eq[[fe.assets.index(a) for a in ("gold", "tbills")]] = 0
    eq = eq / eq.sum()
    done = np.zeros(1, bool)
    while not done.all():
        obs, r, done, _, info = fe.step(eq[None, :])
    fast_ret = info["equity"][0] / 10_000 - 1
    assert fast_ret == pytest.approx(full["total_return"], abs=0.05)      # same strategy, within 5 points


def test_fast_env_costs_taxes_and_speed(synth):
    from ddb.rl.fast import FastAllocatorEnv
    root, _ = synth
    fe = FastAllocatorEnv(split="train", n_envs=128, seed=0, root=root / "db" / "rl" / "fast")
    fe.reset()
    hold = np.full((128, fe.n_assets), np.nan)
    _, r, _, _, info = fe.step(hold)
    assert (info["cost"] == 0).all() and np.allclose(r, 0)                  # holding cash: nothing happens
    a = np.zeros((128, fe.n_assets))
    a[:, 0] = 1.0
    _, _, _, _, info = fe.step(a)
    assert (info["cost"] > 0).all() and (info["turnover"] == 1).all()
    fe2 = FastAllocatorEnv(split="train", n_envs=256, seed=1, root=root / "db" / "rl" / "fast")
    fe2.reset()
    t0, n, done = time.time(), 0, np.zeros(256, bool)
    taxes = 0.0
    while not done.all():
        _, _, done, _, info = fe2.step(fe2.rng.dirichlet(np.ones(fe2.n_assets), 256))
        n += 256
        taxes += info["tax"].sum()
    assert n / (time.time() - t0) > 2_000 and taxes > 0
