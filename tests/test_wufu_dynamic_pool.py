import pandas as pd

from quant_lab.strategies.wufu_etf_rotation import build_dynamic_etf_pool, dynamic_pool_snapshots


def test_build_dynamic_etf_pool_keeps_most_liquid_etf_per_cleaned_industry():
    metadata = pd.DataFrame(
        {
            "symbol": ["AAA", "BBB", "CCC", "DDD"],
            "name": [
                "\u534e\u590f\u82af\u7247ETF",
                "\u6613\u65b9\u8fbe\u82af\u7247ETF",
                "\u534e\u590f\u6e38\u620fETF",
                "\u4e2d\u8bc1500ETF",
            ],
        }
    )
    prices = pd.DataFrame(
        {
            "symbol": ["AAA", "BBB", "CCC", "DDD"] * 3,
            "trade_date": pd.date_range("2024-01-01", periods=3).repeat(4),
            "amount": [100.0, 200.0, 150.0, 1000.0] * 3,
        }
    )

    pool = build_dynamic_etf_pool(metadata, prices, end_date="2024-01-03", liquidity_threshold=50.0)

    assert pool == ["BBB", "CCC"]


def test_dynamic_pool_snapshots_builds_one_cached_pool_per_trade_date():
    metadata = pd.DataFrame(
        {
            "symbol": ["AAA", "BBB", "CCC"],
            "name": [
                "\u534e\u590f\u82af\u7247ETF",
                "\u6613\u65b9\u8fbe\u82af\u7247ETF",
                "\u534e\u590f\u6e38\u620fETF",
            ],
        }
    )
    prices = pd.DataFrame(
        {
            "symbol": ["AAA", "BBB", "CCC"] * 4,
            "trade_date": pd.date_range("2024-01-01", periods=4).repeat(3),
            "amount": [100.0, 200.0, 150.0] * 4,
        }
    )

    snapshots = dynamic_pool_snapshots(metadata, prices, liquidity_threshold=50.0, lookback_days=2)

    last_day = snapshots[snapshots["trade_date"] == pd.Timestamp("2024-01-04")]
    assert last_day["symbol"].tolist() == ["BBB", "CCC"]
    assert last_day["rank"].tolist() == [1, 2]
