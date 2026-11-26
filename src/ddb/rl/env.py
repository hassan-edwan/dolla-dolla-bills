"""RL environment for the allocator: weekly weights across industry sleeves, gold,
T-bills and cash, executed by the real backtester.

- reset() picks an episode inside one split (random 1-year windows in training,
  or the whole split with episode_weeks=None) and returns the first observation.
- step(action) takes one weight per asset (meta["assets"]: industries, then
  "gold", "tbills"). Negative weights are clipped; if they sum above 1 they are
  scaled down; the rest is cash. action=None keeps the current holdings.
  The weights become per-stock targets (each sleeve's names, inverse-volatility
  weighted, from the latest month-end) that fill at the NEXT day's open, with
  spread + impact costs, T+1 settlement, the good-faith rule, wash sales and
  yearly taxes (ddb.sim.engine.Backtester).
- at the end of an episode, tax still owed on gains realized since the last
  January payment is subtracted from equity (and so from the last reward).
- reward = log(equity_t+1 / equity_t)
           - drawdown_penalty * (how much deeper the drawdown got this step)
           - turnover_penalty * sleeve-level turnover.
  Costs and taxes are already inside equity.
- observation = standardized market/industry/haven features at the decision
  date's close (train-period statistics), then the current weight of each asset,
  the cash share and the drawdown. Missing values are 0 (= the training mean)
  with a mask of which features were missing.

Works with gymnasium if installed (observation_space / action_space are set), and
without it (plain reset/step).

    from ddb.rl.env import AllocatorEnv
    env = AllocatorEnv(split="train")
    obs, info = env.reset(seed=0)
    obs, reward, terminated, truncated, info = env.step(action)
"""
from __future__ import annotations

import json
import math
import warnings

import numpy as np
import pandas as pd

from ..config import load
from ..data.prices import PriceData
from ..metrics import drawdown
from ..sim.costs import CostModel
from ..sim.engine import Backtester, SimSettings, year_tax
from . import dataset as D
from .splits import open_split

try:   # optional dependency
    import gymnasium as gym
    _Base = gym.Env
except Exception:  # noqa: BLE001
    gym = None
    _Base = object


class _Hold:
    def decide(self, view, pf):
        return None


class AllocatorEnv(_Base):
    metadata = {"render_modes": []}

    def __init__(self, split: str = "train", episode_weeks: int | None = -1, seed: int | None = None,
                 allow_test: bool = False, data_dir=None, cfg: dict | None = None):
        root = data_dir or D.OUT
        self.cfg = cfg or load("rl")
        self.sim_cfg = load("sim")
        self.meta = json.loads((root / "meta.json").read_text())
        self.assets = self.meta["assets"]
        self.industries = self.meta["industries"]
        obs = pd.read_parquet(root / "obs.parquet")
        obs["d"] = pd.to_datetime(obs["d"])
        self.obs = obs.set_index("d")[self.meta["features"]]
        self.mean = pd.Series(self.meta["mean"]).reindex(self.obs.columns).fillna(0)
        self.std = pd.Series(self.meta["std"]).reindex(self.obs.columns).replace(0, 1).fillna(1)
        sl = pd.read_parquet(root / "sleeves.parquet")
        sl["month"] = pd.to_datetime(sl["month"])
        self.sleeves = sl
        hv = pd.read_parquet(root / "haven.parquet")
        self.haven = hv.assign(d=pd.to_datetime(hv["d"])).set_index("d")
        px = {}
        for f in ("open", "high", "low", "close", "volume"):
            p = pd.read_parquet(root / f"prices_{f}.parquet")
            p = p.set_index(p.columns[0])
            p.index = pd.to_datetime(p.index)
            px[f] = p
        self.px = px
        self.split = split
        self.lo, self.hi = open_split(split, allow_test=allow_test, who=f"AllocatorEnv({split})")
        self.episode_weeks = self.cfg["env"]["episode_weeks"] if episode_weeks == -1 else episode_weeks
        dates = self.obs.index[(self.obs.index >= self.lo) & (self.obs.index <= self.hi)]
        self.dates = dates
        self.rng = np.random.default_rng(seed)
        self.n_assets = len(self.assets)
        self.obs_dim = 2 * self.obs.shape[1] + self.n_assets + 2
        if gym is not None:
            from gymnasium import spaces
            self.observation_space = spaces.Box(-np.inf, np.inf, (self.obs_dim,), np.float32)
            self.action_space = spaces.Box(0.0, 1.0, (self.n_assets,), np.float32)
        self._gen = None

    # ------------------------------------------------------------------ helpers
    def _vol(self, d) -> pd.Series:
        r = self.px["close"].loc[:d].iloc[-64:].pct_change(fill_method=None)
        return (r.std() * math.sqrt(252)).clip(lower=0.05)

    def _sleeve(self, ind: str, d) -> pd.Series:
        """Weights inside one industry sleeve (sum 1), from the latest month-end <= d."""
        s = self.sleeves[(self.sleeves["industry"] == ind) & (self.sleeves["month"] <= d)]
        if s.empty:
            return pd.Series(dtype=float)
        s = s[s["month"] == s["month"].max()]
        names = [str(c) for c in s["cik"] if str(c) in self.px["close"].columns]
        if not names:
            return pd.Series(dtype=float)
        live = self.px["close"].loc[:d, names].iloc[-1].notna()
        names = [n for n in names if live[n]]
        if not names:
            return pd.Series(dtype=float)
        inv = 1 / self._vol(d).reindex(names).fillna(0.5)
        return inv / inv.sum()

    def targets(self, action, d) -> dict:
        a = np.clip(np.nan_to_num(np.asarray(action, dtype=float)), 0, None)
        if a.sum() > 1:
            a = a / a.sum()
        t = {}
        for w, asset in zip(a, self.assets):
            if w <= 1e-6:
                continue
            if asset in self.industries:
                for sym, x in self._sleeve(asset, d).items():
                    t[sym] = t.get(sym, 0) + w * x
            else:
                sym = self.haven[asset].asof(d) if asset in self.haven else None
                if isinstance(sym, str) and sym in self.px["close"].columns:
                    t[sym] = t.get(sym, 0) + w
        return t

    def _asset_weights(self, pf, d) -> np.ndarray:
        w = np.zeros(self.n_assets)
        held = pf.weights or {}
        idx = {a: i for i, a in enumerate(self.assets)}
        sym_asset = {}
        s = self.sleeves[self.sleeves["month"] <= d]
        for r in s.itertuples():
            sym_asset[str(r.cik)] = r.industry
        for k in self.haven.columns:
            for sym in set(self.haven[k].dropna()):
                sym_asset[sym] = k
        for sym, x in held.items():
            a = sym_asset.get(sym)
            if a in idx:
                w[idx[a]] += x
        return w

    def _observe(self, d, pf) -> np.ndarray:
        x = self.obs.loc[d] if d in self.obs.index else self.obs.loc[:d].iloc[-1]
        z = ((x - self.mean) / self.std).to_numpy(dtype=float)
        miss = np.isnan(z).astype(float)
        z = np.clip(np.nan_to_num(z), -10, 10)
        w = self._asset_weights(pf, d)
        dd = self._eq / self._peak - 1
        return np.concatenate([z, miss, w, [max(0.0, 1 - w.sum()), dd]]).astype(np.float32)

    # ------------------------------------------------------------------ API
    def reset(self, seed=None, options=None):
        if seed is not None:
            self.rng = np.random.default_rng(seed)
        options = options or {}
        if len(self.dates) < 3:
            raise RuntimeError(f"not enough decision dates in {self.split}")
        if self.episode_weeks and len(self.dates) > self.episode_weeks + 1:
            i0 = int(options.get("start_index", self.rng.integers(0, len(self.dates) - self.episode_weeks)))
            ep = self.dates[i0:i0 + self.episode_weeks + 1]
        else:
            ep = self.dates
        self.ep_dates = set(ep)
        self.ep_end = ep[-1]
        start = ep[0]
        lo = start - pd.Timedelta(days=400)   # history for liquidity / volatility estimates
        P = {f: v.loc[lo:self.ep_end + pd.Timedelta(days=10)] for f, v in self.px.items()}
        data = PriceData(**P)
        settings = SimSettings.from_config(self.sim_cfg)
        settings.initial_cash = self.cfg["env"]["initial_cash"]
        self.bt = Backtester(data, _Hold(), CostModel.from_config(self.sim_cfg["costs"]), settings)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self._gen = self.bt.iterate(start=start, end=self.ep_end)
            view, pf = next(self._gen)
        self._eq = self._peak = pf.equity
        self._pf, self._d = pf, view.date
        self._last_w = np.zeros(self.n_assets)
        self.history = [{"d": view.date, "equity": pf.equity}]
        return self._observe(view.date, pf), {"date": str(view.date.date()), "equity": pf.equity}

    def step(self, action):
        if self._gen is None:
            raise RuntimeError("call reset() first")
        rw = self.cfg["env"]["reward"]
        target = None if action is None else self.targets(action, self._d)
        new_w = self._last_w if action is None else np.clip(np.nan_to_num(np.asarray(action, float)), 0, None)
        if new_w.sum() > 1:
            new_w = new_w / new_w.sum()
        turnover = float(np.abs(new_w - self._last_w).sum())
        self._last_w = new_w
        eq0, peak0 = self._eq, self._peak
        done = False
        send = target
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            while True:
                try:
                    view, pf = self._gen.send(send)
                except StopIteration as stop:
                    self.result = stop.value
                    done = True
                    eq = float(self.result.equity.iloc[-1])
                    d = self.result.equity.index[-1]
                    pf = self._pf
                    break
                send = None
                d, eq = view.date, pf.equity
                self.history.append({"d": d, "equity": eq})
                if d in self.ep_dates or d >= self.ep_end:
                    break
        if done:   # tax on gains realized since the last January payment is owed: charge it now
            tax = self._unpaid_tax()
            self.tax_due_end = tax
            eq = max(eq - tax, 1e-9)
            self.history.append({"d": d, "equity": eq})
        self._peak = max(peak0, eq)
        dd0, dd1 = eq0 / peak0 - 1, eq / self._peak - 1
        reward = math.log(max(eq, 1e-9) / max(eq0, 1e-9)) - rw["drawdown_penalty"] * max(0.0, dd0 - dd1) \
            - rw["turnover_penalty"] * turnover
        self._eq, self._pf, self._d = eq, pf, d
        terminated = done or d >= self.ep_end
        info = {"date": str(pd.Timestamp(d).date()), "equity": eq, "turnover": turnover, "drawdown": dd1}
        return self._observe(d, pf), float(reward), bool(terminated), False, info

    def _unpaid_tax(self) -> float:
        res = getattr(self, "result", None)
        if res is None or res.realized.empty:
            return 0.0
        r = res.realized.copy()
        r["year"] = pd.to_datetime(r["date"]).dt.year
        paid_years = {pd.Timestamp(d).year - 1 for d in res.taxes_paid.index}
        st_rate = self.sim_cfg["account"].get("short_term_tax_rate", 0.32)
        lt_rate = self.sim_cfg["account"].get("long_term_tax_rate", 0.15)
        tax = 0.0
        for y, g in r.groupby("year"):
            if y in paid_years:
                continue
            st = g.loc[g["term"] == "short", "gain"].sum()
            lt = g.loc[g["term"] == "long", "gain"].sum()
            tax += year_tax(st, lt, 0.0, st_rate, lt_rate)[0]
        return float(tax)

    def equity_curve(self) -> pd.Series:
        h = pd.DataFrame(self.history).drop_duplicates("d", keep="last").set_index("d")["equity"]
        return h

    def max_drawdown(self) -> float:
        return float(drawdown(self.equity_curve()).min())
