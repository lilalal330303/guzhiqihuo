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
    rising = [100.0] * 80 + [
        101.0,
        102.0,
        103.0,
        104.0,
        105.0,
        106.0,
        107.0,
        108.0,
        109.0,
        110.0,
    ]
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
