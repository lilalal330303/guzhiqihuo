import pandas as pd

from quant_lab.backtest.engine import run_long_only_backtest


def test_run_long_only_backtest_executes_positions_and_records_closed_trade():
    signals = pd.DataFrame(
        {
            "trade_date": pd.date_range("2024-01-01", periods=5, freq="D"),
            "close": [100.0, 110.0, 121.0, 108.9, 108.9],
            "position": [0, 1, 1, 0, 0],
            "trade_signal": [0, 1, 0, -1, 0],
        }
    )

    result = run_long_only_backtest(signals, initial_cash=10_000.0)

    assert result.equity_curve["equity"].round(2).tolist() == [
        10_000.0,
        10_000.0,
        11_000.0,
        9_900.0,
        9_900.0,
    ]
    assert len(result.trades) == 1
    trade = result.trades.iloc[0]
    assert trade["entry_date"] == pd.Timestamp("2024-01-02")
    assert trade["exit_date"] == pd.Timestamp("2024-01-04")
    assert round(trade["return_pct"], 4) == -0.01
