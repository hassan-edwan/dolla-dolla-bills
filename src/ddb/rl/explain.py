"""Why did the allocator do that? Attribution, decision reports and charts.

Attribution (counterfactual, per input group): for each group of observation
inputs (the market regime, each industry, gold, T-bills, the current holdings),
replace that group with "normal" (its training-period mean: z = 0, nothing
missing) and ask the policy again. The change in each asset's weight is that
group's contribution. Works for any policy that maps observations to weights.

Decision report, per decision:
- `clear`: real names, dates and values, for people (dashboard, charts);
- `anonymized`: for an LLM reviewer. No dates, no names (sectors are "Sector A..",
  in a per-run shuffled order), and only standardized values (percentiles /
  z-scores), never raw levels: a raw VIX of 80 dates a report to March 2020 as
  surely as the date itself. LLMs trained on the internet know what happened next;
  they must not be able to tell when a decision was made.

Charts (PNG): allocation before/after, attribution by group and asset, and the
recent history of the market regime and sector trends.

    python -m ddb.rl.explain --policy regime_rule --split validation --every 4 [--review]
"""
from __future__ import annotations

import argparse
import json
import string

import numpy as np
import pandas as pd

from ..config import DATA_DIR
from . import dataset as D

OUT = DATA_DIR / "db" / "rl" / "reports"

PLAIN = {   # feature suffix -> plain description
    "ret_4w": "4-week return", "ret_12w": "12-week return", "ret_26w": "26-week return",
    "vol_12w": "12-week volatility", "trend": "price vs its 200-day average", "breadth": "share of stocks above their 200-day average",
    "n_candidates": "number of buy candidates", "cand_score": "average score of buy candidates",
    "median_score": "median score of all screened stocks", "vix": "VIX", "vix_pct": "VIX percentile (5 years)",
    "credit": "credit spread", "baa": "Baa credit spread", "baa_chg_3m": "3-month change in credit spread",
    "curve_10y3m": "10y-3m yield curve", "mkt_trend": "market vs its 200-day average", "mkt_vol": "market volatility",
    "mkt_ret_24m": "24-month market return", "crash_state": "momentum-crash state", "points": "stress points",
    "tbill_yield": "3-month T-bill yield",
}


# Absolute macro levels date a report (e.g. high T-bill yields + an inverted curve = 2022-23),
# so the anonymized report leaves them out and keeps the regime label and relative measures.
DATING = {"tbill_yield", "mkt__curve_10y3m", "mkt__curve_10y2y", "mkt__vix", "mkt__credit", "mkt__baa",
          "mkt__hy_oas", "mkt__mkt_ret_24m", "mkt__baa_chg_3m"}


def _words(z: float) -> str:
    if not np.isfinite(z):
        return "missing"
    a = abs(z)
    lvl = "far" if a >= 2 else "well" if a >= 1 else "slightly" if a >= 0.3 else "about"
    return "about normal" if lvl == "about" else f"{lvl} {'above' if z > 0 else 'below'} normal"


class Explainer:
    """Groups the observation layout of AllocatorEnv / FastAllocatorEnv:
    [z (F), missing mask (F), asset weights (A), cash, drawdown]."""

    def __init__(self, features: list[str], assets: list[str], industries: list[str], seed: int = 0):
        self.features, self.assets, self.industries = features, assets, industries
        F, A = len(features), len(assets)
        self.F, self.A = F, A
        groups: dict[str, list[int]] = {}
        for j, f in enumerate(features):
            head = f.split("__")[0]
            g = "market" if head == "mkt" or f == "tbill_yield" else head
            groups.setdefault(g, []).append(j)
        self.groups = groups
        rng = np.random.default_rng(seed)
        order = rng.permutation(len(industries))
        letters = string.ascii_uppercase
        self.alias = {ind: f"Sector {letters[k]}" for k, ind in zip(order, industries)}
        self.alias.update({"gold": "Gold fund", "tbills": "T-bill fund", "market": "Market regime",
                           "holdings": "Current holdings"})

    def counterfactuals(self, obs: np.ndarray) -> tuple[list[str], np.ndarray]:
        """Observations with one group at a time set to normal (stacked), plus their names."""
        names, rows = [], []
        F, A = self.F, self.A
        for g, idx in self.groups.items():
            o = obs.copy()
            o[idx] = 0.0
            o[[F + j for j in idx]] = 0.0
            names.append(g)
            rows.append(o)
        o = obs.copy()                                     # holdings: as if starting from cash, no drawdown
        o[2 * F:2 * F + A] = 0.0
        o[2 * F + A] = 1.0
        o[2 * F + A + 1] = 0.0
        names.append("holdings")
        rows.append(o)
        return names, np.stack(rows)

    def attribute(self, policy, obs: np.ndarray) -> tuple[np.ndarray, dict]:
        """policy: obs [B, obs_dim] -> weights [B, A]. Returns the action and
        {group: weight change per asset caused by that group}."""
        names, cf = self.counterfactuals(obs)
        out = np.asarray(policy(np.vstack([obs[None], cf])), float)
        base = out[0]
        return base, {g: base - out[k + 1] for k, g in enumerate(names)}

    def report(self, date, obs: np.ndarray, action: np.ndarray, prev_w: np.ndarray, attribution: dict,
               raw: pd.Series | None = None) -> dict:
        F, A = self.F, self.A
        z = obs[:F]
        miss = obs[F:2 * F] > 0
        act = np.clip(np.nan_to_num(action), 0, None)
        act = act / act.sum() if act.sum() > 1 else act
        top = sorted(attribution.items(), key=lambda kv: -float(np.abs(kv[1]).sum()))
        evidence = []
        for g, _ in top[:4]:
            if g == "holdings":
                continue
            idx = sorted(self.groups[g], key=lambda j: -abs(z[j]))[:4]
            for j in idx:
                f = self.features[j]
                key = f.split("__", 1)[1] if "__" in f else f
                evidence.append({"group": g, "feature": f, "plain": PLAIN.get(key, key), "z": None if miss[j] else round(float(z[j]), 2),
                                 "raw": None if raw is None or pd.isna(raw.get(f)) else round(float(raw[f]), 4)})
        moves = [{"asset": a, "from": round(float(prev_w[i]), 3), "to": round(float(act[i]), 3)} for i, a in enumerate(self.assets)]
        attr = {g: {a: round(float(v[i]), 3) for i, a in enumerate(self.assets) if abs(v[i]) >= 0.005}
                for g, v in attribution.items()}
        clear = {"date": str(pd.Timestamp(date).date()), "weights": moves, "cash_to": round(float(1 - act.sum()), 3),
                 "attribution": attr, "evidence": evidence,
                 "drawdown": round(float(obs[2 * F + A + 1]), 4)}
        al = self.alias
        pts = None if raw is None else raw.get("mkt__points")
        state = None if pts is None or pd.isna(pts) else ("stress" if pts >= 3 else "caution" if pts >= 2 else "calm")
        rec = {}
        for a in self.assets:
            v = None if raw is None else raw.get(f"{a}__ret_4w")
            rec[a] = None if v is None or pd.isna(v) else round(float(v), 4)
        clear["market_state"], clear["recent_4w_return"] = state, rec
        anon = {
            "decision": "weekly allocation across sector baskets, a gold fund, a T-bill fund and cash",
            "weights": [{"asset": al.get(m["asset"], m["asset"]), "from": m["from"], "to": m["to"]} for m in moves],
            "cash_to": clear["cash_to"],
            "drawdown_now": clear["drawdown"],
            "market_state": state,
            "recent_4w_return": {al.get(a, a): v for a, v in rec.items()},
            "what_drove_it": [{"input_group": al.get(g, g),
                               "effect_on_weights": {al.get(a, a): v for a, v in d.items()}} for g, d in attr.items() if d],
            "evidence": [{"input_group": al.get(e["group"], e["group"]), "measure": e["plain"],
                          "standardized": e["z"], "reading": _words(e["z"]) if e["z"] is not None else "missing"}
                         for e in evidence if e["feature"] not in DATING],
            "notes": "Values are standardized against a long history (z-scores); 0 = normal. No dates or names are given on purpose.",
        }
        return {"clear": clear, "anonymized": anon}

    def charts(self, rep: dict, history: pd.DataFrame, path) -> None:
        """PNG for people: allocation before/after, attribution, regime + sector trends history."""
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        c = rep["clear"]
        fig, ax = plt.subplots(2, 2, figsize=(13, 8), constrained_layout=True)
        names = [m["asset"] for m in c["weights"]]
        x = np.arange(len(names))
        ax[0, 0].bar(x - 0.2, [m["from"] for m in c["weights"]], 0.4, label="before", color="#c3c2b7")
        ax[0, 0].bar(x + 0.2, [m["to"] for m in c["weights"]], 0.4, label="after", color="#2a78d6")
        ax[0, 0].set_xticks(x, names, rotation=40, ha="right", fontsize=8)
        ax[0, 0].set_title(f"Allocation · {c['date']} (cash after {c['cash_to']:.0%})", fontsize=10)
        ax[0, 0].legend(fontsize=8)
        groups = list(c["attribution"])
        M = np.array([[c["attribution"][g].get(a, 0.0) for a in names] for g in groups]) if groups else np.zeros((1, len(names)))
        lim = max(0.05, float(np.abs(M).max()))
        im = ax[0, 1].imshow(M, cmap="RdBu", vmin=-lim, vmax=lim, aspect="auto")
        ax[0, 1].set_xticks(range(len(names)), names, rotation=40, ha="right", fontsize=8)
        ax[0, 1].set_yticks(range(len(groups)), groups, fontsize=8)
        ax[0, 1].set_title("What drove each weight (change vs that input at normal)", fontsize=10)
        fig.colorbar(im, ax=ax[0, 1], shrink=0.8)
        h = history.tail(52)
        for col, lab in (("mkt__vix_pct", "VIX percentile"), ("mkt__breadth", "breadth"), ("mkt__mkt_trend", "market vs 200d")):
            if col in h:
                ax[1, 0].plot(h.index, h[col], label=lab)
        ax[1, 0].set_title("Market regime, last 52 weeks", fontsize=10)
        ax[1, 0].legend(fontsize=8)
        for ind in self.industries:
            col = f"{ind}__ret_12w"
            if col in h and h[col].notna().any():
                ax[1, 1].plot(h.index, h[col], label=ind, linewidth=1)
        ax[1, 1].set_title("Sector 12-week returns, last 52 weeks", fontsize=10)
        ax[1, 1].legend(fontsize=7, ncol=2)
        for a in ax[1]:
            a.tick_params(axis="x", labelsize=7)
        fig.savefig(path, dpi=110)
        plt.close(fig)


# ------------------------------------------------------------------ baseline policies on observations
def obs_policy(name: str, meta: dict, mean=None, std=None):
    """Baselines as functions of the observation vector (for attribution); they read
    features back in raw units with the decision date's standardization (mean / std of
    earlier dates: env.obs_mean / env.obs_std at that date)."""
    feats, assets, inds = meta["features"], meta["assets"], meta["industries"]
    mean = np.nan_to_num(np.asarray(mean if mean is not None else [meta["mean"].get(f, 0.0) for f in feats], float))
    std = np.asarray(std if std is not None else [meta["std"].get(f, 1.0) or 1.0 for f in feats], float)
    std = np.where(np.isfinite(std) & (std > 0), std, 1.0)
    F, A = len(feats), len(assets)
    col = {f: j for j, f in enumerate(feats)}
    eq = np.array([1 / len(inds) if a in inds else 0.0 for a in assets])
    tb = np.array([1.0 if a == "tbills" else 0.0 for a in assets])
    gold = np.array([1.0 if a == "gold" else 0.0 for a in assets])

    def raw(obs, f):
        return obs[:, col[f]] * std[col[f]] + mean[col[f]]

    def policy(obs):
        obs = np.atleast_2d(obs)
        if name == "equal_industries":
            return np.repeat(eq[None], len(obs), 0)
        if name == "trend_filter":
            t = raw(obs, "mkt__mkt_trend")
            return np.where((t < 0)[:, None], tb[None], eq[None])
        if name == "regime_rule":
            p = np.round(raw(obs, "mkt__points"))           # whole points; avoid 2.9999 < 3
            stress = (p >= 3)[:, None]
            caution = ((p >= 2) & (p < 3))[:, None]
            return np.where(stress, 0.7 * tb + 0.3 * gold, np.where(caution, 0.5 * eq + 0.35 * tb + 0.15 * gold, eq))
        if name == "industry_momentum":
            r = np.stack([raw(obs, f"{i}__ret_12w") if f"{i}__ret_12w" in col else np.full(len(obs), np.nan)
                          for i in inds], 1)
            r = np.where(obs[:, [F + col[f"{i}__ret_12w"] for i in inds]] > 0, -np.inf, r)
            out = np.zeros((len(obs), A))
            for b in range(len(obs)):
                best = np.argsort(r[b])[-2:]
                for k in best:
                    out[b, assets.index(inds[k])] = 0.5
            return out
        raise ValueError(name)
    return policy


def run(policy_name: str = "regime_rule", split: str = "validation", every: int = 4, review: bool = False,
        llm: bool = False) -> dict:
    """Walk a policy through a split in the full environment, writing a report (JSON
    + PNG) for every `every`-th decision, reviewing each with the rule checks (and the
    LLM if `llm`), and recording the decisions in the decision log."""
    from ..db.schema import connect
    from ..decisions import DecisionLog, Factor
    from .env import AllocatorEnv
    from .review import LLMReviewer, RuleReviewer
    env = AllocatorEnv(split=split, episode_weeks=None)
    meta = env.meta
    def pol_at(d):
        dd = env.obs_mean.index[env.obs_mean.index <= d][-1]
        return obs_policy(policy_name, meta, env.obs_mean.loc[dd].to_numpy(), env.obs_std.loc[dd].to_numpy())
    ex = Explainer(meta["features"], meta["assets"], meta["industries"])
    raw = env.obs
    out = OUT / f"{policy_name}_{split}"
    out.mkdir(parents=True, exist_ok=True)
    rules = RuleReviewer()
    lr = LLMReviewer() if llm else None
    con = connect(DATA_DIR / "ddb.duckdb")
    log = DecisionLog(con)
    run_id = log.new_run(f"allocator:{policy_name}", {"split": split}, "baseline policy with attribution reports")
    obs, info = env.reset()
    prev = np.zeros(env.n_assets)
    k, n_flags, reviews = 0, 0, []
    done = False
    while not done:
        d = env._d
        pol = pol_at(d)
        if k % every == 0:
            action, attr = ex.attribute(pol, obs)
            empty = np.array([a in env.industries and env._sleeve(a, d).empty for a in env.assets])
            action = np.where(empty, 0.0, action)       # an empty sleeve's weight stays cash: report what is held
            rep = ex.report(d, obs, action, prev, attr, raw.loc[:d].iloc[-1])
            rep["review_rules"] = rules.review(rep["anonymized"])
            if lr is not None:
                rep["review_llm"] = lr.review(rep["anonymized"])
            n_flags += len(rep["review_rules"]["flags"])
            stamp = str(pd.Timestamp(d).date())
            (out / f"{stamp}.json").write_text(json.dumps(rep, indent=1, default=str))
            ex.charts(rep, raw.loc[:d], out / f"{stamp}.png")
            for i, a in enumerate(env.assets):
                if abs(action[i] - prev[i]) < 1e-6 and action[i] == 0:
                    continue
                facs = [Factor(factor=f"{g}", contribution=float(v[i]), group="attribution",
                               description=f"weight change for {a} caused by {g}",
                               source_table="rl/obs", knowable_at=pd.Timestamp(d) + pd.Timedelta(hours=21))
                        for g, v in attr.items() if abs(v[i]) >= 0.005]
                log.record(run_id, pd.Timestamp(d) + pd.Timedelta(hours=21, minutes=30), 0, f"sleeve:{a}",
                           "buy" if action[i] > prev[i] else "sell" if action[i] < prev[i] else "hold",
                           target_weight=float(action[i]), prev_weight=float(prev[i]),
                           rationale="; ".join(f["text"] for f in rep["review_rules"]["flags"]) or "", factors=facs)
            reviews.append({"date": stamp, **{k2: rep["review_rules"][k2] for k2 in ("verdict", "scores")}})
        else:
            action = pol(obs[None])[0]
        prev = np.clip(action, 0, None)
        obs, r, done, _, info = env.step(action)
        k += 1
    log.flush()
    con.close()
    (out / "summary.json").write_text(json.dumps({"run_id": run_id, "reports": len(reviews), "rule_flags": n_flags,
                                                   "reviews": reviews}, indent=1))
    return {"run_id": run_id, "reports": len(reviews), "rule_flags": n_flags, "dir": str(out)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", default="regime_rule")
    ap.add_argument("--split", default="validation", choices=["train", "validation"])
    ap.add_argument("--every", type=int, default=4)
    ap.add_argument("--llm", action="store_true", help="also ask the LLM reviewer (configs/review.yaml)")
    a = ap.parse_args()
    print(run(a.policy, a.split, a.every, llm=a.llm))
