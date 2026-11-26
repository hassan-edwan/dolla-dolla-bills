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

Signals and short-term data points come first (each step reads the database):

```bash
.venv/bin/python -m ddb.features.panel      # monthly signal panel
.venv/bin/python -m ddb.features.validate   # monthly tests + walk-forward composite
.venv/bin/python -m ddb.features.daily      # next-day / 5-day data points, tested after costs
# optional, intraday (free Alpaca key; ~1 minute per symbol-year of 1-minute bars):
.venv/bin/python -m ddb.db.build_intraday --max-symbols 100
.venv/bin/python -m ddb.features.intraday   # 1/5/15-minute and hourly data points, tested after costs
```

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
  (scorecards, IC over time, quintiles, costs, time of day), universe & screens,
  data sources.

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
| `src/ddb/features/` | Monthly panel + validation; `bars.py` (bar features, after-cost tests), `daily.py`, `intraday.py` |
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
