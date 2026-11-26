# dolla-dolla-bills

A hierarchical ML/RL research system for trading a small universe of volatile,
high-growth stocks: tech and energy plus 2 rotating industries. It can rotate into
a defensive safe-haven sleeve (gold, silver, T-bills) during crashes. Only long
positions (buy and sell), with realistic execution delay, costs, cash-account
settlement and taxes. Uses free data only.

**Status:** Phase 1 (data layer + execution simulator + baselines). See
[`docs/PLAN.md`](docs/PLAN.md) for the full design, roadmap and current results.

> This is a research project. Nothing here is financial advice. Real capital is
> deployed only in stages, after paper trading validates the system.

## Quickstart

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -q

# Free data (cached under data/, git-ignored)
.venv/bin/python scripts/fetch_prices.py --start 2012-01-01
.venv/bin/python scripts/fetch_macro.py
export DDB_SEC_USER_AGENT="dolla-dolla-bills your-email@example.com"   # SEC requires contact info
.venv/bin/python scripts/scan_failures.py --years 2012 2026

# Baseline scoreboard
.venv/bin/python scripts/run_baselines.py --start 2015-01-01
```

## Dashboard

```bash
.venv/bin/pip install -e ".[dev]" fastapi uvicorn
.venv/bin/python -m ddb.app.api              # http://127.0.0.1:8050
.venv/bin/python scripts/export_dashboard.py # one-file snapshot -> data/results/dashboard.html
```

Build everything, in order, then check whether the data is ready for training:

```bash
export DDB_SEC_USER_AGENT="dolla-dolla-bills you@example.com"   # SEC requires contact info
python scripts/build_all.py --download   # first run (SEC bulk files ~3 GB); later runs without --download
python scripts/build_all.py --full       # also 13F, minute bars, spreads, congress, contracts, news (slow)
python scripts/build_all.py --list       # the steps; --from <step> resumes
python -m ddb.rl.readiness               # READY / NOT READY, with the fix for each blocker
```

Alpaca steps (delisted prices, minute bars, spreads, paper fills) need a free key
in `~/.config/ddb/alpaca.env`. Run `python -m ddb.live.tracking` after every update.

Every view has an **as-of date**: it shows only information that was public by
then, i.e. exactly what a model could see. The tabs follow the decision, not the
data source:

- **This month:** buy candidates (pass every screen, top 20% on the walk-forward
  composite, no red flags) with the signals behind each; names to avoid (red
  flags from signals that predicted losers); what changed since last month-end;
  every screened company scored on the questions *Is it a real business? Is the
  market confirming it? Who is buying and watching?* plus the red-flag questions
  *Could it fail or dilute? Is it a lottery ticket?* (`configs/signals.yaml`).
- **Today:** short-term setups for the next open, alerts from the last few days
  (earnings reaction, offering or distress filing, insider buying, gaps, volume
  and news spikes), each data point's edge **after trading costs**, daily range for
  stops, and the intraday (minute/hour) results. If the short-term composite does
  not beat costs, the page says so.
- **Portfolio:** what the model would hold: position sizes (by volatility, with caps
  per name, industry and group of names that move together, scaled to a volatility
  target), cash, expected volatility, beta, effective number of independent bets,
  correlated groups, industry and style exposure, expected return before and after
  costs and tax, upcoming earnings, and the backtest's drawdown vs the "model broken"
  line (`docs/RISK.md`).
- **Market:** the regime (calm / caution / stress) from VIX, credit spreads, the
  yield curve, trend and breadth, momentum-crash risk, and how the model has done in
  each regime. A one-line regime and data-health summary sits on every page.
- **Company:** the monthly verdict by question and the short-term picture first,
  then the evidence: price, events, Sharia ratios, financials, insiders, Congress,
  contracts, news, filings language.
- **Industries:** candidates, red flags and median scores per industry; the
  per-source background (news, research, regulation, ...) is collapsed.
- **Model decisions:** each trade a model made, the factors behind it with their
  contributions, and the source and public date of every piece of evidence.
  Decisions whose evidence postdates the decision cannot be recorded
  (`ddb.decisions.DecisionLog`).
- **Model lab:** how every monthly, daily and intraday data point was tested
  (scorecards, IC over time, quintiles, costs, time of day); track record (live
  forecast log, walk-forward record, signal decay); execution quality (fills vs
  the cost model); data health; universe & screens; data sources.

"Hindsight labels" (how a listing ended) are hidden unless switched on.

## Layout

| Path | What |
|---|---|
| `configs/universe.yaml` | Core / rotating / safe-haven / benchmark tickers, training-universe SIC codes |
| `configs/sim.yaml` | Execution delay, cost model, account rules, taxes, delisting policy |
| `src/ddb/data/` | Point-in-time store, Yahoo prices, FRED, SEC EDGAR, failure ledger |
| `src/ddb/sim/` | Cost model, cash account (T+1, good-faith, FIFO lots, wash sales), backtest engine |
| `src/ddb/strategies/` | Baselines every learned strategy must beat |
| `src/ddb/metrics.py` | Rolling 18-month return distribution and drawdown metrics |
| `src/ddb/db/` | Company database builders, point-in-time API (`pit.py`), screens |
| `configs/short_term.yaml` | Daily and intraday data points, horizons, bar sizes, intraday download scope |
| `src/ddb/features/` | Monthly panel + validation; `bars.py` (bar features, after-cost tests), `daily.py`, `intraday.py`, `regime.py`, `calendar.py` (expected earnings dates) |
| `configs/risk.yaml` | Regime thresholds, portfolio sizing, decay and freshness alerts |
| `src/ddb/portfolio/` | Sizing and risk (`sizing.py`), model portfolio + backtest (`model.py`) |
| `src/ddb/live/` | Forecast log, signal decay, data freshness (`tracking.py`); fills vs cost model (`execution.py`) |
| `configs/rl.yaml` | Train / validation / test periods, RL dataset + environment, readiness thresholds |
| `src/ddb/rl/` | Splits (`splits.py`), observation dataset (`dataset.py`), allocator environment (`env.py`), baselines, readiness report |
| `src/ddb/news/` | News pipeline: GDELT, filing-text signals, Wikipedia attention, arXiv |
| `src/ddb/app/` | Dashboard: API (`api.py`), queries, static frontend |
| `src/ddb/decisions.py` | Decision record format every model must write (explainability + no-hindsight check) |
| `scripts/` | Data fetch, failure scan, baselines, `build_database.py`, `demo_decisions.py`, `export_dashboard.py` |

## Simulator guarantees (tested)

- Decisions at the close of day t fill at day t+1 (open, with optional jitter). A
  strategy can never see bar t+1.
- Long-only, with no leverage (enforced).
- Spread by liquidity tier, square-root market impact, and a 1% ADV participation cap.
- Cash account: T+1 settlement, good-faith rule, FIFO tax lots, wash sales.
  Last year's taxes are paid each January.
- A held stock that stops trading is settled at its failure-ledger exit value, not
  silently dropped.
