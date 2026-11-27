# Data readiness: READY (0 blockers)

Checked 2026-11-27T01:56 UTC. Splits: train 2016-01-01 → 2021-12-31, validation 2022-02-05 → 2023-12-31, test 2024-02-05 → 2026-11-27

| | Check | Detail | Fix |
|---|---|---|---|
| ✅ | built: panel | db/signals/panel.parquet ok |  |
| ✅ | built: validation | db/signals/validation.json ok |  |
| ✅ | built: daily | db/signals/daily/validation.json ok |  |
| ✅ | built: regime | db/regime/regime.parquet ok |  |
| ✅ | built: portfolio | db/portfolio/summary.json ok |  |
| ✅ | built: rl_dataset | db/rl/meta.json ok |  |
| ✅ | price coverage | 11 years since 2016 with >= 300 liquid tracked-industry names (need 8); per year: 2016: 755, 2017: 863, 2018: 973, 2019: 1038, 2020: 1239, 2021: 1627, 2022: 1450, 2023: 1404, 2024: 1499, 2025: 1622, 2026: 1604 |  |
| ✅ | core signals filled | missing share within the liquid universe (gross profitability: among companies with revenue): mom_12_1 8%, high_52w 6%, vol_60d 1%, gross_prof 25%, op_cf_assets 26%, net_issuance 22% |  |
| ✅ | failed companies have prices | 456 of 629 exchange-listed companies that failed or delisted since 2016-01-01 have prices (72%; need 25%) |  |
| ✅ | out-of-sample composite history | 165 months (need 60); 18 proven signals |  |
| ✅ | regime inputs | 100.0% of trading days since 2016-01-01 have VIX, credit spread and breadth |  |
| ✅ | no-hindsight timestamps | 0 violations in 8 tables |  |
| ✅ | clean prices | 3 zero/negative, 1,810 daily moves beyond +300%/-95%, 0 duplicate bars, of 9,107,202 |  |
| ✅ | core data current | prices: ok (1.2 days); filings: ok (1.0 days); macro: ok (1.1 days) |  |
| ✅ | optional: inst_holdings | ok, 87.1 days old |  |
| ⚠️ | optional: intraday | missing | python -m ddb.db.build_intraday && python -m ddb.features.intraday |
| ⚠️ | optional: spreads | missing | python -m ddb.db.build_spreads |
| ⚠️ | optional: news_events | missing | python -m ddb.news.gdelt (backfill: hpc/gdelt_backfill.sbatch) |
| ✅ | RL dataset | weekly decisions per split {'train': 313, 'validation': 99, 'test': 147}; 9 industry sleeves over 145 months; market and haven features complete |  |
| ✅ | haven income included | T-bill ETF distributions in the RL price data: 39.83 per share over the sample (BIL, SGOV); without them T-bills show ~0% return |  |
| ⚠️ | sparse industries | few listed companies early on, so their features are mostly missing (masked in the environment): first buy candidate crypto_adj 2022-06-03, quantum never, space 2025-08-01 | expected for young industries; consider dropping a sleeve that never has candidates |
| ✅ | test period untouched | opened 0 times |  |
