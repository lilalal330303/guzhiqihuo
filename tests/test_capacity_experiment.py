import pandas as pd

from quant_lab.research.capacity_experiment import (
    default_etf_capacity_grid,
    run_capacity_grid_experiment,
)


def test_default_etf_capacity_grid_contains_expected_dimensions():
    grid = default_etf_capacity_grid()

    assert {"participation_rate", "slice_count", "buy_value_ratio", "min_order_value"}.issubset(
        grid.columns
    )
    assert len(grid) == 4 * 6 * 4 * 3


def test_run_capacity_grid_experiment_ranks_lower_penalty_first():
    orders = pd.DataFrame(
        {
            "trade_date": ["2024-01-02"],
            "symbol": ["ETF"],
            "target_value": [1_000_000.0],
        }
    )
    minute_bars = pd.DataFrame(
        {
            "trade_date": ["2024-01-02"] * 10,
            "minute": list(range(932, 942)),
            "symbol": ["ETF"] * 10,
            "close": [10.0] * 10,
            "volume": [100_000.0] * 10,
        }
    )
    grid = pd.DataFrame(
        {
            "participation_rate": [0.10, 0.25],
            "slice_count": [1, 10],
            "buy_value_ratio": [1.0, 1.0],
            "min_order_value": [0.0, 0.0],
        }
    )

    ranked = run_capacity_grid_experiment(orders, minute_bars, grid)

    assert ranked.iloc[0]["fill_ratio"] == 1.0
    assert ranked.iloc[0]["slice_count"] == 10
