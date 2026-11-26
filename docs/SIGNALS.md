# Predictive signals

Which data actually predicts returns in our universe, and how the dashboard uses it.
The literature review is in [`reports/Predictive signals for growth stocks.md`](../reports/Predictive%20signals%20for%20growth%20stocks.md).

## Method

- **Panel** (`python -m ddb.features.panel`): every month-end since 2011, each company
  active in a tracked industry, with each signal in `configs/signals.yaml`.
  - Inputs use only information public at that moment.
  - Financial facts use their first-published version.
  - Short interest is dated by FINRA publication.
- **Targets:** next 1- and 3-month returns. A stock that stops trading because it
  failed takes a -30% delisting return (Shumway) instead of being dropped.
- **Validation** (`python -m ddb.features.validate`), within the liquid universe
  (price >= $2, 20d $volume >= $1M):
  - monthly rank IC against next-month returns, t-statistic and hit rate;
  - quintile returns, the long leg (top quintile minus the universe average,
    which is what a long-only account can earn) and turnover;
  - 2012–2019 and 2020+ separately.
  - Status: **predictive** needs t ≥ 3 and a positive IC in both periods;
    **moderate** needs t ≥ 2 and positive in both.
- **Composite:** walk-forward. Each month it averages the industry-neutral,
  winsorized z-scores of the signals that had t ≥ 2 on earlier months only, so its
  track record is out-of-sample.
- **Dashboard** (organized by decision, not by data source):
  - Each signal answers one question (`question` in `configs/signals.yaml`):
    *Is it a real business? Is the market confirming it? Who is buying and
    watching?* and the red-flag questions *Could it fail or dilute? Is it a
    lottery ticket?* A company's score on a question is the average percentile of
    that question's signals the composite used that month (so only proven ones).
  - Verdict: **buy candidate** = top 20% on the composite and no red flag;
    **avoid** = a red flag; otherwise hold (40-80) or weak.
  - Red flags come only from avoid signals that predicted losers (predictive or
    moderate): worst 10% (5% for going-concern / late filings).
  - "What changed": names that entered or left the top 20% since the previous
    month-end, and new red flags.
  - Panels whose data did not predict are hidden unless "unvalidated context" is on.

## Results (build of 2026-11-26)

Walk-forward composite: rank IC **0.058** (t = 5.1), right in
66% of 161 months. Top quintile **+0.23%/month**
vs the universe, bottom quintile -0.71%, before costs. Most of the edge
comes from avoiding losers, as the literature predicts.

| Signal | Role | Our test | Rank IC | t | Hit rate | Long leg /mo | IC 2012–19 / 2020+ | Published evidence |
|---|---|---|---|---|---|---|---|---|
| Going-concern warning | avoid | **predictive** | 0.048 | 9.1 | 74% | -0.01% | 0.032 / 0.065 | no published test (distress proxy) |
| Cash runway | context | **predictive** | 0.065 | 6.0 | 67% | 0.12% | 0.042 / 0.096 | no published test |
| Cash profitability | pick | **predictive** | 0.056 | 5.3 | 62% | 0.26% | 0.021 / 0.103 | profitability family; real long leg |
| Late filings (12m) | avoid | **predictive** | 0.033 | 5.2 | 65% | -0.13% | 0.022 / 0.040 | no published test (distress proxy) |
| Equity offerings (12m) | avoid | **predictive** | 0.031 | 5.1 | 64% | -0.04% | 0.024 / 0.040 | issuance/financing family: avoid |
| Volatility (60d) | avoid | **predictive** | 0.074 | 4.7 | 60% | 0.06% | 0.050 / 0.106 | short-leg only: avoid high-volatility names |
| Lottery (max daily return) | avoid | **predictive** | 0.061 | 4.7 | 63% | 0.05% | 0.044 / 0.084 | short-leg only: avoid lottery stocks |
| Gross profitability | pick | **predictive** | 0.037 | 4.3 | 65% | 0.10% | 0.030 / 0.047 | works since 2015 (0.94%/mo ex-microcaps, t 3.2); real long leg |
| Near 52-week high | pick | **predictive** | 0.060 | 4.3 | 61% | 0.23% | 0.040 / 0.086 | mixed; not re-checked |
| Share issuance (12m) | avoid | **predictive** | 0.038 | 4.2 | 59% | 0.01% | 0.017 / 0.065 | works (t 2.8) but mostly short leg: avoid diluters |
| Residual momentum | pick | **predictive** | 0.042 | 3.6 | 63% | 0.37% | 0.035 / 0.052 | works; about 2x the Sharpe of raw momentum |
| Momentum (12-1 month) | pick | **moderate** | 0.028 | 2.6 | 59% | 0.44% | 0.024 / 0.034 | works, cost-sensitive; crashes |
| Short interest (% of shares) | avoid | **moderate** | 0.036 | 2.5 | 58% | -0.37% | 0.030 / 0.038 | works, short leg: avoid |
| Earnings surprise (SUE) | context | **moderate** | 0.014 | 2.5 | 60% | 0.23% | 0.012 / 0.017 | weak after 2006 outside microcaps |
| Gov. contracts / revenue | context | **moderate** | 0.013 | 2.4 | 59% | 0.07% | 0.013 / 0.012 | announcement-day only; weak |
| Wikipedia attention shock | context | **moderate** | 0.017 | 2.2 | 62% | 0.39% | 0.019 / 0.016 | weak; spike after run-up is a warning |
| Earnings-day return | pick | **moderate** | 0.011 | 2.1 | 56% | 0.20% | 0.014 / 0.007 | works since 2015 (0.40-0.79%/mo); real long leg |
| Industry momentum | pick | **moderate** | 0.024 | 2.0 | 54% | 0.28% | 0.012 / 0.039 | works in older studies; not re-checked |
| News volume (30d) | context | **weak** | 0.023 | 1.8 | 57% | 0.61% | – / 0.023 | attention: short-term pressure then reversal |
| Sales / price | pick | **weak** | 0.017 | 1.3 | 50% | 0.03% | -0.018 / 0.064 | best valuation ranker for loss-making firms |
| 1-month return (reversal) | pick | **not predictive** | 0.006 | 0.7 | 49% | 0.02% | 0.019 / -0.010 | works gross at 1 month; costly turnover |
| Congressional net buying | context | **not predictive** | 0.002 | 0.7 | 47% | 0.01% | 0.006 / -0.002 | does not work from disclosure date |
| Asset growth | avoid | **not predictive** | 0.005 | 0.7 | 49% | 0.14% | 0.000 / 0.011 | weak since 2015; short-leg only |
| Same-month seasonality | pick | **not predictive** | 0.003 | 0.4 | 52% | -0.04% | -0.001 / 0.007 | works gross (Heston-Sadka); needs history |
| Book / market | context | **not predictive** | -0.001 | -0.1 | 51% | -0.04% | -0.010 / 0.011 | near zero / negative since 2015 (value-weighted) |
| News tone (30d) | context | **not predictive** | -0.005 | -0.4 | 43% | -0.14% | – / -0.005 | moves prices for days, then reverses |
| Short interest (days to cover) | avoid | **not predictive** | -0.005 | -0.6 | 55% | -0.44% | -0.005 / -0.005 | works (1.19%/mo EW 1988-2012), short leg: avoid crowded shorts |
| Insider buyer cluster | context | **not predictive** | -0.005 | -1.2 | 47% | 0.09% | 0.001 / -0.011 | no extra effect from clusters |
| Accruals | context | **not predictive** | -0.009 | -1.3 | 47% | 0.03% | -0.015 / -0.000 | dead since 2015 |
| Bottleneck language (1y) | context | **wrong sign** | -0.015 | -2.3 | 43% | -0.16% | 0.002 / -0.038 | no published test |
| Opportunistic insider buying | pick | **wrong sign** | -0.022 | -3.9 | 37% | -0.12% | -0.022 / -0.023 | real but short-lived (1-5 days after filing) |
| Size (log market cap) | context | **wrong sign** | -0.059 | -5.4 | 40% | -0.50% | -0.035 / -0.091 | weak after costs |
| Illiquidity (Amihud) | context | **wrong sign** | -0.062 | -6.8 | 31% | -0.70% | -0.041 / -0.091 | liquidity premium mostly eaten by costs |

## Caveats

- **Costs:** results are before trading costs, which run about 0.5% per round trip
  in small caps. Several signals turn over slowly (turnover is shown on the
  dashboard), but the composite's top names do change monthly.
- **Survivorship:** delisted companies are covered from 2016 (Alpaca). Earlier
  failures without prices are missing, which flatters low-quality names, so avoid
  signals are, if anything, understated.
- **Multiple testing:** 33 signals were tested. Rely on t ≥ 3 and on signals with
  published support, not on single-period winners.
- **Wrong-sign findings:**
  - Size and illiquidity: small, illiquid names did worse, which supports the
    liquidity filter.
  - Opportunistic insider net buying predicted *lower* returns. In this universe,
    insider sales cluster in winners.
  - These are observations; their sign was not flipped after the fact.
- **Thin news history:** news (GDELT) only covers recent months until the backfill
  completes, so its status is provisional.

## Short-term and intraday data points

Configured in `configs/short_term.yaml`; the bar engine is `ddb.features.bars`.

**Rules** (same no-hindsight standard as the monthly panel):

- A value at bar i uses bars that had closed by then. Intraday bars are labeled
  by their end time (New York); the 09:30-09:35 bar is public at 09:35.
- Targets enter at the **next bar's open** (never the decision bar's close) and
  exit h bars later; intraday targets never cross the session close.
- Fresh events (offerings, distress filings, earnings, insider buys, news) count
  from the first trading day whose close came after they were public.
- Every data point is tested **after costs**: round-trip spread from the
  liquidity tiers in `configs/sim.yaml`, wider at the open. Edge after costs =
  top 20% minus the average name minus that cost. For avoid signals it is how far
  the flagged names lag; avoiding costs nothing.
- Intraday statistics average each trading day first, so thousands of bars in a
  day count as one observation; results are also broken down by time of day.
- The short-term composites are walk-forward like the monthly one: each month uses
  only data points with t >= 3 on earlier data.

**Daily** (`python -m ddb.features.daily`): next-day and 5-day horizons since 2012:
reversal (1 and 5 days), opening gap, volume surge, close location, 20-day
breakout, daily range (ATR, for stops and sizing), fresh earnings reaction, new
offering, new distress filing, fresh insider buying, news and Wikipedia spikes.

**Intraday** (`python -m ddb.db.build_intraday`, then `python -m ddb.features.intraday`):
1-minute Alpaca bars (free account, SIP feed, 2016+, regular session), resampled
to 5-minute, 15-minute and hourly bars: last bar's move, short- and long-window
trend within the session, move since the open, distance from VWAP, volume vs normal
for that time of day, position in the day's range, the day's gap, intraday
volatility. Download scope: the most liquid names in the tracked industries
(including later-delisted ones), plus the configured candidates and benchmarks.

**Learning on bars.** `ddb.features.intraday.load_pricedata(symbols, "15Min", start, end)`
returns bars the backtester can step through with `SimSettings(intraday=True)`:
the same costs; T+1 settlement and the good-faith rule counted in trading days;
liquidity measured from prior sessions only; the opening spread only at the
session's first bar; and `view.bars_left_in_session()` so a strategy can be flat
by the close. A cash account can trade its full balance about once a day.

**Results:** not run yet on the real database. Run the two commands above; the
scorecards appear on the dashboard (Today, and Model lab). Expect most
short-horizon data points to be statistically real but smaller than costs.
