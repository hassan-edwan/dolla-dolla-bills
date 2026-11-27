"""Fast, vectorized version of the allocator environment, for training.

The full environment (ddb.rl.env.AllocatorEnv) runs the real backtester share by
share: exact, but ~25 steps a second. This one precomputes, for every weekly
decision i and every asset a (industry sleeve, gold, T-bills):

  R[i, a]      return from the next open after decision i to the next open after
               decision i+1, with dividends; a name that stops trading inside the
               window is settled like the backtester does (how its listing ended)
  INC[i, a]    the dividend part of R (taxed as income)
  COST[i, a]   round-trip spread cost of the asset's names (sim.yaml tiers, entry at the open)
  CHURN[i, a]  share of the sleeve that changes when its names are refreshed at
               decision i (costs spread and realizes gains)

and steps B episodes at once with array operations: trading costs on turnover
and churn, a tax approximation (average-cost basis per asset, net realized gains
and income taxed at the short-term rate each January, losses carried forward),
the same reward and the same observation layout as the full environment.

Approximations vs the full backtester: no T+1 / good-faith constraints, no market
impact or participation cap, average cost instead of FIFO lots, no wash sales,
positions valued open-to-open. Train here; evaluate the final policy in the full
environment (ddb.rl.baselines.evaluate).

    python -m ddb.rl.fast            # build the arrays (data/db/rl/fast/) and check speed
    env = FastAllocatorEnv(split="train", n_envs=64)
    obs, info = env.reset(seed=0)                      # obs [64, obs_dim]
    obs, reward, done, truncated, info = env.step(actions)   # actions [64, n_assets]
"""
from __future__ import annotations

import json
import math
import time

import numpy as np
import pandas as pd

from ..config import load
from ..data.failures import DEFAULT_RECOVERY
from . import dataset as D
from .splits import open_split

FAST = D.OUT / "fast"


# ------------------------------------------------------------------ build
def _half_spread_bps(dv: np.ndarray, tiers) -> np.ndarray:
    tiers = sorted(([float(a), float(b)] for a, b in tiers), key=lambda t: -t[0])
    out = np.full(dv.shape, tiers[-1][1])
    for min_adv, bps in reversed(tiers):
        out = np.where(dv >= min_adv, bps, out)
    return out


def build(root=None, out=None) -> dict:
    root = root or D.OUT
    out = out or FAST
    t0 = time.time()
    meta = json.loads((root / "meta.json").read_text())
    rd = lambda n: pd.read_parquet(root / f"prices_{n}.parquet").set_index("date")   # noqa: E731
    O, C, V = rd("open"), rd("close"), rd("volume")
    for f in (O, C, V):
        f.index = pd.to_datetime(f.index)
    cal = C.index
    divs = pd.read_parquet(root / "prices_dividends.parquet").set_index("date") if (root / "prices_dividends.parquet").exists() \
        else pd.DataFrame(index=cal)
    divs.index = pd.to_datetime(divs.index)
    divs = divs.reindex(index=cal, columns=C.columns).fillna(0.0)
    obs = pd.read_parquet(root / "obs.parquet")
    obs["d"] = pd.to_datetime(obs["d"])
    obs = obs.set_index("d")[meta["features"]]
    dates = obs.index
    sl = pd.read_parquet(root / "sleeves.parquet")
    sl["month"] = pd.to_datetime(sl["month"])
    hv = pd.read_parquet(root / "haven.parquet")
    hv = hv.assign(d=pd.to_datetime(hv["d"])).set_index("d")
    ex = pd.read_parquet(root / "exits.parquet") if (root / "exits.parquet").exists() else pd.DataFrame(columns=["symbol", "event_type"])
    unk = load("sim")["delisting"].get("unknown_exit_recovery", 0.5)
    recov = {str(s): (DEFAULT_RECOVERY.get(e) if DEFAULT_RECOVERY.get(e) is not None else unk)
             for s, e in zip(ex["symbol"], ex["event_type"])}
    tiers = load("sim")["costs"]["spread_tiers"]
    open_mult = load("sim")["costs"].get("open_spread_multiplier", 1.5)

    Ov, Cv = O.to_numpy(float), C.to_numpy(float)
    Dv = divs.to_numpy(float)
    dv20 = (C * V).rolling(20, min_periods=5).mean().to_numpy(float)
    half = _half_spread_bps(np.nan_to_num(dv20), tiers) / 1e4
    rt_cost = half * open_mult + half                          # buy at the open, sell later
    ret = C.pct_change(fill_method=None)
    vol63 = (ret.rolling(63, min_periods=20).std() * math.sqrt(252)).to_numpy(float)
    last_valid = np.array([C[c].last_valid_index() or cal[0] for c in C.columns])
    col = {c: j for j, c in enumerate(C.columns)}
    assets = meta["assets"]
    inds = meta["industries"]
    W, A = len(dates), len(assets)
    R = np.zeros((W - 1, A))
    INC = np.zeros((W - 1, A))
    COST = np.zeros((W - 1, A))
    CHURN = np.zeros((W - 1, A))
    AVAIL = np.zeros((W - 1, A), bool)
    prev = {a: {} for a in assets}                            # drifted member weights after last week
    for i in range(W - 1):
        d0, d1 = dates[i], dates[i + 1]
        j0 = int(cal.searchsorted(d0, side="right"))         # fill day: next open after the decision
        j1 = int(cal.searchsorted(d1, side="right"))
        if j1 >= len(cal):
            j1 = len(cal) - 1
        jd = int(cal.searchsorted(d0, side="right")) - 1     # decision day (close)
        for a_i, a in enumerate(assets):
            if a in inds:
                s = sl[(sl["industry"] == a) & (sl["month"] <= d0)]
                s = s[s["month"] == s["month"].max()] if len(s) else s
                names = [str(x) for x in s["cik"] if str(x) in col]
                names = [n for n in names if np.isfinite(Cv[jd, col[n]])]
                if not names:
                    prev[a] = {}
                    continue
                inv = np.array([1 / max(np.nan_to_num(vol63[jd, col[n]], nan=0.5), 0.05) for n in names])
                w = dict(zip(names, inv / inv.sum()))
            else:
                sym = hv[a].asof(d0) if a in hv else None
                if not isinstance(sym, str) or sym not in col:
                    prev[a] = {}
                    continue
                w = {sym: 1.0}
            r_a = inc_a = c_a = 0.0
            drift = {}
            for n, wt in w.items():
                k = col[n]
                p0 = Ov[j0, k] if j0 < len(cal) else np.nan
                if not np.isfinite(p0):
                    p0 = Cv[jd, k]
                if not np.isfinite(p0) or p0 <= 0:
                    continue
                inc = Dv[j0 + 1:j1 + 1, k].sum() if j1 > j0 else 0.0
                if last_valid[k] < cal[j1]:                   # stopped trading inside the window
                    lv = Cv[:j1 + 1, k]
                    lc = lv[np.isfinite(lv)][-1] if np.isfinite(lv).any() else p0
                    p1 = lc * recov.get(n, unk)
                else:
                    p1 = Ov[j1, k] if np.isfinite(Ov[j1, k]) else Cv[j1, k]
                rr = (p1 + inc) / p0 - 1
                r_a += wt * rr
                inc_a += wt * inc / p0
                c_a += wt * rt_cost[jd, k]
                drift[n] = wt * (1 + rr)
            old = prev[a]
            if old:
                tot = sum(old.values()) or 1.0
                CHURN[i, a_i] = 0.5 * sum(abs(w.get(n, 0.0) - old.get(n, 0.0) / tot) for n in set(w) | set(old))
            tot = sum(drift.values()) or 1.0
            prev[a] = {n: x / tot for n, x in drift.items()}
            R[i, a_i], INC[i, a_i], COST[i, a_i], AVAIL[i, a_i] = r_a, inc_a, c_a, True
    mean = pd.Series(meta["mean"]).reindex(obs.columns).fillna(0).to_numpy()
    std = pd.Series(meta["std"]).reindex(obs.columns).replace(0, 1).fillna(1).to_numpy()
    Z = (obs.to_numpy(float) - mean) / std
    MISS = np.isnan(Z).astype(np.float32)
    Z = np.clip(np.nan_to_num(Z), -10, 10).astype(np.float32)
    out.mkdir(parents=True, exist_ok=True)
    for n, a in (("R", R), ("INC", INC), ("COST", COST), ("CHURN", CHURN), ("AVAIL", AVAIL), ("Z", Z), ("MISS", MISS)):
        np.save(out / f"{n}.npy", a.astype(np.float32) if a.dtype != bool else a)
    np.save(out / "dates.npy", dates.to_numpy().astype("datetime64[D]"))
    (out / "meta.json").write_text(json.dumps({"assets": assets, "features": list(obs.columns), "weeks": int(W),
                                               "built": pd.Timestamp.now(tz="UTC").isoformat()}))
    return {"weeks": W, "assets": A, "seconds": round(time.time() - t0)}


# ------------------------------------------------------------------ env
class FastAllocatorEnv:
    """B parallel episodes. reset() -> obs [B, obs_dim]; step(actions [B, A]) ->
    obs, reward [B], terminated [B], truncated [B], info. Episodes in a batch run in
    lockstep (same length, independent random starts). A row of NaN in actions means
    'keep the current allocation': no trade between assets, but each industry sleeve
    still refreshes its names (an asset here IS the sleeve). So the full environment's
    buy-and-hold (frozen stocks, never refreshed) has no exact counterpart here."""

    def __init__(self, split: str = "train", n_envs: int = 16, episode_weeks: int | None = -1, seed: int | None = None,
                 allow_test: bool = False, root=None, cfg: dict | None = None):
        root = root or FAST
        self.cfg = cfg or load("rl")
        acc = load("sim")["account"]
        self.st_rate = acc.get("short_term_tax_rate", 0.32) if acc.get("pay_taxes", True) else 0.0
        m = json.loads((root / "meta.json").read_text())
        self.assets = m["assets"]
        self.n_assets = A = len(self.assets)
        ld = lambda n: np.load(root / f"{n}.npy")   # noqa: E731
        self.R, self.INC, self.COST, self.CHURN, self.AVAIL = ld("R"), ld("INC"), ld("COST"), ld("CHURN"), ld("AVAIL")
        self.Z, self.MISS = ld("Z"), ld("MISS")
        self.dates = pd.DatetimeIndex(ld("dates"))
        lo, hi = open_split(split, allow_test=allow_test, who=f"FastAllocatorEnv({split})")
        self.idx = np.where((self.dates >= lo) & (self.dates <= hi))[0]
        self.idx = self.idx[self.idx < len(self.R)]            # need a next week to step into
        self.B = n_envs
        self.weeks = self.cfg["env"]["episode_weeks"] if episode_weeks == -1 else episode_weeks
        if not self.weeks or self.weeks >= len(self.idx):
            self.weeks = len(self.idx)
        self.rw = self.cfg["env"]["reward"]
        self.rng = np.random.default_rng(seed)
        self.obs_dim = 2 * self.Z.shape[1] + A + 2
        self.year = self.dates.year.to_numpy()

    def _obs(self):
        t = self.t
        w = self.V / self.E[:, None]
        cash = 1 - w.sum(1)
        dd = self.E / self.peak - 1
        return np.concatenate([self.Z[t], self.MISS[t], w, cash[:, None], dd[:, None]], axis=1).astype(np.float32)

    def reset(self, seed=None, options=None):
        if seed is not None:
            self.rng = np.random.default_rng(seed)
        B, A = self.B, self.n_assets
        n_start = len(self.idx) - self.weeks + 1
        starts = (options or {}).get("start_index")
        if starts is None:
            starts = self.rng.integers(0, max(n_start, 1), B) if self.weeks < len(self.idx) else np.zeros(B, int)
        self.t = self.idx[np.asarray(starts)]
        self.step_n = 0
        self.E = np.full(B, float(self.cfg["env"]["initial_cash"]))
        self.peak = self.E.copy()
        self.V = np.zeros((B, A))                               # value held in each asset
        self.basis = np.zeros((B, A))                           # average-cost basis of that value
        self.realized = np.zeros(B)                             # net gains + income this tax year
        self.carry = np.zeros(B)                                # loss carried forward
        self.last_w = np.zeros((B, A))
        return self._obs(), {"date": self.dates[self.t].astype(str).tolist()}

    def step(self, actions):
        B, A, t = self.B, self.n_assets, self.t
        act = np.asarray(actions, float).reshape(B, A)
        hold = np.isnan(act).all(1)
        tw = np.clip(np.nan_to_num(act), 0, None)
        s = tw.sum(1, keepdims=True)
        tw = np.where(s > 1, tw / np.maximum(s, 1e-12), tw)
        tw = tw * self.AVAIL[t]                                 # an empty sleeve can't be bought: stays cash
        cur_w = self.V / self.E[:, None]
        tw = np.where(hold[:, None], cur_w, tw)
        # trading: turnover pays half the round trip each way; churn pays a full round trip on that share
        target_v = tw * self.E[:, None]
        trade = target_v - self.V
        cost = (np.abs(trade) * self.COST[t] / 2).sum(1) + (target_v * self.CHURN[t] * self.COST[t]).sum(1)
        # realized gains: selling part of a position, or churn inside a sleeve
        sell = np.clip(-trade, 0, None)
        frac = np.divide(sell, self.V, out=np.zeros_like(sell), where=self.V > 0)
        gain = frac * (self.V - self.basis)
        self.basis = self.basis * (1 - frac)
        keep_v = self.V - sell
        churn_gain = keep_v * self.CHURN[t] * np.divide(keep_v - self.basis, keep_v, out=np.zeros_like(keep_v), where=keep_v > 0)
        self.basis = self.basis + keep_v * self.CHURN[t] * np.divide(keep_v - self.basis, keep_v, out=np.zeros_like(keep_v), where=keep_v > 0)
        buy = np.clip(trade, 0, None)
        self.basis = self.basis + buy
        self.realized += gain.sum(1) + churn_gain.sum(1)
        V = target_v.copy()
        # costs come out of cash, then cash and positions move for a week
        E0 = self.E.copy()
        cash = self.E - V.sum(1) - cost
        income = V * self.INC[t]
        self.realized += income.sum(1)                         # dividends / distributions: taxable income ...
        V = V * (1 + self.R[t])
        self.basis = self.basis + income                       # ... reinvested, so they add to the cost basis
        self.V = V
        E = cash + V.sum(1)
        # taxes: pay last year's net gains in the first week of a new year
        nxt = t + 1
        new_year = self.year[np.minimum(nxt, len(self.year) - 1)] != self.year[t]
        tax = np.zeros(B)
        if new_year.any():
            net = self.realized + self.carry
            tax = np.where(new_year, self.st_rate * np.clip(net, 0, None), 0.0)
            self.carry = np.where(new_year, np.minimum(net, 0.0), self.carry)
            self.realized = np.where(new_year, 0.0, self.realized)
        E = E - tax
        self.step_n += 1
        self.t = nxt
        done = np.full(B, self.step_n >= self.weeks or (self.t >= len(self.R)).any())
        if done.all():                                          # tax still owed at the end of the episode
            owed = self.st_rate * np.clip(self.realized + self.carry, 0, None)
            E = E - owed
            tax = tax + owed
        E = np.maximum(E, 1e-9)
        self.E = E
        dd0 = E0 / self.peak - 1
        self.peak = np.maximum(self.peak, E)
        dd1 = E / self.peak - 1
        turnover = np.abs(tw - self.last_w).sum(1)
        self.last_w = tw
        reward = np.log(E / E0) - self.rw["drawdown_penalty"] * np.clip(dd0 - dd1, 0, None) \
            - self.rw["turnover_penalty"] * turnover
        obs = self._obs() if not done.all() else np.zeros((B, self.obs_dim), np.float32)
        return obs, reward.astype(np.float32), done, np.zeros(B, bool), {"equity": E, "cost": cost, "tax": tax,
                                                                        "turnover": turnover}


if __name__ == "__main__":
    print(build())
    env = FastAllocatorEnv(split="train", n_envs=256, seed=0)
    obs, _ = env.reset()
    t0, n = time.time(), 0
    done = np.zeros(env.B, bool)
    while not done.all():
        obs, r, done, _, info = env.step(env.rng.dirichlet(np.ones(env.n_assets), env.B))
        n += env.B
    print(f"{n} steps in {time.time() - t0:.2f}s -> {n / (time.time() - t0):,.0f} steps/s")
