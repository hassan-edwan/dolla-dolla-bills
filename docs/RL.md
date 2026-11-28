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

## Point in time: what the model sees is what it could have seen

Every input is built as it would have looked at the decision time (the close, 21:30 UTC).

**Time-travel test** (`python -m ddb.rl.pit_audit --reference stored`):
1. Copy the database keeping only rows public by a past date (each row's `knowable_at`).
2. Rebuild all monthly signals from that copy.
3. Check that the past date's signals match the stored ones exactly.

It runs at three dates: 2018-06, 2021-03 and 2024-09. Readiness blocks if any value differs.

The first run found four problems. All are fixed:

| Problem | Effect | Fix |
|---|---|---|
| Several revenue or share-count tags in one filing were picked by an unstable sort | values depended on unrelated data; a preferred tag published later could displace one known earlier | earliest known wins, then a fixed preference order (`panel.prefer`) |
| Earnings-surprise history used every quarter ever reported | a quarter first published later could change an older surprise | each surprise uses only quarters published by then |
| Short interest matched by today's ticker | data under an old ticker was lost; a reused ticker could match the wrong company | matched to the company trading under that ticker that month (`panel.ticker_cik`) |
| Rows existed for companies before their first trade | the row itself revealed a future listing | a company enters the panel once it has a price |

**Scaling:**
- RL observations: expanding mean and standard deviation.
- Store: `Store.normalize_pit` uses the expanding cross-sectional median and IQR.
- `Store.normalize` (train-period statistics) is kept for convenience; it is not point in time.

**Trading costs:** the measured bid-ask spread for a company (`ddb.db.build_spreads`, from 2016) is used from the month after it was measured, for at most 100 days. Where there is none, the spread is estimated from trading volume. This applies in the backtester, the daily cost model and the fast environment.

**Known caveats:**
- **Identity screens:** company addresses, industry codes and names are as of today, with no history kept. They exclude about 3% of liquid company-months.
- **Research-written industry tags:** these are written today about the past. Strict mode turns them off: set `exclude_tag_methods: [research]` in `configs/signals.yaml`. A test showed it barely matters (composite IC 0.062 → 0.056).

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

Features are standardized point in time: each week uses the mean and standard
deviation of earlier weeks only (expanding window, at least 26 weeks), so no
observation is scaled with statistics from its own future.

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

## Allocator training, first round (`python -m ddb.rl.alloc`)

- **Objective:** after-tax growth, with taxes on.
- **Training:** the fast environment.
- **Scoring:** the full backtester.
- **Model selection:** walk-forward folds inside training (fit 2016…Y−1, test on year Y, for Y = 2019, 2020, 2021).
- **Validation:** one logged look (`data/db/rl/alloc/validation_looks.log`).

| Policy | Folds: log growth per year | Folds: avg max drawdown | Validation 2022–23: return per year | Validation: max drawdown |
|---|---|---|---|---|
| Equal weight (sleeves with names) | 13.5% | −17.5% | **11.2%** | −20.6% |
| ES tilt around equal weight, 15% band | 14.7% | −17.7% | 3.2% (seeds 1.4–3.9%) | −26.9% |
| ES free scorer (v2) | 22.1% | −24.0% | −8.8% (seeds −6.8 to −8.1%) | −27.4% |
| Predict-then-optimize | 10.2% | −15.6% | not taken to validation | |
| Volatility-scaled equal weight | 8.1% | −12.2% | not taken to validation | |

**Result: nothing learned beats equal weight out of sample.**
- The free scorer learns all-in sector bets: in 2020 it put 100% into energy.
- The bounded tilt learned to buy the industries that fell over the last 26 weeks (coefficient −1.8). In 2022 that kept it out of energy, which was the year's winner.
- Three fold years and 313 training weeks are not enough to learn rotation between 9 industries.

**Lessons now built into the code:**
- Fold scores must come from the full backtester. The fast and full environments time weeks differently (open-to-open vs close), which adds about ±5 points of noise to a single year, though it averages out over the whole period.
- "Hold" inside a no-trade band must keep the sleeve weights and still refresh each sleeve's names. Passing no action instead freezes the stocks, which is a different policy (buy-and-hold).
- A policy needs a hard limit on concentration.

**Next levers:**
1. More training data for the shared scorer: train it on every industry with listed stocks, not just the 9 tracked ones.
2. Improve the stock-picking layer.
3. Tax-aware holding inside each sleeve: refresh less often and wait for long-term rates.
