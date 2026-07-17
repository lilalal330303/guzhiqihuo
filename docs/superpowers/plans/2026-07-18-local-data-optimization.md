# fixed11_gradual Local Data Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (recommended) or superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local-only data optimization grid around `fixed11_gradual`, validate candidates on the agreed daily window, publish a Chinese report, and export only locally qualified candidates to THS/JQ scripts.

**Architecture:** Reuse `DuckDBRepository`, `run_small_cap_experiment`, `fixed11_gradual` targets and the existing portfolio backtest. Add a focused research runner that materializes data-quality variants before target construction, then writes immutable CSV/JSON evidence and a report artifact. Script export consumes one qualified candidate manifest and never changes the local backtest logic.

**Tech Stack:** Python 3.11, pandas, DuckDB, pytest, existing portfolio backtest, portable HTML report builder.

## Global Constraints

- Use 2020-01-01—2026-07-06, initial cash 1,000,000, daily bars and T+1 execution.
- Keep `fixed11_gradual` as the anchor and do not make cross-platform return equality an acceptance gate.
- Signals may use only query-date-visible rows; no future announcement or price data.
- Store normalized evidence under `reports/local_data_optimization_grid` and preserve source/data snapshot hashes.
- A platform script is emitted only for a candidate that passes all local gates.

---

### Task 1: Add failing tests for data-quality variants and manifest contracts

**Files:**
- Create: `tests/test_local_data_optimization.py`
- Modify: `src/quant_lab/research/__init__.py` only if needed for import exposure

**Interfaces:**
- Consumes: planned `DataVariant`, `DataGridConfig`, `run_data_optimization_grid` interfaces from Task 2.
- Produces: regression tests for PIT visibility, stable sorting, deterministic hashes, and local gate decisions.

- [ ] **Step 1: Write failing tests**

```python
def test_pit_variant_never_uses_future_announcement():
    result = apply_data_variant(snapshot, DataVariant(pit_mode="announcement_visible"))
    assert (result["announcement_date"] <= result["query_date"]).all()

def test_stable_sort_uses_symbol_as_tiebreak():
    ranked = rank_data_candidates(frame_with_equal_market_cap)
    assert ranked["symbol"].tolist() == sorted(ranked["symbol"].tolist())

def test_grid_manifest_has_data_and_target_hashes(tmp_path):
    manifest = run_data_optimization_grid(inputs, output=tmp_path, execute=False)
    assert manifest["data_snapshot_sha256"]
    assert manifest["candidate_count"] > 0

def test_candidate_gate_rejects_drawdown_regression():
    assert not qualifies_local_candidate(candidate_metrics, anchor_metrics)
```

- [ ] **Step 2: Run the focused tests and verify the expected failure**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_local_data_optimization.py -q`

Expected: FAIL because the new data variant and grid interfaces do not yet exist.

### Task 2: Implement deterministic data variants and local grid runner

**Files:**
- Create: `src/quant_lab/research/local_data_optimization.py`
- Create: `tools/run_local_data_optimization_grid.py`
- Test: `tests/test_local_data_optimization.py`

**Interfaces:**
- `DataVariant(pit_mode, listing_days_min, exclude_paused, prefilter_limits, price_max, market_cap_max, quality_weight, completeness_threshold, outlier_mode, replacement_quality_threshold, replacement_limit)`.
- `apply_data_variant(snapshot, variant) -> (filtered, audit)`.
- `rank_data_candidates(frame, variant) -> DataFrame`.
- `qualifies_local_candidate(candidate, anchor) -> bool`.
- `run_data_optimization_grid(inputs, output, execute=True) -> dict`.

- [ ] **Step 1: Implement PIT filtering and time-safe joins**

Use `query_date` and `announcement_date` explicitly. For `announcement_visible`, reject rows where `announcement_date > query_date`; for `announcement_plus_one`, shift the allowed query date by one trading day. Keep the original row’s `as_of_date` in the audit output.

- [ ] **Step 2: Implement master/status/price filters**

Join `security_master`, `trade_status_daily`, `valuations_daily` and the existing snapshot on `symbol` and query date. Apply the variant thresholds without mutating raw columns. Emit one rejection row per `(signal_date, symbol, rule)`.

- [ ] **Step 3: Implement stable ranking and replacement**

Sort by the requested score descending, then `market_cap_100m` ascending, then `symbol` ascending. Replacement candidates must come from the same signal date and variant snapshot; never carry a candidate across dates.

- [ ] **Step 4: Implement the grid runner**

Run the anchor first, then A—F single-factor grids, then at most 36 low-dimensional combinations. For every candidate write parameters, data hash, target hash, equity, trades, rejections, daily audit, and metrics.

- [ ] **Step 5: Run tests and verify they pass**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_local_data_optimization.py -q`

Expected: all focused tests pass.

### Task 3: Execute local backtests and apply acceptance gates

**Files:**
- Modify: `tools/run_local_data_optimization_grid.py`
- Create: `reports/local_data_optimization_grid/`
- Test: `tests/test_local_data_optimization.py`

**Interfaces:**
- Consumes: `ExperimentInputs`, `run_small_cap_experiment`, `CostModel`, and Task 2 grid outputs.
- Produces: `scores.csv`, `parameter_grid.csv`, `data_quality.csv`, `walkforward.csv`, `stress_results.csv`, `candidate_catalog.csv`, and `run_manifest.json`.

- [ ] **Step 1: Run the anchor reproduction**

Run: `\.venv\Scripts\python.exe tools/run_local_data_optimization_grid.py --start 2020-01-01 --end 2026-07-06 --initial-cash 1000000 --output reports/local_data_optimization_grid`

Expected: anchor target hash and equity curve match the existing reference within `1e-6`.

- [ ] **Step 2: Run all single-factor and low-dimensional grids**

Record every candidate even when rejected by the gate. Do not select by total return alone.

- [ ] **Step 3: Run annual and cost-pressure validation**

Use the existing five annual folds and 1.5x cost model. Require total return >= 95% of anchor, Calmar >= 105% of anchor, maximum drawdown no worse by more than 2 percentage points, at least 3/5 annual folds not worse, reconciliation < `1e-6`, and minimum cash >= 0.

- [ ] **Step 4: Verify results and hashes**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_local_data_optimization.py tests/test_backtest_engine.py -q`

Expected: all tests pass; manifest reports unchanged database hash and zero leakage rows.

### Task 4: Build Chinese report and export qualified scripts

**Files:**
- Create: `tools/build_local_data_optimization_report.py`
- Modify: `tools/build_outlog1_dual_scripts.py` only to accept a candidate manifest, if required
- Create: `reports/local_data_optimization_grid/report.html`
- Create: `reports/local_data_optimization_grid/qualified_ths.py`
- Create: `reports/local_data_optimization_grid/qualified_joinquant.py`

**Interfaces:**
- Consumes: Task 3 CSV/JSON evidence and the qualified candidate manifest.
- Produces: Chinese report with executive summary, data-quality findings, grid matrix, performance comparison, annual/cost validation, limitations, and next research paths. Script headers must contain `# VERSION:`, parameter JSON, target hash and data snapshot hash.

- [ ] **Step 1: Build UTF-8 Chinese artifact**

Use the portable report contract with canonical source metadata for every table and chart. Keep report text in UTF-8 and verify no replacement characters.

- [ ] **Step 2: Export scripts only when a candidate is qualified**

If no candidate passes, write a `NO_QUALIFIED_CANDIDATE` manifest and do not produce platform scripts. If one passes, export both scripts with the same candidate version and explicit data limitations.

- [ ] **Step 3: Deliver and validate the report**

Run the portable delivery tool against `artifact.json`; accept `validation=passed` and `package=passed`. If Chromium is unavailable, record `structural_only` without claiming visual QA.

### Task 5: Final verification and handoff

**Files:**
- Modify: `reports/local_data_optimization_grid/run_manifest.json`
- Test: `tests/test_local_data_optimization.py`, `tests/test_ths_near_n1_q20.py`, `tests/test_joinquant_outlog1_script.py`

- [ ] **Step 1: Run the complete focused test set**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_local_data_optimization.py tests/test_ths_near_n1_q20.py tests/test_joinquant_outlog1_script.py -q`

- [ ] **Step 2: Compile all generated scripts and report builders**

Run: `\.venv\Scripts\python.exe -m py_compile src/quant_lab/research/local_data_optimization.py tools/run_local_data_optimization_grid.py tools/build_local_data_optimization_report.py reports/local_data_optimization_grid/qualified_ths.py reports/local_data_optimization_grid/qualified_joinquant.py`

- [ ] **Step 3: Check final artifact integrity**

Confirm UTF-8 report/artifact, no `U+FFFD`, all CSVs readable, candidate hashes resolve, and any platform script points to the qualified candidate.

- [ ] **Step 4: Report unresolved gaps**

State whether any candidate passed, which data-quality dimensions improved, what remains missing, and which next grid is justified by evidence.
