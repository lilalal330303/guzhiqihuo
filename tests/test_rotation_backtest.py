import pandas as pd

from quant_lab.backtest.rotation import run_single_slot_rotation_backtest


def test_rotation_backtest_executes_targets_on_next_day_and_records_switches():
    dates = pd.date_range("2024-01-01", periods=5, freq="D")
    prices = pd.DataFrame(
        {
            "symbol": ["AAA"] * 5 + ["BBB"] * 5,
            "trade_date": list(dates) * 2,
            "close": [10.0, 11.0, 12.0, 12.0, 12.0, 20.0, 20.0, 20.0, 22.0, 24.2],
        }
    )
    targets = pd.DataFrame(
        {
            "trade_date": dates,
            "target_symbol": ["AAA", "AAA", "BBB", "BBB", "BBB"],
        }
    )

    result = run_single_slot_rotation_backtest(prices, targets, initial_cash=10_000.0)

    assert result.equity_curve["held_symbol"].tolist() == [None, "AAA", "AAA", "BBB", "BBB"]
    assert result.equity_curve["equity"].round(2).tolist() == [
        10_000.0,
        11_000.0,
        12_000.0,
        13_200.0,
        14_520.0,
    ]
    assert result.trades["symbol"].tolist() == ["AAA", "BBB"]
    assert result.trades.iloc[0]["entry_date"] == pd.Timestamp("2024-01-02")
    assert result.trades.iloc[0]["exit_date"] == pd.Timestamp("2024-01-04")


def test_rotation_backtest_subtracts_commission_and_slippage_on_rebalance_days():
    dates = pd.date_range("2024-01-01", periods=3, freq="D")
    prices = pd.DataFrame(
        {
            "symbol": ["AAA"] * 3,
            "trade_date": dates,
            "close": [10.0, 10.0, 10.0],
        }
    )
    targets = pd.DataFrame({"trade_date": dates, "target_symbol": ["AAA", "AAA", "AAA"]})

    result = run_single_slot_rotation_backtest(
        prices,
        targets,
        initial_cash=10_000.0,
        commission_rate=0.001,
        slippage_rate=0.001,
        min_commission=0.0,
    )

    assert result.equity_curve["equity"].round(2).tolist() == [10_000.0, 9_980.0, 9_980.0]
    assert result.equity_curve["trade_cost"].round(2).tolist() == [0.0, 20.0, 0.0]


def test_rotation_backtest_skips_unpriced_target_execution_day():
    dates = pd.date_range("2024-01-01", periods=4, freq="D")
    prices = pd.DataFrame(
        {
            "symbol": ["AAA", "AAA", "AAA", "AAA", "BBB", "BBB"],
            "trade_date": [*dates, dates[0], dates[3]],
            "close": [10.0, 11.0, 12.0, 13.0, 20.0, 30.0],
        }
    )
    targets = pd.DataFrame({"trade_date": dates, "target_symbol": ["AAA", "BBB", "BBB", "BBB"]})

    result = run_single_slot_rotation_backtest(prices, targets, initial_cash=10_000.0)

    assert result.equity_curve["held_symbol"].tolist() == [None, "AAA", "AAA", "BBB"]
    assert result.trades["entry_price"].notna().all()
    assert result.trades["exit_price"].notna().all()
