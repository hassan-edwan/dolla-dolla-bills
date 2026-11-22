"""Baselines every learned strategy must beat after costs and taxes."""
from __future__ import annotations

import numpy as np

from ..sim.engine import MarketView, Portfolio


class BuyAndHold:
    """Equal weight once (retrying until filled), then never trade."""

    def __init__(self, symbols):
        self.symbols = list(symbols)

    def decide(self, view: MarketView, pf: Portfolio):
        if pf.weights:
            return None
        live = [s for s in self.symbols if s in view.tradable()]
        return {s: 1.0 / len(live) for s in live} if live else None


class PeriodicEqualWeight:
    def __init__(self, symbols, freq: str = "M"):
        self.symbols, self.freq = list(symbols), freq

    def decide(self, view: MarketView, pf: Portfolio):
        if pf.weights and not view.is_period_end(self.freq):
            return None
        live = [s for s in self.symbols if s in view.tradable()]
        return {s: 1.0 / len(live) for s in live} if live else None


class TrendFilter:
    """Hold the risk basket equal-weight while its equal-weight index is above its
    moving average, otherwise hold the haven. This is the key baseline for the
    'rotate to safety when volatile industries crash' idea.

    The regime is checked every `freq` period. Trades happen only when the regime flips,
    plus a monthly rebalance while risk-on."""

    def __init__(self, risk_symbols, haven: str, ma_days: int = 200, freq: str = "W"):
        self.risk, self.haven, self.ma, self.freq = list(risk_symbols), haven, ma_days, freq
        self.state = None

    def decide(self, view: MarketView, pf: Portfolio):
        if pf.weights and not view.is_period_end(self.freq):
            return None
        closes = view.history("close", self.ma + 1)[self.risk]
        rets = closes.pct_change(fill_method=None).mean(axis=1, skipna=True).fillna(0.0)
        index = (1 + rets).cumprod()
        if len(index) < self.ma:
            return None
        risk_on = bool(index.iloc[-1] > index.iloc[-self.ma:].mean())
        flipped = risk_on != self.state
        self.state = risk_on
        if pf.weights and not flipped and not (risk_on and view.is_period_end("M")):
            return None
        if risk_on:
            live = [s for s in self.risk if s in view.tradable()]
            return {s: 1.0 / len(live) for s in live} if live else None
        return {self.haven: 1.0} if self.haven in view.tradable() else {}


class Momentum12_1:
    """Monthly: hold the top_n by 12-month return, skipping the most recent month."""

    def __init__(self, symbols, top_n: int = 5, lookback: int = 252, skip: int = 21):
        self.symbols, self.top_n, self.lookback, self.skip = list(symbols), top_n, lookback, skip

    def decide(self, view: MarketView, pf: Portfolio):
        if pf.weights and not view.is_period_end("M"):
            return None
        c = view.history("close", self.lookback + 1)[self.symbols]
        if len(c) <= self.lookback:
            return None
        mom = c.iloc[-1 - self.skip] / c.iloc[0] - 1
        mom = mom[[s for s in mom.index if s in view.tradable()]].replace([np.inf, -np.inf], np.nan).dropna()
        top = mom.sort_values(ascending=False).head(self.top_n).index
        return {s: 1.0 / len(top) for s in top} if len(top) else {}
