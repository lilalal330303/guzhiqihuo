import pandas as pd

from quant_lab.strategies.wufu_etf_rotation import (
    DEFAULT_CHINA_ETF_POOL,
    DEFAULT_GLOBAL_ETF_POOL,
    WufuEtfRotationConfig,
    calculate_joinquant_liquidity_thresholds,
    calculate_momentum_score,
    dynamic_pool_snapshots,
    generate_wufu_targets,
)


def test_calculate_momentum_score_rewards_smooth_uptrend():
    smooth_up = pd.Series([10.0 * (1.01**i) for i in range(31)])
    choppy = pd.Series([10.0, 12.0, 9.0, 13.0, 8.0, 14.0] * 6)

    smooth_score = calculate_momentum_score(smooth_up, lookback_days=25)
    choppy_score = calculate_momentum_score(choppy, lookback_days=25)

    assert smooth_score is not None
    assert choppy_score is not None
    assert smooth_score.momentum_score > choppy_score.momentum_score
    assert smooth_score.r_squared > 0.99


def test_default_fixed_pool_matches_joinquant_script_size():
    assert len(DEFAULT_GLOBAL_ETF_POOL) == 17
    assert len(DEFAULT_CHINA_ETF_POOL) == 97
    assert len(set(DEFAULT_GLOBAL_ETF_POOL + DEFAULT_CHINA_ETF_POOL)) == 114


def test_generate_wufu_targets_selects_top_filtered_etf_without_future_data():
    dates = pd.date_range("2024-01-01", periods=35, freq="D")
    prices = pd.concat(
        [
            _bars("AAA", dates, [10.0 * (1.01**i) for i in range(35)], 1000.0),
            _bars("BBB", dates, [10.0] * 35, 1000.0),
        ],
        ignore_index=True,
    )

    targets = generate_wufu_targets(
        prices,
        config=WufuEtfRotationConfig(
            etf_pool=["AAA", "BBB"],
            lookback_days=25,
            holdings_num=1,
            max_score_threshold=20.0,
            enable_volume_check=False,
            enable_loss_filter=False,
        ),
    )

    ready = targets.dropna(subset=["target_symbol"])
    assert not ready.empty
    assert ready.iloc[0]["trade_date"] == dates[25]
    assert ready.iloc[0]["target_symbol"] == "AAA"
    assert ready.iloc[0]["rank"] == 1
    assert "candidates_json" in targets.columns


def test_generate_wufu_targets_uses_daily_dynamic_snapshot_pool():
    dates = pd.date_range("2024-01-01", periods=35, freq="D")
    prices = pd.concat(
        [
            _bars("AAA", dates, [10.0] * 35, 1000.0),
            _bars("DYN", dates, [10.0 * (1.01**i) for i in range(35)], 1000.0),
        ],
        ignore_index=True,
    )
    snapshots = pd.DataFrame(
        {
            "trade_date": [dates[25]],
            "symbol": ["DYN"],
            "rank": [1],
            "industry_key": ["dynamic"],
            "avg_amount": [1000.0],
        }
    )

    targets = generate_wufu_targets(
        prices,
        config=WufuEtfRotationConfig(
            etf_pool=["AAA"],
            lookback_days=25,
            holdings_num=1,
            max_score_threshold=20.0,
            enable_volume_check=False,
            enable_loss_filter=False,
        ),
        dynamic_snapshots=snapshots,
    )

    first_ready = targets.dropna(subset=["target_symbol"]).iloc[0]
    assert first_ready["trade_date"] == dates[25]
    assert first_ready["target_symbol"] == "DYN"


def test_joinquant_liquidity_threshold_uses_previous_three_days_only():
    prices = pd.DataFrame(
        {
            "symbol": ["AAA", "BBB"] * 4,
            "trade_date": list(pd.date_range("2024-01-01", periods=4, freq="D").repeat(2)),
            "amount": [100.0, 300.0, 200.0, 400.0, 300.0, 500.0, 999999.0, 999999.0],
        }
    )

    thresholds = calculate_joinquant_liquidity_thresholds(prices, divisor=2.0, fallback=1.0)

    day4 = thresholds[pd.to_datetime(thresholds["trade_date"]) == pd.Timestamp("2024-01-04")].iloc[0]
    assert day4["liquidity_threshold"] == 300.0


def test_dynamic_pool_snapshots_accepts_daily_liquidity_thresholds():
    dates = pd.date_range("2024-01-01", periods=4, freq="D")
    metadata = pd.DataFrame({"symbol": ["AAA", "BBB"], "name": ["半导体ETF", "医疗ETF"]})
    prices = pd.concat(
        [
            _bars("AAA", dates, [10, 10, 10, 10], 100.0),
            _bars("BBB", dates, [10, 10, 10, 10], 1000.0),
        ],
        ignore_index=True,
    )
    thresholds = pd.DataFrame(
        {
            "trade_date": dates,
            "liquidity_threshold": [0.0, 0.0, 20000.0, 20000.0],
        }
    )

    snapshots = dynamic_pool_snapshots(metadata, prices, thresholds, lookback_days=1)

    early = snapshots[pd.to_datetime(snapshots["trade_date"]) == dates[1]]
    late = snapshots[pd.to_datetime(snapshots["trade_date"]) == dates[3]]
    assert set(early["symbol"]) == {"AAA", "BBB"}
    assert late["symbol"].tolist() == []


def _bars(symbol: str, dates: pd.DatetimeIndex, closes: list[float], volume: float) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": symbol,
            "trade_date": dates,
            "open": closes,
            "high": [value * 1.01 for value in closes],
            "low": [value * 0.99 for value in closes],
            "close": closes,
            "volume": [volume] * len(closes),
            "amount": [value * volume for value in closes],
        }
    )
