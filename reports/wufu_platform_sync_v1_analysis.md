# Wufu Platform Sync V1 Local Backtest

## Version plan

1. V1 diagnostics and boundary sync: add platform detail logs, use JoinQuant-style previous-day weak-state boundary locally, and rerun local backtest.
2. V2 amount calibration: compare `WUFU_THRESHOLD_DETAIL` rows, normalize SuperMind amount units, then rerun fixed-threshold isolation.
3. V3 pool isolation: replay a fixed daily ETF pool across both platforms and locate metadata/name-cleaning drift.
4. V4 scoring isolation: compare `WUFU_SCORE_DETAIL` top candidates, then align current price, volume, and adjustment rules.
5. V5 execution isolation: align minimum order, round lot, capacity, failed-order handling, commission, and slippage.

## Local run

- Run ID: `70bc7d0b-7307-4dd9-b38e-d0c1bb93b708`
- Range: `2020-01-01` to `2026-07-06`
- Total return: `10.474569`
- Annualized return: `0.477970`
- Max drawdown: `-0.374495`
- Trade count: `809`
- Win rate: `0.530284`

## Platform target comparison

- JoinQuant common days: `1575`, matched days: `931`, match rate: `0.5911111111111111`
- SuperMind common days: `1574`, matched days: `784`, match rate: `0.49809402795425667`

## Dynamic pool audit

- Rows: `1575`
- JoinQuant target in local dynamic pool rate: `0.6558730158730158`
- JoinQuant target in local candidates rate: `0.5885714285714285`
- Reason counts: `{'matched_target': 931, 'in_dynamic_pool_not_candidate': 322, 'not_in_local_dynamic_pool': 242, 'in_candidates_not_top': 80}`

## Reading

V1 should be judged by comparability, not only return. The expected next evidence is a pair of platform minute logs with `WUFU_WEAK_DETAIL`, `WUFU_THRESHOLD_DETAIL`, `WUFU_POOL_DETAIL`, and `WUFU_SCORE_DETAIL`; those rows will show whether the remaining target drift comes from index state, amount threshold, ETF universe, or scoring inputs.

## Interpretation

Compared with iteration 6, this V1 local run reduced total return from about `16.95` to `10.47`, increased max drawdown from about `-0.30` to `-0.37`, and reduced JoinQuant target match from about `0.6972` to `0.5911`. This is useful evidence: simply forcing the local weak-state generator to lag by one trading day is not the right final repair.

The likely reason is that there are two different timing problems mixed together:

1. JoinQuant's `09:40` weak-state calculation uses `context.previous_date`, so the index close source should be previous trading day.
2. The local daily target generator still scores ETF candidates from daily bars, while the platform scripts score with `13:10` current price and current volume. Changing only weak-state timing can therefore move regime selection without fixing the intraday scoring input.

The next iteration should not guess another weak lag. It should rerun both platform scripts and compare the new detail logs:

- `WUFU_WEAK_DETAIL`: decide whether each index uses the same last index date, close, MA10, above/below relation.
- `WUFU_THRESHOLD_DETAIL`: decide whether SuperMind's amount unit is smaller than JoinQuant's and by what multiplier.
- `WUFU_POOL_DETAIL`: decide whether all-market ETF metadata and name cleaning produce the same industry representatives.
- `WUFU_SCORE_DETAIL`: decide whether target drift is caused by current price, volume filter, R2, or loss filter.

## Next small version

V2 should focus on amount calibration only:

1. Run `同花顺_聚宽五福ETF同步诊断V1.py` and `聚宽_五福ETF同步诊断V1.py` in minute mode for the same date range.
2. Parse both `WUFU_THRESHOLD_DETAIL` logs and build a daily ratio table.
3. If the ratio is stable, add a SuperMind amount multiplier or unit-normalization branch.
4. Rerun with weak-state unchanged and compare target match. A good V2 target is threshold ratio median between `0.9` and `1.1`, while weak match and target match should not deteriorate.
