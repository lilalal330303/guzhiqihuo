import pandas as pd

from quant_lab.backtest.iron_ore_cta import (
    IronOreBacktestConfig,
    build_iron_ore_signal_snapshot,
    run_iron_ore_v16_backtest,
    select_near_contract_local,
)


def test_select_near_contract_uses_point_in_time_eligibility():
    universe = pd.DataFrame(
        {
            "asof_date": ["2024-01-02"] * 3,
            "symbol": ["I2405.XDCE", "I2406.XDCE", "IC2405.CCFX"],
            "list_date": ["2023-01-01", "2024-01-01", "2023-01-01"],
            "end_date": ["2024-05-10", "2024-06-10", "2024-05-10"],
        }
    )
    assert (
        select_near_contract_local(universe, "2024-04-30", 8)
        == "I2405.XDCE"
    )
    assert select_near_contract_local(universe, "2024-05-05", 8) == "I2406.XDCE"


def _synthetic_downtrend():
    dates = pd.bdate_range("2023-06-01", periods=360)
    close = 320.0 - pd.Series(range(len(dates)), dtype=float) * 0.40
    main = pd.DataFrame(
        {
            "symbol": "I8888.XDCE",
            "trade_date": dates,
            "open": close + 1.0,
            "high": close + 2.0,
            "low": close - 2.0,
            "close": close,
            "volume": 1000.0,
            "amount": close * 1000.0,
            "open_interest": 500.0,
        }
    )
    contract = main.copy()
    contract["symbol"] = "I2405.XDCE"
    contract["open"] = contract["close"] + 0.5
    contracts = pd.DataFrame(
        {
            "symbol": ["I2405.XDCE"],
            "list_date": ["2023-01-01"],
            "end_date": ["2025-05-10"],
        }
    )
    universe = pd.DataFrame(
        {
            "asof_date": dates,
            "symbol": "I2405.XDCE",
            "list_date": "2023-01-01",
            "end_date": "2025-05-10",
        }
    )
    return main, contract, contracts, universe


def test_local_backtest_executes_short_on_next_open_without_future_data():
    main, contract, contracts, universe = _synthetic_downtrend()
    result = run_iron_ore_v16_backtest(
        main,
        contract,
        contracts,
        universe,
        IronOreBacktestConfig(
            start_date="2024-01-02",
            end_date="2024-12-31",
            initial_cash=1_000_000.0,
        ),
    )

    assert not result.signals.empty
    assert (result.signals["signal"] == -1).any()
    assert not result.trades.empty
    short_entries = result.trades[result.trades["side"] == "short_entry"]
    assert not short_entries.empty
    assert (
        pd.to_datetime(short_entries["execution_date"])
        > pd.to_datetime(short_entries["signal_date"])
    ).all()
    assert set(["equity", "cash", "market_value"]).issubset(result.equity_curve.columns)
    assert "annualized_return" in result.metrics


def test_local_backtest_has_no_signal_rows_after_requested_end_date():
    main, contract, contracts, universe = _synthetic_downtrend()
    result = run_iron_ore_v16_backtest(
        main,
        contract,
        contracts,
        universe,
        IronOreBacktestConfig(start_date="2024-01-02", end_date="2024-03-29"),
    )
    assert pd.to_datetime(result.signals["signal_date"]).max() <= pd.Timestamp("2024-03-29")
    assert pd.to_datetime(result.equity_curve["trade_date"]).max() <= pd.Timestamp("2024-03-29")


def test_signal_snapshot_does_not_change_when_future_bars_are_modified():
    main, _, _, _ = _synthetic_downtrend()
    cutoff = pd.Timestamp("2024-01-31")
    changed = main.copy()
    changed.loc[pd.to_datetime(changed["trade_date"]) > cutoff, "close"] *= 4.0
    changed.loc[pd.to_datetime(changed["trade_date"]) > cutoff, "open"] *= 4.0
    original = build_iron_ore_signal_snapshot(main, cutoff)
    modified = build_iron_ore_signal_snapshot(changed, cutoff)
    assert original["signal"] == modified["signal"]
    assert original["efficiency_ratio"] == modified["efficiency_ratio"]
