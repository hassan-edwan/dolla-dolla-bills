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

## Model-ready store (`python -m ddb.store.build`)

One company list (`ids.npy`, 2,879 companies) shared by every block, memory-mapped,
so nothing loads until it is indexed:

```python
from ddb.store import Store
st = Store()
st.month.X[t, :, :]   # raw signals [month, company, signal]
st.month.R[t, :, :]   # sign-adjusted percentile in [-0.5, 0.5] (0.5 = most favorable)
st.month.y[t, :, 0]   # next-month return (label: never an input)
st.month.liquid, st.month.tradable          # universe masks
st.day.X, st.day.mask, st.day.y, st.day.cost # daily data points, same layout
idx = st.split_index("month", "train", horizon_days=31)   # purged
st.events.batch_before(ciks, t, k=32)        # each company's last 32 events public by t
```

The event index holds 1.3M dated facts (filing events, risk phrases, insider trades,
results reports), sorted by company and public time, for attention-style models.
Building the daily block needs `python -m ddb.features.daily` first (it writes the
full daily history).

## Fast environment (`ddb.rl.fast.FastAllocatorEnv`)

Same observation, action and reward as `AllocatorEnv`, from precomputed weekly asset
returns (dividends, exits settled by how each listing ended), costs and sleeve churn;
B episodes stepped at once. About 450,000+ steps/s vs ~26 for the full backtester.
Train here, evaluate the final policy in `AllocatorEnv`.

Agreement with the full backtester on the real data (total return, same strategy):

| Period | Strategy | Full | Fast |
|---|---|---|---|
| 2022-23 | equal industry sleeves | +15.8% | +15.0% |
| 2022-23 | T-bills | +4.3% | +4.4% |
| 2022-23 | 60% industries / 40% haven | +13.4% | +11.8% |
| 2016-21 | equal industry sleeves | +58.9% | +50.2% |
| 2016-21 | T-bills | +3.3% | +3.3% |

The fast env runs ~1-1.5 points a year low on equities, mostly from its simpler tax
(all short-term, average cost) vs the backtester's FIFO lots with long-term rates.
"Hold" (NaN action) keeps the allocation while sleeves still refresh their names, so
the backtester's frozen buy-and-hold has no exact counterpart.

## Decision explanations and reviewers (`python -m ddb.rl.explain`)

For every Nth decision of a policy (`--policy regime_rule --split validation --every 4`):

- **Attribution:** for each input group (market regime, each industry, gold, T-bills,
  current holdings), set it to normal and ask the policy again; the change in each
  weight is that group's contribution. Works for any policy `obs -> weights`.
- **Report** (`data/db/rl/reports/<policy>_<split>/<date>.json` + `.png`):
  - a clear version for people;
  - an anonymized version for an LLM: sectors renamed "Sector A..", no dates or
    names, standardized values only.
  - Absolute macro levels (rates, yield curve, credit spread and VIX levels, 24-month
    return) are left out because they date a report.

  Each decision is also recorded in the decision log (Model decisions page), with
  its attribution as factors and the no-hindsight check.
- **Rule reviewer** (`ddb.rl.review.RuleReviewer`, always on), flags:
  - concentration;
  - sectors bought in a stress regime;
  - turnover;
  - implausible recent returns (bad data);
  - adding to a collapsing sector.
- **LLM reviewer** (`LLMReviewer`, `--llm`): any OpenAI-compatible endpoint (vLLM,
  llama.cpp server), configured in `configs/review.yaml`.
  - It returns a verdict (approve / review / block), 1–5 scores and flags, plus a
    plain-language justification.
  - An unreachable or broken reviewer yields "review", never "approve".
- **Reviewers monitor; they are not a training reward.** A policy trained to please a
  reviewer learns to sound right, not to make money.
- **Trust LLM ratings only on decisions after the model's training cutoff.** Even
  anonymized, market patterns can hint at the era, and the LLM knows what happened next.
- **Measure a reviewer before trusting it:** `review.evaluate(reviewer, reports)`
  plants faults (concentration, stress buying, an implausible return, buying a
  collapsing sector) and counts detections and false alarms.

On 2022-23 decisions of the regime and trend baselines, the rule reviewer:
- caught 100% of each planted fault;
- flagged 1–2 in 25 real decisions, all genuine 100–200% turnover swings when the
  regime flipped.

The industry-momentum baseline is flagged at every decision, correctly: it puts 50%
in each of two sectors.

The LLM reviewer is not measured yet. Serve the PLAN.md §6 local model, set
`configs/review.yaml`, then run `evaluate(LLMReviewer(), reports)`.
