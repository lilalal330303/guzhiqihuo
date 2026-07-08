from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class BacktestResult:
    equity_curve: pd.DataFrame
    trades: pd.DataFrame


def run_long_only_backtest(
    signals: pd.DataFrame,
    initial_cash: float = 100_000.0,
    price_col: str = "close",
) -> BacktestResult:
    """Run a full-allocation long-only backtest from pre-shifted positions."""
    required = {"trade_date", price_col, "position", "trade_signal"}
    missing = required.difference(signals.columns)
    if missing:
        raise ValueError(f"signals missing required columns: {sorted(missing)}")
    if signals.empty:
        raise ValueError("signals must not be empty")

    data = signals.sort_values("trade_date").reset_index(drop=True).copy()
    data["daily_return"] = data[price_col].pct_change().fillna(0.0)
    held_position = data["position"].shift(1).fillna(0).astype(float)
    data["strategy_return"] = held_position * data["daily_return"]
    data["equity"] = initial_cash * (1.0 + data["strategy_return"]).cumprod()

    trades = _extract_trades(data, price_col)
    equity_curve = data[["trade_date", price_col, "position", "strategy_return", "equity"]].copy()
    return BacktestResult(equity_curve=equity_curve, trades=trades)


def _extract_trades(data: pd.DataFrame, price_col: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    open_trade: dict[str, object] | None = None

    for row in data.itertuples(index=False):
        trade_signal = int(getattr(row, "trade_signal"))
        trade_date = getattr(row, "trade_date")
        price = float(getattr(row, price_col))

        if trade_signal == 1 and open_trade is None:
            open_trade = {"entry_date": trade_date, "entry_price": price}
        elif trade_signal == -1 and open_trade is not None:
            entry_price = float(open_trade["entry_price"])
            rows.append(
                {
                    "entry_date": open_trade["entry_date"],
                    "exit_date": trade_date,
                    "entry_price": entry_price,
                    "exit_price": price,
                    "return_pct": (price / entry_price) - 1.0,
                }
            )
            open_trade = None

    if open_trade is not None:
        last = data.iloc[-1]
        entry_price = float(open_trade["entry_price"])
        exit_price = float(last[price_col])
        rows.append(
            {
                "entry_date": open_trade["entry_date"],
                "exit_date": last["trade_date"],
                "entry_price": entry_price,
                "exit_price": exit_price,
                "return_pct": (exit_price / entry_price) - 1.0,
            }
        )

    return pd.DataFrame(
        rows,
        columns=["entry_date", "exit_date", "entry_price", "exit_price", "return_pct"],
    )
