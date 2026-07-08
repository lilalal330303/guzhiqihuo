import pandas as pd

from quant_lab.backtest.wufu_intraday import (
    WufuIntradayTimingConfig,
    run_wufu_intraday_proxy_backtest,
    run_wufu_intraday_real_backtest,
)


def test_wufu_intraday_proxy_uses_trend_and_stop_loss_paths():
    prices = pd.DataFrame(
        [
            {"symbol": "AAA", "trade_date": "2024-01-01", "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.4, "volume": 1, "amount": 1},
            {"symbol": "AAA", "trade_date": "2024-01-02", "open": 10.4, "high": 10.6, "low": 9.0, "close": 9.5, "volume": 1, "amount": 1},
            {"symbol": "AAA", "trade_date": "2024-01-03", "open": 9.5, "high": 9.8, "low": 8.9, "close": 9.7, "volume": 1, "amount": 1},
        ]
    )
    targets = pd.DataFrame(
        [
            {"trade_date": "2024-01-01", "target_symbol": "AAA"},
            {"trade_date": "2024-01-02", "target_symbol": "AAA"},
            {"trade_date": "2024-01-03", "target_symbol": "AAA"},
        ]
    )

    result = run_wufu_intraday_proxy_backtest(prices, targets)
    trades = result["trades"]

    assert trades["action"].tolist() == ["buy", "stop_loss_sell", "buy"]
    assert trades.loc[0, "entry_mode"] == "force"
    assert trades.loc[2, "entry_mode"] == "trend"


def test_wufu_intraday_real_uses_minute_trend_and_stop_loss():
    prices = pd.DataFrame(
        [
            {"symbol": "AAA", "trade_date": "2024-01-01", "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.4, "volume": 1, "amount": 1},
            {"symbol": "AAA", "trade_date": "2024-01-02", "open": 10.4, "high": 11.5, "low": 10.2, "close": 11.2, "volume": 1, "amount": 1},
            {"symbol": "AAA", "trade_date": "2024-01-03", "open": 11.2, "high": 11.3, "low": 9.8, "close": 10.0, "volume": 1, "amount": 1},
        ]
    )
    targets = pd.DataFrame(
        [
            {"trade_date": "2024-01-01", "target_symbol": "AAA"},
            {"trade_date": "2024-01-02", "target_symbol": "AAA"},
            {"trade_date": "2024-01-03", "target_symbol": "AAA"},
        ]
    )
    minute_rows = []
    for i in range(30):
        minute_rows.append(
            {
                "symbol": "AAA.SH",
                "trade_date": "2024-01-02",
                "minute": 1242 + i,
                "close": 10.0 + i * 0.02,
                "low": 10.0 + i * 0.02,
            }
        )
    minute_rows.append({"symbol": "AAA.SH", "trade_date": "2024-01-02", "minute": 1311, "close": 10.7, "low": 10.7})
    minute_rows.append({"symbol": "AAA.SH", "trade_date": "2024-01-03", "minute": 941, "close": 10.1, "low": 9.0})

    result = run_wufu_intraday_real_backtest(prices, targets, pd.DataFrame(minute_rows))
    trades = result["trades"]

    assert trades["action"].tolist() == ["buy", "stop_loss_sell", "buy"]
    assert trades.loc[0, "entry_mode"] == "trend_real"
    assert trades.loc[0, "minute"] == 1311
    assert trades.loc[1, "execution_mode"] == "stop_real"


def test_wufu_intraday_real_uses_configured_initial_entry_minute():
    prices = pd.DataFrame(
        [
            {"symbol": "AAA", "trade_date": "2024-01-01", "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "volume": 1, "amount": 1},
            {"symbol": "AAA", "trade_date": "2024-01-02", "open": 10.0, "high": 10.4, "low": 10.0, "close": 10.3, "volume": 1, "amount": 1},
        ]
    )
    targets = pd.DataFrame(
        [
            {"trade_date": "2024-01-01", "target_symbol": "AAA"},
            {"trade_date": "2024-01-02", "target_symbol": "AAA"},
        ]
    )
    minute_rows = pd.DataFrame(
        [
            {"symbol": "AAA.SH", "trade_date": "2024-01-02", "minute": 1311, "close": 10.10, "low": 10.10},
            {"symbol": "AAA.SH", "trade_date": "2024-01-02", "minute": 1320, "close": 10.20, "low": 10.20},
        ]
    )

    result = run_wufu_intraday_real_backtest(
        prices,
        targets,
        minute_rows,
        WufuIntradayTimingConfig(
            trend_check_minutes=(),
            initial_entry_minute=1320,
            force_buy_minute=1455,
        ),
    )

    trades = result["trades"]
    assert trades.loc[0, "entry_mode"] == "initial_real"
    assert trades.loc[0, "minute"] == 1320
    assert trades.loc[0, "price"] > 10.20


def test_wufu_intraday_real_uses_configured_stop_loss_windows():
    prices = pd.DataFrame(
        [
            {"symbol": "AAA", "trade_date": "2024-01-01", "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "volume": 1, "amount": 1},
            {"symbol": "AAA", "trade_date": "2024-01-02", "open": 10.0, "high": 10.5, "low": 10.0, "close": 10.4, "volume": 1, "amount": 1},
            {"symbol": "AAA", "trade_date": "2024-01-03", "open": 10.4, "high": 10.4, "low": 9.0, "close": 10.2, "volume": 1, "amount": 1},
        ]
    )
    targets = pd.DataFrame(
        [
            {"trade_date": "2024-01-01", "target_symbol": "AAA"},
            {"trade_date": "2024-01-02", "target_symbol": "AAA"},
            {"trade_date": "2024-01-03", "target_symbol": "AAA"},
        ]
    )
    minute_rows = pd.DataFrame(
        [
            {"symbol": "AAA.SH", "trade_date": "2024-01-02", "minute": 1311, "close": 10.0, "low": 10.0},
            {"symbol": "AAA.SH", "trade_date": "2024-01-03", "minute": 941, "close": 10.1, "low": 9.0},
        ]
    )

    blocked = run_wufu_intraday_real_backtest(
        prices,
        targets,
        minute_rows,
        WufuIntradayTimingConfig(
            trend_check_minutes=(),
            force_buy_minute=1311,
            fixed_stop_loss_threshold=0.97,
            stop_loss_windows=((1301, 1456),),
        ),
    )
    allowed = run_wufu_intraday_real_backtest(
        prices,
        targets,
        minute_rows,
        WufuIntradayTimingConfig(
            trend_check_minutes=(),
            force_buy_minute=1311,
            fixed_stop_loss_threshold=0.97,
            stop_loss_windows=((941, 1028),),
        ),
    )

    assert "stop_loss_sell" not in blocked["trades"]["action"].tolist()
    assert "stop_loss_sell" in allowed["trades"]["action"].tolist()
