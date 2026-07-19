"""Original-compatible size-style signal and price-shape normalization.

This Task 2 module intentionally omits the JoinQuant scheduling, candidate
selection, and order runtime.  JoinQuant API names are resolved only when
``get_style_mean_return`` executes so the pure helpers remain locally testable.
"""

import numpy as np
import pandas as pd

from jqdata import *  # noqa: F401,F403 - provided by the JoinQuant runtime


def select_original_branch(mean_2000, mean_500, ratio_threshold):
    """Return the original strategy branch selected by the style ratio."""
    try:
        numerator = float(mean_2000)
        denominator = float(mean_500)
        threshold = float(ratio_threshold)
    except (TypeError, ValueError):
        return None

    if not all(np.isfinite(value) for value in (numerator, denominator, threshold)):
        return None
    if abs(denominator) <= 1e-8:
        return None
    return "BIG" if numerator / denominator > threshold else "SMALL"


def safe_mean_return(close_frame, min_samples=2, winsorize=False):
    """Calculate a safe cross-sectional mean return from first/last closes."""
    if not isinstance(close_frame, pd.DataFrame) or close_frame.empty:
        return None

    frame = close_frame.apply(pd.to_numeric, errors="coerce")
    first = frame.iloc[0]
    last = frame.iloc[-1]
    usable = (
        first.notna()
        & last.notna()
        & np.isfinite(first)
        & np.isfinite(last)
        & first.ne(0)
        & last.ne(0)
    )
    returns = (last[usable] / first[usable] - 1.0).replace(
        [np.inf, -np.inf], np.nan
    ).dropna()

    try:
        required_samples = int(min_samples)
    except (TypeError, ValueError):
        return None
    if required_samples < 0 or len(returns) < required_samples:
        return None

    if winsorize and len(returns) >= 5:
        lower = returns.quantile(0.05)
        upper = returns.quantile(0.95)
        returns = returns.clip(lower, upper)

    value = float(returns.mean())
    return value if np.isfinite(value) else None


def merge_target_with_holdings(holdings, ranked_candidates, target_count):
    """Keep still-ranked holdings first, then fill from candidate rank order."""
    try:
        count = int(target_count)
    except (TypeError, ValueError):
        return []
    if count <= 0:
        return []

    ranked = list(dict.fromkeys(ranked_candidates or ()))
    kept = []
    for stock in holdings or ():
        if stock in ranked and stock not in kept:
            kept.append(stock)
    filled = [stock for stock in ranked if stock not in kept]
    return (kept + filled)[:count]


def _date_values(frame):
    """Extract date-like values from a price frame without inventing dates."""
    for column in ("time", "date", "trade_date"):
        if column in frame.columns:
            return frame[column]
    if isinstance(frame.index, pd.MultiIndex):
        for level_name in ("time", "date", "trade_date"):
            if level_name in frame.index.names:
                return frame.index.get_level_values(level_name)
        return frame.index.get_level_values(0)
    return frame.index


def _normalize_wide_close_frame(frame):
    """Convert a close matrix to numeric values on a sorted DatetimeIndex."""
    if isinstance(frame, pd.Series):
        frame = frame.to_frame()
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return None

    result = frame.copy()
    dates = pd.to_datetime(_date_values(result), errors="coerce")
    valid_dates = ~pd.isna(dates)
    if not np.any(valid_dates):
        return None
    result = result.loc[valid_dates].copy()
    result.index = pd.DatetimeIndex(dates[valid_dates])
    result = result.apply(pd.to_numeric, errors="coerce")
    result = result.replace([np.inf, -np.inf], np.nan).dropna(axis=1, how="all")
    if result.empty or result.shape[1] == 0:
        return None
    if result.index.has_duplicates:
        result = result.groupby(level=0, sort=False).last()
    return result.sort_index(kind="mergesort")


def safe_close_frame(raw_prices):
    """Normalize supported JoinQuant price responses into a close matrix."""
    if raw_prices is None:
        return None

    if not isinstance(raw_prices, pd.DataFrame):
        try:
            close_values = raw_prices["close"]
        except (KeyError, TypeError, AttributeError):
            return None
        return _normalize_wide_close_frame(close_values)

    if raw_prices.empty:
        return None

    if isinstance(raw_prices.columns, pd.MultiIndex):
        try:
            return _normalize_wide_close_frame(raw_prices["close"])
        except KeyError:
            return None

    if "close" not in raw_prices.columns:
        return _normalize_wide_close_frame(raw_prices)

    if "code" not in raw_prices.columns:
        return _normalize_wide_close_frame(raw_prices[["close"]])

    long_frame = raw_prices[["code", "close"]].copy()
    long_frame["date"] = pd.to_datetime(_date_values(raw_prices), errors="coerce")
    long_frame["close"] = pd.to_numeric(long_frame["close"], errors="coerce")
    long_frame = long_frame.dropna(subset=["date", "code"])
    if long_frame.empty:
        return None

    close_frame = long_frame.pivot_table(
        index="date",
        columns="code",
        values="close",
        aggfunc="last",
        sort=False,
    )
    close_frame.columns.name = None
    return _normalize_wide_close_frame(close_frame)


def _configured_value(name, default):
    """Read Task 2 signal settings without requiring Task 3 initialization."""
    runtime_config = globals().get("g")
    if isinstance(runtime_config, dict) and name in runtime_config:
        return runtime_config[name]
    if runtime_config is not None and hasattr(runtime_config, name):
        return getattr(runtime_config, name)

    defaults = globals().get("DEFAULT_PARAMS", {})
    if isinstance(defaults, dict) and name in defaults:
        return defaults[name]
    return default


def get_style_mean_return(context, index_code):
    """Fetch cutoff-safe index closes and return their cross-sectional mean."""
    cutoff = context.previous_date
    style_window = int(_configured_value("style_window", 20))
    min_samples = int(_configured_value("min_style_samples", 2))
    winsorize = bool(_configured_value("winsorize_returns", False))

    # Historical constituents remain mandatory for a cutoff-safe signal.  The
    # Task 3 default for use_historical_constituents is therefore honored here
    # without introducing a current-day constituent fallback.
    use_historical = bool(_configured_value("use_historical_constituents", True))
    if not use_historical:
        return None
    stocks = get_index_stocks(index_code, date=cutoff)
    if not stocks:
        return None

    request = {
        "end_date": cutoff,
        "frequency": "daily",
        "fields": ["close"],
        "count": style_window,
    }
    try:
        raw_prices = get_price(stocks, panel=False, **request)
    except TypeError as exc:
        if "panel" not in str(exc):
            raise
        raw_prices = get_price(stocks, **request)

    close_frame = safe_close_frame(raw_prices)
    return safe_mean_return(
        close_frame,
        min_samples=min_samples,
        winsorize=winsorize,
    )
