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
| 9 | **Congressional trades** | House Clerk PTRs, Senate eFD | the day after the filing date (up to 45+ days after the trade) | ⏸ legal decision (below) |
| 10 | **Which politicians oversee which industry** | `congress-legislators` (public domain): members, terms, committees | committee assignment start | 📋 |
| 11 | **Government contracts** per company | USAspending.gov API (public domain) | award action date | 📋 |
| 12 | **Lobbying spend and issues** per company | Senate LDA API | filing date | 📋 (API down at last check) |
| 13 | **Regulation and policy** affecting each industry | Federal Register API, regulations.gov | publication date | 📋 |
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

### 9. Congressional trades: needs your decision
- The data: STOCK Act Periodic Transaction Reports. The House publishes PDFs
  (parser written and tested). The Senate uses an HTML search site gated by a
  usage agreement.
- **Legal restriction:** 5 U.S.C. §13107(c) makes it unlawful to obtain or use
  these reports "for any commercial purpose, other than by news and
  communications media." Whether a personal trading model is a "commercial
  purpose" is unsettled. The Senate site requires accepting this as a condition
  of access. Download is paused until you decide.
- Options: (a) you decide it's fine for personal research and we pull House +
  Senate directly; (b) use a commercial vendor that licenses this data; (c) skip
  it and rely on corporate insiders (track 8) plus committee/lobbying/contract
  data (tracks 10–12), which carry no such restriction.
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
