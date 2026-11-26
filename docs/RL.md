# Reinforcement learning: data, environment, baselines

Settings: `configs/rl.yaml`.

## Before training: is the data ready?

```bash
python scripts/build_all.py        # builds everything in order (see --list)
python -m ddb.rl.readiness         # READY / NOT READY; writes data/db/rl/readiness.{md,json}
```

The report blocks training until the following hold (thresholds in `readiness`):

- every required build output exists;
- at least 300 liquid tracked-industry stocks have prices in each of 8+ years;
- at least 25% of the companies that failed or delisted since the train start
  have prices (otherwise models learn that risky stocks always survive);
- core signals are at most 35% missing;
- 60+ months of out-of-sample composite history;
- regime inputs cover 95% of days;
- **zero** rows public before they could have been;
- clean prices (no zero prices, no impossible jumps, no duplicate bars);
- core sources are current;
- the RL dataset has enough weekly decisions in each split.

Each failed check comes with the command that fixes it. The Data health page in the
Model lab shows the same checklist.

## Splits (`ddb.rl.splits`)

Default periods:

| Period | Dates |
|---|---|
| train | 2016-01 → 2021-12 |
| validation | 2022-01 → 2023-12 |
| test | 2024-01 → today |

- **2016 start:** Alpaca prices for delisted companies start then, so earlier
  years mostly contain survivors.
- **Embargo:** 35 days at the start of validation and test.
- **Purge:** `purge(dates, horizon)` drops training samples whose label window
  reaches the next period.
- **Locked test period:** opening it needs `allow_test=True`, and every opening is
  logged. Use it once, for the final evaluation.

## Observation dataset (`python -m ddb.rl.dataset`)

Weekly decisions (last trading day of each week). Assets: one sleeve per tracked
industry, plus gold and T-bills; the rest is cash.

**Sleeves:** an industry sleeve is that industry's current buy candidates, the top
5 by composite, weighted by inverse volatility. It is refreshed at each month-end.

**Features**, all public at the decision close:

- market regime;
- per industry: 4/12/26-week return, volatility, trend, breadth, number and score
  of buy candidates, median score;
- gold and T-bill trends;
- the 3-month T-bill yield.

Features are standardized with train-period statistics only.

## Environment (`ddb.rl.env.AllocatorEnv`)

```python
from ddb.rl.env import AllocatorEnv
env = AllocatorEnv(split="train", seed=0)          # random 1-year episodes
obs, info = env.reset()
obs, reward, terminated, truncated, info = env.step(weights)   # one weight per env.assets; None = hold
```

- **Execution:** the real backtester (`Backtester.iterate`). Fills at the next
  open, spread + impact costs, T+1 settlement, good-faith rule, wash sales, yearly
  taxes. Tax still owed at the end of an episode is charged then.
- **Reward:** log return − 0.5 × how much deeper the drawdown got − optional
  turnover penalty.
- **Observation:** standardized features, a missing-value mask, current asset
  weights, cash and drawdown.
- **Gymnasium:** `observation_space` / `action_space` are set when gymnasium is
  installed; otherwise use plain reset/step.

## Baselines (`python -m ddb.rl.baselines --split validation`)

A learned policy must beat each of these on validation, after costs and taxes:

- equal industries (rebalanced weekly);
- buy and hold;
- T-bills only;
- the 200-day trend filter;
- a regime rule (stress → haven);
- industry momentum (best 2 industries by 12-week return).

`evaluate(policy, split)` runs any policy (a callable `(obs, env) -> weights`)
through the same environment.
