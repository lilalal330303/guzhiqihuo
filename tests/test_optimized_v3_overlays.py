import pandas as pd
import pytest

from quant_lab.research.optimized_v3_overlays import build_crash_exposure_budget


def _index_bars(closes) -> pd.DataFrame:
    return pd.DataFrame({
        "trade_date": pd.date_range("2024-01-01", periods=len(closes), freq="B"),
        "close": closes,
    })


def _budget(closes, **overrides) -> pd.DataFrame:
    parameters = {
        "drawdown_threshold": 0.10,
        "defensive_budget": 0.25,
        "recovery_confirmation_days": 3,
    }
    parameters.update(overrides)
    return build_crash_exposure_budget(_index_bars(closes), **parameters)


def test_drawdown_alone_does_not_trigger_above_ma60():
    result = _budget([100.0] + [80.0] * 58 + [90.0])

    last = result.iloc[-1]
    assert bool(last["below_ma60"]) is False
    assert last["rolling_drawdown"] == pytest.approx(-0.10)
    assert bool(last["severe"]) is False
    assert last["exposure_budget"] == 1.0


def test_below_ma60_alone_does_not_trigger_without_drawdown():
    result = _budget([100.0] * 59 + [99.0])

    last = result.iloc[-1]
    assert bool(last["below_ma60"]) is True
    assert last["rolling_drawdown"] == pytest.approx(-0.01)
    assert bool(last["severe"]) is False


def test_both_crash_conditions_trigger_defensive_budget():
    result = _budget([100.0] * 59 + [80.0])

    last = result.iloc[-1]
    assert bool(last["below_ma60"]) is True
    assert last["rolling_drawdown"] == pytest.approx(-0.20)
    assert bool(last["severe"]) is True
    assert bool(last["defensive"]) is True
    assert last["exposure_budget"] == 0.25


def test_recovery_count_is_exact_and_severe_relapse_resets_it():
    closes = [100.0] * 59 + [80.0, 100.0, 80.0, 100.0, 100.0, 100.0, 100.0]
    result = _budget(closes)

    tail = result.iloc[-7:].reset_index(drop=True)
    assert tail["severe"].tolist() == [True, False, True, False, False, False, False]
    assert tail["defensive"].tolist() == [True, True, True, True, True, True, False]
    assert tail["exposure_budget"].tolist() == [
        0.25, 0.25, 0.25, 0.25, 0.25, 0.25, 1.0,
    ]


def test_prefix_calculations_do_not_change_with_future_rows():
    closes = [100.0] * 59 + [80.0, 100.0, 80.0, 100.0, 100.0, 100.0, 95.0]
    prefix = _budget(closes[:64])
    longer = _budget(closes)

    pd.testing.assert_frame_equal(prefix, longer.iloc[:64].reset_index(drop=True))


def test_output_columns_are_exact_and_pre_history_budget_is_full():
    result = _budget([100.0] * 59)

    assert result.columns.tolist() == [
        "trade_date", "close", "ma60", "rolling_high", "rolling_drawdown",
        "below_ma60", "severe", "defensive", "exposure_budget",
    ]
    assert result["exposure_budget"].eq(1.0).all()


@pytest.mark.parametrize(
    "frame",
    [
        pd.DataFrame({"trade_date": ["2024-01-01", "2024-01-01"], "close": [1.0, 2.0]}),
        pd.DataFrame({"trade_date": ["2024-01-01"], "close": [0.0]}),
        pd.DataFrame({"trade_date": ["2024-01-01"], "close": [float("inf")]}),
    ],
)
def test_invalid_index_bars_are_rejected(frame):
    with pytest.raises(ValueError):
        build_crash_exposure_budget(
            frame,
            drawdown_threshold=0.10,
            defensive_budget=0.25,
            recovery_confirmation_days=3,
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"drawdown_threshold": 0.0},
        {"drawdown_threshold": 1.0},
        {"drawdown_threshold": float("nan")},
        {"defensive_budget": -0.01},
        {"defensive_budget": 1.0},
        {"defensive_budget": float("inf")},
        {"recovery_confirmation_days": 0},
        {"lookback": 59},
    ],
)
def test_invalid_crash_parameters_are_rejected(overrides):
    parameters = {
        "drawdown_threshold": 0.10,
        "defensive_budget": 0.25,
        "recovery_confirmation_days": 3,
        "lookback": 60,
    }
    parameters.update(overrides)
    with pytest.raises(ValueError):
        build_crash_exposure_budget(_index_bars([100.0]), **parameters)
