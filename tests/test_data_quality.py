import pandas as pd

from quant_lab.data.quality import detect_split_like_price_jump_events, repair_split_like_price_jumps


def test_repair_split_like_price_jumps_back_adjusts_prior_ohlc():
    prices = pd.DataFrame(
        {
            "symbol": ["AAA", "AAA", "AAA"],
            "trade_date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
            "open": [10.0, 10.0, 5.0],
            "high": [10.0, 10.0, 5.0],
            "low": [10.0, 10.0, 5.0],
            "close": [10.0, 10.0, 5.0],
            "volume": [1000.0, 1000.0, 1000.0],
            "amount": [10000.0, 10000.0, 5000.0],
        }
    )

    repaired = repair_split_like_price_jumps(prices, threshold=0.25)

    assert repaired["close"].tolist() == [5.0, 5.0, 5.0]
    assert repaired["amount"].tolist() == [5000.0, 5000.0, 5000.0]
    assert repaired["volume"].tolist() == [1000.0, 1000.0, 1000.0]


def test_detect_split_like_price_jump_events_records_repair_ratio():
    prices = pd.DataFrame(
        {
            "symbol": ["AAA", "AAA"],
            "trade_date": pd.to_datetime(["2024-01-01", "2024-01-02"]),
            "open": [10.0, 5.0],
            "high": [10.0, 5.0],
            "low": [10.0, 5.0],
            "close": [10.0, 5.0],
            "volume": [1000.0, 1000.0],
            "amount": [10000.0, 5000.0],
        }
    )

    events = detect_split_like_price_jump_events(prices, threshold=0.25)

    assert events[["symbol", "event_date", "previous_close", "current_close", "repair_ratio"]].to_dict("records") == [
        {
            "symbol": "AAA",
            "event_date": pd.Timestamp("2024-01-02"),
            "previous_close": 10.0,
            "current_close": 5.0,
            "repair_ratio": 0.5,
        }
    ]
