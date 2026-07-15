# fixed11_gradual Next-Stage Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and run a leakage-controlled three-route optimization program around `fixed11_gradual`, producing one balanced, one return-seeking, and one defensive candidate only when each route passes its stated out-of-sample gates.

**Architecture:** Add a focused V3 experiment-definition module, extend the existing daily portfolio engine only for parameterized profit protection, and keep target generation, portfolio execution, walk-forward selection, and reporting in their existing architectural layers. Every training fold evaluates the complete approved candidate universe, selects at most three candidates per route using training data only, freezes those candidates for the next test window, and records rejected as well as selected variants.

**Tech Stack:** Python 3, pandas, NumPy, DuckDB, pytest, existing `quant_lab` strategy/backtest/research modules, canonical portable HTML report builder.

## Global Constraints

- Preserve CNY 1,000,000 initial cash, T-day close signals, T+1 first tradable open execution, 100-share lots, existing fees, and `buy_new_only=True`.
- Compare every candidate with `fixed11_gradual` over exactly the same dates and source snapshots.
- Keep ATR disabled, financial red lines unchanged, and stock symbols as six-character strings.
- Frozen-target experiments must preserve original row order; dynamic-holdings experiments must write new target files and SHA-256 hashes.
- A training window may rank candidates only from its own dates. Test-window metrics must never affect selection for that fold.
- Account reconciliation error must be below `1e-6`; cash must never be negative.
- Keep new research orchestration under `src/quant_lab/research/`, execution under `src/quant_lab/backtest/`, and report builders under `tools/`.
- Do not alter unrelated dirty-worktree files.
- Treat daily results as strict daily approximations, not full JoinQuant minute-level reproductions.

---

### Task 1: V3 experiment contracts and approved matrices

**Files:**
- Create: `src/quant_lab/research/optimized_v3_design.py`
- Create: `tests/test_optimized_v3_design.py`

**Interfaces:**
- Produces: `CoreVariant`, `RecoveryVariant`, `StockCountProfile`, `CrashOverlayVariant`, and `ProfitProtectionVariant` frozen dataclasses.
- Produces: `core_one_factor_variants() -> list[CoreVariant]` with 20 unique variants including the anchor.
- Produces: `core_l18_variants() -> list[CoreVariant]` with at most 18 non-duplicate orthogonal variants.
- Produces: `recovery_variants()`, `stock_count_profiles()`, `crash_overlay_variants()`, and `profit_protection_variants()`.

- [ ] **Step 1: Write failing contract and matrix tests**

```python
from quant_lab.research.optimized_v3_design import (
    CoreVariant,
    core_l18_variants,
    core_one_factor_variants,
    crash_overlay_variants,
    profit_protection_variants,
    recovery_variants,
    stock_count_profiles,
)


def test_core_one_factor_matrix_is_unique_and_contains_anchor():
    variants = core_one_factor_variants()
    assert len(variants) == 20
    assert len({variant.name for variant in variants}) == 20
    anchor = next(item for item in variants if item.name == "fixed11_gradual")
    assert anchor.fixed_stop_loss == 0.11
    assert anchor.cooldown_days == 2
    assert anchor.warning_threshold == 0.48
    assert anchor.reduced_budget == 0.25
    assert anchor.confirmation_days == 2
    assert anchor.clear_threshold == 0.50


def test_every_core_variant_has_valid_crowding_order():
    for variant in core_one_factor_variants() + core_l18_variants():
        assert 0 < variant.warning_threshold < variant.clear_threshold < 1
        assert 0 <= variant.reduced_budget <= 1


def test_route_specific_matrix_sizes():
    assert len(recovery_variants()) == 6
    assert [item.counts for item in stock_count_profiles()] == [
        (2, 3, 4, 5), (3, 4, 5, 6), (4, 5, 6, 7)
    ]
    assert len(crash_overlay_variants()) == 6
    assert len(profit_protection_variants()) == 4
```

- [ ] **Step 2: Run the tests and confirm the missing-module failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_optimized_v3_design.py -q`

Expected: FAIL during collection with `ModuleNotFoundError: quant_lab.research.optimized_v3_design`.

- [ ] **Step 3: Implement immutable contracts and deterministic matrices**

```python
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class CoreVariant:
    name: str
    fixed_stop_loss: float = 0.11
    cooldown_days: int = 2
    warning_threshold: float = 0.48
    reduced_budget: float = 0.25
    confirmation_days: int = 2
    clear_threshold: float = 0.50


@dataclass(frozen=True)
class RecoveryVariant:
    name: str
    recovery_threshold: float
    recovery_confirmation_days: int
    recovery_step_days: int = 1


@dataclass(frozen=True)
class StockCountProfile:
    name: str
    counts: tuple[int, int, int, int]


@dataclass(frozen=True)
class CrashOverlayVariant:
    name: str
    drawdown_threshold: float
    defensive_budget: float
    recovery_confirmation_days: int
    lookback: int = 60


@dataclass(frozen=True)
class ProfitProtectionVariant:
    name: str
    activation_profit: float
    profit_floor: float


ANCHOR = CoreVariant(name="fixed11_gradual")
```

Implement the 20 approved one-factor variants by replacing exactly one anchor field. Implement L18 with a hard-coded, reviewed 18-row six-column level matrix so row order is deterministic; map levels to `(0.105, 0.11, 0.115)`, `(1, 2, 3)`, `(0.47, 0.48, 0.49)`, `(0.15, 0.25, 0.35)`, `(1, 2, 3)`, and `(0.50, 0.51, 0.52)`. Deduplicate against the anchor and one-factor parameter tuples.

- [ ] **Step 4: Run focused tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_optimized_v3_design.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the contracts**

```powershell
git add src/quant_lab/research/optimized_v3_design.py tests/test_optimized_v3_design.py
git commit -m "feat: define fixed11 gradual v3 experiment matrices"
```

---

### Task 2: Parameterized gradual crowding and recovery hysteresis

**Files:**
- Modify: `src/quant_lab/research/optimized_v2_grid.py`
- Modify: `tests/test_optimized_v2_grid.py`

**Interfaces:**
- Extends: `build_gradual_crowding_budget(...) -> pd.DataFrame`.
- Adds parameters: `warning_threshold`, `reduced_budget`, `confirmation_days`, `clear_threshold`, `recovery_threshold`, `recovery_confirmation_days`, and `recovery_step_days`.
- Preserves exact anchor output when optional recovery parameters are omitted.

- [ ] **Step 1: Write failing state-machine tests**

```python
def test_gradual_budget_preserves_anchor_behavior():
    crowding = pd.DataFrame({
        "trade_date": pd.date_range("2024-01-02", periods=4, freq="D"),
        "concentration": [0.47, 0.48, 0.48, 0.47],
    })
    result = build_gradual_crowding_budget(crowding)
    assert result["exposure_budget"].tolist() == [1.0, 0.25, 0.0, 1.0]


def test_recovery_hysteresis_requires_safe_confirmation_and_steps_up():
    crowding = pd.DataFrame({
        "trade_date": pd.date_range("2024-01-02", periods=7, freq="D"),
        "concentration": [0.48, 0.48, 0.46, 0.44, 0.44, 0.44, 0.44],
    })
    result = build_gradual_crowding_budget(
        crowding,
        recovery_threshold=0.45,
        recovery_confirmation_days=2,
        recovery_step_days=1,
    )
    assert result["exposure_budget"].tolist() == [0.25, 0.0, 0.0, 0.0, 0.5, 1.0, 1.0]
```

- [ ] **Step 2: Confirm the new keyword arguments fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_optimized_v2_grid.py -q`

Expected: FAIL with `unexpected keyword argument 'recovery_threshold'`.

- [ ] **Step 3: Implement the explicit state machine**

Use these states and transitions:

```python
warning_run = 0
safe_run = 0
budget = 1.0
next_recovery_step = 0

if concentration >= clear_threshold:
    budget, warning_run, safe_run = 0.0, 0, 0
elif concentration >= warning_threshold:
    warning_run += 1
    safe_run = 0
    budget = 0.0 if warning_run >= confirmation_days else min(budget, reduced_budget)
elif budget < 1.0:
    warning_run = 0
    safe_level = warning_threshold if recovery_threshold is None else recovery_threshold
    safe_run = safe_run + 1 if concentration < safe_level else 0
    if safe_run >= recovery_confirmation_days:
        if recovery_step_days <= 0:
            budget = 1.0
        elif budget < 0.5:
            budget = 0.5 if budget < 0.5 else 1.0
            next_recovery_step = recovery_step_days
        elif next_recovery_step <= 1:
            budget = 1.0
            next_recovery_step = 0
        else:
            next_recovery_step -= 1
else:
    warning_run = safe_run = 0
```

Reset `next_recovery_step` whenever a new warning or clear event occurs. Emit exactly one row per input trading date and validate sorted, unique dates.

- [ ] **Step 4: Verify focused and regression tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_optimized_v2_grid.py tests\test_optimized_v3_design.py -q`

Expected: PASS, including exact anchor behavior.

- [ ] **Step 5: Commit the crowding state machine**

```powershell
git add src/quant_lab/research/optimized_v2_grid.py tests/test_optimized_v2_grid.py
git commit -m "feat: parameterize gradual crowding recovery"
```

---

### Task 3: Dynamic stock-count profiles with independent targets

**Files:**
- Modify: `src/quant_lab/research/small_cap_experiment.py`
- Modify: `tests/test_small_cap_experiment.py`
- Create: `tests/test_optimized_v3_targets.py`

**Interfaces:**
- Produces: `dynamic_stock_num(index_diff: float, counts: tuple[int, int, int, int]) -> int`.
- Extends: `build_joinquant_v3_targets(..., dynamic_stock_counts=(3, 4, 5, 6))` without changing default output.
- Produces route-specific target frames containing `signal_date`, `symbol`, `target_weight`, `stock_num`, and `profile_name`.

- [ ] **Step 1: Write failing mapping and baseline-reproduction tests**

```python
def test_dynamic_stock_num_profiles_map_four_market_bands():
    assert dynamic_stock_num(300, (2, 3, 4, 5)) == 2
    assert dynamic_stock_num(0, (2, 3, 4, 5)) == 3
    assert dynamic_stock_num(-300, (2, 3, 4, 5)) == 4
    assert dynamic_stock_num(-600, (2, 3, 4, 5)) == 5


def test_default_profile_matches_frozen_target_hash(strict_repo, expected_hash):
    targets = build_joinquant_v3_targets(
        strict_repo,
        start="2020-01-01",
        end="2026-07-06",
        dynamic_stock_counts=(3, 4, 5, 6),
    )
    assert hash_targets(targets) == expected_hash
```

- [ ] **Step 2: Run focused tests and confirm missing interfaces**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_small_cap_experiment.py tests\test_optimized_v3_targets.py -q`

Expected: FAIL because `dynamic_stock_num` and `dynamic_stock_counts` are not implemented.

- [ ] **Step 3: Extract the mapping without changing defaults**

```python
def dynamic_stock_num(
    index_diff: float,
    counts: tuple[int, int, int, int] = (3, 4, 5, 6),
) -> int:
    if len(counts) != 4 or any(value <= 0 for value in counts):
        raise ValueError("dynamic stock counts must contain four positive integers")
    return (
        counts[0] if index_diff >= 200 else
        counts[1] if index_diff >= -200 else
        counts[2] if index_diff >= -500 else
        counts[3]
    )
```

Call this helper from target generation. Preserve target row order, add `profile_name` only to route-specific exported copies, and keep the existing default schema unchanged for callers that do not request profile metadata.

- [ ] **Step 4: Verify exact target reproduction and all strategy tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_small_cap_experiment.py tests\test_small_cap_strategy.py tests\test_optimized_v3_targets.py -q`

Expected: PASS and default target hash unchanged.

- [ ] **Step 5: Commit target-profile support**

```powershell
git add src/quant_lab/research/small_cap_experiment.py tests/test_small_cap_experiment.py tests/test_optimized_v3_targets.py
git commit -m "feat: parameterize dynamic small-cap holdings"
```

---

### Task 4: Low-frequency crash overlay and mild profit protection

**Files:**
- Modify: `src/quant_lab/backtest/portfolio.py`
- Modify: `tests/test_small_cap_portfolio.py`
- Create: `src/quant_lab/research/optimized_v3_overlays.py`
- Create: `tests/test_optimized_v3_overlays.py`

**Interfaces:**
- Extends `DailyRiskConfig` with `profit_activation: float = 0.30` and `profit_floor: float = 0.10` while keeping `repair_cost_protection=False` by default.
- Produces: `build_crash_exposure_budget(index_bars, drawdown_threshold, defensive_budget, recovery_confirmation_days, lookback=60) -> pd.DataFrame`.
- Crash signal requires both `close < MA60` and rolling-60-day drawdown at or below `-drawdown_threshold`.

- [ ] **Step 1: Write failing overlay tests**

```python
def test_crash_overlay_requires_both_ma60_and_drawdown():
    bars = synthetic_index_bars(
        closes=[100.0] * 60 + [91.0, 89.0, 90.0, 91.0, 92.0]
    )
    budget = build_crash_exposure_budget(
        bars,
        drawdown_threshold=0.10,
        defensive_budget=0.75,
        recovery_confirmation_days=3,
    )
    assert budget.loc[budget["trade_date"].eq(bars.iloc[60]["trade_date"]), "exposure_budget"].item() == 1.0
    assert budget.loc[budget["trade_date"].eq(bars.iloc[61]["trade_date"]), "exposure_budget"].item() == 0.75


def test_profit_protection_uses_configured_activation_and_floor():
    result = run_portfolio_backtest(
        bars=profit_then_retrace_bars(),
        targets=single_stock_targets(),
        risk=DailyRiskConfig(
            enable_atr=False,
            repair_cost_protection=True,
            profit_activation=0.30,
            profit_floor=0.05,
        ),
    )
    sells = result.trades.query("side == 'sell'")
    assert sells.iloc[0]["reason"] == "cost_protection"
```

- [ ] **Step 2: Confirm failures for missing parameters and builder**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_small_cap_portfolio.py tests\test_optimized_v3_overlays.py -q`

Expected: FAIL for missing config fields and overlay module.

- [ ] **Step 3: Implement configurable profit protection**

Move the fixed-stop test before profit protection so the documented reason priority is deterministic, then replace the repaired hard-coded branch with:

```python
if risk.enable_fixed_stop and close < avg_cost * (1.0 - risk.fixed_stop_loss):
    pending_forced_sells.setdefault(symbol, "fixed_stop")
    continue
if risk.enable_cost_protection and risk.repair_cost_protection:
    peak = peak_profit_ratio[symbol]
    if peak >= risk.profit_activation and profit_ratio < risk.profit_floor:
        pending_forced_sells.setdefault(symbol, "cost_protection")
        continue
```

Validate `profit_floor < profit_activation`. Preserve forced-sell priority as fixed stop, then profit protection, ATR, market stop, divergence, and crowding; a symbol may have only one pending reason.

- [ ] **Step 4: Implement the crash-budget builder**

Compute MA60 and rolling 60-day high using only data through T. Emit T-dated signals for application at T+1. Enter defense only when both conditions are true. Exit after `recovery_confirmation_days` consecutive dates where either condition is false. Include diagnostic columns `below_ma60`, `rolling_drawdown`, `defensive`, and `exposure_budget`.

- [ ] **Step 5: Run focused tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_small_cap_portfolio.py tests\test_optimized_v3_overlays.py -q`

Expected: PASS, including T+1 application and no look-ahead.

- [ ] **Step 6: Commit overlays**

```powershell
git add src/quant_lab/backtest/portfolio.py src/quant_lab/research/optimized_v3_overlays.py tests/test_small_cap_portfolio.py tests/test_optimized_v3_overlays.py
git commit -m "feat: add v3 defensive risk overlays"
```

---

### Task 5: Candidate runner, metrics, and neighbor-stability gates

**Files:**
- Create: `src/quant_lab/research/optimized_v3_runner.py`
- Create: `tests/test_optimized_v3_runner.py`

**Interfaces:**
- Produces: `ExperimentCandidate` and `ExperimentResult` frozen dataclasses.
- Produces: `run_candidate(...) -> ExperimentResult` reusing `run_grid` and `run_small_cap_experiment`.
- Produces: `neighbor_stability(scores, candidate, neighbors, tolerance=0.10) -> bool`.
- Produces: `reconcile_account(result) -> float` and rejects error `>=1e-6` or negative cash.

- [ ] **Step 1: Write failing tests for anchor reproduction and stability**

```python
def test_v3_anchor_reproduces_fixed11_gradual(frozen_inputs, expected_equity):
    result = run_candidate(frozen_inputs, ExperimentCandidate.anchor())
    diff = (result.portfolio.equity_curve["equity"] - expected_equity["equity"]).abs().max()
    assert diff < 1e-6


def test_isolated_parameter_spike_fails_neighbor_stability():
    scores = {"left": 1.00, "winner": 1.30, "right": 1.02}
    assert not neighbor_stability(scores, "winner", ["left", "right"], tolerance=0.10)


def test_broad_parameter_plateau_passes_neighbor_stability():
    scores = {"left": 1.20, "winner": 1.30, "right": 1.18}
    assert neighbor_stability(scores, "winner", ["left", "right"], tolerance=0.10)
```

- [ ] **Step 2: Confirm the runner module is missing**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_optimized_v3_runner.py -q`

Expected: FAIL during import.

- [ ] **Step 3: Implement one deterministic execution path**

`ExperimentCandidate` must contain `name`, `route`, `core`, optional `recovery`, optional `stock_profile`, optional `crash_overlay`, and optional `profit_protection`. `run_candidate` must construct `DailyRiskConfig`, exposure-budget input, and target input from those fields, then calculate the existing metrics plus Calmar, maximum underwater calendar days, annual returns, defensive-day count, and mean exposure budget.

- [ ] **Step 4: Add audit failures as hard exceptions**

```python
reconciliation_error = reconcile_account(portfolio)
if reconciliation_error >= 1e-6:
    raise RuntimeError(f"account reconciliation failed: {reconciliation_error}")
minimum_cash = float(portfolio.equity_curve["cash"].min())
if minimum_cash < -1e-9:
    raise RuntimeError(f"negative cash: {minimum_cash}")
```

- [ ] **Step 5: Run focused and existing V2 regression tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_optimized_v3_runner.py tests\test_optimized_v2_grid.py -q`

Expected: PASS and anchor equity difference below `1e-6`.

- [ ] **Step 6: Commit the runner**

```powershell
git add src/quant_lab/research/optimized_v3_runner.py tests/test_optimized_v3_runner.py
git commit -m "feat: add audited v3 optimization runner"
```

---

### Task 6: Strict walk-forward selectors for three routes

**Files:**
- Create: `src/quant_lab/research/optimized_v3_walkforward.py`
- Create: `tests/test_optimized_v3_walkforward.py`

**Interfaces:**
- Produces: `WalkForwardFold`, `RouteGateResult`, and `WalkForwardResult`.
- Produces: `default_folds(last_trade_date) -> list[WalkForwardFold]`.
- Produces: `select_training_candidates(route, training_scores, anchor_scores, limit=3) -> list[str]`.
- Produces: `evaluate_route_gates(route, test_scores, anchor_scores) -> RouteGateResult`.
- Produces: `run_walk_forward(candidate_universe, folds, runner) -> WalkForwardResult`.

- [ ] **Step 1: Write failing fold and leakage tests**

```python
def test_default_walk_forward_folds_are_non_overlapping():
    folds = default_folds(pd.Timestamp("2026-07-06"))
    assert len(folds) == 5
    assert folds[0].train_start == pd.Timestamp("2020-01-01")
    assert folds[0].test_start == pd.Timestamp("2022-01-01")
    assert folds[-1].test_end == pd.Timestamp("2026-07-06")
    assert all(left.test_end < right.test_start for left, right in zip(folds, folds[1:]))


def test_selector_never_receives_test_metrics(spy_runner, candidate_universe):
    run_walk_forward(candidate_universe, default_folds(pd.Timestamp("2026-07-06")), spy_runner)
    for selection_call in spy_runner.selection_calls:
        assert selection_call.max_trade_date <= selection_call.fold.train_end


def test_failed_route_is_not_backfilled_by_lowering_gate():
    result = evaluate_route_gates("defensive", weak_test_scores(), anchor_test_scores())
    assert not result.passed
    assert result.selected_candidate is None
```

- [ ] **Step 2: Run tests and confirm missing module**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_optimized_v3_walkforward.py -q`

Expected: FAIL during import.

- [ ] **Step 3: Implement the five folds and training-only selection**

For every fold:

1. Run the complete approved candidate universe on the training dates.
2. Apply route-specific training constraints and neighbor stability.
3. Select at most three candidates per route using training metrics only.
4. Freeze and run those candidates on the test dates.
5. Persist the training rank, selected parameter hash, and test result separately.

The maximum test count is `5 folds × 3 routes × 3 candidates = 45`. A candidate not selected by the training window must not be run on that fold's test window merely because it performed well elsewhere.

- [ ] **Step 4: Implement exact route gates**

Balanced: median annual-return ratio `>=0.90`, Calmar and Sharpe both better in at least 3 folds, median drawdown not worse, and underwater duration shorter in at least 3 folds.

Return: positive excess return in at least 3 folds, combined drawdown no worse than `-0.32`, no complete test year lagging anchor by more than 0.15, and positive excess under 2× costs.

Defensive: median drawdown improvement at least 0.02, median annual-return ratio `>=0.70`, shorter underwater duration in at least 3 folds, and no drawdown deterioration in the two specified stress windows.

- [ ] **Step 5: Run walk-forward unit tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_optimized_v3_walkforward.py -q`

Expected: PASS, including explicit `selected_candidate=None` for a route with no qualified result.

- [ ] **Step 6: Commit walk-forward logic**

```powershell
git add src/quant_lab/research/optimized_v3_walkforward.py tests/test_optimized_v3_walkforward.py
git commit -m "feat: add strict three-route walk-forward selection"
```

---

### Task 7: Full experiment CLI and durable artifacts

**Files:**
- Create: `tools/run_fixed11_gradual_next_stage.py`
- Create: `tests/test_fixed11_gradual_next_stage_cli.py`
- Output: `reports/small_cap_fixed11_gradual_next_stage/`

**Interfaces:**
- CLI arguments: `--db`, `--start`, `--end`, `--initial-cash`, `--stage`, `--resume`, and `--output`.
- `--stage` accepts `core`, `routes`, `walkforward`, `stress`, or `all`.
- Produces CSV/JSON artifacts plus per-candidate equity, trades, rejections, positions, exposure budgets, and target hashes.

- [ ] **Step 1: Write failing dry-run and resume tests**

```python
def test_cli_dry_run_lists_approved_counts(tmp_path):
    manifest = build_run_manifest(output=tmp_path, execute=False)
    assert manifest["core_one_factor_count"] == 20
    assert manifest["core_orthogonal_max_count"] == 18
    assert manifest["recovery_count"] == 6
    assert manifest["stock_profile_count"] == 3
    assert manifest["crash_overlay_count"] == 6
    assert manifest["profit_protection_count"] == 4


def test_resume_skips_only_hash_matching_completed_run(tmp_path):
    first = fake_completed_result(tmp_path, candidate_hash="abc", passed=True)
    assert should_resume(first, candidate_hash="abc")
    assert not should_resume(first, candidate_hash="changed")
```

- [ ] **Step 2: Confirm the CLI module is missing**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_fixed11_gradual_next_stage_cli.py -q`

Expected: FAIL during import.

- [ ] **Step 3: Implement deterministic stage orchestration**

Write UTF-8 CSVs with stable column order. Before every run, compute a SHA-256 hash over route, parameters, source target hash, date range, initial cash, cost model, and code schema version. `--resume` may skip only when the stored hash matches and the prior audit passed.

Required root artifacts:

```text
run_manifest.json
candidate_catalog.csv
core_scores.csv
route_scores.csv
walkforward_training.csv
walkforward_test.csv
route_gate_results.csv
annual_returns.csv
stress_results.csv
target_manifest.csv
rejected_candidates.csv
```

- [ ] **Step 4: Run the dry-run tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_fixed11_gradual_next_stage_cli.py -q`

Expected: PASS.

- [ ] **Step 5: Run the core stage and audit the anchor**

Run:

```powershell
.\.venv\Scripts\python.exe tools\run_fixed11_gradual_next_stage.py --stage core --start 2020-01-01 --end 2026-07-06 --initial-cash 1000000
```

Expected: `run_manifest.json` records anchor max absolute equity difference `<1e-6`, all reconciliation checks pass, and at most 38 core experiments are executed.

- [ ] **Step 6: Run route and walk-forward stages**

Run:

```powershell
.\.venv\Scripts\python.exe tools\run_fixed11_gradual_next_stage.py --stage routes --resume
.\.venv\Scripts\python.exe tools\run_fixed11_gradual_next_stage.py --stage walkforward --resume
.\.venv\Scripts\python.exe tools\run_fixed11_gradual_next_stage.py --stage stress --resume
```

Expected: no more than 70 full-sample candidates and 45 test-window runs; every selected test row references a training-only selection record.

- [ ] **Step 7: Commit orchestration code, not generated bulk results**

```powershell
git add tools/run_fixed11_gradual_next_stage.py tests/test_fixed11_gradual_next_stage_cli.py
git commit -m "feat: orchestrate fixed11 gradual next-stage research"
```

---

### Task 8: Final report, encoding guard, and complete verification

**Files:**
- Create: `tools/build_fixed11_gradual_next_stage_report.py`
- Create: `tools/verify_fixed11_gradual_next_stage.py`
- Create: `tests/test_fixed11_gradual_next_stage_report.py`
- Output: `reports/small_cap_fixed11_gradual_next_stage/artifact.json`
- Output: `reports/small_cap_fixed11_gradual_next_stage/report.html`
- Output: `reports/small_cap_fixed11_gradual_next_stage/verification.json`

**Interfaces:**
- Report contains the anchor, all candidate families, rejected variants, neighbor sensitivity, fold selections, fold test results, cost pressure, stress windows, and one decision per route.
- Verification fails on missing Chinese headings, replacement characters, known mojibake markers, reconciliation errors, leakage, negative cash, or baseline drift.

- [ ] **Step 1: Write failing report-contract tests**

```python
def test_report_contains_three_routes_and_no_forced_winner():
    artifact = build_artifact(sample_results())
    body = "\n".join(block.get("body", "") for block in artifact["manifest"]["blocks"])
    assert "均衡型" in body
    assert "收益型" in body
    assert "防守型" in body
    assert "无合格候选" in body


def test_report_text_is_utf8_without_known_mojibake():
    artifact = build_artifact(sample_results())
    text = json.dumps(artifact, ensure_ascii=False)
    assert "fixed11_gradual 下一阶段优化" in text
    for bad in ("\ufffd", "绛栫暐", "锛", "鈥", "鍥炴挙"):
        assert bad not in text
```

- [ ] **Step 2: Run tests and confirm missing builder**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_fixed11_gradual_next_stage_report.py -q`

Expected: FAIL during import.

- [ ] **Step 3: Build the canonical analytical artifact**

Create native charts for:

1. all-candidate return versus drawdown frontier;
2. neighbor sensitivity for the six core parameters;
3. fold-by-fold excess return and drawdown;
4. selected-candidate monthly wealth curves;
5. cost and stress-window degradation.

Create tables for full route gates, fold selection frequency, rejected candidates with reasons, and exact final parameters. Use one `artifact.json` as the source of truth and do not hand-author a parallel HTML renderer.

- [ ] **Step 4: Package the portable report**

Run from the Data Analytics plugin root:

```powershell
npm run report:deliver -- --input "C:\Users\16052\Documents\量化研究\reports\small_cap_fixed11_gradual_next_stage\artifact.json" --output "C:\Users\16052\Documents\量化研究\reports\small_cap_fixed11_gradual_next_stage\report.html"
```

Expected: validation and package stages pass. If no compatible headless Chromium is available, structural verification must pass and the limitation must be recorded.

- [ ] **Step 5: Implement and run final verification**

The verifier must assert:

```python
assert manifest["passed"]
assert manifest["anchor_max_abs_equity_diff"] < 1e-6
assert manifest["max_account_reconciliation_error"] < 1e-6
assert manifest["minimum_cash"] >= 0
assert manifest["test_selection_leakage_count"] == 0
assert "charset=utf-8" in html.lower() or 'charset="utf-8"' in html.lower()
assert "\ufffd" not in html
```

Run: `.\.venv\Scripts\python.exe tools\verify_fixed11_gradual_next_stage.py`

Expected: writes `verification.json` with `"passed": true`.

- [ ] **Step 6: Run focused and full project tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m py_compile src\quant_lab\research\optimized_v3_design.py src\quant_lab\research\optimized_v3_overlays.py src\quant_lab\research\optimized_v3_runner.py src\quant_lab\research\optimized_v3_walkforward.py tools\run_fixed11_gradual_next_stage.py tools\build_fixed11_gradual_next_stage_report.py tools\verify_fixed11_gradual_next_stage.py
.\.venv\Scripts\python.exe -m pytest -q
git diff --check -- src tests tools docs
```

Expected: compilation succeeds, pytest reaches 100% with zero failures, and `git diff --check` prints no errors.

- [ ] **Step 7: Commit report and verification code**

```powershell
git add tools/build_fixed11_gradual_next_stage_report.py tools/verify_fixed11_gradual_next_stage.py tests/test_fixed11_gradual_next_stage_report.py
git commit -m "feat: report fixed11 gradual walk-forward optimization"
```

---

## Completion Gate

The work is complete only when:

- the anchor reproduces `fixed11_gradual` within `1e-6`;
- every test-window candidate was selected using its own preceding training window only;
- all accounts reconcile and cash stays non-negative;
- each route either names one candidate that passes every gate or explicitly reports no qualified candidate;
- cost and stress results are present;
- the UTF-8 report packages successfully; and
- the full project test suite passes with zero failures.
