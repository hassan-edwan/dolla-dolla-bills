"""Baseline allocation policies and a common evaluation. A learned policy has to
beat these on the validation period, after costs and taxes, before it means anything.

A policy is any callable (obs_vector, env) -> action (weights per env.assets) or
None (keep holdings). Baselines read raw features through env.feature().

    python -m ddb.rl.baselines [--split validation]
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from ..metrics import summary
from .env import AllocatorEnv


def _w(env, **parts) -> np.ndarray:
    a = np.zeros(env.n_assets)
    for k, v in parts.items():
        if k in env.assets:
            a[env.assets.index(k)] = v
    return a


def feature(env, name: str):
    x = env.obs.loc[:env._d, name].dropna()
    return float(x.iloc[-1]) if len(x) else None


def equal_industries(obs, env):
    """Equal weight in every industry sleeve, rebalanced weekly."""
    return _w(env, **{i: 1 / len(env.industries) for i in env.industries})


def buy_and_hold(obs, env):
    """Equal industry sleeves once, then never trade (sleeves drift, names don't refresh)."""
    return equal_industries(obs, env) if env.equity_curve().size <= 1 else None


def tbills_only(obs, env):
    return _w(env, tbills=1.0)


def trend_filter(obs, env):
    """Industries when the market is above its 200-day average, T-bills otherwise."""
    t = feature(env, "mkt__mkt_trend")
    return tbills_only(obs, env) if t is not None and t < 0 else equal_industries(obs, env)


def regime_rule(obs, env):
    """Calm: all industries. Caution: half industries, half haven. Stress: haven only."""
    p = feature(env, "mkt__points") or 0
    eq = equal_industries(obs, env)
    if p >= 3:
        return _w(env, tbills=0.7, gold=0.3)
    if p >= 2:
        return eq * 0.5 + _w(env, tbills=0.35, gold=0.15)
    return eq


def industry_momentum(obs, env, top: int = 2):
    """The `top` industries with the best 12-week return, equal weight."""
    r = {i: feature(env, f"{i}__ret_12w") for i in env.industries}
    best = sorted((v, i) for i, v in r.items() if v is not None)[-top:]
    return _w(env, **{i: 1 / max(len(best), 1) for _, i in best}) if best else tbills_only(obs, env)


BASELINES = {"equal_industries": equal_industries, "buy_and_hold": buy_and_hold, "tbills_only": tbills_only,
             "trend_filter": trend_filter, "regime_rule": regime_rule, "industry_momentum": industry_momentum}


def evaluate(policy, split: str = "validation", allow_test: bool = False, env: AllocatorEnv | None = None) -> dict:
    """Run the policy over the whole split; metrics after costs and taxes."""
    env = env or AllocatorEnv(split=split, episode_weeks=None, allow_test=allow_test)
    obs, info = env.reset()
    total, turnover, steps, done = 0.0, 0.0, 0, False
    while not done:
        obs, r, done, _, info = env.step(policy(obs, env))
        total += r
        turnover += info["turnover"]
        steps += 1
    eq = env.equity_curve()
    s = summary(eq) if len(eq) > 2 else {}
    res = getattr(env, "result", None)
    out = {"split": split, "steps": steps, "total_reward": total, "turnover_per_step": turnover / max(steps, 1),
           "final_equity": float(eq.iloc[-1]), **{k: (float(v) if isinstance(v, (int, float, np.floating)) else str(v))
                                                  for k, v in s.items()}}
    if res is not None:
        out["taxes_paid"] = float(res.taxes_paid.sum()) + getattr(env, "tax_due_end", 0.0)
        out["trades"] = int(len(res.trades))
    return out


def run_all(split: str = "validation") -> pd.DataFrame:
    rows = []
    for name, pol in BASELINES.items():
        r = evaluate(pol, split)
        rows.append({"policy": name, **r})
    return pd.DataFrame(rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="validation", choices=["train", "validation"])
    df = run_all(ap.parse_args().split)
    cols = ["policy", "total_return", "cagr", "ann_vol", "max_drawdown", "total_reward", "turnover_per_step", "taxes_paid"]
    print(df[[c for c in cols if c in df]].to_string(index=False))
