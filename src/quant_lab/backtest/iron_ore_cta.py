from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

from quant_lab.backtest.metrics import calculate_metrics
from quant_lab.strategies.iron_ore_cta import (
    adaptive_signal,
    atr,
    direction_consistency,
    drawdown_multiplier,
    efficiency_ratio,
    make_params,
    realized_volatility,
    risk_multiplier,
    risk_scaled_amount,
    trailing_stop_hit,
    trend_quality_multiplier,
    volatility_ratio,
)


IRON_ORE_CODE_RE = re.compile(r"^I\d{4}\.XDCE$", re.IGNORECASE)


@dataclass(frozen=True)
class IronOreBacktestConfig:
    start_date: str = "2018-01-01"
    end_date: str = "2026-07-18"
    initial_cash: float = 1_000_000.0
    contract_multiplier: int = 100
    slippage_points: float = 2.0
    open_commission: float = 0.000023
    close_commission: float = 0.000023
    roll_days_before_expiry: int = 8


@dataclass(frozen=True)
class IronOreBacktestResult:
    signals: pd.DataFrame
    trades: pd.DataFrame
    equity_curve: pd.DataFrame
    metrics: dict[str, float | int]


def select_near_contract_local(
    universe: pd.DataFrame,
    signal_date: str | pd.Timestamp,
    roll_days_before_expiry: int = 8,
) -> str | None:
    """Select the nearest eligible contract from the latest known PIT snapshot."""
    required = {"asof_date", "symbol", "list_date", "end_date"}
    missing = required.difference(universe.columns)
    if missing:
        raise ValueError(f"universe missing required columns: {sorted(missing)}")
    if universe.empty:
        return None
    signal_date = pd.Timestamp(signal_date).normalize()
    rows = universe.copy()
    for column in ["asof_date", "list_date", "end_date"]:
        rows[column] = pd.to_datetime(rows[column], errors="coerce")
    rows["symbol"] = rows["symbol"].astype(str).str.upper()
    rows = rows.loc[rows["asof_date"] <= signal_date].copy()
    if rows.empty:
        return None
    latest_asof = rows["asof_date"].max()
    rows = rows.loc[rows["asof_date"] == latest_asof].copy()
    rows = rows.loc[rows["symbol"].map(lambda value: bool(IRON_ORE_CODE_RE.fullmatch(value)))]
    rows = rows.loc[
        (rows["list_date"] <= signal_date)
        & ((rows["end_date"] - signal_date).dt.days > int(roll_days_before_expiry))
    ]
    if rows.empty:
        return None
    return str(rows.sort_values(["end_date", "symbol"]).iloc[0]["symbol"])


def build_iron_ore_signal_snapshot(
    main_daily: pd.DataFrame,
    signal_date: str | pd.Timestamp,
) -> dict[str, object] | None:
    """Build one V1.6 snapshot using only main bars up to signal_date."""
    signal_date = pd.Timestamp(signal_date).normalize()
    bars = main_daily.loc[pd.to_datetime(main_daily["trade_date"]) <= signal_date].copy()
    bars = bars.sort_values("trade_date").reset_index(drop=True)
    if bars.empty:
        return None
    params = make_params(signal_date)
    closes = pd.to_numeric(bars["close"], errors="coerce").dropna().tolist()
    minimum = max(
        params["trend_days"] + params["slope_days"],
        params["slow_trend_days"] + params["slow_slope_days"],
    )
    if len(closes) < minimum:
        return None
    signal = adaptive_signal(closes, params)
    fast = float(pd.Series(closes).tail(params["fast_days"]).mean())
    slow = float(pd.Series(closes).tail(params["trend_days"]).mean())
    previous_slow = float(
        pd.Series(
            closes[-params["trend_days"] - params["slope_days"]:-params["slope_days"]]
        ).mean()
    )
    slow_slope = slow / previous_slow - 1.0 if previous_slow > 0 else 0.0
    efficiency = efficiency_ratio(closes, params["efficiency_days"])
    consistency = direction_consistency(closes, params["direction_days"])
    vol_ratio = volatility_ratio(closes, params["vol_days"], params["vol_long_days"])
    realized = realized_volatility(closes[-params["vol_days"] - 1:])
    signal_multiplier = 1.0
    if params["dual_speed"]:
        from quant_lab.strategies.iron_ore_cta import dual_speed_signal

        signal, signal_multiplier = dual_speed_signal(closes, params)
    regime = risk_multiplier(efficiency, vol_ratio, consistency, params)
    trend = (
        1.0
        if params["dual_speed"]
        else trend_quality_multiplier(
            float(closes[-1]), fast, slow, slow_slope, realized, params
        )
    )
    return {
        "signal_date": signal_date,
        "params": params,
        "signal": int(signal),
        "signal_multiplier": float(signal_multiplier),
        "close": float(closes[-1]),
        "ma_fast": fast,
        "ma_slow": slow,
        "slow_slope": slow_slope,
        "efficiency_ratio": float(efficiency),
        "direction_consistency": float(consistency),
        "volatility_ratio": float(vol_ratio),
        "regime_multiplier": float(regime),
        "trend_multiplier": float(trend),
        "atr": float(atr(bars, params["atr_days"])),
        "realized_vol": float(realized),
    }


def run_iron_ore_v16_backtest(
    main_daily: pd.DataFrame,
    contract_daily: pd.DataFrame,
    contracts: pd.DataFrame,
    universe_daily: pd.DataFrame,
    config: IronOreBacktestConfig | None = None,
) -> IronOreBacktestResult:
    """Run a transparent T+1-open approximation of the JoinQuant V1.6 strategy."""
    config = config or IronOreBacktestConfig()
    main = _prepare_bars(main_daily, "I8888.XDCE")
    contract_bars = _prepare_contract_bars(contract_daily)
    _validate_contract_metadata(contracts)
    universe = universe_daily.copy()
    if universe.empty:
        raise ValueError("universe_daily must not be empty for a point-in-time backtest")

    start = pd.Timestamp(config.start_date).normalize()
    end = pd.Timestamp(config.end_date).normalize()
    calendar = [
        pd.Timestamp(value)
        for value in main["trade_date"].drop_duplicates().sort_values()
        if start <= pd.Timestamp(value) <= end
    ]
    if not calendar:
        raise ValueError("main_daily has no rows inside the configured date range")
    all_dates = list(pd.to_datetime(main["trade_date"]).drop_duplicates().sort_values())
    next_date = {
        all_dates[index]: all_dates[index + 1]
        for index in range(len(all_dates) - 1)
    }
    main_by_date = main.set_index("trade_date")
    contract_by_key = contract_bars.set_index(["symbol", "trade_date"]).sort_index()

    cash = float(config.initial_cash)
    current_symbol: str | None = None
    current_direction = 0
    current_quantity = 0
    entry_price = 0.0
    entry_signal_date: pd.Timestamp | None = None
    best_close: float | None = None
    high_water = cash
    cooldown = 0
    scheduled: dict[pd.Timestamp, dict[str, object]] = {}
    signal_rows: list[dict[str, object]] = []
    trade_rows: list[dict[str, object]] = []
    equity_rows: list[dict[str, object]] = []

    for trade_date in all_dates:
        trade_date = pd.Timestamp(trade_date).normalize()
        if trade_date in scheduled:
            order = scheduled.pop(trade_date)
            state = _execute_scheduled_order(
                order,
                trade_date,
                contract_by_key,
                config,
                state={
                    "cash": cash,
                    "current_symbol": current_symbol,
                    "current_direction": current_direction,
                    "current_quantity": current_quantity,
                    "entry_price": entry_price,
                    "entry_signal_date": entry_signal_date,
                    "best_close": best_close,
                    "cooldown": cooldown,
                },
                trade_rows=trade_rows,
            )
            cash = state["cash"]
            current_symbol = state["current_symbol"]
            current_direction = state["current_direction"]
            current_quantity = state["current_quantity"]
            entry_price = state["entry_price"]
            entry_signal_date = state["entry_signal_date"]
            best_close = state["best_close"]
            cooldown = int(state["cooldown"])

        mark_close, unrealized, market_value = _mark_position(
            current_symbol,
            current_direction,
            current_quantity,
            entry_price,
            trade_date,
            contract_by_key,
            config.contract_multiplier,
        )
        equity = cash + unrealized
        high_water = max(high_water, equity)
        if start <= trade_date <= end:
            equity_rows.append(
                {
                    "trade_date": trade_date,
                    "equity": equity,
                    "cash": cash,
                    "market_value": market_value,
                    "close": float(main_by_date.loc[trade_date, "close"]),
                    "position_direction": current_direction,
                    "position_quantity": current_quantity,
                    "position_symbol": current_symbol or "",
                }
            )

        if trade_date < start or trade_date > end:
            continue
        snapshot = build_iron_ore_signal_snapshot(main, trade_date)
        if snapshot is None:
            signal_rows.append({"signal_date": trade_date, "signal": 0, "reason": "insufficient_history"})
            continue
        params = snapshot["params"]
        target_contract = select_near_contract_local(
            universe,
            trade_date,
            config.roll_days_before_expiry,
        )
        target_direction = (
            1 if snapshot["signal"] == 1 else -1 if snapshot["signal"] == -1 and params["allow_short"] else 0
        )
        reason = "signal"
        if target_contract is None:
            target_direction = 0
            reason = "no_contract"

        if current_symbol:
            current_bar = _latest_contract_bar(
                contract_by_key,
                current_symbol,
                trade_date,
            )
            if current_bar is not None:
                latest_close = float(current_bar["close"])
                if best_close is None:
                    best_close = latest_close
                elif current_direction > 0:
                    best_close = max(best_close, latest_close)
                else:
                    best_close = min(best_close, latest_close)
            stop_hit = _local_stop_hit(current_direction, snapshot, best_close)
            if (
                target_direction == 0
                or current_direction != target_direction
                or current_symbol != target_contract
                or stop_hit
            ):
                if stop_hit:
                    reason = "trailing_or_ma_stop"
                _schedule_close(
                    scheduled,
                    next_date.get(trade_date),
                    trade_date,
                    current_symbol,
                    current_direction,
                    reason,
                    int(params["cooldown_days"]),
                )
        elif cooldown > 0:
            cooldown -= 1
            reason = "cooldown"
        elif target_direction:
            price_bar = _latest_contract_bar(contract_by_key, target_contract, trade_date)
            if price_bar is None:
                reason = "no_contract_price"
            else:
                margin_used = abs(current_quantity * current_direction) * float(price_bar["close"]) * config.contract_multiplier * params["margin_rate"]
                available_cash = max(0.0, equity - margin_used)
                dd = drawdown_multiplier(equity, high_water)
                total_risk = (
                    dd
                    * float(snapshot["regime_multiplier"])
                    * float(snapshot["trend_multiplier"])
                    * float(snapshot["signal_multiplier"])
                )
                quantity = risk_scaled_amount(
                    equity,
                    available_cash,
                    float(price_bar["close"]),
                    float(snapshot["realized_vol"]),
                    total_risk,
                    params,
                )
                if quantity <= 0:
                    reason = "risk_block"
                else:
                    _schedule_open(
                        scheduled,
                        next_date.get(trade_date),
                        trade_date,
                        target_contract,
                        target_direction,
                        quantity,
                    )
                    reason = "scheduled_entry"

        signal_rows.append(
            {
                "signal_date": trade_date,
                "signal": int(snapshot["signal"]),
                "signal_multiplier": float(snapshot["signal_multiplier"]),
                "target_direction": target_direction,
                "target_contract": target_contract or "",
                "efficiency_ratio": float(snapshot["efficiency_ratio"]),
                "direction_consistency": float(snapshot["direction_consistency"]),
                "volatility_ratio": float(snapshot["volatility_ratio"]),
                "regime_multiplier": float(snapshot["regime_multiplier"]),
                "risk_multiplier": float(
                    drawdown_multiplier(equity, high_water)
                    * float(snapshot["regime_multiplier"])
                    * float(snapshot["trend_multiplier"])
                    * float(snapshot["signal_multiplier"])
                ),
                "reason": reason,
            }
        )

    equity_curve = pd.DataFrame(equity_rows)
    trades = pd.DataFrame(trade_rows)
    signals = pd.DataFrame(signal_rows)
    if equity_curve.empty:
        raise ValueError("backtest produced no equity rows")
    metrics = calculate_metrics(equity_curve, _round_trip_trades(trades))
    return IronOreBacktestResult(signals, trades, equity_curve, metrics)


def _prepare_bars(frame: pd.DataFrame, expected_symbol: str) -> pd.DataFrame:
    required = {"symbol", "trade_date", "open", "high", "low", "close"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"main_daily missing required columns: {sorted(missing)}")
    rows = frame.copy()
    rows["symbol"] = rows["symbol"].astype(str).str.upper()
    if set(rows["symbol"]) != {expected_symbol}:
        raise ValueError(f"main_daily must contain only {expected_symbol}")
    rows["trade_date"] = pd.to_datetime(rows["trade_date"]).dt.normalize()
    for column in ["open", "high", "low", "close"]:
        rows[column] = pd.to_numeric(rows[column], errors="coerce")
    if rows[["open", "high", "low", "close"]].isna().any().any():
        raise ValueError("main_daily contains null OHLC")
    return rows.sort_values("trade_date").drop_duplicates("trade_date").reset_index(drop=True)


def _prepare_contract_bars(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"symbol", "trade_date", "open", "high", "low", "close"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"contract_daily missing required columns: {sorted(missing)}")
    rows = frame.copy()
    rows["symbol"] = rows["symbol"].astype(str).str.upper()
    if not rows["symbol"].map(lambda value: bool(IRON_ORE_CODE_RE.fullmatch(value))).all():
        raise ValueError("contract_daily contains an invalid contract code")
    rows["trade_date"] = pd.to_datetime(rows["trade_date"]).dt.normalize()
    for column in ["open", "high", "low", "close"]:
        rows[column] = pd.to_numeric(rows[column], errors="coerce")
    if rows[["open", "high", "low", "close"]].isna().any().any():
        raise ValueError("contract_daily contains null OHLC")
    return rows.sort_values(["symbol", "trade_date"]).drop_duplicates(["symbol", "trade_date"])


def _validate_contract_metadata(contracts: pd.DataFrame) -> None:
    required = {"symbol", "list_date", "end_date"}
    missing = required.difference(contracts.columns)
    if missing:
        raise ValueError(f"contracts missing required columns: {sorted(missing)}")
    codes = contracts["symbol"].astype(str).str.upper()
    if not codes.map(lambda value: bool(IRON_ORE_CODE_RE.fullmatch(value))).all():
        raise ValueError("contracts contains an invalid contract code")


def _latest_contract_bar(indexed: pd.DataFrame, symbol: str | None, date: pd.Timestamp) -> pd.Series | None:
    if not symbol:
        return None
    try:
        rows = indexed.loc[symbol]
    except KeyError:
        return None
    rows = rows.loc[rows.index <= date]
    if rows.empty:
        return None
    return rows.iloc[-1]


def _mark_position(
    symbol: str | None,
    direction: int,
    quantity: int,
    entry_price: float,
    date: pd.Timestamp,
    indexed: pd.DataFrame,
    multiplier: int = 100,
) -> tuple[float | None, float, float]:
    bar = _latest_contract_bar(indexed, symbol, date)
    if bar is None or direction == 0 or quantity <= 0:
        return None, 0.0, 0.0
    close = float(bar["close"])
    unrealized = direction * (close - entry_price) * quantity * multiplier
    return close, unrealized, unrealized


def _local_stop_hit(direction: int, snapshot: dict[str, object], best_close: float | None) -> bool:
    atr_value = float(snapshot["atr"])
    close = float(snapshot["close"])
    fast = float(snapshot["ma_fast"])
    params = snapshot["params"]
    if atr_value <= 0:
        return False
    ma_stop = (
        close < fast - params["stop_atr"] * atr_value
        if direction > 0
        else close > fast + params["stop_atr"] * atr_value
    )
    return ma_stop or trailing_stop_hit(direction, close, best_close, atr_value, params["stop_atr"])


def _schedule_close(
    scheduled: dict[pd.Timestamp, dict[str, object]],
    execution_date: pd.Timestamp | None,
    signal_date: pd.Timestamp,
    symbol: str | None,
    direction: int,
    reason: str,
    cooldown_days: int,
) -> None:
    if execution_date is not None and symbol:
        scheduled[execution_date] = {
            "kind": "close",
            "signal_date": signal_date,
            "symbol": symbol,
            "direction": direction,
            "reason": reason,
            "cooldown_days": cooldown_days,
        }


def _schedule_open(
    scheduled: dict[pd.Timestamp, dict[str, object]],
    execution_date: pd.Timestamp | None,
    signal_date: pd.Timestamp,
    symbol: str | None,
    direction: int,
    quantity: int,
) -> None:
    if execution_date is not None and symbol:
        scheduled[execution_date] = {
            "kind": "open",
            "signal_date": signal_date,
            "symbol": symbol,
            "direction": direction,
            "quantity": quantity,
        }


def _execute_scheduled_order(
    order: dict[str, object],
    execution_date: pd.Timestamp,
    indexed: pd.DataFrame,
    config: IronOreBacktestConfig,
    state: dict[str, object],
    trade_rows: list[dict[str, object]],
) -> dict[str, object]:
    symbol = str(order["symbol"])
    bar = _latest_contract_bar(indexed, symbol, execution_date)
    if bar is None:
        return state
    raw_open = float(bar["open"])
    direction = int(order["direction"])
    if order["kind"] == "close":
        current_direction = int(state["current_direction"])
        quantity = int(state["current_quantity"])
        if quantity <= 0:
            return state
        fill = raw_open - config.slippage_points if current_direction > 0 else raw_open + config.slippage_points
        entry_price = float(state["entry_price"])
        pnl = current_direction * (fill - entry_price) * quantity * config.contract_multiplier
        fee = abs(fill * quantity * config.contract_multiplier) * config.close_commission
        state["cash"] = float(state["cash"]) + pnl - fee
        trade_rows.append(
            {
                "signal_date": order["signal_date"],
                "execution_date": execution_date,
                "symbol": symbol,
                "side": "long_exit" if current_direction > 0 else "short_exit",
                "direction": current_direction,
                "quantity": quantity,
                "price": fill,
                "pnl": pnl - fee,
                "reason": order["reason"],
            }
        )
        state["current_symbol"] = None
        state["current_direction"] = 0
        state["current_quantity"] = 0
        state["entry_price"] = 0.0
        state["entry_signal_date"] = None
        state["best_close"] = None
        state["cooldown"] = int(order.get("cooldown_days", 0))
        return state
    quantity = int(order["quantity"])
    fill = raw_open + config.slippage_points if direction > 0 else raw_open - config.slippage_points
    fee = abs(fill * quantity * config.contract_multiplier) * config.open_commission
    state["cash"] = float(state["cash"]) - fee
    state["current_symbol"] = symbol
    state["current_direction"] = direction
    state["current_quantity"] = quantity
    state["entry_price"] = fill
    state["entry_signal_date"] = order["signal_date"]
    state["best_close"] = fill
    trade_rows.append(
        {
            "signal_date": order["signal_date"],
            "execution_date": execution_date,
            "symbol": symbol,
            "side": "long_entry" if direction > 0 else "short_entry",
            "direction": direction,
            "quantity": quantity,
            "price": fill,
            "pnl": -fee,
            "reason": "scheduled_entry",
        }
    )
    return state


def _round_trip_trades(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame(columns=["return_pct"])
    entries = trades.loc[trades["side"].isin(["long_entry", "short_entry"])].copy()
    exits = trades.loc[trades["side"].isin(["long_exit", "short_exit"])].copy()
    rows = []
    for entry in entries.itertuples(index=False):
        candidates = exits.loc[
            (exits["symbol"] == entry.symbol)
            & (pd.to_datetime(exits["execution_date"]) > pd.Timestamp(entry.execution_date))
        ]
        if candidates.empty:
            continue
        exit_row = candidates.iloc[0]
        sign = 1.0 if entry.direction > 0 else -1.0
        rows.append(
            {
                "entry_date": entry.execution_date,
                "exit_date": exit_row["execution_date"],
                "return_pct": sign * (float(exit_row["price"]) - float(entry.price)) / max(abs(float(entry.price)), 1e-9),
            }
        )
    return pd.DataFrame(rows, columns=["entry_date", "exit_date", "return_pct"])
