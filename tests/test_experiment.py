import pandas as pd

from quant_lab.data.repository import DuckDBRepository
from quant_lab.research.experiment import run_ma_cross_experiment


def test_run_ma_cross_experiment_uses_stored_prices_and_persists_results(tmp_path):
    repo = DuckDBRepository(tmp_path / "market.duckdb")
    repo.initialize()
    prices = pd.DataFrame(
        {
            "symbol": ["000001"] * 8,
            "trade_date": pd.date_range("2024-01-01", periods=8, freq="D"),
            "open": [10.0, 10.0, 10.0, 10.0, 12.0, 13.0, 14.0, 11.0],
            "high": [10.5, 10.5, 10.5, 10.5, 12.5, 13.5, 14.5, 11.5],
            "low": [9.5, 9.5, 9.5, 9.5, 11.5, 12.5, 13.5, 10.5],
            "close": [10.0, 10.0, 10.0, 10.0, 12.0, 13.0, 14.0, 11.0],
            "volume": [1000.0] * 8,
            "amount": [10000.0] * 8,
        }
    )
    repo.upsert_prices(prices, source="unit-test")

    result = run_ma_cross_experiment(
        repo=repo,
        symbol="000001",
        start_date="2024-01-01",
        end_date="2024-01-08",
        short_window=2,
        long_window=4,
        refresh_data=False,
    )

    assert result.run_id
    assert result.metrics["trade_count"] == 1
    assert not result.equity_curve.empty
    assert len(repo.load_trades(result.run_id)) == 1
