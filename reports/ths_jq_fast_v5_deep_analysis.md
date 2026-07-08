# Wufu ETF THS vs JQ V5 Minute Log Report

## Conclusion

V5 worked as a validation version. After THS enabled `external_weak=True`, weak-state match reached `100.00%`, and target match improved from V4 `90.60%` to V5 `98.48%`. This confirms the main V4 issue: THS could not fetch `000510`, so the weak-market state machine diverged.

## Key Metrics

- Common trading days: `1575`
- Date range: `2020-01-02` to `2026-07-06`
- Target match: `1551/1575`, or `98.48%`
- Remaining mismatch days: `24`
- Weak-state match: `1575/1575`, or `100.00%`
- THS total return from first close: `6860.66%`
- THS max drawdown: `-23.70%`

## V4 to V5

| Metric | V4 | V5 |
|---|---:|---:|
| Target match | 90.60% | 98.48% |
| Weak-state match | 89.84% | 100.00% |
| Weak-state mismatch days | 160 | 0 |
| Target mismatch days | 148 | 24 |

## Remaining Difference

The remaining 24 mismatch days are no longer caused by weak-state divergence. Most of them have Top10 overlap of `9/10` or `10/10`, which means the candidate sets are already very close. The remaining differences likely come from 13:10 current price, intraday volume, R2/momentum score inputs, liquidity-filter boundary, or execution handling.

## Next Step

V6 adds diagnostics only for these 24 dates:

- `WUFU_SCORE_DETAIL`
- `WUFU_THRESHOLD_DETAIL`
- `WUFU_POOL_FILTER`
- `WUFU_POSITION`

Use the V6 scripts and compare the new logs to isolate the remaining score and execution differences.
