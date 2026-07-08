from __future__ import annotations

import pandas as pd

from quant_lab.backtest.capacity import build_capacity_grid, score_capacity_grid


def default_etf_capacity_grid() -> pd.DataFrame:
    """Parameter grid for ETF rotation capacity experiments."""
    return build_capacity_grid(
        participation_rates=[0.10, 0.15, 0.25, 0.35],
        slice_counts=[1, 3, 5, 10, 15, 20],
        buy_value_ratios=[0.80, 0.90, 0.95, 0.995],
        min_order_values=[0.0, 20_000.0, 50_000.0],
    )


def run_capacity_grid_experiment(
    orders: pd.DataFrame,
    minute_bars: pd.DataFrame,
    grid: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Score capacity solutions and add a conservative ranking column."""
    candidates = grid if grid is not None else default_etf_capacity_grid()
    scored = score_capacity_grid(orders=orders, minute_bars=minute_bars, grid=candidates)
    if scored.empty:
        return scored

    ranked = scored.copy()
    ranked["capacity_penalty"] = (
        ranked["unfilled_value"].astype(float)
        + ranked["capacity_warning_count"].astype(float) * 10_000.0
        + ranked["severe_capacity_count"].astype(float) * 50_000.0
        + ranked["skipped_min_order_count"].astype(float) * 5_000.0
    )
    return ranked.sort_values(
        ["capacity_penalty", "fill_ratio", "participation_rate", "slice_count"],
        ascending=[True, False, True, True],
    ).reset_index(drop=True)
