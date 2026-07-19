from types import SimpleNamespace

import pandas as pd

from reports.jq_iron_ore_cta_v1_6_all_cycle_short import (
    POST_2024_START,
    POST_PARAMS,
    PRE_PARAMS,
    calculate_adaptive_signal,
    calculate_atr,
    calculate_direction_consistency,
    calculate_drawdown_multiplier,
    calculate_regime_risk_multiplier,
    calculate_risk_scaled_amount,
    calculate_volatility_ratio,
    can_open_replacement,
    get_actual_position,
    select_near_contract,
    select_regime_parameters,
    should_trigger_trailing_stop,
)


def test_all_cycle_short_mode_and_regime_switch():
    assert select_regime_parameters("2023-12-29") == PRE_PARAMS
    assert select_regime_parameters(POST_2024_START) == POST_PARAMS
    assert PRE_PARAMS["allow_short"] is True
    assert POST_PARAMS["allow_short"] is True


def test_direction_consistency_separates_clean_and_choppy_moves():
    rising = list(range(100, 121))
    choppy = [100, 103, 99, 102, 98, 101, 97, 100, 96, 99, 95, 98]
    assert calculate_direction_consistency(rising, 20) > 0.95
    assert calculate_direction_consistency(choppy, 10) < 0.60


def test_all_cycle_downtrend_can_generate_short_signal():
    falling = list(range(220, 90, -1))
    assert calculate_adaptive_signal(falling, PRE_PARAMS) == -1
    assert calculate_adaptive_signal(falling, POST_PARAMS) == -1


def test_regime_gate_and_high_volatility_reduce_risk():
    assert calculate_regime_risk_multiplier(0.20, 1.0, 0.50, POST_PARAMS) == 0.0
    assert calculate_regime_risk_multiplier(0.35, 2.0, 0.80, POST_PARAMS) == 0.5
    assert calculate_regime_risk_multiplier(0.35, 1.2, 0.80, POST_PARAMS) == 1.0


def test_trailing_stop_is_symmetric_for_long_and_short():
    assert should_trigger_trailing_stop(1, 105, 120, 5, 2.5)
    assert not should_trigger_trailing_stop(1, 110, 120, 5, 2.5)
    assert should_trigger_trailing_stop(-1, 115, 90, 5, 2.5)
    assert not should_trigger_trailing_stop(-1, 100, 90, 5, 2.5)


def test_risk_amount_drawdown_atr_volatility_and_rollover_helpers():
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


def test_explicit_short_position_is_not_misread_as_long():
    position = SimpleNamespace(short_amount=3, total_amount=3)
    context = SimpleNamespace(
        portfolio=SimpleNamespace(positions={"I2609.XDCE": position})
    )
    assert get_actual_position(context) == ("I2609.XDCE", -1, 3)
