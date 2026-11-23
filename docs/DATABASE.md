# Company database

A single DuckDB file, `data/ddb.duckdb`, plus Parquet files under `data/db/`.
It covers every SEC-registered company that was ever in the target industries,
**including companies that failed, delisted or were acquired**. Built from free
sources only. Not in git (it is large); rebuild it with:

```bash
export DDB_SEC_USER_AGENT="dolla-dolla-bills you@example.com"
python scripts/build_database.py --download   # first time (~3GB of SEC bulk files)
python scripts/build_database.py              # rebuild all steps
python scripts/db_report.py                   # coverage report
# Alpaca step needs a free key in ~/.config/ddb/alpaca.env (APCA_API_KEY_ID / APCA_API_SECRET_KEY)
```

## The no-hindsight rule

The model may only see information that was public at the moment it decides.
The database enforces this:

1. **Every feature row has `knowable_at`** (UTC), the earliest moment it was public:

   | Data | knowable_at |
   |---|---|
   | Filings, events | SEC acceptance timestamp |
   | XBRL financials | acceptance time of the filing that reported that version |
   | Daily prices | 21:00 UTC on the bar date (after the US close) |
| Insider trades | Form 4 acceptance time (not the trade date) |
| Congressional trades | the day after the disclosure filing (not the trade date) |
   | Splits/dividends | 13:00 UTC on the ex-date |
   | FRED market series | the day after the observation |
   | Company names / industry tags | start date of the name or tag |

2. **Restatements are versions, not overwrites.** Every filing re-reports earlier
   periods. Each version is kept with its own `knowable_at`, so a revised number
   appears only from the date it was filed.
3. **Industry membership is dated.** The SEC exposes only a company's *current*
   industry code, and using it for the past would be hindsight. Tags come from
   the company's dated name history: Riot was "AspenBio Pharma" (biotech) until
   it became "Riot Blockchain" (crypto) on 2017-10-04. A current SIC code that
   contradicts an earlier name only applies after the rename.
4. **As-traded prices.** Yahoo adjusts old prices for later splits, which leaks
   future reverse splits into price levels. `close_raw` / `volume_raw` undo every
   split after each date. Use them for any price- or volume-level feature or filter.
5. **Labels are separate.** `outcomes` (how a company's listing ended) is a
   training *target* only. It is not reachable through the point-in-time API.
6. **One read path for features:**

   ```python
   from ddb.db.schema import connect
   from ddb.db.pit import AsOf

   con = connect("data/ddb.duckdb")
   with AsOf(con, "2019-06-28 20:00") as db:
       universe = db.universe(["tech", "energy"])           # who was in the industry then
       rev = db.latest_fact(1167419, "Revenues")           # financials as known then
       db.query("SELECT * FROM events WHERE cik = 1167419") # only events filed by then
   ```

   Inside `AsOf`, every feature table is filtered to `knowable_at <= t`. Queries
   against `outcomes`, `companies` (current-state snapshot) or the research tables
   raise `LookaheadError`.

## Investment screens (what may be traded)

The user does not invest in **weapons makers**, **Israeli companies**, or
companies that are **not Sharia compliant**. Rules are in `configs/screens.yaml`;
the tables are built by `python -m ddb.db.build_screens`.

Decisions recorded 2026-11-23: crypto allowed; Israel = headquartered there;
the weapons gray zone is excluded outright but still trained on and monitored.

| Screen | Rule | Dated? |
|---|---|---|
| `israel` | **Fail** if headquartered in Israel (SEC business address/city). **Review** if only incorporated or mailing address there (e.g. JFrog, Taboola, Stratasys); not tradable until confirmed | static |
| `weapons` | **Fail**: weapons-industry SIC codes, weapons keywords in any historical name, known weapons makers, **and the gray zone** (mixed civilian/military aerospace codes, defense keywords, defense software such as Palantir) | static |
| `weapons_dod` | **Fail** from the year Department of Defense contract obligations exceed 10% of revenue (after the 90-day DoD delay) | yes |
| `sharia_business` | Fail: interest-based finance, conventional insurance, alcohol, tobacco, gambling, cannabis. **Crypto allowed**, including crypto companies filed under finance codes | static |
| `sharia_financial` | AAOIFI-style ratios each quarter, using only data known then: debt / 36-month average market cap ≤ 30%; cash + interest-bearing securities ≤ 30%; gross interest income / total income ≤ 5%. Pre-revenue companies earning only interest → review. Ratios above 20× → `unknown` (data error). Missing data → unknown | yes (quarterly) |

`monitored_companies`: weapons-excluded companies. Never traded, but their
contracts, filings and insider/politician trades stay in training as
information about suppliers, competitors and industry demand.

Known limits:
- Interest income reported under a company's own custom XBRL tags isn't seen.
  Coinbase's stablecoin reserve income, for example, may be understated.
- Companies with no structured financials (e.g. some 40-F filers like Cameco)
  stay `unknown`, so they aren't tradable.

`AsOf(t).tradable()` returns the companies that pass every screen as known at t.
`review` and `unknown` are **not** tradable by default. Screened-out companies
stay in the database as training data (`exclude_from_training: false`).

## Tables

| Table | Kind | Contents |
|---|---|---|
| `companies` | snapshot (not PIT) | identity, current name/SIC/tickers, first/last filing |
| `company_names` | feature | dated name history |
| `company_industries` | feature | dated industry tags: method `sic`, `keyword_name` or `research`, with a confidence level |
| `tickers` | feature | dated tickers (`sec_current`, `research`) |
| `filings` | feature | every EDGAR filing with acceptance time and 8-K items |
| `events` | feature | failure/dilution/corporate signals derived from filings (below) |
| `fundamentals` | feature | XBRL facts, every version (view over Parquet) |
| `prices` | feature | daily OHLCV, split-adjusted plus as-traded (view over Parquet) |
| `corporate_actions` | feature | splits, dividends |
| `macro` | feature | FRED market series (rates, VIX, spreads, oil, gas, dollar) |
| `insider_transactions` | feature | every Form 3/4/5 transaction since 2006: owner, role, code, shares, price, 10b5-1 flag. `knowable_at` = filing acceptance; `filing_lag_days`; `trans_date_suspect` flags filer typos |
| `gov_contracts` | feature | federal contract transactions (never award totals); `knowable_at` = action date + 90 days for DoD, + 5 otherwise |
| `regulatory_documents` | feature | Federal Register rules/notices for 23 industry-shaping agencies, 2005+; `knowable_at` = publication morning |
| `legislators`, `legislator_terms` | reference | members of Congress since 2005 with terms |
| `committee_seats` | feature | dated committee seats from 2012 (git snapshots of congress-legislators) |
| `committee_industries` | reference | committee → industries it oversees (`configs/committees.yaml`) |
| `screen_static`, `screen_dod_share`, `screen_sharia_financial` | screens | investment screens (above) |
| `news_events` | feature | GDELT articles naming a tracked company or carrying industry + signal themes; tone, source, URL. `knowable_at` = file time + 15 min |
| `filing_text_signals` | feature | filings containing bottleneck / development / stagnation phrases (EDGAR full-text search, 2001+). `knowable_at` = acceptance |
| `wiki_pageviews` | feature | daily Wikipedia views for company and industry-topic articles. `knowable_at` = next day |
| `research_velocity` | feature | arXiv papers per month per topic. `knowable_at` = month end + 1 day |
| `politician_trades` | feature | congressional trades (opt-in, see `RESEARCH_TRACKS.md` #9). `knowable_at` = day after disclosure |
| `outcomes` | **label** | how each company's listing ended: `rule` (from final filings) and `research` (web-verified) |
| `research_notes` | provenance | every web-researched fact with source URL and confidence |
| `research_queue` | to-do | open lookups: unknown outcomes, missing historical tickers, unmatched seeds |

### Event types (from filings)
- **Distress / exit:** bankruptcy (8-K 1.03), delisting notice (3.01), restatement /
  non-reliance (4.02), late annual or quarterly report (NT 10-K / NT 10-Q), auditor
  change (4.01), exchange delisting (25-NSE), voluntary delisting (25), deregistration (15).
- **Dilution:** unregistered equity sale (3.02), shelf registration (S-3), offering
  prospectus (424B5), registration (S-1).
- **Corporate:** merger proxy (DEFM14A), tender offer (SC TO-T), merger registration
  (S-4), activist/control stake (SC 13D), change in control (5.01), officer/director
  change (5.02), spin-off (10-12B), acquisition completed (2.01).

## How companies get in

1. **SIC rules + dated name keywords** (`configs/industries.yaml`) over all ~1M
   EDGAR filers. Investment funds are excluded. A company must have filed at
   least one annual report (10-K/20-F/40-F). Note: the SEC marks many defunct
   operating companies as entity type "other"; they are kept on purpose, since
   dropping them would remove failures.
2. **Web research seeds** (`data/research/seeds_*.csv`): industries the SEC codes
   miss (crypto miners file as "finance services", quantum as "software").
   Researchers deliberately hunted failures as much as winners. Each row is
   matched to a CIK across all of EDGAR, the company is force-added, and the
   industry tag is dated from when the company entered the business.

## Coverage (build of 2026-11-23)

| Table | Rows |
|---|---|
| companies | 9,950 (2,512 listed now, 7,438 gone) |
| filings | 4.3M |
| events | 350k |
| fundamentals (fact versions) | 43.1M, for 6,078 companies |
| prices (daily bars) | 8.6M, for 2,953 tickers, 2000-01 → 2026-11 |
| macro | 83k |
| outcome labels | 10.5k |
| research notes | 2.4k |

| Industry (any time since 2005) | Companies | Listed now | Gone | Web-researched |
|---|---|---|---|---|
| tech | 3,019 | 843 | 2,176 | 94 |
| energy | 2,503 | 488 | 2,015 | 90 |
| gene_biotech | 2,273 | 868 | 1,405 | 0 |
| ev_battery | 432 | 169 | 263 | 93 |
| robotics_ai | 204 | 131 | 73 | 72 |
| nuclear | 118 | 50 | 68 | 46 |
| crypto_adj | 112 | 83 | 29 | 69 |
| space | 106 | 47 | 59 | 46 |
| quantum | 43 | 29 | 14 | 17 |

How companies left: 1,634 acquired · 495 bankrupt · 535 forced delisting ·
1,238 deregistered · 20 went private · 2,011 unknown · 2,488 active.

## Known gaps

- **Financials before ~2009:** XBRL started in 2009–2011, so earlier periods
  have filings and events but no structured numbers. Parsing old 10-K text is a
  later job.
- **Prices for dead companies (biggest gap):** Yahoo drops delisted tickers.
  Alpaca's delisted securities were matched by name to 1,070 dead companies, and
  207 of them got daily bars (221k bars, 2016+; Alpaca history starts in 2016).
  Companies that died before 2016 still lack prices. Their filings, events,
  financials and outcome labels are complete, which is enough to learn failure
  warning signs. Price-based backtests of them need a second source; candidates
  are Alpaca's free historical data (free account + API key) and Stooq.
- **Outcome labels:** about 2,200 "unknown" rule outcomes (stopped filing with no
  clear exit filing) and the open research queue.
- **Research rows:** partly from the researchers' own knowledge and partly
  web-verified. Confidence levels are recorded, and SEC data wins on conflicts.
  19 seeds could not be found in EDGAR (`data/research/seed_unmatched.json`).
