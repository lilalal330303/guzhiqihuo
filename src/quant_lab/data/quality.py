from __future__ import annotations

import pandas as pd


def repair_split_like_price_jumps(prices: pd.DataFrame, threshold: float = 0.25) -> pd.DataFrame:
    required = {"symbol", "trade_date", "open", "high", "low", "close", "amount"}
    missing = required.difference(prices.columns)
    if missing:
        raise ValueError(f"prices missing required columns: {sorted(missing)}")
    if prices.empty:
        return prices.copy()

    rows = prices.copy()
    rows["trade_date"] = pd.to_datetime(rows["trade_date"])
    adjustable_columns = ["open", "high", "low", "close", "amount"]
    for column in adjustable_columns:
        rows[column] = pd.to_numeric(rows[column], errors="coerce").astype(float)
    repaired = []
    for _, group in rows.sort_values(["symbol", "trade_date"]).groupby("symbol", sort=False):
        fixed = group.copy()
        fixed = fixed.reset_index(drop=True)
        for index in range(1, len(fixed)):
            prev_close = float(fixed.loc[index - 1, "close"])
            current_close = float(fixed.loc[index, "close"])
            if prev_close <= 0 or current_close <= 0:
                continue
            ratio = current_close / prev_close
            if abs(ratio - 1.0) <= threshold:
                continue
            fixed.loc[: index - 1, adjustable_columns] = fixed.loc[: index - 1, adjustable_columns] * ratio
        repaired.append(fixed)
    return pd.concat(repaired, ignore_index=True)


def detect_split_like_price_jump_events(prices: pd.DataFrame, threshold: float = 0.25) -> pd.DataFrame:
    required = {"symbol", "trade_date", "close"}
    missing = required.difference(prices.columns)
    if missing:
        raise ValueError(f"prices missing required columns: {sorted(missing)}")
    if prices.empty:
        return pd.DataFrame(
            columns=["symbol", "event_date", "previous_trade_date", "previous_close", "current_close", "daily_return", "repair_ratio"]
        )

    rows = prices.copy()
    rows["trade_date"] = pd.to_datetime(rows["trade_date"])
    rows["close"] = pd.to_numeric(rows["close"], errors="coerce").astype(float)
    events: list[dict[str, object]] = []
    for symbol, group in rows.sort_values(["symbol", "trade_date"]).groupby("symbol", sort=False):
        fixed_closes = group[["trade_date", "close"]].reset_index(drop=True).copy()
        for index in range(1, len(fixed_closes)):
            prev_close = float(fixed_closes.loc[index - 1, "close"])
            current_close = float(fixed_closes.loc[index, "close"])
            if prev_close <= 0 or current_close <= 0:
                continue
            ratio = current_close / prev_close
            daily_return = ratio - 1.0
            if abs(daily_return) <= threshold:
                continue
            events.append(
                {
                    "symbol": symbol,
                    "event_date": fixed_closes.loc[index, "trade_date"],
                    "previous_trade_date": fixed_closes.loc[index - 1, "trade_date"],
                    "previous_close": prev_close,
                    "current_close": current_close,
                    "daily_return": daily_return,
                    "repair_ratio": ratio,
                }
            )
            fixed_closes.loc[: index - 1, "close"] = fixed_closes.loc[: index - 1, "close"] * ratio
    return pd.DataFrame(
        events,
        columns=["symbol", "event_date", "previous_trade_date", "previous_close", "current_close", "daily_return", "repair_ratio"],
    )
