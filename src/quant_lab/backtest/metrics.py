from __future__ import annotations

import pandas as pd


def calculate_metrics(equity_curve: pd.DataFrame, trades: pd.DataFrame) -> dict[str, float | int]:
    """Calculate core backtest metrics from an equity curve and trade list."""
    if equity_curve.empty:
        raise ValueError("equity_curve must not be empty")
    if "equity" not in equity_curve.columns:
        raise ValueError("equity_curve must include equity")

    equity = equity_curve["equity"].astype(float)
    total_return = equity.iloc[-1] / equity.iloc[0] - 1.0
    running_max = equity.cummax()
    drawdowns = equity / running_max - 1.0
    max_drawdown = float(drawdowns.min())

    periods = max(len(equity_curve) - 1, 1)
    annualized_return = (1.0 + total_return) ** (252.0 / periods) - 1.0

    trade_count = int(len(trades))
    if trade_count and "return_pct" in trades.columns:
        win_rate = float((trades["return_pct"] > 0).mean())
    else:
        win_rate = 0.0

    return {
        "total_return": float(total_return),
        "annualized_return": float(annualized_return),
        "max_drawdown": max_drawdown,
        "trade_count": trade_count,
        "win_rate": win_rate,
    }
