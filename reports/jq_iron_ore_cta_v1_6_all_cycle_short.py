"""Iron ore CTA V1.6: all-cycle long/short trend strategy.

The pre-2024 regime keeps the slower V1.4 structure but now permits confirmed
shorts.  From 2024-01-01 the strategy uses a faster trend signal, confirms it
with the slower signal, filters low directional consistency, scales risk in
volatility shocks, and protects open profits with a symmetric ATR trail.

Copy this whole file into JoinQuant.  It intentionally has no local-package
imports and uses only point-in-time market-data requests.
"""

import math
import re

import pandas as pd

try:
    from jqdata import *
except ImportError:
    class _FallbackLog:
        def info(self, *args, **kwargs):
            return None

        def warn(self, *args, **kwargs):
            return None

    log = _FallbackLog()


SIGNAL_SECURITY = "I8888.XDCE"
ALLOW_SHORT = True
POST_2024_START = "2024-01-01"

_COMMON_RISK = {
    "target_annual_vol": 0.30,
    "max_leverage": 3.5,
    "margin_rate": 0.15,
    "max_margin_usage": 0.60,
    "roll_days_before_expiry": 8,
    "contract_multiplier": 100,
    "max_risk_multiplier": 1.25,
}

PRE_PARAMS = dict(
    _COMMON_RISK,
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
    is_post_2024=False,
    dual_speed=False,
    slow_fast_days=20,
    slow_trend_days=60,
    slow_slope_days=10,
    slow_confirmation_days=2,
    slow_entry_buffer=0.002,
    slow_min_spread=0.002,
    slow_min_slope=0.0005,
)

POST_PARAMS = dict(
    _COMMON_RISK,
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
    is_post_2024=True,
    dual_speed=True,
    slow_fast_days=20,
    slow_trend_days=60,
    slow_slope_days=10,
    slow_confirmation_days=2,
    slow_entry_buffer=0.002,
    slow_min_spread=0.002,
    slow_min_slope=0.0005,
)


def _finite_positive(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(value) and value > 0


def _clean_closes(closes):
    values = []
    for value in closes:
        if _finite_positive(value):
            values.append(float(value))
    return values


def select_regime_parameters(signal_date):
    """Return parameters selected only by the historical signal date."""
    try:
        signal_date = pd.Timestamp(signal_date).date()
        switch_date = pd.Timestamp(POST_2024_START).date()
    except (TypeError, ValueError):
        return POST_PARAMS.copy()
    return POST_PARAMS.copy() if signal_date >= switch_date else PRE_PARAMS.copy()


def _raw_trend_state(
    closes,
    index,
    fast_days,
    trend_days,
    slope_days,
    entry_buffer,
    min_spread,
    min_slope,
):
    if index + 1 < trend_days + slope_days:
        return 0
    current_window = closes[index + 1 - trend_days:index + 1]
    previous_window = closes[
        index + 1 - trend_days - slope_days:index + 1 - slope_days
    ]
    if len(current_window) < trend_days or len(previous_window) < trend_days:
        return 0
    fast = sum(closes[index + 1 - fast_days:index + 1]) / float(fast_days)
    slow = sum(current_window) / float(trend_days)
    previous_slow = sum(previous_window) / float(trend_days)
    price = closes[index]
    if not all(_finite_positive(x) for x in (price, fast, slow, previous_slow)):
        return 0
    slope = slow / previous_slow - 1.0
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
    if bullish:
        return 1
    if bearish:
        return -1
    return 0


def classify_v1_signal(
    closes,
    fast_days=20,
    trend_days=60,
    slope_days=10,
    confirmation_days=2,
    entry_buffer=0.002,
    min_spread=0.002,
    min_slope=0.0005,
):
    """Return 1 for bullish, -1 for bearish, and 0 for neutral."""
    values = _clean_closes(closes)
    fast_days = max(1, int(fast_days))
    trend_days = max(fast_days, int(trend_days))
    slope_days = max(1, int(slope_days))
    confirmation_days = max(1, int(confirmation_days))
    minimum = trend_days + slope_days + confirmation_days - 1
    if len(values) < minimum:
        return 0
    states = []
    for index in range(len(values)):
        states.append(
            _raw_trend_state(
                values,
                index,
                fast_days,
                trend_days,
                slope_days,
                entry_buffer,
                min_spread,
                min_slope,
            )
        )
    recent = states[-confirmation_days:]
    if all(state == 1 for state in recent):
        return 1
    if all(state == -1 for state in recent):
        return -1
    return 0


def calculate_efficiency_ratio(closes, window=20):
    """Return net displacement divided by absolute path length."""
    values = _clean_closes(closes)
    window = max(1, int(window))
    if len(values) < window + 1:
        return 0.0
    sample = values[-window - 1:]
    path = sum(
        abs(sample[index] - sample[index - 1])
        for index in range(1, len(sample))
    )
    if path <= 0:
        return 0.0
    return abs(sample[-1] - sample[0]) / path


def calculate_direction_consistency(closes, window=20):
    """Return the fraction of non-zero returns aligned with the net move."""
    values = _clean_closes(closes)
    window = max(1, int(window))
    if len(values) < window + 1:
        return 0.0
    sample = values[-window - 1:]
    net = sample[-1] - sample[0]
    if abs(net) <= 0:
        return 0.0
    net_sign = 1 if net > 0 else -1
    returns = [sample[index] - sample[index - 1] for index in range(1, len(sample))]
    non_zero = [value for value in returns if abs(value) > 0]
    if not non_zero:
        return 0.0
    aligned = sum(1 for value in non_zero if (1 if value > 0 else -1) == net_sign)
    return float(aligned) / float(len(non_zero))


def calculate_realized_volatility(closes, annual_days=252):
    """Return annualized volatility of daily log returns."""
    values = _clean_closes(closes)
    if len(values) < 3:
        return 0.0
    returns = [
        math.log(values[index] / values[index - 1])
        for index in range(1, len(values))
        if _finite_positive(values[index - 1])
        and _finite_positive(values[index])
    ]
    if len(returns) < 2:
        return 0.0
    value = float(pd.Series(returns).std(ddof=1) * math.sqrt(annual_days))
    return value if math.isfinite(value) and value >= 0 else 0.0


def calculate_volatility_ratio(closes, short_days=20, long_days=60):
    """Return short-window realized volatility divided by long volatility."""
    values = _clean_closes(closes)
    short_days = max(2, int(short_days))
    long_days = max(short_days + 1, int(long_days))
    if len(values) < long_days + 1:
        return 1.0
    short_vol = calculate_realized_volatility(values[-short_days - 1:])
    long_vol = calculate_realized_volatility(values[-long_days - 1:])
    if not _finite_positive(long_vol):
        return 1.0
    if not math.isfinite(short_vol) or short_vol < 0:
        return 1.0
    return short_vol / long_vol


def calculate_dual_speed_signal(closes, params):
    """Return (direction, risk multiplier) for the selected regime."""
    fast_signal = classify_v1_signal(
        closes,
        fast_days=params["fast_days"],
        trend_days=params["trend_days"],
        slope_days=params["slope_days"],
        confirmation_days=params["confirmation_days"],
        entry_buffer=params["entry_buffer"],
        min_spread=params["min_spread"],
        min_slope=params["min_slope"],
    )
    efficiency = calculate_efficiency_ratio(closes, params["efficiency_days"])
    consistency = calculate_direction_consistency(closes, params["direction_days"])
    if efficiency < float(params["min_efficiency"]):
        return 0, 0.0
    if consistency < float(params.get("min_consistency", 0.0)):
        return 0, 0.0
    if fast_signal == -1 and not params["allow_short"]:
        return 0, 0.0
    if not params.get("dual_speed", False):
        return fast_signal, 1.0 if fast_signal else 0.0

    slow_signal = classify_v1_signal(
        closes,
        fast_days=params["slow_fast_days"],
        trend_days=params["slow_trend_days"],
        slope_days=params["slow_slope_days"],
        confirmation_days=params["slow_confirmation_days"],
        entry_buffer=params["slow_entry_buffer"],
        min_spread=params["slow_min_spread"],
        min_slope=params["slow_min_slope"],
    )
    if fast_signal != 0 and fast_signal == slow_signal:
        return fast_signal, 1.0
    if fast_signal != 0 and slow_signal == 0:
        return fast_signal, 0.5
    return 0, 0.0


def calculate_adaptive_signal(closes, params):
    """Compatibility wrapper returning only the dual-speed direction."""
    return calculate_dual_speed_signal(closes, params)[0]


def calculate_regime_risk_multiplier(
    efficiency,
    volatility_ratio,
    consistency_or_params,
    params=None,
):
    """Return 0 in a range, 0.5 during volatility shocks, otherwise 1."""
    if params is None:
        params = consistency_or_params
        consistency = 1.0
    else:
        consistency = consistency_or_params
    try:
        efficiency = float(efficiency)
        volatility_ratio = float(volatility_ratio)
        consistency = float(consistency)
        min_efficiency = float(params["min_efficiency"])
        min_consistency = float(params.get("min_consistency", 0.0))
        max_vol_ratio = float(params["max_vol_ratio"])
    except (KeyError, TypeError, ValueError):
        return 0.0
    if not math.isfinite(efficiency) or efficiency < min_efficiency:
        return 0.0
    if not math.isfinite(consistency) or consistency < min_consistency:
        return 0.0
    if not math.isfinite(volatility_ratio):
        return 0.5
    if volatility_ratio > max_vol_ratio:
        return 0.5
    return 1.0


def calculate_atr(bars, window=20):
    """Return a simple-average true range."""
    window = max(1, int(window))
    if bars is None or len(bars) < window:
        return 0.0
    required = {"high", "low", "close"}
    if not required.issubset(set(bars.columns)):
        return 0.0
    data = bars[list(required)].copy()
    for column in required:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.dropna()
    if len(data) < window:
        return 0.0
    previous_close = data["close"].shift(1)
    true_range = pd.concat(
        [
            data["high"] - data["low"],
            (data["high"] - previous_close).abs(),
            (data["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    value = float(true_range.tail(window).mean())
    return value if math.isfinite(value) and value > 0 else 0.0


def calculate_vol_scaled_amount(total_value, available_cash, price, realized_vol, params):
    """Size contracts from volatility, leverage, cash, and margin budgets."""
    if not all(_finite_positive(x) for x in (total_value, price)):
        return 0
    margin_rate = float(params["margin_rate"])
    margin_usage = float(params["max_margin_usage"])
    multiplier = float(params["contract_multiplier"])
    if margin_rate <= 0 or margin_usage <= 0 or multiplier <= 0:
        return 0
    margin_leverage = margin_usage / margin_rate
    target_vol = float(params["target_annual_vol"])
    max_leverage = float(params["max_leverage"])
    try:
        realized_vol = float(realized_vol)
    except (TypeError, ValueError):
        realized_vol = 0.0
    if not math.isfinite(realized_vol) or realized_vol <= 0:
        vol_leverage = max_leverage
    else:
        vol_leverage = target_vol / realized_vol
    effective_leverage = min(max_leverage, margin_leverage, vol_leverage)
    if effective_leverage <= 0:
        return 0
    notional_from_equity = float(total_value) * effective_leverage
    notional_from_cash = max(0.0, float(available_cash)) * margin_leverage
    notional_budget = min(notional_from_equity, notional_from_cash)
    contract_notional = float(price) * multiplier
    return int(math.floor(notional_budget / contract_notional + 1e-9))


def calculate_risk_scaled_amount(
    total_value,
    available_cash,
    price,
    realized_vol,
    risk_multiplier,
    params,
):
    """Apply regime, drawdown, trend, and signal multipliers."""
    try:
        risk_multiplier = float(risk_multiplier)
        max_multiplier = float(params.get("max_risk_multiplier", 1.25))
    except (AttributeError, TypeError, ValueError):
        return 0
    if not math.isfinite(risk_multiplier) or risk_multiplier <= 0:
        return 0
    if not math.isfinite(max_multiplier) or max_multiplier <= 0:
        return 0
    risk_multiplier = min(max_multiplier, risk_multiplier)
    base_amount = calculate_vol_scaled_amount(
        total_value,
        available_cash,
        price,
        realized_vol,
        params,
    )
    return int(max(0.0, float(base_amount) * risk_multiplier))


def calculate_drawdown_multiplier(current_value, high_water):
    """Return the C-tier new-entry multiplier from drawdown."""
    if not _finite_positive(current_value) or not _finite_positive(high_water):
        return 0.0
    drawdown = round(
        max(0.0, 1.0 - float(current_value) / float(high_water)),
        10,
    )
    if drawdown < 0.10:
        return 1.0
    if drawdown < 0.15:
        return 0.90
    if drawdown < 0.20:
        return 0.75
    if drawdown < 0.25:
        return 0.50
    return 0.0


def calculate_trend_quality_multiplier(
    close,
    ma_fast,
    ma_slow,
    slow_slope,
    realized_vol,
    params,
):
    """Keep V1.4's 1.25x strong-trend boost for the legacy regime."""
    if not all(_finite_positive(value) for value in (close, ma_fast, ma_slow)):
        return 1.0
    try:
        slow_slope = float(slow_slope)
        realized_vol = float(realized_vol)
        target_vol = float(params["target_annual_vol"])
    except (KeyError, TypeError, ValueError):
        return 1.0
    if not math.isfinite(slow_slope) or not math.isfinite(realized_vol):
        return 1.0
    strong_trend = (
        float(close) >= float(ma_fast) * 1.01
        and float(ma_fast) >= float(ma_slow) * 1.01
        and slow_slope >= 0.001
    )
    volatility_ok = realized_vol <= target_vol * 1.25
    return 1.25 if strong_trend and volatility_ok else 1.0


def should_trigger_trailing_stop(direction, close, best_close, atr, stop_atr):
    """Return whether a symmetric long/short ATR trailing stop is hit."""
    if direction not in (1, -1):
        return False
    if not all(_finite_positive(value) for value in (close, best_close, atr, stop_atr)):
        return False
    distance = float(atr) * float(stop_atr)
    if direction > 0:
        return float(close) < float(best_close) - distance
    return float(close) > float(best_close) + distance


def select_near_contract(futures, signal_date, roll_days_before_expiry=8):
    """Select the nearest eligible iron ore contract at signal_date."""
    if futures is None or getattr(futures, "empty", True):
        return None
    signal_date = pd.Timestamp(signal_date).date()
    pattern = re.compile(r"^I\d{4}\.XDCE$", re.IGNORECASE)
    eligible = []
    for code, row in futures.iterrows():
        code = str(code).upper()
        if not pattern.match(code):
            continue
        end_date = row.get("end_date")
        if end_date is None or pd.isna(end_date):
            continue
        expiry = pd.Timestamp(end_date).date()
        if (expiry - signal_date).days > int(roll_days_before_expiry):
            eligible.append((expiry, code))
    eligible.sort()
    return eligible[0][1] if eligible else None


def can_open_replacement(old_amount, close_filled, remaining_amount):
    """Allow a replacement only after actual old exposure is flat."""
    old_amount = max(0, int(old_amount or 0))
    close_filled = max(0, int(close_filled or 0))
    remaining_amount = max(0, int(remaining_amount or 0))
    return remaining_amount == 0 and (old_amount == 0 or close_filled >= old_amount)


def initialize(context):
    set_benchmark(SIGNAL_SECURITY)
    set_option("use_real_price", True)
    set_option("avoid_future_data", True)
    g.params = POST_PARAMS.copy()
    g.tradecode = ""
    g.pending_contract = None
    g.cooldown = 0
    g.best_close = None
    g.high_water_value = float(context.portfolio.starting_cash)
    g.drawdown_multiplier = 1.0
    g.trend_multiplier = 1.0
    g.regime_multiplier = 1.0
    g.signal_multiplier = 1.0
    g.risk_multiplier = 1.0
    set_subportfolios(
        [SubPortfolioConfig(cash=context.portfolio.starting_cash, type="futures")]
    )
    set_order_cost(
        OrderCost(
            open_commission=0.000023,
            close_commission=0.000023,
            close_today_commission=0.0023,
        ),
        type="futures",
    )
    set_option("futures_margin_rate", g.params["margin_rate"])
    set_slippage(StepRelatedSlippage(2))
    run_daily(trade_open, time="09:05", reference_security=SIGNAL_SECURITY)


def get_signal_snapshot(signal_date):
    params = select_regime_parameters(signal_date)
    count = max(
        params["trend_days"] + params["slope_days"] + 5,
        params["slow_trend_days"] + params["slow_slope_days"] + 5,
        params["atr_days"] + 5,
        params["vol_long_days"] + 5,
        params["efficiency_days"] + 5,
        params["direction_days"] + 5,
    )
    data = get_price(
        SIGNAL_SECURITY,
        end_date=signal_date,
        frequency="daily",
        fields=["high", "low", "close"],
        count=count,
        panel=False,
    )
    if data is None or data.empty:
        return None
    closes = pd.to_numeric(data["close"], errors="coerce").dropna().tolist()
    minimum = max(
        params["trend_days"] + params["slope_days"],
        params["slow_trend_days"] + params["slow_slope_days"],
    )
    if len(closes) < minimum:
        return None

    signal, signal_multiplier = calculate_dual_speed_signal(closes, params)
    fast = float(pd.Series(closes).tail(params["fast_days"]).mean())
    slow = float(pd.Series(closes).tail(params["trend_days"]).mean())
    previous_slow = float(
        pd.Series(
            closes[-params["trend_days"] - params["slope_days"]:-params["slope_days"]]
        ).mean()
    )
    slow_slope = slow / previous_slow - 1.0 if _finite_positive(previous_slow) else 0.0
    efficiency = calculate_efficiency_ratio(closes, params["efficiency_days"])
    direction_consistency = calculate_direction_consistency(
        closes,
        params["direction_days"],
    )
    volatility_ratio = calculate_volatility_ratio(
        closes,
        params["vol_days"],
        params["vol_long_days"],
    )
    realized_vol = calculate_realized_volatility(closes[-params["vol_days"] - 1:])
    regime_multiplier = calculate_regime_risk_multiplier(
        efficiency,
        volatility_ratio,
        direction_consistency,
        params,
    )
    if params["is_post_2024"]:
        trend_multiplier = 1.0
    else:
        trend_multiplier = calculate_trend_quality_multiplier(
            float(closes[-1]),
            fast,
            slow,
            slow_slope,
            realized_vol,
            params,
        )
    return {
        "params": params,
        "signal": signal,
        "signal_multiplier": signal_multiplier,
        "close": float(closes[-1]),
        "ma_fast": fast,
        "ma_slow": slow,
        "slow_slope": slow_slope,
        "efficiency_ratio": efficiency,
        "direction_consistency": direction_consistency,
        "volatility_ratio": volatility_ratio,
        "regime_multiplier": regime_multiplier,
        "trend_multiplier": trend_multiplier,
        "atr": calculate_atr(data, params["atr_days"]),
        "realized_vol": realized_vol,
    }


def get_target_contract(signal_date):
    futures = get_all_securities(["futures"], date=signal_date)
    return select_near_contract(
        futures,
        signal_date,
        g.params["roll_days_before_expiry"],
    )


def get_contract_price(contract, signal_date):
    data = get_price(
        contract,
        end_date=signal_date,
        frequency="daily",
        fields=["close"],
        count=1,
        panel=False,
    )
    if data is None or data.empty:
        return None
    price = float(data["close"].iloc[-1])
    return price if _finite_positive(price) else None


def _position_amount(position, direction):
    if position is None:
        return 0
    if direction > 0:
        long_amount = getattr(position, "long_amount", None)
        if long_amount is not None:
            return int(long_amount or 0)
        if getattr(position, "short_amount", None) is not None:
            return 0
        return int(getattr(position, "total_amount", 0) or 0)
    short_amount = getattr(position, "short_amount", None)
    if short_amount is not None:
        return int(short_amount or 0)
    if getattr(position, "long_amount", None) is not None:
        return 0
    return int(getattr(position, "total_amount", 0) or 0)


def get_actual_position(context):
    positions = getattr(context.portfolio, "positions", {})
    for code, position in positions.items():
        long_amount = _position_amount(position, 1)
        if long_amount > 0:
            return code, 1, long_amount
        short_amount = _position_amount(position, -1)
        if short_amount > 0:
            return code, -1, short_amount
    return "", 0, 0


def is_order_fully_filled(order):
    if order is None:
        return False
    amount = abs(int(getattr(order, "amount", 0) or 0))
    filled = abs(int(getattr(order, "filled", 0) or 0))
    return amount > 0 and filled >= amount


def close_position(context, code, direction):
    if not code:
        return True
    position = context.portfolio.positions.get(code)
    amount = _position_amount(position, direction)
    if amount <= 0:
        return True
    side = "long" if direction > 0 else "short"
    order = order_target(code, 0, side=side)
    refreshed = context.portfolio.positions.get(code)
    remaining = _position_amount(refreshed, direction)
    if remaining == 0 or is_order_fully_filled(order):
        log.info("V1.6 close code=%s direction=%s amount=%s", code, direction, amount)
        return remaining == 0 or is_order_fully_filled(order)
    log.info("V1.6 close not complete code=%s remaining=%s", code, remaining)
    return False


def should_force_exit(direction, snapshot):
    atr = snapshot.get("atr", 0.0)
    close = snapshot.get("close", 0.0)
    fast = snapshot.get("ma_fast", 0.0)
    params = snapshot.get("params", g.params)
    if not _finite_positive(atr) or not _finite_positive(close):
        return False
    if not _finite_positive(fast):
        ma_stop = False
    else:
        distance = float(params["stop_atr"]) * float(atr)
        ma_stop = (
            close < fast - distance if direction > 0 else close > fast + distance
        )
    trail_stop = should_trigger_trailing_stop(
        direction,
        close,
        g.best_close,
        atr,
        params["stop_atr"],
    )
    return ma_stop or trail_stop


def open_position(context, code, direction, snapshot):
    price = get_contract_price(code, context.previous_date)
    if price is None:
        log.info("V1.6 no valid contract price, skip entry code=%s", code)
        return False
    total_value = float(getattr(context.portfolio, "total_value", 0.0))
    available_cash = float(
        getattr(
            context.portfolio,
            "available_cash",
            getattr(context.portfolio, "cash", 0.0),
        )
    )
    g.regime_multiplier = snapshot["regime_multiplier"]
    g.trend_multiplier = snapshot["trend_multiplier"]
    g.signal_multiplier = snapshot["signal_multiplier"]
    g.risk_multiplier = (
        g.drawdown_multiplier
        * g.regime_multiplier
        * g.trend_multiplier
        * g.signal_multiplier
    )
    amount = calculate_risk_scaled_amount(
        total_value,
        available_cash,
        price,
        snapshot["realized_vol"],
        g.risk_multiplier,
        g.params,
    )
    if amount <= 0:
        log.info(
            "V1.6 risk gate blocks entry code=%s eff=%.3f consistency=%.3f vol_ratio=%.2f",
            code,
            snapshot["efficiency_ratio"],
            snapshot["direction_consistency"],
            snapshot["volatility_ratio"],
        )
        return False
    side = "long" if direction > 0 else "short"
    order = order_target(code, amount, side=side)
    g.best_close = snapshot["close"]
    if not is_order_fully_filled(order):
        log.info("V1.6 entry not fully filled code=%s amount=%s", code, amount)
    else:
        log.info(
            "V1.6 entry code=%s direction=%s amount=%s eff=%.3f consistency=%.3f vol_ratio=%.2f risk=%.2f",
            code,
            direction,
            amount,
            snapshot["efficiency_ratio"],
            snapshot["direction_consistency"],
            snapshot["volatility_ratio"],
            g.risk_multiplier,
        )
    return True


def trade_open(context):
    signal_date = context.previous_date
    total_value = float(getattr(context.portfolio, "total_value", 0.0))
    g.high_water_value = max(g.high_water_value, total_value)
    g.drawdown_multiplier = calculate_drawdown_multiplier(
        total_value,
        g.high_water_value,
    )
    g.regime_multiplier = 1.0
    g.trend_multiplier = 1.0
    g.signal_multiplier = 1.0
    g.risk_multiplier = g.drawdown_multiplier

    snapshot = get_signal_snapshot(signal_date)
    if snapshot is None:
        log.info("V1.6 insufficient signal data date=%s", signal_date)
        return
    g.params = snapshot["params"].copy()

    target_contract = get_target_contract(signal_date)
    if not target_contract:
        log.info("V1.6 no eligible iron ore contract date=%s", signal_date)
        return

    current_code, current_direction, current_amount = get_actual_position(context)
    if current_code:
        if not _finite_positive(g.best_close):
            g.best_close = snapshot["close"]
        elif current_direction > 0:
            g.best_close = max(float(g.best_close), snapshot["close"])
        else:
            g.best_close = min(float(g.best_close), snapshot["close"])

    raw_signal = snapshot["signal"]
    if raw_signal == 1:
        target_direction = 1
    elif raw_signal == -1 and ALLOW_SHORT and g.params["allow_short"]:
        target_direction = -1
    else:
        target_direction = 0

    if current_code:
        needs_close = (
            target_direction == 0
            or current_direction != target_direction
            or current_code != target_contract
            or should_force_exit(current_direction, snapshot)
        )
        if needs_close:
            closed = close_position(context, current_code, current_direction)
            if closed:
                g.best_close = None
                g.tradecode = ""
                g.pending_contract = target_contract if target_direction else None
                g.cooldown = g.params["cooldown_days"]
            return
        g.tradecode = current_code
        return

    g.best_close = None
    if g.cooldown > 0:
        g.cooldown -= 1
        log.info("V1.6 cooldown after exit, remaining=%s", g.cooldown)
        return
    if target_direction == 0:
        return

    if open_position(context, target_contract, target_direction, snapshot):
        g.tradecode = target_contract
        g.pending_contract = None
