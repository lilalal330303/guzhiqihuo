from __future__ import annotations

import pandas as pd


def generate_ma_cross_signals(
    bars: pd.DataFrame,
    short_window: int,
    long_window: int,
    price_col: str = "close",
) -> pd.DataFrame:
    """Generate long-only moving-average crossover signals."""
    if short_window <= 0 or long_window <= 0:
        raise ValueError("moving-average windows must be positive")
    if short_window >= long_window:
        raise ValueError("short_window must be smaller than long_window")
    if price_col not in bars.columns:
        raise ValueError(f"price column not found: {price_col}")

    result = bars.copy()
    result["short_ma"] = result[price_col].rolling(short_window).mean()
    result["long_ma"] = result[price_col].rolling(long_window).mean()
    result["signal"] = (result["short_ma"] > result["long_ma"]).astype(int)
    result.loc[result["long_ma"].isna(), "signal"] = 0

    result["position"] = result["signal"].shift(1).fillna(0).astype(int)
    result["trade_signal"] = result["position"].diff().fillna(result["position"]).astype(int)
    return result
