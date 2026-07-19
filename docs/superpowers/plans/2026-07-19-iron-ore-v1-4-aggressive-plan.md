# 铁矿石 CTA V1.4 激进收益版实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 基于 V1.3 新建 V1.4 激进收益版，在 C 档风险预算下只对强趋势低失控波动提高暴露，并交付可直接粘贴到聚宽的单文件脚本。

**Architecture:** 新建独立的 V1.4 脚本，保留 V1.3 的严格信号、点时数据、实际持仓识别、ATR 止损、冷却和先平后开换月。新增纯函数 `calculate_trend_quality_multiplier`，把趋势质量乘数与回撤乘数分别计算，再在开仓数量上组合；V1.3 文件不修改，桌面目录输出 V1.4 副本。

**Tech Stack:** Python 3、pandas、pytest、JoinQuant futures API。

## Global Constraints

- V1.4 只能新增文件，不修改 V1.3/V1.2/V1.1。
- 默认参数必须是 `target_annual_vol=0.30`、`max_margin_usage=0.60`、`max_leverage=3.5`。
- 严格趋势信号必须保持 20/60/10 均线斜率、2 日确认、0.2% 价格缓冲、0.2% 均线间距、0.05% 最小斜率。
- 趋势质量乘数只能在四个强趋势低波动条件同时满足时为 1.25，否则为 1.00；不得用它过滤已有有效信号。
- 回撤乘数边界必须为 `<10%:1.00`、`10%-<15%:0.90`、`15%-<20%:0.75`、`20%-<25%:0.50`、`>=25%:0.00`。
- 回撤为 0 时停止新开仓，不因回撤单独强平已有仓位。
- 脚本不得包含实际的 `from reports` 或 `from __future__` 导入，不得使用 `get_bars`，市场数据必须截断到 `signal_date`。
- 默认 `ALLOW_SHORT=False`；近月合约必须匹配 `I####.XDCE`。

---

### Task 1: 建立 V1.4 行为测试并验证 RED

**Files:**
- Create: `tests/test_iron_ore_cta_v1_4_aggressive.py`
- Target: `reports/jq_iron_ore_cta_v1_4_aggressive.py`

**Interfaces:**
- Consumes: `classify_v1_signal`、`calculate_drawdown_multiplier`、`calculate_trend_quality_multiplier`、`calculate_risk_scaled_amount`、`calculate_realized_volatility`、`calculate_atr`、`select_near_contract`、`can_open_replacement`。
- Produces: V1.4 的严格信号、趋势加速、回撤边界、C 档仓位和换月保护测试。

- [ ] **Step 1: Write the failing test**

```python
import pandas as pd

from reports.jq_iron_ore_cta_v1_4_aggressive import (
    calculate_atr,
    calculate_drawdown_multiplier,
    calculate_realized_volatility,
    calculate_risk_scaled_amount,
    calculate_trend_quality_multiplier,
    can_open_replacement,
    classify_v1_signal,
    select_near_contract,
)


def test_v1_signal_remains_strict():
    rising = [100.0] * 80 + [101, 102, 103, 104, 105, 106, 107, 108, 109, 110]
    falling = list(range(140, 58, -1))
    assert classify_v1_signal(rising, confirmation_days=2) == 1
    assert classify_v1_signal(falling, confirmation_days=1) == -1


def test_trend_quality_boost_requires_all_strong_conditions():
    params = {"target_annual_vol": 0.30}
    strong = calculate_trend_quality_multiplier(110, 100, 98, 0.002, 0.20, params)
    weak = calculate_trend_quality_multiplier(103, 100, 98, 0.002, 0.20, params)
    high_vol = calculate_trend_quality_multiplier(110, 100, 98, 0.002, 0.40, params)
    assert strong == 1.25
    assert weak == 1.0
    assert high_vol == 1.0


def test_aggressive_drawdown_bands_are_piecewise():
    assert calculate_drawdown_multiplier(1_000_000, 1_000_000) == 1.0
    assert calculate_drawdown_multiplier(900_000, 1_000_000) == 0.90
    assert calculate_drawdown_multiplier(850_000, 1_000_000) == 0.75
    assert calculate_drawdown_multiplier(800_000, 1_000_000) == 0.50
    assert calculate_drawdown_multiplier(750_000, 1_000_000) == 0.0


def test_c_tier_risk_budget_scales_base_and_trend_boost():
    params = {
        "target_annual_vol": 0.30,
        "max_margin_usage": 0.60,
        "margin_rate": 0.15,
        "max_leverage": 3.5,
        "contract_multiplier": 100,
        "max_risk_multiplier": 1.25,
    }
    base = calculate_risk_scaled_amount(1_000_000, 1_000_000, 500, 0.20, 1.0, params)
    boosted = calculate_risk_scaled_amount(1_000_000, 1_000_000, 500, 0.20, 1.25, params)
    stopped = calculate_risk_scaled_amount(1_000_000, 1_000_000, 500, 0.20, 0.0, params)
    assert base == 30
    assert boosted == 37
    assert stopped == 0


def test_helpers_and_rollover_guard_remain_available():
    closes = [100, 102, 101, 105, 103, 108]
    bars = pd.DataFrame({"high": [101, 103, 102, 106, 104, 109], "low": [99, 100, 100, 102, 101, 104], "close": closes})
    assert calculate_realized_volatility(closes) > 0
    assert calculate_atr(bars, 3) > 0
    futures = pd.DataFrame({"end_date": pd.to_datetime(["2026-08-05", "2026-08-20", "2026-08-30"])}, index=["I2608.XDCE", "I2609.XDCE", "IC2608.CCFX"])
    assert select_near_contract(futures, pd.Timestamp("2026-07-31").date(), 8) == "I2609.XDCE"
    assert can_open_replacement(3, 3, 0)
    assert not can_open_replacement(3, 3, 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest -q tests/test_iron_ore_cta_v1_4_aggressive.py`

Expected: collection fails with `ModuleNotFoundError` because the V1.4 module does not exist.

### Task 2: Implement the standalone V1.4 script

**Files:**
- Create: `reports/jq_iron_ore_cta_v1_4_aggressive.py`

**Interfaces:**
- Consumes: the V1.3 standalone flow and Task 1 function signatures.
- Produces: JoinQuant single-file script with C-tier exposure and conditional trend boost.

- [ ] **Step 1: Implement pure risk functions**

Implement C-tier defaults, `calculate_drawdown_multiplier`, `calculate_trend_quality_multiplier`, `calculate_vol_scaled_amount`, and `calculate_risk_scaled_amount`. Use rounded drawdown boundaries to avoid floating point misclassification. Permit risk multipliers above 1.0 only up to `params["max_risk_multiplier"]` (1.25).

- [ ] **Step 2: Preserve and extend the V1.3 snapshot/execution flow**

Add `slow_slope` to the point-in-time snapshot using the 60-day slow average and its 10-day prior slow average. At the start of `trade_open`, compute the drawdown multiplier. In `open_position`, compute the trend quality multiplier from snapshot fields and pass their product to `calculate_risk_scaled_amount`. Do not resize or force-close existing positions solely because the multiplier changes.

- [ ] **Step 3: Run focused tests to verify GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest -q tests/test_iron_ore_cta_v1_4_aggressive.py`

Expected: all V1.4 tests pass.

### Task 3: Add static audit and JoinQuant copy

**Files:**
- Create: `tools/verify_iron_ore_cta_v1_4_aggressive.py`
- Create: `C:\Users\16052\Desktop\2025聚宽优秀策略\029_穿越牛熊2.0(非小市值)年化50%的cta策略\V1.4_铁矿石CTA_激进收益版.py`

- [ ] **Step 1: Implement static audit**

Require C-tier defaults, `calculate_trend_quality_multiplier`, the four drawdown thresholds, point-in-time data, anchored `I####.XDCE` selection, no package/future imports, no V1.2 trend-strength classifier, and `ALLOW_SHORT=False`. Success output must be `iron ore CTA V1.4 static audit: 0 violations`.

- [ ] **Step 2: Copy only after workspace verification**

Create the desktop file only if it does not already exist, then compare SHA256 with the workspace script. Do not overwrite an existing user file.

### Task 4: Full verification and commit

**Files:**
- Verify: all V1.4 files plus the desktop copy.

- [ ] **Step 1: Run focused tests, compile, static audit and runtime smoke**

Run the V1.4 focused test, `py_compile`, and static audit. The runtime smoke must cover a strict entry with the 1.25 trend boost, high-volatility suppression of the boost, drawdown scaling, and close-first rollover.

- [ ] **Step 2: Run the full test suite**

Run: `.\.venv\Scripts\python.exe -m pytest -q --disable-warnings`

Expected: exit code 0 and all tests pass.

- [ ] **Step 3: Review scoped diff and commit**

Run `git diff --check`, stage only the V1.4 spec, plan, script, test and audit, then commit with `feat: add iron ore CTA V1.4 aggressive risk tier`.

## Self-review

- Spec coverage: C-tier budget, strong-trend-only boost, high-volatility suppression, drawdown bands, point-in-time data and safe rollover each have explicit tasks and tests.
- Placeholder scan: no TBD/TODO or unspecified implementation step remains.
- Type consistency: all imported test functions are named in Task 2 and used by Task 3/4 verification.
