"""Iron ore CTA V1.3.

This standalone JoinQuant script keeps the V1.1 strict trend signal and
close-first rollover flow. It adds volatility-based sizing and a drawdown
multiplier for new entries. Copy this whole file into the JoinQuant editor.
Shorting is disabled by default.
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
ALLOW_SHORT = False

DEFAULT_PARAMS = {
    "fast_days": 20,
    "trend_days": 60,
    "slope_days": 10,
    "atr_days": 20,
    "vol_days": 20,
    "confirmation_days": 2,
    "entry_buffer": 0.002,
    "min_spread": 0.002,
    "min_slope": 0.0005,
    "target_annual_vol": 0.20,
    "max_leverage": 2.5,
    "margin_rate": 0.15,
    "max_margin_usage": 0.40,
    "roll_days_before_expiry": 8,
    "contract_multiplier": 100,
    "stop_atr": 3.0,
    "cooldown_days": 2,
}


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
    """Return 1 for bullish, -1 for bearish, 0 for neutral."""
    values = _clean_closes(closes)
    minimum = trend_days + slope_days + max(1, confirmation_days) - 1
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
    recent = states[-max(1, confirmation_days):]
    if all(state == 1 for state in recent):
        return 1
    if all(state == -1 for state in recent):
        return -1
    return 0


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
    return float(pd.Series(returns).std(ddof=1) * math.sqrt(annual_days))


def calculate_atr(bars, window=20):
    """Return a simple-average true range."""
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
    return int(notional_budget // (float(price) * multiplier))


def calculate_drawdown_multiplier(current_value, high_water):
    """Return a new-entry risk multiplier from the portfolio drawdown."""
    if not _finite_positive(current_value) or not _finite_positive(high_water):
        return 0.0
    drawdown = round(
        max(0.0, 1.0 - float(current_value) / float(high_water)),
        10,
    )
    if drawdown < 0.10:
        return 1.0
    if drawdown < 0.15:
        return 0.75
    if drawdown < 0.20:
        return 0.50
    return 0.0


def calculate_risk_scaled_amount(
    total_value, available_cash, price, realized_vol, risk_multiplier, params
):
    """Apply the drawdown multiplier after volatility-based sizing."""
    try:
        risk_multiplier = float(risk_multiplier)
    except (TypeError, ValueError):
        return 0
    if not math.isfinite(risk_multiplier) or risk_multiplier <= 0:
        return 0
    risk_multiplier = min(1.0, risk_multiplier)
    base_amount = calculate_vol_scaled_amount(
        total_value,
        available_cash,
        price,
        realized_vol,
        params,
    )
    return int(max(0.0, float(base_amount) * risk_multiplier))


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
    g.params = DEFAULT_PARAMS.copy()
    g.params["allow_short"] = ALLOW_SHORT
    g.tradecode = ""
    g.pending_contract = None
    g.cooldown = 0
    g.high_water_value = float(context.portfolio.starting_cash)
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
    count = max(
        DEFAULT_PARAMS["trend_days"] + DEFAULT_PARAMS["slope_days"] + 5,
        DEFAULT_PARAMS["atr_days"] + 5,
        DEFAULT_PARAMS["vol_days"] + 5,
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
    if len(closes) < DEFAULT_PARAMS["trend_days"] + DEFAULT_PARAMS["slope_days"]:
        return None
    params = g.params
    signal = classify_v1_signal(
        closes,
        fast_days=params["fast_days"],
        trend_days=params["trend_days"],
        slope_days=params["slope_days"],
        confirmation_days=params["confirmation_days"],
        entry_buffer=params["entry_buffer"],
        min_spread=params["min_spread"],
        min_slope=params["min_slope"],
    )
    fast = float(pd.Series(closes).tail(params["fast_days"]).mean())
    slow = float(pd.Series(closes).tail(params["trend_days"]).mean())
    atr = calculate_atr(data, params["atr_days"])
    realized_vol = calculate_realized_volatility(
        closes[-params["vol_days"] - 1:]
    )
    return {
        "signal": signal,
        "close": float(closes[-1]),
        "ma_fast": fast,
        "ma_slow": slow,
        "atr": atr,
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
        if long_amount is not None and int(long_amount or 0) > 0:
            return int(long_amount)
        return int(getattr(position, "total_amount", 0) or 0)
    short_amount = getattr(position, "short_amount", None)
    return int(short_amount or 0)


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
        log.info("V1.3 close code=%s direction=%s amount=%s", code, direction, amount)
        return remaining == 0
    log.info("V1.3 close not complete code=%s remaining=%s", code, remaining)
    return False


def should_force_exit(direction, snapshot):
    atr = snapshot.get("atr", 0.0)
    if atr <= 0:
        return False
    close = snapshot["close"]
    fast = snapshot["ma_fast"]
    distance = float(g.params["stop_atr"]) * atr
    if direction > 0:
        return close < fast - distance
    return close > fast + distance


def open_position(context, code, direction, snapshot):
    price = get_contract_price(code, context.previous_date)
    if price is None:
        log.info("V1.3 no valid contract price, skip entry code=%s", code)
        return False
    total_value = float(getattr(context.portfolio, "total_value", 0.0))
    available_cash = float(
        getattr(
            context.portfolio,
            "available_cash",
            getattr(context.portfolio, "cash", 0.0),
        )
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
            "V1.3 risk budget does not allow new entry code=%s multiplier=%.2f",
            code,
            g.risk_multiplier,
        )
        return False
    side = "long" if direction > 0 else "short"
    order = order_target(code, amount, side=side)
    if not is_order_fully_filled(order):
        log.info("V1.3 entry not fully filled code=%s amount=%s", code, amount)
    else:
        log.info(
            "V1.3 entry code=%s direction=%s amount=%s vol=%.4f risk=%.2f",
            code,
            direction,
            amount,
            snapshot["realized_vol"],
            g.risk_multiplier,
        )
    return True


def trade_open(context):
    signal_date = context.previous_date
    total_value = float(getattr(context.portfolio, "total_value", 0.0))
    g.high_water_value = max(g.high_water_value, total_value)
    g.risk_multiplier = calculate_drawdown_multiplier(
        total_value,
        g.high_water_value,
    )

    snapshot = get_signal_snapshot(signal_date)
    if snapshot is None:
        log.info("V1.3 insufficient signal data date=%s", signal_date)
        return

    target_contract = get_target_contract(signal_date)
    if not target_contract:
        log.info("V1.3 no eligible iron ore contract date=%s", signal_date)
        return

    current_code, current_direction, current_amount = get_actual_position(context)
    raw_signal = snapshot["signal"]
    if raw_signal == 1:
        target_direction = 1
    elif raw_signal == -1 and g.params["allow_short"]:
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
                g.tradecode = ""
                g.pending_contract = target_contract if target_direction else None
                g.cooldown = g.params["cooldown_days"]
            return
        g.tradecode = current_code
        return

    if g.cooldown > 0:
        g.cooldown -= 1
        log.info("V1.3 cooldown after exit, remaining=%s", g.cooldown)
        return
    if target_direction == 0:
        return

    if open_position(context, target_contract, target_direction, snapshot):
        g.tradecode = target_contract
        g.pending_contract = None
