# -*- coding:utf-8 -*-
"""
V69 当前策略聚宽回测脚本

参考本地 V69：
1. 1分钟K线，四类股指期货 IF/IH/IC/IM。
2. 主策略只交易：趋势回踩、开盘区间突破。
3. 箱体、VWAP偏离只做观察，不直接开仓。
4. 组合最多4手敞口；同品种不同时持有多笔敞口；同向最多2手。
5. 当天新开仓退出时允许反向开仓形成有效对锁。
6. 昨日对锁旧仓可平单边作为开仓筹码；复用时必须方向匹配。
7. 如果同品种同方向今仓会挡住平昨，则不复用旧筹码，改为新开；由旧筹码形成的敞口退出时直接平昨，不再滚动续锁。

注意：
- 本脚本按聚宽 Python3 格式改造：initialize + run_daily(every_bar) + attribute_history + order/order_target。
- 聚宽金融期货默认会区分平今费用；旧筹码复用、对锁库存仍用脚本内 ledger 做策略层标记。
- 默认每天选择聚宽当月可交易合约；如需固定跑某一期，改 V69_CONTRACT_MODE 为 "fixed_stage"，并修改 V69_STAGE。
"""

import pandas as pd


V69_STAGE = "2606"
V69_CONTRACT_MODE = "current_month"  # current_month / fixed_stage
V69_CONTRACT_MONTH = "current_month"  # current_month / next_month / next_quarter / skip_quarter
V69_PRODUCTS = ["IF", "IH", "IC", "IM"]
V69_OFFICIAL_START = ""


def initialize(context):
    set_benchmark("000300.XSHG")
    set_option("use_real_price", True)
    set_option("order_volume_ratio", 1)
    set_option("futures_margin_rate", 0.13)
    set_subportfolios([SubPortfolioConfig(cash=context.portfolio.cash, type="index_futures")])
    set_order_cost(
        OrderCost(open_commission=0.000023, close_commission=0.000023, close_today_commission=0.0023),
        type="index_futures",
    )
    log.info("V69聚宽策略：允许对锁 + 旧筹码方向约束 + 平昨今仓阻挡检查")

    context.v69_stage = V69_STAGE
    context.v69_contract_mode = V69_CONTRACT_MODE
    context.v69_contract_month = V69_CONTRACT_MONTH
    context.official_start = V69_OFFICIAL_START
    context.v69_products = list(V69_PRODUCTS)
    context.contracts = {}
    context.ins = "IF1512.CCFX"

    context.initial_cash = 1000000
    context.signal_frequency = "1m"
    context.signal_bar_count = 420
    context.min_signal_bars = 80

    context.v69_multiplier = {"IF": 300, "IH": 300, "IC": 200, "IM": 200}
    context.v69_margin_rate = {"IF": 0.12, "IH": 0.12, "IC": 0.12, "IM": 0.12}
    context.risk_points = {"IF": 66.7, "IH": 66.7, "IC": 100.0, "IM": 100.0}

    context.first_open_hhmm = 945
    context.last_open_hhmm = 1435
    context.force_lock_hhmm = 1455
    context.open_range_end_hhmm = 945
    context.no_trade_before_hhmm = 945
    context.max_active_lots = 4
    context.max_same_direction_lots = 2
    context.max_lock_pairs_per_product = 4
    context.max_daily_open = 80
    context.v69_min_available_cash_ratio = 0.05
    context.min_action_interval_min = 1
    context.cross_product_cool_min = 6

    context.atr_n = 14
    context.ema_n = 20
    context.adx_n = 14
    context.trend_adx_min = 18
    context.open_range_min_atr = 0.80
    context.pullback_buffer_atr = 0.20
    context.stop_floor_ratio = 0.35
    context.stop_atr_mult = 1.00
    context.trend_tp_r = 1.20
    context.opening_tp_r = 1.00

    context.ledger = {}
    context.open_positions = []
    context.lock_inventory = {}
    context.opening_range = {}
    context.last_action_min = -99999
    context.last_route_signature = {}
    context.daily_open_count = 0
    context.daily_realized_pnl = 0.0
    context.tail_locked = False
    context.last_bar_key = ""
    context.last_diag_date = ""
    context.last_diag_hhmm = -1

    _refresh_contracts(context)

    run_daily(before_trading, time="before_open", reference_security=context.ins)
    run_daily(trade, time="every_bar", reference_security=context.ins)


def before_trading(context):
    _refresh_contracts(context)
    for code, book in context.ledger.items():
        book["long_yday"] += book["long_today"]
        book["short_yday"] += book["short_today"]
        book["long_today"] = 0
        book["short_today"] = 0
    context.open_positions = []
    context.opening_range = dict((code, {"high": 0.0, "low": 0.0, "ready": False}) for code in context.contracts.values())
    context.daily_open_count = 0
    context.daily_realized_pnl = 0.0
    context.tail_locked = False
    context.last_action_min = -99999
    context.last_route_signature = {}
    context.last_bar_key = ""


def _ensure_product_book(context, product, code):
    if code not in context.ledger:
        context.ledger[code] = {
            "product": product,
            "long_today": 0,
            "short_today": 0,
            "long_yday": 0,
            "short_yday": 0,
            "long_y_price": 0.0,
            "short_y_price": 0.0,
        }
    if code not in context.lock_inventory:
        context.lock_inventory[code] = []
    if code not in context.opening_range:
        context.opening_range[code] = {"high": 0.0, "low": 0.0, "ready": False}


def _get_stock_index_future_code(context, product, month):
    if context.v69_contract_mode == "fixed_stage":
        return product + context.v69_stage + ".CCFX"
    display_name_dict = {
        "IF": ["沪深300指数期货", "沪深300股指期货"],
        "IH": ["上证50股指期货", "上证50指数期货"],
        "IC": ["中证500股指期货", "中证500指数期货"],
        "IM": ["中证1000股指期货", "中证1000指数期货"],
    }
    month_dict = {"current_month": 0, "next_month": 1, "next_quarter": 2, "skip_quarter": 3}
    dt = context.current_dt.date()
    display_names = display_name_dict.get(product, [])
    offset = month_dict.get(month, 0)
    try:
        all_futures = get_all_securities(types=["futures"], date=dt)
        active = all_futures[(all_futures.start_date <= dt) & (all_futures.end_date >= dt)]
        matched = active[active.display_name.isin(display_names)]
        if len(matched) == 0:
            matched = active[active.index.map(lambda x: str(x).startswith(product))]
        if len(matched) == 0:
            log.info("{} 当天未找到可交易合约，日期 {}".format(product, dt))
            return ""
        matched = matched.sort_index()
        if len(matched) > 4 and month in ("next_quarter", "skip_quarter"):
            offset += 1
        offset = min(offset, len(matched) - 1)
        return matched.index[offset]
    except Exception as exc:
        log.info("{} 获取聚宽期货合约失败：{}".format(product, exc))
        return ""


def _refresh_contracts(context):
    contracts = {}
    for product in context.v69_products:
        code = _get_stock_index_future_code(context, product, context.v69_contract_month)
        if not code:
            continue
        contracts[product] = code
        _ensure_product_book(context, product, code)
    if contracts:
        old = getattr(context, "contracts", {})
        context.contracts = contracts
        context.ins = contracts.get("IF", list(contracts.values())[0])
        if old != contracts:
            log.info("V69合约刷新：{}".format(context.contracts))


def _hhmm(dt):
    return int(dt.strftime("%H%M"))


def _minute_of_day(dt):
    return dt.hour * 60 + dt.minute


def _product_from_code(context, code):
    for product, contract in context.contracts.items():
        if contract == code:
            return product
    return code[:2]


def _jq_history(code, count, unit, fields):
    try:
        df = attribute_history(code, count, unit, fields, df=True)
    except Exception as exc:
        log.info("{} 获取行情失败：{}".format(code, exc))
        return None
    if df is None or len(df) == 0:
        return None
    return df


def _jq_position_amount(context, code, side):
    try:
        if side == "long":
            pos = context.portfolio.long_positions[code]
        else:
            pos = context.portfolio.short_positions[code]
        if hasattr(pos, "total_amount"):
            return int(pos.total_amount)
        if hasattr(pos, "closeable_amount"):
            return int(pos.closeable_amount)
    except Exception:
        return 0
    return 0


def _jq_order_open(code, side, qty):
    order(code, int(qty), side=side)


def _jq_order_close(context, code, side, qty):
    current_amount = _jq_position_amount(context, code, side)
    target_amount = max(current_amount - int(qty), 0)
    order_target(code, target_amount, side=side)


def _pop_lock_inventory(context, code, side):
    inv = context.lock_inventory.get(code, [])
    for idx, item in enumerate(inv):
        if item.get("side") == side:
            inv.pop(idx)
            return True
    return False


def _latest_price(context, code, now_dt):
    df = _jq_history(code, 2, context.signal_frequency, ["open", "high", "low", "close", "volume"])
    if df is None or len(df) == 0:
        return None
    return float(df["close"].iloc[-1])


def _calc_indicators(df, context):
    df = df.copy()
    prev_close = df["close"].shift(1)
    tr1 = df["high"] - df["low"]
    tr2 = (df["high"] - prev_close).abs()
    tr3 = (df["low"] - prev_close).abs()
    df["tr"] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df["atr"] = df["tr"].rolling(context.atr_n).mean()
    df["ema20"] = df["close"].ewm(span=context.ema_n, adjust=False).mean()
    df["vwap"] = (df["close"] * df["volume"]).cumsum() / df["volume"].replace(0, float("nan")).cumsum()
    up_move = df["high"] - df["high"].shift(1)
    dn_move = df["low"].shift(1) - df["low"]
    plus_dm = up_move.where((up_move > dn_move) & (up_move > 0), 0.0)
    minus_dm = dn_move.where((dn_move > up_move) & (dn_move > 0), 0.0)
    plus_di = 100 * plus_dm.rolling(context.adx_n).mean() / df["tr"].rolling(context.adx_n).mean()
    minus_di = 100 * minus_dm.rolling(context.adx_n).mean() / df["tr"].rolling(context.adx_n).mean()
    df["pdi"] = plus_di
    df["mdi"] = minus_di
    df["adx"] = (abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, float("nan")) * 100).rolling(context.adx_n).mean()
    df["ema_slope3"] = df["ema20"] - df["ema20"].shift(3)
    return df


def _get_signal_frame(context, code, now_dt):
    df = _jq_history(
        code,
        int(context.signal_bar_count),
        context.signal_frequency,
        ["open", "high", "low", "close", "volume"],
    )
    if df is None or len(df) < int(context.min_signal_bars):
        return None
    return _calc_indicators(df, context)


def _update_opening_range(context, code, df, hhmm):
    info = context.opening_range[code]
    if info["ready"]:
        return
    today = df.copy()
    if hasattr(today.index, "date"):
        today = today[today.index.date == today.index[-1].date()]
    if len(today) == 0:
        return
    opening = today[today.index.map(lambda x: _hhmm(x) <= context.open_range_end_hhmm)]
    if len(opening) > 0:
        info["high"] = float(opening["high"].max())
        info["low"] = float(opening["low"].min())
    if hhmm > context.open_range_end_hhmm and info["high"] > 0 and info["low"] > 0:
        info["ready"] = True


def _classify_candidate(context, code, df):
    product = _product_from_code(context, code)
    last = df.iloc[-1]
    prev = df.iloc[-2]
    required = ["atr", "ema20", "vwap", "adx", "pdi", "mdi", "ema_slope3"]
    if any(pd.isnull(last[x]) for x in required):
        return None
    price = float(last["close"])
    atr = float(last["atr"])
    if atr <= 0:
        return None
    info = context.opening_range[code]

    trend_up = (
        price > float(last["ema20"])
        and float(last["ema_slope3"]) > 0
        and price > float(last["vwap"])
        and float(last["adx"]) >= context.trend_adx_min
        and float(last["pdi"]) > float(last["mdi"])
    )
    trend_down = (
        price < float(last["ema20"])
        and float(last["ema_slope3"]) < 0
        and price < float(last["vwap"])
        and float(last["adx"]) >= context.trend_adx_min
        and float(last["mdi"]) > float(last["pdi"])
    )
    pullback_up = trend_up and float(last["low"]) <= float(last["ema20"]) + context.pullback_buffer_atr * atr and price > float(last["ema20"])
    pullback_down = trend_down and float(last["high"]) >= float(last["ema20"]) - context.pullback_buffer_atr * atr and price < float(last["ema20"])

    opening_width = info["high"] - info["low"] if info["ready"] else 0.0
    opening_up = info["ready"] and price > info["high"] and opening_width >= context.open_range_min_atr * atr and price > float(last["vwap"]) and float(last["pdi"]) > float(last["mdi"])
    opening_down = info["ready"] and price < info["low"] and opening_width >= context.open_range_min_atr * atr and price < float(last["vwap"]) and float(last["mdi"]) > float(last["pdi"])

    if pullback_up:
        module = "TREND_PULLBACK"
        side = "long"
        tp_r = context.trend_tp_r
        score = 3.0 + min(float(last["adx"]) / 20.0, 2.0)
        reason = "趋势回踩做多"
    elif pullback_down:
        module = "TREND_PULLBACK"
        side = "short"
        tp_r = context.trend_tp_r
        score = 3.0 + min(float(last["adx"]) / 20.0, 2.0)
        reason = "趋势回踩做空"
    elif opening_up:
        module = "OPENING_RANGE_BREAKOUT"
        side = "long"
        tp_r = context.opening_tp_r
        score = 2.0 + min(opening_width / atr, 2.0)
        reason = "开盘区间向上突破"
    elif opening_down:
        module = "OPENING_RANGE_BREAKOUT"
        side = "short"
        tp_r = context.opening_tp_r
        score = 2.0 + min(opening_width / atr, 2.0)
        reason = "开盘区间向下突破"
    else:
        return None

    stop_points = max(context.stop_floor_ratio * context.risk_points[product], context.stop_atr_mult * atr)
    expected_profit = stop_points * tp_r * context.v69_multiplier[product]
    expected_margin = price * context.v69_multiplier[product] * context.v69_margin_rate[product]
    efficiency = expected_profit / expected_margin if expected_margin > 0 else 0
    return {
        "code": code,
        "product": product,
        "side": side,
        "price": price,
        "atr": atr,
        "stop_points": stop_points,
        "take_profit_points": stop_points * tp_r,
        "score": score,
        "efficiency": efficiency,
        "module": module,
        "reason": reason,
        "bar_time": df.index[-1],
    }


def _active_lots(context):
    return len(context.open_positions)


def _same_direction_lots(context, side):
    return sum(1 for pos in context.open_positions if pos["side"] == side)


def _has_product_exposure(context, code):
    return any(pos["code"] == code for pos in context.open_positions)


def _available_cash_est(context):
    # 同花顺实盘账户对象字段因版本不同，这里用初始资金做保守估算占位。
    used_margin = 0.0
    for pos in context.open_positions:
        product = _product_from_code(context, pos["code"])
        used_margin += pos["entry_price"] * context.v69_multiplier[product] * context.v69_margin_rate[product]
    return context.initial_cash + context.daily_realized_pnl - used_margin


def _can_open_candidate(context, cand, now_min):
    if context.daily_open_count >= context.max_daily_open:
        return False
    if now_min - context.last_action_min < context.min_action_interval_min:
        return False
    if _active_lots(context) >= context.max_active_lots:
        return False
    if _same_direction_lots(context, cand["side"]) >= context.max_same_direction_lots:
        return False
    if _has_product_exposure(context, cand["code"]):
        return False
    if _available_cash_est(context) < context.initial_cash * context.v69_min_available_cash_ratio:
        return False
    return True


def _close_yday_chip_for_entry(context, code, side, price, reason):
    # side 是目标开仓方向；做多时平旧空，做空时平旧多。
    book = context.ledger[code]
    if side == "long":
        if book["short_yday"] <= 0:
            return False
        if book["short_today"] > 0:
            log.info("{}：有今日空仓，平旧空会被优先平今，放弃旧筹码复用 {}".format(code, reason))
            return False
        _pop_lock_inventory(context, code, "short")
        _jq_order_close(context, code, "short", 1)
        book["short_yday"] -= 1
        book["long_yday"] += 1
        book["long_y_price"] = price
        log.info("{}：平旧空一脚作为多头筹码 {}".format(code, reason))
        return True
    if book["long_yday"] <= 0:
        return False
    if book["long_today"] > 0:
        log.info("{}：有今日多仓，平旧多会被优先平今，放弃旧筹码复用 {}".format(code, reason))
        return False
    _pop_lock_inventory(context, code, "long")
    _jq_order_close(context, code, "long", 1)
    book["long_yday"] -= 1
    book["short_yday"] += 1
    book["short_y_price"] = price
    log.info("{}：平旧多一脚作为空头筹码 {}".format(code, reason))
    return True


def _open_new_position(context, cand, now_min):
    code = cand["code"]
    side = cand["side"]
    price = cand["price"]
    product = cand["product"]
    _jq_order_open(code, side, 1)
    book = context.ledger[code]
    if side == "long":
        book["long_today"] += 1
    else:
        book["short_today"] += 1
    context.open_positions.append({
        "code": code,
        "side": side,
        "entry_price": price,
        "entry_min": now_min,
        "entry_type": "new_open",
        "stop_points": cand["stop_points"],
        "take_profit_points": cand["take_profit_points"],
        "module": cand["module"],
        "product": product,
    })
    context.daily_open_count += 1
    context.last_action_min = now_min
    log.info("{} 新开{}：{} price={:.2f} score={:.2f} eff={:.5f}".format(code, side, cand["reason"], price, cand["score"], cand["efficiency"]))


def _open_from_old_chip(context, cand, now_min):
    code = cand["code"]
    side = cand["side"]
    price = cand["price"]
    if not _close_yday_chip_for_entry(context, code, side, price, cand["reason"]):
        return False
    context.open_positions.append({
        "code": code,
        "side": side,
        "entry_price": price,
        "entry_min": now_min,
        "entry_type": "old_chip",
        "stop_points": cand["stop_points"],
        "take_profit_points": cand["take_profit_points"],
        "module": cand["module"],
        "product": cand["product"],
    })
    context.daily_open_count += 1
    context.last_action_min = now_min
    log.info("{} 复用旧筹码形成{}敞口：{}".format(code, side, cand["reason"]))
    return True


def _enter_candidate(context, cand, now_min):
    code = cand["code"]
    if _open_from_old_chip(context, cand, now_min):
        return
    _open_new_position(context, cand, now_min)


def _position_hit_exit(pos, price):
    if pos["side"] == "long":
        pnl_points = price - pos["entry_price"]
    else:
        pnl_points = pos["entry_price"] - price
    if pnl_points <= -pos["stop_points"]:
        return True, "止损", pnl_points
    if pnl_points >= pos["take_profit_points"]:
        return True, "止盈", pnl_points
    return False, "", pnl_points


def _close_old_chip_exposure(context, pos, price, reason):
    code = pos["code"]
    side = pos["side"]
    book = context.ledger[code]
    if side == "long":
        _jq_order_close(context, code, "long", 1)
        book["long_yday"] = max(book["long_yday"] - 1, 0)
    else:
        _jq_order_close(context, code, "short", 1)
        book["short_yday"] = max(book["short_yday"] - 1, 0)
    product = pos["product"]
    points = price - pos["entry_price"] if side == "long" else pos["entry_price"] - price
    context.daily_realized_pnl += points * context.v69_multiplier[product]
    log.info("{} 旧筹码{}敞口直接平昨：{} pnl_points={:.2f}".format(code, side, reason, points))


def _lock_new_open_position(context, pos, price, reason):
    code = pos["code"]
    side = pos["side"]
    opposite = "short" if side == "long" else "long"
    inv = context.lock_inventory[code]
    if len(inv) >= context.max_lock_pairs_per_product:
        # 锁仓额度不足时只好平今；实盘可选择跳过或人工处理。
        _jq_order_close(context, code, side, 1)
        log.info("{} 锁仓额度不足，直接平今 {}".format(code, reason))
    else:
        _jq_order_open(code, opposite, 1)
        inv.append({"side": opposite, "price": price})
        book = context.ledger[code]
        if opposite == "long":
            book["long_today"] += 1
        else:
            book["short_today"] += 1
        log.info("{} 新开仓退出，用反向腿对锁：{}".format(code, reason))
    product = pos["product"]
    points = price - pos["entry_price"] if side == "long" else pos["entry_price"] - price
    context.daily_realized_pnl += points * context.v69_multiplier[product]


def _manage_positions(context, now_dt, hhmm):
    now_min = _minute_of_day(now_dt)
    remaining = []
    for pos in context.open_positions:
        price = _latest_price(context, pos["code"], now_dt)
        if price is None:
            remaining.append(pos)
            continue
        hit, reason, _ = _position_hit_exit(pos, price)
        if not hit and hhmm < context.force_lock_hhmm:
            remaining.append(pos)
            continue
        if not hit:
            reason = "尾盘处理"
        if pos["entry_type"] == "old_chip":
            _close_old_chip_exposure(context, pos, price, reason)
        else:
            _lock_new_open_position(context, pos, price, reason)
        context.last_action_min = now_min
    context.open_positions = remaining


def _build_candidates(context, now_dt, hhmm):
    out = []
    checked = 0
    enough_bars = 0
    for product, code in context.contracts.items():
        checked += 1
        df = _get_signal_frame(context, code, now_dt)
        if df is None:
            continue
        enough_bars += 1
        _update_opening_range(context, code, df, hhmm)
        cand = _classify_candidate(context, code, df)
        if cand is not None:
            out.append(cand)
    out.sort(key=lambda x: (x["score"], x["efficiency"]), reverse=True)
    if hhmm in (1000, 1100, 1400):
        diag_key = "{}-{}".format(now_dt.strftime("%Y-%m-%d"), hhmm)
        if getattr(context, "last_diag_hhmm", "") != diag_key:
            context.last_diag_hhmm = diag_key
            log.info(
                "V69诊断 {} 合约{}个 行情足够{}个 候选{}个 活动{}手 今日开仓{}次".format(
                    now_dt.strftime("%H:%M"),
                    checked,
                    enough_bars,
                    len(out),
                    len(context.open_positions),
                    context.daily_open_count,
                )
            )
            if len(out) > 0:
                top = out[0]
                log.info(
                    "V69候选第一名 {} {} {} price={:.2f} score={:.2f} eff={:.5f}".format(
                        top["code"], top["side"], top["reason"], top["price"], top["score"], top["efficiency"]
                    )
                )
    return out


def trade(context):
    now_dt = context.current_dt
    if getattr(context, "official_start", ""):
        if now_dt.strftime("%Y-%m-%d") < context.official_start:
            return
    hhmm = _hhmm(now_dt)
    now_min = _minute_of_day(now_dt)

    bar_key = "{}-{}".format(now_dt.strftime("%Y-%m-%d %H:%M"), context.v69_stage)
    if context.last_bar_key == bar_key:
        return
    context.last_bar_key = bar_key

    _manage_positions(context, now_dt, hhmm)
    if hhmm >= context.force_lock_hhmm:
        return
    if hhmm < context.first_open_hhmm or hhmm > context.last_open_hhmm:
        return
    if context.daily_open_count >= context.max_daily_open:
        return

    candidates = _build_candidates(context, now_dt, hhmm)
    for cand in candidates:
        if not _can_open_candidate(context, cand, now_min):
            continue
        sig = "{}-{}-{}".format(cand["code"], cand["side"], cand["module"])
        if context.last_route_signature.get(sig, -99999) + context.cross_product_cool_min > now_min:
            continue
        _enter_candidate(context, cand, now_min)
        context.last_route_signature[sig] = now_min
        break


def handle_data(context, data):
    trade(context)


def after_trading(context):
    log.info("V69收盘：当日开仓{}次｜活动敞口{}手｜已实现{:.2f}".format(
        context.daily_open_count,
        len(context.open_positions),
        context.daily_realized_pnl,
    ))
