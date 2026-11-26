# Few signals survive costs; use most to avoid stocks

Only a short list of stock-level metrics still predicts US returns reliably after publication. They are **gross profitability, net share issuance and external financing, earnings-announcement returns and surprise streaks, filing-text changes ("Lazy Prices"), and price momentum if it is built to keep costs down**. Even these deliver modest, noisy edges. Monthly rank ICs of a few hundredths and monthly long-short hit rates of 55-64% are typical, and a realistic net long-only gain is low single-digit percent of annual alpha, not the 1%/month in the original papers. Across hundreds of anomalies, returns fall roughly by half after publication. Net of trading costs, the average anomaly earns about 4 bp/month and the best about 10-20 bp ([Chen & Velikov, JFQA 2023](https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/zeroing-in-on-the-expected-returns-of-anomalies/945133D5A3ECEEAF466AEE91551FD225)). Two facts matter most for a long-only book of volatile small/mid-cap growth stocks:

- **Much of the evidence comes from the short leg.** High issuance, high asset growth, high idiosyncratic volatility, lottery-like spikes (MAX) and crowded short interest all predict *low* returns. A long-only investor captures that only by avoiding those stocks.
- **Only a few signals pick winners.** The positive selectors with real long legs are profitability, announcement-return and streak signals, and momentum.

Almost everything above can be built from free data: SEC XBRL companyfacts, Form 4 and full-text filings, daily prices, FINRA short interest and FRED. Most of the project's alternative-data signals have weak or no support at monthly horizons:

- **Congressional trades:** fail when copied from the disclosure date.
- **Wikipedia and Google attention:** predict price pressure for days to weeks, then a reversal.
- **News tone:** reverses within days.
- **Government contracts and Federal Register events:** only small announcement-day effects.
- **arXiv activity and "bottleneck" language in filings:** no published evidence at all.

So the dashboard should be built to stop the project from fooling itself. It should rank signals by out-of-sample IC decay and net long-leg spread, deflate results for the number of variants tried, and keep delisted names in the backtest.

## Published anomalies lose about half their edge, and costs take most of the rest

Start with base rates, because they set the prior for every signal below. Hou, Xue and Zhang tested 452 anomalies with NYSE breakpoints and value weights, which stops microcaps from dominating the results. **65% fail a |t| > 1.96 test, and 82% fail a multiple-testing hurdle of 2.78** ([HXZ, RFS 2020](https://ideas.repec.org/a/oup/rfinst/v33y2020i5p2019-2133..html)). Microcaps are about 60% of firms but only about 3% of market cap ([Alpha Architect](https://alphaarchitect.com/replicating-anomalies/)). Jensen, Kelly and Pedersen use a Bayesian method and get a more optimistic **82.4% replication rate**. Their rate is similar for small caps (85.7%) and large caps (79.8%) but falls to 68.1% for nano caps. They also find an average **47% decline** from in-sample alpha (0.49%/month) to post-sample alpha (0.26%) ([JKP, JF 2023](https://research-api.cbs.dk/ws/portalfiles/portal/95651880/theis_ingerslev_jensen_et_al_is_there_a_replication_crisis_in_finance_publishersversion.pdf)). McLean and Pontiff's 97 predictors earned **26% less out-of-sample and 58% less after publication**, and the strongest in-sample signals declined the most ([McLean & Pontiff, JF 2016](https://Www.Gwern.net/doc/economics/2016-mclean.pdf)). The US is the only one of 39 markets with a reliable post-publication decline ([Jacobs & Müller](https://www.wiwi.hu-berlin.de/en/Professorships/bwl/finance/seminars/papers-fin-acc-res-seminars/17s/jacobs.pdf)).

Transaction costs then take most of what is left. In the working-paper version of Chen and Velikov, the average of 120 anomalies falls from **66 bp/month gross in-sample, to 38 bp net of spreads, to 13 bp net after publication, to 8 bp net after publication and after 2005**. Short-sale fees of 10-20 bp/month would wipe out the remainder. Only 9% of modern-era net t-statistics exceed 2 ([Chen & Velikov, FEDS 2020-039](https://www.federalreserve.gov/econres/feds/files/2020039pap.pdf)). Turnover predicts survival better than anything else. Anomalies with **less than 50% one-sided monthly turnover** generally keep significant net spreads if they are built to reduce costs, and almost none of the higher-turnover strategies do. Every 1% of monthly turnover costs at least about 1 bp ([Novy-Marx & Velikov, RFS 2016](https://mysimon.rochester.edu/novy-marx/research/ToAatTC.pdf)). Momentum costs about 48 bp/month to trade, against roughly 5-6 bp for size and value ([Alpha Architect](https://alphaarchitect.com/trading-costs-destroy-factor-investing/)).

Three accuracy benchmarks follow:

- **Signal ICs:** "a stellar stock selection model may often have an IC of 0.05 or 0.1," and an IC of 0.01 is real information but hard to detect statistically ([Zhang, Guo & Cao, arXiv 2010.08601](https://arxiv.org/pdf/2010.08601)).
- **Stock-level R² with machine learning:** the best ML models reach a monthly out-of-sample R² of only **0.33-0.43%** across 30,000 stocks ([Gu, Kelly & Xiu, RFS 2020](https://www.nber.org/papers/w25398.pdf)).
- **Market timing:** the 2024 Goyal-Welch-Zafirov update finds that most equity-premium predictors fail out of sample ([GWZ, RFS 2024](https://ideas.repec.org/a/oup/rfinst/v37y2024i11p3490-3557..html)).

The long-only constraint also cuts the transfer coefficient to about 0.3-0.6 ([Clarke, de Silva & Thorley, FAJ 2002](https://rpc.cfainstitute.org/research/financial-analysts-journal/2002/portfolio-constraints-and-the-fundamental-law-of-active-management)). A worked example with the Fundamental Law (IR ≈ TC × IC × √breadth): take IC = 0.04, about 300 effective bets a year and TC = 0.4. That gives an IR of about 0.28, or roughly 2% a year of gross active return at 8% tracking error, before costs. A backtest that shows much more than that in this universe more likely has a bug than an edge.

## Profitability, issuance and earnings-announcement signals hold up after 2015

The Open Source Asset Pricing (OSAP) portfolio data run through December 2025 and show which accounting signals still work ([OSAP](https://www.openassetpricing.com/)). The research team computed the figures below. All are % per month (t-statistic). "Long leg" is the top portfolio minus the average portfolio, which is the part a long-only investor can capture.

| Signal | In-sample | Post-publication | 2015-25 | Ex-microcap, 2015-25 | Long leg, 2015-25 | Monthly hit rate, 2015-25 | Long-only role |
|---|---|---|---|---|---|---|---|
| Gross profitability (GP/assets) | 0.30 (2.4) | 0.89 (2.4) | **0.96 (2.5)** | **0.94 (3.2)** | **0.45 (2.7)** | 61% | Positive selector |
| Cash-based operating profitability | 0.48 (3.3) | 0.54 (1.0) | 0.60 (1.3) | 0.60 (1.4) | **0.58 (2.6)** | 59% | Positive selector |
| R&D-adjusted operating profitability | 0.34 (2.0) | 0.73 (1.4) | 0.82 (1.7) | 0.72 (1.7) | **0.57 (2.6)** | 55% | Positive selector |
| Share issuance, 1 year | 0.69 (4.2) | 0.94 (2.8) | **1.31 (2.8)** | 0.37 (1.3) | 0.28 (1.7) | 64% | Avoid screen |
| External financing (XFIN) | 1.07 (4.7) | 1.23 (3.5) | **1.63 (3.1)** | 0.40 (0.9) | 0.29 (2.0) | 61% | Avoid screen |
| Earnings-announcement return | 1.14 (12.5) | 0.80 (7.3) | 0.40 (2.1) | 0.15 (1.0) | 0.10 (1.1) | 64% | Event tilt |
| Earnings-surprise streak | 1.09 (10.5) | 0.67 (4.4) | **0.65 (3.7)** | 0.36 (1.8) | 0.21 (1.9) | 63% | Positive tilt |
| SUE (standardized earnings surprise) | 1.16 (4.9) | 0.41 (5.1) | 0.11 (0.6) | 0.02 (0.1) | 0.04 (0.4) | 52% | Mostly dead |
| Sales/price | 0.72 (2.9) | 0.81 (3.0) | 0.63 (1.4) | 0.37 (0.8) | 0.25 (1.2) | 55% | Valuation for loss-makers |
| Book-to-market | 0.96 (5.3) | 0.59 (3.5) | 0.30 (1.1) | 0.03 (0.1) | 0.13 (0.7) | 53% | Weak |
| Asset growth | 1.51 (7.8) | 0.49 (1.9) | 0.21 (0.7) | 0.37 (1.3) | -0.39 (-1.1) | 50% | Short-leg only |
| Sloan accruals | 0.69 (6.7) | 0.09 (0.9) | -0.07 (-0.4) | -0.05 (-0.3) | -0.09 (-0.7) | 45% | Dead |
| Net operating assets (NOA) | 1.10 (7.6) | 0.03 (0.1) | -0.02 (-0.1) | 0.38 (1.3) | -0.39 (-1.3) | 46% | Dead |
| Piotroski F-score | 1.05 (3.7) | 0.56 (1.1) | -0.58 (-1.0) | -0.72 (-1.3) | -0.16 (-0.6) | 47% | Dead |
| R&D / market cap | 1.01 (5.8) | 0.20 (0.6) | -0.30 (-0.6) | 0.41 (1.1) | -0.32 (-1.0) | 48% | Dead |

Read across the rows and three groups appear.

**Profitability got stronger after publication.** It is the clearest positive selector, with a long leg of about 0.45-0.58%/month in 2015-25, and it survives outside microcaps.

**Issuance and external financing are very strong but mostly short-side.** After publication, one-year share issuance earned **0.76 (t = 3.5) on the short leg and only 0.18 (t = 1.4) on the long leg**. Most of the spread sits in microcaps, since the ex-microcap 2015-25 figure is about a third of the full-sample one. For this project, avoiding heavy diluters is free alpha, but buying non-issuers is not much of a bet.

**The earnings-announcement family has split.** Raw SUE drift is essentially gone outside microcaps. Martineau finds post-earnings drift has not existed for large stocks since about 2006 ([Martineau, CFR 2022](https://nowpublishers.com/article/Details/CFR-0122)), though rebuttals say it "is alive and well" and the dispute is about research design ([UCLA Anderson Review](https://anderson-review.ucla.edu/is-post-earnings-announcement-drift-a-thing-again)). The announcement-window return and surprise streaks still earn about 0.4-0.65%/month.

Value has two faces. It "replicates" over 1963-present, yet value-weighted book-to-market earned **-0.59%/month (t = -1.5) over 2015-25**. Accruals, NOA, the F-score and R&D/market cap have decayed to zero, consistent with the finding that accrual hedge returns are "no longer reliably positive" ([Green, Hand & Soliman, Management Science 2011](https://ideas.repec.org/a/inm/ormnsc/v57y2011i5p797-816.html)). Distress measures are contested: CHS failure probability earned 0.02%/month over 2009-2025 in OSAP ([OSAP](https://www.openassetpricing.com/)), and CDS-based work even finds a positive distress premium ([AEA 2020](https://aeaweb.org/conference/2020/preliminary/paper/kk4AsyGT)).

For unprofitable growth firms, which make up much of the nuclear, quantum, space and biotech universe, the profitability relation is weak. Fama and French find it strongest among profitable firms ([Dissecting Anomalies, JF 2008](https://www.johnhcochrane.com/s/fama_french_dissecting_anomalies_JF.pdf)). Among loss-makers, book-to-market and revenue-to-price predict returns *more* strongly than among profitable firms ([Mohrschladt & Siedhoff, Abacus 2024](https://ideas.repec.org/a/bla/abacus/v60y2024i4p752-776.html)). Firms with extreme losses show -6.58% post-announcement drift ([NYU working paper](https://archive.nyu.edu/bitstream/2451/27762/2/Post%20Losses%20Announcement%20Drift%2010-2008.pdf)). The practical ranking for loss-makers is therefore EV/sales or revenue/price, plus an issuance avoid screen. Cash runway (cash divided by quarterly burn) is intuitive but has no published test. It likely works through the dilution channel, so treat it as a proxy for issuance and not as a separate factor.

Every signal in the table can be computed from free EDGAR XBRL companyfacts. Examples are `GrossProfit` or revenue minus `CostOfRevenue` over `Assets`, shares from `dei:EntityCommonStockSharesOutstanding`, and XFIN from issuance and repayment cash-flow tags. The data.sec.gov APIs need no authentication and update within about a minute of filing ([SEC EDGAR API docs](https://www.sec.gov/page/sec-api-documentation)).

The critical point-in-time rule is to **never backtest on the `frames` endpoint**. It returns the "last filed" fact, so it bakes in restatements ([SEC EDGAR API docs](https://www.sec.gov/page/sec-api-documentation)). Instead, take each (concept, period) value from the earliest-filed fact, and date it from the filing's `acceptanceDateTime` in the submissions API. For comparison, JKP lag all accounting data by four months ([JKP 2023](https://research-api.cbs.dk/ws/portalfiles/portal/95651880/theis_ingerslev_jensen_et_al_is_there_a_replication_crisis_in_finance_publishersversion.pdf)). Usable XBRL history starts around 2009-2011, which limits any own-data backtest to about 15 years. The announcement-return signal needs the 8-K Item 2.02 timestamp from the submissions API, not XBRL.

## Price signals pay only with cost controls; volatility and short interest are avoid screens

Cross-sectional 12-1 momentum still earns a small premium: **16 bp/month net over 2006-2016**. Frazzini, Israel and Moskowitz found it slightly negative net over 1998-2013. Chen and Velikov find that value-weighting plus buy/hold bands (for example, enter in the top 20% and exit below the top 35%) move momentum "from among the worst performers ... to among the best performers" ([Chen & Velikov 2020](https://www.federalreserve.gov/econres/feds/files/2020039pap.pdf)).

Two cheap fixes, both computable from daily prices, address momentum's main weakness:

- **Volatility scaling:** sizing momentum by its own trailing realized volatility "virtually eliminates crashes and nearly doubles the Sharpe ratio," from 0.53 to 0.97 ([Barroso & Santa-Clara, JFE 2015](https://econpapers.repec.org/RePEc:eee:jfinec:v:116:y:2015:i:1:p:111-120)).
- **Residual momentum:** ranking on returns net of factor exposure also roughly doubles the Sharpe ratio ([Blitz, Huij & Martens](https://core.ac.uk/download/18511704.pdf)).

These matter for this universe because the US momentum factor crashed 28% in 2002 and 54% in 2009 ([Advisor Perspectives](https://www.advisorperspectives.com/commentaries/2017/10/18/can-momentum-investing-be-saved-1)). The high-beta, beaten-down growth names this project holds are exactly the past losers that rip in junk rallies. Industry momentum is strongest at a one-month horizon and is spanned by factor momentum ([Ehsani & Linnainmaa, NBER w25551](https://www.nber.org/papers/w25551.pdf)), so it fits industry rotation. Long-only portfolios capture about half of momentum profits ([Israel & Moskowitz, JFE 2013](https://www.aqr.com/Insights/Research/Journal-Article/The-Role-of-Shorting-Firm-Size-and-Time-on-Market-Anomalies)).

Lottery and volatility signals belong on the avoid side:

- **MAX:** the spread between the lowest- and highest-MAX deciles (MAX = largest daily return in the past month) exceeds **1%/month** ([Bali, Cakici & Whitelaw, JFE 2011](https://www.nber.org/papers/w14804.pdf)).
- **Idiosyncratic volatility:** the negative IVOL-return relation is concentrated among *overpriced*, hard-to-short stocks and is strongest under high sentiment. Among underpriced stocks it turns positive ([Stambaugh, Yu & Yuan, JF 2015](https://www.nber.org/papers/w18560)).

Most names in a quantum/space/crypto-adjacent universe sit in the top IVOL deciles. So the usable rule is conditional: penalize extreme MAX and IVOL only when other signals (heavy issuance, rich valuation, attention spikes, high short interest) also flag the stock as overpriced.

Short interest follows the same pattern. Days-to-cover (short ratio divided by average turnover) earns **1.19%/month equal-weighted but 0.67% value-weighted**, gross, over 1988-2012, and the alpha comes from the short side ([Hong et al., NBER w21166](https://www.nber.org/papers/w21166)). FINRA short interest is free and twice-monthly. It is **published on the 7th business day after settlement**, so a backtest must date each signal at publication ([FINRA](https://www.finra.org/filing-reporting/short-interest/short-interest-reporting-due-dates)). FINRA proposed moving to weekly reporting in May 2026, with approval unconfirmed ([SR-FINRA-2026-012](https://www.finra.org/sites/default/files/2026-05/SR-FINRA-2026-012.pdf)). FINRA's daily Reg SHO short-volume files are a different dataset. FINRA says they "do not equate to short interest," and they are driven largely by market-making ([FINRA Reg SHO](https://www.finra.org/finra-data/browse-catalog/reg-sho-daily)). Daily-shorting strategies earn gross returns that costs wipe out ([summary](https://typeset.io/pdf/short-sale-strategies-and-return-predictability-2esdbz4rk4.pdf)). Use high days-to-cover as an avoid flag and expect squeeze tails in both directions. Amihud illiquidity and dollar volume belong in capacity and cost filters, not the alpha score.

Market-level timing deserves even less trust. In GWZ's 2024 update, the term spread has an out-of-sample R² of 0.02%, default spreads -0.11% and -0.34%, and Martin's VIX-based SVIX -2.90% ([Ivo Welch summary](https://www.ivo-welch.org/home/card-eqpredict.html)). All of these are free from FRED and all fail as monthly return forecasts. Use them as regime and risk displays. Two candidates have better records:

- **Variance risk premium (VIX² minus realized variance):** explained over 15% of *quarterly* excess-return variation in 1990-2005 ([Bollerslev, Tauchen & Zhou](https://www.federalreserve.gov/pubs/feds/2007/200711/index.html)). Its post-2009 out-of-sample performance is unverified.
- **Time-series momentum:** the past 12-month return predicts the next month's for equity indices and does best in extreme markets ([Moskowitz, Ooi & Pedersen 2012](https://papers.ssrn.com/abstract=2089463)).

Trend rules on sector ETFs are the most defensible trigger for the project's safe-haven sleeve, and they control drawdowns more than they add return. Same-calendar-month seasonality earns about 13%/year gross ([Keloharju, Linnainmaa & Nyberg](https://www.nber.org/papers/w20815.pdf)). It needs five or more years of history, which most recent IPOs and SPACs in this universe lack.

## Most of the project's alternative-data signals fail at monthly horizons

The table gives a verdict on each signal the project already tracks, with recommended weight.

| Tracked signal | Evidence verdict | Horizon where it works | Recommended role |
|---|---|---|---|
| Insider open-market purchases (Form 4, code P, opportunistic) | Works, smaller than classic estimates | 1-5 days after filing | Tilt or tie-breaker |
| Insider sales, routine trades | No information | — | Near-zero weight |
| Congressional trades | Fails for copying from disclosure | — | Display only; leaders-only research flag |
| Wikipedia page views | Weak; rises then likely reverses | About 1 week | Contrarian flag after run-ups |
| GDELT news tone | Days-long pressure, then reversal | 1-5 days | Change-in-tone only; low weight |
| Filing-text change (Lazy Prices) | Works; slow diffusion | Months | Core slow signal |
| Filing "bottleneck" language | No published test found | Unknown | Experimental; must earn weight on own data |
| arXiv activity | No published test found | Unknown | Experimental; display only |
| Patents / innovative efficiency | Works, slow | 1-12 months | Possible slow input |
| Government contracts | Small announcement effect | ±1 day | Material awards only (≥ about 5% of revenue) |
| Federal Register events | No evidence as stock picker | Event days | Context display |

**Insider buying.** Insider purchases carry real but short-lived information. Cohen, Malloy and Pomorski split insiders into "routine" traders (who trade in the same month every year) and opportunistic ones. Opportunistic trades earn **82 bp/month value-weighted**, while routine trades earn about zero, over 1986-2007 ([NBER w16454](https://www.nber.org/papers/w16454)). Sales carry essentially nothing ([Jeng, Metrick & Zeckhauser](https://scholar.harvard.edu/sites/scholar.harvard.edu/files/rzeckhauser/files/insider_trading.pdf)). A recent study on free EDGAR data matches this project's setup: 7,405 officer purchase signals over 2022-2026, excluding 10b5-1 plan trades and entering the session after filing. It finds **+0.53% after 1 day (t = 6.5) and +1.01% after 5 days (t = 5.1)**, but an insignificant +0.98% at 21 days (t = 1.7) and +1.10% at 63 days. Cluster buying added nothing significant ([QuantInsti](https://blog.quantinsti.com/sec-form-4-insider-trading-python-event-study/)). That study is a practitioner replication, not peer-reviewed. A monthly rebalance captures little of this edge. Insider buying should be a weekly event trigger or tie-breaker, and the 10b5-1 flag should be used to drop planned trades.

**Congressional trades.** These are the weakest of the project's signals. Post-STOCK Act, senators' purchases *underperform* at one month, and even top-percentile members look like random stock pickers ([Belmont et al., JPubE 2022](https://ideas.repec.org/a/eee/pubeco/v207y2022ics0047272722000044.html)). Covering all members over 2012-2023, Chen and Sacerdote find portfolios "underperform or, at best, match market benchmarks," with timing that follows retail social-media sentiment ([NBER w35041](https://www.nber.org/papers/w35041)). The one bullish result: members who rise to leadership outperform peers by **47 percentage points a year after ascension**, partly by buying firms that later win more government contracts ([Wei & Zhou, NBER w34524](https://www.nber.org/papers/w34524)). That paper does not test returns from the disclosure date, which can lag the trade by up to 45 days. The outperformance of the NANC ETF (93% since launch against 79% for SPY through May 2026) fits a mega-cap tech tilt better than information ([24/7 Wall St](https://247wallst.com/investing/2026/05/16/nanc-traders-beat-the-crowd-by-33-points-and-the-difference-keeps-growing/)). Congressional trades should get zero model weight. A leaders-only, disclosure-dated, factor-adjusted test is the only version worth running.

**Attention signals.** Higher Google search volume predicts higher prices over two weeks and a **reversal within the year** ([Da, Engelberg & Gao, JF 2011](https://rady.ucsd.edu/faculty/directory/engelberg/pub/portfolios/GOOGLE.pdf)). The effect is significant only among smaller stocks ([NBER w23274](https://www.nber.org/papers/w23274.pdf)). Wikipedia has one positive recent paper: rising views predict higher returns with unexplained alpha ([Pyun, Economics Letters 2024](https://ideas.repec.org/a/eee/ecolet/v241y2024ics0165176524003203.html)), and a secondary summary says weekly rebalancing beats monthly. Other work finds that hourly views spike *after* big daily moves, so attention follows returns ([Ungeheuer](https://madoc.bib.uni-mannheim.de/45292)). For a monthly book, an attention spike after a run-up is a mild warning, not a buy signal. Measure it as abnormal attention, for example log this week's views minus log of the prior eight-week median.

**News tone.** Tetlock's media pessimism predicts downward market pressure followed by reversion to fundamentals ([Tetlock, JF 2007](https://www.columbia.edu/~pt2238/papers/Tetlock_Media_Sentiment_JF.pdf)). Media sentiment predicts returns mainly in recessions ([Garcia, JF 2013](https://leeds-faculty.colorado.edu/garcia/paper86v12.pdf)). No peer-reviewed study of firm-level GDELT tone for US stocks turned up. GDELT's coarse entity matching and dictionary tone add noise, so use only the 1-5 day *change* in tone, at low weight.

**Contracts and regulation.** Contract awards show small positive announcement returns, concentrated in aerospace and defense and in firms where the award is material ([Palkar, Larson & Larson 2012](https://ideas.repec.org/a/taf/apfiec/v22y2012i2p147-164.html); [HEC Montréal 2024](https://biblos.hec.ca/biblio/memoires/yunianti_priska_m2024.pdf)). A 2024 pharma study calls the effect limited ([IDEAS](https://ideas.repec.org/a/bba/j00001/v3y2024i1p1-26d131.html)). Regulatory *exposure* is a priced characteristic: the top-decile "regulatory operating leverage" stocks earn 5-7% a year more, read as compensation for risk ([Advisor Perspectives](https://www.advisorperspectives.com/articles/2021/05/03/high-regulatory-costs-drive-higher-stock-returns)). Raw Federal Register counts, however, treat every rule as equal regardless of direction or economic significance ([Fed IFDP 1433](https://www.federalreserve.gov/econres/ifdp/files/ifdp1433.pdf)). No study tests Federal Register timing as a stock-level predictor.

**Filing-text signals.** Filing text is the strongest free signal the project already touches. In "Lazy Prices," firms that substantially change their 10-K or 10-Q language later underperform. Buying non-changers and shorting changers earned **up to 188 bp/month of five-factor alpha** over 1995-2014, with no announcement-date reaction. The most predictive changes concern executives, litigation and risk factors ([Cohen, Malloy & Nguyen, JF 2020](https://www.nber.org/papers/w25084)). Because the market takes months to react, the signal suits monthly rebalancing. With typical post-publication decay, plan on well under half the in-sample alpha.

The project's "bottleneck" language extraction has no published test. Similarity of Item 1A against the same filing type a year earlier is the validated version of filing text. Bottleneck keywords should be treated as a hypothesis whose IC must be measured on the project's own data. Patents scaled by R&D ("innovative efficiency") positively predict returns ([Hirshleifer, Hsu & Li, JFE 2013](https://ideas.repec.org/a/eee/jfinec/v107y2013i3p632-654.html)), but the signal is slow and lagged. No credible study of arXiv counts and stock returns was found.

## Validate with IC decay curves, deflated Sharpe ratios and delisting-aware backtests

The project's universe has hundreds of names and about 10-15 years of point-in-time data, so validation noise is the main risk. Even a 30-stock IC can swing about ±0.35 by chance ([FAJ 1983](https://rpc.cfainstitute.org/en/research/financial-analysts-journal/1983/problems-in-measuring-the-quality-of-investment-information-the-perils-of-the-information-coef)). Harvey, Liu and Zhu argue a new factor needs **t > 3, not 2**, after accounting for industry-wide data mining ([NBER w20592](https://nber.org/papers/w20592)). For the project's own search, the deflated Sharpe ratio is the right tool. It tests the observed Sharpe against the expected maximum Sharpe of N unskilled trials and adjusts for skew, kurtosis and sample length, so N must count every variant tried ([Deflated Sharpe ratio](https://en.wikipedia.org/wiki/Deflated_Sharpe_ratio)). That requires a written log of every variant.

When forward-return windows overlap, for example 21-day returns sampled weekly, use purged and embargoed cross-validation. Combinatorial purged CV then gives a distribution of out-of-sample paths instead of a single backtest ([skfolio CPCV](https://skfolio.org/generated/skfolio.model_selection.CombinatorialPurgedCV.html)). Benchmark out-of-sample R² against a zero forecast, not the historical mean, which inflates it ([GKX](https://www.nber.org/papers/w25398.pdf)). Delisted stocks must stay in the sample. Missing delisting returns are large and negative ([Shumway, JF 1997](https://ideas.repec.org/a/bla/jfinan/v52y1997i1p327-40.html)), and **-55% is the standard Nasdaq correction** for performance-related delistings ([Shumway & Warther, JF 1999](https://ideas.repec.org/a/bla/jfinan/v54y1999i6p2361-2379.html)). The project's failure ledger already supports this. Run backtests under both the ledger values and a -55% imputation, and require conclusions to survive both.

For combining signals, the evidence favors simple methods at this scale. Gu, Kelly and Xiu find that nonlinear models roughly double long-short Sharpe over linear ones: NN4 reaches 1.35 value-weighted against 0.61 for 3-variable OLS. But the gains come from fast price, liquidity and volatility interactions, with **110-130% monthly turnover**, before costs. Shallow models beat deep ones as data shrinks, and an equal-weight ensemble of methods was among the best ([GKX](https://www.nber.org/papers/w25398.pdf)). With a few hundred names, the sensible default is:

1. Winsorize or rank each signal.
2. Neutralize within sector so the composite is not a hidden sector bet.
3. Sign-align each signal so higher is better, and set missing values to the sector median.
4. Average with equal weights, or with IC weights shrunk heavily toward equal.

Apply the avoid screens (dilution, extreme MAX and IVOL among overpriced names, high days-to-cover) as exclusions before ranking, not as negative weights. Use buy/hold bands, for example buy in the top 10% and hold until the name leaves the top 20%. This is the most effective simple cost control ([Novy-Marx & Velikov](https://mysimon.rochester.edu/novy-marx/research/ToAatTC.pdf)). ML becomes a challenger only once it beats this composite out of sample, net of costs.

The dashboard should extend the Alphalens tear sheet ([alphalens-reloaded](https://github.com/stefan-jansen/alphalens-reloaded/blob/main/src/alphalens/tears.py)) with Barra-style exposure and attribution views ([MSCI Barra](https://www.msci.com/resources/factsheets/Barra_Analytics_on_FactSet.pdf)). Its central panel should be a **signal scorecard** with one row per signal plus the composite. Columns:

- mean rank IC at 5, 21 and 63 days;
- IC IR and Newey-West t-statistic;
- percentage of periods with positive IC;
- top-quintile return minus the universe, gross and net;
- monthly turnover;
- number of variants tried and deflated Sharpe;
- trailing 12-month IC;
- an evidence-grade badge from the literature (survives / short-leg only / unproven).

Supporting panels:

- **IC decay curve**, to justify weekly versus monthly rebalancing.
- **IC time series with a monthly heatmap**, to show which regimes each signal works in.
- **Signal correlation matrix**, to show whether the composite really adds breadth.
- **Portfolio exposures against a small-cap growth benchmark** (size, momentum, beta, volatility, sector), to catch unintended bets.
- **Per-stock factor-contribution waterfall** (z-score × weight), which plugs directly into the existing Model Decisions tab.
- **Data-quality panel** covering coverage, missing values, delisting imputations and point-in-time checks.

## Conclusion

The literature changes the question this project should ask. Asking which signals predict winners in volatile growth stocks yields a short list. Asking which signals identify the stocks to *avoid*, and which positive selectors are cheap enough to hold, yields a long one. For a long-only, free-data system, most of the realistic edge comes from three things: refusing to own serial diluters, lottery-like spikes and crowded shorts; tilting toward profitability, earnings-announcement strength and stable filing language; and controlling momentum and turnover so costs don't consume the rest. The project's distinctive alternative-data feeds (Congress, Wikipedia, GDELT, arXiv, Federal Register, bottleneck language) are worth keeping as dashboard context and as hypotheses, but on current evidence none deserves model weight until it clears an out-of-sample, deflated test on the project's own point-in-time data.

The literature also leaves the largest uncertainty unaddressed. No source tested any of these signals inside nuclear, quantum, space, EV or crypto-adjacent stocks specifically, and many of these firms are too young for long-history signals. The project's PIT EDGAR, price and failure-ledger store is better placed to answer that than any published paper. The first deliverable should be the signal scorecard computed on this universe, with every signal held to the same bar, including the ones the project is most excited about.
