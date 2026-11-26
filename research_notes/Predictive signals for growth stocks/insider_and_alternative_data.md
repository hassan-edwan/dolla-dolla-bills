# Informed-Trading and Alternative-Data Signals for US Stock Returns

Scope note: this research run used 15 search/fetch calls. Claims verified in this session have a [Source](URL). Claims drawn from the researcher's prior knowledge of the literature and **not re-verified in this session** are marked "(unverified this session)" and should be checked before anyone relies on the exact numbers.

Verdict summary (for the report writer):

| Signal | Verdict | Horizon | Note on free data |
|---|---|---|---|
| Insider open-market purchases (opportunistic, officer-level, non-10b5-1) | **Works, but smaller and shorter than the classic papers suggest** | Days to 1 month after filing; small caps | SEC EDGAR Form 4 (free, filed within 2 business days) |
| Insider sales / routine trades | **Does not work / weak** | n/a | Same |
| Congressional trades (copy from disclosure) | **Does not work** for the average member; **unclear** for leaders | n/a | House/Senate disclosure sites; up to 45-day lag |
| Government contract awards | **Weak** (small announcement effect, no clear drift) | ±1 day | USAspending, DoD daily contract announcements |
| Federal Register / regulatory events | **Unclear / weak** as a stock-picking signal; regulatory exposure is a priced characteristic | Event days; annual | Federal Register API, RegData |
| Google search volume (SVI) | **Works short-term then reverses**; not a monthly long signal | 2 weeks up, reversal within a year | Google Trends (sampled, normalized) |
| Wikipedia page views | **Weak/unclear**; one recent positive paper, weekly better than monthly | ~1 week | Wikimedia pageviews API (free, from mid-2015) |
| News tone (Tetlock) | **Works at days, reverses**; firm-level negative words predict earnings | 1-5 days (market); next quarter earnings (firm) | GDELT (free, noisy) |
| Filing text changes ("Lazy Prices") | **Works; best fit for monthly rebalancing** | Months (slow diffusion) | EDGAR full text (free) |
| Patents / innovative efficiency | **Works (slow, long-horizon)** | 1-12 months | USPTO PatentsView, KPSS public data (lagged) |
| Analyst revisions | **Works (strong)**, data not free | 1-3 months | Partial substitutes only |

## Corporate insider trading (SEC Forms 3/4/5)

### Takeaway
Insider *purchases* by *opportunistic* (non-routine) insiders carry real information; routine trades and sales carry roughly none. But a post-2022, filing-date, outside-investor event study on free EDGAR data finds the edge is concentrated in the first 1-5 trading days after filing (+0.5% to +1.0% vs SPY) and is not statistically distinguishable from zero at 1-3 months. Give purchase signals moderate weight at short horizons; give sales and routine trades near-zero weight.

### Cited Findings
- Cohen, Malloy & Pomorski ("Decoding Inside Information," JF 2012, vol. 67(3), 1009-1043): classify an insider as "routine" if they trade in the same calendar month in prior years; everyone else is "opportunistic." A portfolio of opportunistic trades earns **value-weighted abnormal returns of 82 bp/month**; routine traders' abnormal returns are **essentially zero**. Sample: Thomson Reuters insider filings, Jan 1986-Dec 2007 — [NBER w16454](https://www.nber.org/papers/w16454); [NBER Digest](https://www.nber.org/digest/apr11/decoding-inside-information)
- More than half of all insider trades are routine and not informative — [NBER Digest](https://www.nber.org/digest/apr11/decoding-inside-information)
- Opportunistic trades predict future firm-specific news and announcement returns around analyst forecasts, management forecasts and earnings. The most informed opportunistic traders are **local, non-executive insiders at geographically concentrated, poorly governed firms**. Opportunistic traders are more likely to face SEC enforcement, and they trade less after SEC enforcement waves — [NBER w16454](https://www.nber.org/papers/w16454)
- Jeng, Metrick & Zeckhauser: insider purchases earn abnormal returns of **more than 6% per year**, and sales earn none. An earlier NBER version reports purchase portfolios beating the market by **about 7.4%/yr** in raw returns. This is measured from the *trade* date, so it is the insider's own return, not an outside copier's — [Harvard/Zeckhauser PDF](https://scholar.harvard.edu/sites/scholar.harvard.edu/files/rzeckhauser/files/insider_trading.pdf); [NBER w6913](https://www.nber.org/system/files/working_papers/w6913/w6913.pdf)
- Lakonishok & Lee (2001): purchases are more informative than sales, and the effect is concentrated in smaller firms (1975-1995) — as summarized in [QuantInsti](https://blog.quantinsti.com/sec-form-4-insider-trading-python-event-study/)
- **Recent filing-date evidence (2022Q1-2026Q2, free EDGAR data).** Construction: Form 4, transaction code P, non-derivative common shares; 4/A amendments and joint filings excluded; officer/president/chair roles only; trades flagged as 10b5-1 excluded; aggregated to one issuer × filing-date signal; entry at the next session after filing; 7,405 signals. Results:
  - CAR vs SPY: 1 session +0.53% (t=6.5); 5 sessions +1.01% (t=5.1); 21 sessions +0.98% (t=1.7, p=0.10); 63 sessions +1.10% (t=1.2, n.s.)
  - BHAR at 63 sessions: +0.10% (n.s.)
  - **Cluster minus solo** buying: +0.18 pp at 21 days and +1.53 pp at 63 days, both with confidence intervals crossing zero
  - First-time vs repeat buyers: not significant
  — [QuantInsti, "SEC Form 4 Insider Purchases in Python: A Filing-Date Event Study"](https://blog.quantinsti.com/sec-form-4-insider-trading-python-event-study/)
- Open-market insider purchases made in the gap before an 8-K is filed are especially informative (about 43,000 transactions, 2004-2014) — [Cohen/Jackson et al. via Columbia Millstein SSRN 2657877](https://millstein.law.columbia.edu/sites/default/files/content/images/SSRN-id2657877.pdf); [Cooley PubCo summary](https://cooleypubco.com/2015/09/16/academic-study-shows-insiders-beat-the-market-in-the-8-k-trading-gap/)
- Insider purchases become less credible signals after acquisitions. The author stresses that this does not make them uninformative in general — [CLS Blue Sky Blog, 2026](https://clsbluesky.law.columbia.edu/2026/09/22/when-are-insider-purchases-credible-signals-of-private-information/?amp=1)
- After the 2022 SEC Rule 10b5-1 amendments, the share of insider sales executed under 10b5-1 plans fell significantly — [Kim, Kim & Rajgopal, Wharton](https://accounting.wharton.upenn.edu/wp-content/uploads/2025/10/KimKimRajgopal.pdf)
- (Unverified this session) Those amendments added a 90-day-or-longer cooling-off period for officers and directors and a Form 4 checkbox flagging 10b5-1 trades, effective for filings from about April 2023. Before then, plan trades can't be identified reliably from Form 4 (footnotes only).

### Inferences
- **How to build it from free data:** parse EDGAR Form 4 XML. Keep code P only (drop A, M, F, G, which are grants, exercises, tax withholding and gifts). Drop 10b5-1-flagged trades from 2023 onward. Classify routine vs opportunistic using CMP's rule, which needs at least 3 prior years of each insider's history. Date the signal on the **filing acceptance timestamp**, entering at the next open. Scale by purchase value relative to market cap or dollar volume.
- Weighting: CEO/CFO and C-suite purchases are a reasonable filter. Cohen-Malloy-Pomorski suggest non-executive local directors at poorly governed firms may be *more* informed, though, so don't restrict to the CEO.
- **Monthly rebalancing captures little**, because most of the measurable post-filing edge sits in days 1-5. If the project rebalances monthly, treat insider buying as a tilt or tie-breaker rather than a primary factor.
- Sales: use only as weak negative information, for example large non-plan sales by several officers. The classic papers and the recent study both find little in sales.
- The 82 bp/month CMP figure predates 2008, uses trade-date-adjacent portfolios and may have decayed. The 2022-2026 study suggests roughly 1% over a month, with low significance.

### Gaps
- I did not find a peer-reviewed 2010-2025 study that measures returns of opportunistic vs routine trades from the *filing* date. The recent evidence is a practitioner blog, which needs replication.
- The CEO-vs-other split and small-cap vs large-cap effect sizes in post-2010 data were not found in this session.
- Exact effect sizes for cluster buying in peer-reviewed work were not verified. The recent blog finds it not significant.

## Congressional stock trades (STOCK Act disclosures)

### Takeaway
The early evidence of large congressional alpha (Ziobrowski et al.) covers pre-2002 samples. Post-STOCK Act (2012+) studies consistently find the average member **matches or underperforms** benchmarks, so copying from the disclosure date is not supported. A 2025 NBER paper finds that members who rise to *leadership* outperform sharply. That is not an investable "follow all of Congress" signal, and it was not shown to survive the disclosure lag. NANC's outperformance looks like a large-cap tech/growth tilt, not evidence of information.

### Cited Findings
- Belmont, Sacerdote, Sehgal & Van Hoek, "Do senators and house members beat the stock market? Evidence from the STOCK Act," J. Public Economics 2022, vol. 207. Senate sample 2012-March 2020:
  - Senators' purchases underperform an industry-size benchmark at the 1-month horizon.
  - Stocks they sold underperformed the market by about 9% (significant).
  - Even at the 95th/99th percentiles, House and Senate returns are consistent with random stock picking.
  - No evidence of industry-specific skill tied to committee assignments.
  — [IDEAS/RePEc](https://ideas.repec.org/a/eee/pubeco/v207y2022ics0047272722000044.html); [NBER w26975](https://www.nber.org/papers/w26975); [Dartmouth news](https://home.dartmouth.edu/news/2020/04/us-senators-stock-picks-do-not-appear-reflect-inside-traders-edge)
- Chen & Sacerdote, "Capital in the Capitol: Congressional Trades Resemble Uninformed Retail Trading," NBER w35041 (April 2026). All members and their families, 2012-2023:
  - Portfolios "underperform or, at best, match market benchmarks."
  - Positions track professional recommendations, and timing follows retail social-media sentiment.
  — [NBER w35041](https://www.nber.org/papers/w35041)
- Wei & Zhou, "'Captain Gains' on Capitol Hill," NBER w34524 (Nov 2025). Members who later reach leadership perform like matched peers before ascending, but **outperform them by 47 percentage points annually after ascension**. Channels include:
  - higher returns when their party controls the chamber
  - sales ahead of regulatory actions
  - purchases of firms that later receive more government contracts
  - trades that predict corporate news, and donor-owned or home-state firms
  The abstract does not report returns measured from disclosure dates — [NBER w34524](https://www.nber.org/papers/w34524)
- Huang & Xuan: before the STOCK Act, firms with members of Congress as shareholders earned Carhart alphas of about 9.5%/yr. In later work (2023), abnormal performance **largely disappeared after the STOCK Act** — [VoxEU/CEPR column](https://cepr.org/index%2Ephp/voxeu/columns/political-power-and-profitable-trades-us-congress)
- Gao & Huang (2016): politically connected hedge funds lost some of their edge after the STOCK Act — [VoxEU/CEPR](https://cepr.org/index%2Ephp/voxeu/columns/political-power-and-profitable-trades-us-congress); [HLS Forum](https://corpgov.law.harvard.edu/2016/08/26/capitalizing-on-capitol-hill-informed-trading-by-hedge-fund-managers/)
- Eggers & Hainmueller, "Capitol Losses" (2013), on House members' portfolios 2004-2008 — [MIT PDF](https://www.mit.edu/~jhainm/Paper/Eggmueller_CapitolLosses.pdf). (Unverified this session) They find members' portfolios underperformed passive benchmarks by roughly 2-2.5%/yr, though members did overweight locally headquartered and politically connected firms.
- (Unverified this session) Ziobrowski et al. (2004) found senators beat the market by about 12%/yr (1993-1998), and Ziobrowski et al. (2011) found House members beat it by about 6%/yr (1985-2001). Those were trade-date returns, before the STOCK Act. A Cato brief summarizes this earlier literature — [Cato RB231](https://www.cato.org/sites/cato.org/files/2020-08/RB231.pdf)
- 2026 working papers on strategic or "unreadable" disclosure of congressional trades (ABFER 2026) suggest disclosure itself is gamed in timing and format — [ABFER PS26066](https://abfer.org/media/abfer-events-2026/posters/selected-papers/PS26066_Electoral-Pressure-and-Strategic-Disclosure-of-Congressional-Trades.pdf); [ABFER AC26P2063](https://abfer.org/media/abfer-events-2026/annual-conference/papers-corporate/AC26P2063_Unreadable-Political-Trades.pdf)
- **Copycat ETFs:**
  - NANC (Democratic trades) returned 30.51% in 2024 vs 19.68% for KRUZ (Republican trades) — [PortfoliosLab](https://portfolioslab.com/symbol/NANC)
  - KRUZ returned -1.31% in 2025 — [PortfoliosLab KRUZ](https://portfolioslab.com/symbol/KRUZ)
  - NANC returned 93.23% since launch through May 13, 2026, vs 78.79% for SPY — [24/7 Wall St](https://247wallst.com/investing/2026/05/16/nanc-traders-beat-the-crowd-by-33-points-and-the-difference-keeps-growing/)
  - In 2024 the "God Bless America" (YALL) ETF beat both political trackers with a 33% gain — [Fortune](https://fortune.com/2024/12/22/god-bless-america-etf-yall-donald-trump-tesla-stock-elon-musk-sp500-nancy-pelosi-fund/)
  - Side-by-side comparison of NANC vs KRUZ — [etf.com](https://www.etf.com/sections/etf-basics/nanc-vs-kruz-battle-congress-stock-trackers)

### Inferences
- NANC's lead over SPY (about 14 points cumulative over roughly 3 years) is consistent with a concentrated mega-cap tech overweight, and KRUZ's lag fits its energy/value tilt. Neither is factor-adjusted evidence of skill. Treat both ETFs as style bets.
- Disclosure timing: the STOCK Act allows up to **45 days** after the trade, and late filings are common. The data are therefore stale relative to any information edge, and there is no peer-reviewed evidence of positive returns from the disclosure date. **Verdict: does not work** for broad copying. **Unclear** for leadership-only or committee-relevant filters. The Wei-Zhou result is promising but has not been shown to be tradeable after disclosure.
- The project should assign little or no weight to raw congressional-trade signals. If it keeps them, restrict to party leaders and measure from the disclosure date with factor adjustment.

### Gaps
- No study found that explicitly measures factor-adjusted returns of congressional trades from the *disclosure* date after 2012. Quiver Quantitative research notes were not retrieved.
- The exact NANC/KRUZ calendar-2025 comparison vs SPY was not cleanly retrieved.

## Government contract awards (USAspending / DoD announcements)

### Takeaway
Contract wins produce small, positive announcement-window abnormal returns, concentrated in aerospace/defense and in smaller firms where the contract is material. Evidence of a tradeable post-announcement drift is weak. **Weak** signal; only material awards (relative to revenue) matter.

### Cited Findings
- Larson & Picou: event study of contract winners split into federal non-military, military, municipal and foreign subsamples. Foreign-government awards earn more than corporate or US-government awards — [Emerald/JOPP](https://www.emerald.com/insight/content/doi/10.1108/JOPP-02-02-2002-B004/full/html); [IPPA PDF](https://www.ippa.org/jopp/download/vol2/issue-2/LarsonPicou.pdf)
- Palkar, Larson & Larson (2012, Applied Financial Economics): military awards in a 10-year window around 9/11 show positive announcement-day abnormal returns. Long-run (-1 to +60 day) results suggest post-9/11 contracts were "underfunded" — [IDEAS](https://ideas.repec.org/a/taf/apfiec/v22y2012i2p147-164.html)
- 2024 study of NASDAQ pharma firms receiving federal contracts: a significant effect on CAR, but average daily abnormal returns positive and not significant. The authors call the effect limited — [IDEAS](https://ideas.repec.org/a/bba/j00001/v3y2024i1p1-26d131.html)
- HEC Montréal thesis (2024): positive excess returns in the days after signing, concentrated in aerospace and defense — [HEC PDF](https://biblos.hec.ca/biblio/memoires/yunianti_priska_m2024.pdf)
- Congressional leaders buy stocks of firms that later receive more government contracts, which implies contract flow can be anticipated by insiders before it's public — [NBER w34524](https://www.nber.org/papers/w34524)

### Inferences
- Construction: DoD posts contracts of $7.5M or more daily at defense.gov (5pm ET, so act the next day). USAspending has obligations, but award dates and reporting lag by days to weeks. Scale award value by trailing revenue and only flag awards of roughly 5% or more of revenue. Most large primes (LMT, RTX) see no measurable effect because awards are expected and in backlog.
- Not suitable as a primary monthly factor.

### Gaps
- No recent (2015-2025) large-sample US study with drift estimates from USAspending data was found.

## Federal Register / regulatory events

### Takeaway
Regulatory *exposure* (RegData restriction counts) relates to the cross-section of returns as a risk or priced characteristic. Specific regulatory events move affected industries. There is no evidence that simply monitoring Federal Register publications yields alpha. **Unclear/weak** as a stock-picking signal.

### Cited Findings
- Ince & Ozsoylev (2020), "regulatory operating leverage" built from RegData 3.0 text analysis of the CFR: the top decile earns **6.84% (EW) / 5.28% (VW)** more annually than the bottom decile, read as compensation for systematic risk — [Advisor Perspectives](https://www.advisorperspectives.com/articles/2021/05/03/high-regulatory-costs-drive-higher-stock-returns)
- The most-regulated industries (RegData) earned about 4% higher CARs in the 10 days after the 2016 election, attributed to expected deregulation — [JFQA](https://www.cambridge.org/core/services/aop-cambridge-core/content/view/1DC48EC40956186AFA32FAB9F483B42C/S0022109023000510a.pdf/impact-of-regulations-on-firm-value-evidence-from-the-2016-us-presidential-election.pdf)
- Firms regulated by the EPA, FDA, OSHA or SEC perform worse when agency enforcement intensity rises (Donelson, Garfinkel & Roudini 2023) — [AFA](https://afajof.org/management/viewp.php?n=23380)
- Counts of rules or pages in the Federal Register treat all actions equally regardless of economic significance or direction, which is a key weakness — [Federal Reserve IFDP 1433](https://www.federalreserve.gov/econres/ifdp/files/ifdp1433.pdf)
- Members of Congress who reach leadership sell ahead of regulatory actions — [NBER w34524](https://www.nber.org/papers/w34524)

### Inferences
- Raw Federal Register counts are noise. If the project uses them, it should classify rule direction (burden up or down) and economic significance (for example, "significant" under EO 12866), map them to NAICS, and expect event-day industry moves rather than monthly drift.

### Gaps
- No study found that tests Federal Register publication timing as a tradable predictor of individual-stock returns.

## Investor attention: Google search volume and Wikipedia page views

### Takeaway
Attention predicts **short-term positive price pressure followed by reversal**, mainly in small, retail-heavy stocks. At monthly or longer horizons, high attention is neutral to negative. Google SVI: works short-term, then reverses. Wikipedia: weak/unclear.

### Cited Findings
- Da, Engelberg & Gao, "In Search of Attention" (JF 2011): an increase in Google SVI predicts **higher prices over the next two weeks and a reversal within the year**. Russell 3000, 2004-2008 — [Engelberg UCSD PDF](https://rady.ucsd.edu/faculty/directory/engelberg/pub/portfolios/GOOGLE.pdf); [NBER conference draft](https://projects.nber.org/confer/2009/mms09/Da_Engelberg_Gao.pdf)
- Follow-up work (Da, Hua, Hung & Peng): retail attention brings transitory positive price pressure and then reversal, significant only among **smaller stocks** — [NBER/related PDF](https://www.nber.org/papers/w23274.pdf)
- Pyun (2024, Economics Letters): firms with rising Wikipedia views earn higher returns, and long-short portfolios on view changes have unexplained alphas — [IDEAS](https://ideas.repec.org/a/eee/ecolet/v241y2024ics0165176524003203.html). Weekly rebalancing beats monthly, which implies a short-lived signal — [MLQuants summary](https://mlquants.substack.com/p/the-wikipedia-effect-analyzing-investor) (secondary source)
- Moat et al. (2013, Scientific Reports): Wikipedia views and edits for Dow Jones companies (2007-2012) increased before market declines, tested as trading strategies against random benchmarks — [PMC](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3647164/)
- Ungeheuer: hourly Wikipedia views spike after stocks are daily winners or losers, so attention *follows* returns — [Mannheim](https://madoc.bib.uni-mannheim.de/45292)
- Wikipedia views showed no relation to volume or volatility in the Nigerian market — [DOAJ](https://doaj.org/article/7aa15c17ae1e47558d3980b896f3bfaa)

### Inferences
- For a monthly rebalanced growth-stock strategy, a spike in attention should **not** count as a bullish signal. If anything, abnormally high attention after a run-up is a mild contrarian or reversal flag.
- Construction: use *abnormal* attention, for example log(this week) minus log(median of the prior 8 weeks), rather than levels. Google Trends values are sampled and rescaled 0-100 per query, so keep pulls consistent and average several pulls. Ticker queries are ambiguous (for example "CAT"). The Wikimedia pageviews API is free from July 2015, with the older stats.grok.se data before that.
- Moat et al. is a market-level, small-sample result with a known data-mining risk. Don't use it for cross-sectional picking.

### Gaps
- No 2015-2025 out-of-sample replication of the Da-Engelberg-Gao SVI effect was retrieved.

## News tone / sentiment (Tetlock; GDELT)

### Takeaway
Media pessimism predicts **downward market pressure over days followed by reversal** (Tetlock 2007), which fits sentiment rather than information. Firm-specific negative words have some information about future earnings (Tetlock, Saar-Tsechansky & Macskassy 2008) that is mostly priced within about a day. Usefulness at monthly rebalancing is low.

### Cited Findings
- Tetlock (2007, JF 62(3)): pessimism in the WSJ "Abreast of the Market" column, measured by principal components, robustly predicts **downward pressure on market prices followed by reversion to fundamentals**. Unusually high or low pessimism predicts high volume, and low returns lead to high pessimism. The interpretation is sentiment or non-informational trading — [Tetlock JF PDF](https://www.columbia.edu/~pt2238/papers/Tetlock_Media_Sentiment_JF.pdf); [Columbia](https://business.columbia.edu/faculty/research/giving-content-investor-sentiment-role-media-stock-market)
- Tetlock, Saar-Tsechansky & Macskassy, "More Than Words: Quantifying Language to Measure Firms' Fundamentals" (JF 2008) — citation confirmed at [Tetlock papers page](https://www.columbia.edu/~pt2238/papers/papers.html). (Unverified this session) Its findings:
  - the fraction of negative words in firm-specific news predicts low earnings
  - prices briefly underreact, with most of the information incorporated by the next trading day
  - negative words about fundamentals are most informative
- Garcia (2013, JF) on NYT financial columns finds media sentiment predicts returns mainly in recessions — [Garcia PDF](https://leeds-faculty.colorado.edu/garcia/paper86v12.pdf)

### Inferences
- At monthly rebalancing, a news-tone *level* is mostly stale. If the project uses GDELT, it should use the *change* in tone over the last 1-5 days, expect partial reversal and be wary of GDELT's coarse entity matching and dictionary-based tone.

### Gaps
- No peer-reviewed GDELT firm-level US stock-return study was retrieved in this session.

## Text in filings ("Lazy Prices," risk factors, 8-Ks)

### Takeaway
**Works, and suits monthly rebalancing.** Firms that change their 10-K/10-Q language subsequently underperform, and the market takes months to notice. Risk-factor, CEO/CFO and litigation sections carry the most signal. Built from free EDGAR text with no announcement-day effect, it is one of the best free, slow-moving signals.

### Cited Findings
- Cohen, Malloy & Nguyen, "Lazy Prices" (JF 2020, 75(3), 1371-1415). Full history of US 10-K/10-Q filings, 1995-2014:
  - Shorting "changers" and buying "non-changers" earns **up to 188 bp/month alpha (over 22%/yr)** in five-factor alpha.
  - Changes predict future earnings, profitability, news and bankruptcies.
  - There is **no announcement-date reaction**, consistent with investor inattention.
  - The most predictive changes concern the executive team (CEO/CFO), litigation and risk factors.
  — [NBER w25084](https://www.nber.org/papers/w25084); [RePEc](https://econpapers.repec.org/RePEc:bla:jfinan:v:75:y:2020:i:3:p:1371-1415)
- An Alpha Architect summary attributes the 188 bp figure (t=2.76) to the risk-factors section in particular — [Alpha Architect](https://alphaarchitect.com/lazy-prices/)
- Insider purchases in the window between an event and its 8-K filing are especially informative — [Columbia/SSRN 2657877](https://millstein.law.columbia.edu/sites/default/files/content/images/SSRN-id2657877.pdf)

### Inferences
- Construction: for each firm, compute cosine or Jaccard similarity between this filing and the *same filing type a year earlier* (10-K vs prior 10-K; 10-Q vs the same quarter last year), then rank. Use the EDGAR acceptance date as the signal date. The returns accrue over months, so monthly rebalancing is appropriate. Section-level (Item 1A risk factors) similarity is stronger but needs section parsing.
- Post-publication decay is likely (McLean-Pontiff-style decay typically halves anomaly returns), so plan for substantially less than 188 bp. (Inference, not measured here.)

### Gaps
- No post-2014 out-of-sample estimate of Lazy Prices was retrieved.
- Supply-chain/bottleneck language and 8-K event-type return studies were not covered in this session.

## Research activity (patents, arXiv) and returns

### Takeaway
**Works, but slow.** Innovative efficiency (patents or citations per R&D dollar) positively predicts returns. Patent market value (KPSS) is largely priced at grant, so it's more useful as a fundamental or growth input than as an event signal. No credible evidence was found on arXiv paper counts.

### Cited Findings
- Hirshleifer, Hsu & Li, "Innovative efficiency and stock returns" (JFE 2013, 107(3), 632-654): IE (patents or citations scaled by R&D) is a **strong positive predictor of future returns** after controlling for firm characteristics and risk — [IDEAS](https://ideas.repec.org/a/eee/jfinec/v107y2013i3p632-654.html)
- Their later "innovative originality" paper: originality predicts higher, more persistent profitability and higher abnormal returns, consistent with undervaluation — [summary via search](https://hub.hku.hk/handle/10722/177807)
- Kogan, Papanikolaou, Seru & Stoffman (QJE 2017) estimate patent value from stock reactions around grant dates, filtering noise with distributional assumptions. Patent grants are rapidly reflected in prices — [NBER w23432 / related](https://www.nber.org/papers/w23432.pdf); [MPRA](https://mpra.ub.uni-muenchen.de/59835/1/MPRA_paper_59835.pdf)
- Angelo & Johnston (2023) split patent value into innovative skill and innovative luck — [vLex](https://law-journals-books.vlex.com/vid/technological-innovation-and-stock-1049444948)

### Inferences
- Construction: USPTO PatentsView (free) for grants and citations, matched to firms through the KPSS public crosswalk (on GitHub, updated with a lag) or name matching. Patent applications publish about 18 months after filing, and citations accumulate over years, so the signal is inherently lagged. Use a 5-year R&D capital denominator from XBRL.
- arXiv paper counts: no evidence of predictive power was found. Treat as unproven.

### Gaps
- Effect sizes (monthly alpha) for IE were not extracted. Post-2015 decay is unknown.
- No study of arXiv activity and stock or industry returns was found.

## Analyst revisions and earnings estimates

### Takeaway
Analyst forecast revisions and earnings surprises are among the most robust predictors (post-earnings drift and revision momentum), but IBES-type data are not free. Free substitutes give partial coverage.

### Cited Findings
- Opportunistic insider trades predict returns around future analyst forecast announcements, which shows overlapping information content — [NBER w16454](https://www.nber.org/papers/w16454)

### Inferences
- Free substitutes, all inference rather than tested in this session:
  - standardized unexpected earnings (SUE) built from SEC XBRL companyfacts as a seasonal random walk, for post-earnings drift
  - earnings-announcement returns (3-day CAR) from free prices, as a surprise proxy
  - broker-provided analyst ratings and consensus snapshots, such as the project's Robinhood ratings and earnings-results endpoints, which can be stored forward to build a revision history (no backfill)
  - Yahoo/Zacks consensus pages via scraping, which carry terms-of-use and survivorship issues
- The project already loads PIT fundamentals from companyfacts, so XBRL-based SUE and earnings-announcement returns are the most practical free proxies.

### Gaps
- Effect sizes for revision momentum and post-earnings drift were not retrieved in this session (budget limit). Standard references include Bernard & Thomas 1989 and Chan, Jegadeesh & Lakonishok 1996.
