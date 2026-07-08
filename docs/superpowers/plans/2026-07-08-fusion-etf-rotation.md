# Fusion ETF Rotation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a single fused ETF rotation strategy using Wufu V12C as the baseline and Qixing as an optional enhancement, then export a clean JoinQuant script.

**Architecture:** Keep the local workbench logic in `src/quant_lab/strategies/wufu_etf_rotation.py`, adding a fusion wrapper around existing Wufu target generation. Add tests that prove baseline compatibility, deduplication, Qixing scoring, weak-pool constraints, defensive fallback, and JoinQuant export cleanliness. Generate `reports/jq_fusion_etf_rotation_v1.py` by deriving from the confirmed V12C script and adding a Qixing enhancement block without introducing multi-strategy ownership.

**Tech Stack:** Python 3.11+, pandas, numpy, pytest, JoinQuant script APIs in the exported script.

## Global Constraints

- Base script: `reports/jq_wufu_fixed_pool_v12c_ultra_split.py`.
- Local strategy layer: `src/quant_lab/strategies/wufu_etf_rotation.py`.
- Output JoinQuant script: `reports/jq_fusion_etf_rotation_v1.py`.
- Remove unused small-cap, blue-chip, and multi-strategy account logic.
- Preserve Wufu V12C behavior as the baseline unless a Qixing enhancement is explicitly enabled.
- Fuse Qixing and Wufu into one target-generation pipeline, one holding set, and one order path.
- Avoid ownership conflicts by removing strategy IDs, virtual sub-accounts, and parallel schedulers.
- Do not add Streamlit UI changes in this pass.
- Use TDD for production-code behavior changes.

---

## File Structure

- Modify: `src/quant_lab/strategies/wufu_etf_rotation.py`
  - Add `DEFAULT_QIXING_ETF_POOL`, `QixingEnhancementConfig`, `FusionEtfRotationConfig`, `generate_fusion_etf_targets()`, and helper functions for fused pools/scores.
- Create: `tests/test_fusion_etf_rotation.py`
  - Focused tests for the fusion API and export cleanliness.
- Create: `reports/jq_fusion_etf_rotation_v1.py`
  - Clean JoinQuant adapter derived from V12C with Qixing enhancement folded into a single selector.

---

### Task 1: Local Fusion API And Baseline Compatibility

**Files:**
- Modify: `src/quant_lab/strategies/wufu_etf_rotation.py`
- Create: `tests/test_fusion_etf_rotation.py`

**Interfaces:**
- Consumes: `WufuEtfRotationConfig`, `generate_wufu_targets()`
- Produces:
  - `DEFAULT_QIXING_ETF_POOL: list[str]`
  - `QixingEnhancementConfig`
  - `FusionEtfRotationConfig`
  - `generate_fusion_etf_targets(prices, config=None, weak_states=None, dynamic_snapshots=None, liquidity_thresholds=None, liquidity_lookback=3) -> pd.DataFrame`

- [ ] **Step 1: Write failing baseline and dedupe tests**

Add this to `tests/test_fusion_etf_rotation.py`:

```python
import json

import pandas as pd

from quant_lab.strategies.wufu_etf_rotation import (
    FusionEtfRotationConfig,
    QixingEnhancementConfig,
    WufuEtfRotationConfig,
    generate_fusion_etf_targets,
    generate_wufu_targets,
)


def test_fusion_matches_wufu_when_qixing_disabled():
    dates = pd.date_range("2024-01-01", periods=35, freq="D")
    prices = pd.concat(
        [
            _bars("AAA", dates, [10.0 * (1.01**i) for i in range(35)], 1000.0),
            _bars("BBB", dates, [10.0] * 35, 1000.0),
            _bars("511880", dates, [1.0] * 35, 100000.0),
        ],
        ignore_index=True,
    )
    wufu_config = WufuEtfRotationConfig(
        etf_pool=["AAA", "BBB"],
        global_etf_pool=["AAA", "BBB"],
        defensive_etf="511880",
        lookback_days=25,
        max_score_threshold=20.0,
        enable_volume_check=False,
        enable_loss_filter=False,
    )

    wufu = generate_wufu_targets(prices, config=wufu_config)
    fusion = generate_fusion_etf_targets(
        prices,
        config=FusionEtfRotationConfig(wufu=wufu_config, qixing=QixingEnhancementConfig(enabled=False)),
    )

    pd.testing.assert_series_equal(
        fusion["target_symbol"],
        wufu["target_symbol"],
        check_names=False,
    )


def test_fusion_deduplicates_wufu_and_qixing_symbols():
    dates = pd.date_range("2024-01-01", periods=35, freq="D")
    prices = pd.concat(
        [
            _bars("AAA", dates, [10.0 * (1.01**i) for i in range(35)], 1000.0),
            _bars("BBB", dates, [10.0 * (1.005**i) for i in range(35)], 1000.0),
            _bars("511880", dates, [1.0] * 35, 100000.0),
        ],
        ignore_index=True,
    )
    config = FusionEtfRotationConfig(
        wufu=WufuEtfRotationConfig(
            etf_pool=["AAA", "BBB"],
            global_etf_pool=["AAA", "BBB"],
            defensive_etf="511880",
            lookback_days=25,
            max_score_threshold=20.0,
            enable_volume_check=False,
            enable_loss_filter=False,
        ),
        qixing=QixingEnhancementConfig(enabled=True, pool=["AAA", "AAA", "BBB"], preferred_pool_bonus=0.0),
    )

    targets = generate_fusion_etf_targets(prices, config=config)
    ready = targets.dropna(subset=["target_symbol"]).iloc[0]
    candidates = json.loads(ready["candidates_json"])

    assert [row["symbol"] for row in candidates].count("AAA") == 1
    assert [row["symbol"] for row in candidates].count("BBB") == 1


def _bars(symbol: str, dates: pd.DatetimeIndex, closes: list[float], volume: float) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": symbol,
            "trade_date": dates,
            "open": closes,
            "high": [value * 1.01 for value in closes],
            "low": [value * 0.99 for value in closes],
            "close": closes,
            "volume": [volume] * len(closes),
            "amount": [value * volume for value in closes],
        }
    )
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_fusion_etf_rotation.py -q`

Expected: FAIL with import errors for `FusionEtfRotationConfig`, `QixingEnhancementConfig`, and `generate_fusion_etf_targets`.

- [ ] **Step 3: Implement minimal local fusion API**

Add these definitions near `WufuEtfRotationConfig` in `src/quant_lab/strategies/wufu_etf_rotation.py`:

```python
DEFAULT_QIXING_ETF_POOL = [
    "518880",
    "159980",
    "159985",
    "501018",
    "161226",
    "159981",
    "513100",
    "159509",
    "513290",
    "513500",
    "159529",
    "513400",
    "513520",
    "513030",
    "513080",
    "513310",
    "513730",
    "159792",
    "513130",
    "513050",
    "159920",
    "513690",
    "510300",
    "510500",
    "510050",
    "510210",
    "159915",
    "588080",
    "512100",
    "563360",
    "563300",
    "512890",
    "159967",
    "512040",
    "159201",
    "511380",
    "511010",
    "511220",
]


@dataclass(frozen=True)
class QixingEnhancementConfig:
    enabled: bool = False
    pool: list[str] = field(default_factory=lambda: DEFAULT_QIXING_ETF_POOL.copy())
    preferred_pool_bonus: float = 0.0
    short_lookback_days: int = 10
    short_momentum_min: float | None = None
    liquidity_lookback_days: int = 20
    liquidity_threshold: float | None = None
    volume_lookback_days: int = 5
    volume_threshold: float | None = None
    premium_threshold: float | None = None


@dataclass(frozen=True)
class FusionEtfRotationConfig:
    wufu: WufuEtfRotationConfig = field(default_factory=WufuEtfRotationConfig)
    qixing: QixingEnhancementConfig = field(default_factory=QixingEnhancementConfig)
```

Add `generate_fusion_etf_targets()` after `generate_wufu_targets()`:

```python
def generate_fusion_etf_targets(
    prices: pd.DataFrame,
    config: FusionEtfRotationConfig | None = None,
    weak_states: pd.DataFrame | None = None,
    dynamic_snapshots: pd.DataFrame | None = None,
    liquidity_thresholds: pd.DataFrame | dict[pd.Timestamp | str, float] | float | None = None,
    liquidity_lookback: int = 3,
) -> pd.DataFrame:
    config = config or FusionEtfRotationConfig()
    if not config.qixing.enabled:
        return generate_wufu_targets(
            prices,
            config=config.wufu,
            weak_states=weak_states,
            dynamic_snapshots=dynamic_snapshots,
            liquidity_thresholds=liquidity_thresholds,
            liquidity_lookback=liquidity_lookback,
        )

    fused_wufu = WufuEtfRotationConfig(
        **{
            **config.wufu.__dict__,
            "etf_pool": list(dict.fromkeys(config.wufu.etf_pool + config.qixing.pool)),
        }
    )
    return _generate_fusion_targets_with_bonus(
        prices=prices,
        config=FusionEtfRotationConfig(wufu=fused_wufu, qixing=config.qixing),
        weak_states=weak_states,
        dynamic_snapshots=dynamic_snapshots,
        liquidity_thresholds=liquidity_thresholds,
        liquidity_lookback=liquidity_lookback,
    )
```

Add `_generate_fusion_targets_with_bonus()` using the existing Wufu cache/ranking helpers:

```python
def _generate_fusion_targets_with_bonus(
    prices: pd.DataFrame,
    config: FusionEtfRotationConfig,
    weak_states: pd.DataFrame | None,
    dynamic_snapshots: pd.DataFrame | None,
    liquidity_thresholds: pd.DataFrame | dict[pd.Timestamp | str, float] | float | None,
    liquidity_lookback: int,
) -> pd.DataFrame:
    wufu_config = config.wufu
    required = {"symbol", "trade_date", "close", "volume"}
    missing = required.difference(prices.columns)
    if missing:
        raise ValueError(f"prices missing required columns: {sorted(missing)}")
    if wufu_config.holdings_num != 1:
        raise ValueError("fusion local version supports holdings_num=1")

    data = prices.copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"])
    data = data.sort_values(["symbol", "trade_date"])
    dynamic_by_date = _dynamic_pool_by_date(dynamic_snapshots)
    dynamic_symbols = [symbol for symbols in dynamic_by_date.values() for symbol in symbols]
    allowed = set(wufu_config.etf_pool + wufu_config.dynamic_etf_pool + dynamic_symbols + config.qixing.pool)
    if wufu_config.defensive_etf:
        allowed.add(wufu_config.defensive_etf)
    data = data[data["symbol"].isin(allowed)]
    if data.empty:
        raise ValueError("no prices available for configured ETF pool")

    weak_by_date = _weak_state_by_date(weak_states)
    symbol_bars = _symbol_bar_cache(data)
    threshold_by_date = _liquidity_threshold_by_date(liquidity_thresholds) if liquidity_thresholds is not None else None
    qixing_pool = set(config.qixing.pool)
    rows: list[dict[str, object]] = []
    for trade_date in sorted(data["trade_date"].drop_duplicates()):
        is_weak = weak_by_date.get(trade_date, False)
        daily_dynamic_pool = dynamic_by_date.get(trade_date, [])
        etf_pool = (
            wufu_config.global_etf_pool
            if is_weak
            else list(dict.fromkeys(wufu_config.etf_pool + wufu_config.dynamic_etf_pool + daily_dynamic_pool + config.qixing.pool))
        )
        if threshold_by_date is not None:
            filtered_pool = _filter_pool_by_liquidity_for_date(symbol_bars, trade_date, etf_pool, threshold_by_date, liquidity_lookback)
            if filtered_pool:
                etf_pool = filtered_pool
        metrics = _rank_etfs_for_date_cached(symbol_bars, trade_date, wufu_config, etf_pool=etf_pool, is_weak=is_weak)
        metrics = [_with_fusion_score(row, qixing_pool, config.qixing) for row in metrics]
        metrics.sort(key=lambda row: float(row["fusion_score"]), reverse=True)
        for index, row in enumerate(metrics, start=1):
            row["rank"] = index
        candidates = _apply_fusion_candidate_threshold(metrics, wufu_config, is_weak=is_weak)
        target = candidates[0] if candidates else None
        if target is None and wufu_config.defensive_etf in symbol_bars:
            target = _defensive_target_cached(symbol_bars, trade_date, wufu_config.defensive_etf)
        rows.append(
            {
                "trade_date": trade_date,
                "target_symbol": target["symbol"] if target else None,
                "rank": target["rank"] if target else None,
                "momentum_score": target["momentum_score"] if target else None,
                "fusion_score": target.get("fusion_score") if target else None,
                "annualized_return": target["annualized_return"] if target else None,
                "r_squared": target["r_squared"] if target else None,
                "close": target["close"] if target else None,
                "is_weak": is_weak,
                "candidates_json": json.dumps(_serializable_fusion_candidates(candidates[:10]), ensure_ascii=False),
            }
        )
    return pd.DataFrame(rows)
```

Add the helper functions:

```python
def _with_fusion_score(
    row: dict[str, object],
    qixing_pool: set[str],
    config: QixingEnhancementConfig,
) -> dict[str, object]:
    output = dict(row)
    bonus = config.preferred_pool_bonus if str(row["symbol"]) in qixing_pool else 0.0
    output["qixing_bonus"] = float(bonus)
    output["fusion_score"] = float(row["momentum_score"]) + float(bonus)
    output["sources"] = ["wufu", "qixing"] if str(row["symbol"]) in qixing_pool else ["wufu"]
    return output


def _apply_fusion_candidate_threshold(
    ranked: list[dict[str, object]],
    config: WufuEtfRotationConfig,
    is_weak: bool = False,
) -> list[dict[str, object]]:
    top_10 = ranked[:10]
    if len(top_10) < config.holdings_num:
        return top_10
    reference_score = float(top_10[config.holdings_num - 1]["fusion_score"])
    ratio = 1.0 if is_weak else config.score_threshold_ratio
    score_threshold = reference_score * ratio
    return [row for row in top_10 if float(row["fusion_score"]) >= score_threshold]


def _serializable_fusion_candidates(candidates: list[dict[str, object]]) -> list[dict[str, object]]:
    fields = ["symbol", "rank", "momentum_score", "fusion_score", "qixing_bonus", "annualized_return", "r_squared", "close", "sources"]
    return [{field: candidate.get(field) for field in fields} for candidate in candidates]
```

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m pytest tests/test_fusion_etf_rotation.py -q`

Expected: PASS.

---

### Task 2: Qixing Bonus, Weak Constraint, And Defensive Fallback

**Files:**
- Modify: `tests/test_fusion_etf_rotation.py`
- Modify: `src/quant_lab/strategies/wufu_etf_rotation.py`

**Interfaces:**
- Consumes: `generate_fusion_etf_targets()`
- Produces: verified Qixing enhancement semantics.

- [ ] **Step 1: Write failing behavior tests**

Append to `tests/test_fusion_etf_rotation.py`:

```python
def test_qixing_bonus_can_promote_close_candidate():
    dates = pd.date_range("2024-01-01", periods=35, freq="D")
    prices = pd.concat(
        [
            _bars("WUFU", dates, [10.0 * (1.010**i) for i in range(35)], 1000.0),
            _bars("QIX", dates, [10.0 * (1.009**i) for i in range(35)], 1000.0),
            _bars("511880", dates, [1.0] * 35, 100000.0),
        ],
        ignore_index=True,
    )

    targets = generate_fusion_etf_targets(
        prices,
        config=FusionEtfRotationConfig(
            wufu=WufuEtfRotationConfig(
                etf_pool=["WUFU"],
                global_etf_pool=["WUFU"],
                defensive_etf="511880",
                lookback_days=25,
                max_score_threshold=20.0,
                enable_volume_check=False,
                enable_loss_filter=False,
            ),
            qixing=QixingEnhancementConfig(enabled=True, pool=["QIX"], preferred_pool_bonus=0.5),
        ),
    )

    first_ready = targets.dropna(subset=["target_symbol"]).iloc[0]
    assert first_ready["target_symbol"] == "QIX"
    assert first_ready["fusion_score"] > first_ready["momentum_score"]


def test_weak_market_uses_wufu_global_pool_before_qixing_enhancement():
    dates = pd.date_range("2024-01-01", periods=35, freq="D")
    prices = pd.concat(
        [
            _bars("GLOBAL", dates, [10.0 * (1.006**i) for i in range(35)], 1000.0),
            _bars("QIX", dates, [10.0 * (1.020**i) for i in range(35)], 1000.0),
            _bars("511880", dates, [1.0] * 35, 100000.0),
        ],
        ignore_index=True,
    )
    weak_states = pd.DataFrame({"trade_date": dates, "is_weak": [True] * len(dates)})

    targets = generate_fusion_etf_targets(
        prices,
        config=FusionEtfRotationConfig(
            wufu=WufuEtfRotationConfig(
                etf_pool=["GLOBAL"],
                global_etf_pool=["GLOBAL"],
                defensive_etf="511880",
                lookback_days=25,
                max_score_threshold=20.0,
                enable_volume_check=False,
                enable_loss_filter=False,
            ),
            qixing=QixingEnhancementConfig(enabled=True, pool=["QIX"], preferred_pool_bonus=10.0),
        ),
        weak_states=weak_states,
    )

    first_ready = targets.dropna(subset=["target_symbol"]).iloc[0]
    assert first_ready["target_symbol"] == "GLOBAL"


def test_fusion_falls_back_to_defensive_etf_when_no_candidate_passes():
    dates = pd.date_range("2024-01-01", periods=35, freq="D")
    prices = pd.concat(
        [
            _bars("BAD", dates, [10.0 * (0.99**i) for i in range(35)], 1000.0),
            _bars("511880", dates, [1.0] * 35, 100000.0),
        ],
        ignore_index=True,
    )

    targets = generate_fusion_etf_targets(
        prices,
        config=FusionEtfRotationConfig(
            wufu=WufuEtfRotationConfig(
                etf_pool=["BAD"],
                global_etf_pool=["BAD"],
                defensive_etf="511880",
                lookback_days=25,
                min_score_threshold=0.1,
                max_score_threshold=20.0,
                enable_volume_check=False,
                enable_loss_filter=False,
            ),
            qixing=QixingEnhancementConfig(enabled=True, pool=["BAD"], preferred_pool_bonus=0.0),
        ),
    )

    first_ready = targets.dropna(subset=["target_symbol"]).iloc[0]
    assert first_ready["target_symbol"] == "511880"
    assert first_ready["rank"] == 999
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_fusion_etf_rotation.py -q`

Expected: at least `test_qixing_bonus_can_promote_close_candidate` fails if Task 1 did not fully implement bonus ranking, or all pass if Task 1 implementation already covered these behaviors. If all pass, record that these tests validate existing Task 1 behavior.

- [ ] **Step 3: Adjust implementation only if RED shows a gap**

If weak mode incorrectly includes Qixing-only symbols, change `_generate_fusion_targets_with_bonus()` weak branch to:

```python
etf_pool = (
    wufu_config.global_etf_pool
    if is_weak
    else list(dict.fromkeys(wufu_config.etf_pool + wufu_config.dynamic_etf_pool + daily_dynamic_pool + config.qixing.pool))
)
```

If bonus is not ranking, ensure:

```python
metrics = [_with_fusion_score(row, qixing_pool, config.qixing) for row in metrics]
metrics.sort(key=lambda row: float(row["fusion_score"]), reverse=True)
```

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest tests/test_fusion_etf_rotation.py -q`

Expected: PASS.

---

### Task 3: JoinQuant Fusion Export

**Files:**
- Create: `reports/jq_fusion_etf_rotation_v1.py`
- Modify: `tests/test_fusion_etf_rotation.py`

**Interfaces:**
- Consumes: `reports/jq_wufu_fixed_pool_v12c_ultra_split.py`
- Produces: `reports/jq_fusion_etf_rotation_v1.py`

- [ ] **Step 1: Write failing export cleanliness test**

Append to `tests/test_fusion_etf_rotation.py`:

```python
from pathlib import Path


def test_joinquant_fusion_export_is_single_strategy_clean():
    script = Path("reports/jq_fusion_etf_rotation_v1.py")
    assert script.exists()
    text = script.read_text(encoding="utf-8")

    forbidden = [
        "portfolio_value_proportion",
        "sub_account",
        "stock_strategy",
        "strategy_holdings",
        "小市值",
        "白马",
        "run_weekly(strategy_1",
        "qixing_etf_sell_trade",
        "qixing_etf_buy_trade",
    ]
    for token in forbidden:
        assert token not in text

    assert "QIXING_ETF_POOL" in text
    assert "QIXING_ENHANCEMENT_ENABLED" in text
    assert "select_target" in text
    assert "order_target_value" in text
```

- [ ] **Step 2: Run test and verify RED**

Run: `python -m pytest tests/test_fusion_etf_rotation.py::test_joinquant_fusion_export_is_single_strategy_clean -q`

Expected: FAIL because `reports/jq_fusion_etf_rotation_v1.py` does not exist.

- [ ] **Step 3: Create the exported script**

Copy `reports/jq_wufu_fixed_pool_v12c_ultra_split.py` to `reports/jq_fusion_etf_rotation_v1.py`, then make these focused edits:

1. Change the module docstring title to `JoinQuant version: Fusion ETF rotation V1 based on Wufu V12C`.
2. Add constants after `CHINA_ETF_POOL`:

```python
QIXING_ETF_POOL = [
    "518880.XSHG", "159980.XSHE", "159985.XSHE", "501018.XSHG", "161226.XSHE",
    "159981.XSHE", "513100.XSHG", "159509.XSHE", "513290.XSHG", "513500.XSHG",
    "159529.XSHE", "513400.XSHG", "513520.XSHG", "513030.XSHG", "513080.XSHG",
    "513310.XSHG", "513730.XSHG", "159792.XSHE", "513130.XSHG", "513050.XSHG",
    "159920.XSHE", "513690.XSHG", "510300.XSHG", "510500.XSHG", "510050.XSHG",
    "510210.XSHG", "159915.XSHE", "588080.XSHG", "512100.XSHG", "563360.XSHG",
    "563300.XSHG", "512890.XSHG", "159967.XSHE", "512040.XSHG", "159201.XSHE",
    "511380.XSHG", "511010.XSHG", "511220.XSHG",
]
QIXING_ENHANCEMENT_ENABLED = True
QIXING_PREFERRED_POOL_BONUS = 0.0
```

3. In `initialize(context)`, add:

```python
    g.qixing_etf_pool = QIXING_ETF_POOL[:]
    g.qixing_enhancement_enabled = QIXING_ENHANCEMENT_ENABLED
    g.qixing_preferred_pool_bonus = QIXING_PREFERRED_POOL_BONUS
```

4. In the non-weak branch of `morning_routine(context)`, after `g.merged_etf_pool` is built, dedupe Qixing into the unified pool:

```python
        if g.qixing_enhancement_enabled:
            g.merged_etf_pool = list(dict.fromkeys(g.merged_etf_pool + g.qixing_etf_pool))
```

5. In `score_symbol(code, context)`, include `fusion_score` in the returned row:

```python
    qixing_bonus = g.qixing_preferred_pool_bonus if code in getattr(g, "qixing_etf_pool", []) else 0.0
    result["qixing_bonus"] = qixing_bonus
    result["fusion_score"] = result["momentum_score"] + qixing_bonus
```

6. In `select_target(context)`, sort candidates by `fusion_score` when present:

```python
    ranked.sort(key=lambda item: item.get("fusion_score", item.get("momentum_score", -999999)), reverse=True)
```

Do not add strategy IDs, sub-accounts, or Qixing order callbacks.

- [ ] **Step 4: Run export cleanliness test**

Run: `python -m pytest tests/test_fusion_etf_rotation.py::test_joinquant_fusion_export_is_single_strategy_clean -q`

Expected: PASS.

- [ ] **Step 5: Static-check exported script**

Run: `python -m py_compile reports/jq_fusion_etf_rotation_v1.py`

Expected: exits with code 0.

---

### Task 4: Final Verification

**Files:**
- Verify only; no planned file edits.

**Interfaces:**
- Consumes: completed Tasks 1-3.
- Produces: verified working local module and exported JoinQuant script.

- [ ] **Step 1: Run focused tests**

Run: `python -m pytest tests/test_wufu_etf_rotation.py tests/test_fusion_etf_rotation.py -q`

Expected: PASS.

- [ ] **Step 2: Run full suite**

Run: `python -m pytest -q`

Expected: PASS. If unrelated legacy tests fail, capture the exact failing test names and error messages.

- [ ] **Step 3: Scan exported script for removed conflict patterns**

Run:

```powershell
Select-String -LiteralPath 'reports\jq_fusion_etf_rotation_v1.py' -Pattern 'portfolio_value_proportion|sub_account|stock_strategy|strategy_holdings|qixing_etf_sell_trade|qixing_etf_buy_trade|小市值|白马' -Encoding UTF8
```

Expected: no matches.

- [ ] **Step 4: Report git limitation if still unavailable**

Run: `git status --short`

Expected: if `git` is unavailable in this environment, report that commits could not be created here. If available, commit changed files with:

```bash
git add docs/superpowers/specs/2026-07-08-fusion-etf-rotation-design.md docs/superpowers/plans/2026-07-08-fusion-etf-rotation.md src/quant_lab/strategies/wufu_etf_rotation.py tests/test_fusion_etf_rotation.py reports/jq_fusion_etf_rotation_v1.py
git commit -m "feat: add fused wufu qixing etf rotation"
```

---

## Self-Review

- Spec coverage: Tasks cover local fusion API, Qixing-as-enhancement, conflict prevention, V12C-based JoinQuant export, and verification.
- Placeholder scan: no TODO/TBD placeholders remain.
- Type consistency: `FusionEtfRotationConfig`, `QixingEnhancementConfig`, and `generate_fusion_etf_targets()` are consistently named across tasks.
