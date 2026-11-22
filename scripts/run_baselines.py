"""Run the Phase 1 baselines on cached prices and print the scoreboard.

    python scripts/run_baselines.py [--start 2015-01-01]
"""
import argparse
import warnings

import pandas as pd

from ddb import metrics
from ddb.config import DATA_DIR, load, universe_symbols
from ddb.data.failures import FailureLedger
from ddb.data.prices import PriceData
from ddb.sim.costs import CostModel
from ddb.sim.engine import Backtester, SimSettings
from ddb.strategies.baselines import BuyAndHold, Momentum12_1, PeriodicEqualWeight, TrendFilter


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2015-01-01")
    ap.add_argument("--end", default=None)
    args = ap.parse_args()

    ucfg, scfg = load("universe"), load("sim")
    g = universe_symbols(ucfg, include_pool=False)
    focus = g["tech"] + g["energy"]
    haven = ucfg["safe_haven"]["cash_proxy"]
    data = PriceData.from_cache(DATA_DIR, focus + g["haven"] + g["benchmarks"])
    focus = [s for s in focus if s in data.symbols]
    costs = CostModel.from_config(scfg["costs"])
    settings = SimSettings.from_config(scfg)
    ledger = FailureLedger.load(DATA_DIR / "failures" / "ledger.csv")

    strategies = {
        "SPY buy&hold": BuyAndHold(["SPY"]),
        "QQQ buy&hold": BuyAndHold(["QQQ"]),
        "focus EW buy&hold": BuyAndHold(focus),
        "focus EW monthly": PeriodicEqualWeight(focus, "M"),
        "focus trend->BIL": TrendFilter(focus, haven, 200, "W"),
        "focus mom 12-1 top5": Momentum12_1(focus, 5),
    }
    rows = []
    for name, strat in strategies.items():
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            res = Backtester(data, strat, costs, settings, ledger).run(args.start, args.end)
        s = metrics.summary(res.equity)
        tax = res.taxes_paid.sum()
        rows.append({"strategy": name, **{k: s.get(k) for k in (
            "cagr", "max_drawdown", "sharpe_rf0", "h18_median", "h18_p05", "h18_pct_positive")},
            "trades": len(res.trades), "taxes_paid": tax, "wash_disallowed": res.wash_disallowed_total})
    out = pd.DataFrame(rows).set_index("strategy")
    pd.set_option("display.width", 200)
    print(f"{args.start} .. {data.calendar[-1].date()}  initial ${settings.initial_cash:,.0f}  "
          f"(h18 = rolling 18-month return)")
    print(out.to_string(float_format=lambda x: f"{x:,.3f}"))
    (DATA_DIR / "results").mkdir(exist_ok=True)
    out.to_csv(DATA_DIR / "results" / "baselines.csv")


if __name__ == "__main__":
    main()
