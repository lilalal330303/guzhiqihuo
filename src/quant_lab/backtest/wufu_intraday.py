from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class WufuIntradayTimingConfig:
    initial_cash: float = 1_000_000.0
    commission_rate: float = 0.0001
    slippage_rate: float = 0.0001
    min_commission: float = 5.0
    cash_buffer: float = 0.998
    round_lot: int = 100
    trend_lookback_minutes: int = 30
    trend_slope_threshold: float = 0.001
    fixed_stop_loss_threshold: float = 0.95
    intraday_entry_weight: float = 0.65
    initial_entry_minute: int | None = None
    trend_check_minutes: tuple[int, ...] = (1311, 1340, 1410, 1440)
    force_buy_minute: int = 1455
    stop_loss_windows: tuple[tuple[int, int], ...] = ((941, 1028), (1041, 1129), (1301, 1456))


def run_wufu_intraday_proxy_backtest(
    prices: pd.DataFrame,
    targets: pd.DataFrame,
    config: WufuIntradayTimingConfig | None = None,
) -> dict[str, pd.DataFrame]:
    """Run a daily-OHLC proxy for Wufu intraday timing.

    The true platform rule uses 1-minute bars. Local minute history is not
    always available, so this proxy estimates the 13:11 entry price from the
    daily open-close path and uses the daily low to model a 5% fixed stop.
    """

    cfg = config or WufuIntradayTimingConfig()
    required_prices = {"symbol", "trade_date", "open", "high", "low", "close"}
    missing_prices = required_prices.difference(prices.columns)
    if missing_prices:
        raise ValueError(f"prices missing required columns: {sorted(missing_prices)}")
    required_targets = {"trade_date", "target_symbol"}
    missing_targets = required_targets.difference(targets.columns)
    if missing_targets:
        raise ValueError(f"targets missing required columns: {sorted(missing_targets)}")

    rows = prices.copy()
    rows["trade_date"] = pd.to_datetime(rows["trade_date"])
    pivots = {
        field: rows.pivot_table(index="trade_date", columns="symbol", values=field, aggfunc="last").sort_index()
        for field in ["open", "high", "low", "close"]
    }
    close = pivots["close"].ffill()
    target_rows = targets[["trade_date", "target_symbol"]].copy()
    target_rows["trade_date"] = pd.to_datetime(target_rows["trade_date"])
    target_by_date = target_rows.drop_duplicates("trade_date", keep="last").set_index("trade_date")["target_symbol"]
    target_by_date = target_by_date.reindex(close.index).ffill()

    cash = cfg.initial_cash
    held_symbol: str | None = None
    shares = 0
    entry_price = 0.0
    equity_rows: list[dict[str, object]] = []
    trade_rows: list[dict[str, object]] = []

    shifted_target = target_by_date.shift(1)
    for trade_date in close.index:
        desired_raw = shifted_target.get(trade_date)
        desired = None if pd.isna(desired_raw) else str(desired_raw)
        if desired and desired not in close.columns:
            desired = None

        if held_symbol and shares > 0:
            low_price = _price_at(pivots["low"], trade_date, held_symbol)
            if low_price > 0 and entry_price > 0 and low_price <= entry_price * cfg.fixed_stop_loss_threshold:
                stop_price = entry_price * cfg.fixed_stop_loss_threshold
                cash += _sell_value_after_cost(shares, stop_price, cfg)
                trade_rows.append(_trade_row(trade_date, "stop_loss_sell", held_symbol, stop_price, shares, cfg))
                held_symbol = None
                shares = 0
                entry_price = 0.0

        if desired != held_symbol:
            if held_symbol and shares > 0:
                sell_price = _price_at(close, trade_date, held_symbol)
                cash += _sell_value_after_cost(shares, sell_price, cfg)
                trade_rows.append(_trade_row(trade_date, "sell", held_symbol, sell_price, shares, cfg))
                held_symbol = None
                shares = 0
                entry_price = 0.0

            if desired:
                buy_price, mode, trend_slope_pct = _proxy_entry_price(pivots, trade_date, desired, cfg)
                if buy_price > 0:
                    total_value = cash
                    budget = max(0.0, total_value * cfg.cash_buffer - cfg.min_commission)
                    buy_shares = int(budget / (buy_price * (1.0 + cfg.commission_rate)) / cfg.round_lot) * cfg.round_lot
                    buy_notional = buy_shares * buy_price
                    buy_cost = _cost(buy_notional, cfg)
                    if buy_shares > 0 and buy_notional + buy_cost <= cash + 1e-6:
                        cash -= buy_notional + buy_cost
                        held_symbol = desired
                        shares = buy_shares
                        entry_price = buy_price
                        trade = _trade_row(trade_date, "buy", desired, buy_price, buy_shares, cfg)
                        trade["entry_mode"] = mode
                        trade["trend_slope_pct"] = trend_slope_pct
                        trade_rows.append(trade)

        mark_price = _price_at(close, trade_date, held_symbol) if held_symbol else 0.0
        position_value = shares * mark_price if held_symbol else 0.0
        equity_rows.append(
            {
                "trade_date": trade_date.date(),
                "target_symbol": desired,
                "held_symbol": held_symbol,
                "shares": shares,
                "cash": cash,
                "position_value": position_value,
                "equity": cash + position_value,
            }
        )

    return {"equity": pd.DataFrame(equity_rows), "trades": pd.DataFrame(trade_rows)}


def run_wufu_intraday_real_backtest(
    prices: pd.DataFrame,
    targets: pd.DataFrame,
    minute_bars: pd.DataFrame,
    config: WufuIntradayTimingConfig | None = None,
) -> dict[str, pd.DataFrame]:
    """Run Wufu intraday timing with real 1-minute bars when available.

    Missing minute days fall back to the daily-OHLC proxy path so full-cycle
    experiments remain runnable while the local minute store is being filled.
    """

    cfg = config or WufuIntradayTimingConfig()
    required_minutes = {"symbol", "trade_date", "minute", "close"}
    missing_minutes = required_minutes.difference(minute_bars.columns)
    if missing_minutes and not minute_bars.empty:
        raise ValueError(f"minute_bars missing required columns: {sorted(missing_minutes)}")

    rows = prices.copy()
    rows["trade_date"] = pd.to_datetime(rows["trade_date"])
    pivots = {
        field: rows.pivot_table(index="trade_date", columns="symbol", values=field, aggfunc="last").sort_index()
        for field in ["open", "high", "low", "close"]
    }
    close = pivots["close"].ffill()

    minutes = _normalize_minutes_for_backtest(minute_bars)
    minute_groups = {key: frame.sort_values("minute") for key, frame in minutes.groupby(["trade_date", "symbol"])}

    target_rows = targets[["trade_date", "target_symbol"]].copy()
    target_rows["trade_date"] = pd.to_datetime(target_rows["trade_date"])
    target_by_date = target_rows.drop_duplicates("trade_date", keep="last").set_index("trade_date")["target_symbol"]
    target_by_date = target_by_date.reindex(close.index).ffill()

    cash = cfg.initial_cash
    held_symbol: str | None = None
    shares = 0
    entry_price = 0.0
    equity_rows: list[dict[str, object]] = []
    trade_rows: list[dict[str, object]] = []
    shifted_target = target_by_date.shift(1)

    for trade_date in close.index:
        date_text = trade_date.strftime("%Y-%m-%d")
        desired_raw = shifted_target.get(trade_date)
        desired = None if pd.isna(desired_raw) else str(desired_raw)
        if desired and desired not in close.columns:
            desired = None

        if held_symbol and shares > 0:
            stop = _first_stop_loss_from_minutes(
                minute_groups.get((date_text, held_symbol)),
                entry_price,
                cfg,
                end_minute=_pre_entry_end_minute(cfg) if desired != held_symbol else None,
            )
            if stop is None and (date_text, held_symbol) not in minute_groups:
                stop = _proxy_stop_loss(pivots, trade_date, held_symbol, entry_price, cfg)
            if stop is not None:
                stop_minute, stop_price, stop_mode = stop
                cash += _sell_value_after_cost(shares, stop_price, cfg)
                trade = _trade_row(trade_date, "stop_loss_sell", held_symbol, stop_price, shares, cfg)
                trade["minute"] = stop_minute
                trade["execution_mode"] = stop_mode
                trade_rows.append(trade)
                held_symbol = None
                shares = 0
                entry_price = 0.0

        if desired != held_symbol:
            if held_symbol and shares > 0:
                sell_price, sell_minute, sell_mode = _minute_price_or_daily_close(
                    minute_groups.get((date_text, held_symbol)), trade_date, held_symbol, pivots["close"], _entry_minute(cfg)
                )
                cash += _sell_value_after_cost(shares, sell_price, cfg)
                trade = _trade_row(trade_date, "sell", held_symbol, sell_price, shares, cfg)
                trade["minute"] = sell_minute
                trade["execution_mode"] = sell_mode
                trade_rows.append(trade)
                held_symbol = None
                shares = 0
                entry_price = 0.0

            if desired:
                buy_price, mode, trend_slope_pct, buy_minute = _real_or_proxy_entry_price(
                    minute_groups.get((date_text, desired)), pivots, trade_date, desired, cfg
                )
                if buy_price > 0:
                    total_value = cash
                    budget = max(0.0, total_value * cfg.cash_buffer - cfg.min_commission)
                    buy_shares = int(budget / (buy_price * (1.0 + cfg.commission_rate)) / cfg.round_lot) * cfg.round_lot
                    buy_notional = buy_shares * buy_price
                    buy_cost = _cost(buy_notional, cfg)
                    if buy_shares > 0 and buy_notional + buy_cost <= cash + 1e-6:
                        cash -= buy_notional + buy_cost
                        held_symbol = desired
                        shares = buy_shares
                        entry_price = buy_price
                        trade = _trade_row(trade_date, "buy", desired, buy_price, buy_shares, cfg)
                        trade["entry_mode"] = mode
                        trade["trend_slope_pct"] = trend_slope_pct
                        trade["minute"] = buy_minute
                        trade_rows.append(trade)

        if held_symbol and shares > 0:
            last_buy = trade_rows[-1] if trade_rows and trade_rows[-1].get("action") == "buy" and trade_rows[-1].get("symbol") == held_symbol else None
            start_minute = int(last_buy["minute"]) + 1 if last_buy and last_buy.get("minute") else 0
            stop = _first_stop_loss_from_minutes(
                minute_groups.get((date_text, held_symbol)),
                entry_price,
                cfg,
                start_minute=start_minute,
            )
            if stop is not None:
                stop_minute, stop_price, stop_mode = stop
                cash += _sell_value_after_cost(shares, stop_price, cfg)
                trade = _trade_row(trade_date, "stop_loss_sell", held_symbol, stop_price, shares, cfg)
                trade["minute"] = stop_minute
                trade["execution_mode"] = stop_mode
                trade_rows.append(trade)
                held_symbol = None
                shares = 0
                entry_price = 0.0

        mark_price = _price_at(close, trade_date, held_symbol) if held_symbol else 0.0
        position_value = shares * mark_price if held_symbol else 0.0
        equity_rows.append(
            {
                "trade_date": trade_date.date(),
                "target_symbol": desired,
                "held_symbol": held_symbol,
                "shares": shares,
                "cash": cash,
                "position_value": position_value,
                "equity": cash + position_value,
            }
        )

    return {"equity": pd.DataFrame(equity_rows), "trades": pd.DataFrame(trade_rows)}


def _proxy_entry_price(
    pivots: dict[str, pd.DataFrame],
    trade_date: pd.Timestamp,
    symbol: str,
    cfg: WufuIntradayTimingConfig,
) -> tuple[float, str, float]:
    open_price = _price_at(pivots["open"], trade_date, symbol)
    close_price = _price_at(pivots["close"], trade_date, symbol)
    if open_price <= 0 or close_price <= 0:
        return 0.0, "missing", 0.0
    trend_slope_pct = ((close_price / open_price) - 1.0) * 100.0 / max(cfg.trend_lookback_minutes, 1)
    if trend_slope_pct > cfg.trend_slope_threshold:
        intraday_price = open_price + (close_price - open_price) * cfg.intraday_entry_weight
        return intraday_price * (1.0 + cfg.slippage_rate), "trend", float(trend_slope_pct)
    return close_price * (1.0 + cfg.slippage_rate), "force", float(trend_slope_pct)


def _real_or_proxy_entry_price(
    minute_rows: pd.DataFrame | None,
    pivots: dict[str, pd.DataFrame],
    trade_date: pd.Timestamp,
    symbol: str,
    cfg: WufuIntradayTimingConfig,
) -> tuple[float, str, float, int | None]:
    if minute_rows is None or minute_rows.empty:
        price, mode, slope = _proxy_entry_price(pivots, trade_date, symbol, cfg)
        return price, f"{mode}_proxy", slope, None

    if cfg.initial_entry_minute is not None:
        price = _minute_price_at_or_before(minute_rows, cfg.initial_entry_minute)
        if price > 0:
            return price * (1.0 + cfg.slippage_rate), "initial_real", 0.0, cfg.initial_entry_minute

    for check_minute in cfg.trend_check_minutes:
        closes = minute_rows.loc[minute_rows["minute"] <= check_minute, "close"].astype(float).tail(cfg.trend_lookback_minutes)
        closes = closes[closes > 0]
        if len(closes) < 5:
            continue
        x = np.arange(len(closes), dtype="float64")
        slope = float(np.polyfit(x, closes.to_numpy(), 1)[0])
        mean_price = float(closes.mean())
        slope_pct = slope / mean_price * 100.0 if mean_price > 0 else 0.0
        if slope_pct > cfg.trend_slope_threshold:
            price = _minute_price_at_or_before(minute_rows, check_minute)
            if price > 0:
                return price * (1.0 + cfg.slippage_rate), "trend_real", slope_pct, check_minute

    force_price = _minute_price_at_or_before(minute_rows, cfg.force_buy_minute)
    if force_price > 0:
        return force_price * (1.0 + cfg.slippage_rate), "force_real", 0.0, cfg.force_buy_minute
    price, mode, slope = _proxy_entry_price(pivots, trade_date, symbol, cfg)
    return price, f"{mode}_proxy", slope, None


def _first_stop_loss_from_minutes(
    minute_rows: pd.DataFrame | None,
    entry_price: float,
    cfg: WufuIntradayTimingConfig,
    *,
    start_minute: int = 0,
    end_minute: int | None = None,
) -> tuple[int, float, str] | None:
    if minute_rows is None or minute_rows.empty or entry_price <= 0:
        return None
    threshold = entry_price * cfg.fixed_stop_loss_threshold
    rows = minute_rows[minute_rows["minute"] >= start_minute].copy()
    if end_minute is not None:
        rows = rows[rows["minute"] <= end_minute]
    if rows.empty:
        return None
    price_field = "low" if "low" in rows.columns else "close"
    rows = rows[rows["minute"].map(lambda minute: _is_stop_loss_minute(minute, cfg))]
    rows = rows[pd.to_numeric(rows[price_field], errors="coerce") <= threshold]
    if rows.empty:
        return None
    first = rows.sort_values("minute").iloc[0]
    return int(first["minute"]), float(threshold), "stop_real"


def _proxy_stop_loss(
    pivots: dict[str, pd.DataFrame],
    trade_date: pd.Timestamp,
    symbol: str,
    entry_price: float,
    cfg: WufuIntradayTimingConfig,
) -> tuple[int | None, float, str] | None:
    low_price = _price_at(pivots["low"], trade_date, symbol)
    if low_price > 0 and entry_price > 0 and low_price <= entry_price * cfg.fixed_stop_loss_threshold:
        return None, entry_price * cfg.fixed_stop_loss_threshold, "stop_proxy"
    return None


def _minute_price_or_daily_close(
    minute_rows: pd.DataFrame | None,
    trade_date: pd.Timestamp,
    symbol: str,
    close: pd.DataFrame,
    minute: int,
) -> tuple[float, int | None, str]:
    price = _minute_price_at_or_before(minute_rows, minute)
    if price > 0:
        return price, minute, "minute"
    return _price_at(close, trade_date, symbol), None, "daily_close"


def _minute_price_at_or_before(minute_rows: pd.DataFrame | None, minute: int) -> float:
    if minute_rows is None or minute_rows.empty:
        return 0.0
    rows = minute_rows[minute_rows["minute"] <= minute].sort_values("minute")
    if rows.empty:
        return 0.0
    value = rows.iloc[-1]["close"]
    return 0.0 if pd.isna(value) else float(value)


def _normalize_minutes_for_backtest(minute_bars: pd.DataFrame) -> pd.DataFrame:
    if minute_bars.empty:
        return pd.DataFrame(columns=["symbol", "trade_date", "minute", "close", "low"])
    rows = minute_bars.copy()
    rows["symbol"] = rows["symbol"].astype(str).map(_strip_exchange_suffix)
    rows["trade_date"] = pd.to_datetime(rows["trade_date"]).dt.strftime("%Y-%m-%d")
    rows["minute"] = pd.to_numeric(rows["minute"], errors="coerce").astype("Int64")
    rows["close"] = pd.to_numeric(rows["close"], errors="coerce")
    if "low" in rows.columns:
        rows["low"] = pd.to_numeric(rows["low"], errors="coerce")
    else:
        rows["low"] = rows["close"]
    rows = rows.dropna(subset=["symbol", "trade_date", "minute", "close"])
    rows["minute"] = rows["minute"].astype(int)
    return rows[["symbol", "trade_date", "minute", "close", "low"]].drop_duplicates(
        ["symbol", "trade_date", "minute"], keep="last"
    )


def _is_stop_loss_minute(minute: int, cfg: WufuIntradayTimingConfig) -> bool:
    return any(start <= minute <= end for start, end in cfg.stop_loss_windows)


def _entry_minute(cfg: WufuIntradayTimingConfig) -> int:
    if cfg.initial_entry_minute is not None:
        return int(cfg.initial_entry_minute)
    return 1311


def _pre_entry_end_minute(cfg: WufuIntradayTimingConfig) -> int:
    return _entry_minute(cfg) - 1


def _strip_exchange_suffix(symbol: str) -> str:
    return str(symbol).split(".")[0]


def _price_at(frame: pd.DataFrame, trade_date: pd.Timestamp, symbol: str | None) -> float:
    if not symbol or symbol not in frame.columns or trade_date not in frame.index:
        return 0.0
    value = frame.at[trade_date, symbol]
    return 0.0 if pd.isna(value) else float(value)


def _cost(notional: float, cfg: WufuIntradayTimingConfig) -> float:
    if notional <= 0:
        return 0.0
    return max(notional * cfg.commission_rate, cfg.min_commission) + notional * cfg.slippage_rate


def _sell_value_after_cost(shares: int, price: float, cfg: WufuIntradayTimingConfig) -> float:
    notional = max(0.0, shares * price)
    return notional - _cost(notional, cfg)


def _trade_row(
    trade_date: pd.Timestamp,
    action: str,
    symbol: str,
    price: float,
    shares: int,
    cfg: WufuIntradayTimingConfig,
) -> dict[str, object]:
    notional = max(0.0, shares * price)
    return {
        "trade_date": trade_date.date(),
        "action": action,
        "symbol": symbol,
        "price": price,
        "shares": shares,
        "notional": notional,
        "cost": _cost(notional, cfg),
    }
