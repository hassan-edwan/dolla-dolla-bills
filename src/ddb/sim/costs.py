"""Transaction cost model: tiered half-spread + square-root market impact."""
from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class CostModel:
    commission_per_order: float = 0.0
    spread_tiers: list = field(default_factory=lambda: [
        (1e9, 1.0), (1e8, 3.0), (2e7, 8.0), (5e6, 20.0), (0, 50.0)])
    open_spread_multiplier: float = 1.5
    impact_coef: float = 0.1
    max_participation: float = 0.01

    @classmethod
    def from_config(cls, cfg: dict) -> "CostModel":
        cfg = dict(cfg)
        if "spread_tiers" in cfg:
            cfg["spread_tiers"] = [tuple(t) for t in cfg["spread_tiers"]]
        return cls(**cfg)

    def half_spread_bps(self, adv_dollars: float) -> float:
        for min_adv, bps in sorted(self.spread_tiers, key=lambda t: -t[0]):
            if adv_dollars >= min_adv:
                return bps
        return self.spread_tiers[-1][1]

    def slippage_frac(self, order_value: float, adv_dollars: float, daily_vol: float,
                      at_open: bool = True) -> float:
        """Adverse price move as a fraction of price (always >= 0)."""
        adv = max(adv_dollars, 1.0)
        spread = self.half_spread_bps(adv) * (self.open_spread_multiplier if at_open else 1.0) / 1e4
        vol = daily_vol if math.isfinite(daily_vol) else 0.03
        impact = self.impact_coef * vol * math.sqrt(max(order_value, 0.0) / adv)
        return spread + impact

    def max_order_value(self, adv_dollars: float) -> float:
        return self.max_participation * max(adv_dollars, 0.0)
