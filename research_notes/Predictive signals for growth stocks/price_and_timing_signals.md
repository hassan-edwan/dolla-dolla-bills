# Price, Volume, Short-Interest and Market-Timing Return Predictors (US equities)

Scope note: These notes come from about 17 searches and fetches. Where a number could not be checked against a primary or near-primary source this session, it is marked "UNVERIFIED (background knowledge)" and kept out of Cited Findings. The report writer should treat those as leads, not facts.

## Q0. Cross-cutting: how much survives publication, costs and the post-2005 trading era?

### Takeaway
The average published anomaly earns about 66 bps/month gross in-sample. Net of spreads it earns 38 bps. Net and post-publication it earns 13 bps. Net, post-publication and post-2005 it earns 8 bps, and short-sale fees (10-20 bps/month) would wipe that out. Price/trading signals (momentum, IVOL, volume) are high-turnover and sit in the worst tail before cost mitigation. Expect small, noisy edges, not the 1%/month headline numbers.

### Cited Findings
- Chen & Velikov, 120 anomalies with effective bid-ask spreads: 66 bps/month gross in-sample, 38 bps net in-sample (after cost optimization), 13 bps net post-publication, 8 bps net post-publication and post-2005. Short-sale costs of 10-20 bps/month "would wipe out the remaining profits." The strongest anomalies return only 10-20 bps after data-mining adjustment — [Chen & Velikov, "Zeroing in on the Expected Returns of Anomalies", FEDS 2020-039](https://www.federalreserve.gov/econres/feds/files/2020039pap.pdf)
- Same paper: only 9% of post-pub/post-2005 net-return t-stats exceed 2.0 in absolute value. Even the 90th-percentile anomaly has an expected return of about 20 bps/month after shrinkage. Standard errors on individual anomalies are 30-60 bps/month, so "it is impossible to tell if any individual anomaly has strong performance in the modern era" — [Chen & Velikov 2020](https://www.federalreserve.gov/econres/feds/files/2020039pap.pdf)
- Same paper: 12-month momentum (Mom12m) nets 16 bps/month post-2005 (2006-2016). Size nets -26 bps and B/M 33 bps. Frazzini-Israel-Moskowitz (2015) found momentum's net return slightly negative over 1998-2013 — [Chen & Velikov 2020](https://www.federalreserve.gov/econres/feds/files/2020039pap.pdf)
- Same paper: high-turnover anomalies (Mom12m, Mom6Jnk, IdioVol, detrended volume) occupy "the vast majority of the left tail" of net returns under the academic implementation. Value-weighting plus buy/hold bands (e.g., enter top 20%, exit below top 35%) move momentum "from among the worst performers ... to among the best performers," and also rescue IdioVol — [Chen & Velikov 2020](https://www.federalreserve.gov/econres/feds/files/2020039pap.pdf)
- Momentum for young firms (MomYoung), cash-flow/price and tangibility had post-pub/post-2005 net returns above 80 bps/month, but the authors attribute much of that to data-mining luck — [Chen & Velikov 2020](https://www.federalreserve.gov/econres/feds/files/2020039pap.pdf)
- McLean & Pontiff (JF 2016): anomaly returns are 26% lower out-of-sample and 58% lower post-publication. The decline is larger for predictors with higher in-sample returns — [McLean & Pontiff 2016 (PDF)](https://Www.Gwern.net/doc/economics/2016-mclean.pdf); [Ivey summary](https://ivey.uwo.ca/media/3775549/pontiff.pdf)
- Jacobs & Müller (241 anomalies, 39 markets): the US is the only country with a reliable post-publication decline, about 62% equal-weighted and 66% value-weighted. Part of it is a general time trend — [Jacobs & Müller](https://www.wiwi.hu-berlin.de/en/Professorships/bwl/finance/seminars/papers-fin-acc-res-seminars/17s/jacobs.pdf)
- Chen & Zimmermann: publication bias is too small to explain the post-publication decline — [Chen & Zimmermann, FEDS 2018-033](https://www.federalreserve.gov/econres/feds/files/2018033pap.pdf)
- A 2025 study using the Chen-Zimmermann (Open Source Asset Pricing) dataset finds anomaly returns and CAPM alphas decline post-publication but "remain economically strong and statistically significant" (gross of costs) — [Out-of-Sample Alphas, ASU 2025](https://finance-conference.wpcarey.asu.edu/sites/default/files/2025-02/Out-of-Sample_Alphas_%282025-02-12%29_with_link.pdf)
- Momentum has the highest trading costs among the classic factors, about 48.4 bps/month versus about 5-6 bps for size and value, in one cost study summarized by Alpha Architect — [Alpha Architect, transaction costs](https://alphaarchitect.com/trading-costs-destroy-factor-investing/)
- The US momentum factor suffered crashes of 28% (2002) and 54% (2009) and remained underwater versus its 2007 (and even 1999) peak as of about 2017 — [Advisor Perspectives 2017](https://www.advisorperspectives.com/commentaries/2017/10/18/can-momentum-investing-be-saved-1)

### Inferences
- For a small/mid-cap high-volatility growth universe, effective spreads and borrow fees are well above the cross-sectional average. Gross academic long-short spreads should therefore be discounted heavily. A realistic prior is 0-30 bps/month net for any single price signal, so signals are better used as tilts or filters inside a long-only book than as standalone long-short strategies.
- Cost mitigation (value-weighting, buy/hold bands, slower rebalancing) matters as much as signal choice for momentum and IVOL-type signals.

### Gaps
- No source found giving post-2010 net returns for momentum specifically within US small caps. Chen-Velikov's post-2005 window ends in 2016. Open Source Asset Pricing data (openassetpricing.com) would allow a direct computation through 2023-24, but it was not fetched here.

## Q1. Momentum family (12-1, industry, residual, 52-week high, short-term reversal, time-series/trend, intermediate) and crashes

### Takeaway
Cross-sectional 12-1 momentum still has a positive but small and noisy net premium post-2005 (about 16 bps/month in Chen-Velikov, about 0 in Frazzini-Israel-Moskowitz 1998-2013). It is prone to severe crashes in rebounds after bear markets. Volatility scaling roughly doubles the Sharpe ratio and largely removes crashes. Residual momentum also roughly doubles the Sharpe ratio by cutting factor exposure. Both are directly computable from daily prices.

### Cited Findings
- 12-1 momentum post-2005 net: 16 bps/month (2006-2016). Momentum becomes among the best net performers only with value-weighting and buy/hold bands — [Chen & Velikov 2020](https://www.federalreserve.gov/econres/feds/files/2020039pap.pdf)
- Risk-managed momentum (Barroso & Santa-Clara, JFE 2015): scaling momentum exposure by its own trailing realized volatility "virtually eliminates crashes and nearly doubles the Sharpe ratio," from 0.53 to 0.97 over 1927-2011 — [Barroso & Santa-Clara (RePEc)](https://econpapers.repec.org/RePEc:eee:jfinec:v:116:y:2015:i:1:p:111-120); [Barroso PDF](https://blog.iese.edu/financeseminars/files/2017/09/Barroso.pdf); [CFA Institute blog](https://blogs.cfainstitute.org/blog/2018/01/17/timing-the-market-momentum-and-beyond)
- Daniel & Moskowitz (2016) dynamic momentum manages time-varying skewness, and later work builds on it to "tame" crashes — [Bianchi et al. 2022, Taming momentum crashes](https://strathprints.strath.ac.uk/90217/1/Bianchi-etal-SSRN-2022-Taming-momentum-crashes.pdf)
- Residual momentum (Blitz, Huij & Martens, JEF 2011): ranking on residual returns from a Fama-French regression instead of total returns cuts time-varying factor exposures, giving roughly double the Sharpe ratio of total-return momentum, mainly through lower volatility. A later paper reports a US Sharpe ratio of 0.59 for standard residual momentum and 1.23 for a beta-neutral version — [Blitz-Huij-Martens via core.ac.uk](https://core.ac.uk/download/18511704.pdf); [Grobys & Kolari 2019](https://osuva.uwasa.fi/bitstream/10024/11757/2/Osuva_Grobys_Kolari_2019.pdf)
- Industry momentum (Moskowitz & Grinblatt 1999): past industry returns predict industry returns, most strongly at the one-month horizon, and industry momentum accounts for much of stock momentum. Later work finds industry momentum is spanned by factor momentum — [Arnott-type review / repositorio.ucp.pt](https://repositorio.ucp.pt/bitstreams/185837aa-e37e-433f-ac1a-0d5d79027b8f/download); [Ehsani & Linnainmaa, Factor Momentum, NBER w25551](https://www.nber.org/papers/w25551.pdf)
- Time-series momentum (Moskowitz, Ooi & Pedersen, JFE 2012): in 58 liquid futures (including equity indices), the past 12-month excess return positively predicts the next month's return. The effect lasts about a year and then partially reverses. The diversified portfolio performs best in extreme markets. Data for 1985-2009 is free from AQR — [MOP 2012, SSRN](https://papers.ssrn.com/abstract=2089463); [AQR TSMOM data](https://www.aqr.com/insights/datasets/time-series-momentum-original-paper-data)
- Momentum and short-term reversal sit in the Chen-Velikov replication list ("Short term reversal", "Intermediate Momentum", "52 week high", "Industry Momentum", "Momentum and Volume"), and the high-turnover price signals mostly lose money net under naive implementation — [Chen & Velikov 2020](https://www.federalreserve.gov/econres/feds/files/2020039pap.pdf)

### Inferences
- UNVERIFIED (background knowledge): Daniel & Moskowitz (JFE 2016) document that momentum crashes happen in "panic states" after market declines with high volatility, when the market rebounds and past losers (high-beta junk) rally. Examples are 1932 and spring 2009, when the winner-minus-loser portfolio lost around 70-80% within months. Volatile growth names in small caps (biotech, EV, crypto-adjacent, space, quantum) are exactly the high-beta losers that rip in such rebounds (e.g., Nov 2020 vaccine rotation, early 2021 meme rally, Nov 2022-Jan 2023 junk rally). A momentum tilt in that universe carries amplified crash risk.
- UNVERIFIED (background knowledge): George & Hwang (JF 2004) found that nearness to the 52-week high explains most momentum profits and does not reverse long-term. Jegadeesh (1990) and Lehmann (1990) document a one-month reversal, which is largely a liquidity-provision effect that is hard to capture net of costs in small caps. Novy-Marx (2012) shows that 12-7 "intermediate" returns drive momentum more than 6-2 returns. Confirm the numbers from the original papers before using them.
- Long-only usefulness: winner-only (long-leg) momentum avoids the short-side crash mechanism (shorted losers rallying), but a long-winners book still suffers in junk rebounds through relative underperformance. Volatility scaling and residualizing are cheap fixes computable from daily OHLCV.
- Computation from free daily data: 12-1 = cumulative return from t-252 to t-21 trading days. Residual momentum = sum of residuals from a rolling 36-month regression on market (and optionally size/value factors from Ken French's free library), scaled by residual standard deviation. 52-week-high proximity = Close / max(High over 252 days). Short-term reversal = return over the last 21 days. Industry momentum = cap-weighted 12-1 return of the stock's industry. Vol-managed momentum: scale weights by target vol / trailing 126-day realized vol of the momentum portfolio.

### Gaps
- No primary source fetched for Daniel-Moskowitz crash magnitudes, George-Hwang effect size, short-term reversal effect sizes post-2010, or intermediate momentum.
- No sourced evidence that momentum works specifically in tech, biotech, EV or quantum small caps post-2010.
- No rank-IC estimates found for these signals.

## Q2. Low volatility / BAB / IVOL puzzle / MAX: long-leg or short-leg?

### Takeaway
The IVOL and MAX effects are mainly short-leg effects. They are concentrated in overpriced, hard-to-short, high-volatility lottery stocks favored by retail investors, and they are strongest under high sentiment. For volatile growth stocks this works as a warning or avoid filter (high-MAX, high-IVOL names have low expected returns), not as a source of long alpha. BAB's net-of-cost alpha is disputed.

### Cited Findings
- Stambaugh, Yu & Yuan (JF 2015): the negative IVOL-return relation is concentrated among overpriced stocks, especially those less easily shorted. Among underpriced stocks the IVOL-return relation is positive. The negative effect dominates in aggregate because of arbitrage asymmetry. High sentiment strengthens the negative relation among overpriced stocks — [SYY, NBER w18560](https://www.nber.org/papers/w18560); [JF version (RePEc)](https://econpapers.repec.org/RePEc:bla:jfinan:v:70:y:2015:i:5:p:1903-1948)
- MAX effect (Bali, Cakici & Whitelaw, JFE 2011): the difference in average raw and risk-adjusted returns between the lowest- and highest-MAX deciles (MAX = maximum daily return in the prior month) exceeds 1% per month, and it survives controls for size, value, momentum and short-term reversal — [BCW NBER w14804](https://www.nber.org/papers/w14804.pdf); [Alpha Architect summary](https://alphaarchitect.com/hot-off-the-jfe-press-maxing-out-your-returns/)
- An alternative reading is that post-MAX underperformance reflects overreaction and occurs generally, not only in ex-ante lottery-like stocks — [Gorman et al., Critical Finance Review 2022](https://cfr.ivo-welch.info/published/papers/gorman2021could.pdf)
- High-MAX stocks have low institutional ownership, so they mainly attract individual investors — [Fong 2014 chapter (IDEAS)](https://ideas.repec.org/h/pal/palchp/978-1-137-38173-6_7.html)
- BAB: Novy-Marx & Velikov (JFE 2022) argue that BAB's net-of-cost returns come from tilts toward profitability and investment, and that Frazzini-Pedersen's non-standard beta estimation drives the results. A summary says BAB's 5-factor alpha is insignificant after costs. Rebuttals argue the cost estimates are overstated — [Novy-Marx & Velikov, BABAB](https://mysimon.rochester.edu/novy-marx/research/BABAB.pdf); [RePEc](https://econpapers.repec.org/RePEc:eee:jfinec:v:143:y:2022:i:1:p:80-106); [Alpha Architect, BAB construction](https://alphaarchitect.com/betting-against-beta-bab-construction/)
- Idiosyncratic volatility is a high-turnover anomaly in the left tail of net returns under naive implementation, and it is "significantly improved" by value-weighting and buy/hold bands — [Chen & Velikov 2020](https://www.federalreserve.gov/econres/feds/files/2020039pap.pdf)

### Inferences
- In a universe of volatile small/mid-cap growth names, most stocks sit in the high-IVOL/high-MAX deciles. The evidence implies low average risk-adjusted returns there, especially among names that also look overpriced on other signals (high valuation, high issuance, high retail attention, high short interest). A practical use is to down-weight or avoid stocks with an extreme recent single-day jump (MAX) and high IVOL unless other signals mark them as underpriced, per SYY's positive IVOL relation among underpriced stocks.
- Since the alpha is mostly in the short leg and the hardest-to-short names, a long-only investor captures it mainly by avoidance, which costs nothing to implement.
- Computation: IVOL = standard deviation of daily residuals from a 1-month (or 3-month) regression on market (FF3 factors from the Ken French library). MAX = max daily return over the past 21 days (or the average of the top 5 days). Beta = 1-year daily or 5-year monthly regression, with Frazzini-Pedersen-style shrinkage.

### Gaps
- No post-2010 MAX or IVOL effect sizes were sourced. The original Ang-Hodrick-Xing-Zhang (2006) IVOL spread was not fetched.

## Q3. Liquidity (Amihud), turnover, volume shocks

### Takeaway
Little was sourced this session. Chen-Velikov list Amihud illiquidity, share-turnover volatility and detrended volume among replicated anomalies. Turnover was the only reliable in-sample predictor of which anomalies survive post-2005: higher turnover means worse net performance. Volume signals are high-turnover and cost-sensitive.

### Cited Findings
- Amihud's illiquidity, share turnover volatility and detrended trading volume (VolumeTrend) are in the 120-anomaly replication set. VolumeTrend is a high-turnover, left-tail net performer under naive implementation — [Chen & Velikov 2020](https://www.federalreserve.gov/econres/feds/files/2020039pap.pdf)
- Anomaly turnover is the only in-sample characteristic that reliably predicts post-pub/post-2005 net returns, though the top quartile yields only about 14 bps/month — [Chen & Velikov 2020](https://www.federalreserve.gov/econres/feds/files/2020039pap.pdf)

### Inferences
- UNVERIFIED (background knowledge): Amihud (2002) ILLIQ = average of |daily return| / daily dollar volume, which is computable from OHLCV. Illiquid stocks earn a premium in the cross-section, but that premium accrues to the hardest-to-trade names, so it is largely uncapturable after impact costs. Gervais, Kaniel & Mingelgrin (2001) found that abnormally high volume over a short window predicts higher subsequent returns ("high-volume return premium"). Confirm both before citing.
- Practical role for a growth-stock book: use Amihud and dollar-volume as capacity and cost filters, not alpha signals.

### Gaps
- No sourced effect sizes or post-2010 evidence for Amihud, turnover or abnormal volume.

## Q4. Short interest: days-to-cover, changes, FINRA daily short volume vs bi-monthly short interest; data availability and lag

### Takeaway
Days-to-cover (short interest / shares outstanding, divided by average daily turnover) is the best-documented short-interest predictor. It earns 1.19%/month equal-weighted long-short gross (1988-2012) but only 0.67% value-weighted, and the alpha comes from the short side. FINRA short interest is free, twice monthly, and published about 7 business days after settlement, so signals must be lagged accordingly. FINRA daily short sale volume is a different, noisier dataset (heavily market-maker driven, not positions). It has some predictive power but is cost-limited.

### Cited Findings
- Hong, Li, Ni, Scheinkman & Yan: DTC = short ratio / average daily share turnover is a better predictor of poor returns than the short ratio. A long-short DTC strategy earns about 1.2% (1.19%) per month equal-weighted versus 0.71% for the short ratio. It earns 0.67% value-weighted. Sample 1988-2012, gross of trading and borrowing costs — [NBER w21166](https://www.nber.org/papers/w21166); [CXO Advisory summary](https://www.cxoadvisory.com/short-selling/days-to-cover-short-interest-as-a-stock-return-predictor)
- Chen-Velikov replicate a "ShortInterest" anomaly and "Inst own among high short interest" — [Chen & Velikov 2020](https://www.federalreserve.gov/econres/feds/files/2020039pap.pdf)
- FINRA Rule 4560: member firms report short positions in all equity securities twice monthly. Settlement dates fall mid-month (the 15th, or the prior settlement day) and at month-end. Reports are due by 6 p.m. ET on the 2nd business day after the settlement date. Data is published on the 7th business day after settlement (e.g., 2026: Jan 15 settlement, Jan 20 due, Jan 27 published) — [FINRA Short Interest Reporting](https://www.finra.org/filing-reporting/short-interest); [FINRA due dates](https://www.finra.org/filing-reporting/short-interest/short-interest-reporting-due-dates)
- FINRA Equity Short Interest data is available through an interactive grid on finra.org for five rolling years by settlement date — [FINRA Equity Short Interest catalog](https://www.finra.org/finra-data/browse-catalog/equity-short-interest)
- In a May 2026 rule filing (SR-FINRA-2026-012), FINRA proposed raising reporting and dissemination frequency from twice-monthly to weekly. Approval status was not confirmed — [SR-FINRA-2026-012](https://www.finra.org/sites/default/files/2026-05/SR-FINRA-2026-012.pdf); [SEC notice 34-105482](https://www.sec.gov/files/rules/sro/finra/2026/34-105482.pdf)
- FINRA Daily Short Sale Volume files (Reg SHO, off-exchange/TRF trades) are posted by 6:00 p.m. ET on the trade date. FINRA says they do not equate to short interest — [FINRA Reg SHO Daily](https://www.finra.org/finra-data/browse-catalog/reg-sho-daily)
- Daily short volume is heavily driven by market-making and is not netted against intraday buying — [Nasdaq, what to know about short selling](https://www.nasdaq.com/articles/what-you-should-know-about-short-selling)
- Studies of 2010-2015, when FINRA published daily short volume, find shorting flows remain a significant predictor of negative future returns — [Lehigh (Yan) research](https://www.lehigh.edu/~xuy219/research/Short_Final_Version.pdf)
- At the market level, a one-standard-deviation increase in aggregate daily shorting predicts market excess returns up to 36 bps lower over the next 10 trading days — [Aggregate shorting, JFM (Lehigh)](https://www.lehigh.edu/~xuy219/research/Aggshort_JFM.pdf)
- A strategy based on daily shorting activity (2005 Nasdaq data) earns significant gross returns, but costs wipe out profits — [typeset summary, short sale strategies and return predictability](https://typeset.io/pdf/short-sale-strategies-and-return-predictability-2esdbz4rk4.pdf)

### Inferences
- For long-only growth investors, the main use is avoidance: high DTC flags crowded shorts with poor expected returns. In small-cap meme/volatile names, high DTC also raises squeeze risk (e.g., Jan 2021), so the realized distribution is fat-tailed in both directions.
- Lag discipline: a signal using mid-month short interest can only be traded about 7 business days later, so backtests must date the signal at publication, not settlement.
- Computation: SI ratio = short interest / shares outstanding (shares from SEC XBRL dei:EntityCommonStockSharesOutstanding). DTC = SI / average daily volume over the prior 1 month (equivalently, SI ratio / average turnover). Change in SI = SI_t / SI_{t-1} - 1 over successive reports. Daily short-volume ratio = ShortVolume / TotalVolume from Reg SHO files, but only covers FINRA TRF off-exchange volume, not all exchanges.

### Gaps
- No post-2012 DTC performance or net-of-borrow-cost estimates were found.
- Whether FINRA's historical short interest files before the rolling 5 years are free was not confirmed. Pre-2021 exchange-level short interest histories (Nasdaq/NYSE) may not be freely available.

## Q5. Market/industry timing (time-series predictors)

### Takeaway
The 2024 Goyal-Welch-Zafirov update (data to end-2021, 46 variables) finds that most predictors lost in-sample significance or fail out-of-sample. Term spread (OOS R² about 0.02%), default spreads (OOS R² -0.11% and -0.34%) and VIX-based Martin (OOS R² -2.9%) all fail. The few survivors are mostly annual or quarterly accounting/macro aggregates. The variance risk premium has the best quarterly-horizon evidence in its own paper. Time-series momentum or trend has the best practical record, mainly as drawdown control. Realistic monthly OOS R² is about 0-1%.

### Cited Findings
- Goyal, Welch & Zafirov (RFS 2024, "A Comprehensive 2022 Look"): re-examine 29 variables from 26 post-2008 papers plus the original 17, using data to end-2021. Over a third lose in-sample significance, about half of the rest perform poorly OOS, and "the predictive performance remains disappointing" — [RFS 37(11) 3490-3557 (IDEAS)](https://ideas.repec.org/a/oup/rfinst/v37y2024i11p3490-3557..html); [SFI summary](https://www.sfi.ch/en/publications/a-comprehensive-2022-look-at-the-empirical-performance-of-equity-premium-prediction); [SSRN 3929119](https://ssrn.com/abstract=3929119)
- Per the authors' summary page: survivors with significant positive OOS R² include Hirshleifer-Hou-Teoh aggregate accruals (annual, OOS R² 16.68% / 12.49%), aggregate cash flow (5.16%), Cochrane investment/capital (quarterly, 2.26%) and Møller-Rangvid 4th-quarter consumption growth (4.86%) — [Ivo Welch card](https://www.ivo-welch.org/home/card-eqpredict.html)
- Same page: Fama-French term spread (tms) has in-sample t = 1.11 and OOS R² = 0.02%. Default yield spread (dfy) has OOS R² = -0.11%, default return spread (dfr) -0.34%. Martin's SVIX has in-sample t = 1.69 but OOS R² = -2.90%. Trend and moving-average rules are not evaluated — [Ivo Welch card](https://www.ivo-welch.org/home/card-eqpredict.html)
- Variance risk premium (Bollerslev, Tauchen & Zhou, RFS 2009): VRP (implied minus realized variance) explains over 15% of quarterly excess-return variation in 1990-2005, and over 25% combined with P/E. Predictability peaks at the quarterly horizon — [Bollerslev & Zhou FEDS 2007-11](https://www.federalreserve.gov/pubs/feds/2007/200711/index.html); [BTZ, RFS 22(11)](https://scholars.duke.edu/publication/732839)
- Time-series momentum: the past 12-month excess return predicts returns for each of 58 futures including equity indices, persists about a year and partially reverses, and performs best in extreme markets — [Moskowitz, Ooi & Pedersen 2012](https://papers.ssrn.com/abstract=2089463)
- Aggregate daily short selling predicts lower market returns over 10 days (see Q4) — [Aggregate shorting, JFM](https://www.lehigh.edu/~xuy219/research/Aggshort_JFM.pdf)

### Inferences
- The VRP is computable for free: VIX² (FRED series VIXCLS) minus trailing realized variance of S&P 500 daily returns (FRED SP500). Its post-2009 OOS performance was not verified, and VIX-based SVIX failed in GWZ 2024, so treat it cautiously.
- Term spread (FRED T10Y3M or T10Y2Y) and credit spread (BAA10Y, BAMLH0A0HYM2) are free but fail as monthly equity-premium predictors per GWZ 2024. They may still serve as regime or risk indicators.
- UNVERIFIED (background knowledge): Faber (2007, SSRN) shows that a 10-month simple moving average rule on the S&P 500 roughly matches returns with much lower drawdowns. The benefit comes mostly from sidestepping long bear markets (2000-02, 2008), and the rule whipsaws in V-shaped selloffs (2018, 2020). Treat it as risk management, not return enhancement.
- Realistic monthly R²: Campbell-Thompson (2008) style results suggest well-constrained predictors give monthly OOS R² of about 0.5-1%. Consistent with GWZ, a monthly R² above 1-2% should be viewed as suspect.
- Industry timing via industry momentum (Q1) and trend-following on sector ETFs (XBI, ICLN, TAN, URA, ARKK-style) is computable from daily prices. No source here measures its OOS performance for these specific themes.

### Gaps
- No sourced OOS test of the 200-day/10-month moving-average rule post-2010.
- No sourced post-2009 VRP OOS R².
- Goyal-Welch updated data is downloadable from Amit Goyal's website, but the URL was not verified this session.

## Q6. Seasonality (Heston-Sadka) and turn-of-month

### Takeaway
Same-calendar-month seasonality is large gross (about 13%/year long-short 1963-2011; the Keloharju-Linnainmaa-Nyberg seasonality factor earns 61 bps/month, t = 8.37). It is computable from monthly returns. Its implementability net of costs and its post-publication performance were not verified. Keloharju et al. argue it largely reflects seasonal variation in factor premia, which reverses.

### Cited Findings
- Heston & Sadka (JFE 2008): stocks tend to have relatively high (or low) returns every year in the same calendar month — [Heston & Sadka via UMD research summary](https://rhsmith.umd.edu/news/seasonality-stock-market-returns)
- A long-short strategy based on same-calendar-month returns earns about 13%/year on average over 1963-2011 — [Keloharju, Linnainmaa & Nyberg, NBER w20815](https://www.nber.org/papers/w20815.pdf)
- A seasonality factor averages 61 bps/month (t = 8.37) — [Keloharju, Linnainmaa & Nyberg, "Return Seasonalities" (AQR Insight Award version)](https://www.aqr.com/-/media/AQR/Documents/AQR-Insight-Award/2015/AllSeasons20141219pdf.pdf)
- Seasonality is in the Chen-Velikov replication set ("Return Seasonality"), but its individual net figure was not extracted — [Chen & Velikov 2020](https://www.federalreserve.gov/econres/feds/files/2020039pap.pdf)
- International evidence also exists — [Heston & Sadka, JFQA 2010 (IDEAS)](https://ideas.repec.org/a/cup/jfinqa/v45y2010i05p1133-1160_00.html)

### Inferences
- Computation: for month m, signal = average return of the stock in the same calendar month over years t-1 to t-5 (or t-1 to t-20), from daily prices aggregated to monthly. It needs a long price history, which young growth stocks (recent IPOs and SPACs in EV, space, quantum) often lack. That limits coverage in the target universe.
- Turn-of-month effect: no source retrieved. It is a market-level calendar effect and would need index-level testing.

### Gaps
- No source on turn-of-month effect magnitudes or post-2010 persistence.
- No net-of-cost or post-publication estimate for Heston-Sadka seasonality.

