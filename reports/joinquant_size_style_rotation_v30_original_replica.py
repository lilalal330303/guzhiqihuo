"""V3.0 original-replica adapters.

The default mode intentionally reproduces the original backtest date
semantics; STRICT_ASOF is provided only as a research comparison mode.
"""

import numpy as np
import pandas as pd

from jqdata import *


RUN_MODE = "ORIGINAL_REPLICA"
INDEX_2000 = "399303.XSHE"
INDEX_500 = "399905.XSHE"
MARKET_INDEX = "000985.XSHG"


def fundamental_date(context):
    return context.previous_date if RUN_MODE == "STRICT_ASOF" else None


def constituent_date(context):
    return context.previous_date if RUN_MODE == "STRICT_ASOF" else context.current_dt


def select_style_branch(mean_2000, mean_500, ratio_threshold=1.2):
    try:
        numerator = float(mean_2000)
        denominator = float(mean_500)
        threshold = float(ratio_threshold)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(numerator) or not np.isfinite(denominator):
        return None
    if abs(denominator) <= 1e-12:
        return None
    return "BIG" if numerator / denominator > threshold else "SMALL"


def _date_column(columns):
    preferred = {"date", "datetime", "time", "trade_date", "交易日期"}
    for column in columns:
        if str(column).lower() in preferred:
            return column
    return None


def _code_column(columns):
    preferred = {"code", "security", "symbol", "stock", "证券代码"}
    for column in columns:
        if str(column).lower() in preferred:
            return column
    return None


def _coerce_dates(values):
    return pd.to_datetime(values, errors="coerce")


def _finish_close_frame(frame):
    if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
        return None

    result = frame.copy()
    result.index = _coerce_dates(result.index)
    result = result.loc[~result.index.isna()]
    if result.empty:
        return None

    for column in result.columns:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    result = result.groupby(level=0, sort=True).last()
    result = result.dropna(axis=1, how="all")
    if result.empty:
        return None
    return result.sort_index()


def _multiindex_close_frame(raw_prices):
    if "close" not in raw_prices.columns or raw_prices.index.nlevels != 2:
        return None

    reset = raw_prices.reset_index()
    date_column = _date_column(reset.columns)
    code_column = _code_column(reset.columns)
    index_columns = list(reset.columns[:2]) if date_column is None else []

    if date_column is None:
        date_candidates = []
        for column in index_columns:
            parsed = _coerce_dates(reset[column])
            date_candidates.append((parsed.notna().sum(), column))
        if not date_candidates:
            return None
        date_column = max(date_candidates)[1]
    if code_column is None:
        code_candidates = [column for column in index_columns if column != date_column]
        if not code_candidates:
            code_candidates = [column for column in reset.columns if column != date_column and column != "close"]
        if not code_candidates:
            return None
        code_column = code_candidates[0]

    dates = _coerce_dates(reset[date_column])
    valid = reset.loc[dates.notna(), [date_column, code_column, "close"]].copy()
    valid[date_column] = dates.loc[valid.index]
    if valid.empty:
        return None
    valid["close"] = pd.to_numeric(valid["close"], errors="coerce")
    return valid.pivot_table(
        index=date_column,
        columns=code_column,
        values="close",
        aggfunc="last",
    )


def _long_close_frame(raw_prices):
    if "close" not in raw_prices.columns:
        return None

    date_column = _date_column(raw_prices.columns)
    code_column = _code_column(raw_prices.columns)
    if date_column is None:
        index_dates = _coerce_dates(raw_prices.index)
        if not index_dates.notna().any():
            return None
        working = raw_prices.reset_index()
        date_column = working.columns[0]
        working[date_column] = index_dates
    else:
        working = raw_prices.copy()
    if code_column is None or date_column == code_column:
        return None

    dates = _coerce_dates(working[date_column])
    valid = working.loc[dates.notna(), [date_column, code_column, "close"]].copy()
    valid[date_column] = dates.loc[valid.index]
    if valid.empty:
        return None
    valid["close"] = pd.to_numeric(valid["close"], errors="coerce")
    return valid.pivot_table(
        index=date_column,
        columns=code_column,
        values="close",
        aggfunc="last",
    )


def safe_close_frame(raw_prices):
    """Return a sorted date-indexed wide numeric close frame when usable."""
    if raw_prices is None or not isinstance(raw_prices, pd.DataFrame) or raw_prices.empty:
        return None

    if isinstance(raw_prices.index, pd.MultiIndex):
        normalized = _multiindex_close_frame(raw_prices)
        return _finish_close_frame(normalized)

    if "close" in raw_prices.columns and _code_column(raw_prices.columns) is not None:
        normalized = _long_close_frame(raw_prices)
        return _finish_close_frame(normalized)

    return _finish_close_frame(raw_prices)
