# dolla-dolla-bills — System Design Plan

Status: v0.3 (Phase 1 in progress) · Last updated: 2026-11-22

A hierarchical system of models for trading a small, focused universe of volatile
high-growth stocks. It can rotate into a defensive "safe-haven" sleeve when those
industries crash. Only long positions (buy and sell), with realistic execution delay.

---

## 0. Guiding principles

1. **The data layer and execution simulator come first.** If a backtest can see the
   future, every result built on it is worthless.
2. **Supervised models at the bottom, RL for allocation at the top.** Market data has
   a low signal-to-noise ratio. RL from scratch overfits, so it is used only for
   allocation and sizing decisions.
3. **The LLM pulls facts out of documents. It does not predict.** A pretrained LLM has
   seen the future relative to any backtest before its training cutoff (see §6).
4. **Log every experiment.** With many generated strategies, some will look good by
   chance. Results are judged with multiple-testing-corrected metrics.
5. **Scale real capital in stages.** Each new tranche of money must be earned by live
   performance that matches the backtest.

---

## 1. Decisions so far

| Topic | Decision |
|---|---|
| Universe | 2 fixed core industries (**tech, energy**) + **2 rotating slots** from a candidate pool, plus a safe-haven sleeve |
| Instruments | Long-only stocks and ETFs. No shorting, options, or leverage |
| Data | **Free sources only** (EDGAR, FRED, Yahoo). The LLM fills context gaps and hunts for failures to offset survivorship bias (§4.5) |
| Objective | **Maximize 18-month growth**, measured on the distribution of rolling 18-month returns (§1.1) |
| Risk limit | No preset drawdown limit. A "model broken" breaker only (§1.1) |
| Capital | Paper first, then real money in stages, toward tens of thousands of USD |
| Compute (build/train) | University HPC cluster |
| Compute (live) | Cloud or on-prem, chosen from usage measured during paper trading (§9) |
| Broker | **Alpaca** for the experiment (free paper trading + API). Robinhood is the user's current broker (§9.3) |
| Repo | `hassan-edwan/dolla-dolla-bills` |

### 1.1 Objective: "whatever increases gain on an 18-month basis"
- Maximizing *expected* (average) 18-month gain pushes the optimizer toward putting
  everything into the single most volatile stock. It looks great on average and
  usually ends badly: a −50% loss needs +100% to recover.
- What compounds fastest over 18 months is **expected log growth** (the Kelly
  criterion). Log growth already punishes deep drawdowns, so no separate risk
  preference is needed.
- **Model selection** uses the *distribution* of rolling 18-month returns across
  walk-forward windows: the median, the 5th/25th percentile, and the % of windows
  that are positive. The single best backtest path is never used.
- **"Model broken" breaker.** This is not a risk preference. If the live drawdown
  exceeds the backtest's 99th-percentile drawdown, the model is behaving unlike
  anything it was tested on. Trading halts for review (`configs/sim.yaml`).

---

## 2. Universe design

### 2.1 Focus (trading) universe
- **Core (always on):** tech and energy, about 10 candidates each
  (`configs/universe.yaml`). Energy covers oil & gas E&Ps plus power/solar names.
- **Rotating (2 slots):** filled monthly from a pool: nuclear, quantum, space,
  crypto-adjacent, EV/battery, gene/biotech, robotics/AI. A slot can be swapped at
  most every 2 months, to avoid churn and wash sales. Phase 1–2 baselines use the
  core only. In Phase 3 the rotation selector comes first as a simple
  rule-based scorer (industry momentum + LLM trend score), and is replaced by the
  central allocator once that beats it.
- Every pool industry stays in the **training** universe even when it is not
  selected for trading.

**Liquidity filter:** average daily dollar volume above about $10M and price above
about $3. This keeps bid-ask spreads and market impact manageable for an account of
tens of thousands of dollars.

### 2.2 Defensive / safe-haven sleeve
The system cannot hold physical metal, so it uses ETFs backed by physical bullion,
plus cash-like instruments:

- Gold: physically backed gold ETFs (e.g. GLD / IAU class)
- Silver: physically backed silver ETF (e.g. SLV class)
- Cash proxy: 0–3 month T-bill ETFs (e.g. SGOV / BIL class)
- Optional: a defensive equity industry (utilities / staples ETF)

Gold is not a reliable crash hedge in every regime. In 2022, for example, T-bills were
the place to be, not gold. The allocator should learn which haven fits the current
regime, and the backtest must show that rotating beats simply holding T-bills.

### 2.3 Training universe vs. trading universe (important)
A single company has only about 2,500 daily bars per decade and about 40 earnings
reports. More compute does not create more data. So:

- **Train** signal models on a wider *training universe* of about 150–300 related
  stocks and ETFs: same industries, adjacent industries, and delisted names.
- **Trade** only the focus universe.
- Model structure: a **shared backbone + company embedding + small per-company
  heads**, so each company still gets a specialized model without overfitting.

### 2.4 Where the extra compute per company goes
This is where a small universe pays off. Each company gets *deep research* from the
LLM rather than a bigger price model:

- Full reads of each 10-K/10-Q, diffed against prior filings
- Earnings call transcripts: tone, guidance, and analyst-question themes
- Dilution watch: S-3 / 424B / ATM offering filings. These matter a lot for
  small-cap growth stocks.
- Insider transactions (Form 4), 13F changes
- Competitor and supply-chain mention graph
- Biotech: trial timelines and catalyst calendar

---

## 3. Architecture

```
                ┌──────────────────────────────────────┐
                │ CENTRAL ALLOCATOR (RL)  — weekly     │
                │ capital across: industries + havens  │
                │ inputs: regime probs, industry state │
                └───────────────┬──────────────────────┘
        ┌───────────────┬───────┴───────┬────────────────┐
  ┌─────▼─────┐   ┌─────▼─────┐   ┌─────▼─────┐   ┌──────▼──────┐
  │ Industry  │   │ Industry  │   │ Industry  │   │ Safe-haven  │
  │ mgr (RL)  │   │ mgr (RL)  │   │ mgr (RL)  │   │ mgr (rules/ │
  │ e.g. AI   │   │ e.g. Space│   │ e.g. Nucl.│   │ small RL)   │
  └─────┬─────┘   └─────┬─────┘   └─────┬─────┘   └─────────────┘
        └──── consume per-stock conviction scores ────┐
  ┌───────────────────────────────────────────────────▼─────────┐
  │ THESIS AGENTS (supervised), thesis × horizon grid            │
  │ momentum | mean-rev | value/quality | earnings drift |       │
  │ sentiment (LLM features) | dilution/insider | macro-regime   │
  │ × {daily, weekly, monthly}                                   │
  └──────────────────────────────────────────────────────────────┘
        ▲ features                                  ▲ new features/models
  ┌─────┴──────────────┐                 ┌──────────┴───────────┐
  │ RESEARCH LLM       │──hypotheses────▶│ MODEL FACTORY        │
  │ local, RAG + tools │   + code        │ sandbox → walk-fwd → │
  │                    │                 │ gate → registry      │
  └────────────────────┘                 └──────────────────────┘
        ▲
  ┌─────┴──────────────────────────────────────────────────────┐
  │ REGIME DETECTOR (HMM / changepoint) → crash probability     │
  │ POINT-IN-TIME DATA LAYER  +  EXECUTION SIMULATOR            │
  └────────────────────────────────────────────────────────────┘
        ▲
  ┌─────┴──────────────────────────────────────────────────────┐
  │ RISK OVERLAY (hard rules, cannot be overridden by models)   │
  └────────────────────────────────────────────────────────────┘
```

---

## 4. Foundation: data layer + execution simulator

### 4.1 Point-in-time data
- Every record has a `knowable_at` timestamp: filing acceptance time, not
  period end.
- Survivorship-free: include delisted and acquired companies in the training
  universe.
- Corporate actions: splits, reverse splits (common in volatile small caps), and
  ticker changes.
- Storage: Parquet files partitioned by date, queried with DuckDB / Polars.

### 4.2 Execution delay

| Horizon | Decide at | Fill at |
|---|---|---|
| Daily | close of day t | open of t+1, or t+1 VWAP; random jitter |
| Weekly | Friday close | Monday open / VWAP |
| Monthly | last trading day | next trading day |

### 4.3 Costs and frictions
- Half-spread cost, using wider spreads for small caps and around open and close
- Square-root market impact as a function of order size / average daily volume
- Partial fills and occasional missed fills on gap days
- Fractional shares allowed (if the broker supports them)

### 4.4 Account and regulatory constraints (model these explicitly)
- **Cash account settlement (T+1):** sale proceeds cannot be reused before settlement
  without good-faith violations. Simulate settled vs. unsettled cash.
- **Day-trading rules:** the pattern-day-trader rules for accounts under $25k have
  been under revision. Check the current FINRA rule and the broker's policy before
  going live. The daily horizon (decide at close, fill next open) avoids same-day
  round trips by design.
- **Wash-sale rule:** frequent rotation in and out of the same few names will trigger
  wash sales. Track them in the simulator.
- **Taxes:** short-term gains are taxed as ordinary income. Add an after-tax P&L view
  and a turnover penalty in rewards.

### 4.5 Free-data strategy and the failure hunt
Free price sources (Yahoo) mostly omit delisted companies, so a naive backtest only
sees survivors. Countermeasures:

1. **Failure ledger** (`data/failures/ledger.csv`, `src/ddb/data/failures.py`).
   Every delisting and deregistration from EDGAR's quarterly full index since 2012
   goes in it. Companies that still have a current ticker are excluded, because
   their Form 25s cover notes, warrants or exchange moves. The simulator settles any
   held position that stops trading at its ledger exit value:
   - bankruptcy → 0
   - forced delisting → 20% of last close
   - unknown → 50% (configurable)
2. **Universe event scan:** 8-K items (bankruptcy 1.03, delisting notice 3.01,
   unregistered equity sales 3.02, restatement 4.02, acquisition 2.01) and dilution
   filings (S-3, 424B5, S-1) for every candidate. These become warning features.
3. **LLM failure research (Phase 5):** for each delisted CIK in the training
   industries (selected by SIC code), the LLM reads the final 8-Ks / 10-Ks and records:
   - the historical ticker
   - what shareholders actually received (merger price, or 0)
   - early warning signs: going-concern language, repeated dilution, auditor
     changes, delisting notices

   This yields a labeled failure set, so models learn what failure looks like
   instead of only ever seeing winners.
4. **Price cross-checks:** where free sources overlap (Yahoo vs. Alpaca free
   historical bars vs. Stooq), flag mismatches before training.
5. **Macro:** only unrevised market series from FRED (rates, spreads, VIX, oil, gas).
   Revised series (GDP, CPI, payrolls) must come from ALFRED vintages. FRED now
   serves only 3 years of ICE high-yield spreads (BAMLH0A0HYM2). For longer history,
   use a price-based proxy instead (HYG vs. IEF total-return ratio).
6. **Hindsight in the universe itself (the biggest bias right now).** The
   candidate tickers in `configs/universe.yaml` were picked in 2026, by people who
   already know NVDA, PLTR and VST won. Any backtest of that list since 2015 is
   inflated, including the baselines. The fix is a **rule-based, point-in-time
   universe**: at each rebalance date, choose names from the training universe by
   SIC code, liquidity and trailing growth, using only data knowable then. The
   hand-picked list is for plumbing tests only.

### 4.6 Baselines (everything must beat these after costs)
1. Buy-and-hold equal-weight focus universe
2. Buy-and-hold industry ETFs
3. QQQ / SPY buy-and-hold
4. Simple 12-1 momentum within the universe
5. Simple trend filter: hold the universe when above its 200-day moving average,
   otherwise T-bills. **This is the key baseline for the defensive-rotation idea.**

---

## 5. Model layers

### 5.1 Thesis agents (supervised)
- Output: a conviction score from −1 to 1 plus a confidence value, per stock,
  per horizon.
- Target: forward return relative to the industry, at each horizon.
- Models: start with LightGBM, then temporal CNN / small transformer with company
  embeddings.
- Population management: track each agent's rolling information coefficient (IC).
  Retire agents that decay and spawn variants of agents that work.

### 5.2 Regime detector
- Inputs: industry index returns/volatility, VIX, credit spreads, breadth, rates, and
  dollar strength.
- Models: Gaussian HMM, Bayesian changepoint detection, and a simple drawdown/trend
  rule as a sanity check.
- Output: `P(crash regime)` and `P(risk-on)` fed to the central allocator.

### 5.3 Industry managers (RL)
- State: agent scores and track records, industry momentum/volatility, holdings, and
  settled cash.
- Action: target weights over the industry's names, as discrete buckets.
- Reward: industry-relative return − turnover cost − volatility penalty.
- Algorithm: PPO (try SAC as an alternative). Train against frozen thesis agents.

### 5.4 Central allocator (RL)
- State: regime probabilities, industry-level features, LLM industry-trend briefs,
  manager track records, and portfolio drawdown.
- Action: allocation across industries + safe-haven sleeve.
- Reward: differential Sharpe, or log return − λ·drawdown − costs − tax drag.
- **Hysteresis:** require the signal to persist before switching between risk-on and
  risk-off. Whipsawing is expensive with taxes and wash sales.
- Simpler baseline to beat: a contextual bandit, and the trend-filter rule (§4.6 #5).

### 5.5 Risk overlay (hard rules, outside all models)
- Max 15% per name, max 50% per industry (tunable)
- Portfolio drawdown circuit breaker → forced move to T-bills, then human review
- Daily loss limit, max orders per day, and a check for stale data
- A live kill switch

---

## 6. Research LLM

**Two roles, at different times:**
- **Now (database building):** the LLM is a *research assistant for building the
  training database*. It looks up information the free sources miss:
  - which companies belong to each industry, especially ones the SEC codes miss
  - failed and delisted companies
  - historical tickers
  - how each listing ended

  Every fact is stored with its source URL, a confidence level and the date it
  refers to (`docs/DATABASE.md`). It does **not** generate features or make
  decisions yet.
- **Later (once the system is in use):** feature extraction and lookups, as
  described below.

- **Model:** a local 14–32B open-weights model (Qwen / Llama class), 4-bit quantized,
  served with vLLM or llama.cpp.
- **Tools:** retrieval (RAG) over SEC EDGAR filings and transcripts, news, FRED, and a
  Python sandbox.
- **Outputs are structured features only:**
  - sentiment and tone scores
  - guidance delta
  - new-risk-factor flags
  - dilution-risk flags
  - industry trend briefs

### 6.1 Preventing lookahead leakage
- Anonymize inputs: replace company names, tickers, and dates with placeholders.
- Restrict the LLM to *local extraction* ("what does this filing say").
  Never ask it to forecast.
- Treat backtest gains from LLM features before the model's training cutoff as
  suspect. Real validation happens on periods after the cutoff, and in paper trading.
- Run every backtest with and without LLM features. If the LLM adds a large gain
  only on pre-cutoff periods, assume it is leaking.

---

## 7. Model factory (LLM-generated models)

Loop:

1. The LLM proposes a hypothesis, e.g. "ATM offering filings predict 20-day
   underperformance in small-cap space stocks."
2. The LLM writes the feature and model code (ARIMA, GARCH, regressions, logistic,
   LightGBM, cointegration, HMM, …).
3. The code runs in a sandbox: Apptainer on HPC, Docker elsewhere. No network
   access, read-only data.
4. Walk-forward evaluation on purged + embargoed folds.
5. **Gate:**
   - out-of-sample IC above a threshold
   - **deflated Sharpe ratio**, corrected for the total trial count
   - low correlation with existing features
   - stable across regimes
6. Passing models go to the registry (MLflow) and become features or new thesis
   agents.
7. **Every trial is logged, including failures.** The trial count feeds the
   deflated-Sharpe correction.

---

## 8. Validation protocol

- Purged + embargoed walk-forward CV (López de Prado).
- **Locked holdout:** keep the most recent 18–24 months untouched until the final
  evaluation, and evaluate on it once.
- Stress periods to check explicitly: 2018 Q4, 2020 Mar, 2021–22 growth crash,
  2023 regional banks, and any 2024–26 drawdowns.
- **Paper trading for 3–6 months** before real money.

### 8.1 Staged capital deployment

| Stage | Capital | Gate to advance |
|---|---|---|
| Paper | $0 | 3+ months; live metrics within backtest confidence band |
| Live 1 | ~$1–2k | 3 months; no rule breaches; slippage ≈ simulated |
| Live 2 | ~$5–10k | 3–6 months; drawdown within limits |
| Live 3 | tens of thousands | Sustained risk-adjusted outperformance vs. baselines |

If a stage fails, capital drops back one stage and the run gets a post-mortem.

---

## 9. Compute strategy

### 9.1 Now: university HPC (build + train)
- **Check the university's acceptable-use policy first.** Many forbid using research
  compute for personal financial gain. Keep HPC work framed and used as research
  (models, backtests, papers), and keep live trading off university resources.
- Use Slurm job scripts and Apptainer containers so everything ports cleanly to
  cloud or on-prem later.
- Keep all code, configs, and model artifacts in this repo or in artifact storage
  you own, not only on the cluster. You will lose access eventually.

### 9.2 Later: live trading (inference + periodic retraining)
Live trading needs much less compute than training:

- **Daily pipeline:** data pull, features, LightGBM, and RL policy inference.
  About minutes of CPU time.
- **LLM research:** about 30 companies' new filings and news per day. Roughly
  0.5–2 GPU-hours/day on a 24GB-class card (estimate; measure during paper trading).
- **Retraining:** weekly or monthly. Bursty GPU use.

Options to compare, using usage measured during paper trading:

1. **Small VPS + on-demand cloud GPU by the hour.** Lowest upfront cost; pay as you go.
2. **Home box with a 24GB-class GPU.** One-time hardware cost plus power. Wins if
   GPU use is high every day.
3. **Hosted LLM API for the research step** + VPS for everything else. No GPU to
   manage, but per-token cost and data leaves your machine.

Decision rule: total the measured monthly GPU-hours × cloud rate over 24–36 months
and compare against hardware + power. Revisit after Phase 7.

### 9.3 Broker / execution
- **Alpaca for the experiment:**
  - free paper-trading account with the same API as live trading
  - commission-free US stocks and ETFs
  - fractional shares
  - free historical bars, usable for cross-checking Yahoo
- Robinhood (the user's current broker): fine for comparison and manual review.
  Confirm it offers a supported equities trading API before building automated
  execution on it.
- At first, every live order goes through a review step. Fully automated orders come
  only after Live 1.
- The simulator models a **cash account** (T+1 settlement, good-faith rule), so
  pattern-day-trader margin rules don't apply.

---

## 10. Roadmap

| Phase | Deliverable | Rough time |
|---|---|---|
| 1 | Repo scaffold, point-in-time data layer, execution simulator (§4), baselines | ✅ done |
| 1b | **Company database** (`docs/DATABASE.md`, research tracks in `docs/RESEARCH_TRACKS.md`): every company ever in the target industries, incl. failures; filings, events, financials, prices, outcome labels; LLM-researched seeds (`docs/DATABASE.md`) | 🔄 in progress |
| 2 | Thesis agents (supervised) + population manager | 3–4 wks |
| 3 | Regime detector + single-level RL allocator (focus + haven) | 2–3 wks |
| 4 | Full hierarchy: industry managers + central allocator + risk overlay | 3–4 wks |
| 5 | Local LLM feature extraction with anonymization (§6) | 3 wks |
| 6 | Model factory with gating (§7) | 3–4 wks |
| 7 | Paper trading, monitoring dashboard, compute usage measurement | 3–6 months |
| 8 | Staged live capital (§8.1) | ongoing |

---

## 11. Proposed repo layout

```
dolla-dolla-bills/
  docs/                 PLAN.md, decision records
  configs/              universe, costs, risk limits, experiment configs
  src/ddb/
    data/               ingestion, point-in-time store, corporate actions
    sim/                execution simulator, account/tax/settlement model
    agents/             thesis agents (supervised)
    regime/             regime detection
    rl/                 gym envs, industry managers, central allocator
    llm/                local LLM serving, RAG, feature extraction, anonymizer
    factory/            hypothesis → code → sandbox → evaluation → registry
    risk/               hard-rule overlay, kill switch
    live/               broker adapters, scheduler, monitoring
  hpc/                  Slurm scripts, Apptainer definitions
  tests/
```

---

## 12. Phase 1 status

Done:
- [x] Repo scaffold, configs (`configs/universe.yaml`, `configs/sim.yaml`)
- [x] Point-in-time store with restatement handling (`src/ddb/data/store.py`)
- [x] Free data sources:
  - Yahoo daily prices + dividends/splits
  - FRED market series
  - EDGAR form index, submissions, XBRL company facts
- [x] Failure ledger + EDGAR exit/8-K/dilution scan (`scripts/scan_failures.py`)
- [x] Execution simulator (`src/ddb/sim/`):
  - next-day fills with jitter
  - tiered spread + square-root impact + participation cap
  - cash account: T+1 settlement, good-faith rule, FIFO lots, wash sales, tax estimate
  - delisting exits
- [x] Baselines + 18-month metrics (`scripts/run_baselines.py`)

Phase 1 baseline scoreboard (2015-01 → 2026-11, $10k, after costs and taxes paid each
January; **hand-picked, hindsight-biased universe, so plumbing check only**):

| Strategy | CAGR | Max DD | Median 18m | 5th pct 18m | Taxes paid |
|---|---|---|---|---|---|
| SPY buy & hold | 11.7% | −31% | +24% | −5% | $0 |
| QQQ buy & hold | 16.5% | −34% | +33% | −14% | $0 |
| Focus EW buy & hold | 34.0% | −50% | +74% | +5% | $0 |
| Focus EW monthly rebalance | 26.8% | −52% | +50% | −8% | $21k |
| Focus trend → T-bills | 21.0% | −40% | +43% | −23% | $15k |
| Focus 12-1 momentum, top 5 | 44.2% | −39% | +94% | +16% | $157k |

Early observations:
- Rebalancing and rotation lose to buy-and-hold mostly because of short-term taxes
  and wash sales. Turnover has a real cost.
- The 200-day trend filter cut drawdown, but its worst 18-month windows were
  worse: it whipsawed out and missed the rebounds.

Next:
- [ ] **Rule-based point-in-time universe selection** (removes the hindsight bias above)
- [ ] Training universe from EDGAR SIC codes, including delisted CIKs
- [ ] Historical ticker resolution for delisted CIKs
- [ ] XBRL fundamentals ingestion into the PIT store for the training universe
- [ ] Walk-forward / purged CV harness (needed before Phase 2)
- [ ] Price cross-check against a second free source
- [ ] HPC: Slurm + Apptainer definitions

## 13. Open questions
1. Seed list for the rotating pool. The initial pool is in `configs/universe.yaml`.
   Edit freely.
2. Check the university HPC acceptable-use policy before training trading models on
   it.
