from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quant_lab.data.repository import DuckDBRepository
from quant_lab.strategies.wufu_etf_rotation import (  # noqa: E402
    WufuEtfRotationConfig,
    generate_a_share_weak_states_joinquant_style,
    generate_wufu_targets,
)


START_DATE = "2020-01-02"
END_DATE = "2026-07-06"
INITIAL_CASH = 1_000_000.0
COMMISSION_RATE = 0.0001
SLIPPAGE_RATE = 0.0001
MIN_COMMISSION = 5.0
CASH_BUFFER = 0.998
ROUND_LOT = 100


def main() -> None:
    repo = DuckDBRepository(ROOT / "data" / "market.duckdb")
    config = WufuEtfRotationConfig()
    symbols = list(dict.fromkeys(config.etf_pool + config.global_etf_pool + [config.defensive_etf]))
    prices = repo.load_prices_for_symbols(symbols, START_DATE, END_DATE)
    if prices.empty:
        raise RuntimeError("no local ETF daily prices found")
    prices, excluded_symbols = exclude_symbols_with_price_jumps(prices, max_abs_daily_return=0.25)
    index_prices = repo.load_prices_for_symbols(["000300", "399101", "399006", "000510"], START_DATE, END_DATE)
    weak_states = pd.DataFrame()
    if not index_prices.empty:
        weak_states = generate_a_share_weak_states_joinquant_style(
            index_prices,
            ma_lookback=config.weak_period_ma_lookback,
            max_weak_days=config.max_weak_days,
            signal_lag_days=0,
        )
    targets = generate_wufu_targets(prices, config=config, weak_states=weak_states)
    targets = targets[pd.to_datetime(targets["trade_date"]).between(pd.Timestamp(START_DATE), pd.Timestamp(END_DATE))]
    result = run_execution_backtest(prices, targets)
    out_prefix = ROOT / "reports" / "wufu_v8_local_execution"
    targets.to_csv(out_prefix.with_name(out_prefix.name + "_targets.csv"), index=False, encoding="utf-8-sig")
    result["equity"].to_csv(out_prefix.with_name(out_prefix.name + "_equity.csv"), index=False, encoding="utf-8-sig")
    result["trades"].to_csv(out_prefix.with_name(out_prefix.name + "_trades.csv"), index=False, encoding="utf-8-sig")
    summary = {
        "start_date": START_DATE,
        "end_date": END_DATE,
        "params": asdict(config)
        | {
            "initial_cash": INITIAL_CASH,
            "commission_rate": COMMISSION_RATE,
            "slippage_rate": SLIPPAGE_RATE,
            "min_commission": MIN_COMMISSION,
            "cash_buffer": CASH_BUFFER,
            "round_lot": ROUND_LOT,
            "weak_state_source": "local-index-joinquant-style" if not weak_states.empty else "missing-index-data",
        },
        "rows": {
            "prices": int(len(prices)),
            "symbols": int(prices["symbol"].nunique()),
            "targets": int(len(targets)),
            "weak_states": int(len(weak_states)),
            "excluded_symbols": int(len(excluded_symbols)),
        },
        "excluded_symbols": excluded_symbols,
        "metrics": result["metrics"],
    }
    out_prefix.with_name(out_prefix.name + "_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def run_execution_backtest(prices: pd.DataFrame, targets: pd.DataFrame) -> dict[str, pd.DataFrame | dict[str, float | int]]:
    price_rows = prices.copy()
    price_rows["trade_date"] = pd.to_datetime(price_rows["trade_date"])
    close_raw = price_rows.pivot_table(index="trade_date", columns="symbol", values="close", aggfunc="last").sort_index()
    close = close_raw.ffill()
    target_rows = targets[["trade_date", "target_symbol"]].copy()
    target_rows["trade_date"] = pd.to_datetime(target_rows["trade_date"])
    target_by_date = target_rows.drop_duplicates("trade_date", keep="last").set_index("trade_date")["target_symbol"]
    target_by_date = target_by_date.reindex(close.index).ffill()

    cash = INITIAL_CASH
    shares = 0
    held_symbol: str | None = None
    equity_rows: list[dict[str, object]] = []
    trade_rows: list[dict[str, object]] = []

    for trade_date in close.index:
        desired_raw = target_by_date.shift(1).get(trade_date)
        desired = None if pd.isna(desired_raw) else str(desired_raw)
        if desired and desired not in close.columns:
            desired = None

        current_value = _position_value(close, trade_date, held_symbol, shares)
        total_value_before = cash + current_value

        if desired != held_symbol:
            if held_symbol and shares > 0:
                sell_price = float(close.at[trade_date, held_symbol])
                sell_value = shares * sell_price
                sell_cost = _cost(sell_value)
                cash += sell_value - sell_cost
                trade_rows.append(
                    {
                        "trade_date": trade_date.date(),
                        "action": "sell",
                        "symbol": held_symbol,
                        "price": sell_price,
                        "shares": shares,
                        "notional": sell_value,
                        "cost": sell_cost,
                    }
                )
                held_symbol = None
                shares = 0
            if desired and pd.notna(close_raw.at[trade_date, desired]):
                buy_price = float(close_raw.at[trade_date, desired]) * (1.0 + SLIPPAGE_RATE)
                budget = max(0.0, (cash + _position_value(close, trade_date, held_symbol, shares)) * CASH_BUFFER - MIN_COMMISSION)
                buy_shares = int(budget / (buy_price * (1.0 + COMMISSION_RATE)) / ROUND_LOT) * ROUND_LOT
                buy_notional = buy_shares * buy_price
                buy_cost = _cost(buy_notional)
                if buy_shares > 0 and buy_notional + buy_cost <= cash + 1e-6:
                    cash -= buy_notional + buy_cost
                    held_symbol = desired
                    shares = buy_shares
                    trade_rows.append(
                        {
                            "trade_date": trade_date.date(),
                            "action": "buy",
                            "symbol": desired,
                            "price": buy_price,
                            "shares": buy_shares,
                            "notional": buy_notional,
                            "cost": buy_cost,
                        }
                    )

        position_value = _position_value(close, trade_date, held_symbol, shares)
        equity_rows.append(
            {
                "trade_date": trade_date.date(),
                "target_symbol": desired,
                "held_symbol": held_symbol,
                "shares": shares,
                "cash": cash,
                "position_value": position_value,
                "equity": cash + position_value,
                "value_before_rebalance": total_value_before,
            }
        )

    equity = pd.DataFrame(equity_rows)
    trades = pd.DataFrame(trade_rows)
    metrics = calculate_metrics(equity, trades)
    return {"equity": equity, "trades": trades, "metrics": metrics}


def _position_value(close: pd.DataFrame, trade_date: pd.Timestamp, symbol: str | None, shares: int) -> float:
    if not symbol or shares <= 0 or symbol not in close.columns:
        return 0.0
    price = close.at[trade_date, symbol]
    if pd.isna(price):
        return 0.0
    return float(price) * shares


def _cost(notional: float) -> float:
    if notional <= 0:
        return 0.0
    return max(notional * COMMISSION_RATE, MIN_COMMISSION) + notional * SLIPPAGE_RATE


def calculate_metrics(equity: pd.DataFrame, trades: pd.DataFrame) -> dict[str, float | int]:
    values = equity["equity"].astype(float)
    returns = values.pct_change().fillna(0.0)
    drawdown = values / values.cummax() - 1.0
    years = max((pd.to_datetime(equity["trade_date"]).iloc[-1] - pd.to_datetime(equity["trade_date"]).iloc[0]).days / 365.25, 1e-9)
    pair_returns = paired_trade_returns(trades)
    return {
        "total_return": float(values.iloc[-1] / values.iloc[0] - 1.0),
        "annualized_return": float((values.iloc[-1] / values.iloc[0]) ** (1.0 / years) - 1.0),
        "max_drawdown": float(drawdown.min()),
        "trade_count": int(len(trades)),
        "buy_count": int((trades["action"] == "buy").sum()) if not trades.empty else 0,
        "sell_count": int((trades["action"] == "sell").sum()) if not trades.empty else 0,
        "win_rate": float("nan") if not pair_returns else float(sum(1 for value in pair_returns if value > 0) / len(pair_returns)),
        "final_equity": float(values.iloc[-1]),
        "daily_volatility": float(returns.std()),
    }


def paired_trade_returns(trades: pd.DataFrame) -> list[float]:
    if trades.empty:
        return []
    open_by_symbol: dict[str, tuple[float, int]] = {}
    returns: list[float] = []
    for row in trades.itertuples(index=False):
        action = getattr(row, "action")
        symbol = str(getattr(row, "symbol"))
        price = float(getattr(row, "price"))
        shares = int(getattr(row, "shares"))
        if action == "buy":
            open_by_symbol[symbol] = (price, shares)
        elif action == "sell" and symbol in open_by_symbol:
            entry_price, entry_shares = open_by_symbol.pop(symbol)
            matched_shares = min(entry_shares, shares)
            if matched_shares > 0 and entry_price > 0:
                returns.append(price / entry_price - 1.0)
    return returns


def exclude_symbols_with_price_jumps(prices: pd.DataFrame, max_abs_daily_return: float) -> tuple[pd.DataFrame, list[str]]:
    rows = prices.sort_values(["symbol", "trade_date"]).copy()
    rows["daily_return"] = rows.groupby("symbol")["close"].pct_change()
    broken = sorted(rows.loc[rows["daily_return"].abs() > max_abs_daily_return, "symbol"].unique().tolist())
    if not broken:
        return prices, []
    return prices[~prices["symbol"].isin(broken)].reset_index(drop=True), broken


if __name__ == "__main__":
    main()
