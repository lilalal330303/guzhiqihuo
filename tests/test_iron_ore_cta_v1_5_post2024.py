from types import SimpleNamespace

import pandas as pd

from reports.jq_iron_ore_cta_v1_5_post2024 import (
    POST_2024_START,
    POST_PARAMS,
    PRE_PARAMS,
    calculate_adaptive_signal,
    calculate_atr,
    calculate_drawdown_multiplier,
    calculate_efficiency_ratio,
    calculate_realized_volatility,
    calculate_regime_risk_multiplier,
    calculate_risk_scaled_amount,
    calculate_volatility_ratio,
    can_open_replacement,
    get_actual_position,
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
        1_000_000,
        1_000_000,
        500,
        0.20,
        0.5,
        POST_PARAMS,
    )
    assert amount == 15
    assert calculate_drawdown_multiplier(750_000, 1_000_000) == 0.0
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
    assert calculate_volatility_ratio(closes * 12, 5, 20) > 0
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


def test_position_detection_does_not_treat_short_total_as_long():
    position = SimpleNamespace(short_amount=3, total_amount=3)
    context = SimpleNamespace(
        portfolio=SimpleNamespace(positions={"I2609.XDCE": position})
    )
    assert get_actual_position(context) == ("I2609.XDCE", -1, 3)
