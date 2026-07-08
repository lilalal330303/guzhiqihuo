import pandas as pd
import pytest

from quant_lab.strategies.ma_cross import generate_ma_cross_signals


def test_generate_ma_cross_signals_turns_long_when_short_ma_moves_above_long_ma():
    bars = pd.DataFrame(
        {
            "trade_date": pd.date_range("2024-01-01", periods=7, freq="D"),
            "close": [10.0, 10.0, 10.0, 10.0, 14.0, 15.0, 16.0],
        }
    )

    result = generate_ma_cross_signals(bars, short_window=2, long_window=4)

    assert result["signal"].tolist() == [0, 0, 0, 0, 1, 1, 1]
    assert result["position"].tolist() == [0, 0, 0, 0, 0, 1, 1]
    assert result["trade_signal"].tolist() == [0, 0, 0, 0, 0, 1, 0]


def test_generate_ma_cross_signals_rejects_invalid_windows():
    bars = pd.DataFrame(
        {
            "trade_date": pd.date_range("2024-01-01", periods=4, freq="D"),
            "close": [10.0, 11.0, 12.0, 13.0],
        }
    )

    with pytest.raises(ValueError, match="short_window must be smaller"):
        generate_ma_cross_signals(bars, short_window=5, long_window=3)
