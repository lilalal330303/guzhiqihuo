import pandas as pd

from quant_lab.backtest.portfolio import (
    DailyRiskConfig,
    CostModel,
    detect_macd_divergence_dates,
    run_portfolio_backtest,
)


def _bars(high_limit=11.0):
    return pd.DataFrame({
        "symbol": ["000001"] * 3,
        "trade_date": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]),
        "open": [9.8, 10.0, 10.5], "close": [9.9, 10.4, 10.6],
        "high_limit": [10.8, high_limit, 11.5], "low_limit": [8.8, 9.0, 9.4],
        "paused": [False, False, False],
    })


def test_signal_on_t_executes_at_next_open_with_lot_and_costs():
    targets = pd.DataFrame({
        "signal_date": pd.to_datetime(["2024-01-02"]),
        "symbol": ["000001"], "target_weight": [1.0],
    })
    result = run_portfolio_backtest(_bars(), targets, initial_cash=10_000.0)
    fill = result.trades.iloc[0]
    assert fill["trade_date"] == pd.Timestamp("2024-01-03")
    assert fill["raw_price"] == 10.0
    assert fill["quantity"] == 900
    assert fill["fee"] == 5.0
    assert fill["fill_price"] == 10.002


def test_buy_at_upper_limit_is_rejected():
    targets = pd.DataFrame({
        "signal_date": pd.to_datetime(["2024-01-02"]),
        "symbol": ["000001"], "target_weight": [1.0],
    })
    bars = _bars(high_limit=10.0)
    result = run_portfolio_backtest(bars, targets, initial_cash=10_000.0)
    assert result.trades.empty
    assert result.rejections.loc[0, "reason"] == "upper_limit"


def test_cost_model_charges_stamp_tax_only_on_sell():
    costs = CostModel()
    assert costs.fee(1000.0, "buy") == 5.0
    assert costs.fee(10_000.0, "sell") == 10.0


def test_equity_before_signal_execution_does_not_include_future_holding():
    targets = pd.DataFrame({
        "signal_date": pd.to_datetime(["2024-01-02"]),
        "symbol": ["000001"], "target_weight": [1.0],
    })
    result = run_portfolio_backtest(_bars(), targets, initial_cash=10_000.0)
    assert result.equity_curve.loc[0, "equity"] == 10_000.0


def test_sell_trade_reports_realized_return_from_fifo_cost_basis():
    bars = pd.DataFrame({
        "symbol": ["000001"] * 4,
        "trade_date": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]),
        "open": [10.0, 10.0, 11.0, 11.0], "close": [10.0, 10.5, 11.0, 11.0],
        "high_limit": [11.0, 11.0, 12.0, 12.0], "low_limit": [9.0, 9.0, 9.0, 9.0],
        "paused": [False] * 4,
    })
    targets = pd.DataFrame({"signal_date": pd.to_datetime(["2024-01-02", "2024-01-03"]),
                            "symbol": ["000001", "000001"], "target_weight": [1.0, 0.0]})
    result = run_portfolio_backtest(bars, targets, initial_cash=10_000.0)
    sell = result.trades.loc[result.trades["side"] == "sell"].iloc[0]
    assert sell["return_pct"] > 0


def test_daily_fixed_stop_signal_executes_at_next_open():
    bars = pd.DataFrame({
        "symbol": ["000001"] * 4,
        "trade_date": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]),
        "open": [10.0, 10.0, 9.0, 9.0], "close": [10.0, 8.9, 9.0, 9.0],
        "high": [10.1, 10.1, 9.1, 9.1], "low": [9.9, 8.8, 8.9, 8.9],
        "high_limit": [11.0] * 4, "low_limit": [8.0] * 4,
        "paused": [False] * 4, "is_st": [False] * 4,
    })
    targets = pd.DataFrame({
        "signal_date": pd.to_datetime(["2024-01-02"]),
        "symbol": ["000001"], "target_weight": [1.0],
    })

    result = run_portfolio_backtest(
        bars,
        targets,
        initial_cash=10_000.0,
        risk=DailyRiskConfig(enable_atr=False, enable_market_stop=False, enable_divergence=False),
    )

    sell = result.trades.loc[result.trades["side"].eq("sell")].iloc[0]
    assert sell["trade_date"] == pd.Timestamp("2024-01-04")
    assert sell["reason"] == "fixed_stop"


def test_daily_market_stop_uses_close_signal_and_next_open_fill():
    bars = pd.DataFrame({
        "symbol": ["000001"] * 4,
        "trade_date": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]),
        "open": [10.0] * 4, "close": [10.0] * 4,
        "high": [10.1] * 4, "low": [9.9] * 4,
        "high_limit": [11.0] * 4, "low_limit": [9.0] * 4,
        "paused": [False] * 4, "is_st": [False] * 4,
    })
    targets = pd.DataFrame({
        "signal_date": pd.to_datetime(["2024-01-02"]),
        "symbol": ["000001"], "target_weight": [1.0],
    })
    market = pd.DataFrame({
        "trade_date": pd.to_datetime(["2024-01-03"]), "down_ratio": [-0.06]
    })

    result = run_portfolio_backtest(
        bars, targets, initial_cash=10_000.0,
        risk=DailyRiskConfig(enable_fixed_stop=False, enable_atr=False, enable_divergence=False),
        market_daily=market,
    )

    sell = result.trades.loc[result.trades["side"].eq("sell")].iloc[0]
    assert sell["trade_date"] == pd.Timestamp("2024-01-04")
    assert sell["reason"] == "market_stop"


def test_daily_crowding_clear_uses_previous_close_information():
    bars = pd.DataFrame({
        "symbol": ["000001"] * 4,
        "trade_date": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]),
        "open": [10.0] * 4, "close": [10.0] * 4,
        "high": [10.1] * 4, "low": [9.9] * 4,
        "high_limit": [11.0] * 4, "low_limit": [9.0] * 4,
        "paused": [False] * 4, "is_st": [False] * 4,
    })
    targets = pd.DataFrame({
        "signal_date": pd.to_datetime(["2024-01-02"]),
        "symbol": ["000001"], "target_weight": [1.0],
    })
    crowding = pd.DataFrame({
        "trade_date": pd.to_datetime(["2024-01-03"]), "concentration": [0.49]
    })

    result = run_portfolio_backtest(
        bars, targets, initial_cash=10_000.0,
        risk=DailyRiskConfig(
            enable_fixed_stop=False, enable_atr=False, enable_market_stop=False,
            enable_divergence=False,
        ),
        crowding_daily=crowding,
    )

    sell = result.trades.loc[result.trades["side"].eq("sell")].iloc[0]
    assert sell["trade_date"] == pd.Timestamp("2024-01-04")
    assert sell["reason"] == "crowding_clear"


def test_tminus1_exposure_budget_reduces_positions_at_next_open():
    bars = pd.DataFrame({
        "symbol": ["000001"] * 4,
        "trade_date": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]),
        "open": [10.0] * 4, "close": [10.0] * 4,
        "high": [10.1] * 4, "low": [9.9] * 4,
        "high_limit": [11.0] * 4, "low_limit": [9.0] * 4,
        "paused": [False] * 4, "is_st": [False] * 4,
    })
    targets = pd.DataFrame({
        "signal_date": pd.to_datetime(["2024-01-02"]),
        "symbol": ["000001"], "target_weight": [1.0],
    })
    budgets = pd.DataFrame({
        "trade_date": pd.to_datetime(["2024-01-03"]), "exposure_budget": [0.25]
    })

    result = run_portfolio_backtest(
        bars, targets, initial_cash=10_000.0,
        risk=DailyRiskConfig(
            enable_fixed_stop=False, enable_atr=False, enable_market_stop=False,
            enable_divergence=False, enable_crowding_daily=False,
        ),
        exposure_budget_daily=budgets,
    )

    sell = result.trades.loc[result.trades["side"].eq("sell")].iloc[0]
    assert sell["trade_date"] == pd.Timestamp("2024-01-04")
    assert sell["reason"] == "risk_budget_reduce"
    remaining = result.positions.loc[
        result.positions["trade_date"].eq(pd.Timestamp("2024-01-04")), "quantity"
    ].sum()
    assert remaining <= 300


def test_fixed_stop_starts_two_trading_day_buy_cooldown():
    bars = pd.DataFrame({
        "symbol": ["000001"] * 5,
        "trade_date": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08"]),
        "open": [10.0, 10.0, 9.0, 9.0, 9.0], "close": [10.0, 8.9, 9.0, 9.0, 9.0],
        "high": [10.1] * 5, "low": [8.8] * 5,
        "high_limit": [11.0] * 5, "low_limit": [8.0] * 5,
        "paused": [False] * 5, "is_st": [False] * 5,
    })
    targets = pd.DataFrame({
        "signal_date": pd.to_datetime(["2024-01-02", "2024-01-03"]),
        "symbol": ["000001", "000001"], "target_weight": [1.0, 1.0],
    })

    result = run_portfolio_backtest(
        bars, targets, initial_cash=10_000.0,
        risk=DailyRiskConfig(enable_atr=False, enable_market_stop=False, enable_divergence=False),
    )

    assert len(result.trades.loc[result.trades["side"].eq("buy")]) == 1
    assert "cooldown" in result.rejections["reason"].tolist()


def test_macd_divergence_needs_full_245_day_history():
    index_bars = pd.DataFrame({
        "trade_date": pd.date_range("2024-01-01", periods=100, freq="B"),
        "close": range(100, 200),
    })
    assert detect_macd_divergence_dates(index_bars) == set()


def test_repaired_cost_protection_remembers_prior_profit_band():
    bars = pd.DataFrame({
        "symbol": ["000001"] * 5,
        "trade_date": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08"]),
        "open": [10.0, 10.0, 13.0, 10.5, 10.5], "close": [10.0, 13.2, 10.5, 10.5, 10.5],
        "high": [10.1, 13.3, 13.1, 10.6, 10.6], "low": [9.9, 9.9, 10.4, 10.4, 10.4],
        "high_limit": [14.0] * 5, "low_limit": [8.0] * 5,
        "paused": [False] * 5, "is_st": [False] * 5,
    })
    targets = pd.DataFrame({
        "signal_date": pd.to_datetime(["2024-01-02"]),
        "symbol": ["000001"], "target_weight": [1.0],
    })

    result = run_portfolio_backtest(
        bars, targets, initial_cash=10_000.0,
        risk=DailyRiskConfig(
            enable_fixed_stop=False, enable_atr=False, enable_market_stop=False,
            enable_divergence=False, repair_cost_protection=True,
        ),
    )

    sell = result.trades.loc[result.trades["side"].eq("sell")].iloc[0]
    assert sell["trade_date"] == pd.Timestamp("2024-01-05")
    assert sell["reason"] == "cost_protection"


def test_joinquant_buy_new_only_does_not_resize_existing_target():
    bars = pd.DataFrame({
        "symbol": ["000001"] * 4,
        "trade_date": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]),
        "open": [10.0] * 4, "close": [10.0] * 4,
        "high_limit": [11.0] * 4, "low_limit": [9.0] * 4,
        "paused": [False] * 4, "is_st": [False] * 4,
    })
    targets = pd.DataFrame({
        "signal_date": pd.to_datetime(["2024-01-02", "2024-01-03"]),
        "symbol": ["000001", "000001"], "target_weight": [1.0, 0.5],
    })

    result = run_portfolio_backtest(
        bars, targets, initial_cash=10_000.0, buy_new_only=True
    )

    assert result.trades["side"].tolist() == ["buy"]
    assert result.positions.groupby("trade_date")["quantity"].sum().max() == 900
