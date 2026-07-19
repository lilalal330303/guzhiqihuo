from __future__ import annotations

import math
from typing import Any

import pandas as pd


POST_2024_START = pd.Timestamp("2024-01-01")
COMMON_RISK = {
    "target_annual_vol": 0.30,
    "max_leverage": 3.5,
    "margin_rate": 0.15,
    "max_margin_usage": 0.60,
    "contract_multiplier": 100,
    "max_risk_multiplier": 1.25,
}


def make_params(signal_date: str | pd.Timestamp) -> dict[str, Any]:
    post = pd.Timestamp(signal_date) >= POST_2024_START
    if post:
        return dict(
            COMMON_RISK,
            fast_days=10,
            trend_days=40,
            slope_days=5,
            atr_days=14,
            vol_days=20,
            vol_long_days=60,
            efficiency_days=20,
            direction_days=20,
            confirmation_days=2,
            entry_buffer=0.001,
            min_spread=0.001,
            min_slope=0.0003,
            min_efficiency=0.25,
            min_consistency=0.60,
            max_vol_ratio=1.8,
            stop_atr=2.5,
            cooldown_days=1,
            allow_short=True,
            dual_speed=True,
            slow_fast_days=20,
            slow_trend_days=60,
            slow_slope_days=10,
            slow_confirmation_days=2,
            slow_entry_buffer=0.002,
            slow_min_spread=0.002,
            slow_min_slope=0.0005,
        )
    return dict(
        COMMON_RISK,
        fast_days=20,
        trend_days=60,
        slope_days=10,
        atr_days=20,
        vol_days=20,
        vol_long_days=60,
        efficiency_days=20,
        direction_days=20,
        confirmation_days=2,
        entry_buffer=0.002,
        min_spread=0.002,
        min_slope=0.0005,
        min_efficiency=0.0,
        min_consistency=0.0,
        max_vol_ratio=1.8,
        stop_atr=3.0,
        cooldown_days=2,
        allow_short=True,
        dual_speed=False,
        slow_fast_days=20,
        slow_trend_days=60,
        slow_slope_days=10,
        slow_confirmation_days=2,
        slow_entry_buffer=0.002,
        slow_min_spread=0.002,
        slow_min_slope=0.0005,
    )


def _finite_positive(value: object) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number > 0


def _clean_closes(closes: list[float] | pd.Series) -> list[float]:
    return [float(value) for value in closes if _finite_positive(value)]


def classify_signal(
    closes: list[float] | pd.Series,
    fast_days: int,
    trend_days: int,
    slope_days: int,
    confirmation_days: int,
    entry_buffer: float,
    min_spread: float,
    min_slope: float,
) -> int:
    values = _clean_closes(closes)
    fast_days = max(1, int(fast_days))
    trend_days = max(fast_days, int(trend_days))
    slope_days = max(1, int(slope_days))
    confirmation_days = max(1, int(confirmation_days))
    if len(values) < trend_days + slope_days + confirmation_days - 1:
        return 0
    states = []
    for index in range(len(values)):
        if index + 1 < trend_days + slope_days:
            states.append(0)
            continue
        current = values[index + 1 - trend_days:index + 1]
        previous = values[index + 1 - trend_days - slope_days:index + 1 - slope_days]
        fast = sum(values[index + 1 - fast_days:index + 1]) / fast_days
        slow = sum(current) / trend_days
        previous_slow = sum(previous) / trend_days
        slope = slow / previous_slow - 1.0
        price = values[index]
        bullish = (
            price > fast * (1.0 + entry_buffer)
            and fast > slow * (1.0 + min_spread)
            and slope >= min_slope
        )
        bearish = (
            price < fast * (1.0 - entry_buffer)
            and fast < slow * (1.0 - min_spread)
            and slope <= -min_slope
        )
        states.append(1 if bullish else -1 if bearish else 0)
    recent = states[-confirmation_days:]
    if all(value == 1 for value in recent):
        return 1
    if all(value == -1 for value in recent):
        return -1
    return 0


def efficiency_ratio(closes: list[float] | pd.Series, window: int = 20) -> float:
    values = _clean_closes(closes)
    window = max(1, int(window))
    if len(values) < window + 1:
        return 0.0
    sample = values[-window - 1:]
    path = sum(abs(sample[index] - sample[index - 1]) for index in range(1, len(sample)))
    return 0.0 if path <= 0 else abs(sample[-1] - sample[0]) / path


def direction_consistency(closes: list[float] | pd.Series, window: int = 20) -> float:
    values = _clean_closes(closes)
    window = max(1, int(window))
    if len(values) < window + 1:
        return 0.0
    sample = values[-window - 1:]
    net = sample[-1] - sample[0]
    if net == 0:
        return 0.0
    net_sign = 1 if net > 0 else -1
    returns = [sample[index] - sample[index - 1] for index in range(1, len(sample))]
    non_zero = [value for value in returns if value != 0]
    if not non_zero:
        return 0.0
    return sum((1 if value > 0 else -1) == net_sign for value in non_zero) / len(non_zero)


def realized_volatility(closes: list[float] | pd.Series, annual_days: int = 252) -> float:
    values = _clean_closes(closes)
    if len(values) < 3:
        return 0.0
    returns = [math.log(values[index] / values[index - 1]) for index in range(1, len(values))]
    value = float(pd.Series(returns).std(ddof=1) * math.sqrt(annual_days))
    return value if math.isfinite(value) and value >= 0 else 0.0


def volatility_ratio(
    closes: list[float] | pd.Series,
    short_days: int = 20,
    long_days: int = 60,
) -> float:
    values = _clean_closes(closes)
    short_days = max(2, int(short_days))
    long_days = max(short_days + 1, int(long_days))
    if len(values) < long_days + 1:
        return 1.0
    short = realized_volatility(values[-short_days - 1:])
    long = realized_volatility(values[-long_days - 1:])
    return 1.0 if long <= 0 else short / long


def dual_speed_signal(closes: list[float] | pd.Series, params: dict[str, Any]) -> tuple[int, float]:
    fast_signal = classify_signal(
        closes,
        params["fast_days"],
        params["trend_days"],
        params["slope_days"],
        params["confirmation_days"],
        params["entry_buffer"],
        params["min_spread"],
        params["min_slope"],
    )
    efficiency = efficiency_ratio(closes, params["efficiency_days"])
    consistency = direction_consistency(closes, params["direction_days"])
    if efficiency < params["min_efficiency"] or consistency < params["min_consistency"]:
        return 0, 0.0
    if fast_signal == -1 and not params["allow_short"]:
        return 0, 0.0
    if not params["dual_speed"]:
        return fast_signal, 1.0 if fast_signal else 0.0
    slow_signal = classify_signal(
        closes,
        params["slow_fast_days"],
        params["slow_trend_days"],
        params["slow_slope_days"],
        params["slow_confirmation_days"],
        params["slow_entry_buffer"],
        params["slow_min_spread"],
        params["slow_min_slope"],
    )
    if fast_signal and fast_signal == slow_signal:
        return fast_signal, 1.0
    if fast_signal and slow_signal == 0:
        return fast_signal, 0.5
    return 0, 0.0


def adaptive_signal(closes: list[float] | pd.Series, params: dict[str, Any]) -> int:
    return dual_speed_signal(closes, params)[0]


def atr(bars: pd.DataFrame, window: int) -> float:
    if len(bars) < window or not {"high", "low", "close"}.issubset(bars.columns):
        return 0.0
    data = bars.loc[:, ["high", "low", "close"]].astype(float)
    previous = data["close"].shift(1)
    true_range = pd.concat(
        [
            data["high"] - data["low"],
            (data["high"] - previous).abs(),
            (data["low"] - previous).abs(),
        ],
        axis=1,
    ).max(axis=1)
    value = float(true_range.tail(window).mean())
    return value if math.isfinite(value) and value > 0 else 0.0


def risk_multiplier(
    efficiency: float,
    volatility: float,
    consistency: float,
    params: dict[str, Any],
) -> float:
    if efficiency < params["min_efficiency"] or consistency < params["min_consistency"]:
        return 0.0
    if not math.isfinite(volatility) or volatility > params["max_vol_ratio"]:
        return 0.5
    return 1.0


def drawdown_multiplier(current_value: float, high_water: float) -> float:
    if current_value <= 0 or high_water <= 0:
        return 0.0
    drawdown = round(max(0.0, 1.0 - current_value / high_water), 10)
    if drawdown < 0.10:
        return 1.0
    if drawdown < 0.15:
        return 0.90
    if drawdown < 0.20:
        return 0.75
    if drawdown < 0.25:
        return 0.50
    return 0.0


def trend_quality_multiplier(
    close: float,
    ma_fast: float,
    ma_slow: float,
    slow_slope: float,
    realized_vol: float,
    params: dict[str, Any],
) -> float:
    strong = (
        close >= ma_fast * 1.01
        and ma_fast >= ma_slow * 1.01
        and slow_slope >= 0.001
        and realized_vol <= params["target_annual_vol"] * 1.25
    )
    return 1.25 if strong else 1.0


def vol_scaled_amount(
    total_value: float,
    available_cash: float,
    price: float,
    realized_vol: float,
    params: dict[str, Any],
) -> int:
    if total_value <= 0 or price <= 0:
        return 0
    margin_leverage = params["max_margin_usage"] / params["margin_rate"]
    vol_leverage = (
        params["max_leverage"]
        if realized_vol <= 0
        else params["target_annual_vol"] / realized_vol
    )
    leverage = min(params["max_leverage"], margin_leverage, vol_leverage)
    budget = min(total_value * leverage, max(0.0, available_cash) * margin_leverage)
    return int(budget / (price * params["contract_multiplier"]) + 1e-9)


def risk_scaled_amount(
    total_value: float,
    available_cash: float,
    price: float,
    realized_vol: float,
    multiplier: float,
    params: dict[str, Any],
) -> int:
    if multiplier <= 0:
        return 0
    multiplier = min(float(params["max_risk_multiplier"]), float(multiplier))
    return int(vol_scaled_amount(total_value, available_cash, price, realized_vol, params) * multiplier)


def trailing_stop_hit(
    direction: int,
    close: float,
    best_close: float | None,
    atr_value: float,
    stop_atr: float,
) -> bool:
    if direction not in (-1, 1) or best_close is None or atr_value <= 0 or stop_atr <= 0:
        return False
    if direction > 0:
        return close < best_close - atr_value * stop_atr
    return close > best_close + atr_value * stop_atr
