# Portfolio, risk, regime and monitoring

Settings: `configs/risk.yaml`. Everything below uses only information public at
each date; the dashboard's as-of control applies to all of it.

## Model portfolio (`python -m ddb.portfolio.model`)

At every month-end, the monthly buy candidates (pass every screen, top 20% on
the walk-forward composite, no red flag) become positions:

1. top `max_names` by composite;
2. weights proportional to 1 / volatility (63 days), so a name that swings twice
   as much gets half the weight;
3. caps: `max_weight` per name, `max_industry` per industry, and `max_cluster`
   per group of holdings whose daily returns correlate >= `cluster_corr` (they
   are effectively one bet); excess goes to uncapped names, or stays cash;
4. the book is scaled down when its expected volatility exceeds `target_vol`, and
   by `stress_exposure` in a stress regime (1.0 by default: the regime is shown but
   doesn't change sizes until you decide it should);
5. positions under `min_weight` are dropped.

The targets are traded through the backtester (fills at the next open, spread +
impact costs, T+1 settlement, good-faith rule, FIFO lots, wash sales, yearly
taxes).

Risk shown for each month-end:

- volatility and beta;
- each holding's share of the portfolio's risk;
- **effective number of bets** = 1 / sum of squared risk shares;
- **diversification ratio** = weighted average volatility / portfolio volatility
  (1 = none);
- correlated groups, industry weights;
- style tilts (weighted z-scores for size, momentum, volatility, value,
  profitability, 52-week high).

**Expected return** = the average excess return of the composite quintile each
holding is in, over months whose results were public before that month-end. After
costs subtracts the backtest's realized monthly cost so far. After tax applies the
short-term rate (`sim.yaml`), since positions rarely last a year.

**"Model broken" line:** the 99th-percentile worst drawdown in 18-month windows of
the backtest. At each date it is computed from history that ended 18 months
earlier, so a current drawdown can't move its own threshold. A drawdown beyond it
means the model no longer behaves like its backtest: stop and review.

## Market regime (`python -m ddb.features.regime`)

One point each, at each day's close:

- VIX >= 30 or in its top 10% of 5 years;
- high-yield spread >= 6 or +1.5 points in 3 months;
- the equal-weight market below its 200-day average;
- fewer than 35% of liquid stocks above their 200-day average.

3+ points = **stress**, 2 (or 1 with an inverted 10y-3m curve) = **caution**,
else calm. **Momentum crash risk** (Daniel-Moskowitz): market down over 24 months
and volatility in its top 20%; momentum tends to crash in the rebound. The Market
tab shows how the composite did, out of sample, in each regime.

FRED series are public the day after their date.

## Earnings calendar

Free data has no forward calendar. The next results date is estimated from the
company's own results 8-Ks (item 2.02):

- a year after the report three reports back (companies report at about the same
  time each year);
- otherwise the last report plus the typical gap.

Names expected to report within `earnings_warning_days` trading days are flagged
on This month, Today and Portfolio.

## Monitoring (`python -m ddb.live.tracking`, after every data update)

- **Forecast log:** each new month-end ranking and short-term ranking is saved
  once, never overwritten, and scored when its month is over. This is the true
  live record.
- **Walk-forward record:** the composite's out-of-sample record. A negative
  12-month average raises an alert.
- **Signal decay:** for each signal the composite uses (and each proven daily data
  point), the recent IC vs the earlier record. An alert fires when the recent IC is
  negative or its t is below `decay_t_min`.
- **Data freshness:** the newest row in each source vs `freshness` limits. A stale
  source silently freezes the signals built on it.
- **Execution** (`python -m ddb.live.execution`): each Alpaca paper fill vs its
  arrival price (open of the first minute bar after the order), compared with the
  cost model for that order. If fills cost more than the model, every backtest and
  every "pays after costs" verdict is too optimistic.
