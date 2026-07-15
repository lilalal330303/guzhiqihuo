# Task 7 implementation report

## Outcome

- Implemented and executed the resumable `fixed11_gradual` V3.3 experiment CLI through core, routes, walk-forward, cost, and stress stages.
- The research workflow completed with `passed=true`; this means the evidence and audits are complete, not that a strategy route passed.
- No route qualified: `qualified_route_count=0`. Balanced, return, and defensive all retain the conservative `missing_policy_fold` gate result.
- Bulk artifacts remain uncommitted under `reports/small_cap_fixed11_gradual_next_stage/`.

## Final run contract and evidence

- Requested interval: 2020-01-01 through 2026-07-06; initial cash CNY 1,000,000.
- Global schema: `fixed11-gradual-v3.3`; stress evidence schema: `diagnostic-v1`.
- Experiment fingerprint: `0a67dbda1f37506fd9e7ef1d2febe741e10241f93a814609d0b15df31403d53d`.
- Database SHA-256 before/after: `65c56b0df35a451841727b876c555a21e8181bd2520313db1ec6ef4cb8bcb175`; size 5,568,212,992 bytes and mtime were also unchanged.
- Same-snapshot independent V2 anchor maximum absolute equity difference: `3.725290298461914e-09`.
- Historical artifact drift remains separately recorded: historical end equity CNY 21,296,433.48 and maximum absolute drift CNY 6,581,644.68. It is not used as the current-snapshot anchor.
- Full-sample candidates: 66 = 37 core + 29 routes, below the limit of 70.
- Walk-forward: five folds, 27 training calls per fold, 135 training calls total, 19 non-anchor test calls plus five anchor tests. Selection leakage count is zero.
- Total current-fingerprint audits: 261 = 66 full sample + 135 training + 24 test + 36 diagnostic stress audits.
- Maximum account reconciliation error: `3.725290298461914e-09`; global minimum cash: CNY 0.3723245.

## Crash mechanism audit

- Exact indicator warmup uses 60 prior trading dates; trigger ratios are measured only on the requested interval.
- Overlay 01: 31.2381%, failed.
- Overlay 02: 34.3492%, failed.
- Overlay 03: 22.2222%, failed.
- Overlay 04: 19.6825%, passed.
- Overlay 05: 11.3016%, passed.
- Overlay 06: 13.0159%, passed.
- Only the three passing overlays entered the walk-forward universe. The universe was 27 candidates: one anchor plus 26 route candidates.

## Walk-forward decisions

- Balanced produced stable policies in 4/5 folds and missed 2023.
- Return produced stable policies in 4/5 folds and missed 2022.
- Defensive produced a stable policy in only 1/5 folds.
- No missing route/fold was backfilled. All three gates remain `passed=false`, with no selected candidate and reason `missing_policy_fold`.
- Normal non-anchor test calls were 19, below the limit of 45.

## Diagnostic cost and stress evidence

Because no route had a complete five-fold policy, the stress stage selected one explicitly in-sample diagnostic leader per route. These leaders are marked `diagnostic_only=true`, `qualified_for_gate=false`, `diagnostic_available=true`, and `selection_basis=full_sample_in_sample`; their results never enter route gates.

- Balanced leader: `balanced__recovery_0.45_confirm_2`.
- Return leader: `return__one_factor_fixed_stop_loss_0p115__current`.
- Defensive leader: `defensive__crash_overlay_05`.
- Stress table: 57 rows = 42 cost rows + 12 stress-window rows + 3 missing-policy markers; each route has 19 rows.
- Seven cost models are complete: combined 1x/1.5x/2x, fee-only 1.5x/2x, and slippage-only 1.5x/2x. Each model has candidate and anchor rows for all three routes.
- Two windows are complete: 2024 Q1 and 2026 YTD. Each has candidate and anchor rows for all three routes.
- New unique diagnostic audits: 36 = 28 cost audits plus eight window audits. Shared anchor runs are reused safely across routes.
- `cost_evidence_complete=true` and `stress_evidence_complete=true`.

Combined 1x to 2x diagnostic results were not monotonic:

- Balanced total return 17.9942 to 16.2726; maximum drawdown -27.31% to -27.52%.
- Return total return 17.4176 to 18.8601; maximum drawdown -27.30% to -27.51%.
- Defensive total return 12.9934 to 13.7444; maximum drawdown -22.27% to -22.63%.

The higher return under higher modeled cost for return/defensive is not interpreted as a benefit from cost. Integer-share sizing, changed fills, and path-dependent rebalancing can alter later holdings, so the stress matrix is a scenario result rather than a monotonic fee subtraction. This effect must be highlighted in downstream analysis.

Window diagnostics:

- 2024 Q1: balanced and return -1.14% with -29.84% maximum drawdown; defensive +6.10% with -20.69% maximum drawdown.
- 2026 YTD: all three diagnostic leaders -2.99% with -21.23% maximum drawdown.

## Artifact and completion audit

- All four stages are complete.
- All eleven root artifacts are present and non-empty: manifest, catalog, core scores, route scores, walk-forward training, walk-forward test, route gates, annual returns, stress results, target manifest, and rejected candidates.
- All 36 new diagnostic audits passed; their maximum reconciliation error was `3.725290298461914e-09` and minimum cash was CNY 0.944889.
- `route_decisions` validates diagnostic and formal semantics, missing-policy fold counts, unavailable-candidate markers, reasons, and qualification status.
- Completion validates the unchanged database, anchor parity, account reconciliation, non-negative cash, call limits, zero leakage, crash mechanism evidence, stress schema, evidence counts, route decisions, and non-empty root artifacts.

## TDD and verification

Final verification commands:

`\.venv\Scripts\python.exe -m pytest tests\test_small_cap_index_history.py tests\test_fixed11_gradual_next_stage_cli.py tests\test_small_cap_experiment.py tests\test_optimized_v3_runner.py tests\test_optimized_v3_walkforward.py tests\test_optimized_v2_grid.py -q`

Result: 81/81 passed.

`\.venv\Scripts\python.exe -m py_compile tools\run_fixed11_gradual_next_stage.py tests\test_fixed11_gradual_next_stage_cli.py`

`git diff --check`

Both checks passed. Independent review approved through `a916ef6`; the final focused reviewer suite passed 59/59.

Executed stage commands:

- `\.venv\Scripts\python.exe tools\run_fixed11_gradual_next_stage.py --stage routes --resume`
- `\.venv\Scripts\python.exe tools\run_fixed11_gradual_next_stage.py --stage walkforward --resume`
- `\.venv\Scripts\python.exe tools\run_fixed11_gradual_next_stage.py --stage stress --resume`

## Task 7 commits

- `2f82fc6 feat: orchestrate fixed11 gradual next-stage research`
- `759950d fix: harden next-stage research audits`
- `4ecbaa5 fix: isolate experiment snapshots`
- `706c7d0 fix: validate resumable period evidence`
- `5b6d406 fix: fingerprint root experiment evidence`
- `5ae7f5a fix: gate crash overlays by trigger ratio`
- `905a9f6 fix: scope crash audit to evidence interval`
- `348785a fix: version crash mechanism evidence`
- `f8b2cde fix: load exact crash indicator warmup`
- `d3e62f5 feat: add diagnostic stress evidence`
- `3d8bf60 fix: audit absent diagnostic routes`
- `7da4eb0 fix: validate diagnostic completion evidence`
- `a916ef6 fix: enforce route decision semantics`
