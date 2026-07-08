import pandas as pd

from quant_lab.data.repository import DuckDBRepository


def test_repository_writes_prices_and_backtest_results(tmp_path):
    repo = DuckDBRepository(tmp_path / "market.duckdb")
    repo.initialize()
    prices = pd.DataFrame(
        {
            "symbol": ["000001", "000001"],
            "trade_date": pd.to_datetime(["2024-01-02", "2024-01-03"]),
            "open": [10.0, 10.5],
            "high": [11.0, 11.5],
            "low": [9.8, 10.2],
            "close": [10.8, 11.2],
            "volume": [1000.0, 1200.0],
            "amount": [10_000.0, 13_000.0],
        }
    )
    trades = pd.DataFrame(
        {
            "entry_date": pd.to_datetime(["2024-01-02"]),
            "exit_date": pd.to_datetime(["2024-01-03"]),
            "entry_price": [10.8],
            "exit_price": [11.2],
            "return_pct": [0.037037],
        }
    )

    repo.upsert_prices(prices, source="unit-test")
    run_id = repo.save_backtest_run(
        symbol="000001",
        start_date="2024-01-02",
        end_date="2024-01-03",
        short_window=2,
        long_window=3,
        metrics={"total_return": 0.03},
        trades=trades,
    )

    loaded = repo.load_prices("000001", "2024-01-01", "2024-01-31")
    loaded_trades = repo.load_trades(run_id)

    assert loaded["close"].tolist() == [10.8, 11.2]
    assert loaded["source"].unique().tolist() == ["unit-test"]
    assert loaded_trades["return_pct"].round(6).tolist() == [0.037037]


def test_repository_writes_wufu_rotation_experiment(tmp_path):
    repo = DuckDBRepository(tmp_path / "market.duckdb")
    repo.initialize()
    trades = pd.DataFrame(
        {
            "symbol": ["510300"],
            "entry_date": pd.to_datetime(["2024-01-02"]),
            "exit_date": pd.to_datetime(["2024-01-03"]),
            "entry_price": [3.0],
            "exit_price": [3.3],
            "return_pct": [0.1],
        }
    )

    run_id = repo.save_wufu_rotation_run(
        start_date="2024-01-01",
        end_date="2024-01-31",
        hypothesis="ETF momentum rotation",
        params={"lookback_days": 25},
        metrics={"total_return": 0.1},
        trades=trades,
        next_research_note="Compare wider ETF pool.",
    )

    loaded = repo.load_wufu_rotation_trades(run_id)

    assert run_id
    assert loaded["symbol"].tolist() == ["510300"]
    assert loaded["return_pct"].tolist() == [0.1]


def test_repository_caches_dynamic_pool_and_targets(tmp_path):
    repo = DuckDBRepository(tmp_path / "market.duckdb")
    repo.initialize()
    pool = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2024-01-02", "2024-01-02"]),
            "symbol": ["510300", "159915"],
            "rank": [1, 2],
            "industry_key": ["沪深", "创业"],
            "avg_amount": [2000.0, 1000.0],
        }
    )
    targets = pd.DataFrame(
        {
            "cache_key": ["unit", "unit"],
            "trade_date": pd.to_datetime(["2024-01-02", "2024-01-03"]),
            "target_symbol": ["510300", "159915"],
            "is_weak": [False, True],
            "candidates_json": ['[{"symbol":"510300"}]', '[{"symbol":"159915"}]'],
        }
    )

    repo.save_dynamic_pool_snapshot(pool, source="unit-test")
    repo.save_wufu_target_cache(targets)

    loaded_pool = repo.load_dynamic_pool_snapshot("2024-01-02")
    loaded_pool_range = repo.load_dynamic_pool_snapshots("2024-01-01", "2024-01-31")
    loaded_targets = repo.load_wufu_target_cache("unit", "2024-01-01", "2024-01-31")

    assert loaded_pool["symbol"].tolist() == ["510300", "159915"]
    assert loaded_pool_range["symbol"].tolist() == ["510300", "159915"]
    assert loaded_targets["target_symbol"].tolist() == ["510300", "159915"]


def test_repository_saves_etf_universe_snapshots(tmp_path):
    repo = DuckDBRepository(tmp_path / "market.duckdb")
    repo.initialize()
    snapshots = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2024-01-02", "2024-01-02", "2024-01-03"]),
            "symbol": ["510300", "159915", "510300"],
            "name": ["沪深300ETF", "创业板ETF", "沪深300ETF"],
            "is_active": [True, True, True],
        }
    )

    repo.replace_etf_universe_snapshots(snapshots, source="unit-test")
    loaded = repo.load_etf_universe_snapshots("2024-01-02", "2024-01-03")

    assert loaded["symbol"].tolist() == ["159915", "510300", "510300"]
    assert loaded["source"].unique().tolist() == ["unit-test"]


def test_repository_saves_price_repair_events(tmp_path):
    repo = DuckDBRepository(tmp_path / "market.duckdb")
    repo.initialize()
    events = pd.DataFrame(
        {
            "symbol": ["510300"],
            "event_date": pd.to_datetime(["2024-01-03"]),
            "previous_trade_date": pd.to_datetime(["2024-01-02"]),
            "previous_close": [10.0],
            "current_close": [5.0],
            "daily_return": [-0.5],
            "repair_ratio": [0.5],
        }
    )

    repo.save_price_repair_events(events, source="unit-repair")
    loaded = repo.load_price_repair_events("2024-01-01", "2024-01-31")

    assert loaded["symbol"].tolist() == ["510300"]
    assert loaded["repair_ratio"].tolist() == [0.5]
    assert loaded["source"].tolist() == ["unit-repair"]
