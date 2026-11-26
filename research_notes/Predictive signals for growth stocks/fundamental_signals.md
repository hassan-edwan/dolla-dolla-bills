# Accounting / Fundamental Return Predictors: Replication, Decay, Long-Only Usefulness, and EDGAR XBRL Construction

Method note: besides the papers, this file includes my own calculations on the Chen & Zimmermann Open Source Asset Pricing (OSAP) portfolio returns. These are monthly data through 2025-12, downloaded with the official `openassetpricing` Python package from [openassetpricing.com](https://www.openassetpricing.com/). The script and raw output sit next to this file: `fundamental_signals_osap_stats.py` and `fundamental_signals_osap_results.txt`. The column definitions are:
- **OP**: the original-paper implementation. It is mostly equal-weighted and includes microcaps.
- **exMicro**: the "ex_nyse_p20_me" alternative. It drops stocks below the NYSE 20th-percentile market cap.
- **VWdec**: value-weighted deciles.
- **Insample**: the original paper's sample years.
- **Postpub**: the years after the publication year.
- **2015-25**: Jan 2015 to Dec 2025.

Returns are % per month, with t-statistics in parentheses. OSAP portfolios are sign-aligned: the highest-numbered portfolio is the predicted "good" leg. **Long leg** = top portfolio minus the equal average of all quantile portfolios, which is a crude proxy for the equal-weighted universe and not the market. **Short leg** = that average minus the bottom portfolio. **Hit** = share of months from 2015 to 2025 with a positive long-short return. All of these OSAP-derived numbers are labelled "[OSAP calc]" below and are sourced to [OSAP / openassetpricing.com](https://www.openassetpricing.com/). The original-paper return and t-stat figures come from OSAP's [SignalDoc.csv](https://github.com/OpenSourceAP/CrossSection/blob/master/SignalDoc.csv).

## Which fundamental anomalies survive large replication studies, and which fail (especially excluding microcaps)?

### Takeaway
The headline replication rate depends on method:
- **Hou-Xue-Zhang (HXZ):** 35%. They use NYSE breakpoints, value weights, and t > 1.96.
- **Jensen-Kelly-Pedersen (JKP):** 82.4%. They use a Bayesian method, tercile spreads, and capped value weights. They find replication holds even among mega and large caps.

The fundamental themes that survive almost every method are:
- profitability and quality (gross profitability, cash-based operating profitability);
- net share issuance and external financing;
- earnings-announcement-based momentum (announcement return, SUE streaks).

Weak or dead after 2000, especially outside microcaps, are:
- Sloan accruals;
- NOA and dNOA;
- most balance-sheet growth signals;
- R&D-to-market;
- the Piotroski F-score;
- Altman Z-score and CHS failure probability (as a long-short signal).

Value (B/M) "replicates" over long samples but has been close to zero, or negative in value-weighted form, since 2007.

### Cited Findings

**Hou, Xue & Zhang (2020): headline replication rates**
- They tested 452 anomalies with NYSE breakpoints and value-weighted returns to limit microcaps. 65% fail a single-test |t| > 1.96 hurdle, including 96% of trading-frictions variables. With a multiple-testing hurdle of t = 2.78, 82% fail — [Hou, Xue & Zhang, RFS 2020 (RePEc)](https://ideas.repec.org/a/oup/rfinst/v33y2020i5p2019-2133..html); [NBER w23394](https://www.nber.org/papers/w23394).
- Microcaps are about 60% of firms but only about 3% of market cap. This is the rationale for the HXZ construction — [Alpha Architect summary](https://alphaarchitect.com/replicating-anomalies/).

**Jensen, Kelly & Pedersen (2023): replication rates and how they differ from HXZ**
- The JKP baseline US replication rate is 55.6% using OLS t-stats on raw returns, comparable to HXZ's 35%. It rises to 61.3% after dropping factors the original papers never found significant, and to 82.4% under their Bayesian/empirical-Bayes model — [JKP, JF 2023 (CBS open-access PDF)](https://research-api.cbs.dk/ws/portalfiles/portal/95651880/theis_ingerslev_jensen_et_al_is_there_a_replication_crisis_in_finance_publishersversion.pdf).
- JKP's construction choices differ from HXZ's:
  - tercile spreads instead of deciles;
  - breakpoints from non-microcap stocks (above the NYSE 20th percentile);
  - accounting data always lagged 4 months;
  - capped value weights;
  - IBES-based factors excluded.

  Source: [JKP 2023](https://research-api.cbs.dk/ws/portalfiles/portal/95651880/theis_ingerslev_jensen_et_al_is_there_a_replication_crisis_in_finance_publishersversion.pdf).

**JKP: replication by size group and by theme**
- Empirical-Bayes replication rates by size group are 77.3% for mega, 79.8% for large, 85.7% for small, 85.7% for micro, and 68.1% for nano. JKP conclude that criticisms based on stock size or liquidity are "largely groundless" — [JKP 2023](https://research-api.cbs.dk/ws/portalfiles/portal/95651880/theis_ingerslev_jensen_et_al_is_there_a_replication_crisis_in_finance_publishersversion.pdf).
- The Spearman rank correlation of cluster alphas is 73% between mega and micro caps, but only 36% between mega and nano caps. Nano caps were 458 of 4,356 US stocks at end-2020 — [JKP 2023](https://research-api.cbs.dk/ws/portalfiles/portal/95651880/theis_ingerslev_jensen_et_al_is_there_a_replication_crisis_in_finance_publishersversion.pdf).
- JKP use 13 themes: Accruals, Debt Issuance, Investment, Leverage, Low Risk, Momentum, Profit Growth, Profitability, Quality, Seasonality, Size, Short-Term Reversal, and Value. Eleven of the 13 replicate at 50% or better; the exceptions are low leverage and size. In the tangency portfolio, profitability, investment and size are the three themes that do not get significant weight once the other themes are controlled for — [JKP 2023](https://research-api.cbs.dk/ws/portalfiles/portal/95651880/theis_ingerslev_jensen_et_al_is_there_a_replication_crisis_in_finance_publishersversion.pdf).

**Chen & Zimmermann / OSAP: replication quality labels**
- In OSAP's documentation, CHS Failure Probability and Altman Z-score are labelled "4_not": not predictive in the original paper's own test. Piotroski F-score, Accruals, Asset Growth, Gross Profitability, Share Issuance and Announcement Return are labelled "1_clear" — [OSAP SignalDoc.csv](https://github.com/OpenSourceAP/CrossSection/blob/master/SignalDoc.csv).

**OSAP: post-publication and recent results by signal [OSAP calc]**

All returns are % per month (t-statistic).

Profitability:

| Signal | Post-pub, original construction | Ex-microcap | 2015-25, original construction | 2015-25, ex-microcap | Hit rate 2015-25 |
|---|---|---|---|---|---|
| Gross profitability (GP, Novy-Marx 2013) | 0.89 (2.4) | 0.91 (3.3) | 0.96 (2.5) | 0.94 (3.2) | 61% |

- GP is one of the few accounting signals that is strong today, including outside microcaps. Cash-based operating profitability is positive but noisier: 0.60 (1.3) in 2015-25 — [OSAP](https://www.openassetpricing.com/).

Issuance and external financing:

| Signal | Post-pub, original construction | Ex-microcap | Value-weighted deciles | 2015-25, original construction | Hit rate 2015-25 |
|---|---|---|---|---|---|
| ShareIss1Y (Pontiff-Woodgate) | 0.94 (2.8) | 0.35 (1.7) | 0.67 (2.5) | 1.31 (2.8) | 64% |
| ShareIss5Y | 0.87 (3.3) | 0.36 (2.3) | 0.63 (2.3) | — | — |
| XFIN (net external financing) | — | — | — | 1.63 (3.1) | — |

- Most of the issuance effect sits in microcaps, but it remains significant in value-weighted form — [OSAP](https://www.openassetpricing.com/).

Earnings-announcement signals:

| Signal | Post-pub, original construction | Ex-microcap | Value-weighted deciles | 2015-25, original construction | 2015-25, VW deciles | Hit rate 2015-25 |
|---|---|---|---|---|---|---|
| AnnouncementReturn (Chan-Jegadeesh-Lakonishok) | 0.80 (7.3) | 0.50 (4.8) | 0.98 (4.4) | 0.40 (2.1) | 0.79 (2.2) | 64% |
| EarningsStreak | — | — | — | 0.65 (3.7) | — | — |
| EarningsSurprise (SUE, seasonal random walk) | 0.41 (5.1) | — | — | 0.11 (0.6) | 0.13 (0.5) | — |

- SUE is ex-microcap insignificant after publication, at 0.12 (1.2) — [OSAP](https://www.openassetpricing.com/).

Value:

| Signal | In-sample | Post-pub, original construction | Post-pub, ex-microcap | Post-pub, VW deciles | 2015-25, original construction | 2015-25, VW deciles |
|---|---|---|---|---|---|---|
| BMdec (Fama-French B/M) | 0.96 (5.3) | 0.59 (3.5) | 0.22 (1.2) | -0.11 (-0.6) | 0.30 (1.1) | -0.59 (-1.5) |
| SP (sales/price) | — | 0.81 (3.0) | — | — | 0.63 (1.4) | 1.04 (1.7) |

- EP is weak throughout: 0.22 (1.8) post-publication. EntMult and CF are insignificant post-publication — [OSAP](https://www.openassetpricing.com/).

Accruals and balance-sheet growth (in-sample → post-pub, original construction):

| Signal | In-sample | Post-pub | Note |
|---|---|---|---|
| Accruals (Sloan) | 0.69 (6.7) | 0.09 (0.9) | 2015-25: -0.07 (-0.4), hit rate 45% |
| PctAcc | 0.47 (3.6) | 0.02 (0.2) | — |
| NOA | 1.10 (7.6) | 0.03 (0.1) | — |
| dNoa | 1.06 (9.4) | 0.14 (1.2) | — |
| InvestPPEInv | 0.80 (7.9) | 0.19 (1.7) | 2015-25: 0.02 |
| AssetGrowth (Cooper-Gulen-Schill) | 1.51 (7.8) | 0.49 (1.9) | Ex-microcap post-pub 0.46 (2.3); 2015-25: 0.21 (0.7) |

Source: [OSAP](https://www.openassetpricing.com/).

Piotroski F-score, R&D and distress:

| Signal | In-sample | Post-pub | 2015-25 |
|---|---|---|---|
| Piotroski F-score (PS) | 1.05 (3.7) | 0.56 (1.1) | -0.58 (-1.0); ex-microcap -0.72 (-1.3) |
| RD (R&D/market cap) | 1.01 (5.8) | 0.20 (0.6) | -0.30 (-0.6) |
| RDcap | — | -0.19 (-0.6) | — |

- Dichev O-score has only 2 portfolios in OSAP's original construction, with a tiny extreme-distress bucket of about 48 stocks. It shows 0.98 (2.6) post-publication but is insignificant ex-microcap at 0.21 (0.5) — [OSAP](https://www.openassetpricing.com/).
- CHS Failure Probability (in OSAP's "placebo" set) earns 0.56 (1.25) over 1981-2003, 0.02 (0.06) over 2009-2025, and 0.36 (1.25) over 2015-25. The June-rebalanced version is -0.60 (-0.96) over 2015-25. Altman Z-score is insignificant in all periods — [OSAP](https://www.openassetpricing.com/).

CHS in the original paper:
- Campbell-Hilscher-Szilagyi document that distressed stocks delivered anomalously low returns since 1981 despite higher volatility, beta, and SMB/HML loadings — [CHS, JF 2008 (NBER w12362)](https://www.nber.org/papers/w12362); [RePEc](https://econpapers.repec.org/RePEc:bla:jfinan:v:63:y:2008:i:6:p:2899-2939).
- Later CDS-based work (Friewald et al. 2014) finds a *positive* distress premium, so the sign of the distress relation is contested — [AEA 2020 paper summary](https://aeaweb.org/conference/2020/preliminary/paper/kk4AsyGT).

### Inferences
- **Strong under every construction since 2015:** GP, the issuance family (ShareIss1Y/5Y, XFIN, NetEquityFinance), and the announcement-based earnings signals (AnnouncementReturn, EarningsStreak, RevenueSurprise is marginal). These are the best-supported fundamental building blocks.
- **Value has two faces:** B/M replicates over 1963-present, which is why JKP count it as a success. A 2015-2025 investor would have earned nothing from value-weighted B/M. Sales/price held up better than B/M.
- **Mostly microcap effects:** HXZ-style failures concentrate in accruals and investment variants. OSAP numbers suggest issuance and SUE are also largely microcap effects, with the ex-microcap spread about one-third of the original construction.

### Gaps
- CHS failure probability is not in OSAP's main predictor set, and I did not retrieve CHS's own decile alphas, so the original-paper monthly spread for CHS is not given here.
- I could not extract JKP's theme-level alphas for individual signals; only cluster-level replication rates are given.

## Post-publication decay and current (2015-2025) performance by signal

### Takeaway
Average anomaly returns fall by roughly half after publication:
- McLean-Pontiff: 26% lower out-of-sample and 58% lower post-publication;
- JKP: a 47% decline;
- Chen-Zimmermann's bias-corrected estimate: only 12%.

The decay is very uneven across signals:
- Accruals, NOA, investment, R&D/ME and F-score fell to about zero.
- SUE fell to about zero outside microcaps. Martineau finds PEAD has been non-existent for large caps since about 2006, though this is disputed.
- Profitability (GP) and issuance did not decay; they got stronger after publication.

### Cited Findings

**Size of the average post-publication decline**
- McLean & Pontiff (2016) studied 97 predictors and found returns "26% lower out-of-sample and 58% lower post-publication" (as quoted in JKP) — [JKP 2023 quoting McLean-Pontiff](https://research-api.cbs.dk/ws/portalfiles/portal/95651880/theis_ingerslev_jensen_et_al_is_there_a_replication_crisis_in_finance_publishersversion.pdf); [McLean & Pontiff, JF 2016 (RePEc)](https://econpapers.repec.org/RePEc:bla:jfinan:v:71:y:2016:i:1:p:5-32).
- In JKP's data, the average in-sample alpha is 0.49%/month and the average post-original-sample alpha is 0.26%, a 47% decline. Of the factors significant in the original publication, 83.3% are positive post-sample. Regressing out-of-sample alpha on in-sample alpha gives a GLS slope of 0.26 post-sample (t from 3.5 to 5.3 across panels) — [JKP 2023](https://research-api.cbs.dk/ws/portalfiles/portal/95651880/theis_ingerslev_jensen_et_al_is_there_a_replication_crisis_in_finance_publishersversion.pdf).
- Chen & Zimmermann (2020b) estimate a bias-corrected post-publication drop of only 12% in US data. Jacobs & Müller (2020) find "the United States is the only country with a reliable post-publication decline" — [JKP 2023, fn. 9](https://research-api.cbs.dk/ws/portalfiles/portal/95651880/theis_ingerslev_jensen_et_al_is_there_a_replication_crisis_in_finance_publishersversion.pdf).

**Accruals**
- Green, Hand & Soliman (2011) find Sloan accrual hedge returns "no longer reliably positive" in the US. They attribute this partly to hedge-fund capital and partly to a shrinking signal — [Green, Hand & Soliman, Management Science 2011 (RePEc)](https://ideas.repec.org/a/inm/ormnsc/v57y2011i5p797-816.html).

**PEAD / SUE**
- Martineau (2022) finds that in modern markets prices absorb the surprise on the announcement date. PEAD has been non-existent for large stocks since about 2006 and has only recently disappeared for microcaps — [Martineau, CFR 2022](https://nowpublishers.com/article/Details/CFR-0122); [PDF](https://cfr.ivo-welch.info/published/papers/martineau2021rest.pdf).
- UCLA Anderson's summary says the drift began fading in non-microcaps in 2001 and was gone by 2006. It notes rebuttals (e.g., Dickerson, Julliard & Mueller) that claim PEAD "is alive and well", with the disagreement attributed to research design — [UCLA Anderson Review](https://anderson-review.ucla.edu/is-post-earnings-announcement-drift-a-thing-again).

**Per-signal decay [OSAP calc]**

All figures are % per month, original construction (t-statistic), source [OSAP](https://www.openassetpricing.com/).

| Signal | In-sample | Post-pub | 2015-25 | Hit rate 2015-25 |
|---|---|---|---|---|
| Value B/M | 0.96 | 0.59 | 0.30 (1.1) | — |
| E/P | 0.37 | 0.22 | 0.31 (1.0) | — |
| S/P | 0.72 | 0.81 | 0.63 (1.4) | — |
| Gross profitability | 0.30 (2.4) | 0.89 (2.4) | 0.96 (2.5) | 61% |
| Asset growth | 1.51 | 0.49 | 0.21 (0.7) | 50% |
| Accruals | 0.69 | 0.09 | -0.07 | 45% |
| ShareIss1Y | 0.69 | 0.94 | 1.31 (2.8) | — |
| SUE | 1.16 | 0.41 | 0.11 (0.6) | — |
| Announcement return | 1.14 (12.5) | 0.80 | 0.40 (2.1) | — |
| Revenue surprise | 0.73 | 0.37 | 0.34 (1.8) | — |
| F-score | 1.05 | 0.56 | -0.58 | — |
| R&D/ME | 1.01 | 0.20 | -0.30 | — |
| ChTax (change in taxes) | 1.05 (9.1) | 0.43 (2.9) | 0.31 (1.7) | — |
| Change in asset turnover | — | 0.09 | 0.14 | — |
| GrSaleToGrInv | — | — | -0.24 (-1.8) | — |

Cross-check on gross profitability: the original paper (VW, quintiles) reports 0.31%/month with t = 2.49 — [OSAP SignalDoc](https://github.com/OpenSourceAP/CrossSection/blob/master/SignalDoc.csv).

### Inferences
- **Signals that rose after publication:** GP, issuance, and S/P. Rising after publication is a sign of a risk or limits-to-arbitrage premium (or simply under-arbitraged), not of arbitraged-away mispricing.
- **Earnings and revenue surprise:** for a 2026 strategy, raw SUE drift should be treated as nearly dead outside microcaps. The announcement-window return (EAR) and surprise streaks retain about 0.4-0.65%/month.

### Gaps
- I did not obtain McLean-Pontiff's per-signal post-publication numbers, so per-signal decay comes from my OSAP calculations only.
- I did not fetch the Dickerson-Julliard-Mueller PEAD rebuttal numbers.
- I found no source specifically covering earnings or revenue *acceleration* (second difference) as a published anomaly. Its closest proxies in this file are EarningsStreak, RevenueSurprise and ChAssetTurnover.

## Which signals work for unprofitable growth firms and small caps, and which are mostly short-leg effects (useless long-only)?

### Takeaway
Most balance-sheet and issuance anomalies are short-leg effects. Their profits come from avoiding or shorting high issuers, high asset growth, high NOA and high accruals. For example, ShareIss1Y post-publication is 0.76 (t = 3.5) on the short leg vs 0.18 (t = 1.4) on the long leg.

The signals with a material long leg are:
- profitability (GP long leg 0.43, t = 2.7; R&D-adjusted and cash-based operating profitability long legs about 0.6, t ≈ 2.5);
- announcement return (0.41, t = 5.4 post-publication);
- earnings streaks.

For unprofitable firms, the literature says the profitability relation is weak or absent among loss-makers. Valuation ratios (B/M, revenue/price) work *more* strongly among loss firms. Issuance and dilution are the natural "avoid" screen.

### Cited Findings

**Short-leg concentration [OSAP calc]**

Post-publication, original construction (% per month, t-statistic). Long leg = top portfolio minus the EW average of portfolios; short leg = average minus the bottom portfolio.

| Signal | Long leg | Short leg |
|---|---|---|
| ShareIss1Y | 0.18 (1.4) | 0.76 (3.5) |
| XFIN | 0.28 (3.0) | 0.95 (3.4) |
| Asset growth | -0.03 (-0.1) | 0.52 (3.1) |
| NOA | -0.29 (-1.6) | 0.32 (3.1) |
| Accruals | -0.07 | 0.16 (2.4) |
| InvGrowth | -0.30 | 0.65 (3.1) |
| roaq (quarterly ROA) | 0.19 (1.4) | 1.16 (3.3) |
| GP | 0.43 (2.7) | 0.47 (1.8) |
| OperProfRD | 0.65 (2.5) | 0.08 (0.2) |
| CBOperProf | 0.63 (2.4) | -0.09 |
| AnnouncementReturn | 0.41 (5.4) | 0.39 (3.2) |
| EarningsStreak | 0.24 (2.6) | 0.42 (3.2) |
| BMdec | 0.28 (3.3) | 0.31 (2.7) |

Long legs in 2015-25 (% per month, t-statistic):
- GP 0.45 (2.7)
- OperProfRD 0.57 (2.6)
- CBOperProf 0.58 (2.6)
- ShareIss5Y 0.26 (2.0)
- XFIN 0.29 (2.0)
- AnnouncementReturn 0.10 (1.1)
- BMdec 0.13 (0.7)

Source: [OSAP](https://www.openassetpricing.com/).

**Why anomalies concentrate on the short side**
- Stambaugh, Yu & Yuan (2012) studied 11 anomalies. Short legs are more profitable after high sentiment, and sentiment has no relation to long-leg returns. On average, 78% of benchmark-adjusted short-leg profits occur after high-sentiment months. Long-short profits are 1.22%/month after high sentiment vs 0.52% after low sentiment (1965-2008) — [Stambaugh, Yu & Yuan, JFE 2012 (NBER w16898)](https://www.nber.org/papers/w16898.pdf); [UMN record](https://experts.umn.edu/en/publications/the-short-of-it-investor-sentiment-and-anomalies/).

**Unprofitable firms**
- Fama & French ("Dissecting Anomalies") find a pervasive positive profitability-return relation among *profitable* firms. The evidence that unprofitable firms have unusually low returns is weaker — [Fama & French, Dissecting Anomalies, JF 2008](https://www.johnhcochrane.com/s/fama_french_dissecting_anomalies_JF.pdf).
- Among loss firms, book-to-market and revenue-to-price positively predict returns, and the value effects are significantly stronger than among profitable firms. The authors attribute this to analyst over-optimism for loss firms — [Mohrschladt & Siedhoff, Abacus 2024](https://ideas.repec.org/a/bla/abacus/v60y2024i4p752-776.html).
- Firms with extreme losses show -6.58% abnormal post-announcement drift, vs +3.55% for extreme profits — [Post-Losses Announcement Drift (NYU working paper)](https://archive.nyu.edu/bitstream/2451/27762/2/Post%20Losses%20Announcement%20Drift%2010-2008.pdf).

**R&D in high-tech and biotech**
- A dissertation on biotech, IT and renewable energy finds the R&D-return relation varies by size and sub-industry. Smaller biotech firms show a stronger positive association between lagged R&D and returns. This is a single, non-peer-reviewed source — [Princeton thesis record](https://theses-dissertations.princeton.edu/signposting/describedby/8fe74f37-ea92-4e37-8c2d-ed49ff508331).
- Goyal & Wahal argue that industry-adjusted R&D/book equity forecasts cash profitability for up to 3 years, i.e., R&D works through expected profitability — [Goyal & Wahal SSRN 4339765](https://agtaz19.github.io/pdf/ssrn-4339765.pdf).

**Size dependence**
- JKP find small and micro replication rates (85.7%) are comparable to large-cap rates (79.8%). Nano caps (below the NYSE 1st percentile) behave differently (68.1%) — [JKP 2023](https://research-api.cbs.dk/ws/portalfiles/portal/95651880/theis_ingerslev_jensen_et_al_is_there_a_replication_crisis_in_finance_publishersversion.pdf).

### Inferences

**For a long-only growth or small-cap book:**
- Use profitability (GP/assets, cash-based operating profitability) and announcement-return/streak signals as *positive* selectors.
- Use issuance (ShareIss1Y, XFIN), asset/inventory growth, NOA and accruals only as *exclusion* screens, where their value lies.
- Valuation (revenue/price, EV/sales) is the most defensible way to rank unprofitable firms. B/M and E/P are undefined or noisy when equity or earnings are negative.

**Cash burn / runway** has no well-replicated stand-alone published anomaly that I found. It is economically tied to dilution, because cash-burning firms issue. That makes "low expected dilution" (high runway) the likely mechanism, overlapping the issuance anomaly.

### Gaps
- No found source tests these anomalies within EV, crypto-adjacent, space, nuclear or quantum stocks specifically, or within energy or tech sectors in recent data. The project's own PIT EDGAR + price database could test this directly.
- I found no academic test of cash runway (cash / quarterly burn) as a predictor.

## Typical realistic ICs and hit rates, and how much transaction costs take at monthly rebalancing

### Takeaway
Net of realistic trading costs and post-publication decay, the average published anomaly earns about 4 bp/month (Chen-Velikov). The strongest individual anomalies earn about 10 bp, and anomaly combinations about 20 bp.

Low-turnover accounting signals (annual rebalancing, under 50% one-sided monthly turnover) are the ones that survive costs. Monthly-rebalanced, high-turnover strategies in small caps mostly do not.

Monthly hit rates of the surviving long-short signals in 2015-25 are only 55-64%.

### Cited Findings

**Net-of-cost returns (Chen & Velikov)**
- For 204 anomalies, after effective bid-ask spreads, post-publication decay and the modern trading era, the average expected return is about 4 bp/month. The strongest anomalies net at most 10 bp after controlling for data mining, and combinations net about 20 bp — [Chen & Velikov, JFQA 2023](https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/zeroing-in-on-the-expected-returns-of-anomalies/945133D5A3ECEEAF466AEE91551FD225); [FEDS 2020-039](https://www.federalreserve.gov/econres/feds/zeroing-in-on-the-expected-returns-of-anomalies.htm).
- An earlier draft found the average equal-weighted long-short portfolio nets -3 bp/month post-publication after costs, and cost-optimized versions net 4-12 bp. Note the version differences: the working paper covered 120 anomalies and 8 bp; the published version covers 204 anomalies and 4 bp — [FEDS working paper PDF](https://www.federalreserve.gov/econres/feds/files/2020039pap.pdf).

**Turnover and cost mitigation (Novy-Marx & Velikov)**
- Anomalies with under 50% one-sided monthly turnover generally keep significant net spreads when designed to mitigate costs. Few higher-turnover strategies do — [Novy-Marx & Velikov, RFS 2016 (NBER w20721)](https://www.nber.org/papers/w20721).
- A buy/hold spread is the most effective simple cost mitigation. Size, value and profitability have the greatest capacity — [NBER w20721](https://www.nber.org/papers/w20721); [RePEc](https://econpapers.repec.org/RePEc:oup:rfinst:v:29:y:2016:i:1:p:104-147.).

**Hit rates [OSAP calc]**
- Monthly long-short win rates in 2015-25: ShareIss1Y 64%, AnnouncementReturn 64%, EarningsStreak 63%, GP 61%, RevenueSurprise 61%, BMdec 53%, Accruals 45% — [OSAP](https://www.openassetpricing.com/).

**IC and the fundamental law**
- IC is the cross-sectional correlation between the signal and forward returns. Under the fundamental law, IR ≈ IC × TC × √N, and a consistent IR estimate is mean(IC)/sd(IC) — [Ding & Martin / arXiv 2010.08601](https://arxiv.org/pdf/2010.08601v1.pdf); [CFA Institute technical appendix](https://www.cfainstitute.org/-/media/documents/support/programs/cfa/technical-append-to-analysis-of-active-portfolio-mgmt.pdf).

### Inferences
- I found no peer-reviewed source for per-signal rank ICs. The commonly quoted range for single fundamental signals is about 0.02-0.05 monthly rank IC, but this is a practitioner rule of thumb I could not verify. It is consistent with the decile spreads above: a 0.5-1%/month top-bottom spread with about 10% cross-sectional monthly volatility implies an IC of a few percent.
- Prefer annual or quarterly rebalanced accounting signals with buy/hold bands. Monthly-rebalanced, equal-weighted small-cap implementations of issuance and SUE likely lose most of their gross edge.

### Gaps
- I did not obtain per-anomaly turnover and cost tables from Novy-Marx & Velikov.
- I have no sourced per-signal rank ICs. The project can compute them directly from its EDGAR + price data.

## Exact computation from SEC EDGAR XBRL (us-gaap concepts) with point-in-time timing

### Takeaway
All of the surviving signals can be built from free EDGAR XBRL companyfacts:
- GP/assets;
- operating and cash-based profitability;
- share issuance;
- external financing;
- asset growth;
- accruals;
- revenue/price and B/M;
- SUE.

Each fact carries `filed` (filing date) and `accn`. The accession number joins to the submissions API, whose `acceptanceDateTime` gives the exact availability timestamp.

Use the *first-filed* value for each period (not the restated value), and treat data as known from the acceptance timestamp. Rebalance with an extra 1-2 day buffer. Practical XBRL history starts around 2009-2011, so backtests are limited to about 15 years.

### Cited Findings
- EDGAR's data.sec.gov APIs (submissions, companyfacts, companyconcept, frames) need no authentication. The XBRL APIs update within about a minute of filing. The bulk companyfacts.zip contains all companyfacts/frames data. Frames return the one fact per entity that was "last filed" and most closely fits the requested calendar period — [SEC EDGAR API documentation](https://www.sec.gov/page/sec-api-documentation).
- An unofficial schema describes companyfacts' `filed` field as the date EDGAR accepted the filing — [apis.io SEC Company Facts schema](https://apis.io/apis/sec/sec-company-facts-api/). This is third-party; check it against live data.
- Because frames choose the *last filed* fact, they reflect restatements. They are not point-in-time-safe for backtests — [SEC EDGAR API documentation](https://www.sec.gov/page/sec-api-documentation).
- JKP lag all accounting data 4 months. HXZ use mixed update schemes. Results are somewhat sensitive to the lag. One documented case: the Xie (2001) abnormal-accruals paper used a 3-month lag, which OSAP believes explains its weaker replication — [JKP 2023](https://research-api.cbs.dk/ws/portalfiles/portal/95651880/theis_ingerslev_jensen_et_al_is_there_a_replication_crisis_in_finance_publishersversion.pdf); [OSAP SignalDoc](https://github.com/OpenSourceAP/CrossSection/blob/master/SignalDoc.csv).

### Inferences

The concept mappings below are my own, based on standard us-gaap taxonomy names. They need fallbacks because filers use alternative tags. Annual values use FY/10-K facts with a duration of about 365 days; TTM means the sum of the last 4 quarterly durations, derived from 10-Q year-to-date facts by differencing.

| Signal | Formula | us-gaap concepts (with fallbacks) | Timing |
|---|---|---|---|
| Gross profitability (Novy-Marx) | (Revenue − COGS) / Total assets | `GrossProfit`; else `Revenues` / `RevenueFromContractWithCustomerExcludingAssessedTax` / `SalesRevenueNet` (pre-2018) minus `CostOfRevenue` / `CostOfGoodsAndServicesSold` / `CostOfGoodsSold`; denominator `Assets` | Annual (10-K), or TTM from 10-Qs; available at acceptance |
| Operating profitability (FF RMW) | (Rev − COGS − SG&A − interest) / book equity | Add `SellingGeneralAndAdministrativeExpense`, `InterestExpense`; book equity = `StockholdersEquity` (fallback `StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest`) | Same |
| R&D-adjusted operating profitability (Ball et al. 2016) | (Rev − COGS − SG&A excluding R&D) / Assets | `ResearchAndDevelopmentExpense` added back if included in SG&A (most XBRL filers report it separately, so use Rev − COGS − SG&A) | Same |
| Cash-based operating profitability | Operating profitability − ΔAR − Δinventory − Δprepaids + Δdeferred revenue + ΔAP + Δaccrued, over Assets | `AccountsReceivableNetCurrent`, `InventoryNet`, `PrepaidExpenseCurrent`, `ContractWithCustomerLiabilityCurrent` / `DeferredRevenueCurrent`, `AccountsPayableCurrent`, `AccruedLiabilitiesCurrent`; or use `IncreaseDecreaseInAccountsReceivable` etc. from the cash-flow statement | Same |
| Accruals (Sloan, cash-flow version) | (Net income − CFO) / average Assets | `NetIncomeLoss` (or `IncomeLossFromContinuingOperations`), `NetCashProvidedByUsedInOperatingActivities` | Annual |
| Asset growth (CGS; CMA proxy) | Assets_t / Assets_{t−1} − 1 | `Assets` | Annual |
| Net share issuance 1Y (Pontiff-Woodgate) | log(split-adjusted shares_t / shares_{t−12m}) | `dei:EntityCommonStockSharesOutstanding` (cover page, most timely) or `CommonStockSharesOutstanding`; split-adjust with `StockholdersEquityNoteStockSplitConversionRatio1` or price-data split factors | Quarterly; cover-page date is near the filing date |
| Net external financing (XFIN, Bradshaw-Richardson-Sloan) | (Equity issued − repurchases − dividends + debt issued − debt repaid) / avg Assets | `ProceedsFromIssuanceOfCommonStock`, `PaymentsForRepurchaseOfCommonStock`, `PaymentsOfDividends`, `ProceedsFromIssuanceOfLongTermDebt`, `RepaymentsOfLongTermDebt` | Annual or TTM |
| Book-to-market | Book equity / market cap | `StockholdersEquity` minus `PreferredStockValue`; market cap from price × shares at rebalance date | Use the latest filed book value |
| Sales/price, EV/sales | Revenue TTM / market cap | Revenue tags as above; EV adds `LongTermDebt` + `DebtCurrent` − `CashAndCashEquivalentsAtCarryingValue` | — |
| SUE (seasonal random walk) | (EPS_q − EPS_{q−4}) / sd(last 8 differences) | `EarningsPerShareDiluted` / `EarningsPerShareBasic`; Q4 = FY − 9M YTD | Event-time from 10-Q/10-K acceptance |
| Earnings announcement return | Cumulative abnormal return over [−1,+1] around the announcement | Event date: the 8-K Item 2.02 acceptance time (submissions API, `items` field), which typically precedes the 10-Q | Not available from XBRL alone |
| F-score | 9 binary tests | `NetIncomeLoss`, `NetCashProvidedByUsedInOperatingActivities`, `Assets`, `LongTermDebtNoncurrent`, `AssetsCurrent` / `LiabilitiesCurrent`, shares, gross margin, asset turnover | Annual |
| R&D intensity | R&D / market cap, or R&D / Assets | `ResearchAndDevelopmentExpense` (also `ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost`) | — |
| Cash runway | Cash / max(−CFO_TTM, ε) × 4 (in quarters) | `CashAndCashEquivalentsAtCarryingValue` + `ShortTermInvestments` / `MarketableSecuritiesCurrent`; quarterly CFO from YTD differencing | — |
| CHS failure probability | Logit on NIMTAAVG, TLMTA, EXRETAVG, SIGMA, RSIZE, CASHMTA, MB, PRICE | `NetIncomeLoss`, `Liabilities`, cash tags, plus prices | Market variables come from prices |

Point-in-time rules:
- Choose each (concept, period end) value from the fact with the earliest `filed` date. Ignore later 10-K/A or comparative-period refilings.
- Use the submissions API `acceptanceDateTime` for the accession. A filing accepted after 16:00 ET is tradable the next session.
- Do not use frames for backtests.

### Gaps
- I did not verify the SEC's own definition of the companyfacts `filed` field; the only source found is third-party.
- I did not verify the tag-usage frequency of the fallback concepts; it should be checked empirically in the companyfacts bulk data.
