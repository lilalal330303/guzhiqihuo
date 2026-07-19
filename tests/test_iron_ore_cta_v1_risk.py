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
    bearish = list(range(140, 58, -1))
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
        {
            "high": [101, 103, 102, 106, 104, 109],
            "low": [99, 100, 100, 102, 101, 104],
            "close": closes,
        }
    )
    assert calculate_realized_volatility(closes) > 0
    assert calculate_atr(bars, 3) > 0


def test_near_contract_excludes_expiring_and_non_iron_contracts():
    futures = pd.DataFrame(
        {"end_date": pd.to_datetime(["2026-08-05", "2026-08-20", "2026-08-30"])},
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


def test_replacement_requires_actual_flat_exposure():
    assert can_open_replacement(old_amount=3, close_filled=3, remaining_amount=0)
    assert not can_open_replacement(old_amount=3, close_filled=3, remaining_amount=1)
