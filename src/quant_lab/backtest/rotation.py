from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class RotationBacktestResult:
    equity_curve: pd.DataFrame
    trades: pd.DataFrame


def run_single_slot_rotation_backtest(
    prices: pd.DataFrame,
    targets: pd.DataFrame,
    initial_cash: float = 100_000.0,
    commission_rate: float = 0.0,
    slippage_rate: float = 0.0,
    min_commission: float = 0.0,
) -> RotationBacktestResult:
    required_prices = {"symbol", "trade_date", "close"}
    missing_prices = required_prices.difference(prices.columns)
    if missing_prices:
        raise ValueError(f"prices missing required columns: {sorted(missing_prices)}")
    required_targets = {"trade_date", "target_symbol"}
    missing_targets = required_targets.difference(targets.columns)
    if missing_targets:
        raise ValueError(f"targets missing required columns: {sorted(missing_targets)}")
    if prices.empty or targets.empty:
        raise ValueError("prices and targets must not be empty")

    price_data = prices.copy()
    price_data["trade_date"] = pd.to_datetime(price_data["trade_date"])
    close_pivot = price_data.pivot_table(index="trade_date", columns="symbol", values="close", aggfunc="last").sort_index()
    returns = close_pivot.pct_change().fillna(0.0)

    target_data = targets[["trade_date", "target_symbol"]].copy()
    target_data["trade_date"] = pd.to_datetime(target_data["trade_date"])
    target_by_date = target_data.drop_duplicates("trade_date", keep="last").set_index("trade_date")
    target_by_date = target_by_date.reindex(close_pivot.index).ffill()
    held_symbols = target_by_date["target_symbol"].shift(1)

    strategy_returns = []
    trade_costs = []
    equity_values = []
    effective_held_symbols = []
    equity = initial_cash
    previous_held_symbol = None
    for trade_date, desired_symbol in held_symbols.items():
        held_symbol = _executable_symbol(close_pivot, trade_date, None if pd.isna(desired_symbol) else desired_symbol)
        if held_symbol is None and previous_held_symbol is not None:
            held_symbol = _executable_symbol(close_pivot, trade_date, previous_held_symbol)
        if pd.isna(held_symbol) or held_symbol not in returns.columns:
            strategy_return = 0.0
        else:
            strategy_return = float(returns.at[trade_date, held_symbol])
        turnover_sides = _turnover_sides(previous_held_symbol, None if pd.isna(held_symbol) else held_symbol)
        trade_cost = _estimate_trade_cost(
            equity,
            turnover_sides=turnover_sides,
            commission_rate=commission_rate,
            slippage_rate=slippage_rate,
            min_commission=min_commission,
        )
        equity = equity * (1.0 + strategy_return) - trade_cost
        strategy_returns.append(strategy_return)
        trade_costs.append(trade_cost)
        equity_values.append(equity)
        effective_held_symbols.append(held_symbol)
        previous_held_symbol = None if pd.isna(held_symbol) else held_symbol

    equity_curve = pd.DataFrame(
        {
            "trade_date": close_pivot.index,
            "held_symbol": pd.Series(
                [None if pd.isna(symbol) else symbol for symbol in effective_held_symbols],
                dtype="object",
            ),
            "strategy_return": strategy_returns,
            "trade_cost": trade_costs,
        }
    )
    equity_curve["equity"] = equity_values

    trades = _extract_rotation_trades(equity_curve, close_pivot)
    return RotationBacktestResult(equity_curve=equity_curve.reset_index(drop=True), trades=trades)


def _turnover_sides(previous_symbol: str | None, next_symbol: str | None) -> int:
    if previous_symbol == next_symbol:
        return 0
    if previous_symbol is None and next_symbol is None:
        return 0
    if previous_symbol is None or next_symbol is None:
        return 1
    return 2


def _executable_symbol(close_pivot: pd.DataFrame, trade_date: pd.Timestamp, symbol: str | None) -> str | None:
    if symbol is None or symbol not in close_pivot.columns:
        return None
    price = close_pivot.at[trade_date, symbol]
    if pd.isna(price):
        return None
    return symbol


def _estimate_trade_cost(
    equity: float,
    turnover_sides: int,
    commission_rate: float,
    slippage_rate: float,
    min_commission: float,
) -> float:
    if turnover_sides <= 0:
        return 0.0
    per_side_notional = max(equity, 0.0)
    commission = max(per_side_notional * commission_rate, min_commission) if commission_rate or min_commission else 0.0
    slippage = per_side_notional * slippage_rate
    return turnover_sides * (commission + slippage)


def _extract_rotation_trades(equity_curve: pd.DataFrame, close_pivot: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    open_trade: dict[str, object] | None = None
    previous_symbol: str | None = None

    for row in equity_curve.itertuples(index=False):
        trade_date = getattr(row, "trade_date")
        held_symbol = getattr(row, "held_symbol")
        held_symbol = None if pd.isna(held_symbol) else held_symbol
        if held_symbol == previous_symbol:
            continue

        if previous_symbol is not None and open_trade is not None:
            exit_raw = close_pivot.at[trade_date, previous_symbol]
            if pd.isna(exit_raw):
                continue
            exit_price = float(exit_raw)
            entry_price = float(open_trade["entry_price"])
            rows.append(
                {
                    "symbol": previous_symbol,
                    "entry_date": open_trade["entry_date"],
                    "exit_date": trade_date,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "return_pct": exit_price / entry_price - 1.0,
                }
            )
            open_trade = None

        if held_symbol is not None:
            entry_raw = close_pivot.at[trade_date, held_symbol]
            if pd.isna(entry_raw):
                previous_symbol = None
                continue
            open_trade = {
                "entry_date": trade_date,
                "entry_price": float(entry_raw),
            }
        previous_symbol = held_symbol

    if previous_symbol is not None and open_trade is not None:
        last_date = close_pivot.index[-1]
        exit_raw = close_pivot.at[last_date, previous_symbol]
        if pd.isna(exit_raw):
            return pd.DataFrame(
                rows,
                columns=["symbol", "entry_date", "exit_date", "entry_price", "exit_price", "return_pct"],
            )
        exit_price = float(exit_raw)
        entry_price = float(open_trade["entry_price"])
        rows.append(
            {
                "symbol": previous_symbol,
                "entry_date": open_trade["entry_date"],
                "exit_date": last_date,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "return_pct": exit_price / entry_price - 1.0,
            }
        )

    return pd.DataFrame(
        rows,
        columns=["symbol", "entry_date", "exit_date", "entry_price", "exit_price", "return_pct"],
    )
