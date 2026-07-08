import pandas as pd

from quant_lab.backtest.metrics import calculate_metrics


def test_calculate_metrics_from_equity_curve_and_trades():
    equity_curve = pd.DataFrame(
        {
            "trade_date": pd.date_range("2024-01-01", periods=4, freq="D"),
            "equity": [100.0, 120.0, 90.0, 110.0],
        }
    )
    trades = pd.DataFrame({"return_pct": [0.10, -0.05, 0.02]})

    metrics = calculate_metrics(equity_curve, trades)

    assert round(metrics["total_return"], 4) == 0.10
    assert round(metrics["max_drawdown"], 4) == -0.25
    assert metrics["trade_count"] == 3
    assert round(metrics["win_rate"], 4) == 0.6667
    assert metrics["annualized_return"] > 100
