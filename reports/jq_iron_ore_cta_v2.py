"""铁矿石 CTA V2，可直接复制到聚宽策略编辑器。

默认 `ALLOW_SHORT = False`，用于和原始长多/空仓版本做可比回测；
确认执行和风控口径后，将其改为 True 才启用下行趋势做空。
"""

import math
import re

import pandas as pd

try:
    from jqdata import *
except ImportError:  # 本地测试时没有 jqdata；聚宽环境会走上面的真实 API。
    class _FallbackLog:
        def info(self, *args, **kwargs):
            return None

        def warn(self, *args, **kwargs):
            return None

    log = _FallbackLog()


SIGNAL_SECURITY = "I8888.XDCE"
ALLOW_SHORT = False


DEFAULT_PARAMS = {
    "allow_short": ALLOW_SHORT,
    "fast_days": 20,
    "trend_days": 60,
    "slope_days": 10,
    "atr_days": 20,
    "confirmation_days": 2,
    "entry_buffer": 0.003,
    "exit_buffer": 0.003,
    "min_spread": 0.002,
    "min_slope": 0.0005,
    "stop_atr": 3.5,
    "cooldown_days": 3,
    "roll_days_before_expiry": 8,
    # deferred_rank=1 表示按到期日排序后的第二个可用合约，保留原策略次远月倾向。
    "deferred_rank": 1,
    "contract_multiplier": 100,
    "margin_rate": 0.15,
    "max_margin_usage": 0.45,
    "risk_per_atr": 0.012,
}


def initialize(context):
    set_benchmark(SIGNAL_SECURITY)
    set_option("use_real_price", True)
    set_option("avoid_future_data", True)

    g.params = dict(DEFAULT_PARAMS)
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

    g.current_contract = None
    g.current_direction = 0
    g.pending_contract = None
    g.pending_direction = 0
    g.raw_signal = 0
    g.raw_signal_days = 0
    g.confirmed_signal = 0
    g.cooldown = 0

    log.info(
        "CTA_V2 initialized: security=%s allow_short=%s deferred_rank=%s",
        SIGNAL_SECURITY,
        g.params["allow_short"],
        g.params["deferred_rank"],
    )
    run_daily(trade_open, time="09:05", reference_security=SIGNAL_SECURITY)


def select_contract_code(
    futures, signal_date, roll_days_before_expiry=8, deferred_rank=1
):
    """按点时合约列表选择安全的次近月 I 合约。"""
    if futures is None or getattr(futures, "empty", True):
        return None

    signal_day = pd.Timestamp(signal_date).date()
    eligible = []
    for code, row in futures.iterrows():
        raw = str(code).upper()
        if re.match(r"^I\d{4}\.XDCE$", raw) is None:
            continue
        try:
            start_day = pd.Timestamp(row["start_date"]).date()
            end_day = pd.Timestamp(row["end_date"]).date()
        except (KeyError, TypeError, ValueError):
            continue
        days_left = (end_day - signal_day).days
        if start_day > signal_day or end_day <= signal_day:
            continue
        if days_left <= int(roll_days_before_expiry):
            continue
        eligible.append((end_day, raw))

    eligible.sort(key=lambda item: (item[0], item[1]))
    if not eligible:
        return None
    rank = max(0, min(int(deferred_rank), len(eligible) - 1))
    return eligible[rank][1]


def classify_trend(closes, params):
    """返回 1=上行、-1=下行、0=震荡或样本不足。"""
    values = pd.Series(closes).dropna().astype(float)
    fast_days = int(params["fast_days"])
    trend_days = int(params["trend_days"])
    slope_days = int(params["slope_days"])
    min_required = trend_days + slope_days
    if len(values) < min_required:
        return 0

    ma_fast = float(values.iloc[-fast_days:].mean())
    ma_trend = float(values.iloc[-trend_days:].mean())
    ma_trend_prev = float(
        values.iloc[-trend_days - slope_days : -slope_days].mean()
    )
    price = float(values.iloc[-1])
    if not all(
        math.isfinite(value) and value > 0
        for value in (price, ma_fast, ma_trend, ma_trend_prev)
    ):
        return 0

    spread = ma_fast / ma_trend - 1.0
    slope = ma_trend / ma_trend_prev - 1.0
    if (
        price > ma_fast * (1.0 + params["entry_buffer"])
        and spread > params["min_spread"]
        and slope > params["min_slope"]
    ):
        return 1
    if (
        price < ma_fast * (1.0 - params["exit_buffer"])
        and spread < -params["min_spread"]
        and slope < -params["min_slope"]
    ):
        return -1
    return 0


def transition_direction(current_direction, confirmed_signal, allow_short):
    """将确认信号映射成实际目标方向，0 表示空仓。"""
    if confirmed_signal > 0:
        return 1
    if confirmed_signal < 0:
        return -1 if allow_short else 0
    return current_direction


def calculate_contract_amount(total_value, available_cash, price, atr, params):
    """ATR 风险预算与保证金预算取小，并向下取整。"""
    if min(float(total_value), float(available_cash), float(price), float(atr)) <= 0:
        return 0

    multiplier = float(params["contract_multiplier"])
    risk_lots = int(
        float(total_value)
        * float(params["risk_per_atr"])
        // (float(atr) * multiplier)
    )
    margin_per_contract = (
        float(price) * multiplier * float(params["margin_rate"])
    )
    if margin_per_contract <= 0:
        return 0
    margin_lots = int(
        max(0.0, float(available_cash))
        * float(params["max_margin_usage"])
        // margin_per_contract
    )
    return max(0, min(risk_lots, margin_lots))


def can_open_replacement(old_amount, close_filled, remaining_amount):
    """只有旧仓实际归零，才允许开替代合约。"""
    if float(old_amount) <= 0:
        return True
    return float(close_filled) >= float(old_amount) and float(remaining_amount) <= 0


def calculate_atr(price_data, atr_days):
    if price_data is None or len(price_data) < int(atr_days) + 1:
        return None
    required = {"high", "low", "close"}
    if not required.issubset(set(price_data.columns)):
        return None
    data = price_data[["high", "low", "close"]].dropna().astype(float)
    if len(data) < int(atr_days) + 1:
        return None
    previous_close = data["close"].shift(1)
    true_range = pd.concat(
        [
            data["high"] - data["low"],
            (data["high"] - previous_close).abs(),
            (data["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = float(true_range.iloc[-int(atr_days) :].mean())
    return atr if math.isfinite(atr) and atr > 0 else None


def get_signal_snapshot(signal_date):
    count = max(
        int(g.params["trend_days"]) + int(g.params["slope_days"]) + 2,
        int(g.params["atr_days"]) + 2,
    )
    data = get_price(
        SIGNAL_SECURITY,
        end_date=signal_date,
        frequency="daily",
        fields=["high", "low", "close"],
        count=count,
        panel=False,
    )
    if data is None or data.empty or "close" not in data.columns:
        return None
    data = data.dropna(subset=["close"])
    if len(data) < count:
        return None

    closes = data["close"].astype(float)
    ma_fast = float(closes.iloc[-g.params["fast_days"] :].mean())
    atr = calculate_atr(data, g.params["atr_days"])
    if atr is None or not math.isfinite(ma_fast):
        return None
    return {
        "raw_signal": classify_trend(closes, g.params),
        "close": float(closes.iloc[-1]),
        "ma_fast": ma_fast,
        "atr": atr,
        "signal_date": signal_date,
    }


def update_signal_confirmation(raw_signal):
    if raw_signal == g.raw_signal:
        g.raw_signal_days += 1
    else:
        g.raw_signal = raw_signal
        g.raw_signal_days = 1

    if raw_signal in (1, -1) and g.raw_signal_days >= g.params["confirmation_days"]:
        g.confirmed_signal = raw_signal
    return g.confirmed_signal


def get_account(context):
    subportfolios = getattr(context, "subportfolios", None)
    if subportfolios:
        return subportfolios[0]
    return context.portfolio


def get_total_value(context):
    account = get_account(context)
    return float(getattr(account, "total_value", context.portfolio.total_value))


def get_available_cash(context):
    account = get_account(context)
    value = getattr(account, "available_cash", None)
    if value is None:
        value = getattr(account, "cash", 0.0)
    return float(value)


def get_positions(context):
    account = get_account(context)
    return getattr(account, "positions", {}) or {}


def get_position_amount(context, contract, direction):
    position = get_positions(context).get(contract)
    if position is None:
        return 0.0
    field = "long_amount" if direction > 0 else "short_amount"
    value = getattr(position, field, None)
    if value is None:
        value = getattr(position, "total_amount", 0.0)
    try:
        return abs(float(value))
    except (TypeError, ValueError):
        return 0.0


def get_actual_exposure(context):
    for contract in get_positions(context):
        long_amount = get_position_amount(context, contract, 1)
        if long_amount > 0:
            return contract, 1, long_amount
        short_amount = get_position_amount(context, contract, -1)
        if short_amount > 0:
            return contract, -1, short_amount
    return None, 0, 0.0


def is_order_fully_filled(order):
    if order is None:
        return False
    amount = abs(float(getattr(order, "amount", 0) or 0))
    filled = abs(float(getattr(order, "filled", 0) or 0))
    return amount > 0 and filled >= amount


def close_directional_position(context, contract, direction):
    current_amount = get_position_amount(context, contract, direction)
    if current_amount <= 0:
        return True
    side = "long" if direction > 0 else "short"
    order = order_target(contract, 0, side=side)
    remaining = get_position_amount(context, contract, direction)
    if remaining > 0:
        log.info(
            "CTA_V2 close incomplete: contract=%s side=%s requested=%s filled=%s remaining=%s",
            contract,
            side,
            current_amount,
            getattr(order, "filled", 0) if order is not None else 0,
            remaining,
        )
        return False
    return is_order_fully_filled(order) or remaining <= 0


def open_directional_position(context, contract, amount, direction):
    if amount <= 0:
        return False
    side = "long" if direction > 0 else "short"
    order = order_target(contract, int(amount), side=side)
    actual = get_position_amount(context, contract, direction)
    if actual > 0:
        log.info(
            "CTA_V2 open submitted: contract=%s side=%s target=%s actual=%s filled=%s",
            contract,
            side,
            amount,
            actual,
            getattr(order, "filled", 0) if order is not None else 0,
        )
        return True
    if is_order_fully_filled(order):
        return True
    log.info(
        "CTA_V2 open not filled: contract=%s side=%s target=%s",
        contract,
        side,
        amount,
    )
    return False


def get_contract_price(contract, signal_date):
    data = get_price(
        contract,
        end_date=signal_date,
        frequency="daily",
        fields=["close"],
        count=1,
        panel=False,
    )
    if data is None or data.empty or "close" not in data.columns:
        return None
    price = float(data["close"].iloc[-1])
    return price if math.isfinite(price) and price > 0 else None


def get_target_contract(signal_date):
    futures = get_all_securities(["futures"], date=signal_date)
    return select_contract_code(
        futures,
        signal_date,
        g.params["roll_days_before_expiry"],
        g.params["deferred_rank"],
    )


def emergency_exit(snapshot, direction):
    if direction == 0:
        return False
    stop_atr = float(g.params["stop_atr"])
    if direction > 0:
        return snapshot["close"] < snapshot["ma_fast"] - stop_atr * snapshot["atr"]
    return snapshot["close"] > snapshot["ma_fast"] + stop_atr * snapshot["atr"]


def submit_target(context, target_contract, target_direction, snapshot):
    current_contract, current_direction, current_amount = get_actual_exposure(context)

    if current_direction != 0 and emergency_exit(snapshot, current_direction):
        log.info(
            "CTA_V2 emergency exit: date=%s contract=%s direction=%s close=%.2f ma20=%.2f atr=%.2f",
            snapshot["signal_date"],
            current_contract,
            current_direction,
            snapshot["close"],
            snapshot["ma_fast"],
            snapshot["atr"],
        )
        if close_directional_position(context, current_contract, current_direction):
            g.cooldown = int(g.params["cooldown_days"])
        return

    if target_direction == 0:
        if current_direction != 0 and close_directional_position(
            context, current_contract, current_direction
        ):
            g.cooldown = int(g.params["cooldown_days"])
            g.current_contract = None
            g.current_direction = 0
            log.info("CTA_V2 flat: date=%s reason=confirmed_down_or_neutral", snapshot["signal_date"])
        return

    if target_contract is None:
        log.info("CTA_V2 skip: date=%s reason=no_safe_contract", snapshot["signal_date"])
        return

    if current_direction != 0 and (
        current_direction != target_direction or current_contract != target_contract
    ):
        if close_directional_position(context, current_contract, current_direction):
            g.pending_contract = target_contract
            g.pending_direction = target_direction
            g.current_contract = None
            g.current_direction = 0
            log.info(
                "CTA_V2 replacement pending: old=%s new=%s direction=%s",
                current_contract,
                target_contract,
                target_direction,
            )
        return

    if g.cooldown > 0 and current_direction == 0:
        log.info(
            "CTA_V2 skip: date=%s reason=cooldown remaining=%s",
            snapshot["signal_date"],
            g.cooldown,
        )
        return

    price = get_contract_price(target_contract, snapshot["signal_date"])
    if price is None:
        log.info(
            "CTA_V2 skip: date=%s reason=no_contract_price contract=%s",
            snapshot["signal_date"],
            target_contract,
        )
        return
    amount = calculate_contract_amount(
        get_total_value(context),
        get_available_cash(context),
        price,
        snapshot["atr"],
        g.params,
    )
    if amount <= 0:
        log.info(
            "CTA_V2 skip: date=%s reason=zero_target_amount price=%.2f atr=%.2f",
            snapshot["signal_date"],
            price,
            snapshot["atr"],
        )
        return

    if open_directional_position(context, target_contract, amount, target_direction):
        g.current_contract = target_contract
        g.current_direction = target_direction
        g.pending_contract = None
        g.pending_direction = 0


def trade_open(context):
    signal_date = getattr(context, "previous_date", None)
    if signal_date is None:
        log.info("CTA_V2 skip: reason=context_has_no_previous_date")
        return

    if g.cooldown > 0:
        g.cooldown -= 1

    snapshot = get_signal_snapshot(signal_date)
    if snapshot is None:
        log.info("CTA_V2 skip: date=%s reason=insufficient_or_invalid_data", signal_date)
        return

    raw_signal = snapshot["raw_signal"]
    confirmed_signal = update_signal_confirmation(raw_signal)
    _, actual_direction, _ = get_actual_exposure(context)
    if actual_direction != 0:
        g.current_direction = actual_direction

    target_direction = transition_direction(
        g.current_direction,
        confirmed_signal,
        g.params["allow_short"],
    )
    target_contract = None
    if target_direction != 0:
        target_contract = get_target_contract(signal_date)

    log.info(
        "CTA_V2 signal: date=%s raw=%s raw_days=%s confirmed=%s target_direction=%s contract=%s close=%.2f ma20=%.2f atr=%.2f",
        signal_date,
        raw_signal,
        g.raw_signal_days,
        confirmed_signal,
        target_direction,
        target_contract,
        snapshot["close"],
        snapshot["ma_fast"],
        snapshot["atr"],
    )
    submit_target(context, target_contract, target_direction, snapshot)
