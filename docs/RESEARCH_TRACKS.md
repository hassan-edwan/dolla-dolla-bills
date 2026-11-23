# Research tracks

Everything the system should learn from, where it comes from (free sources
only), and **when each piece of information became public**. That last part
decides whether a model may use it on a given day.

Status: ✅ in the database · 🔄 partial · ⏸ waiting on a decision · 📋 planned

| # | Track | Free source | When it's knowable (`knowable_at`) | Status |
|---|---|---|---|---|
| 1 | Company identity, industry membership, name history | SEC EDGAR bulk submissions | rename/filing date | ✅ |
| 2 | Filings and distress / dilution events | SEC EDGAR | SEC acceptance time | ✅ |
| 3 | Reported financials (every revision) | SEC XBRL company facts | acceptance time of the reporting filing | ✅ (2009+) |
| 4 | Daily prices, listed companies | Yahoo | after the close | ✅ |
| 5 | Daily prices, delisted companies | Alpaca (free account) | after the close | 🔄 2016+ only |
| 6 | Market / macro series | FRED | next day | ✅ |
| 7 | How each company's listing ended | final filings + web research | **label only**, never a feature | ✅ |
| 8 | **Corporate insider trades** (officers, directors, 10% owners) | SEC Form 3/4/5 data sets, 2006+ | Form 4 acceptance time, **not** trade date | ✅ |
| 9 | **Congressional trades** | House Clerk PTRs (2015+), Senate eFD (2012+) | the day after the filing date (up to 45+ days after the trade) | 🔄 approved; loading |
| 10 | **Which politicians oversee which industry** | `congress-legislators` (public domain): members, terms, and committee seats from 211 git snapshots since 2012; committee → industry map in `configs/committees.yaml` | first snapshot showing the seat | ✅ |
| 11 | **Government contracts** per company | USAspending.gov API (public domain), transaction level, FY2008+ | action date + 90 days (DoD release delay) or + 5 days | 🔄 loading |
| 12 | **Lobbying spend and issues** per company | Senate LDA API | filing date | 📋 (API down at last check) |
| 13 | **Regulation and policy** affecting each industry | Federal Register API: 23 agencies mapped to industries (`configs/regulators.yaml`), 2005+ | publication morning | 🔄 loading |
| 14 | **Competitors and peers** | 10-K "Competition" sections (LLM reads filings) | 10-K acceptance time | 📋 |
| 15 | **Valuation inputs** (multiples, growth, margins, dilution, cash runway) | derived from tracks 3–5 + 8 | max of the inputs' knowable_at | 📋 (Phase 2 features) |
| 16 | Industry trend research (capacity, demand, prices) | EIA (energy), USPTO patents, Google Trends, filings | publication date | 📋 |
| 17 | Earnings call content | 8-K exhibit 99 press releases (transcripts aren't free) | 8-K acceptance time | 📋 |

## Notes per track

### 8. Insider trades
- Every Form 3/4/5 since 2006 for companies in the database.
- Kept fields: owner, role (officer / director / 10% owner), transaction code,
  shares, price, holdings after, direct/indirect, 10b5-1 plan flag (2023+),
  derivative vs. common.
- The informative codes are **P** (open-market buy) and **S** (open-market sale).
  Awards (A), tax withholding (F) and option exercises (M) are mostly noise.
  Trades under a pre-scheduled 10b5-1 plan carry less signal.
- `filing_lag_days` is kept. Late filings are common, and the model can only
  see a trade from `knowable_at`.
- Planned features: cluster buying (several insiders buying within a window),
  CEO/CFO buys, buys after price drops, and co-movement of insider net buying
  with later returns. All are computed with only filings knowable at each date.

### 9. Congressional trades (approved: option 1, official filings directly)
- The data: STOCK Act Periodic Transaction Reports. The House publishes PDFs
  (parser written and tested). The Senate uses an HTML search site gated by a
  usage agreement.
- **Legal restriction:** 5 U.S.C. §13107(c) makes it unlawful to obtain or use
  these reports "for any commercial purpose, other than by news and
  communications media." Whether a personal trading model is a "commercial
  purpose" is unsettled. The Senate site requires accepting this as a condition
  of access. Download is paused until you decide.
- Decision: the user approved option 1 (pull House + Senate filings directly
  for personal research).
- Coverage:
  - House electronic PTRs are indexed from 2015. Earlier ones were paper-only.
  - Paper/scanned filings in both chambers are flagged `needs_ocr`.
- If used: amounts are ranges, trades by spouses and dependents are included,
  and `knowable_at` is the **disclosure**, not the trade.

### 10. "Political insiders who know the industry"
Combine track 10 with 9 (if approved) or 11–13. Committee seats map to
industries, for example:
- Energy & Commerce / Energy & Natural Resources → energy, nuclear
- Armed Services → space, defense
- Science, Space & Technology → space, quantum, AI
- Financial Services / Banking → crypto

The signal is then "trades or policy actions by people with oversight of this
industry," dated to when they became public.

### 14. Competitors
Each 10-K names competitors. The LLM extracts the list from each annual report as
filed, which gives a dated peer graph (peers change over time). Competitor
filings, events and insider activity then become features for each company.
This is LLM *research for the database*, not live feature generation.

### 15. Valuation
Built in Phase 2 from data already stored:
- price/sales, EV/revenue, growth, gross margin, operating cash burn and months
  of cash runway
- share-count growth (dilution), insider net buying
- the same metrics relative to industry peers, as known at each date

## The rule for every track
A row enters the database with the timestamp of its **public release**.
Training and backtests read only through `AsOf(t)`, so nothing released after t
can influence a decision at t.


## News: bottlenecks, industry development, stagnation

**What's tracked today:**
- **Company news** that arrives through SEC filings: 8-K events such as
  bankruptcy, delisting notices and restatements, offerings, insider trades,
  merger proxies and late filings.
- **Market and macro series.**
- **Regulatory documents** (track 13).

**Not yet tracked:** general news coverage.

The plan, by what we want to predict:

| Question | Signals | Free source | Status |
|---|---|---|---|
| **Where will bottlenecks arise?** | Supply constraints: "backlog", "lead times", "shortage", "allocation", "capacity constrained" language in 10-K/10-Q/8-K text, counted per industry over time | SEC filing text (LLM/keyword extraction, dated by acceptance) | 📋 |
| | Physical supply data: oil/gas inventories, refinery use, power demand, uranium and lithium prices and production | EIA open data (free key), USGS mineral commodity data, FRED commodity series | 📋 (EIA key needed) |
| | Chip supply chain: monthly semiconductor sales, imports/exports of chips and equipment | SIA/WSTS releases, Census trade data | 📋 |
| | Licensing queues: reactor license dockets, launch licenses, spectrum filings, grid interconnection queues | Federal Register (✅ loading), NRC dockets, FCC filings, FERC | 🔄 |
| | Trade friction: tariffs, anti-dumping on solar/batteries, export controls on AI chips/quantum | Federal Register (USTR, ITC, BIS, ITA) | 🔄 loading |
| **Is the industry developing?** | Research velocity: papers per month (quantum, AI, batteries, fusion) | arXiv API | 📋 |
| | Patent filings by company and industry | USPTO bulk data / PatentsView | 📋 |
| | Government money flowing in: contracts and grants | USAspending (✅ loading) | 🔄 |
| | New entrants: IPOs, SPAC deals and S-1 registrations per industry | SEC filings (✅ have them) | ✅ data, features 📋 |
| | Media attention and tone per company/industry | GDELT 2.0 global news knowledge graph (15-minute files since 2015, ~600MB/day, so it needs a filtering pipeline) | 📋 |
| | Search interest | Google Trends | 📋 |
| **Is it stagnating?** | Rising late filings, going-concern warnings, delisting notices, dilution per industry | SEC events (✅) | ✅ data, features 📋 |
| | Insider net selling across an industry | Form 4 (✅) | ✅ data, features 📋 |
| | Falling contract awards, regulatory headwinds, attention fading | USAspending, Federal Register, GDELT | 🔄 / 📋 |
| | Exits: bankruptcies, forced delistings and acquisitions per industry per year | outcomes labels, events | ✅ |

**Timing rules for news:**
- A news item is usable from its **publication timestamp**: GDELT gives the
  15-minute crawl time and the Federal Register gives the publication morning.
- Filing-text signals are usable from SEC acceptance time.
- Statistical releases (EIA, Census) are usable from their **release date**, not
  the period they describe. Revised series need vintages, as with FRED/ALFRED.
