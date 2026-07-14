import pandas as pd
import pytest

from quant_lab.research.paper_after_close import aggregate_daily_bars, already_completed, fatal_replay_results, validate_close_window


def test_aggregate_daily_bars_builds_truthful_ohlcv_from_minutes():
    bars = pd.DataFrame([
        {"symbol": "510300.SH", "trade_date": "2026-07-14", "datetime": "2026-07-14 09:31", "open": 4.0, "high": 4.1, "low": 3.9, "close": 4.05, "volume": 10, "amount": 40},
        {"symbol": "510300.SH", "trade_date": "2026-07-14", "datetime": "2026-07-14 15:00", "open": 4.05, "high": 4.2, "low": 4.0, "close": 4.1, "volume": 20, "amount": 82},
    ])

    daily = aggregate_daily_bars(bars)

    assert daily.to_dict("records") == [{
        "symbol": "510300.SH", "trade_date": pd.Timestamp("2026-07-14"),
        "open": 4.0, "high": 4.2, "low": 3.9, "close": 4.1,
        "volume": 30.0, "amount": 122.0,
    }]


def test_validate_close_window_requires_every_symbol_and_strategy_minute():
    required = [1301, 1310, 1440, 1456]
    bars = pd.DataFrame([
        {"symbol": symbol, "minute": minute}
        for symbol in ("510300.SH", "159915.SZ") for minute in required
    ])
    validate_close_window(bars, ["510300.SH", "159915.SZ"], required)

    with pytest.raises(RuntimeError, match="missing required close-window bars"):
        validate_close_window(bars.iloc[:-1], ["510300.SH", "159915.SZ"], required)


def test_validate_close_window_normalizes_adapter_symbols_to_exchange_suffixes():
    bars = pd.DataFrame([{"symbol": "159201.SZ", "minute": 1310}])

    validate_close_window(bars, ["159201"], [1310])


def test_fatal_replay_results_ignores_expected_pre_signal_no_intent_minutes():
    class Result:
        def __init__(self, status, reason):
            self.status, self.reason = status, reason

    results = [Result("blocked", "intent_missing"), Result("executed", None), Result("blocked", "data_missing")]

    assert fatal_replay_results(results) == [results[-1]]


def test_already_completed_only_accepts_matching_successful_trade_date():
    assert already_completed({"trade_date": "2026-07-14", "status": "completed"}, "2026-07-14")
    assert not already_completed({"trade_date": "2026-07-14", "status": "failed"}, "2026-07-14")
    assert not already_completed({"trade_date": "2026-07-13", "status": "completed"}, "2026-07-14")
