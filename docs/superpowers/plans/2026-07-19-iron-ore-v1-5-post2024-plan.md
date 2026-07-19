# 铁矿石 CTA V1.5 2024 年后自适应多空版实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 2024 年后切换到更快、支持做空、带趋势效率和波动率状态控制的铁矿石 CTA，并交付可直接粘贴到聚宽的单文件脚本。

**Architecture:** 新建独立的 V1.5 脚本，保留 V1.4 的点时行情、实际持仓识别、ATR 止损、冷却和先平后开换月；通过 `select_regime_parameters` 按历史 signal_date 选择 2024 年前旧参数或 2024 年后 10/40/5 参数。2024 年后先由趋势信号决定多空，再用效率比决定是否交易、波动率比决定是否半仓；V1.4 不修改。

**Tech Stack:** Python 3、pandas、pytest、JoinQuant futures API。

## Global Constraints

- 只新增 V1.5 文件，不修改 V1.4/V1.3/V1.2/V1.1。
- `POST_2024_START` 必须为 `2024-01-01`，阶段选择只使用 `signal_date`。
- 2024 年前使用 V1.4 20/60/10 结构；2024 年后使用 10/40/5、2 日确认、趋势效率比阈值 0.25。
- `ALLOW_SHORT=True`，但只在 2024 年后且明确下行信号时做空；震荡期方向信号必须归零。
- 基础风险预算为目标年化波动率 0.30、最大保证金占用 0.60、最大杠杆 3.5。
- 2024 年后短/长波动率比值大于 1.8 时风险乘数为 0.5，否则为 1.0；回撤乘数为 `<10%:1.0`、`10%-<15%:0.9`、`15%-<20%:0.75`、`20%-<25%:0.5`、`>=25%:0`。
- 所有行情使用 `end_date=signal_date`，期货元数据使用带 `date=signal_date` 的调用。
- 不使用 `from reports`、`from __future__`、`get_bars`；合约限制为 `I####.XDCE`。

---

### Task 1: 写 V1.5 行为测试并验证 RED

**Files:**
- Create: `tests/test_iron_ore_cta_v1_5_post2024.py`
- Target: `reports/jq_iron_ore_cta_v1_5_post2024.py`

**Interfaces:**
- Consumes: `select_regime_parameters`、`classify_v1_signal`、`calculate_efficiency_ratio`、`calculate_volatility_ratio`、`calculate_adaptive_signal`、`calculate_drawdown_multiplier`、`calculate_regime_risk_multiplier`、`calculate_risk_scaled_amount`、`select_near_contract`、`can_open_replacement`。
- Produces: 对 2024 年后多空、震荡过滤、波动减仓和旧版兼容的可执行约束。

- [ ] **Step 1: Write the failing test**

```python
import pandas as pd

from reports.jq_iron_ore_cta_v1_5_post2024 import (
    POST_2024_START,
    PRE_PARAMS,
    POST_PARAMS,
    calculate_adaptive_signal,
    calculate_atr,
    calculate_drawdown_multiplier,
    calculate_efficiency_ratio,
    calculate_realized_volatility,
    calculate_regime_risk_multiplier,
    calculate_risk_scaled_amount,
    calculate_volatility_ratio,
    can_open_replacement,
    classify_v1_signal,
    select_near_contract,
    select_regime_parameters,
)


def test_regime_parameters_switch_at_2024_start():
    assert select_regime_parameters("2023-12-29") == PRE_PARAMS
    assert select_regime_parameters(POST_2024_START) == POST_PARAMS
    assert POST_PARAMS["allow_short"] is True


def test_efficiency_ratio_separates_directional_and_choppy_prices():
    directional = list(range(100, 131))
    choppy = [100, 102, 99, 101, 98, 100, 97, 99, 96, 98, 95, 97]
    assert calculate_efficiency_ratio(directional, 10) > 0.95
    assert calculate_efficiency_ratio(choppy, 10) < 0.25


def test_post2024_adaptive_signal_allows_downtrend_short():
    falling = list(range(160, 90, -1))
    assert calculate_adaptive_signal(falling, POST_PARAMS) == -1


def test_post2024_choppy_regime_is_flat_and_high_vol_is_half_risk():
    assert calculate_regime_risk_multiplier(0.20, 1.0, POST_PARAMS) == 0.0
    assert calculate_regime_risk_multiplier(0.35, 2.0, POST_PARAMS) == 0.5
    assert calculate_regime_risk_multiplier(0.35, 1.2, POST_PARAMS) == 1.0


def test_c_tier_amount_and_rollover_helpers_remain_safe():
    amount = calculate_risk_scaled_amount(
        1_000_000, 1_000_000, 500, 0.20, 0.5, POST_PARAMS
    )
    assert amount == 15
    assert calculate_drawdown_multiplier(750_000, 1_000_000) == 0.0
    closes = [100, 102, 101, 105, 103, 108]
    bars = pd.DataFrame({"high": [101, 103, 102, 106, 104, 109], "low": [99, 100, 100, 102, 101, 104], "close": closes})
    assert calculate_realized_volatility(closes) > 0
    assert calculate_atr(bars, 3) > 0
    assert calculate_volatility_ratio(closes * 12, 5, 20) > 0
    futures = pd.DataFrame({"end_date": pd.to_datetime(["2026-08-05", "2026-08-20", "2026-08-30"])}, index=["I2608.XDCE", "I2609.XDCE", "IC2608.CCFX"])
    assert select_near_contract(futures, pd.Timestamp("2026-07-31").date(), 8) == "I2609.XDCE"
    assert can_open_replacement(3, 3, 0)
    assert not can_open_replacement(3, 3, 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest -q tests/test_iron_ore_cta_v1_5_post2024.py`

Expected: collection fails with `ModuleNotFoundError` because the V1.5 module does not exist.

### Task 2: Implement the standalone V1.5 strategy

**Files:**
- Create: `reports/jq_iron_ore_cta_v1_5_post2024.py`

**Interfaces:**
- Consumes: V1.4 execution shape and Task 1 function signatures.
- Produces: standalone JoinQuant script with pre-2024 legacy mode and post-2024 adaptive long/short mode.

- [ ] **Step 1: Implement pure signal/regime helpers**

Implement `PRE_PARAMS`, `POST_PARAMS`, `select_regime_parameters`, the V1 strict classifier, `calculate_efficiency_ratio`, `calculate_volatility_ratio`, `calculate_adaptive_signal`, `calculate_drawdown_multiplier`, `calculate_regime_risk_multiplier`, and volatility-based quantity sizing. Use `POST_PARAMS["allow_short"] = True`, `min_efficiency=0.25`, `max_vol_ratio=1.8`, and `risk_multiplier=0.5` for elevated volatility.

- [ ] **Step 2: Implement point-in-time snapshot and execution**

Use `signal_date` to choose parameters. Return `signal`, `efficiency_ratio`, `volatility_ratio`, `regime_multiplier`, ATR, realized volatility, fast/slow averages and slope. Map signal `-1` to a short target only when post-2024 parameters allow it. Keep close-first rollover, actual position checks, cooldown, and ATR exit.

- [ ] **Step 3: Run focused tests to verify GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest -q tests/test_iron_ore_cta_v1_5_post2024.py`

Expected: all V1.5 tests pass.

### Task 3: Add static audit and JoinQuant copy

**Files:**
- Create: `tools/verify_iron_ore_cta_v1_5_post2024.py`
- Create: `C:\Users\16052\Desktop\2025聚宽优秀策略\029_穿越牛熊2.0(非小市值)年化50%的cta策略\V1.5_铁矿石CTA_2024适配多空版.py`

- [ ] **Step 1: Implement static audit**

Require `POST_2024_START`, `ALLOW_SHORT=True`, 10/40/5 post parameters, efficiency threshold 0.25, volatility ratio threshold 1.8, point-in-time calls, contract regex, and no package/future imports or `get_bars`. Success output must be `iron ore CTA V1.5 static audit: 0 violations`.

- [ ] **Step 2: Copy only after verification**

Create the desktop file only when absent, then compare SHA256 with the workspace script. Do not overwrite an existing user file.

### Task 4: Full verification and commit

**Files:**
- Verify: V1.5 spec, plan, script, test, audit and desktop copy.

- [ ] **Step 1: Run focused tests, compile, static audit and runtime smoke**

Runtime smoke must verify post-2024 short entry, choppy regime no-entry, high-volatility half-size, and close-first rollover.

- [ ] **Step 2: Run full project tests**

Run: `.\.venv\Scripts\python.exe -m pytest -q --disable-warnings`

Expected: exit code 0 and all tests pass.

- [ ] **Step 3: Review scoped diff and commit**

Run `git diff --check`, stage only the V1.5 spec, plan, script, test and audit, then commit with `feat: add iron ore CTA V1.5 post-2024 adaptive regime`.

## Self-review

- Spec coverage: 2024 switch, shorting, efficiency filter, volatility reduction, point-in-time data and safe rollover each have tests/tasks.
- Placeholder scan: no TBD/TODO or vague implementation step remains.
- Type consistency: all imported names in Task 1 are defined by Task 2 and used by the verifier/runtime smoke.
