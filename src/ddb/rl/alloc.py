"""Allocator training: walk-forward folds, batched rollouts, and the policies to beat.

Objective: after-tax growth. A policy is scored by the log of its final equity after
costs and taxes (tax still owed at the end of a window is charged), on the fast
environment (ddb.rl.fast). Final candidates are re-checked in the full backtester.

Folds (inside the training period only; validation and test stay closed):
  fit on 2016 .. Y-1, evaluate on calendar year Y, for Y = 2019, 2020, 2021.

Policies, in the order they have to beat each other:
  equal_industries   equal weight across the industry sleeves that have names, weekly
  vol_scaled         weight ~ vol^-a across sleeves, trend-based cash share, no-trade band
  predict_optimize   pooled ridge forecast of each asset's next 4 weeks, then a
                     cost-aware long-only mean-variance step, no-trade band
  scorer (ES)        one small linear scorer shared by every sleeve (same weights for
                     each industry, so 9x the examples and no memorizing which industry
                     won), softmax over sleeves + gold + T-bills + cash, no-trade band;
                     trained with evolution strategies on after-tax log growth

Every policy is vectorized: params [B, D] -> weights for B parallel episodes, so a
whole grid or ES population runs in one batch.

    python -m ddb.rl.alloc folds          # every policy on the 3 folds
    python -m ddb.rl.alloc validate       # the finalists on validation (fast + full env)
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..config import DATA_DIR
from .fast import FastAllocatorEnv

OUT = DATA_DIR / "db" / "rl" / "alloc"
FOLD_YEARS = (2019, 2020, 2021)
SLEEVE_FEATS = ["ret_4w", "ret_12w", "ret_26w", "vol_12w", "trend", "breadth", "n_candidates", "cand_score", "median_score"]
HAVEN_SLOTS = {"ret_4w": 0, "ret_12w": 1, "trend": 4}
TYPES = ("industry", "gold", "tbills")


# ------------------------------------------------------------------ environment helpers
def make_env(split: str, n_envs: int, lo=None, hi=None, weeks: int | None = None, allow_test: bool = False) -> FastAllocatorEnv:
    """Fast env restricted to decision dates in [lo, hi] (inside the split)."""
    env = FastAllocatorEnv(split=split, n_envs=n_envs, episode_weeks=None, allow_test=allow_test)
    keep = np.ones(len(env.idx), bool)
    if lo is not None:
        keep &= env.dates[env.idx] >= pd.Timestamp(lo)
    if hi is not None:
        keep &= env.dates[env.idx] <= pd.Timestamp(hi)
    env.idx = env.idx[keep]
    env.weeks = len(env.idx) if not weeks or weeks >= len(env.idx) else weeks
    return env


@dataclass
class Layout:
    """Index maps from the observation vector to per-asset tokens."""
    assets: list
    features: list
    n_feat: int
    tok_idx: np.ndarray = field(init=False)      # [A, 9] feature index or -1
    mkt_idx: np.ndarray = field(init=False)
    types: np.ndarray = field(init=False)        # [A] 0 industry, 1 gold, 2 tbills

    def __post_init__(self):
        f = {n: i for i, n in enumerate(self.features)}
        A = len(self.assets)
        self.tok_idx = np.full((A, len(SLEEVE_FEATS)), -1)
        self.types = np.zeros(A, int)
        for a, name in enumerate(self.assets):
            if name in ("gold", "tbills"):
                self.types[a] = TYPES.index(name)
                for k, s in HAVEN_SLOTS.items():
                    self.tok_idx[a, s] = f.get(f"{name}__{k}", -1)
            else:
                for s, k in enumerate(SLEEVE_FEATS):
                    self.tok_idx[a, s] = f.get(f"{name}__{k}", -1)
        self.mkt_idx = np.array([i for n, i in f.items() if n.startswith("mkt__") or n == "tbill_yield"])

    def split_obs(self, obs: np.ndarray):
        """obs [B, obs_dim] -> tokens [B, A, 9], missing [B, A, 9], market [B, M], weights [B, A], cash [B]."""
        F, A = self.n_feat, len(self.assets)
        Z, MISS = obs[:, :F], obs[:, F:2 * F]
        w, cash = obs[:, 2 * F:2 * F + A], obs[:, 2 * F + A]
        idx = np.where(self.tok_idx >= 0, self.tok_idx, 0)
        tok = np.where(self.tok_idx >= 0, Z[:, idx], 0.0)
        miss = np.where(self.tok_idx >= 0, MISS[:, idx], 1.0)
        tok = np.where(miss > 0, 0.0, tok)
        return tok, miss, Z[:, self.mkt_idx], w, cash


def layout(env: FastAllocatorEnv) -> Layout:
    meta = json.loads((DATA_DIR / "db" / "rl" / "meta.json").read_text())
    return Layout(env.assets, meta["features"], env.Z.shape[1])


def rollout(env: FastAllocatorEnv, policy, params: np.ndarray, starts: np.ndarray | None = None,
            band: np.ndarray | float = 0.0, record: bool = False, state: dict | None = None) -> dict:
    """Run B = len(params) episodes in lockstep; policy(obs, params, env, state) -> target
    weights [B, A] (rest is cash). A trade happens only if it moves more than `band`
    of the portfolio (half the L1 change). Returns after-tax log growth per episode."""
    B = len(params)
    env.B = B
    obs, _ = env.reset(options={"start_index": starts} if starts is not None else None)
    E0 = env.E.copy()
    band = np.broadcast_to(np.asarray(band, float), (B,))
    state = dict(state or {})
    done = np.zeros(B, bool)
    tax = cost = turn = 0.0
    W = []
    while not done.all():
        tw = policy(obs, params, env, state)
        cur = obs[:, 2 * env.Z.shape[1]:2 * env.Z.shape[1] + env.n_assets]
        move = 0.5 * (np.abs(tw - cur).sum(1) + np.abs(tw.sum(1) - cur.sum(1)))
        act = np.where((move < band)[:, None] & (env.step_n > 0), np.nan, tw)
        if record:
            W.append(np.where(np.isnan(act), cur, act))
        obs, _, done, _, info = env.step(act)
        tax, cost, turn = tax + info["tax"], cost + info["cost"], turn + info["turnover"]
    out = {"log_growth": np.log(env.E / E0), "tax": tax / E0, "cost": cost / E0, "turnover": turn / env.step_n,
           "weeks": env.step_n}
    if record:
        out["weights"] = np.stack(W, 1)
    return out


# ------------------------------------------------------------------ policies
def p_equal(obs, params, env, state):
    L = state.setdefault("L", layout(env))
    ind = (L.types == 0) & (env.AVAIL[env.t] > 0)                       # sleeves that have names this week
    ind = ind.astype(float)
    return ind / np.maximum(ind.sum(1, keepdims=True), 1)


def p_vol_scaled(obs, params, env, state):
    """params [B, 3]: a (vol exponent), c (cash share when the market trend is down), k (trend tilt)."""
    L = state.setdefault("L", layout(env))
    tok, miss, mkt, w, cash = L.split_obs(obs)
    a, c, k = params[:, 0:1], params[:, 1:2], params[:, 2:3]
    vol_z = tok[:, :, 3]
    trend = tok[:, :, 4]
    ind = L.types == 0
    s = np.where(ind, -a * vol_z + k * trend, -np.inf)                  # vol_z is standardized: exp(-a z) ~ vol^-a
    s = s - s.max(1, keepdims=True)
    wi = np.exp(s) * ind
    wi = wi / wi.sum(1, keepdims=True)
    mtrend = mkt[:, list(L.mkt_idx).index(L.features.index("mkt__mkt_trend"))]
    down = (mtrend < 0)[:, None]
    tb = np.zeros_like(wi)
    tb[:, L.assets.index("tbills")] = 1.0
    return np.where(down, (1 - c) * wi + c * tb, wi)


def scorer_dim(L: Layout) -> int:
    M = len(L.mkt_idx)
    return len(SLEEVE_FEATS) + 1 + len(TYPES) * (M + 1) + (M + 1)


def p_scorer(obs, params, env, state):
    """Shared linear scorer. params [B, D]:
    th_tok [9] + th_w [1]                (same for every asset: features of that asset)
    th_mkt[type] [M] + bias[type] for 3 types (market conditions shift a type's appeal)
    th_cash [M] + bias_cash               (cash's score)
    softmax over available assets + cash."""
    L = state.setdefault("L", layout(env))
    tok, miss, mkt, w, cash = L.split_obs(obs)
    B, A, K = tok.shape
    M = mkt.shape[1]
    p = params
    th_tok, th_w = p[:, :K], p[:, K]
    o = K + 1
    th_type = p[:, o:o + len(TYPES) * (M + 1)].reshape(B, len(TYPES), M + 1)
    o += len(TYPES) * (M + 1)
    th_cash = p[:, o:o + M + 1]
    s = np.einsum("bak,bk->ba", tok, th_tok) + w * th_w[:, None]
    ty = th_type[:, L.types, :]                                           # [B, A, M+1]
    s = s + np.einsum("bam,bm->ba", ty[:, :, :M], mkt) + ty[:, :, M]
    sc = (th_cash[:, :M] * mkt).sum(1) + th_cash[:, M]
    avail = env.AVAIL[env.t] > 0                                           # [B, A]
    s = np.where(avail, s, -np.inf)
    allx = np.concatenate([s, sc[:, None]], 1)
    allx = allx - allx.max(1, keepdims=True)
    e = np.exp(allx)
    e = e / e.sum(1, keepdims=True)
    return e[:, :A]


def scorer_init(L: Layout) -> np.ndarray:
    """Start at equal weight across industries: industry bias high, havens and cash low."""
    p = np.zeros(scorer_dim(L))
    M = len(L.mkt_idx)
    o = len(SLEEVE_FEATS) + 1
    p[o + 0 * (M + 1) + M] = 0.0           # industry bias
    p[o + 1 * (M + 1) + M] = -3.0          # gold
    p[o + 2 * (M + 1) + M] = -3.0          # tbills
    p[o + 3 * (M + 1) + M] = -3.0          # cash
    return p


def tilt_dim(L: Layout) -> int:
    M = len(L.mkt_idx)
    return len(SLEEVE_FEATS) + 1 + 2 * (M + 1)


def tilt_init(L: Layout) -> np.ndarray:
    p = np.zeros(tilt_dim(L))
    M = len(L.mkt_idx)
    p[len(SLEEVE_FEATS) + 1 + M] = -4.0                       # risk-off share starts at ~0
    return p


def p_tilt(obs, params, env, state, kappa: float = 1.0, max_off: float = 0.5):
    """Bounded tilt around equal weight (the benchmark), params [B, D]:
      industry a:  EW_a * exp(kappa * tanh(th_tok . tok_a + th_w * w_a)), renormalized
                   (so no sleeve can exceed ~e^2 times another: built-in diversification)
      risk-off:    h = max_off * sigmoid(th_h . mkt + b_h) moved to havens,
                   split gold / T-bills by sigmoid(th_g . mkt + b_g)
    Same scorer for every industry; zero parameters except b_h = -4 is equal weight."""
    L = state.setdefault("L", layout(env))
    tok, miss, mkt, w, cash = L.split_obs(obs)
    B, A, K = tok.shape
    M = mkt.shape[1]
    th_tok, th_w = params[:, :K], params[:, K]
    o = K + 1
    th_h, b_h = params[:, o:o + M], params[:, o + M]
    o += M + 1
    th_g, b_g = params[:, o:o + M], params[:, o + M]
    ind = (L.types == 0)[None, :] & (env.AVAIL[env.t] > 0)
    s = kappa * np.tanh(np.einsum("bak,bk->ba", tok, th_tok) + w * th_w[:, None])
    wi = np.where(ind, np.exp(s), 0.0)
    wi = wi / np.maximum(wi.sum(1, keepdims=True), 1e-12)
    sig = lambda x: 1 / (1 + np.exp(-x))   # noqa: E731
    h = max_off * sig((th_h * mkt).sum(1) + b_h)
    g = sig((th_g * mkt).sum(1) + b_g)
    out = wi * (1 - h)[:, None]
    out[:, L.assets.index("gold")] += h * g
    out[:, L.assets.index("tbills")] += h * (1 - g)
    return out


# ------------------------------------------------------------------ predict, then optimize
def fit_forecaster(env: FastAllocatorEnv, lo, hi, horizon: int = 4, ridge: float = 10.0) -> dict:
    """Pooled ridge: next `horizon` weeks of log return in excess of T-bills, per asset,
    from that asset's token + market features + type dummies. Fit on decision dates in
    [lo, hi - horizon weeks] (purged so no label reaches past hi)."""
    L = layout(env)
    d = env.dates
    ok = np.where((d >= pd.Timestamp(lo)) & (d <= pd.Timestamp(hi) - pd.Timedelta(weeks=horizon)))[0]
    ok = ok[ok + horizon <= len(env.R)]
    lr = np.log1p(env.R)
    tb = L.assets.index("tbills")
    X, y = [], []
    for t in ok:
        obs = np.concatenate([env.Z[t], env.MISS[t], np.zeros(env.n_assets + 2)])[None].astype(np.float32)
        tok, miss, mkt, _, _ = L.split_obs(obs)
        fut = lr[t:t + horizon].sum(0)
        for a in range(env.n_assets):
            if a == tb or env.AVAIL[t, a] == 0:
                continue
            X.append(_design(tok[0, a:a + 1], mkt[0], L.types[a:a + 1])[0])
            y.append(fut[a] - fut[tb])
    X, y = np.asarray(X), np.asarray(y)
    mu_x, sd_x = X.mean(0), X.std(0) + 1e-9
    Xs = (X - mu_x) / sd_x
    beta = np.linalg.solve(Xs.T @ Xs + ridge * np.eye(Xs.shape[1]), Xs.T @ (y - y.mean()))
    return {"beta": beta, "mu_x": mu_x, "sd_x": sd_x, "y0": y.mean(), "horizon": horizon, "n": len(y)}


def _design(tok, mkt, typ):
    """tok [..., A, 9], mkt [..., M], typ [A] -> [..., A, 9 + M + 3]."""
    tok = np.asarray(tok)
    oh = np.eye(len(TYPES))[np.asarray(typ)]
    shp = tok.shape[:-1]
    return np.concatenate([tok, np.broadcast_to(np.asarray(mkt)[..., None, :], shp + (np.shape(mkt)[-1],)),
                           np.broadcast_to(oh, shp + (len(TYPES),))], -1)


def p_predict_optimize(obs, params, env, state):
    """params [B, 2]: risk aversion gamma, forecast shrink s. Weekly: mu = s * forecast / horizon,
    Sigma from the trailing 52 weeks; long-only, sum <= 1 (rest cash); a few projected
    gradient steps from the current weights (so it doesn't trade for nothing)."""
    L = state.setdefault("L", layout(env))
    fc = state["fc"]
    tok, miss, mkt, w, cash = L.split_obs(obs)
    B, A = w.shape
    X = _design(tok, mkt, L.types)                                                  # [B, A, D]
    mu = ((X - fc["mu_x"]) / fc["sd_x"]) @ fc["beta"] + fc["y0"]                  # [B, A] excess, horizon
    mu = mu / fc["horizon"]
    tb = L.assets.index("tbills")
    mu[:, tb] = 0.0
    t = env.t
    lr = np.log1p(env.R)
    key = int(t[0]) if (t == t[0]).all() else None
    if key is not None and state.get("S_key") == key:
        S = state["S"]
    else:
        S = np.stack([np.cov(lr[max(ti - 52, 0):ti].T) if ti > 10 else np.eye(A) * 1e-3 for ti in t])   # past weeks only
        if key is not None:
            state["S_key"], state["S"] = key, S
    gamma, shrink = params[:, 0:1], params[:, 1:2]
    mu = mu * shrink
    avail = env.AVAIL[t] > 0
    x = np.where(avail, w, 0.0)
    for _ in range(50):
        g = mu - gamma * np.einsum("bij,bj->bi", S, x)
        x = _project(np.where(avail, x + 0.5 * g, 0.0))
    return x


def _project(x):
    """Each row onto {x >= 0, sum x <= 1}."""
    x = np.clip(x, 0, None)
    s = x.sum(1)
    over = s > 1
    if over.any():
        v = x[over]
        u = -np.sort(-v, 1)
        css = np.cumsum(u, 1) - 1
        k = np.arange(1, v.shape[1] + 1)
        r = (u - css / k > 0).sum(1)
        th = css[np.arange(len(v)), r - 1] / r
        x[over] = np.clip(v - th[:, None], 0, None)
    return x


# ------------------------------------------------------------------ evolution strategies
def train_es(lo, hi, iters: int = 150, pop: int = 48, windows: int = 24, weeks: int = 52, sigma: float = 0.1,
             lr: float = 0.03, decay: float = 0.005, band: float = 0.05, seed: int = 0, log=None,
             policy=None, init=None) -> np.ndarray:
    """OpenAI-style ES on after-tax log growth over random `weeks`-long windows in [lo, hi].
    Antithetic pairs, rank-shaped fitness, the same windows for the whole population each
    iteration (common random numbers), weight decay toward the starting point."""
    rng = np.random.default_rng(seed)
    env = make_env("train", 1, lo, hi, weeks=weeks)
    L = layout(env)
    policy = policy or p_scorer
    theta0 = (init or scorer_init)(L)
    theta = theta0.copy()
    D = len(theta)
    m, v = np.zeros(D), np.zeros(D)
    n_start = len(env.idx) - env.weeks + 1
    for it in range(iters):
        eps = rng.standard_normal((pop // 2, D))
        eps = np.concatenate([eps, -eps])
        P = theta + sigma * eps                                          # [pop, D]
        st = rng.integers(0, n_start, windows)
        params = np.repeat(P, windows, 0)
        starts = np.tile(st, pop)
        r = rollout(env, policy, params, starts, band)["log_growth"].reshape(pop, windows).mean(1)
        rk = np.empty(pop)
        rk[np.argsort(r)] = np.arange(pop)
        f = rk / (pop - 1) - 0.5
        g = (f[:, None] * eps).sum(0) / (pop * sigma) - decay * (theta - theta0)
        m = 0.9 * m + 0.1 * g                                            # Adam ascent
        v = 0.999 * v + 0.001 * g * g
        theta = theta + lr * (m / (1 - 0.9 ** (it + 1))) / (np.sqrt(v / (1 - 0.999 ** (it + 1))) + 1e-8)
        if log and (it % 25 == 0 or it == iters - 1):
            log(f"    it {it:4d}  mean window log-growth {r.mean():+.4f}  best {r.max():+.4f}")
    return theta


# ------------------------------------------------------------------ evaluation
def eval_window(policy, params: np.ndarray, split: str, lo, hi, band=0.0, state_init=None, allow_test=False) -> dict:
    """One episode per row of params over the whole window [lo, hi]."""
    env = make_env(split, len(params), lo, hi, allow_test=allow_test)
    r = rollout(env, policy, params, np.zeros(len(params), int), band, state=state_init)
    first, last = env.dates[env.idx[0]], env.dates[env.idx[-1]]
    yrs = max((last - first).days / 365.25, 1e-9)
    r["cagr"] = np.exp(r["log_growth"] / yrs) - 1
    return r


class _Shim:
    """What a vectorized policy reads from the fast env, for one full-env decision date."""
    def __init__(self, fast: FastAllocatorEnv, d):
        self.Z, self.R, self.AVAIL, self.assets, self.n_assets = fast.Z, fast.R, fast.AVAIL, fast.assets, fast.n_assets
        self.t = np.array([min(int(np.searchsorted(fast.dates, d, side="right")) - 1, len(fast.R) - 1)])


def eval_full(policy, params: np.ndarray, split: str, lo=None, hi=None, band: float = 0.0, state_init=None,
              allow_test: bool = False) -> dict:
    """The same policy in the full backtester (share-level lots, wash sales, measured
    spreads, impact, T+1). One parameter vector."""
    from ..metrics import summary
    from .env import AllocatorEnv
    fast = FastAllocatorEnv(split=split, n_envs=1, episode_weeks=None, allow_test=allow_test)
    env = AllocatorEnv(split=split, episode_weeks=None, allow_test=allow_test)
    if lo is not None or hi is not None:
        keep = np.ones(len(env.dates), bool)
        if lo is not None:
            keep &= env.dates >= pd.Timestamp(lo)
        if hi is not None:
            keep &= env.dates <= pd.Timestamp(hi)
        env.dates = env.dates[keep]
    state = dict(state_init or {})
    obs, info = env.reset()
    first = True
    done = False
    F = fast.Z.shape[1]
    while not done:
        sh = _Shim(fast, env._d)
        tw = policy(obs[None], np.asarray(params)[None], sh, state)[0]
        cur = obs[2 * F:2 * F + fast.n_assets]
        move = 0.5 * (np.abs(tw - cur).sum() + abs(tw.sum() - cur.sum()))
        # inside the band: keep the sleeve weights (no trade between assets), but each
        # sleeve still refreshes its names, exactly as the fast env does; None would also
        # freeze the names (buy-and-hold), which is a different policy
        act = cur.copy() if (not first and move < band) else tw
        first = False
        obs, _, done, _, info = env.step(act)
    eq = env.equity_curve()
    res = getattr(env, "result", None)
    out = {k: float(v) for k, v in summary(eq).items() if isinstance(v, (int, float, np.floating))}
    out["log_growth"] = float(np.log(eq.iloc[-1] / eq.iloc[0]))
    if res is not None:
        out["taxes_paid"] = (float(res.taxes_paid.sum()) + getattr(env, "tax_due_end", 0.0)) / float(eq.iloc[0])
        out["trades"] = int(len(res.trades))
    return out


def folds() -> list[tuple[str, str, str, str]]:
    return [("2016-01-01", f"{y - 1}-12-31", f"{y}-01-01", f"{y}-12-31") for y in FOLD_YEARS]


VOL_GRID = np.array([[a, c, k] for a in (0.0, 0.25, 0.5, 1.0) for c in (0.0, 0.5, 1.0) for k in (0.0, 0.25, 0.5)])
PO_GRID = np.array([[g, s] for g in (1.0, 3.0, 10.0, 30.0) for s in (0.0, 0.5, 1.0)])
BANDS = (0.0, 0.05, 0.10)
EW_BANDS = (0.10, 0.20)


def run_folds(es_iters: int = 150, seeds=(0, 1, 2), log=print) -> pd.DataFrame:
    """Every policy on every fold. Tuned policies pick their parameters on the fold's own
    fitting years (mean of 52-week windows), then are scored once on the fold year."""
    rows = []
    for (flo, fhi, elo, ehi) in folds():
        year = elo[:4]
        log(f"fold {year}: fit {flo[:4]}-{fhi[:4]}")
        # equal
        r = eval_window(p_equal, np.zeros((1, 1)), "train", elo, ehi)
        rows.append({"fold": year, "policy": "equal_industries", "cagr": r["cagr"][0], "log_growth": r["log_growth"][0],
                     "tax": r["tax"][0], "cost": r["cost"][0], "turnover": r["turnover"][0]})
        # vol-scaled: tune on fit years with 52-week windows
        best = _tune(p_vol_scaled, VOL_GRID, flo, fhi)
        r = eval_window(p_vol_scaled, best["params"][None], "train", elo, ehi, best["band"])
        rows.append({"fold": year, "policy": "vol_scaled", "cagr": r["cagr"][0], "log_growth": r["log_growth"][0],
                     "tax": r["tax"][0], "cost": r["cost"][0], "turnover": r["turnover"][0], "chosen": best})
        # predict, then optimize
        env = make_env("train", 1)
        fc = fit_forecaster(env, flo, fhi)
        best = _tune(p_predict_optimize, PO_GRID, flo, fhi, state_init={"fc": fc}, windows=12)
        r = eval_window(p_predict_optimize, best["params"][None], "train", elo, ehi, best["band"], {"fc": fc})
        rows.append({"fold": year, "policy": "predict_optimize", "cagr": r["cagr"][0], "log_growth": r["log_growth"][0],
                     "tax": r["tax"][0], "cost": r["cost"][0], "turnover": r["turnover"][0], "chosen": best})
        # ES scorer, several seeds
        for s in seeds:
            th = train_es(flo, fhi, iters=es_iters, seed=s, log=log)
            r = eval_window(p_scorer, th[None], "train", elo, ehi, 0.05)
            rows.append({"fold": year, "policy": "es_scorer", "seed": s, "cagr": r["cagr"][0],
                         "log_growth": r["log_growth"][0], "tax": r["tax"][0], "cost": r["cost"][0],
                         "turnover": r["turnover"][0]})
            np.save(OUT / f"es_fold{year}_seed{s}.npy", th)
        log(pd.DataFrame([x for x in rows if x["fold"] == year]).drop(columns=["chosen"], errors="ignore")
            .to_string(index=False, float_format=lambda v: f"{v:+.4f}"))
    return pd.DataFrame(rows)


def _tune(policy, grid, lo, hi, state_init=None, windows: int = 32, weeks: int = 52, seed: int = 0) -> dict:
    """Best (params, band) by mean after-tax log growth over the same random windows."""
    env = make_env("train", 1, lo, hi, weeks=weeks)
    rng = np.random.default_rng(seed)
    st = rng.integers(0, len(env.idx) - env.weeks + 1, windows)
    best = None
    for band in BANDS:
        params = np.repeat(grid, windows, 0)
        r = rollout(env, policy, params, np.tile(st, len(grid)), band, state=state_init)["log_growth"].reshape(len(grid), windows).mean(1)
        i = int(np.argmax(r))
        if best is None or r[i] > best["score"]:
            best = {"params": grid[i], "band": band, "score": float(r[i])}
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["folds", "full_folds"])
    ap.add_argument("--iters", type=int, default=150)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    if a.what == "full_folds":
        df = full_folds()
        print("\nmean over folds (full backtester):\n",
              df.groupby("policy")[["log_growth", "max_dd", "tax", "trades"]].mean().to_string(float_format=lambda v: f"{v:+.4f}"))
        print(f"{time.time() - t0:.0f}s")
        return
    df = run_folds(a.iters)
    df.to_json(OUT / "folds.json", orient="records", indent=1, default_handler=str)
    summ = df.groupby("policy")[["cagr", "log_growth", "tax", "cost", "turnover"]].mean()
    print("\nmean over folds (2019, 2020, 2021):\n", summ.to_string(float_format=lambda v: f"{v:+.4f}"))
    print(f"{time.time() - t0:.0f}s")



# ------------------------------------------------------------------ variants + full-backtester fold scores
ES_VARIANTS = {
    "es_v1": dict(band=0.05, weeks=52, decay=0.005),
    "es_v2": dict(band=0.10, weeks=104, decay=0.02),
    "es_tilt": dict(band=0.05, weeks=104, decay=0.02, policy="tilt"),
    "es_tilt_b15": dict(band=0.15, weeks=104, decay=0.02, policy="tilt"),
}
POLICIES = {"scorer": (p_scorer, scorer_init), "tilt": (p_tilt, tilt_init)}


def train_variant(name: str, seeds=(0, 1, 2), iters: int = 150, log=print) -> dict:
    """Train an ES variant on every fold's fitting years; the policy for a fold is the
    average of the seeds' parameters (a linear scorer, so averaging is an ensemble of sorts)."""
    kw = dict(ES_VARIANTS[name])
    pol, init = POLICIES[kw.pop("policy", "scorer")]
    kw.update(policy=pol, init=init)
    out = {}
    for flo, fhi, elo, ehi in folds():
        ths = []
        for s in seeds:
            f = OUT / f"{name}_fold{elo[:4]}_seed{s}.npy"
            if name == "es_v1" and (OUT / f"es_fold{elo[:4]}_seed{s}.npy").exists():
                th = np.load(OUT / f"es_fold{elo[:4]}_seed{s}.npy")
            elif f.exists():
                th = np.load(f)
            else:
                log(f"  {name} fold {elo[:4]} seed {s}")
                th = train_es(flo, fhi, iters=iters, seed=s, log=log, **kw)
            np.save(f, th)
            ths.append(th)
        out[elo[:4]] = np.mean(ths, 0)
    return out


def full_folds(variants=("es_v1", "es_v2", "es_tilt", "es_tilt_b15"), log=print) -> pd.DataFrame:
    """Every policy on every fold year, scored in the full backtester."""
    rows = []
    th = {v: train_variant(v, log=log) for v in variants}
    env = make_env("train", 1)
    for flo, fhi, elo, ehi in folds():
        y = elo[:4]
        res = {"equal_industries": eval_full(p_equal, np.zeros(1), "train", elo, ehi)}
        for b in EW_BANDS:
            res[f"equal_band{int(b * 100)}"] = eval_full(p_equal, np.zeros(1), "train", elo, ehi, b)
        best = _tune(p_vol_scaled, VOL_GRID, flo, fhi)
        res["vol_scaled"] = eval_full(p_vol_scaled, best["params"], "train", elo, ehi, best["band"])
        fc = fit_forecaster(env, flo, fhi)
        best = _tune(p_predict_optimize, PO_GRID, flo, fhi, state_init={"fc": fc}, windows=12)
        res["predict_optimize"] = eval_full(p_predict_optimize, best["params"], "train", elo, ehi, best["band"], {"fc": fc})
        for v in variants:
            pol = POLICIES[ES_VARIANTS[v].get("policy", "scorer")][0]
            res[v] = eval_full(pol, th[v][y], "train", elo, ehi, ES_VARIANTS[v]["band"])
        for k, r in res.items():
            rows.append({"fold": y, "policy": k, "log_growth": r["log_growth"], "max_dd": r.get("max_drawdown"),
                         "tax": r.get("taxes_paid"), "trades": r.get("trades")})
        log(pd.DataFrame([x for x in rows if x["fold"] == y]).to_string(index=False, float_format=lambda v: f"{v:+.4f}"))
    df = pd.DataFrame(rows)
    df.to_json(OUT / "full_folds.json", orient="records", indent=1)
    return df


if __name__ == "__main__":
    main()
