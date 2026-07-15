from __future__ import annotations

from dataclasses import dataclass
import math

import pandas as pd


@dataclass(frozen=True)
class CostModel:
    commission_rate: float = 0.85 / 10_000
    minimum_commission: float = 5.0
    sell_stamp_tax: float = 0.0005
    fixed_slippage: float = 0.002

    def fee(self, amount: float, side: str) -> float:
        commission = max(amount * self.commission_rate, self.minimum_commission)
        tax = amount * self.sell_stamp_tax if side == "sell" else 0.0
        return round(commission + tax, 10)


@dataclass(frozen=True)
class DailyRiskConfig:
    """Daily-close risk signals, all filled no earlier than next open."""

    enable_fixed_stop: bool = True
    fixed_stop_loss: float = 0.09
    enable_atr: bool = True
    atr_period: int = 14
    atr_multiplier: float = 2.0
    enable_cost_protection: bool = True
    repair_cost_protection: bool = False
    profit_activation: float = 0.30
    profit_floor: float = 0.10
    enable_market_stop: bool = True
    market_stop: float = 0.05
    enable_divergence: bool = True
    enable_crowding_daily: bool = True
    crowding_danger: float = 0.48
    enable_cooldown: bool = True
    cooldown_days: int = 2

    def __post_init__(self) -> None:
        if not math.isfinite(self.profit_activation) or not math.isfinite(self.profit_floor):
            raise ValueError("profit protection thresholds must be finite")
        if not 0 <= self.profit_floor < self.profit_activation:
            raise ValueError("profit_floor must satisfy 0 <= profit_floor < profit_activation")


@dataclass(frozen=True)
class PortfolioBacktestResult:
    equity_curve: pd.DataFrame
    trades: pd.DataFrame
    positions: pd.DataFrame
    rejections: pd.DataFrame


def detect_macd_divergence_dates(index_bars: pd.DataFrame) -> set[pd.Timestamp]:
    """Return dates matching the source script's 245-day MACD top divergence."""
    if index_bars.empty:
        return set()
    frame = index_bars.loc[:, ["trade_date", "close"]].copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    frame = frame.sort_values("trade_date").dropna().reset_index(drop=True)
    if len(frame) < 245:
        return set()
    hits: set[pd.Timestamp] = set()
    for end in range(245, len(frame) + 1):
        grid = frame.iloc[end - 245:end].copy()
        close = grid["close"].astype(float)
        dif = close.ewm(span=12, min_periods=11, adjust=False).mean() - close.ewm(
            span=26, min_periods=25, adjust=False
        ).mean()
        dea = dif.ewm(span=9, min_periods=8, adjust=False).mean()
        macd = (dif - dea) * 2
        mask = macd.lt(0) & macd.shift(1).ge(0)
        crosses = list(mask.index[mask.fillna(False)])
        if len(crosses) < 2:
            continue
        key2, key1 = crosses[-2], crosses[-1]
        price_condition = close.loc[key2] < close.loc[key1]
        dif_condition = dif.loc[key2] > dif.loc[key1] > 0
        cross_today = macd.iloc[-2] > 0 > macd.iloc[-1]
        trend_condition = dif.iloc[-10:].mean() < dif.iloc[-20:-10].mean()
        if price_condition and dif_condition and cross_today and trend_condition:
            hits.add(pd.Timestamp(grid.iloc[-1]["trade_date"]))
    return hits


def run_portfolio_backtest(
    bars: pd.DataFrame,
    targets: pd.DataFrame,
    initial_cash: float = 1_000_000.0,
    costs: CostModel | None = None,
    risk: DailyRiskConfig | None = None,
    market_daily: pd.DataFrame | None = None,
    index_bars: pd.DataFrame | None = None,
    crowding_daily: pd.DataFrame | None = None,
    exposure_budget_daily: pd.DataFrame | None = None,
    buy_new_only: bool = False,
) -> PortfolioBacktestResult:
    """Run a daily, next-open portfolio rebalance without future-state leakage.

    Each signal-date group is a complete desired portfolio.  It becomes
    executable at the next available market day, sells are applied before buys,
    and the equity curve is recorded only after that day's close.
    """
    costs = costs or CostModel()
    prices = bars.copy()
    prices["trade_date"] = pd.to_datetime(prices["trade_date"])
    signals = targets.copy()
    signals["signal_date"] = pd.to_datetime(signals["signal_date"])
    calendar = [pd.Timestamp(value) for value in sorted(prices["trade_date"].unique())]
    next_dates = {calendar[i]: calendar[i + 1] for i in range(len(calendar) - 1)}
    executable: dict[pd.Timestamp, pd.DataFrame] = {}
    for signal_date, group in signals.groupby("signal_date", sort=True):
        execute_date = next_dates.get(pd.Timestamp(signal_date))
        if execute_date is not None:
            executable[execute_date] = group.copy()
    executable_budgets: dict[pd.Timestamp, float] = {}
    if exposure_budget_daily is not None and not exposure_budget_daily.empty:
        budget_frame = exposure_budget_daily.loc[:, ["trade_date", "exposure_budget"]].copy()
        budget_frame["trade_date"] = pd.to_datetime(budget_frame["trade_date"])
        for row in budget_frame.itertuples(index=False):
            execute_date = next_dates.get(pd.Timestamp(row.trade_date))
            if execute_date is not None:
                executable_budgets[execute_date] = min(1.0, max(0.0, float(row.exposure_budget)))
    cash = float(initial_cash)
    holdings: dict[str, int] = {}
    lots: dict[str, list[dict[str, float]]] = {}
    trade_rows: list[dict[str, object]] = []
    rejection_rows: list[dict[str, object]] = []
    equity_rows: list[dict[str, object]] = []
    position_rows: list[dict[str, object]] = []
    pending_forced_sells: dict[str, str] = {}
    price_history: dict[str, list[dict[str, float]]] = {}
    atr_stop_prices: dict[str, float] = {}
    cooldown_until: dict[str, int] = {}
    peak_profit_ratio: dict[str, float] = {}
    market_stop_values: dict[pd.Timestamp, float] = {}
    if market_daily is not None and not market_daily.empty:
        market_frame = market_daily.copy()
        market_frame["trade_date"] = pd.to_datetime(market_frame["trade_date"])
        market_stop_values = market_frame.set_index("trade_date")["down_ratio"].astype(float).to_dict()
    divergence_dates = detect_macd_divergence_dates(index_bars) if index_bars is not None else set()
    divergence_hold_until = -1
    crowding_values: dict[pd.Timestamp, float] = {}
    if crowding_daily is not None and not crowding_daily.empty:
        crowding_frame = crowding_daily.copy()
        crowding_frame["trade_date"] = pd.to_datetime(crowding_frame["trade_date"])
        crowding_values = crowding_frame.set_index("trade_date")["concentration"].astype(float).to_dict()

    def execute_sell(
        trade_date: pd.Timestamp,
        symbol: str,
        sell_quantity: int,
        row: pd.Series,
        reason: str,
    ) -> None:
        nonlocal cash
        fill_price = max(0.0, float(row["open"]) - costs.fixed_slippage)
        amount = sell_quantity * fill_price
        fee = costs.fee(amount, "sell")
        remaining = sell_quantity
        matched_cost = 0.0
        while remaining:
            lot = lots[symbol][0]
            matched = min(remaining, int(lot["quantity"]))
            matched_cost += matched * lot["cost_per_share"]
            lot["quantity"] -= matched
            remaining -= matched
            if lot["quantity"] == 0:
                lots[symbol].pop(0)
        cash += amount - fee
        holdings[symbol] -= sell_quantity
        realized_proceeds = amount - fee
        trade_rows.append({
            "trade_date": trade_date, "symbol": symbol, "side": "sell",
            "quantity": sell_quantity, "raw_price": float(row["open"]),
            "fill_price": fill_price, "amount": amount, "fee": fee,
            "return_pct": realized_proceeds / matched_cost - 1.0,
            "reason": reason,
        })

    for day_index, trade_date in enumerate(calendar):
        day = prices[prices["trade_date"] == trade_date].set_index("symbol")
        for symbol, reason in list(pending_forced_sells.items()):
            quantity = holdings.get(symbol, 0)
            if quantity <= 0:
                pending_forced_sells.pop(symbol, None)
                continue
            if symbol not in day.index:
                rejection_rows.append({"trade_date": trade_date, "symbol": symbol, "reason": "missing_bar"})
                continue
            row = day.loc[symbol]
            if bool(row.get("paused", False)) or float(row["open"]) <= float(row.get("low_limit", float("-inf"))):
                rejection_rows.append({"trade_date": trade_date, "symbol": symbol, "reason": "sell_blocked"})
                continue
            execute_sell(trade_date, symbol, quantity, row, reason)
            if risk is not None and risk.enable_cooldown and reason == "fixed_stop":
                cooldown_until[symbol] = day_index + risk.cooldown_days
            pending_forced_sells.pop(symbol, None)
            atr_stop_prices.pop(symbol, None)
            peak_profit_ratio.pop(symbol, None)
        active_budget = executable_budgets.get(trade_date, 1.0)
        if active_budget < 1.0 and holdings:
            open_equity = cash + sum(
                quantity * float(day.loc[symbol, "open"])
                for symbol, quantity in holdings.items() if symbol in day.index
            )
            current_market_value = sum(
                quantity * float(day.loc[symbol, "open"])
                for symbol, quantity in holdings.items() if symbol in day.index
            )
            target_market_value = open_equity * active_budget
            if current_market_value > target_market_value and current_market_value > 0:
                retain_ratio = target_market_value / current_market_value
                for symbol, quantity in list(holdings.items()):
                    if quantity <= 0 or symbol == "511880" or symbol not in day.index:
                        continue
                    row = day.loc[symbol]
                    if bool(row.get("paused", False)) or float(row["open"]) <= float(
                        row.get("low_limit", float("-inf"))
                    ):
                        rejection_rows.append({
                            "trade_date": trade_date, "symbol": symbol,
                            "reason": "risk_budget_sell_blocked",
                        })
                        continue
                    desired_quantity = int(quantity * retain_ratio / 100) * 100
                    sell_quantity = max(0, quantity - desired_quantity)
                    if sell_quantity:
                        execute_sell(
                            trade_date, symbol, sell_quantity, row, "risk_budget_reduce"
                        )
        crowded_previous = (
            risk is not None
            and risk.enable_crowding_daily
            and day_index > 0
            and crowding_values.get(calendar[day_index - 1], 0.0) >= risk.crowding_danger
        )
        if trade_date in executable and not crowded_previous and not (
            risk is not None and risk.enable_divergence and day_index <= divergence_hold_until
        ):
            desired = (
                executable[trade_date].set_index("symbol")["target_weight"].astype(float)
                * active_budget
            ).to_dict()
            open_equity = cash + sum(
                quantity * float(day.loc[symbol, "open"])
                for symbol, quantity in holdings.items() if symbol in day.index
            )
            # Sell removed/reduced positions first, making released cash usable today.
            for symbol, quantity in list(holdings.items()):
                target_weight = max(0.0, desired.get(symbol, 0.0))
                if symbol not in day.index:
                    rejection_rows.append({"trade_date": trade_date, "symbol": symbol, "reason": "missing_bar"})
                    continue
                row = day.loc[symbol]
                if bool(row.get("paused", False)) or float(row["open"]) <= float(row.get("low_limit", float("-inf"))):
                    rejection_rows.append({"trade_date": trade_date, "symbol": symbol, "reason": "sell_blocked"})
                    continue
                desired_quantity = (
                    quantity if buy_new_only and symbol in desired
                    else int((open_equity * target_weight) / float(row["open"]) / 100) * 100
                )
                sell_quantity = max(0, quantity - desired_quantity)
                if sell_quantity:
                    execute_sell(trade_date, symbol, sell_quantity, row, "rebalance")
            new_symbols = [symbol for symbol in desired if holdings.get(symbol, 0) <= 0]
            new_symbol_budget = 0.0
            if buy_new_only and new_symbols:
                desired_total_weight = min(1.0, sum(max(0.0, weight) for weight in desired.values()))
                current_value = sum(
                    quantity * float(day.loc[symbol, "open"])
                    for symbol, quantity in holdings.items()
                    if symbol in desired and symbol in day.index
                )
                available_cash = min(cash, max(0.0, open_equity * desired_total_weight - current_value))
                new_symbol_budget = available_cash / len(new_symbols)
            for symbol, weight in desired.items():
                if symbol not in day.index:
                    rejection_rows.append({"trade_date": trade_date, "symbol": symbol, "reason": "missing_bar"})
                    continue
                row = day.loc[symbol]
                if risk is not None and day_index <= cooldown_until.get(symbol, -1):
                    rejection_rows.append({"trade_date": trade_date, "symbol": symbol, "reason": "cooldown"})
                    continue
                if bool(row.get("paused", False)) or bool(row.get("is_st", False)):
                    rejection_rows.append({"trade_date": trade_date, "symbol": symbol, "reason": "paused"})
                    continue
                if float(row["open"]) >= float(row.get("high_limit", float("inf"))):
                    rejection_rows.append({"trade_date": trade_date, "symbol": symbol, "reason": "upper_limit"})
                    continue
                fill_price = float(row["open"]) + costs.fixed_slippage
                if buy_new_only and holdings.get(symbol, 0) > 0:
                    continue
                target_value = new_symbol_budget if buy_new_only else open_equity * max(0.0, weight)
                target_quantity = int(target_value / fill_price / 100) * 100
                buy_quantity = max(0, target_quantity - holdings.get(symbol, 0))
                while buy_quantity > 0 and buy_quantity * fill_price + costs.fee(buy_quantity * fill_price, "buy") > cash:
                    buy_quantity -= 100
                if buy_quantity <= 0:
                    if target_quantity > holdings.get(symbol, 0):
                        rejection_rows.append({"trade_date": trade_date, "symbol": symbol, "reason": "insufficient_cash"})
                    continue
                amount = buy_quantity * fill_price
                fee = costs.fee(amount, "buy")
                cash -= amount + fee
                holdings[symbol] = holdings.get(symbol, 0) + buy_quantity
                lots.setdefault(symbol, []).append({"quantity": float(buy_quantity), "cost_per_share": (amount + fee) / buy_quantity})
                trade_rows.append({"trade_date": trade_date, "symbol": symbol, "side": "buy", "quantity": buy_quantity,
                                   "raw_price": float(row["open"]), "fill_price": fill_price, "amount": amount, "fee": fee,
                                   "return_pct": None, "reason": "rebalance"})
        for symbol, row in day.iterrows():
            if {"high", "low", "close"}.issubset(row.index):
                price_history.setdefault(str(symbol), []).append({
                    "high": float(row["high"]), "low": float(row["low"]), "close": float(row["close"])
                })
        if risk is not None:
            for symbol, quantity in list(holdings.items()):
                if quantity <= 0 or symbol not in day.index or symbol == "511880":
                    continue
                close = float(day.loc[symbol, "close"])
                total_quantity = sum(float(lot["quantity"]) for lot in lots.get(symbol, []))
                avg_cost = (
                    sum(float(lot["quantity"]) * float(lot["cost_per_share"]) for lot in lots.get(symbol, []))
                    / total_quantity if total_quantity else close
                )
                profit_ratio = close / avg_cost - 1.0 if avg_cost else 0.0
                peak_profit_ratio[symbol] = max(peak_profit_ratio.get(symbol, profit_ratio), profit_ratio)
                if risk.enable_fixed_stop and close < avg_cost * (1.0 - risk.fixed_stop_loss):
                    pending_forced_sells.setdefault(symbol, "fixed_stop")
                    continue
                if risk.enable_cost_protection and risk.repair_cost_protection:
                    peak = peak_profit_ratio[symbol]
                    if peak >= risk.profit_activation and profit_ratio < risk.profit_floor:
                        pending_forced_sells.setdefault(symbol, "cost_protection")
                        continue
                history = price_history.get(symbol, [])
                if risk.enable_atr and len(history) >= risk.atr_period + 1:
                    previous = history[-(risk.atr_period + 1):]
                    true_ranges = [
                        max(
                            previous[i]["high"] - previous[i]["low"],
                            abs(previous[i]["high"] - previous[i - 1]["close"]),
                            abs(previous[i]["low"] - previous[i - 1]["close"]),
                        )
                        for i in range(1, len(previous))
                    ]
                    existing_stop = atr_stop_prices.get(symbol)
                    if existing_stop is not None and close <= existing_stop:
                        pending_forced_sells.setdefault(symbol, "atr_stop")
                    atr_stop_prices[symbol] = close - sum(true_ranges) / len(true_ranges) * risk.atr_multiplier
            if risk.enable_market_stop and market_stop_values.get(trade_date, 0.0) <= -risk.market_stop:
                for symbol, quantity in holdings.items():
                    if quantity > 0 and symbol != "511880":
                        pending_forced_sells.setdefault(symbol, "market_stop")
            if risk.enable_divergence and trade_date in divergence_dates:
                divergence_hold_until = day_index + 9
                for symbol, quantity in holdings.items():
                    if quantity <= 0 or symbol == "511880" or symbol not in day.index:
                        continue
                    row = day.loc[symbol]
                    if float(row["close"]) < float(row.get("high_limit", float("inf"))):
                        pending_forced_sells.setdefault(symbol, "macd_divergence")
            if risk.enable_crowding_daily and crowding_values.get(trade_date, 0.0) >= risk.crowding_danger:
                for symbol, quantity in holdings.items():
                    if quantity > 0 and symbol != "511880":
                        pending_forced_sells.setdefault(symbol, "crowding_clear")
        market_value = sum(qty * float(day.loc[symbol, "close"]) for symbol, qty in holdings.items() if symbol in day.index)
        equity_rows.append({"trade_date": pd.Timestamp(trade_date), "cash": cash,
                            "market_value": market_value, "equity": cash + market_value})
        for symbol, qty in holdings.items():
            position_rows.append({"trade_date": pd.Timestamp(trade_date), "symbol": symbol, "quantity": qty})

    return PortfolioBacktestResult(
        pd.DataFrame(equity_rows),
        pd.DataFrame(trade_rows, columns=["trade_date", "symbol", "side", "quantity", "raw_price", "fill_price", "amount", "fee", "return_pct", "reason"]),
        pd.DataFrame(position_rows, columns=["trade_date", "symbol", "quantity"]),
        pd.DataFrame(rejection_rows, columns=["trade_date", "symbol", "reason"]),
    )
