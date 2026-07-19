# 铁矿石 CTA V1.3 风险分级增强版实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 V1.1 的趋势信号和换月框架上，增加可解释的波动率仓位与回撤分级降风险，生成一个不依赖本地包、可直接粘贴到聚宽的单文件脚本。

**Architecture:** 新建独立的 `reports/jq_iron_ore_cta_v1_3_risk.py`，复制 V1.1 的点时趋势信号、实际持仓识别、先平后开换月和止损流程；只新增纯函数 `calculate_drawdown_multiplier` 与回撤缩放后的合约数量计算，并在每日交易前更新高水位。现有 V1.1/V1.2 文件不修改，桌面目录另存为 V1.3 直贴文件。

**Tech Stack:** Python 3、pandas、pytest、JoinQuant futures API。

## Global Constraints

- 必须兼容聚宽旧版 Python 运行时：不使用 `from __future__ import annotations`。
- 脚本必须是单文件：不导入 `reports.*`、不依赖 `src.*`，可直接复制到聚宽策略编辑器。
- 市场数据使用 `end_date=signal_date`，期货元数据使用 `get_all_securities(["futures"], date=signal_date)`，避免未来数据。
- 默认 `ALLOW_SHORT=False`，默认只做多，确认后如需做空由用户显式改为 True。
- 保留 V1.1 的严格趋势确认：20 日均线、60 日均线、10 日斜率、连续 2 日确认、0.2% 入场缓冲、0.2% 均线间距、0.05% 最小斜率。
- V1.3 默认目标年化波动率 20%、最大保证金占用 40%、最大杠杆 2.5、ATR 止损 3.0、换月/反向信号后冷却 2 个交易日。
- 回撤分级只限制新开仓和新仓位规模，不因回撤阈值单独强平当前持仓；当前持仓仍由反向信号、换月和 ATR 止损退出。
- 交付前必须运行聚焦测试、全量测试、静态审计、Python 编译、运行时冒烟，并核对桌面副本哈希一致。

---

### Task 1: 建立 V1.3 风控行为测试

**Files:**
- Create: `tests/test_iron_ore_cta_v1_3_risk.py`
- Test target: `reports/jq_iron_ore_cta_v1_3_risk.py`

**Interfaces:**
- Consumes: `classify_v1_signal`、`calculate_drawdown_multiplier`、`calculate_risk_scaled_amount`、`calculate_realized_volatility`、`calculate_atr`、`select_near_contract`、`can_open_replacement`。
- Produces: 明确约束信号不变、回撤分级边界、仓位计算和换月保护的可执行测试。

- [ ] **Step 1: Write the failing test**

```python
import pandas as pd

from reports.jq_iron_ore_cta_v1_3_risk import (
    calculate_atr,
    calculate_drawdown_multiplier,
    calculate_realized_volatility,
    calculate_risk_scaled_amount,
    can_open_replacement,
    classify_v1_signal,
    select_near_contract,
)


def test_v1_signal_keeps_strict_bullish_and_bearish_confirmation():
    rising = [100.0] * 80 + [101.0, 102.0, 103.0, 104.0, 105.0,
                              106.0, 107.0, 108.0, 109.0, 110.0]
    falling = list(range(140, 58, -1))
    assert classify_v1_signal(rising, confirmation_days=2) == 1
    assert classify_v1_signal(falling, confirmation_days=1) == -1


def test_drawdown_multiplier_is_piecewise_and_does_not_force_exit():
    assert calculate_drawdown_multiplier(1_000_000, 1_000_000) == 1.0
    assert calculate_drawdown_multiplier(900_000, 1_000_000) == 0.75
    assert calculate_drawdown_multiplier(850_000, 1_000_000) == 0.5
    assert calculate_drawdown_multiplier(800_000, 1_000_000) == 0.0


def test_risk_scaled_amount_respects_volatility_and_drawdown_budget():
    params = {
        "target_annual_vol": 0.20,
        "max_margin_usage": 0.40,
        "margin_rate": 0.15,
        "max_leverage": 2.5,
        "contract_multiplier": 100,
    }
    base = calculate_risk_scaled_amount(
        1_000_000, 1_000_000, 500, 0.20, 1.0, params
    )
    assert base == 20
    assert calculate_risk_scaled_amount(
        1_000_000, 1_000_000, 500, 0.20, 0.75, params
    ) == 15
    assert calculate_risk_scaled_amount(
        1_000_000, 1_000_000, 500, 0.20, 0.0, params
    ) == 0


def test_indicator_helpers_and_rollover_guard_remain_available():
    closes = [100, 102, 101, 105, 103, 108]
    bars = pd.DataFrame({
        "high": [101, 103, 102, 106, 104, 109],
        "low": [99, 100, 100, 102, 101, 104],
        "close": closes,
    })
    assert calculate_realized_volatility(closes) > 0
    assert calculate_atr(bars, 3) > 0
    futures = pd.DataFrame(
        {"end_date": pd.to_datetime(["2026-08-05", "2026-08-20", "2026-08-30"])},
        index=["I2608.XDCE", "I2609.XDCE", "IC2608.CCFX"],
    )
    assert select_near_contract(futures, pd.Timestamp("2026-07-31").date(), 8) == "I2609.XDCE"
    assert can_open_replacement(3, 3, 0)
    assert not can_open_replacement(3, 3, 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest -q tests/test_iron_ore_cta_v1_3_risk.py`

Expected: FAIL during collection with `ModuleNotFoundError` because the V1.3 production module does not exist yet.

### Task 2: Implement the standalone V1.3 strategy

**Files:**
- Create: `reports/jq_iron_ore_cta_v1_3_risk.py`

**Interfaces:**
- Consumes: V1.1 signal/execution behavior and Task 1 function signatures.
- Produces: 可直接粘贴的 JoinQuant strategy，包含 `initialize(context)`、`trade_open(context)`、纯函数风控接口和安全换月流程。

- [ ] **Step 1: Implement minimal pure functions**

Implement `_finite_positive`、`_clean_closes`、`_raw_trend_state`、`classify_v1_signal`、`calculate_realized_volatility`、`calculate_atr`、`calculate_drawdown_multiplier` and `calculate_risk_scaled_amount` with these exact defaults and boundary rules:

```python
DEFAULT_PARAMS = {
    "fast_days": 20, "trend_days": 60, "slope_days": 10,
    "atr_days": 20, "vol_days": 20, "confirmation_days": 2,
    "entry_buffer": 0.002, "min_spread": 0.002, "min_slope": 0.0005,
    "target_annual_vol": 0.20, "max_leverage": 2.5,
    "margin_rate": 0.15, "max_margin_usage": 0.40,
    "roll_days_before_expiry": 8, "contract_multiplier": 100,
    "stop_atr": 3.0, "cooldown_days": 2,
}


def calculate_drawdown_multiplier(current_value, high_water):
    if current_value <= 0 or high_water <= 0:
        return 0.0
    drawdown = max(0.0, 1.0 - float(current_value) / float(high_water))
    if drawdown < 0.10:
        return 1.0
    if drawdown < 0.15:
        return 0.75
    if drawdown < 0.20:
        return 0.50
    return 0.0


def calculate_risk_scaled_amount(
    total_value, available_cash, price, realized_vol, risk_multiplier, params
):
    base_amount = calculate_vol_scaled_amount(
        total_value, available_cash, price, realized_vol, params
    )
    return int(max(0.0, float(base_amount) * float(risk_multiplier)))
```

The signal classifier must remain the strict V1.1 classifier; it must not introduce a moderate/strong trend branch.

- [ ] **Step 2: Implement point-in-time data, actual-position execution, and risk overlay**

Copy the V1.1 execution shape into the new standalone file, with the following required changes:

```python
def initialize(context):
    # ... V1.1 setup ...
    g.high_water_value = float(context.portfolio.starting_cash)
    g.risk_multiplier = 1.0


def trade_open(context):
    total_value = float(getattr(context.portfolio, "total_value", 0.0))
    g.high_water_value = max(g.high_water_value, total_value)
    g.risk_multiplier = calculate_drawdown_multiplier(
        total_value, g.high_water_value
    )
    # ... then retain V1.1 snapshot, target selection, close-first rollover,
    # reverse-signal exit, ATR stop and cooldown flow ...
```

`open_position` must pass `g.risk_multiplier` to `calculate_risk_scaled_amount`; if it is zero, it must skip new entry. Existing positions must not be force-closed only because the multiplier reaches zero. `should_force_exit` must read `g.params["stop_atr"]`, not a global constant, and all data calls must retain the signal-date cutoff.

- [ ] **Step 3: Run focused tests to verify GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest -q tests/test_iron_ore_cta_v1_3_risk.py`

Expected: all V1.3 tests pass.

### Task 3: Add static audit and direct JoinQuant copy

**Files:**
- Create: `tools/verify_iron_ore_cta_v1_3_risk.py`
- Create: `C:\Users\16052\Desktop\2025聚宽优秀策略\029_穿越牛熊2.0(非小市值)年化50%的cta策略\V1.3_铁矿石CTA_风险控制增强版.py`

**Interfaces:**
- Consumes: the standalone V1.3 strategy.
- Produces: static checks for imports, point-in-time data, risk defaults, contract pattern and drawdown function; exact byte copy for JoinQuant use.

- [ ] **Step 1: Implement static audit**

The audit must fail if the script contains an actual `from reports` or `from __future__` import, an unguarded `get_bars(`, an undated futures metadata call, old 70% margin budget, missing `end_date=signal_date`, missing `calculate_drawdown_multiplier`, or short mode enabled by default. It must print `iron ore CTA V1.3 static audit: 0 violations` on success.

- [ ] **Step 2: Copy and verify the standalone file**

Copy the workspace script byte-for-byte to the desktop strategy directory only after the workspace file passes tests and compile. Confirm the copy has no package import and its SHA256 matches the workspace script.

### Task 4: Verification and handoff

**Files:**
- Verify: `reports/jq_iron_ore_cta_v1_3_risk.py`, `tests/test_iron_ore_cta_v1_3_risk.py`, `tools/verify_iron_ore_cta_v1_3_risk.py`, desktop copy.

- [ ] **Step 1: Run focused tests, compile, static audit, and runtime smoke**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_iron_ore_cta_v1_3_risk.py
.\.venv\Scripts\python.exe -m py_compile reports/jq_iron_ore_cta_v1_3_risk.py
.\.venv\Scripts\python.exe tools/verify_iron_ore_cta_v1_3_risk.py
```

The runtime smoke must exercise a strict bullish entry, risk multiplier reduction, close-first rollover, and cooldown/replacement guard using test doubles without connecting to JoinQuant.

- [ ] **Step 2: Run the full test suite**

Run: `.\.venv\Scripts\python.exe -m pytest -q --disable-warnings`

Expected: exit code 0 and no failures.

- [ ] **Step 3: Review the scoped diff and commit**

Run `git diff --check` and `git diff -- reports/jq_iron_ore_cta_v1_3_risk.py tests/test_iron_ore_cta_v1_3_risk.py tools/verify_iron_ore_cta_v1_3_risk.py docs/superpowers/plans/2026-07-19-iron-ore-v1-3-risk-throttle-plan.md`; stage only those four workspace files and commit with `feat: add iron ore CTA V1.3 risk throttle`.

## Self-review

- Spec coverage: V1.1 signal preservation is covered by Task 1 and Task 2; return/risk balance is covered by target volatility, margin cap, leverage cap and drawdown bands; JoinQuant pasteability is covered by Task 3; no-future-data and safe rollover are covered by Task 2 and static audit; delivery verification is covered by Task 4.
- Placeholder scan: no `TBD`, `TODO`, or unspecified implementation step is required; all commands, thresholds and function names are explicit.
- Type consistency: Task 1 imports the exact functions Task 2 implements; Task 3 audits the same standalone file; Task 4 verifies every created artifact.
