# dolla-dolla-bills — System Design Plan

Status: draft v0.2 · Last updated: 2026-11-22

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
| Universe | Small focus set of volatile, high-growth industries, plus a defensive sleeve |
| Instruments | Long-only stocks and ETFs. No shorting, options, or leverage |
| Capital | Paper first, then real money in stages, toward tens of thousands of USD |
| Compute (build/train) | University HPC cluster |
| Compute (live) | Cloud or on-prem, chosen from usage measured during paper trading (§9) |
| Repo | `hassan-edwan/dolla-dolla-bills` |

---

## 2. Universe design

### 2.1 Focus (trading) universe — about 15–30 names
Pick **2–4 volatile, high-growth industries** with about 5–10 liquid names each.
Candidates (to be decided):

- AI / semiconductors (compute, memory, networking)
- Quantum computing
- Space / launch / satellite
- Nuclear / SMR / uranium
- Clinical-stage biotech (warning: binary FDA events)
- EV / batteries / energy storage
- Crypto-adjacent equities (miners, exchanges)

**Liquidity filter:** average daily dollar volume above about $5–10M and price above
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

### 4.5 Baselines (everything must beat these after costs)
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
- Simpler baseline to beat: a contextual bandit, and the trend-filter rule (§4.5 #5).

### 5.5 Risk overlay (hard rules, outside all models)
- Max 15% per name, max 50% per industry (tunable)
- Portfolio drawdown circuit breaker → forced move to T-bills, then human review
- Daily loss limit, max orders per day, and a check for stale data
- A live kill switch

---

## 6. Research LLM

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
- Pick a broker with a documented programmatic equities API and a paper-trading
  account (e.g. Alpaca or Interactive Brokers). Check whether your current broker
  supports automated equity orders before relying on it.
- At first, every live order goes through a review step. Fully automated orders come
  only after Live 1.

---

## 10. Roadmap

| Phase | Deliverable | Rough time |
|---|---|---|
| 1 | Repo scaffold, point-in-time data layer, execution simulator (§4), baselines | 3–5 wks |
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

## 12. Open questions

1. Which 2–4 industries? (Pick by liquidity, data history, and how much you know
   about the domain.)
2. Data budget: free sources (EDGAR, FRED, yfinance for prototyping only) vs. a paid
   survivorship-free source (Norgate / Sharadar / Polygon class)?
3. Which broker for paper and live trading?
4. Acceptable max drawdown for the live account (e.g. 25%? 35%?). This sets the
   circuit breaker and the reward's λ.
