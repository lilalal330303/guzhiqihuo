# Size Style Rotation V2.2 Original-Compatible Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an independent JoinQuant Python3 script that preserves the original size-rotation behavior while fixing historical-date safety, data-shape failures, and order handling.

**Architecture:** Keep the original strategy file untouched. Put pure signal/data-normalization functions at the top of a standalone JoinQuant script, keep candidate selection and order routines close to the original, and expose optional guards as disabled-by-default parameters. Test pure functions locally with a stubbed `jqdata` module and use AST checks for historical-date calls.

**Tech Stack:** JoinQuant Python3 API (`jqdata`), Python standard library, NumPy, pandas, pytest, Python AST.

## Global Constraints

- Preserve original behavior: 20-day cross-sectional constituent returns, `mean_2000 / mean_500 > 1.2`, original branch direction, monthly first-trading-day rebalance at 09:30, five holdings, max price 10, and zero default slippage.
- Do not overwrite `C:\Users\16052\Desktop\2025聚宽优秀策略\039_干积分-大小盘反复横跳V2.0\39干积分-大小盘反复横跳V2.0.txt`.
- All `get_index_stocks` and `get_fundamentals` calls must use an explicit historical `date`.
- Default `winsorize_returns=False`, `market_guard=False`, `slippage=0.0`, and `use_historical_constituents=True`.
- Signals use `context.previous_date`; no current-day close or post-close data may enter the signal.
- Signals generated at rebalance time are executed through `order_target_value` on the same JoinQuant scheduled event, matching the original monthly workflow.
- Run focused tests before the full test suite; do not claim a JoinQuant cloud backtest was run locally.

---

### Task 1: Add failing tests for the original-compatible pure functions

**Files:**
- Create: `tests/test_joinquant_size_style_rotation_v22_original_compatible.py`

**Interfaces:**
- The tests will require `select_original_branch(mean_2000, mean_500, ratio_threshold)`.
- The tests will require `safe_mean_return(close_frame, min_samples, winsorize)`.
- The tests will require `merge_target_with_holdings(holdings, ranked_candidates, target_count)`.

- [ ] **Step 1: Write the failing tests**

```python
def test_original_ratio_preserves_branch_direction():
    ns = load_strategy()
    assert ns["select_original_branch"](0.30, 0.20, 1.2) == "BIG"
    assert ns["select_original_branch"](0.24, 0.20, 1.2) == "SMALL"


def test_original_ratio_rejects_invalid_denominator():
    ns = load_strategy()
    assert ns["select_original_branch"](0.30, 0.0, 1.2) is None


def test_cross_sectional_mean_return_ignores_missing_values():
    ns = load_strategy()
    frame = pd.DataFrame(
        [[100.0, 100.0], [110.0, np.nan]],
        columns=["A", "B"],
    )
    result = ns["safe_mean_return"](frame, min_samples=2, winsorize=False)
    assert result == pytest.approx(0.10)


def test_cross_sectional_mean_return_returns_none_when_sample_is_too_small():
    ns = load_strategy()
    frame = pd.DataFrame([[100.0, np.nan], [110.0, np.nan]], columns=["A", "B"])
    assert ns["safe_mean_return"](frame, min_samples=2, winsorize=False) is None


def test_existing_holdings_are_kept_in_ranked_target():
    ns = load_strategy()
    assert ns["merge_target_with_holdings"](
        ["A"], ["B", "A", "C"], 2
    ) == ["A", "B"]
```

The test loader must inject an empty `jqdata` module before `runpy.run_path`, and provide `pandas`, `numpy`, and `pytest` imports in the test module.

- [ ] **Step 2: Run the focused tests to verify the expected failure**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q tests/test_joinquant_size_style_rotation_v22_original_compatible.py
```

Expected: FAIL because the new V2.2 script and required pure functions do not yet exist.

- [ ] **Step 3: Commit the red tests**

```powershell
git add -- tests/test_joinquant_size_style_rotation_v22_original_compatible.py
git commit -m "test: define original-compatible size rotation behavior"
```

### Task 2: Implement the original-compatible signal and data normalization

**Files:**
- Create: `reports/joinquant_size_style_rotation_v22_original_compatible.py`
- Modify: `tests/test_joinquant_size_style_rotation_v22_original_compatible.py`

**Interfaces:**
- Produces `select_original_branch`, `safe_mean_return`, and `merge_target_with_holdings` for Task 1.
- Produces `safe_close_frame(raw_prices)` and `get_style_mean_return(context, index_code)` for the runtime path.

- [ ] **Step 1: Add minimal pure-function implementation**

```python
def select_original_branch(mean_2000, mean_500, ratio_threshold):
    if mean_2000 is None or mean_500 is None:
        return None
    try:
        numerator = float(mean_2000)
        denominator = float(mean_500)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(numerator) or not np.isfinite(denominator):
        return None
    if abs(denominator) <= 1e-8:
        return None
    return "BIG" if numerator / denominator > ratio_threshold else "SMALL"


def safe_mean_return(close_frame, min_samples=2, winsorize=False):
    if close_frame is None or getattr(close_frame, "empty", True):
        return None
    frame = close_frame.apply(pd.to_numeric, errors="coerce")
    first = frame.iloc[0].replace(0, np.nan)
    last = frame.iloc[-1]
    returns = ((last - first) / first).replace([np.inf, -np.inf], np.nan).dropna()
    if len(returns) < min_samples:
        return None
    if winsorize and len(returns) >= 5:
        returns = returns.clip(returns.quantile(0.05), returns.quantile(0.95))
    value = float(returns.mean())
    return value if np.isfinite(value) else None


def merge_target_with_holdings(holdings, ranked_candidates, target_count):
    ranked = list(dict.fromkeys(ranked_candidates))
    kept = []
    for stock in holdings:
        if stock in ranked and stock not in kept:
            kept.append(stock)
    filled = [stock for stock in ranked if stock not in kept]
    return (kept + filled)[:target_count]
```

- [ ] **Step 2: Run the focused tests to verify green**

Run the same focused pytest command from Task 1. Expected: PASS for all pure-function tests.

- [ ] **Step 3: Add data-shape tests before implementing runtime normalization**

```python
def test_safe_close_frame_pivots_panel_false_multi_stock_frame():
    ns = load_strategy()
    raw = pd.DataFrame({
        "code": ["A", "B", "A", "B"],
        "close": [100.0, 200.0, 110.0, 220.0],
    }, index=pd.to_datetime(["2024-01-01", "2024-01-01", "2024-01-02", "2024-01-02"]))
    result = ns["safe_close_frame"](raw)
    assert list(result.columns) == ["A", "B"]
    assert result.iloc[-1].to_dict() == {"A": 110.0, "B": 220.0}
```

- [ ] **Step 4: Implement `safe_close_frame` and `get_style_mean_return`**

`safe_close_frame` must accept a pandas DataFrame with `close` and optional `code`, a Panel-like object exposing `raw_prices["close"]`, or a DataFrame already containing one close column. It must return a date-indexed DataFrame with security codes as columns or `None`.

`get_style_mean_return` must:

1. Set `cutoff = context.previous_date`.
2. Call `get_index_stocks(index_code, date=cutoff)` when `use_historical_constituents` is true.
3. Fetch exactly `style_window=20` daily closes ending at `cutoff`.
4. Normalize the response with `safe_close_frame`.
5. Return `safe_mean_return(...)`, or `None` when the pool or sample is unusable.

The first `get_price` attempt may use `panel=False`; if the runtime rejects that keyword, retry the same single request without `panel` and normalize both return shapes.

- [ ] **Step 5: Run focused tests and commit the signal layer**

```powershell
& .\.venv\Scripts\python.exe -m pytest -q tests/test_joinquant_size_style_rotation_v22_original_compatible.py
git add -- reports/joinquant_size_style_rotation_v22_original_compatible.py tests/test_joinquant_size_style_rotation_v22_original_compatible.py
git commit -m "feat: add original-compatible size rotation signal layer"
```

### Task 3: Implement original-compatible candidate selection and orders

**Files:**
- Modify: `reports/joinquant_size_style_rotation_v22_original_compatible.py`
- Modify: `tests/test_joinquant_size_style_rotation_v22_original_compatible.py`

**Interfaces:**
- Runtime entry points: `initialize`, `prepare_stock_list`, `monthly_adjustment`, and `check_limit_up`.
- Candidate functions: `small_candidates`, `big_candidates`, `get_candidates`.

- [ ] **Step 1: Add failing runtime-parameter tests**

```python
def test_default_parameters_are_original_compatible():
    ns = load_strategy()
    params = ns["DEFAULT_PARAMS"]
    assert params["stock_num"] == 5
    assert params["style_window"] == 20
    assert params["ratio_threshold"] == 1.2
    assert params["max_price"] == 10.0
    assert params["slippage"] == 0.0
    assert params["winsorize_returns"] is False
    assert params["market_guard"] is False
```

- [ ] **Step 2: Run the focused test to verify it fails**

Expected: FAIL because `DEFAULT_PARAMS` is not yet defined.

- [ ] **Step 3: Implement the runtime with exact B0 defaults**

The script must define:

```python
DEFAULT_PARAMS = {
    "stock_num": 5,
    "style_window": 20,
    "ratio_threshold": 1.2,
    "min_style_samples": 2,
    "max_price": 10.0,
    "min_listing_days": 375,
    "recent_limit_days": 40,
    "winsorize_returns": False,
    "market_guard": False,
    "market_guard_ma": 60,
    "slippage": 0.0,
    "use_historical_constituents": True,
    "big_use_filtered_pool": False,
}
```

`initialize` must set the `000985.XSHG` benchmark, real prices, future-data protection, original order cost, `FixedSlippage(0)` by default, and schedule `prepare_stock_list` at 09:05, `monthly_adjustment` on month day 1 at 09:30, and `check_limit_up` at 14:00.

`small_candidates` must preserve the original ROE/ROA, price, market-cap ordering and recent-limit-up hold protection. `big_candidates` must use `stocks` when `big_use_filtered_pool=False`, matching original B0 behavior; `big_use_filtered_pool=True` is reserved for the later experiment. Both branches must pass `date=context.previous_date` to fundamentals queries.

`monthly_adjustment` must call the original-compatible style signal, optionally apply `market_guard` only when enabled, keep protected holdings, sell non-target holdings, and divide available cash equally among missing targets.

- [ ] **Step 4: Add tests for default guard behavior and target construction**

```python
def test_market_guard_is_disabled_by_default():
    ns = load_strategy()
    assert ns["DEFAULT_PARAMS"]["market_guard"] is False


def test_merge_target_does_not_duplicate_existing_holdings():
    ns = load_strategy()
    assert ns["merge_target_with_holdings"](
        ["A", "A"], ["A", "B", "C"], 3
    ) == ["A", "B", "C"]
```

- [ ] **Step 5: Run all focused tests and commit the runtime**

```powershell
& .\.venv\Scripts\python.exe -m pytest -q tests/test_joinquant_size_style_rotation_v22_original_compatible.py
git add -- reports/joinquant_size_style_rotation_v22_original_compatible.py tests/test_joinquant_size_style_rotation_v22_original_compatible.py
git commit -m "feat: add original-compatible JoinQuant runtime"
```

### Task 4: Add static checks and user-facing comparison documentation

**Files:**
- Create: `reports/joinquant_size_style_rotation_v22_original_compatible_readme.md`
- Modify: `tests/test_joinquant_size_style_rotation_v22_original_compatible.py`

**Interfaces:**
- Documentation names the script, B0 defaults, B1-B4 experiment matrix, and data-safety behavior.
- Static checks inspect the final script AST.

- [ ] **Step 1: Add a static-check test**

```python
def test_strategy_calls_use_explicit_historical_dates():
    source = Path("reports/joinquant_size_style_rotation_v22_original_compatible.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {"get_fundamentals", "get_index_stocks"}
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in names]
    assert calls
    assert all(any(keyword.arg == "date" for keyword in call.keywords) for call in calls)
```

- [ ] **Step 2: Run the static test and verify it fails if any date keyword is missing**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q tests/test_joinquant_size_style_rotation_v22_original_compatible.py
```

Expected after implementation: PASS.

- [ ] **Step 3: Write the README**

The README must include:

- why V2.1 was rejected as the main path;
- original-compatible signal definition and the intentionally preserved branch naming;
- B0/B1/B2/B3/B4 matrix;
- comparisons for 2020-01-01 to 2026-07-18, 2020-2021, 2022-2023, and 2024-2026;
- required metrics: total return, annualized return, maximum drawdown, trade count, win rate, turnover, empty-target count, and slippage sensitivity;
- the fact that no JoinQuant cloud result is asserted by local tests.

- [ ] **Step 4: Run final verification**

```powershell
& .\.venv\Scripts\python.exe -m pytest -q
& .\.venv\Scripts\python.exe -m compileall -q reports/joinquant_size_style_rotation_v22_original_compatible.py
& .\.venv\Scripts\python.exe -c "import ast, pathlib; p=pathlib.Path('reports/joinquant_size_style_rotation_v22_original_compatible.py'); ast.parse(p.read_text(encoding='utf-8')); print('AST OK')"
git diff --check
```

Expected: the full test suite passes, compilation succeeds, `AST OK` is printed, and `git diff --check` has no errors.

- [ ] **Step 5: Commit the README and final tests**

```powershell
git add -- reports/joinquant_size_style_rotation_v22_original_compatible_readme.md tests/test_joinquant_size_style_rotation_v22_original_compatible.py
git commit -m "docs: add v2.2 original-compatible backtest matrix"
```
