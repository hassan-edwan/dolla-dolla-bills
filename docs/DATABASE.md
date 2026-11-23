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

## Known gaps

- **Financials before ~2009:** XBRL started in 2009–2011, so earlier periods
  have filings and events but no structured numbers. Parsing old 10-K text is a
  later job.
- **Prices for dead companies:** Yahoo rarely serves delisted tickers. Their
  filings, events, financials and outcome labels are still in the database, which
  is enough to learn failure warning signs. Price-based backtests of them need
  another source.
- **Outcome labels:** about 2,200 "unknown" rule outcomes (stopped filing with no
  clear exit filing) and the open research queue.
- **Research rows:** partly from the researchers' own knowledge and partly
  web-verified. Confidence levels are recorded, and SEC data wins on conflicts.
  19 seeds could not be found in EDGAR (`data/research/seed_unmatched.json`).
