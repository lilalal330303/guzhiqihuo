# -*- coding: utf-8 -*-
"""固收+当前稳定版 V1.0：进取路线锁定版。"""

import datetime
import math

import pandas as pd

from jqdata import *


RISK_CODES = {
    "510880.XSHG",
    "512890.XSHG",
    "513100.XSHG",
    "518880.XSHG",
}


def initialize(context):
    set_benchmark("511010.XSHG")
    set_option("use_real_price", True)
    set_option("avoid_future_data", True)
    set_slippage(FixedSlippage(0.002))
    set_order_cost(
        OrderCost(
            open_tax=0,
            close_tax=0,
            open_commission=0.0002,
            close_commission=0.0002,
            close_today_commission=0,
            min_commission=5,
        ),
        type="fund",
    )
    log.set_level("order", "error")

    g.params = {
        "name": "固收+当前稳定版V1.0_进取路线锁定",
        "version": "stable-v1.0",
        "weights": {
            "511010.XSHG": 0.60,
            "511990.XSHG": 0.05,
            "518880.XSHG": 0.10,
            "510880.XSHG": 0.125,
            "513100.XSHG": 0.125,
        },
        "rebalance_every_days": 20,
        "rebalance_threshold": 0.15,
        "momentum_window": 120,
        "vol_window": 60,
        "target_volatility": 0.06,
        "cash_buffer": 0.02,
        "min_listing_days": 60,
        "min_lots": 1,
        "lot_size": 100,
        "float_tolerance": 1e-8,
        "cash_proxy": "511990.XSHG",
    }
    g.trade_days = 0
    run_daily(trade, time="9:35")


def normalize_weights(weights):
    """清理并归一化权重，修复 dict_values 与整数比较报错。"""

    positive = {}
    for code, value in weights.items():
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value) and value > 0:
            positive[code] = value

    # 关键修复：必须使用 sum，不能直接写 positive.values()。
    total = sum(positive.values())
    if total <= 0:
        log.warn("目标权重为空或无效")
        return {}

    tolerance = g.params.get("float_tolerance", 1e-8)
    if abs(total - 1.0) > tolerance:
        log.info("目标权重和为 %.8f，执行归一化", total)
    return {code: value / total for code, value in positive.items()}


def valid_price(value):
    try:
        return value is not None and math.isfinite(float(value)) and float(value) > 0
    except (TypeError, ValueError):
        return False


def close_history(context, code, count):
    try:
        frame = get_price(
            code,
            end_date=context.previous_date,
            count=count,
            frequency="daily",
            fields=["close"],
            fq=None,
            skip_paused=False,
        )
    except Exception as exc:
        log.info("跳过 %s 历史数据：%s", code, exc)
        return pd.Series(dtype=float)

    if frame is None or "close" not in getattr(frame, "columns", []):
        return pd.Series(dtype=float)
    return pd.to_numeric(frame["close"], errors="coerce").dropna()


def inverse_vol_weights(context, weights):
    risk_codes = [code for code in weights if code in RISK_CODES]
    if not risk_codes:
        return weights

    vol = {}
    window = g.params["vol_window"]
    for code in risk_codes:
        history = close_history(context, code, window + 1)
        if len(history) < window + 1:
            return weights
        returns = history.pct_change().dropna().tail(window)
        value = float(returns.std() * math.sqrt(252))
        if not valid_price(value):
            return weights
        vol[code] = value

    risk_budget = sum(weights[code] for code in risk_codes)
    inverse_sum = sum(1.0 / value for value in vol.values())
    if not valid_price(inverse_sum):
        return weights

    for code in risk_codes:
        weights[code] = risk_budget * (1.0 / vol[code]) / inverse_sum
    return weights


def portfolio_volatility(context, weights):
    histories = {}
    window = g.params["vol_window"]
    for code in weights:
        history = close_history(context, code, window + 1)
        if len(history) < window + 1:
            return None
        histories[code] = history.pct_change().dropna().tail(window)

    if not histories:
        return None
    returns = pd.concat(histories, axis=1).dropna()
    if len(returns) < 2:
        return None

    portfolio_returns = pd.Series(0.0, index=returns.index)
    for code, weight in weights.items():
        if code in returns:
            portfolio_returns = portfolio_returns + returns[code] * weight

    value = float(portfolio_returns.std() * math.sqrt(252))
    return value if valid_price(value) else None


def calculate_target_weights(context):
    weights = normalize_weights(g.params["weights"])
    if not weights:
        return {}

    # 风险资产按最近 60 日波动率倒数分配风险预算。
    weights = inverse_vol_weights(context, weights)

    # 组合年化波动率超过目标时，把风险资产的部分权重转入现金管理 ETF。
    realized = portfolio_volatility(context, weights)
    target_volatility = g.params["target_volatility"]
    if realized is not None and realized > target_volatility:
        scale = min(1.0, target_volatility / realized)
        moved = 0.0
        for code in RISK_CODES:
            if code in weights:
                old = weights[code]
                weights[code] = old * scale
                moved += old - weights[code]
        cash_proxy = g.params["cash_proxy"]
        weights[cash_proxy] = weights.get(cash_proxy, 0.0) + moved

    # 现金缓冲进入现金管理 ETF；买入时还会再次保留可用现金。
    cash_proxy = g.params["cash_proxy"]
    weights[cash_proxy] = weights.get(cash_proxy, 0.0) + g.params["cash_buffer"]
    return normalize_weights(weights)


def tradeable(context, code, for_buy, current_data=None):
    info = get_security_info(code)
    if info is None:
        log.info("跳过 %s：证券信息为空", code)
        return False

    if context.previous_date - info.start_date < datetime.timedelta(
        days=g.params["min_listing_days"]
    ):
        log.info("跳过 %s：上市时间不足", code)
        return False

    if current_data is None:
        current_data = get_current_data()
    try:
        current = current_data[code]
    except Exception:
        log.info("跳过 %s：无法取得实时数据", code)
        return False

    last_price = getattr(current, "last_price", None)
    high_limit = getattr(current, "high_limit", None)
    low_limit = getattr(current, "low_limit", None)
    if getattr(current, "paused", False) or not valid_price(last_price):
        log.info("跳过 %s：停牌或价格无效", code)
        return False
    if not valid_price(high_limit) or not valid_price(low_limit):
        log.info("跳过 %s：涨跌停边界无效", code)
        return False
    if for_buy and last_price >= high_limit:
        log.info("跳过 %s：涨停无法买入", code)
        return False
    if not for_buy and last_price <= low_limit:
        log.info("跳过 %s：跌停无法卖出", code)
        return False
    return True


def position_value(context, code):
    position = context.portfolio.positions.get(code)
    if position is None:
        return 0.0
    try:
        return max(float(position.value), 0.0)
    except (TypeError, ValueError):
        return 0.0


def trade(context):
    g.trade_days += 1
    period = g.params["rebalance_every_days"]

    # 第 1 个交易日建仓，之后每隔 period 个交易日再平衡。
    if g.trade_days != 1 and (g.trade_days - 1) % period != 0:
        return

    target_weights = calculate_target_weights(context)
    if not target_weights:
        return

    total_value = float(context.portfolio.total_value)
    tolerance = g.params["float_tolerance"]
    current_data = get_current_data()
    sells = []
    buys = []

    for code, weight in target_weights.items():
        try:
            current = current_data[code]
        except Exception:
            continue

        last_price = getattr(current, "last_price", None)
        if not valid_price(last_price):
            log.info("跳过 %s：无有效价格", code)
            continue

        target_value = total_value * weight
        current_value = position_value(context, code)
        difference = target_value - current_value
        deviation = abs(difference) / max(target_value, tolerance)
        minimum_value = (
            g.params["min_lots"] * g.params["lot_size"] * float(last_price)
        )

        if deviation <= g.params["rebalance_threshold"] + tolerance:
            continue
        if abs(difference) < minimum_value:
            continue

        if difference < 0 and tradeable(context, code, False, current_data):
            sells.append((code, target_value))
        elif difference > 0 and tradeable(context, code, True, current_data):
            buys.append((code, target_value))

    # 先卖后买，释放现金后再增仓。
    for code, target_value in sells:
        result = order_target_value(code, target_value)
        log.info("减仓 %s 到 %.2f：%s", code, target_value, result)

    reserve = total_value * g.params["cash_buffer"]
    try:
        usable_cash = max(float(context.portfolio.available_cash) - reserve, 0.0)
    except (TypeError, ValueError):
        usable_cash = 0.0

    for code, target_value in buys:
        current_value = position_value(context, code)
        affordable_target = current_value + usable_cash
        constrained_target = min(target_value, affordable_target)
        if constrained_target <= current_value + tolerance:
            log.info("跳过 %s：扣除现金缓冲后资金不足", code)
            continue

        result = order_target_value(code, constrained_target)
        log.info("增仓 %s 到 %.2f：%s", code, constrained_target, result)
        usable_cash = max(usable_cash - (constrained_target - current_value), 0.0)


