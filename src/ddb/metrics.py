"""Performance metrics. The primary objective is the distribution of rolling
18-month (378 trading day) log returns, not the single best path."""
from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252
HORIZON_18M = 378


def drawdown(equity: pd.Series) -> pd.Series:
    return equity / equity.cummax() - 1.0


def rolling_horizon_log_returns(equity: pd.Series, horizon: int = HORIZON_18M) -> pd.Series:
    lr = np.log(equity)
    return (lr.shift(-horizon) - lr).dropna()


def summary(equity: pd.Series, horizon: int = HORIZON_18M) -> dict:
    equity = equity.dropna()
    rets = equity.pct_change().dropna()
    years = max(len(rets) / TRADING_DAYS, 1e-9)
    total = equity.iloc[-1] / equity.iloc[0] - 1
    vol = rets.std() * np.sqrt(TRADING_DAYS)
    dd = drawdown(equity)
    out = {
        "start": equity.index[0].date(),
        "end": equity.index[-1].date(),
        "total_return": total,
        "cagr": (1 + total) ** (1 / years) - 1,
        "ann_vol": vol,
        "sharpe_rf0": (rets.mean() * TRADING_DAYS) / vol if vol > 0 else np.nan,
        "max_drawdown": dd.min(),
    }
    h = rolling_horizon_log_returns(equity, horizon)
    if len(h):
        simple = np.expm1(h)
        out.update({
            "h18_median": float(simple.median()),
            "h18_p05": float(simple.quantile(0.05)),
            "h18_p25": float(simple.quantile(0.25)),
            "h18_pct_positive": float((simple > 0).mean()),
            "h18_windows": int(len(h)),
        })
    return out


def drawdown_quantile(equity: pd.Series, window: int = HORIZON_18M, q: float = 0.99) -> float:
    """q-quantile of the worst drawdown seen within rolling windows. Used for the
    'model is broken' check: a live drawdown beyond this is evidence the model no
    longer behaves like its backtest."""
    worst = []
    for k in range(0, max(len(equity) - window, 1), max(window // 20, 1)):
        w = equity.iloc[k:k + window]
        worst.append(drawdown(w).min())
    return float(np.quantile(worst, 1 - q)) if worst else float("nan")
