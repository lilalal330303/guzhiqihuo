import pandas as pd

from quant_lab.backtest.capacity import (
    CapacityConfig,
    build_capacity_grid,
    score_capacity_grid,
    simulate_rebalance_capacity,
)


def test_simulate_rebalance_capacity_caps_fills_by_minute_amount():
    orders = pd.DataFrame(
        {
            "trade_date": ["2024-01-02"],
            "symbol": ["ETF"],
            "target_value": [1_000_000.0],
        }
    )
    minute_bars = pd.DataFrame(
        {
            "trade_date": ["2024-01-02", "2024-01-02"],
            "minute": [932, 933],
            "symbol": ["ETF", "ETF"],
            "close": [10.0, 10.0],
            "volume": [10_000.0, 50_000.0],
        }
    )

    result = simulate_rebalance_capacity(
        orders,
        minute_bars,
        CapacityConfig(participation_rate=0.25, buy_value_ratio=1.0, slice_count=2),
    )

    assert result.summary["desired_value"] == 1_000_000.0
    assert result.summary["filled_value"] == 150_000.0
    assert result.summary["unfilled_value"] == 850_000.0
    assert result.summary["capacity_warning_count"] == 2
    assert result.fills["capacity_ratio"].round(2).tolist() == [0.05, 0.25]


def test_score_capacity_grid_compares_execution_parameters():
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
            "volume": [40_000.0] * 10,
        }
    )
    grid = build_capacity_grid(
        participation_rates=[0.10, 0.25],
        slice_counts=[1, 10],
        buy_value_ratios=[1.0],
        min_order_values=[0.0],
    )

    scored = score_capacity_grid(orders, minute_bars, grid)

    one_slice = scored[scored["slice_count"] == 1].sort_values("participation_rate")
    assert one_slice["fill_ratio"].round(2).tolist() == [0.04, 0.10]
    ten_slice_high_participation = scored[
        (scored["slice_count"] == 10) & (scored["participation_rate"] == 0.25)
    ].iloc[0]
    assert ten_slice_high_participation["fill_ratio"] == 1.0


def test_simulate_rebalance_capacity_can_use_order_level_slice_count():
    orders = pd.DataFrame(
        {
            "trade_date": ["2024-01-02", "2024-01-03"],
            "symbol": ["ETF", "ETF"],
            "target_value": [100_000.0, 100_000.0],
            "slices": [1, 2],
        }
    )
    minute_bars = pd.DataFrame(
        {
            "trade_date": ["2024-01-02", "2024-01-03", "2024-01-03"],
            "minute": [932, 932, 933],
            "symbol": ["ETF", "ETF", "ETF"],
            "close": [10.0, 10.0, 10.0],
            "volume": [10_000.0, 5_000.0, 5_000.0],
        }
    )

    result = simulate_rebalance_capacity(
        orders,
        minute_bars,
        CapacityConfig(participation_rate=1.0, buy_value_ratio=1.0, slice_count=None),
    )

    assert result.summary["fill_slice_count"] == 3
    assert result.summary["fill_ratio"] == 1.0
