# #39 大小盘反复横跳 V2.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 产出一份可直接复制到聚宽的 V2.1 独立脚本，在保留原始反转收益来源的同时加入风格滞回、趋势防守、历史成分池和低换手执行。

**Architecture:** 所有可在本地验证的风格打分、滞回、防守和候选缓冲逻辑写成聚宽脚本内的纯函数；聚宽 API 调用只负责取数、基本面筛选和下单。测试通过注入最小 `jqdata` 占位模块加载脚本，不连接聚宽、不依赖本地行情服务。

**Tech Stack:** Python 3.12 AST、pytest、NumPy、pandas、聚宽 Python3 API。

## Global Constraints

- 所有历史行情和基本面信号只能使用 `context.previous_date` 及之前的数据。
- `get_current_data` 仅用于当日成交可行性检查，不参与历史排序或风格信号计算。
- SMALL 使用历史国证2000 `399303.XSHE` 成分，BIG 使用历史中证500 `399905.XSHE` 成分。
- 风格信号默认是20日反转权重0.65、60日趋势权重0.35。
- 风格切换必须满足 `switch_gap` 和 `min_style_months` 两个条件。
- 默认5只持仓、月初09:35调仓、先卖后买、滑点默认0.001。
- 候选池为空、行情不足或订单不可执行时保持可执行的现有持仓。

---

### Task 1: Write failing tests for pure V2.1 behavior

**Files:**
- Create: `tests/test_joinquant_size_style_rotation_v21.py`
- Test target to be created: `reports/joinquant_size_style_rotation_v21.py`

**Interfaces:**
- Tests load the target script with a stub module named `jqdata`.
- The script must expose pure functions `compute_style_scores`, `select_style_with_hysteresis`, `market_risk_off`, and `merge_target_with_holdings`.

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path
import runpy
import sys
import types


def load_strategy():
    jqdata_stub = types.ModuleType("jqdata")
    sys.modules["jqdata"] = jqdata_stub
    return runpy.run_path(
        Path("reports/joinquant_size_style_rotation_v21.py"),
        run_name="joinquant_size_style_rotation_v21_test",
    )


def test_reversal_dominates_when_recent_style_leads():
    ns = load_strategy()
    scores = ns["compute_style_scores"](
        small_returns={20: 0.20, 60: 0.04},
        big_returns={20: 0.04, 60: 0.08},
        small_vol={20: 0.25, 60: 0.22},
        big_vol={20: 0.20, 60: 0.18},
    )
    assert scores["BIG"] > scores["SMALL"]


def test_hysteresis_keeps_current_style_for_small_edge():
    ns = load_strategy()
    assert ns["select_style_with_hysteresis"]("SMALL", {"SMALL": 0.12, "BIG": 0.16}, 0.10, 2, 2) == "SMALL"


def test_hysteresis_switches_after_gap_and_minimum_hold():
    ns = load_strategy()
    assert ns["select_style_with_hysteresis"]("SMALL", {"SMALL": 0.10, "BIG": 0.30}, 0.10, 2, 2) == "BIG"


def test_risk_off_requires_both_style_indices_below_trend():
    ns = load_strategy()
    assert ns["market_risk_off"](0.98, 1.00, 1.05, 1.04, -0.04) is False
    assert ns["market_risk_off"](0.98, 1.00, 0.97, 0.96, -0.04) is True


def test_holdings_in_buffer_are_kept_before_new_candidates():
    ns = load_strategy()
    result = ns["merge_target_with_holdings"](
        holdings=["A", "Z"],
        ranked_candidates=["B", "A", "C", "D", "E", "F"],
        target_count=3,
        buffer_count=5,
    )
    assert result == ["A", "B", "C"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_joinquant_size_style_rotation_v21.py -q`

Expected: FAIL because `reports/joinquant_size_style_rotation_v21.py` and its pure functions do not exist yet.

### Task 2: Implement pure style, risk and turnover logic

**Files:**
- Create: `reports/joinquant_size_style_rotation_v21.py`

**Interfaces:**
- `compute_style_scores(small_returns, big_returns, small_vol, big_vol) -> dict[str, float]`
- `select_style_with_hysteresis(current_style, scores, switch_gap, hold_months, min_style_months) -> str`
- `market_risk_off(market_close, market_ma60, small_ma60, big_ma60, market_return20) -> bool`
- `merge_target_with_holdings(holdings, ranked_candidates, target_count, buffer_count) -> list[str]`

- [ ] **Step 1: Implement the smallest passing pure functions**

```python
def _safe_ratio(value, volatility):
    if volatility is None or not np.isfinite(volatility) or volatility <= 1e-8:
        return 0.0
    return float(value) / float(volatility)


def compute_style_scores(small_returns, big_returns, small_vol, big_vol):
    small_score = -0.65 * _safe_ratio(small_returns.get(20, 0.0), small_vol.get(20, 0.0))
    small_score += 0.35 * _safe_ratio(small_returns.get(60, 0.0), small_vol.get(60, 0.0))
    big_score = -0.65 * _safe_ratio(big_returns.get(20, 0.0), big_vol.get(20, 0.0))
    big_score += 0.35 * _safe_ratio(big_returns.get(60, 0.0), big_vol.get(60, 0.0))
    return {"SMALL": small_score, "BIG": big_score}


def select_style_with_hysteresis(current_style, scores, switch_gap, hold_months, min_style_months):
    challenger = "BIG" if current_style == "SMALL" else "SMALL"
    if hold_months < min_style_months:
        return current_style
    if scores.get(challenger, -np.inf) - scores.get(current_style, -np.inf) > switch_gap:
        return challenger
    return current_style


def market_risk_off(market_close, market_ma60, small_ma60, big_ma60, market_return20):
    return bool(
        market_close < market_ma60
        and small_ma60 < 1.0
        and big_ma60 < 1.0
        and market_return20 < 0.0
    )


def merge_target_with_holdings(holdings, ranked_candidates, target_count, buffer_count):
    buffer_set = set(ranked_candidates[:buffer_count])
    kept = [stock for stock in holdings if stock in buffer_set]
    filled = [stock for stock in ranked_candidates if stock not in kept]
    return (kept + filled)[:target_count]
```

- [ ] **Step 2: Run the focused tests**

Run: `pytest tests/test_joinquant_size_style_rotation_v21.py -q`

Expected: PASS for the five pure-function tests.

### Task 3: Add JoinQuant data, candidate and execution layers

**Files:**
- Modify: `reports/joinquant_size_style_rotation_v21.py`

**Interfaces:**
- Runtime entry points: `initialize`, `monthly_adjustment`, `prepare_stock_list`, `check_limit_up`.
- Data helpers: `get_index_close`, `style_signal`, `determine_market_style`, `get_candidates`.
- Candidate helpers: `small_candidates`, `big_candidates`, `base_style_pool`, `is_tradeable`.
- Order helper: `safe_order_target_value`.

- [ ] **Step 1: Add initialization and parameters**

Use the following parameter contract inside `initialize`:

```python
g.params = {
    "stock_num": 5,
    "candidate_buffer": 2,
    "style_windows": (20, 60),
    "style_lookback_vol": 20,
    "switch_gap": 0.10,
    "min_style_months": 2,
    "min_listing_days": 375,
    "recent_limit_days": 40,
    "max_price": 0.0,
    "risk_off_enabled": True,
    "slippage": 0.001,
}
```

Schedule `prepare_stock_list` at 09:05, `monthly_adjustment` on the first trading day at 09:35, and `check_limit_up` at 14:00. Use `set_option("avoid_future_data", True)` and `get_fundamentals(..., date=context.previous_date)`.

- [ ] **Step 2: Add direct-index style signal and stateful hysteresis**

For each of `399303.XSHE` and `399905.XSHE`, fetch daily close history ending at `context.previous_date` for at least 61 rows, compute 20/60-day returns and 20-day daily-return volatility, pass them to `compute_style_scores`, and update `g.current_style` only through `select_style_with_hysteresis`. Store `g.style_months` and reset it only when a style actually changes.

- [ ] **Step 3: Add market risk-off and historical candidate pools**

Use `000985.XSHG` close history ending at `context.previous_date` to compute the 60-day moving average and 20-day return. Treat both style moving-average ratios as `close / MA60`. If `risk_off_enabled` and `market_risk_off(...)` returns true, return an empty target and let the execution layer close positions that are not protected by the existing yesterday-limit-up rule.

Use `get_index_stocks("399303.XSHE", date=cutoff)` for SMALL and `get_index_stocks("399905.XSHE", date=cutoff)` for BIG. Apply the existing listing, ST, paused, price and limit checks. Query fundamentals only with `date=cutoff`; rank SMALL by ascending market cap and BIG by descending market cap after the existing quality/value filters.

- [ ] **Step 4: Add turnover buffer and safe orders**

Fetch `stock_num * candidate_buffer` ranked candidates, retain current holdings that are still in that buffer, and fill remaining slots from the ranked list. Sell non-target holdings first, excluding yesterday-limit-up holdings; buy missing targets with equal available cash allocation. Skip invalid or limit-locked orders and log the reason.

- [ ] **Step 5: Run tests and AST/static checks**

Run: `pytest tests/test_joinquant_size_style_rotation_v21.py -q`

Run: `python -c "import ast, pathlib; ast.parse(pathlib.Path('reports/joinquant_size_style_rotation_v21.py').read_text(encoding='utf-8')); print('AST OK')"`

Run: `rg -n "get_fundamentals\([^\n]*date=None|get_index_stocks\([^\n]*\)|history\([^\n]*current_dt|current_price\([^\n]*\).*order_by" reports/joinquant_size_style_rotation_v21.py`

Expected: focused tests pass, AST prints `AST OK`, and the static scan prints no prohibited calls.

### Task 4: Prepare delivery note and verification matrix

**Files:**
- Create: `reports/joinquant_size_style_rotation_v21_readme.md`

**Interfaces:**
- Documents the script path, default parameters, known behavioral differences from original/V1, and the exact JoinQuant comparison matrix.

- [ ] **Step 1: Write the delivery note**

Include the following comparison rows: original, V1, V2.1; slippage values 0/0.001/0.002; style mode default reversal-hybrid; risk-off on/off; periods 2020-01-01 to 2026-07-18, 2020-2021, 2022-2023, 2024-2026.

- [ ] **Step 2: Run final verification**

Run: `pytest tests/test_joinquant_size_style_rotation_v21.py -q`

Run: `python -m compileall -q reports/joinquant_size_style_rotation_v21.py`

Run: `git diff --check -- reports/joinquant_size_style_rotation_v21.py reports/joinquant_size_style_rotation_v21_readme.md tests/test_joinquant_size_style_rotation_v21.py`

Expected: exit code 0 for all commands, with the focused test count shown as passing and no whitespace errors.

- [ ] **Step 3: Commit implementation files**

```bash
git add reports/joinquant_size_style_rotation_v21.py reports/joinquant_size_style_rotation_v21_readme.md tests/test_joinquant_size_style_rotation_v21.py
git commit -m "feat: add size style rotation v2.1 joinquant script"
```
