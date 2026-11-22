import numpy as np
import pandas as pd
import pytest

from ddb.data.failures import FailureLedger
from ddb.sim.costs import CostModel
from ddb.sim.engine import Backtester, SimSettings
from ddb.strategies.baselines import BuyAndHold, TrendFilter

from conftest import make_prices

FREE = CostModel(spread_tiers=[(0, 0.0)], impact_coef=0.0, max_participation=1.0)


class Recorder:
    """Buys AAA once on a given day and records what it could see."""

    def __init__(self, buy_on: int = 5):
        self.calls = 0
        self.buy_on = buy_on
        self.seen_last = []

    def decide(self, view, pf):
        self.seen_last.append((view.date, view.history("close").index[-1]))
        self.calls += 1
        if self.calls == self.buy_on:
            return {"AAA": 1.0}
        return None


def test_fill_happens_next_day_at_open():
    closes = [100.0 + i for i in range(20)]          # rising
    data = make_prices({"AAA": closes})
    strat = Recorder(buy_on=5)                        # decides at close of day index 4
    res = Backtester(data, strat, FREE, SimSettings(initial_cash=1000)).run()
    t = res.trades.iloc[0]
    assert t["date"] == data.calendar[5]
    assert t["ref"] == pytest.approx(data.open.iloc[5]["AAA"])   # = close of day 4 (no gap)
    assert t["ref"] != data.close.iloc[5]["AAA"]


def test_strategy_never_sees_future():
    data = make_prices({"AAA": [100.0] * 15})
    strat = Recorder(buy_on=999)
    Backtester(data, strat, FREE).run()
    assert all(d == last for d, last in strat.seen_last)


def test_costs_reduce_equity():
    data = make_prices({"AAA": [100.0] * 30}, volume=1e5)  # ~$10M ADV -> wide spread tier
    free = Backtester(data, BuyAndHold(["AAA"]), FREE, SimSettings(initial_cash=10_000)).run()
    costly = Backtester(data, BuyAndHold(["AAA"]), CostModel(max_participation=1.0),
                        SimSettings(initial_cash=10_000)).run()
    assert costly.equity.iloc[-1] < free.equity.iloc[-1]
    assert costly.trades["slippage_bps"].iloc[0] > 0


def test_participation_cap_limits_order():
    data = make_prices({"AAA": [100.0] * 30}, volume=100)   # ADV $10k
    res = Backtester(data, BuyAndHold(["AAA"]), CostModel(max_participation=0.01),
                     SimSettings(initial_cash=10_000, min_trade_value=1)).run()
    assert res.trades["shares"].iloc[0] * 100 <= 100 + 1e-6   # 1% of $10k
    assert (res.cancelled["reason"] == "participation_cap").any()


def test_long_only_and_no_leverage_enforced():
    data = make_prices({"AAA": [100.0] * 10, "BBB": [50.0] * 10})

    class Bad:
        def __init__(self, w):
            self.w = w

        def decide(self, view, pf):
            return self.w

    with pytest.raises(ValueError):
        Backtester(data, Bad({"AAA": -0.5}), FREE).run()
    with pytest.raises(ValueError):
        Backtester(data, Bad({"AAA": 0.8, "BBB": 0.5}), FREE).run()


def test_delisted_holding_settles_at_ledger_value():
    data = make_prices({"AAA": [10.0] * 10, "SPY": [100.0] * 20})
    ledger = FailureLedger()
    ledger.add(symbol="AAA", event_type="bankruptcy", event_date="2024-01-15", terminal_value=0.0)
    res = Backtester(data, BuyAndHold(["AAA"]), FREE, SimSettings(initial_cash=1000), ledger).run()
    assert len(res.exits) == 1 and res.exits.iloc[0]["kind"] == "bankruptcy"
    assert res.equity.iloc[-1] == pytest.approx(0.0, abs=1.0)


def test_unknown_exit_uses_recovery_policy():
    data = make_prices({"AAA": [10.0] * 10, "SPY": [100.0] * 20})
    with pytest.warns(UserWarning):
        res = Backtester(data, BuyAndHold(["AAA"]), FREE,
                         SimSettings(initial_cash=1000, unknown_exit_recovery=0.5)).run()
    assert res.equity.iloc[-1] == pytest.approx(500, rel=0.01)


def test_trend_filter_rotates_to_haven_in_crash():
    up = list(np.linspace(100, 200, 250))
    crash = list(np.linspace(200, 80, 60))
    data = make_prices({"RISK": up + crash, "BIL": [100.0] * 310})
    res = Backtester(data, TrendFilter(["RISK"], "BIL", ma_days=200), FREE,
                     SimSettings(initial_cash=10_000)).run()
    final_w = res.weights.iloc[-1]
    assert final_w.get("BIL", 0) > 0.9
    # Rotation saved most of the crash vs. holding.
    hold = Backtester(data, BuyAndHold(["RISK"]), FREE, SimSettings(initial_cash=10_000)).run()
    assert res.equity.iloc[-1] > hold.equity.iloc[-1]


def test_taxes_paid_in_january_reduce_equity():
    n = 300
    closes = list(np.linspace(100, 200, n))
    data = make_prices({"AAA": closes, "BIL": [100.0] * n}, start="2024-06-03")

    class SellInDec:
        def decide(self, view, pf):
            if not pf.weights and view.date.year == 2024 and view.date.month < 12:
                return {"AAA": 1.0}
            if view.date.month == 12 and pf.weights.get("AAA", 0) > 0:
                return {"BIL": 1.0}
            return None

    taxed = Backtester(data, SellInDec(), FREE, SimSettings(initial_cash=10_000)).run()
    untaxed = Backtester(data, SellInDec(), FREE, SimSettings(initial_cash=10_000, pay_taxes=False)).run()
    assert len(taxed.taxes_paid) == 1 and taxed.taxes_paid.index[0].year == 2025
    gain = taxed.realized["gain"].sum()
    assert taxed.taxes_paid.iloc[0] == pytest.approx(0.32 * gain, rel=0.01)
    assert taxed.equity.iloc[-1] < untaxed.equity.iloc[-1]
