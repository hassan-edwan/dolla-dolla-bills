# How quants validate, combine and present predictive stock signals (small long-only account, US small/mid-cap growth, weekly-to-monthly rebalance)

## Q1. Validation: how to test a signal on our own data without fooling ourselves

### Takeaway
Judge a signal by its cross-sectional rank IC (its mean, its stability measured as IC/std(IC), and how fast it decays by horizon), its monotonic quantile spreads and its turnover, all measured strictly out of sample. Set the bar high: t > 3, not 2. Deflate for the number of variants tried, use purged and embargoed splits when labels overlap, and keep delisted stocks with realistic delisting returns. Published anomalies lose about half their return after publication, and about two-thirds fail to replicate once microcaps are controlled for.

### Cited Findings
- **Multiple-testing hurdle.** Harvey, Liu and Zhu (RFS 2016, vol. 29(1), pp. 5–68) build a multiple-testing framework over hundreds of published factors. They conclude a new factor needs a t-statistic above about 3.0 rather than 2.0, and that "most claimed research findings in financial economics are likely false." — [NBER w20592](https://nber.org/papers/w20592); [RePEc listing](https://ideas.repec.org/a/oup/rfinst/v29y2016i1p5-68..html)
- A Feb 2026 NBER working paper by Harvey, Sancetta and Zhao derives a lower bound for the minimum t-stat of roughly 3.0. — [NBER w34898 (per search summary)](https://www.nber.org/system/files/working_papers/w34898/w34898.pdf)
- **Replication failure.** Hou, Xue and Zhang ("Replicating Anomalies," RFS 2020) control microcaps with NYSE breakpoints and value-weighted returns. On that basis, 65% of 452 anomalies fail |t| ≥ 1.96, and so do 96% of the "trading frictions" category. At a multiple-testing hurdle of 2.78 the failure rate rises to 82%. Replicated anomalies also have "much smaller" economic magnitudes than originally reported. — [RePEc](https://ideas.repec.org/a/oup/rfinst/v33y2020i5p2019-2133..html); [NBER w23394](https://www.nber.org/papers/23394)
- **Microcaps distort results.** Microcaps (below the 20th NYSE percentile) are about 60% of listed stocks but only about 3% of total market cap (Fama-French 2008, as cited by Novy-Marx & Velikov). — [Novy-Marx & Velikov PDF](https://mysimon.rochester.edu/novy-marx/research/ToAatTC.pdf)
- **Decay after publication.** McLean and Pontiff (JF 2016, 97 predictors): "Portfolio returns are 26% lower out-of-sample and 58% lower post-publication." The 26% is an upper bound on data-mining bias, which implies a publication effect of about 32%. They reject the hypothesis that predictability disappears entirely. — [McLean & Pontiff PDF (gwern mirror)](https://Www.Gwern.net/doc/economics/2016-mclean.pdf); [RePEc](https://econpapers.repec.org/RePEc:bla:jfinan:v:71:y:2016:i:1:p:5-32)
- **Deflated Sharpe ratio (Bailey & López de Prado, 2014).** The DSR is the Probabilistic Sharpe Ratio evaluated against a benchmark SR₀: the expected maximum Sharpe of N unskilled trials.
  - SR₀ is built from the variance of the trial Sharpes, the Euler–Mascheroni constant, and Φ⁻¹(1−1/N) and Φ⁻¹(1−1/(Ne)), so it rises with N.
  - The PSR adjusts for sample length (√(T−1)), skewness and kurtosis.
  - N should count every distinct strategy variant you considered, not just those you report.
  - Implementations differ on Pearson vs excess kurtosis: the term is (γ₄−1)/4 with Pearson kurtosis, or (κ+2)/4 with excess kurtosis. Check units before coding it.
  - Sources: [Wikipedia: Deflated Sharpe ratio](https://en.wikipedia.org/wiki/Deflated_Sharpe_ratio); [arXiv 2608.27734](https://arxiv.org/pdf/2608.27734); [quantstrat deflatedSharpe docs](https://www.rdocumentation.org/packages/quantstrat/versions/0.16.7/topics/deflatedSharpe)
- **Purged and embargoed cross-validation (López de Prado, *Advances in Financial Machine Learning*, 2018, ch. 7 and 12).**
  - Purging removes training observations whose label windows overlap the test fold.
  - An embargo adds a buffer after the test set to cut serial-correlation leakage.
  - Combinatorial Purged CV (CPCV) builds C(N,K) splits that produce many out-of-sample backtest paths, so you get a distribution of performance rather than one number.
  - A synthetic demo showed a shuffled k-fold R² of 0.83 against −1.31 for the purged version. That demo is illustrative only.
  - Sources: [Wikipedia: Purged cross-validation](https://en.wikipedia.org/wiki/Purged_cross-validation); [skfolio CombinatorialPurgedCV](https://skfolio.org/generated/skfolio.model_selection.CombinatorialPurgedCV.html); [quant-lessons purging/embargo](https://5x5x5x5.github.io/quant-lessons/backtest/purging-embargo/)
- **Professional ML split design.** Gu, Kelly and Xiu use a strictly chronological design: 18 years of training (1957–1974), 12 years of validation, and 30 years of recursive out-of-sample testing. — [GKX NBER w25398](https://www.nber.org/papers/w25398.pdf)
- **Benchmark choice inflates R².** GKX note that benchmarking out-of-sample R² against the historical mean inflates it by about 3%. For OLS-3, R² against the historical mean is 3.74% per month, because the historical mean is a very noisy forecaster. Benchmark against a zero forecast instead. — [GKX](https://www.nber.org/papers/w25398.pdf)
- **IC noise in small universes.** A 1983 Financial Analysts Journal article notes that an IC on all NYSE stocks is unlikely to exceed 0.10, but an IC computed on 30 stocks can vary randomly by about ±0.35. — [CFA Institute FAJ 1983, "Perils of the Information Coefficient"](https://rpc.cfainstitute.org/en/research/financial-analysts-journal/1983/problems-in-measuring-the-quality-of-investment-information-the-perils-of-the-information-coef)
- **Delisting bias.**
  - Shumway (JF 1997, 52(1), pp. 327–340): delistings for bankruptcy and other negative reasons are generally surprises. Correct delisting returns are missing for most such stocks since 1962, and the omitted returns are large and negative. — [RePEc Shumway 1997](https://ideas.repec.org/a/bla/jfinan/v52y1997i1p327-40.html)
  - Shumway and Warther (JF 1999) on Nasdaq: using −55% for missing performance-related delisting returns corrects the bias, and that bias materially affects the measured size effect. — [RePEc Shumway & Warther 1999](https://ideas.repec.org/a/bla/jfinan/v54y1999i6p2361-2379.html)
  - A later asset-growth study reports a sample mean delisting return of −38.3%. This figure comes from a search summary, not verified at the primary source. — [core.ac.uk](https://core.ac.uk/download/35456666.pdf)
- **Turnover sets the cost hit.** Transaction costs cut realized spreads by more than 1% of monthly one-sided turnover: 20% monthly turnover costs at least 20 bp per month. Statistical significance falls proportionately. — [Novy-Marx & Velikov](https://mysimon.rochester.edu/novy-marx/research/ToAatTC.pdf)

### Inferences
- **Practical validation checklist** (standard Alphalens-style practice; see Q4):
  - Compute the Spearman rank IC each rebalance date for horizons of 1, 5, 21 and 63 trading days.
  - Report mean IC, std(IC), IC IR (mean/std, annualized by √periods per year), the share of periods with IC > 0, and a t-stat on mean IC. Use Newey-West standard errors with lag ≥ horizon−1 whenever the forward-return windows overlap, for example a 21-day return sampled weekly.
  - Show quintile mean forward returns, which should rise monotonically, and the top-minus-bottom spread net of estimated costs.
  - For a long-only book, also show top quintile minus universe average.
  - Report the top-quintile hit rate (share of names beating the universe median) and turnover, measured as top-quintile membership change and as the signal's rank autocorrelation.
  - Plot an IC decay curve by horizon to choose the rebalance frequency. If IC at 21 days is not clearly below IC at 5 days, monthly rebalancing loses little.
- **On the t > 3 bar for a single own-data test.** Harvey-Liu-Zhu's 3.0 assumes the industry-wide search. For our own search, use the DSR with N set to the actual number of signal and parameter variants tried, and keep a written log of every variant.
- **Small universes make IC noisy.** With a universe of a few hundred names and only about 5–10 years of point-in-time data, monthly IC will be very noisy (the 1983 FAJ ±0.35 point). Prefer weekly ICs with Newey-West, and pool across horizons only with overlap corrections.
- **Survivorship bias is acute here.** Volatile small/mid-cap growth has high delisting rates. A dataset that lacks delisted tickers will overstate returns, especially for signals that tilt toward distressed, high-volatility or illiquid names.
  - If delisting returns are unavailable, impute −30% to −55% for performance-related delistings (the Shumway / Shumway-Warther range) and 0% or the merger price for M&A delistings.
  - Run the backtest under both assumptions and check that the conclusions survive.
- **Expect shrinkage.** Expect at least a one-third to one-half haircut on any backtested spread relative to its in-sample value (McLean-Pontiff).

### Gaps
- I could not verify from the primary source Shumway (1997)'s exact NYSE/AMEX correction figure, which is commonly cited as about −30%. The search result explicitly did not confirm it. Only the −55% Nasdaq figure (Shumway-Warther 1999) is confirmed.
- I found no primary source specifying a standard Newey-West lag choice for IC t-stats. The lag ≥ horizon−1 rule above is a standard econometric inference, not a cited guideline.
- I did not read the original Bailey & López de Prado (2014) DSR paper directly; the formula details come from secondary sources.

## Q2. Combination: z-score composites vs IC-weighting vs machine learning

### Takeaway
Gu-Kelly-Xiu show that nonlinear ML (shallow neural nets, trees) roughly doubles long-short Sharpe over a 3-variable OLS on about 30,000 stocks and 94 characteristics. The gains come mostly from interactions among price-trend, liquidity and volatility signals, and they require more than 100% monthly turnover. For a small universe and short history, shallow models win even in GKX. A robust, rank-based, sector-neutral equal-weight or shrunk-IC-weight composite is the sensible default. ML is a later challenger that must beat it out of sample after costs.

### Cited Findings
- **GKX data and setup.** Gu, Kelly and Xiu, "Empirical Asset Pricing via Machine Learning" (RFS 2020, 33(5), pp. 2223–2273) use nearly 30,000 stocks from 1957–2016 and 94 characteristics, plus interactions and industry dummies (900+ predictors). — [GKX](https://www.nber.org/papers/w25398.pdf)
- **GKX out-of-sample monthly stock-level R²:**
  - OLS with all 900+ predictors: negative.
  - Elastic net: 0.11%. PCR: 0.26%. PLS: 0.27%.
  - Trees and neural nets: 0.33–0.40%, peaking at 0.40% for NN3.
  - The GLM with splines but no interactions fails to robustly beat linear models, which shows that predictor interactions are the key nonlinearity.
  - An equal-weight ensemble of all 11 ML methods gives 0.43%.
  - Source: [GKX](https://www.nber.org/papers/w25398.pdf)
- **Large vs small stocks.** Trees and NNs are "especially successful among large stocks," with R² of 0.52–0.70% for the top 1,000 by market cap. The authors read this as evidence that ML is not just picking up illiquidity effects. — [GKX](https://www.nber.org/papers/w25398.pdf)
- **Shallow beats deep.** NN performance peaks at 3 hidden layers and declines after that. Boosted trees and random forests pick trees with fewer than about 6 leaves on average. GKX attribute this to the small data size and tiny signal-to-noise ratio. — [GKX](https://www.nber.org/papers/w25398.pdf)
- **Portfolio results.**
  - Long-short decile spread on NN forecasts: annualized out-of-sample Sharpe of 1.35 value-weighted (NN4: 2.3% per month, 20.1% annualized volatility) and 2.45 equal-weighted.
  - The benchmark OLS-3 earns 0.61 (VW) and 0.83 (EW).
  - Excluding stocks below the 20th NYSE size percentile, the NN4 equal-weighted Sharpe falls to 1.69.
  - The ML ensemble earns 2.49 EW and 1.33 VW.
  - S&P 500 timing with NN forecasts earns Sharpe 0.77 vs 0.51 for buy-and-hold.
  - Source: [GKX](https://www.nber.org/papers/w25398.pdf)
- **Turnover.** NN1–NN5 portfolios turn over 110–130% per month, and trees and penalized regressions turn over slightly more. For reference, a short-term reversal decile spread turns over 172.6% per month and a size decile spread 22.9%. GKX's Sharpe ratios are before transaction costs. — [GKX](https://www.nber.org/papers/w25398.pdf)
- **Factor-adjusted performance.** A six-factor model (FF5 plus momentum) explains up to about 40% of linear-model strategy returns but only about 10–30% of NN portfolios. NN information ratios are 0.9–2.4. The short side of all portfolios is "essentially flat in the post-2000 sample." — [GKX](https://www.nber.org/papers/w25398.pdf)
- **Which predictors matter (consistent across all models):**
  1. Price trends: short-term reversal (mom1m), 12-month momentum (mom12m), momentum change (chmom), industry momentum (indmom), max daily return (maxret), long-term reversal (mom36m).
  2. Liquidity: turnover and its volatility, log market cap, dollar volume, Amihud illiquidity, zero-trade days, bid-ask spread.
  3. Risk: total and idiosyncratic volatility, beta, beta².
  4. Valuation and fundamentals: E/P, S/P, asset growth, number of recent earnings increases (nincr).
  - Linear models concentrate importance in momentum and reversal. Trees and NNs are "more democratic."
  - Source: [GKX](https://www.nber.org/papers/w25398.pdf)
- **Cost mitigation, which also bears on how signals are combined.** Novy-Marx and Velikov find a buy/hold spread is the single most effective simple fix: a stricter rule to enter a position than to keep it, e.g. buy in the top 10% and hold until the name leaves the top 20%. For very high-turnover strategies, combine it with restricting trading to low-cost stocks and rebalancing less often. — [Novy-Marx & Velikov](https://mysimon.rochester.edu/novy-marx/research/ToAatTC.pdf)

### Inferences
- **Default composite for a small universe:**
  1. Winsorize each raw signal (e.g., at the 1st/99th percentile), or simply convert it to cross-sectional ranks.
  2. Neutralize within sector or industry by ranking or z-scoring within GICS sector. This stops a growth universe from becoming a single-sector bet.
  3. Convert to z-scores and flip signs so higher is better.
  4. For missing values, set the z-score to 0 (sector median) and require a minimum count of non-missing signals per stock.
  5. Average the z-scores with equal weights, or with IC weights shrunk heavily toward equal. Estimating IC weights is noisy (see the ±0.35 small-sample IC noise in Q1).
- **This is a reasoned recommendation, not a tested result.** GKX's own finding that an equal-weight ensemble beats most single models, and that shallow models beat deep ones as data shrinks, supports simple, regularized combination when the universe has hundreds rather than tens of thousands of names. I did not find a paper that directly tests equal-weight vs IC-weight composites in small universes.
- **The GKX signals that matter most are fast** (reversal, momentum, maxret, volatility). With weekly or monthly rebalancing and small-cap costs, they will be heavily eroded, as shown by GKX's turnover and Novy-Marx & Velikov's costs. Slow signals (value, profitability, asset growth, earnings increases) survive costs better.
- **Long-only matters.** GKX's short side contributes little after 2000, which is mildly encouraging for long-only implementation. But their R² is fitted on equal-weighted errors, and their EW Sharpe drops sharply once microcaps are removed.

### Gaps
- No source fetched quantifies "how much ML adds" in a universe of about 200–1,000 small/mid-cap growth names with about 10 years of data. GKX's top-1,000 vs bottom-1,000 split is the closest evidence.
- No primary source located for Qian & Hua or other formal IC-weighted composite methodology (e.g., the weight ∝ Σ_IC⁻¹ · mean IC optimal-weight result); omitted rather than stated from memory.

## Q3. Realistic performance expectations after costs (long-only small caps)

### Takeaway
A good equity signal has a rank IC in the low hundredths, about 0.02–0.10. Long-only constraints pass through only a fraction of that edge (transfer coefficient about 0.3–0.6). Small-cap costs are roughly 2× large-cap costs, and anomalies with more than 50% monthly turnover rarely survive costs. A realistic target for a long-only small-cap composite is a modest active return, with net information ratios well under 1. Treat backtested gross Sharpe ratios above 1.5 as suspect.

### Cited Findings
- **Fundamental Law and transfer coefficient.** The Fundamental Law is IR ≈ IC × √Breadth, where breadth is the number of independent bets per year. Clarke, de Silva and Thorley (FAJ 2002) generalize it to IR = TC × IC × √BR.
  - TC = 1 when the portfolio is unconstrained.
  - The long-only constraint is the main thing that pulls TC down.
  - One cited example gives TC ≈ 0.3 when shorting is forbidden, turnover is capped at 50% and the portfolio must stay market-cap-neutral.
  - Long-short strategies reach about 0.7–0.8.
  - Sources: [CFA Institute FAJ 2002](https://rpc.cfainstitute.org/research/financial-analysts-journal/2002/portfolio-constraints-and-the-fundamental-law-of-active-management); [Institutional Investor, "The cost of constraint"](https://www.institutionalinvestor.com/article/2btgijdgl1kk3akuoutc0/home/the-cost-of-constraint); [CFI explainer](https://corporatefinanceinstitute.com/resources/capital-markets/fundamental-law-of-active-management/)
- **What a good IC looks like.**
  - Zhang, Guo and Cao (Wells Fargo, 2020): "a stellar stock selection model may often have an IC of 0.05 or 0.1." An IC of 0.01 is weak but real information and hard to detect statistically. — [arXiv 2010.08601](https://arxiv.org/pdf/2010.08601)
  - Practitioner rule of thumb: mean IC above 0.10 is strong for equities, and most effective factors fall in 0.05–0.15. Treat the upper end as optimistic. — [Interactive Brokers Campus](https://www.interactivebrokers.com/campus/?p=260461)
- **Costs by size and turnover (Novy-Marx & Velikov, RFS 2016, 29(1), pp. 104–147):**
  - Round-trip costs for typical value-weighted anomaly strategies average more than 50 bp. They are much higher for strategies in high-cost stocks (idiosyncratic volatility, distress).
  - Equal-weighted strategies cost 2–3× more.
  - Average monthly costs: about 5.66 bp for size, 5.45 bp for value and 48.4 bp for momentum. Mid-turnover strategies (14–35% per month) cost about 20–57 bp per month.
  - Most anomalies with less than 50% monthly one-sided turnover keep significant net spreads when built to mitigate costs. Only two strategies with more than 50% turnover do.
  - Effective spreads rise steeply as market cap falls (their Fig. 1).
  - Source: [Novy-Marx & Velikov](https://mysimon.rochester.edu/novy-marx/research/ToAatTC.pdf); [NBER w20721](https://www.nber.org/papers/w20721)
- **Gross vs net Sharpe by size (Novy-Marx & Velikov).**
  - The ValMomProf mid-turnover strategy has gross Sharpe of 1.14 in microcaps, 1.05 in small caps and 0.84 in large caps, vs net 0.87, 0.85 and 0.64.
  - High-turnover strategies' "extremely high gross Sharpe ratios across the micro-caps turn severely negative" after costs. The best survivors net only 0.28–0.48 Sharpe in small and large caps.
  - Low-turnover anomalies are barely affected by costs, even in microcaps.
  - Source: [Novy-Marx & Velikov](https://mysimon.rochester.edu/novy-marx/research/ToAatTC.pdf)
- **AQR live execution costs (Frazzini, Israel & Moskowitz, "Trading Costs"):**
  - Data: about $1.7 trillion of AQR executions across 21 developed markets over 19 years.
  - Average market impact is just under 9 bp (median just above 6 bp), and about 15 bp value-weighted.
  - Small-cap trades cost almost 19 bp vs almost 9 bp for large caps, before controlling for size.
  - They conclude that size, value and momentum survive costs for patient institutional traders.
  - These figures come from secondary summaries of the paper.
  - A Federal Reserve paper disputes them, arguing that net anomaly returns are much smaller once post-2005 costs and price impact are included.
  - Sources: [Alpha Architect summary](https://alphaarchitect.com/the-best-research-paper-ever-written-on-trading-costs/); [NBER conference draft](https://conference.nber.org/conf_papers/f68262/f68262.pdf); [Fed FEDS 2020-039](https://www.federalreserve.gov/econres/feds/files/2020039pap.pdf)
- **The long side carries much of the premium.** Israel and Moskowitz (JFE 2013) find long positions account for nearly all of the size premium, about 60% of the value premium and about half of momentum profits. The value premium shrinks with firm size, while momentum shows no reliable relation to size. — [AQR](https://www.aqr.com/Insights/Research/Journal-Article/The-Role-of-Shorting-Firm-Size-and-Time-on-Market-Anomalies); [RePEc](https://econpapers.repec.org/RePEc:eee:jfinec:v:108:y:2013:i:2:p:275-301)
- **Size-limited ML results.** GKX's NN equal-weighted Sharpe falls from 2.45 to 1.69 when microcaps are excluded, and to 1.35 value-weighted. All are gross, long-short, with more than 110% monthly turnover. — [GKX](https://www.nber.org/papers/w25398.pdf)

### Inferences
- **Worked Fundamental Law example** (illustrative arithmetic, not a cited result):
  - Assumptions: IC = 0.04, a universe of about 300 names, monthly rebalancing. Effective independent breadth is far below 300 × 12 because names are correlated and signals persist; assume effective BR ≈ 300.
  - Unconstrained IR ≈ 0.04 × √300 ≈ 0.69.
  - With a long-only TC of about 0.4: IR ≈ 0.28. At 8% tracking error, that is about 2.2% per year of gross active return, before costs.
- **Holding count.** With about 15–30 holdings in a tens-of-thousands-dollar account, TC is reduced further. Diversification is limited, and the TC math above is only an upper bound.
- **Costs for a small retail account.** A small account has negligible market impact, so the binding cost is the bid-ask spread. Novy-Marx & Velikov's effective-spread measure (market orders, small liquidity demander) is the right model, not AQR's institutional impact numbers.
  - Volatile small/mid-cap growth names will often have effective spreads of tens of bp.
  - At 30–50% monthly one-sided turnover, budget roughly 15–50 bp per month of drag (applying Novy-Marx & Velikov's "≥1% of turnover" rule and their small-cap spreads).
- **Reasonable net expectations.** Low single-digit annual alpha over a small-cap growth benchmark, with a high chance of multi-year underperformance stretches. Signals with more than 50% monthly turnover (short-term reversal, pure short-horizon momentum) are unlikely to survive costs at weekly rebalancing.
- **Growth universe.** Value premia are concentrated in small stocks (Israel-Moskowitz), but a growth-only universe truncates value spreads. Momentum, quality/profitability and earnings-revision-type signals are likely the more relevant levers. This is an inference; I found no direct study of growth-only universes.

### Gaps
- I could not access the primary text of Frazzini-Israel-Moskowitz; its numbers are from secondary summaries.
- I could not confirm Grinold-Kahn's own "IC 0.05 good / 0.10 great" wording from the primary text.
- I found no source giving net-of-cost Sharpe or IR specifically for long-only US small/mid-cap growth quant portfolios.
- The TC ≈ 0.3 figure is from a summary of Clarke-de Silva-Thorley; the full paper was not read.

## Q4. What quant signal research and decision dashboards show

### Takeaway
The standard signal-research view (Alphalens) has four panels: returns by quantile, IC (time series, histogram, Q-Q plot, monthly heatmap), turnover and rank autocorrelation, and event-style cumulative returns, with optional sector breakdowns. Portfolio-level views (Barra, Axioma, Pyfolio style) add factor exposures vs benchmark, risk decomposition into factor and specific risk, and return attribution to factors.

### Cited Findings
- **Alphalens scope.** Alphalens ("Performance analysis of predictive (alpha) stock factors," Quantopian, Apache-2.0) covers Returns Analysis, Information Coefficient Analysis, Turnover Analysis and Grouped Analysis. The entry points are `get_clean_factor_and_forward_returns(factor, prices, quantiles=..., groupby=...)` and `create_full_tear_sheet`. — [quantopian/alphalens](https://github.com/quantopian/alphalens)
- **Alphalens tear-sheet components** (maintained fork alphalens-reloaded, `tears.py`):
  - Summary: quantile statistics table, returns table (alpha/beta, top-minus-bottom spread), quantile returns bar chart, information table (IC mean, IC std, risk-adjusted IC, t-stat, p-value, skew, kurtosis), turnover table.
  - Returns: quantile returns bar and violin plots, cumulative returns of the factor-weighted portfolio, cumulative returns by quantile, and a time series of the top-minus-bottom spread with confidence band. Optional per-sector quantile bars.
  - Information: IC time series (with a rolling mean), IC histogram, IC Q-Q plot, monthly IC heatmap, IC by group (sector).
  - Turnover: top and bottom quantile turnover, and factor rank autocorrelation per horizon.
  - Event returns: average cumulative return by quantile around the signal date, with optional std bars.
  - Source: [alphalens-reloaded tears.py](https://github.com/stefan-jansen/alphalens-reloaded/blob/main/src/alphalens/tears.py)
- **MSCI Barra analytics (via FactSet)** provide tracking error, decomposition of risk into common-factor and stock-specific parts, active exposures and contributions to risk, in absolute and benchmark-relative terms. — [Barra Analytics on FactSet factsheet](https://www.msci.com/resources/factsheets/Barra_Analytics_on_FactSet.pdf)
- **Barra attribution.** Barra Portfolio Manager offers Brinson, factor-based or hybrid attribution, and BarraOne adds equity-factor attribution. The equity models split risk and return into style, sector and macro factors "to identify exposures and unintended bets." — [Barra Portfolio Manager](https://www.msci.com/data-and-analytics/portfolio-management/barra-portfolio-manager); [BarraOne](https://www.msci.com/data-and-analytics/portfolio-management/barra-one); [MSCI equity factor models](https://www.msci.com/data-and-analytics/factor-investing/equity-factor-models)
- **Barra style factors** monitored in MSCI's multi-factor index construction: value, momentum, quality, beta, residual volatility, size, mid-cap, yield, growth and liquidity. — [MSCI Core Multi-Factor methodology](https://www.msci.com/downloads/web/msci-com/indexes/group/multiple-factor-indexes/CoreMultiFactor_ProductInsight_Rev.pdf)
- **Example report.** A Barra Aegis Performance Analyst example shows an annualized breakdown of active risk and return by source (countries, asset selection, and so on). — [Barra Aegis Performance Analyst](https://www.msci.com/documents/10199/242721/Barra_Aegis_Performance_Analyst.pdf/c41a3468-bd20-4ffc-93f6-80d859f7e40c)
- **Performance and turnover table conventions in academic ML work.** GKX report drawdowns, max one-month loss, turnover and factor-model alphas and information ratios for each model's portfolio. They also show cumulative long and short leg performance against the market. — [GKX](https://www.nber.org/papers/w25398.pdf)

### Inferences
Suggested dashboard for this project. This is a synthesis of the Alphalens and Barra conventions above, adapted to long-only use.
1. **Signal scorecard table.** One row per signal and the composite. Columns: mean rank IC at 5, 21 and 63 days; IC IR; Newey-West t; % of periods with IC > 0; top-quintile minus universe return (gross and net); top-quintile hit rate; monthly turnover; rank autocorrelation; the deflated-Sharpe or "variants tried" count; last 12-month IC; and live vs backtest flags.
2. **IC time series.** Bars for each period's IC plus a 12-month rolling mean line, with a monthly heatmap to show regime dependence.
3. **IC decay curve.** IC against horizon, used to justify the rebalance frequency.
4. **Quantile return bars** (Q1–Q5, net of costs) and cumulative returns by quantile. For long-only, show top quintile vs universe vs a small/mid-cap growth benchmark (e.g., the Russell 2000 Growth index).
5. **Signal correlation matrix.** Average cross-sectional rank correlation among signals, used to judge whether the composite adds breadth.
6. **Portfolio factor exposures vs benchmark.** Active z-score exposure to size, momentum, volatility/beta, value, growth, liquidity and sector weights. This flags unintended bets, the core Barra use case.
7. **Per-stock factor percentile profile.** For each candidate or holding: its percentile on each signal (within sector), the composite score, and the contribution of each signal to the composite (z × weight). This makes each buy or sell decision attributable to specific factors.
8. **Performance attribution.** Realized active return split into factor contributions (exposure × factor return) plus a stock-specific residual. Also show turnover and cost drag, and drawdown.
9. **Data-quality panel.** Universe coverage, missing-value rate per signal, delisting count and the imputation used, and the point-in-time check.

### Gaps
- No primary Axioma or Bloomberg (e.g., Bloomberg PORT, factor tool) documentation was retrieved, so their specific screens are not described here.
- Pyfolio tear-sheet contents (returns, drawdown, rolling beta/Sharpe, exposures, round trips) were not fetched; Pyfolio is mentioned only as the companion library listed in the Alphalens README.
