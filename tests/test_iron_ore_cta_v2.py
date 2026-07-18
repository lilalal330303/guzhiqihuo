from datetime import date

import pandas as pd

from reports.jq_iron_ore_cta_v2 import (
    calculate_contract_amount,
    can_open_replacement,
    classify_trend,
    select_contract_code,
    transition_direction,
)


PARAMS = {
    "fast_days": 20,
    "trend_days": 60,
    "slope_days": 10,
    "entry_buffer": 0.003,
    "exit_buffer": 0.003,
    "min_spread": 0.002,
    "min_slope": 0.0005,
}


def make_futures(rows):
    return pd.DataFrame(
        [
            {"start_date": start_date, "end_date": end_date}
            for _, start_date, end_date in rows
        ],
        index=[code for code, _, _ in rows],
    )


def test_select_contract_excludes_contracts_inside_roll_window():
    futures = make_futures(
        [
            ("I2405.XDCE", "2024-01-02", "2024-05-10"),
            ("I2406.XDCE", "2024-01-02", "2024-06-10"),
            ("I2407.XDCE", "2024-01-02", "2024-07-10"),
        ]
    )

    assert select_contract_code(futures, date(2024, 5, 6), 8, 1) == "I2407.XDCE"


def test_classify_trend_requires_spread_and_slope_confirmation():
    bullish = pd.Series([100 + i * 0.5 for i in range(90)])
    flat = pd.Series([100.0] * 90)

    assert classify_trend(bullish, PARAMS) == 1
    assert classify_trend(flat, PARAMS) == 0


def test_calculate_contract_amount_is_capped_by_risk_budget():
    params = {
        "contract_multiplier": 100,
        "margin_rate": 0.15,
        "max_margin_usage": 0.45,
        "risk_per_atr": 0.012,
    }

    assert calculate_contract_amount(1_000_000, 1_000_000, 800, 20, params) == 6


def test_short_signal_is_disabled_in_comparison_mode():
    assert transition_direction(0, -1, allow_short=False) == 0
    assert transition_direction(1, -1, allow_short=True) == -1


def test_replacement_requires_actual_flat_position_after_close():
    assert can_open_replacement(old_amount=2, close_filled=2, remaining_amount=0)
    assert not can_open_replacement(old_amount=2, close_filled=2, remaining_amount=1)
    assert not can_open_replacement(old_amount=2, close_filled=0, remaining_amount=2)
