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

Every view has an **as-of date**: it shows only information that was public by
then, i.e. exactly what a model could see. Tabs:

- **Overview:** data coverage.
- **Universe & screens:** active vs tradable companies per industry over time;
  exclusions with reasons.
- **Industries:** filing language, news, research, attention, insider money, exits,
  regulation, contracts, congressional trades, committee leaders.
- **Company:** everything on one company: price, events, Sharia ratios,
  financials, insiders, Congress, contracts, news, filings language.
- **Model decisions:** each trade a model made, the factors behind it with their
  contributions, and the source and public date of every piece of evidence.
  Decisions whose evidence postdates the decision cannot be recorded
  (`ddb.decisions.DecisionLog`).

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
