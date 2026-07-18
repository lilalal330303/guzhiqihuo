# 铁矿石 CTA V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在保留原始 20/60 铁矿石趋势思想的前提下，生成一份可直接复制到聚宽的双模式 V2 脚本，并验证其信号、合约和换月状态机。

**Architecture:** 聚宽脚本保持单文件可复制结构，但内部拆成点时合约筛选、信号计算、风险手数、持仓读取、订单执行和每日调度函数。默认用 `ALLOW_SHORT=False` 做长多/空仓对照，改为 `True` 后启用空头趋势。所有信号输入以 `context.previous_date` 为上限，实际合约用 `get_all_securities(..., date=...)` 选择。

**Tech Stack:** Python 3 syntax, JoinQuant `jqdata` API, pandas-compatible DataFrame API, pytest/stub tests, `py_compile`.

## Global Constraints

- 交易标的是铁矿石 `I####.XDCE`，不是股指期货 `IC####.CCFX`。
- 信号只能使用前一交易日及更早数据，不得使用当前日未完成 K 线。
- 合约换月必须先平旧合约，确认实际持仓归零后才允许开新合约。
- 手数必须同时受 ATR 风险预算和保证金占用上限约束。
- 保留原始手续费 `0.000023/0.000023/0.0023` 和 `StepRelatedSlippage(2)`，不通过改成本制造收益。
- 不清理现有工作区改动；只新增本次策略文件、设计/计划文件和测试文件。

---

### Task 1: Add pure strategy helpers and red tests

**Files:**
- Create: `tests/test_iron_ore_cta_v2.py`
- Create: `reports/jq_iron_ore_cta_v2.py`

**Interfaces:**
- `select_contract_code(futures, signal_date, roll_days_before_expiry, deferred_rank)` returns a contract code or `None`.
- `classify_trend(closes, params)` returns `1`, `0`, or `-1`.
- `calculate_contract_amount(total_value, available_cash, price, atr, params)` returns a non-negative integer.
- `transition_direction(current_direction, confirmed_signal, allow_short)` returns `1`, `0`, or `-1`.

- [ ] **Step 1: Write failing tests for point-in-time contract selection.**

```python
def test_select_contract_excludes_contracts_inside_roll_window():
    futures = make_futures([
        ("I2405.XDCE", "2024-01-02", "2024-05-10"),
        ("I2406.XDCE", "2024-01-02", "2024-06-10"),
        ("I2407.XDCE", "2024-01-02", "2024-07-10"),
    ])
    assert select_contract_code(futures, date(2024, 5, 6), 8, 1) == "I2407.XDCE"
```

- [ ] **Step 2: Run the focused test and verify it fails because the module is missing.**

Run: `pytest tests/test_iron_ore_cta_v2.py::test_select_contract_excludes_contracts_inside_roll_window -q`

Expected: collection/import failure because `reports.jq_iron_ore_cta_v2` does not yet expose `select_contract_code`.

- [ ] **Step 3: Add the minimum pure helper declarations and implementation.**

```python
def select_contract_code(futures, signal_date, roll_days_before_expiry, deferred_rank):
    eligible = []
    signal_date = pd.Timestamp(signal_date).date()
    for code, row in futures.iterrows():
        raw = str(code).upper()
        if not re.match(r"^I\d{4}\.XDCE$", raw):
            continue
        start_date = pd.Timestamp(row["start_date"]).date()
        end_date = pd.Timestamp(row["end_date"]).date()
        if start_date > signal_date or (end_date - signal_date).days <= roll_days_before_expiry:
            continue
        eligible.append((end_date, raw))
    eligible.sort()
    if not eligible:
        return None
    return eligible[min(deferred_rank, len(eligible) - 1)][1]
```

- [ ] **Step 4: Run the focused test and verify it passes.**

Run: `pytest tests/test_iron_ore_cta_v2.py::test_select_contract_excludes_contracts_inside_roll_window -q`

Expected: `1 passed`.

### Task 2: Add signal, risk, and direction tests before implementation

**Files:**
- Modify: `tests/test_iron_ore_cta_v2.py`
- Modify: `reports/jq_iron_ore_cta_v2.py`

- [ ] **Step 1: Add failing tests for trend confirmation and risk caps.**

```python
def test_classify_trend_requires_spread_and_slope_confirmation():
    bullish = pd.Series([100 + i * 0.5 for i in range(90)])
    flat = pd.Series([100.0] * 90)
    assert classify_trend(bullish, PARAMS) == 1
    assert classify_trend(flat, PARAMS) == 0


def test_calculate_contract_amount_is_capped_by_margin():
    params = {"contract_multiplier": 100, "margin_rate": 0.15,
              "max_margin_usage": 0.45, "risk_per_atr": 0.012}
    assert calculate_contract_amount(1_000_000, 1_000_000, 800, 20, params) == 6


def test_short_signal_is_disabled_in_comparison_mode():
    assert transition_direction(0, -1, allow_short=False) == 0
    assert transition_direction(1, -1, allow_short=True) == -1
```

- [ ] **Step 2: Run these tests and verify they fail for missing helpers.**

Run: `pytest tests/test_iron_ore_cta_v2.py -q`

Expected: failures naming `classify_trend`, `calculate_contract_amount`, or `transition_direction`.

- [ ] **Step 3: Implement only the pure helpers needed by the tests.**

```python
def classify_trend(closes, params):
    closes = pd.Series(closes).dropna().astype(float)
    if len(closes) < params["trend_days"] + params["slope_days"]:
        return 0
    ma20 = closes.iloc[-params["fast_days"]:].mean()
    ma60 = closes.iloc[-params["trend_days"]:].mean()
    ma60_prev = closes.iloc[-params["trend_days"] - params["slope_days"]:-params["slope_days"]].mean()
    price = closes.iloc[-1]
    spread = ma20 / ma60 - 1.0
    slope = ma60 / ma60_prev - 1.0
    if price > ma20 * (1 + params["entry_buffer"]) and spread > params["min_spread"] and slope > params["min_slope"]:
        return 1
    if price < ma20 * (1 - params["exit_buffer"]) and spread < -params["min_spread"] and slope < -params["min_slope"]:
        return -1
    return 0


def calculate_contract_amount(total_value, available_cash, price, atr, params):
    if min(total_value, available_cash, price, atr) <= 0:
        return 0
    risk_lots = int(total_value * params["risk_per_atr"] // (atr * params["contract_multiplier"]))
    margin_per_contract = price * params["contract_multiplier"] * params["margin_rate"]
    margin_lots = int(max(0.0, available_cash) * params["max_margin_usage"] // margin_per_contract)
    return max(0, min(risk_lots, margin_lots))


def transition_direction(current_direction, confirmed_signal, allow_short):
    if confirmed_signal > 0:
        return 1
    if confirmed_signal < 0:
        return -1 if allow_short else 0
    return current_direction
```

- [ ] **Step 4: Run the helper tests and verify they pass.**

Run: `pytest tests/test_iron_ore_cta_v2.py -q`

Expected: all pure-helper tests pass.

### Task 3: Implement the JoinQuant execution state machine

**Files:**
- Modify: `reports/jq_iron_ore_cta_v2.py`
- Modify: `tests/test_iron_ore_cta_v2.py`

- [ ] **Step 1: Add failing tests for先平后开 and partial-fill state.**

```python
def test_roll_requires_zero_actual_position_before_opening_new_contract():
    broker = StubBroker({"I2406.XDCE": {"long": 2}})
    assert roll_to_contract(broker, "I2406.XDCE", "I2407.XDCE", 1) is False
    assert broker.opened == []


def test_partial_open_is_not_reported_as_full_target():
    broker = StubBroker({})
    broker.next_fill = 3
    assert open_directional_position(broker, "I2407.XDCE", 10, 1) is True
    assert broker.position("I2407.XDCE", 1) == 3
```

- [ ] **Step 2: Run the tests and verify the state-machine tests fail.**

Run: `pytest tests/test_iron_ore_cta_v2.py -q`

Expected: failures because `roll_to_contract` and `open_directional_position` are not implemented.

- [ ] **Step 3: Implement state helpers and daily execution.**

The production script must include:

```python
def close_directional_position(context, contract, direction):
    amount = get_position_amount(context, contract, direction)
    if amount <= 0:
        return True
    order = order_target(contract, 0, side="long" if direction > 0 else "short")
    remaining = get_position_amount(context, contract, direction)
    return remaining <= 0 or is_order_fully_filled(order)


def roll_to_contract(context, old_contract, new_contract, direction):
    if old_contract == new_contract:
        return True
    if not close_directional_position(context, old_contract, direction):
        log.info("CTA_V2 roll blocked: old contract is not flat")
        return False
    if get_position_amount(context, old_contract, direction) > 0:
        return False
    return True
```

The daily handler must: obtain the previous-date signal, update confirmation counters, choose the point-in-time contract, close an opposite direction before opening, and refuse to open when the old contract is not flat.

- [ ] **Step 4: Run state-machine tests and verify they pass.**

Run: `pytest tests/test_iron_ore_cta_v2.py -q`

Expected: all state-machine tests pass.

### Task 4: Wire the complete 聚宽 script and diagnostics

**Files:**
- Modify: `reports/jq_iron_ore_cta_v2.py`

- [ ] **Step 1: Add initialization and daily schedule.**

The script must call `set_option("avoid_future_data", True)`, use a `futures` subportfolio, retain the original cost/slippage settings, and schedule one absolute-time daily handler at `09:05` with `reference_security="I8888.XDCE"`.

- [ ] **Step 2: Add point-in-time signal and ATR data retrieval.**

All `get_price` calls must pass `end_date=context.previous_date` or the explicitly supplied signal date. The signal loader must return `None` when samples or valid prices are insufficient.

- [ ] **Step 3: Add structured logs and parameter switch.**

The script must expose `g.params["allow_short"]` or a top-level parameter with default `False`, log the selected mode, and log every skipped trade reason.

- [ ] **Step 4: Run Python syntax compilation.**

Run: `python -m py_compile reports/jq_iron_ore_cta_v2.py`

Expected: exit code 0 and no traceback.

### Task 5: Static audit and final verification

**Files:**
- Create: `tools/verify_iron_ore_cta_v2.py`
- Modify: `tests/test_iron_ore_cta_v2.py`

- [ ] **Step 1: Add a static audit for forbidden patterns.**

The audit must fail if the script contains `get_bars(` without `end_date`, `g.flag = 1` immediately after an order without a fill check, or a non-`I####.XDCE` contract passed to the trade executor.

- [ ] **Step 2: Run the full focused verification.**

Run: `pytest tests/test_iron_ore_cta_v2.py -q`  
Run: `python -m py_compile reports/jq_iron_ore_cta_v2.py`  
Run: `python tools/verify_iron_ore_cta_v2.py`

Expected: all tests pass, syntax compilation exits 0, and the static audit prints zero violations.

- [ ] **Step 3: Review the final diff without touching unrelated changes.**

Run: `git diff -- docs/superpowers/specs/2026-07-19-iron-ore-cta-v2-design.md docs/superpowers/plans/2026-07-19-iron-ore-cta-v2.md reports/jq_iron_ore_cta_v2.py tests/test_iron_ore_cta_v2.py tools/verify_iron_ore_cta_v2.py`

Expected: only the new design, plan, script, tests, and verifier are in the scoped diff.
