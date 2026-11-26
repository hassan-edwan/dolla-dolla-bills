"""Position sizing and portfolio risk (pure functions on returns and weights).

Sizing, in order:
1. take the top `max_names` buy candidates;
2. weight by inverse volatility (or equally);
3. cap single names, industries and clusters of highly correlated holdings,
   handing the excess to the rest (or leaving cash when everything is capped);
4. scale the whole book down to `target_vol` when its expected volatility is
   higher, and by `stress_exposure` in a stress regime; the rest is cash;
5. drop positions below `min_weight`.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def clusters(corr: pd.DataFrame, threshold: float) -> dict:
    """Connected groups of names whose pairwise correlation is >= threshold -> {name: cluster id}."""
    names = list(corr.index)
    parent = {n: n for n in names}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    C = corr.to_numpy()
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            if np.isfinite(C[i, j]) and C[i, j] >= threshold:
                parent[find(names[i])] = find(names[j])
    roots = {}
    return {n: roots.setdefault(find(n), len(roots)) for n in names}


def cap_groups(w: pd.Series, groups: pd.Series, cap: float, iters: int = 50) -> pd.Series:
    """Scale every group above `cap` down to it and give the excess to names in
    uncapped groups, in proportion to their weight. Excess nobody can take stays cash."""
    w = w.copy()
    for _ in range(iters):
        gw = w.groupby(groups).sum()
        over = gw[gw > cap + 1e-12]
        if over.empty:
            break
        excess = 0.0
        for g, tot in over.items():
            m = groups == g
            w[m] *= cap / tot
            excess += tot - cap
        free = ~groups.isin(gw[gw >= cap - 1e-12].index)
        room = w[free].sum()
        if room <= 0:
            break
        w[free] += excess * w[free] / room
    return w


def size(cands: pd.DataFrame, rets: pd.DataFrame, cfg: dict, stress: bool = False) -> tuple[pd.Series, dict]:
    """cands: rows with `key` (column name in rets), `industry`, `score`, ordered best first.
    rets: daily returns (lookback window, past only). Returns weights (sum <= 1) and notes."""
    c = cands.head(cfg["max_names"]).copy()
    notes = {"capped": {}, "scale": 1.0}
    if c.empty:
        return pd.Series(dtype=float), notes
    keys = list(c["key"])
    r = rets.reindex(columns=keys).iloc[-cfg["vol_lookback_days"]:]
    vol = r.std() * np.sqrt(252)
    vol = vol.fillna(vol.median() if vol.notna().any() else 0.5).clip(lower=0.05)
    raw = (1 / vol) if cfg.get("sizing", "inverse_vol") == "inverse_vol" else pd.Series(1.0, index=keys)
    w = raw / raw.sum()
    w = cap_groups(w, pd.Series(keys, index=keys), cfg["max_weight"])
    ind = pd.Series(list(c["industry"].fillna("other")), index=keys)
    w = cap_groups(w, ind, cfg["max_industry"])
    rr = rets.reindex(columns=keys).iloc[-cfg.get("risk_lookback_days", 126):]
    corr = rr.corr(min_periods=40)
    cl = pd.Series(clusters(corr.fillna(0), cfg["cluster_corr"]))
    if cl.nunique() < len(cl):
        w = cap_groups(w, cl.reindex(keys), cfg["max_cluster"])
    w = cap_groups(w, pd.Series(keys, index=keys), cfg["max_weight"])   # redistribution can re-breach name caps
    cov = rr.cov(min_periods=40).reindex(index=keys, columns=keys)
    pv = port_vol(w, cov)
    if pv and np.isfinite(pv) and pv > cfg["target_vol"]:
        notes["scale"] = cfg["target_vol"] / pv
    if stress:
        notes["scale"] *= cfg.get("stress_exposure", 1.0)
    w = w * notes["scale"]
    w = w[w >= cfg["min_weight"]]
    if w.sum() > 1:                        # rounding in the redistribution; never lever up
        w = w / w.sum()
    notes["clusters"] = cl.to_dict()
    notes["vol"] = vol.to_dict()
    return w, notes


def port_vol(w: pd.Series, cov: pd.DataFrame) -> float:
    c = cov.reindex(index=w.index, columns=w.index).fillna(0.0).to_numpy()
    v = float(w.to_numpy() @ c @ w.to_numpy())
    return float(np.sqrt(max(v, 0.0) * 252))


def risk(w: pd.Series, rets: pd.DataFrame, mkt: pd.Series | None = None) -> dict:
    """Risk of a weight vector from past daily returns: volatility, beta, each name's
    share of the risk, effective number of independent bets, and pairwise correlation."""
    if w.empty:
        return {}
    r = rets.reindex(columns=w.index)
    cov = r.cov(min_periods=40).fillna(0.0)
    W = w.to_numpy()
    C = cov.to_numpy()
    var = float(W @ C @ W)
    contrib = W * (C @ W) / var if var > 0 else np.full(len(W), np.nan)
    out = {"vol": float(np.sqrt(max(var, 0) * 252)), "cash": float(1 - w.sum()),
           "risk_share": dict(zip(w.index, np.round(contrib, 4))),
           "effective_bets": float(1 / np.nansum(contrib ** 2)) if var > 0 else None,
           "names": int(len(w))}
    sd = np.sqrt(np.diag(C))
    out["diversification"] = float((W @ sd) / np.sqrt(var)) if var > 0 else None
    corr = r.corr(min_periods=40)
    out["corr"] = corr.round(3).where(corr.notna(), None).to_numpy().tolist()
    if mkt is not None and len(mkt.dropna()) > 40:
        m = mkt.reindex(r.index)
        mv = m.var()
        betas = r.apply(lambda x: x.cov(m) / mv if mv > 0 else np.nan)
        out["beta_by_name"] = betas.round(3).to_dict()
        out["beta"] = float((betas.fillna(1.0) * w).sum())
        port = (r.fillna(0) * W).sum(axis=1)
        out["corr_to_market"] = float(port.corr(m))
    return out
