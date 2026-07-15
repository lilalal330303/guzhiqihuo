from __future__ import annotations

import math
from numbers import Integral

import numpy as np
import pandas as pd


def build_crash_exposure_budget(
    index_bars: pd.DataFrame,
    *,
    drawdown_threshold: float,
    defensive_budget: float,
    recovery_confirmation_days: int,
    lookback: int = 60,
) -> pd.DataFrame:
    required = {"trade_date", "close"}
    missing = required.difference(index_bars.columns)
    if missing:
        raise ValueError(f"index_bars missing required columns: {sorted(missing)}")

    if not math.isfinite(float(drawdown_threshold)) or not 0 < drawdown_threshold < 1:
        raise ValueError("drawdown_threshold must be finite and satisfy 0 < value < 1")
    if not math.isfinite(float(defensive_budget)) or not 0 <= defensive_budget < 1:
        raise ValueError("defensive_budget must be finite and satisfy 0 <= value < 1")
    if (
        isinstance(recovery_confirmation_days, bool)
        or not isinstance(recovery_confirmation_days, Integral)
        or recovery_confirmation_days < 1
    ):
        raise ValueError("recovery_confirmation_days must be an integer >= 1")
    if isinstance(lookback, bool) or not isinstance(lookback, Integral) or lookback < 60:
        raise ValueError("lookback must be an integer >= 60")

    frame = index_bars.loc[:, ["trade_date", "close"]].copy()
    try:
        frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise").dt.normalize()
        frame["close"] = pd.to_numeric(frame["close"], errors="raise").astype(float)
    except (TypeError, ValueError) as exc:
        raise ValueError("trade_date and close must contain valid values") from exc
    if frame["trade_date"].isna().any():
        raise ValueError("trade_date must not contain missing values")
    if frame["trade_date"].duplicated().any():
        raise ValueError("trade_date must be unique after normalization")
    if not frame["trade_date"].is_monotonic_increasing:
        raise ValueError("trade_date must be ascending")
    if not np.isfinite(frame["close"]).all() or frame["close"].le(0).any():
        raise ValueError("close must contain finite positive values")

    close = frame["close"]
    frame["ma60"] = close.rolling(60, min_periods=60).mean()
    frame["rolling_high"] = close.rolling(lookback, min_periods=lookback).max()
    frame["rolling_drawdown"] = close / frame["rolling_high"] - 1.0
    frame["below_ma60"] = close.lt(frame["ma60"])
    frame["severe"] = frame["below_ma60"] & frame["rolling_drawdown"].le(
        -drawdown_threshold
    )

    defensive = False
    recovery_count = 0
    defensive_states: list[bool] = []
    budgets: list[float] = []
    for severe in frame["severe"]:
        if bool(severe):
            defensive = True
            recovery_count = 0
        elif defensive:
            recovery_count += 1
            if recovery_count > recovery_confirmation_days:
                defensive = False
                recovery_count = 0
        defensive_states.append(defensive)
        budgets.append(float(defensive_budget) if defensive else 1.0)

    frame["defensive"] = defensive_states
    frame["exposure_budget"] = budgets
    return frame.loc[:, [
        "trade_date", "close", "ma60", "rolling_high", "rolling_drawdown",
        "below_ma60", "severe", "defensive", "exposure_budget",
    ]].reset_index(drop=True)
