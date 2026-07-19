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
        {
            "high": [101, 103, 102, 106, 104, 109],
            "low": [99, 100, 100, 102, 101, 104],
            "close": closes,
        }
    )
    futures = pd.DataFrame(
        {"end_date": pd.to_datetime(["2026-08-05", "2026-08-20"])},
        index=["I2608.XDCE", "I2609.XDCE"],
    )
    assert calculate_realized_volatility(closes) > 0
    assert calculate_atr(bars, 3) > 0
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
