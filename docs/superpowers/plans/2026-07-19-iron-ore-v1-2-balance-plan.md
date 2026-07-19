# Iron Ore CTA V1.2 Balance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a V1.2 JoinQuant iron ore CTA that recovers part of V1.1's missed trend return through graded exposure while keeping volatility and leverage materially below the original V1.

**Architecture:** Keep the V1.1 single-file JoinQuant structure and actual-position execution safeguards. Replace the binary trend gate with a pure `classify_trend_strength` helper returning `0.0`, `0.5`, or `1.0`; multiply volatility-scaled size by that exposure fraction; soften confirmation and buffers; keep optional short mode disabled by default.

**Tech Stack:** Python 3 compatible with JoinQuant, `jqdata`, pandas, pytest, and the existing local static-audit workflow.

## Global Constraints

- Keep `SIGNAL_SECURITY = "I8888.XDCE"` and the original futures fee/slippage settings.
- Default to `ALLOW_SHORT = False`; short exposure is a separate backtest and uses half risk budget when enabled.
- Keep all signal data ending at `context.previous_date` and futures metadata point-in-time.
- Use target annual volatility `0.22`, maximum margin usage `0.45`, and maximum nominal leverage `2.5`.
- Use strong-trend exposure `1.0`, moderate-trend exposure `0.5`, and weak/bearish exposure `0.0`.
- Preserve close-first rollover, actual-position checks, cooldown, and expiry safety buffer.
- Do not modify the existing V1.1 script or unrelated dirty worktree files.

---

### Task 1: Define graded trend and sizing behavior with failing tests

**Files:**
- Create: `tests/test_iron_ore_cta_v1_2_balance.py`
- Create: `reports/jq_iron_ore_cta_v1_2_balance.py` only after the failing test run

**Interfaces:**
- Tests import `classify_trend_strength`, `calculate_balanced_amount`, `calculate_realized_volatility`, `calculate_atr`, `select_near_contract`, and `can_open_replacement` from `reports.jq_iron_ore_cta_v1_2_balance`.
- `classify_trend_strength` returns a tuple `(direction, strength)`, where direction is `1`, `0`, or `-1`, and strength is `1.0`, `0.5`, or `0.0`.

- [ ] **Step 1: Write the failing tests**

```python
import pandas as pd

from reports.jq_iron_ore_cta_v1_2_balance import (
    calculate_atr,
    calculate_balanced_amount,
    calculate_realized_volatility,
    can_open_replacement,
    classify_trend_strength,
    select_near_contract,
)


def test_strong_bull_trend_gets_full_exposure():
    closes = [100.0] * 70 + list(range(101, 121))
    direction, strength = classify_trend_strength(closes, confirmation_days=1)
    assert direction == 1
    assert strength == 1.0


def test_moderate_bull_trend_gets_half_exposure():
    closes = [100.0] * 60 + [100.1] * 20 + list(range(101, 111))
    direction, strength = classify_trend_strength(
        closes,
        confirmation_days=1,
        strong_slope=0.03,
    )
    assert direction == 1
    assert strength == 0.5


def test_bear_trend_is_flat_when_short_is_disabled():
    closes = list(range(140, 58, -1))
    direction, strength = classify_trend_strength(
        closes,
        confirmation_days=1,
        allow_short=False,
    )
    assert direction == 0
    assert strength == 0.0


def test_balanced_amount_respects_strength_and_two_point_five_leverage():
    params = {
        "target_annual_vol": 0.22,
        "max_margin_usage": 0.45,
        "margin_rate": 0.15,
        "max_leverage": 2.5,
        "contract_multiplier": 100,
    }
    full = calculate_balanced_amount(1_000_000, 1_000_000, 500, 0.22, 1.0, params)
    half = calculate_balanced_amount(1_000_000, 1_000_000, 500, 0.22, 0.5, params)
    assert full == 20
    assert half == 10


def test_atr_vol_contract_and_replacement_helpers_remain_safe():
    closes = [100, 102, 101, 105, 103, 108]
    bars = pd.DataFrame(
        {"high": [101, 103, 102, 106, 104, 109], "low": [99, 100, 100, 102, 101, 104], "close": closes}
    )
    futures = pd.DataFrame(
        {"end_date": pd.to_datetime(["2026-08-05", "2026-08-20"])},
        index=["I2608.XDCE", "I2609.XDCE"],
    )
    assert calculate_realized_volatility(closes) > 0
    assert calculate_atr(bars, 3) > 0
    assert select_near_contract(futures, pd.Timestamp("2026-07-31").date(), 8) == "I2609.XDCE"
    assert can_open_replacement(3, 3, 0)
    assert not can_open_replacement(3, 3, 1)
```

- [ ] **Step 2: Run the focused tests and confirm the expected collection failure**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_iron_ore_cta_v1_2_balance.py -q
```

Expected: collection fails because `reports.jq_iron_ore_cta_v1_2_balance` does not exist.

### Task 2: Implement pure V1.2 signal and balanced sizing helpers

**Files:**
- Create: `reports/jq_iron_ore_cta_v1_2_balance.py`

**Interfaces:**
- `classify_trend_strength(closes, fast_days=20, trend_days=60, slope_days=10, confirmation_days=1, entry_buffer=0.001, min_spread=0.001, moderate_slope=0.0002, strong_slope=0.002, allow_short=False) -> tuple`.
- `calculate_balanced_amount(total_value, available_cash, price, realized_vol, strength, params) -> int` applies volatility scaling, strength scaling, margin cap, and leverage cap.
- Reuse the proven V1.1 pure helpers for realized volatility, ATR, near-contract selection, replacement gating, and actual-position execution.

- [ ] **Step 1: Implement the minimum helper behavior**

The trend classifier must evaluate the latest confirmed raw states. It returns:

```text
strong bullish: price > MA20 > MA60, MA60 slope >= strong_slope -> (1, 1.0)
moderate bullish: price > MA60, MA20 > MA60, MA60 slope >= moderate_slope -> (1, 0.5)
bearish with ALLOW_SHORT=False -> (0, 0.0)
neutral -> (0, 0.0)
```

When `ALLOW_SHORT=True`, a confirmed bearish state returns `(-1, 0.5)` so short risk is half the long budget.

The sizing formula is:

```python
vol_leverage = target_annual_vol / realized_vol
margin_leverage = max_margin_usage / margin_rate
effective_leverage = min(vol_leverage, margin_leverage, max_leverage)
notional = min(total_value * effective_leverage,
               available_cash * margin_leverage)
amount = int(notional * strength / (price * contract_multiplier))
```

- [ ] **Step 2: Run focused tests and confirm they pass**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_iron_ore_cta_v1_2_balance.py -q
```

Expected: all pure-helper tests pass.

### Task 3: Add V1.2 JoinQuant execution and direct-copy script

**Files:**
- Modify: `reports/jq_iron_ore_cta_v1_2_balance.py`
- Create: `C:/Users/16052/Desktop/2025聚宽优秀策略/029_穿越牛熊2.0(非小市值)年化50%的cta策略/V1.2_铁矿石CTA_风险收益平衡版.py`

**Interfaces:**
- `initialize(context)` uses the V1.2 parameters and schedules one 09:05 daily callback.
- `get_signal_snapshot(signal_date)` reads point-in-time OHLC data and returns direction, strength, moving averages, ATR, and realized volatility.
- `trade_open(context)` closes invalid/old exposure first, applies cooldown, sizes by strength and volatility, and opens the target contract only when flat.

- [ ] **Step 1: Use V1.2 defaults**

```python
"target_annual_vol": 0.22,
"max_leverage": 2.5,
"max_margin_usage": 0.45,
"confirmation_days": 1,
"entry_buffer": 0.001,
"min_spread": 0.001,
"min_slope": 0.0002,
"strong_slope": 0.002,
"stop_atr": 3.5,
"cooldown_days": 1,
"short_strength": 0.5,
```

- [ ] **Step 2: Preserve V1.1 execution safeguards**

Keep the previous-date cutoff, point-in-time futures metadata, `I####.XDCE` regex, actual position detection, partial-fill handling, close-first rollover, and expiry buffer. Do not add any folder import; the delivered desktop file must be a standalone JoinQuant script.

- [ ] **Step 3: Log the decision decomposition**

Every daily decision must log direction, strength, realized volatility, effective contract amount, selected contract, and whether the action was entry, hold, exit, or rollover.

### Task 4: Add static audit, run verification, and commit scoped files

**Files:**
- Create: `tools/verify_iron_ore_cta_v1_2_balance.py`

- [ ] **Step 1: Audit the direct-copy script**

The audit must fail if the script contains `from reports`, `import reports`, `get_bars(`, a fixed `max_margin_usage=0.70`, missing `end_date=signal_date`, missing `date=signal_date` in futures metadata, or a `from __future__` import.

- [ ] **Step 2: Run focused syntax, tests, audit, and runtime smoke**

```powershell
.\.venv\Scripts\python.exe -m py_compile reports/jq_iron_ore_cta_v1_2_balance.py tests/test_iron_ore_cta_v1_2_balance.py tools/verify_iron_ore_cta_v1_2_balance.py
.\.venv\Scripts\python.exe -m pytest tests/test_iron_ore_cta_v1_2_balance.py -q
.\.venv\Scripts\python.exe tools/verify_iron_ore_cta_v1_2_balance.py
git diff --check -- reports/jq_iron_ore_cta_v1_2_balance.py tests/test_iron_ore_cta_v1_2_balance.py tools/verify_iron_ore_cta_v1_2_balance.py
```

Expected: syntax succeeds, focused tests pass, audit reports zero violations, and diff check is clean. A runtime smoke must verify full entry, close-first rollover, one-day cooldown, and replacement entry.

- [ ] **Step 3: Run the full project regression suite**

```powershell
.\.venv\Scripts\python.exe -m pytest -q --disable-warnings
```

Expected: exit code 0 with no test failures.

- [ ] **Step 4: Commit only V1.2 files**

```powershell
git add -- reports/jq_iron_ore_cta_v1_2_balance.py tests/test_iron_ore_cta_v1_2_balance.py tools/verify_iron_ore_cta_v1_2_balance.py docs/superpowers/plans/2026-07-19-iron-ore-v1-2-balance-plan.md
git commit -m "feat: add balanced iron ore CTA V1.2"
```

Do not stage or modify unrelated existing worktree changes.
