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
    rising = [100.0] * 80 + [
        101,
        102,
        103,
        104,
        105,
        106,
        107,
        108,
        109,
        110,
    ]
    falling = list(range(140, 58, -1))
    assert classify_v1_signal(rising, confirmation_days=2) == 1
    assert classify_v1_signal(falling, confirmation_days=1) == -1


def test_trend_quality_boost_requires_all_strong_conditions():
    params = {"target_annual_vol": 0.30}
    strong = calculate_trend_quality_multiplier(
        110,
        100,
        98,
        0.002,
        0.20,
        params,
    )
    weak = calculate_trend_quality_multiplier(
        100.5,
        100,
        98,
        0.002,
        0.20,
        params,
    )
    high_vol = calculate_trend_quality_multiplier(
        110,
        100,
        98,
        0.002,
        0.40,
        params,
    )
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
    base = calculate_risk_scaled_amount(
        1_000_000,
        1_000_000,
        500,
        0.20,
        1.0,
        params,
    )
    boosted = calculate_risk_scaled_amount(
        1_000_000,
        1_000_000,
        500,
        0.20,
        1.25,
        params,
    )
    stopped = calculate_risk_scaled_amount(
        1_000_000,
        1_000_000,
        500,
        0.20,
        0.0,
        params,
    )
    assert base == 30
    assert boosted == 37
    assert stopped == 0


def test_helpers_and_rollover_guard_remain_available():
    closes = [100, 102, 101, 105, 103, 108]
    bars = pd.DataFrame(
        {
            "high": [101, 103, 102, 106, 104, 109],
            "low": [99, 100, 100, 102, 101, 104],
            "close": closes,
        }
    )
    assert calculate_realized_volatility(closes) > 0
    assert calculate_atr(bars, 3) > 0
    futures = pd.DataFrame(
        {
            "end_date": pd.to_datetime(
                ["2026-08-05", "2026-08-20", "2026-08-30"]
            )
        },
        index=["I2608.XDCE", "I2609.XDCE", "IC2608.CCFX"],
    )
    assert (
        select_near_contract(
            futures,
            pd.Timestamp("2026-07-31").date(),
            8,
        )
        == "I2609.XDCE"
    )
    assert can_open_replacement(3, 3, 0)
    assert not can_open_replacement(3, 3, 1)
