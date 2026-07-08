from __future__ import annotations

import pandas as pd


def build_etf_universe_snapshots(
    metadata: pd.DataFrame,
    trade_dates: pd.Series | pd.DatetimeIndex | list[pd.Timestamp],
    prices: pd.DataFrame | None = None,
) -> pd.DataFrame:
    required = {"symbol", "name"}
    missing = required.difference(metadata.columns)
    if missing:
        raise ValueError(f"metadata missing required columns: {sorted(missing)}")

    meta = metadata[["symbol", "name"]].drop_duplicates("symbol").copy()
    meta["symbol"] = meta["symbol"].astype(str)
    dates = pd.Series(pd.to_datetime(list(trade_dates))).drop_duplicates().sort_values()
    if dates.empty or meta.empty:
        return pd.DataFrame(columns=["trade_date", "symbol", "name", "is_active"])

    coverage = _price_coverage(prices)
    rows: list[pd.DataFrame] = []
    for trade_date in dates:
        daily = meta.copy()
        daily["trade_date"] = trade_date
        if coverage.empty:
            daily["is_active"] = True
        else:
            joined = daily.join(coverage, on="symbol")
            daily["is_active"] = (
                joined["first_trade_date"].notna()
                & (joined["first_trade_date"] <= trade_date)
                & (joined["last_trade_date"] >= trade_date)
            )
        rows.append(daily[["trade_date", "symbol", "name", "is_active"]])
    return pd.concat(rows, ignore_index=True)


def _price_coverage(prices: pd.DataFrame | None) -> pd.DataFrame:
    if prices is None or prices.empty:
        return pd.DataFrame()
    required = {"symbol", "trade_date"}
    missing = required.difference(prices.columns)
    if missing:
        raise ValueError(f"prices missing required columns: {sorted(missing)}")
    rows = prices.copy()
    rows["symbol"] = rows["symbol"].astype(str)
    rows["trade_date"] = pd.to_datetime(rows["trade_date"])
    return rows.groupby("symbol")["trade_date"].agg(first_trade_date="min", last_trade_date="max")
