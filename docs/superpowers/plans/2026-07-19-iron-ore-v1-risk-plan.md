# Iron Ore CTA V1.1 Risk-Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a JoinQuant-compatible V1.1 iron ore CTA that preserves the original I8888/MA20/MA60 idea while removing the approximately 4.67x fixed exposure, adding trend confirmation, volatility-scaled sizing, and safe contract rollover.

**Architecture:** The delivered JoinQuant script remains a single copy-paste file under `reports/`, with pure signal, volatility, sizing, and contract-selection helpers separated from platform execution functions. Tests import only the pure helpers; a static audit checks that the script uses point-in-time data, does not reintroduce `get_bars` without an end date, and does not contain the previous fixed 70% margin model.

**Tech Stack:** Python 3 compatible with JoinQuant, `jqdata`, pandas, pytest, and the existing local verification scripts.

## Global Constraints

- Keep `SIGNAL_SECURITY = "I8888.XDCE"` and the original futures fees/slippage unless the platform rejects an API call.
- Default to `ALLOW_SHORT = False`; the short branch must be explicitly enabled for a separate backtest.
- Signals use data ending at `context.previous_date`; no current-day close/high/low may be used for a 09:05 order.
- Do not use the original `max_margin_usage=0.70` as the only sizing rule; cap margin usage at 35% and nominal leverage at 2.0.
- Contract metadata must be point-in-time and must select only `I####.XDCE` contracts with an expiry safety buffer.
- Rollover must close the old contract first and wait for actual flat exposure before opening the replacement.
- Do not modify unrelated dirty worktree files.

---

### Task 1: Define pure V1.1 behavior with failing tests

**Files:**
- Create: `tests/test_iron_ore_cta_v1_risk.py`
- Create: `reports/jq_iron_ore_cta_v1_risk.py` only after the failing test run

**Interfaces:**
- Tests will import `classify_v1_signal`, `calculate_realized_volatility`, `calculate_atr`, `calculate_vol_scaled_amount`, `select_near_contract`, and `can_open_replacement` from `reports.jq_iron_ore_cta_v1_risk`.
- The implementation will use plain Python values and pandas DataFrames so these functions can be tested without a JoinQuant runtime.

- [ ] **Step 1: Write the failing tests**

```python
import pandas as pd

from reports.jq_iron_ore_cta_v1_risk import (
    calculate_atr,
    calculate_realized_volatility,
    calculate_vol_scaled_amount,
    can_open_replacement,
    classify_v1_signal,
    select_near_contract,
)


def test_v1_signal_requires_bullish_stack_for_long():
    bearish = list(range(120, 61, -1))
    assert classify_v1_signal(bearish, confirmation_days=1) == -1


def test_v1_signal_requires_confirmation_and_slope():
    closes = [100.0] * 80 + [101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0, 110.0]
    assert classify_v1_signal(closes, confirmation_days=2) == 1
    assert classify_v1_signal(closes[:-1] + [99.0], confirmation_days=2) == 0


def test_volatility_scaled_amount_is_below_old_fixed_leverage():
    params = {
        "target_annual_vol": 0.15,
        "max_margin_usage": 0.35,
        "margin_rate": 0.15,
        "max_leverage": 2.0,
        "contract_multiplier": 100,
    }
    amount = calculate_vol_scaled_amount(
        total_value=1_000_000,
        available_cash=1_000_000,
        price=500,
        realized_vol=0.30,
        params=params,
    )
    assert amount == 10


def test_realized_volatility_and_atr_are_positive():
    closes = [100, 102, 101, 105, 103, 108]
    bars = pd.DataFrame(
        {"high": [101, 103, 102, 106, 104, 109], "low": [99, 100, 100, 102, 101, 104], "close": closes}
    )
    assert calculate_realized_volatility(closes) > 0
    assert calculate_atr(bars, 3) > 0


def test_near_contract_excludes_expiring_and_non_iron_contracts():
    futures = pd.DataFrame(
        {"end_date": pd.to_datetime(["2026-08-05", "2026-08-20", "2026-08-30"])},
        index=["I2608.XDCE", "I2609.XDCE", "IC2608.CCFX"],
    )
    assert select_near_contract(futures, pd.Timestamp("2026-07-31").date(), 8) == "I2609.XDCE"


def test_replacement_requires_actual_flat_exposure():
    assert can_open_replacement(old_amount=3, close_filled=3, remaining_amount=0)
    assert not can_open_replacement(old_amount=3, close_filled=3, remaining_amount=1)
```

- [ ] **Step 2: Run the focused tests and confirm the expected collection failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_iron_ore_cta_v1_risk.py -q
```

Expected: FAIL during collection because `reports.jq_iron_ore_cta_v1_risk` does not exist yet.

### Task 2: Implement the pure V1.1 signal, volatility, sizing, and contract helpers

**Files:**
- Create: `reports/jq_iron_ore_cta_v1_risk.py`

**Interfaces:**
- `classify_v1_signal(closes, fast_days=20, trend_days=60, slope_days=10, confirmation_days=2, min_slope=0.0005) -> int` returns `1` for confirmed bullish trend, `-1` for confirmed bearish trend, and `0` otherwise.
- `calculate_realized_volatility(closes, annual_days=252) -> float` returns annualized log-return volatility or `0.0` when insufficient.
- `calculate_atr(bars, window=20) -> float` returns the latest simple-average true range or `0.0` when insufficient.
- `calculate_vol_scaled_amount(total_value, available_cash, price, realized_vol, params) -> int` applies target volatility, max leverage, margin cap, and contract multiplier.
- `select_near_contract(futures, signal_date, roll_days_before_expiry=8) -> str | None` selects only eligible `I####.XDCE` contracts using point-in-time metadata.
- `can_open_replacement(old_amount, close_filled, remaining_amount) -> bool` returns true only when actual exposure is flat after a close.

- [ ] **Step 1: Implement only the helpers needed by the failing tests**

The sizing formula must cap all three budgets:

```python
vol_leverage = target_annual_vol / realized_vol
margin_leverage = max_margin_usage / margin_rate
effective_leverage = min(vol_leverage, margin_leverage, max_leverage)
notional_budget = min(total_value * effective_leverage,
                      available_cash * margin_leverage)
amount = int(notional_budget / (price * contract_multiplier))
```

Use `math.log` for realized-volatility returns, `pd.to_datetime` for contract expiry comparisons, and a regular expression anchored to `^I\d{4}\.XDCE$`.

- [ ] **Step 2: Run the focused tests and confirm they pass**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_iron_ore_cta_v1_risk.py -q
```

Expected: all pure-helper tests pass.

### Task 3: Add the JoinQuant execution layer with conservative defaults

**Files:**
- Modify: `reports/jq_iron_ore_cta_v1_risk.py`

**Interfaces:**
- `initialize(context)` configures `I8888.XDCE`, a futures subportfolio, original fees/slippage, and one `run_daily(trade_open, time="09:05", reference_security=SIGNAL_SECURITY)` schedule.
- `get_signal_snapshot(signal_date)` reads daily OHLC data ending at `signal_date` and returns close, ATR, realized volatility, and the confirmed V1.1 signal.
- `trade_open(context)` obtains the previous-date snapshot, identifies actual exposure, rolls safely, closes on neutral/bearish signals, and opens only after the account is flat.

- [ ] **Step 1: Add configuration and point-in-time data access**

Use these defaults:

```python
DEFAULT_PARAMS = {
    "fast_days": 20,
    "trend_days": 60,
    "slope_days": 10,
    "atr_days": 20,
    "confirmation_days": 2,
    "min_slope": 0.0005,
    "target_annual_vol": 0.15,
    "max_leverage": 2.0,
    "margin_rate": 0.15,
    "max_margin_usage": 0.35,
    "roll_days_before_expiry": 8,
    "contract_multiplier": 100,
    "stop_atr": 3.0,
    "cooldown_days": 2,
}
```

`get_price` calls must set `end_date=signal_date`; `get_all_securities(["futures"], date=signal_date)` must be used for contract metadata.

- [ ] **Step 2: Add actual-position and order helpers**

Track long and short amounts from the position object, close with `order_target(code, 0, side="long")` or `side="short"`, and never use a boolean flag as the sole evidence that exposure exists. If a close is not fully filled or actual remaining exposure is non-zero, do not open the replacement on that day.

- [ ] **Step 3: Add the daily execution state machine**

The daily order sequence is:

```text
read previous-date signal -> identify actual position -> close obsolete/invalid position
-> wait until actual flat -> observe cooldown -> size by volatility -> open target direction
```

`ALLOW_SHORT=False` maps a bearish signal to flat. `ALLOW_SHORT=True` permits a short only after the same safe close-then-open sequence.

- [ ] **Step 4: Add logging for signal, realized volatility, effective leverage, amount, contract, and rollover state**

Each order decision must include enough fields to reconcile the JoinQuant trade log with the backtest curve.

### Task 4: Add static audit and run the full verification suite

**Files:**
- Create: `tools/verify_iron_ore_cta_v1_risk.py`

- [ ] **Step 1: Implement static checks**

The audit must fail if the script contains `get_bars(`, `max_margin_usage` set to `0.70`, an unbounded futures metadata call without `date=`, an order target that is not a real `I####.XDCE` contract, or a `from __future__` import that could break older JoinQuant runtimes.

- [ ] **Step 2: Run focused syntax, unit, and static checks**

```powershell
.\.venv\Scripts\python.exe -m py_compile reports/jq_iron_ore_cta_v1_risk.py tests/test_iron_ore_cta_v1_risk.py tools/verify_iron_ore_cta_v1_risk.py
.\.venv\Scripts\python.exe -m pytest tests/test_iron_ore_cta_v1_risk.py -q
.\.venv\Scripts\python.exe tools/verify_iron_ore_cta_v1_risk.py
git diff --check -- reports/jq_iron_ore_cta_v1_risk.py tests/test_iron_ore_cta_v1_risk.py tools/verify_iron_ore_cta_v1_risk.py
```

Expected: syntax succeeds, focused tests pass, static audit reports zero violations, and `git diff --check` is clean.

- [ ] **Step 3: Run the existing project regression suite**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: exit code 0 with no test failures.

- [ ] **Step 4: Commit only the scoped implementation files**

```powershell
git add -- reports/jq_iron_ore_cta_v1_risk.py tests/test_iron_ore_cta_v1_risk.py tools/verify_iron_ore_cta_v1_risk.py docs/superpowers/plans/2026-07-19-iron-ore-v1-risk-plan.md
git commit -m "feat: add volatility controlled iron ore CTA V1.1"
```

Do not stage or modify unrelated existing worktree changes.
