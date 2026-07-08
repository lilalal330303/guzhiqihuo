import pandas as pd

from quant_lab.data.repository import DuckDBRepository
from quant_lab.research.wufu_etf_rotation import run_wufu_etf_rotation_experiment
from quant_lab.strategies.wufu_etf_rotation import WufuEtfRotationConfig


def test_run_wufu_experiment_uses_stored_etf_prices_and_persists_results(tmp_path):
    repo = DuckDBRepository(tmp_path / "market.duckdb")
    repo.initialize()
    dates = pd.date_range("2024-01-01", periods=35, freq="D")
    prices = pd.concat(
        [
            _bars("AAA", dates, [10.0 * (1.01**i) for i in range(35)]),
            _bars("BBB", dates, [10.0] * 35),
        ],
        ignore_index=True,
    )
    repo.upsert_prices(prices, source="unit-test")

    result = run_wufu_etf_rotation_experiment(
        repo=repo,
        start_date="2024-01-01",
        end_date="2024-02-04",
        config=WufuEtfRotationConfig(
            etf_pool=["AAA", "BBB"],
            defensive_etf=None,
            max_score_threshold=20.0,
            enable_volume_check=False,
            enable_loss_filter=False,
        ),
        refresh_data=False,
    )

    assert result.run_id
    assert result.metrics["trade_count"] == 1
    assert result.targets.dropna(subset=["target_symbol"]).iloc[0]["target_symbol"] == "AAA"
    assert repo.load_wufu_rotation_trades(result.run_id)["symbol"].tolist() == ["AAA"]


def test_run_wufu_experiment_uses_warmup_history_before_start_date(tmp_path):
    repo = DuckDBRepository(tmp_path / "market.duckdb")
    repo.initialize()
    dates = pd.date_range("2023-12-01", periods=45, freq="D")
    repo.upsert_prices(_bars("AAA", dates, [10.0 * (1.01**i) for i in range(45)]), source="unit-test")

    result = run_wufu_etf_rotation_experiment(
        repo=repo,
        start_date="2024-01-01",
        end_date="2024-01-14",
        config=WufuEtfRotationConfig(
            etf_pool=["AAA"],
            defensive_etf=None,
            max_score_threshold=20.0,
            enable_volume_check=False,
            enable_loss_filter=False,
        ),
        refresh_data=False,
    )

    first_target = result.targets.dropna(subset=["target_symbol"]).iloc[0]
    assert first_target["trade_date"] == pd.Timestamp("2024-01-01")
    assert first_target["target_symbol"] == "AAA"


def test_run_wufu_experiment_excludes_symbols_with_price_jump(tmp_path):
    repo = DuckDBRepository(tmp_path / "market.duckdb")
    repo.initialize()
    dates = pd.date_range("2023-12-01", periods=50, freq="D")
    stable = [10.0 * (1.005**i) for i in range(50)]
    broken = stable[:35] + [stable[34] * 0.45] + [stable[34] * 0.45 * (1.005**i) for i in range(14)]
    repo.upsert_prices(
        pd.concat([_bars("AAA", dates, stable), _bars("BAD", dates, broken)], ignore_index=True),
        source="unit-test",
    )

    result = run_wufu_etf_rotation_experiment(
        repo=repo,
        start_date="2024-01-01",
        end_date="2024-01-19",
        config=WufuEtfRotationConfig(
            etf_pool=["AAA", "BAD"],
            defensive_etf=None,
            max_score_threshold=20.0,
            enable_volume_check=False,
            enable_loss_filter=False,
        ),
        refresh_data=False,
    )

    assert result.data_quality_excluded_symbols == ["BAD"]
    assert "BAD" not in result.targets["target_symbol"].dropna().tolist()


def test_run_wufu_experiment_applies_supplied_weak_states(tmp_path):
    repo = DuckDBRepository(tmp_path / "market.duckdb")
    repo.initialize()
    dates = pd.date_range("2023-12-01", periods=45, freq="D")
    repo.upsert_prices(
        pd.concat(
            [
                _bars("GLB", dates, [10.0 * (1.005**i) for i in range(45)]),
                _bars("CHN", dates, [10.0 * (1.02**i) for i in range(45)]),
            ],
            ignore_index=True,
        ),
        source="unit-test",
    )
    weak_states = pd.DataFrame(
        {
            "trade_date": pd.date_range("2024-01-01", periods=14, freq="D"),
            "is_weak": [True] * 14,
        }
    )

    result = run_wufu_etf_rotation_experiment(
        repo=repo,
        start_date="2024-01-01",
        end_date="2024-01-14",
        config=WufuEtfRotationConfig(
            etf_pool=["GLB", "CHN"],
            global_etf_pool=["GLB"],
            defensive_etf=None,
            max_score_threshold=100.0,
            enable_volume_check=False,
            enable_loss_filter=False,
        ),
        refresh_data=False,
        weak_states=weak_states,
    )

    assert set(result.targets.dropna(subset=["target_symbol"])["target_symbol"]) == {"GLB"}


def test_run_wufu_experiment_can_build_local_weak_states_from_index_prices(tmp_path):
    repo = DuckDBRepository(tmp_path / "market.duckdb")
    repo.initialize()
    dates = pd.date_range("2023-12-01", periods=45, freq="D")
    repo.upsert_prices(
        pd.concat(
            [
                _bars("GLB", dates, [10.0 * (1.005**i) for i in range(45)]),
                _bars("CHN", dates, [10.0 * (1.02**i) for i in range(45)]),
            ],
            ignore_index=True,
        ),
        source="unit-test",
    )
    index_rows = []
    for symbol in ["000300", "399101", "399006", "000510"]:
        closes = [10.0] * 30 + [9.0] * 15
        index_rows.append(_bars(symbol, dates, closes))
    repo.upsert_prices(pd.concat(index_rows, ignore_index=True), source="unit-test-index")

    result = run_wufu_etf_rotation_experiment(
        repo=repo,
        start_date="2024-01-01",
        end_date="2024-01-14",
        config=WufuEtfRotationConfig(
            etf_pool=["GLB", "CHN"],
            global_etf_pool=["GLB"],
            defensive_etf=None,
            max_score_threshold=100.0,
            enable_volume_check=False,
            enable_loss_filter=False,
        ),
        refresh_data=False,
        use_local_weak_states=True,
    )

    assert result.targets.dropna(subset=["target_symbol"])["is_weak"].any()
    assert "CHN" not in result.targets.loc[result.targets["is_weak"], "target_symbol"].dropna().tolist()


def test_run_wufu_experiment_can_use_joinquant_style_weak_lag(tmp_path):
    repo = DuckDBRepository(tmp_path / "market.duckdb")
    repo.initialize()
    dates = pd.date_range("2023-12-01", periods=70, freq="D")
    repo.upsert_prices(_bars("AAA", dates, [10.0 * (1.01**i) for i in range(70)]), source="unit-test")
    for symbol in ["000300", "399101", "399006", "000510"]:
        closes = [10.0] * 60 + [5.0] * 10
        repo.upsert_prices(_bars(symbol, dates, closes), source="unit-test-index")

    result = run_wufu_etf_rotation_experiment(
        repo=repo,
        start_date="2024-01-28",
        end_date="2024-02-03",
        config=WufuEtfRotationConfig(
            etf_pool=["AAA"],
            global_etf_pool=["AAA"],
            defensive_etf=None,
            max_score_threshold=100.0,
            enable_volume_check=False,
            enable_loss_filter=False,
        ),
        refresh_data=False,
        use_local_weak_states=True,
        weak_state_signal_lag_days=1,
    )

    weak_by_date = result.targets.set_index("trade_date")["is_weak"]
    assert bool(weak_by_date.loc[pd.Timestamp("2024-01-30")]) is False
    assert bool(weak_by_date.loc[pd.Timestamp("2024-01-31")]) is True


def _bars(symbol: str, dates: pd.DatetimeIndex, closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": symbol,
            "trade_date": dates,
            "open": closes,
            "high": [value * 1.01 for value in closes],
            "low": [value * 0.99 for value in closes],
            "close": closes,
            "volume": [1000.0] * len(closes),
            "amount": [value * 1000.0 for value in closes],
        }
    )
