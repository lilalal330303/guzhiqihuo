# -*- coding:utf-8 -*-
"""
JoinQuant version: Wufu ETF rotation sync/verification script.

Purpose:
- Keep parameters aligned with the local iteration-6 and SuperMind script.
- Use JoinQuant-native scheduled callbacks.
- Split signal and execution: 13:10 generate target, 13:11 place orders.
- Print WUFU_SIGNAL and WUFU_EXECUTE logs for cross-platform validation.
"""

import math
from datetime import timedelta

import numpy as np
import pandas as pd
from jqdata import *


GLOBAL_ETF_POOL = ['518880.XSHG', '501018.XSHG', '161226.XSHE', '159985.XSHE', '159980.XSHE', '513310.XSHG', '159518.XSHE', '159509.XSHE', '513100.XSHG', '513520.XSHG', '513500.XSHG', '159502.XSHE', '513400.XSHG', '513030.XSHG', '513290.XSHG', '520830.XSHG', '159529.XSHE']
CHINA_ETF_POOL = ['513090.XSHG', '513120.XSHG', '513180.XSHG', '513330.XSHG', '513750.XSHG', '159892.XSHE', '513190.XSHG', '159605.XSHE', '513630.XSHG', '159323.XSHE', '510900.XSHG', '513920.XSHG', '513970.XSHG', '511380.XSHG', '512050.XSHG', '510500.XSHG', '159915.XSHE', '510300.XSHG', '512100.XSHG', '159949.XSHE', '588080.XSHG', '159967.XSHE', '588220.XSHG', '563300.XSHG', '510760.XSHG', '588200.XSHG', '515880.XSHG', '159981.XSHE', '512880.XSHG', '513350.XSHG', '159326.XSHE', '159516.XSHE', '159206.XSHE', '512480.XSHG', '159363.XSHE', '159870.XSHE', '512400.XSHG', '159755.XSHE', '588170.XSHG', '159992.XSHE', '159995.XSHE', '512890.XSHG', '515220.XSHG', '159566.XSHE', '159819.XSHE', '512800.XSHG', '512690.XSHG', '515050.XSHG', '562500.XSHG', '512170.XSHG', '517520.XSHG', '159869.XSHE', '512070.XSHG', '159611.XSHE', '562800.XSHG', '515120.XSHG', '512010.XSHG', '510880.XSHG', '515790.XSHG', '515980.XSHG', '512660.XSHG', '159928.XSHE', '512710.XSHG', '560860.XSHG', '515030.XSHG', '159766.XSHE', '159218.XSHE', '159852.XSHE', '516160.XSHG', '516150.XSHG', '159227.XSHE', '159583.XSHE', '588790.XSHG', '159865.XSHE', '512980.XSHG', '159851.XSHE', '561360.XSHG', '561980.XSHG', '562590.XSHG', '512200.XSHG', '159732.XSHE', '159667.XSHE', '516510.XSHG', '159840.XSHE', '159998.XSHE', '159825.XSHE', '512670.XSHG', '159883.XSHE', '515210.XSHG', '515400.XSHG', '159256.XSHE', '561330.XSHG', '515170.XSHG', '159638.XSHE', '516520.XSHG', '513360.XSHG', '516190.XSHG']
DEBUG_DETAIL_TOP_N = 10
DEBUG_DETAIL_SAMPLE_N = 20
USE_DYNAMIC_POOL = False
USE_FULL_MARKET_THRESHOLD = False
DETAIL_LOG_ENABLED = False
WEAK_DETAIL_LOG_ENABLED = True
EXECUTION_CASH_BUFFER = 0.998
ROUND_LOT = 100
EXECUTION_COST_RESERVE_RATE = 0.0002
WEAK_CALENDAR_VERSION = "joinquant_v4_ranges_20200102_20260706_v9"
INTRADAY_TIMING_ENABLED = True
TREND_LOOKBACK_MINUTES = 30
TREND_SLOPE_THRESHOLD = 0.001
FORCE_BUY_TIME = "14:55"
FIXED_STOP_LOSS_ENABLED = True
FIXED_STOP_LOSS_THRESHOLD = 0.95
DIAGNOSTIC_DATES = set([
    "2020-07-17", "2020-12-14", "2021-04-20", "2021-05-26", "2021-05-27",
    "2021-05-28", "2021-05-31", "2021-06-03", "2021-07-01", "2021-07-02",
    "2021-07-21", "2021-08-31", "2021-09-10", "2021-11-30", "2021-12-01",
    "2021-12-09", "2021-12-10", "2022-03-29", "2024-11-25", "2025-07-22",
    "2025-09-04", "2025-09-09", "2025-11-14", "2026-07-02",
])
WEAK_DEBUG_DATES = set([
    "2020-02-11", "2020-03-31", "2020-04-01", "2020-04-02", "2020-04-29",
    "2020-04-30", "2020-05-19", "2020-07-23", "2020-08-18", "2020-08-19",
    "2021-02-09", "2021-02-24", "2021-05-07", "2021-06-04", "2021-06-08",
    "2021-06-09", "2021-06-10", "2021-06-15", "2021-06-16", "2021-06-24",
    "2021-07-19", "2021-07-20", "2021-07-26", "2021-08-03", "2021-08-04",
    "2021-08-16", "2021-08-25", "2021-08-27", "2021-08-30", "2021-09-01",
    "2021-09-02", "2021-09-03", "2021-09-07",
    "2026-06-29", "2026-06-30", "2026-07-01", "2026-07-02", "2026-07-03",
])

FUND_COMPANIES = ["国海富兰克林", "交银施罗德", "光大保德信", "兴证全球", "华泰柏瑞", "汇添富", "易方达", "华安", "广发", "招商", "华宝", "嘉实", "华夏", "国泰", "博时", "富国", "南方", "鹏华", "银华", "平安", "大成", "华商"]
NOISE_WORDS = ["指数ETF", "上市开放式", "LOF基金", "ETF基金", "LOF连接", "ETF连接", "连接基金", "指数基金", "指数A", "指数C", "基本面", "ETF", "LOF", "央企", "全指", "场外", "量化", "指基", "国企", "上海", "产业", "连接", "四川", "指数", "智能", "精选", "民营", "指增", "基金", "民企", "板块", "场内", "增强", "低波", "策略", "主题", "龙头"]
EXCLUDE_DYNAMIC_KEYWORDS = ["现金流", "A500", "MSCI", "基准国债", "公司债", "企业债", "政金债", "信用债", "利率债", "国开债", "城投债", "美元债", "可转债", "科创债", "沪深", "货币", "国债", "转债", "双债", "城投", "深成", "中证", "深证", "上证", "短融", "地债", "债"]
SPECIAL_GROUPS = [
    {"name": "香港组", "keywords": ["HS科技", "港股通", "恒生", "恒指", "港股", "H股", "香港", "HK", "中概", "港"], "remove_words": ["港股通", "恒生", "恒指", "港股", "H股", "香港", "HK", "中概", "港", "HS"]},
    {"name": "科创组", "keywords": ["科创创业", "科创板", "科创", "科综", "双创", "创创"], "remove_words": ["科创创业", "科创板", "科创", "科综", "双创", "创创", "债券", "债"]},
    {"name": "美指组", "keywords": ["纳斯达克", "标普", "纳指"], "remove_words": ["纳斯达克", "标普", "纳指"]},
    {"name": "创业组", "keywords": ["创业板", "创成长", "创业", "创板"], "remove_words": ["创业板", "创成长", "创业", "创板"]},
]


def initialize(context):
    set_option("avoid_future_data", True)
    set_option("use_real_price", True)
    set_slippage(PriceRelatedSlippage(0.0001), type="fund")
    set_order_cost(
        OrderCost(
            open_tax=0,
            close_tax=0,
            open_commission=0.0001,
            close_commission=0.0001,
            close_today_commission=0.0001,
            min_commission=5,
        ),
        type="fund",
    )
    set_benchmark("510300.XSHG")
    log.set_level("order", "error")
    log.set_level("system", "error")
    log.set_level("strategy", "info")

    g.global_etf_pool = GLOBAL_ETF_POOL[:]
    g.china_etf_pool = CHINA_ETF_POOL[:]
    g.fixed_etf_pool = g.global_etf_pool + g.china_etf_pool
    g.defensive_etf = "511880.XSHG"
    g.holdings_num = 1
    g.lookback_days = 25
    g.min_score_threshold = 0.0
    g.max_score_threshold = 5.0
    g.score_threshold_ratio = 0.9
    g.r2_threshold = 0.4
    g.ma_lookback = 10
    g.ma_threshold = 1.0
    g.volume_lookback = 5
    g.volume_threshold = 1.8
    g.loss = 0.97
    g.weak_period_ma_lookback = 10
    g.max_weak_days = 20
    g.dynamic_top_n = 100
    g.liquidity_lookback = 3
    g.liquidity_divisor = 20000.0
    g.liquidity_fallback = 10000000.0
    g.min_money = 10

    g.avg_etf_money_threshold = g.liquidity_fallback
    g.dynamic_etf_pool = []
    g.filtered_fixed_pool = []
    g.filtered_global_pool = []
    g.merged_etf_pool = g.fixed_etf_pool[:]
    g.is_a_share_weak = False
    g.weak_start_date = None
    g.target_etfs_list = []
    g.pending_buy_etfs = []
    g.last_signal_date = None
    g.last_execute_date = None
    g.last_force_buy_date = None
    g.last_position_log_date = None
    g.top10_log = ""

    run_daily(morning_routine, time="09:40")
    run_daily(signal_routine, time="13:10")
    run_daily(execute_routine, time="13:11")
    run_daily(check_pending_buys_trend, time="13:40")
    run_daily(check_pending_buys_trend, time="14:10")
    run_daily(check_pending_buys_trend, time="14:40")
    run_daily(force_buy_pending, time=FORCE_BUY_TIME)
    run_daily(minute_level_stop_loss, time="every_bar")
    run_daily(reset_daily_flags, time="15:10")
    log.info("WUFU_JQ_FIXED_POOL_V10_INTRADAY schedule morning=09:40 signal=13:10 execute=13:11 trend=13:40,14:10,14:40 force_buy={} reset=15:10 diagnostics={} execution_buffer={} round_lot={} weak_calendar_version={} weak_indexes=000300.XSHG,399101.XSHE,399006.XSHE,000510.XSHG".format(
        FORCE_BUY_TIME, len(DIAGNOSTIC_DATES), EXECUTION_CASH_BUFFER, ROUND_LOT, WEAK_CALENDAR_VERSION
    ))
    log.info("WUFU_INTRADAY_CONFIG enabled={} trend_lookback_minutes={} trend_slope_threshold={} stop_loss_enabled={} stop_loss_threshold={}".format(
        INTRADAY_TIMING_ENABLED, TREND_LOOKBACK_MINUTES, TREND_SLOPE_THRESHOLD, FIXED_STOP_LOSS_ENABLED, FIXED_STOP_LOSS_THRESHOLD
    ))


def morning_routine(context):
    calculate_global_etf_threshold(context)
    check_a_share_weak_period(context)
    if g.is_a_share_weak:
        filter_global_pool_by_volume(context)
        g.merged_etf_pool = g.filtered_global_pool[:] if g.filtered_global_pool else g.global_etf_pool[:]
    else:
        if USE_DYNAMIC_POOL:
            update_sector_pool(context)
        else:
            g.dynamic_etf_pool = []
        filter_fixed_pool_by_volume(context)
        g.merged_etf_pool = list(dict.fromkeys(g.filtered_fixed_pool + g.dynamic_etf_pool))
    log.info(
        "WUFU_MORNING now={} weak={} threshold={:.0f} pool={}".format(
            context.current_dt.strftime("%Y-%m-%d %H:%M:%S"),
            g.is_a_share_weak,
            g.avg_etf_money_threshold,
            len(g.merged_etf_pool),
        )
    )


def signal_routine(context):
    today = context.current_dt.date()
    if g.last_signal_date == today:
        return
    target = select_target(context)
    g.target_etfs_list = [target] if target else []
    g.last_signal_date = today
    log.info(
        "WUFU_SIGNAL source=run_daily now={} signal_date={} target={} top10={}".format(
            context.current_dt.strftime("%Y-%m-%d %H:%M:%S"),
            today,
            ",".join(g.target_etfs_list),
            g.top10_log,
        )
    )


def execute_routine(context):
    today = context.current_dt.date()
    if g.last_execute_date == today:
        return
    if g.last_signal_date != today:
        signal_routine(context)
    targets = set(g.target_etfs_list)
    g.pending_buy_etfs = []
    for security, position in list(context.portfolio.positions.items()):
        if position.total_amount > 0 and security not in targets:
            try:
                order_target_value(security, 0)
            except Exception as exc:
                log.info("WUFU_ORDER_FAIL action=sell code={} reason={}".format(security, exc))
    if g.target_etfs_list:
        current_positions = {
            security
            for security, position in context.portfolio.positions.items()
            if position.total_amount > 0
        }
        g.pending_buy_etfs = [code for code in g.target_etfs_list if code not in current_positions]
        if INTRADAY_TIMING_ENABLED:
            execute_pending_buy_with_trend(context, force=False)
            if g.pending_buy_etfs:
                log.info("WUFU_PENDING_BUY date={} pending={} next_checks=13:40,14:10,14:40 force_buy={}".format(
                    today, ",".join(g.pending_buy_etfs), FORCE_BUY_TIME
                ))
        else:
            execute_pending_buy_with_trend(context, force=True)
    g.last_execute_date = today
    log.info(
        "WUFU_EXECUTE source=run_daily now={} trade_date={} target={}".format(
            context.current_dt.strftime("%Y-%m-%d %H:%M:%S"),
            today,
            ",".join(g.target_etfs_list),
        )
    )


def check_intraday_trend(security, context):
    try:
        minute_data = get_price(
            security,
            end_date=context.current_dt,
            count=TREND_LOOKBACK_MINUTES,
            frequency="1m",
            fields=["close"],
            skip_paused=False,
            fq="pre",
        )
        if minute_data is None or minute_data.empty:
            log.info("WUFU_INTRADAY_TREND date={} code={} status=no_data action=pass".format(
                context.current_dt.strftime("%Y-%m-%d %H:%M:%S"), security
            ))
            return True
        closes = minute_data["close"].astype(float).values
        closes = closes[closes > 0]
        if len(closes) < 5:
            log.info("WUFU_INTRADAY_TREND date={} code={} status=insufficient rows={} action=wait".format(
                context.current_dt.strftime("%Y-%m-%d %H:%M:%S"), security, len(closes)
            ))
            return False
        x = np.arange(len(closes), dtype="float64")
        slope = np.polyfit(x, closes, 1)[0]
        mean_price = closes.mean()
        slope_pct = slope / mean_price * 100 if mean_price > 0 else 0.0
        passed = slope_pct > TREND_SLOPE_THRESHOLD
        log.info("WUFU_INTRADAY_TREND date={} code={} rows={} slope_pct={:.6f} threshold={:.6f} passed={}".format(
            context.current_dt.strftime("%Y-%m-%d %H:%M:%S"), security, len(closes), slope_pct, TREND_SLOPE_THRESHOLD, passed
        ))
        return passed
    except Exception as exc:
        log.info("WUFU_INTRADAY_TREND date={} code={} status=error reason={} action=pass".format(
            context.current_dt.strftime("%Y-%m-%d %H:%M:%S"), security, exc
        ))
        return True


def execute_pending_buy_with_trend(context, force=False):
    if not g.pending_buy_etfs:
        return
    current_positions = {
        security
        for security, position in context.portfolio.positions.items()
        if position.total_amount > 0
    }
    g.pending_buy_etfs = [code for code in g.pending_buy_etfs if code not in current_positions]
    if not g.pending_buy_etfs:
        return

    buy_now = []
    still_pending = []
    for code in g.pending_buy_etfs:
        if force or check_intraday_trend(code, context):
            buy_now.append(code)
        else:
            still_pending.append(code)

    total_count = len(buy_now) + len(still_pending)
    for i, code in enumerate(buy_now):
        remaining_to_buy = max(total_count - i, 1)
        target_value = context.portfolio.total_value * EXECUTION_CASH_BUFFER / remaining_to_buy
        plan = _rounded_lot_plan(code, target_value)
        log.info("WUFU_ORDER_PLAN date={} mode={} code={} account_value={:.2f} buffered_value={:.2f} price={:.4f} shares={} order_value={:.2f} estimated_cost={:.2f} residual_cash={:.2f} round_lot={}".format(
            context.current_dt.date(), "force" if force else "trend",
            code, context.portfolio.total_value, target_value, plan["price"], plan["shares"], plan["order_value"],
            plan["estimated_cost"], plan["residual_cash"], ROUND_LOT
        ))
        if plan["order_value"] > 0:
            try:
                order_target_value(code, plan["order_value"])
            except Exception as exc:
                log.info("WUFU_ORDER_FAIL action=buy code={} mode={} reason={}".format(code, "force" if force else "trend", exc))
        else:
            log.info("WUFU_ORDER_FAIL action=buy code={} mode={} reason=rounded_value_zero".format(code, "force" if force else "trend"))

    g.pending_buy_etfs = still_pending
    log.info("WUFU_PENDING_BUY date={} mode={} bought={} pending={}".format(
        context.current_dt.strftime("%Y-%m-%d %H:%M:%S"), "force" if force else "trend",
        ",".join(buy_now), ",".join(g.pending_buy_etfs)
    ))


def check_pending_buys_trend(context):
    if not INTRADAY_TIMING_ENABLED or not g.pending_buy_etfs:
        return
    execute_pending_buy_with_trend(context, force=False)


def force_buy_pending(context):
    today = context.current_dt.date()
    if g.last_force_buy_date == today or not g.pending_buy_etfs:
        return
    execute_pending_buy_with_trend(context, force=True)
    g.last_force_buy_date = today


def minute_level_stop_loss(context):
    if not FIXED_STOP_LOSS_ENABLED:
        return
    current_time = context.current_dt.strftime("%H:%M")
    if not (("09:40" < current_time < "10:29") or ("10:40" < current_time < "11:30") or ("13:00" < current_time < "14:57")):
        return
    current_data = get_current_data()
    for security, position in list(context.portfolio.positions.items()):
        if position.total_amount <= 0 or position.closeable_amount <= 0:
            continue
        price = float(current_data[security].last_price)
        cost = float(position.avg_cost)
        if price <= 0 or cost <= 0:
            continue
        if price <= cost * FIXED_STOP_LOSS_THRESHOLD:
            loss_pct = price / cost - 1.0
            log.info("WUFU_STOP_LOSS date={} code={} price={:.4f} cost={:.4f} loss_pct={:.4f} threshold={:.4f}".format(
                context.current_dt.strftime("%Y-%m-%d %H:%M:%S"), security, price, cost, loss_pct, FIXED_STOP_LOSS_THRESHOLD
            ))
            try:
                order_target_value(security, 0)
            except Exception as exc:
                log.info("WUFU_ORDER_FAIL action=stop_loss_sell code={} reason={}".format(security, exc))


def reset_daily_flags(context):
    g.top10_log = ""
    g.pending_buy_etfs = []
    _log_position(context)


def after_trading_end(context):
    _log_position(context)


def _log_position(context):
    today = context.current_dt.date()
    if getattr(g, "last_position_log_date", None) == today:
        return
    log.info("WUFU_POSITION date={} value={:.2f} positions={}".format(
        today, context.portfolio.total_value, _position_detail(context)
    ))
    g.last_position_log_date = today


def calculate_global_etf_threshold(context):
    try:
        if USE_FULL_MARKET_THRESHOLD:
            df_etf = get_all_securities(["etf"], date=context.current_dt)
            etf_list = df_etf.index.tolist()
        else:
            etf_list = g.fixed_etf_pool[:]
        if not etf_list:
            g.avg_etf_money_threshold = g.liquidity_fallback
            _detail_log("WUFU_THRESHOLD_DETAIL date={} universe=0 valid=0 totals= threshold={:.0f} source=fallback_empty_universe".format(context.current_dt.date(), g.avg_etf_money_threshold))
            return
        trade_days = get_trade_days(end_date=context.previous_date, count=g.liquidity_lookback)
        if len(trade_days) < g.liquidity_lookback:
            g.avg_etf_money_threshold = g.liquidity_fallback
            _detail_log("WUFU_THRESHOLD_DETAIL date={} universe={} valid=0 totals= threshold={:.0f} source=fallback_insufficient_history".format(context.current_dt.date(), len(etf_list), g.avg_etf_money_threshold))
            return
        df = get_price(
            security=etf_list,
            start_date=trade_days[0],
            end_date=context.previous_date,
            frequency="daily",
            fields=["money"],
            panel=False,
            skip_paused=True,
        )
        if df is None or df.empty:
            g.avg_etf_money_threshold = g.liquidity_fallback
            _detail_log("WUFU_THRESHOLD_DETAIL date={} universe={} valid=0 totals= threshold={:.0f} source=fallback_empty_price".format(context.current_dt.date(), len(etf_list), g.avg_etf_money_threshold))
            return
        daily_totals = df.groupby("time")["money"].sum()
        if len(daily_totals) < g.liquidity_lookback:
            g.avg_etf_money_threshold = g.liquidity_fallback
            source = "fallback_short_totals"
        else:
            g.avg_etf_money_threshold = float(daily_totals.mean() / g.liquidity_divisor)
            source = "joinquant_formula"
        _detail_log("WUFU_THRESHOLD_DETAIL date={} universe={} valid={} totals={} threshold={:.0f} source={}".format(
            context.current_dt.date(), len(etf_list), int(df["code"].nunique()) if "code" in df.columns else len(etf_list),
            _fmt_float_list(daily_totals.tail(g.liquidity_lookback).tolist()), g.avg_etf_money_threshold,
            source if USE_FULL_MARKET_THRESHOLD else "joinquant_fixed_pool_formula"
        ))
    except Exception as exc:
        log.warning("WUFU_THRESHOLD failed {}; fallback".format(exc))
        g.avg_etf_money_threshold = g.liquidity_fallback
        _detail_log("WUFU_THRESHOLD_DETAIL date={} universe=0 valid=0 totals= threshold={:.0f} source=fallback_exception".format(context.current_dt.date(), g.avg_etf_money_threshold))


def check_a_share_weak_period(context):
    indexes = ["000300.XSHG", "399101.XSHE", "399006.XSHE", "000510.XSHG"]
    below_count = 0
    above_count = 0
    valid_count = 0
    details = []
    for index in indexes:
        hist = get_price(index, end_date=context.previous_date, count=g.weak_period_ma_lookback, frequency="daily", fields=["close"])
        if hist is None or hist.empty or len(hist) < g.weak_period_ma_lookback:
            details.append("{}:NA".format(index))
            continue
        current_price = float(hist["close"].iloc[-1])
        ma_value = float(hist["close"].mean())
        last_date = _last_trade_date(hist)
        if current_price > ma_value:
            above_count += 1
            state = "above"
        elif current_price < ma_value:
            below_count += 1
            state = "below"
        else:
            state = "equal"
        valid_count += 1
        details.append("{}:{}:{:.4f}:{:.4f}:{}".format(index, last_date, current_price, ma_value, state))
    weak_condition_met = below_count >= 3
    exit_condition_met = above_count >= 3
    before = g.is_a_share_weak
    weak_days = len(get_trade_days(start_date=g.weak_start_date, end_date=context.current_dt.date())) if g.is_a_share_weak and g.weak_start_date else 0
    if g.is_a_share_weak:
        if exit_condition_met or weak_days >= g.max_weak_days:
            g.is_a_share_weak = False
            g.weak_start_date = None
        elif weak_condition_met:
            g.weak_start_date = context.current_dt.date()
    elif weak_condition_met:
        g.is_a_share_weak = True
        g.weak_start_date = context.current_dt.date()
    log.info("WUFU_WEAK_SOURCE date={} mode=auto weak={} valid={} min_valid=4 version={} source=index".format(
        context.current_dt.date(), g.is_a_share_weak, valid_count, WEAK_CALENDAR_VERSION
    ))
    _weak_detail_log("WUFU_WEAK_DETAIL date={} before={} after={} below={} above={} weak_start={} weak_days={} detail={}".format(
        context.current_dt.date(), before, g.is_a_share_weak, below_count, above_count, g.weak_start_date, weak_days, "|".join(details)
    ))


def filter_global_pool_by_volume(context):
    g.filtered_global_pool = filter_pool_by_amount(g.global_etf_pool, context)


def filter_fixed_pool_by_volume(context):
    g.filtered_fixed_pool = filter_pool_by_amount(g.fixed_etf_pool, context)


def filter_pool_by_amount(pool, context):
    try:
        price_data = get_price(pool, end_date=context.previous_date, count=g.liquidity_lookback, frequency="daily", fields=["money"], panel=False)
        if price_data is None or price_data.empty:
            return pool[:]
        avg_money = price_data.groupby("code")["money"].sum() / g.liquidity_lookback
        qualified = avg_money[avg_money > g.avg_etf_money_threshold].index.tolist()
        rejected = avg_money[avg_money <= g.avg_etf_money_threshold].sort_values(ascending=False)
        rejected_sample = ["{}:{:.0f}".format(code, value) for code, value in rejected.head(DEBUG_DETAIL_SAMPLE_N).items()]
        _detail_log("WUFU_POOL_FILTER date={} input={} output={} threshold={:.0f} selected={} rejected_sample={}".format(
            context.current_dt.date(), len(pool), len(qualified), g.avg_etf_money_threshold,
            ",".join(qualified), "|".join(rejected_sample)
        ))
        return qualified if qualified else pool[:]
    except Exception:
        return pool[:]


def update_sector_pool(context):
    try:
        df_etf = get_all_securities(["etf"], date=context.current_dt)
        if df_etf is None or df_etf.empty:
            g.dynamic_etf_pool = []
            return
        rows = []
        etf_list = df_etf.index.tolist()
        price_data = get_price(etf_list, end_date=context.previous_date, count=g.liquidity_lookback, frequency="daily", fields=["money"], panel=False)
        if price_data is None or price_data.empty:
            g.dynamic_etf_pool = []
            return
        avg_money = price_data.groupby("code")["money"].sum() / g.liquidity_lookback
        for code, sec in df_etf.iterrows():
            name = getattr(sec, "display_name", "") or str(sec.get("display_name", code))
            key = dynamic_industry_key(name)
            if not key:
                continue
            money = float(avg_money.get(code, 0))
            if money > g.avg_etf_money_threshold:
                rows.append({"code": code, "industry_key": key, "avg_money": money})
        if not rows:
            g.dynamic_etf_pool = []
            return
        frame = pd.DataFrame(rows).sort_values("avg_money", ascending=False)
        frame = frame.drop_duplicates("industry_key", keep="first").sort_values("avg_money", ascending=False)
        g.dynamic_etf_pool = frame["code"].head(g.dynamic_top_n).tolist()
        sample = ["{}:{}:{:.0f}".format(row.code, row.industry_key, row.avg_money) for row in frame.head(DEBUG_DETAIL_SAMPLE_N).itertuples(index=False)]
        _detail_log("WUFU_POOL_DETAIL date={} dynamic_candidates={} dynamic_groups={} dynamic_pool={}".format(
            context.current_dt.date(), len(rows), len(frame), "|".join(sample)
        ))
    except Exception as exc:
        log.warning("WUFU_DYNAMIC_POOL failed {}".format(exc))
        g.dynamic_etf_pool = []


def dynamic_industry_key(name):
    raw = str(name)
    if any(word in raw for word in EXCLUDE_DYNAMIC_KEYWORDS):
        return ""
    group = None
    for item in SPECIAL_GROUPS:
        if any(keyword in raw for keyword in item["keywords"]):
            group = item
            break
    cleaned = raw
    for word in FUND_COMPANIES:
        cleaned = cleaned.replace(word, "")
    if group:
        for word in group["remove_words"]:
            cleaned = cleaned.replace(word, "")
    for word in NOISE_WORDS:
        cleaned = cleaned.replace(word, "")
    cleaned = cleaned.strip()
    key = cleaned[:2] if len(cleaned) >= 2 else cleaned
    if not key:
        return ""
    return group["name"] + "_" + key if group else key


def select_target(context):
    pool = g.merged_etf_pool if g.merged_etf_pool else (g.global_etf_pool if g.is_a_share_weak else g.fixed_etf_pool)
    rows = []
    for code in pool:
        item = score_symbol(code, context)
        if item:
            rows.append(item)
    rows.sort(key=lambda item: item["score"], reverse=True)
    g.top10_log = ",".join(["{}:{:.4f}".format(item["code"], item["score"]) for item in rows[:10]])
    g.score_detail_log = "|".join([
        "{}:{:.4f}:{:.4f}:{:.4f}:{:.4f}:{:.0f}".format(
            item["code"], item["score"], item["annualized"], item["r2"], item.get("price", np.nan), item.get("today_volume", np.nan)
        )
        for item in rows[:DEBUG_DETAIL_TOP_N]
    ])
    if not rows:
        _detail_log("WUFU_SCORE_DETAIL date={} weak={} pool={} passed=0 target={} top10=".format(context.current_dt.date(), g.is_a_share_weak, len(pool), g.defensive_etf))
        return g.defensive_etf
    reference_score = rows[g.holdings_num - 1]["score"] if len(rows) >= g.holdings_num else rows[0]["score"]
    ratio = 1.0 if g.is_a_share_weak else g.score_threshold_ratio
    candidates = [item for item in rows[:10] if item["score"] >= reference_score * ratio]
    target = candidates[0]["code"] if candidates else g.defensive_etf
    _detail_log("WUFU_SCORE_DETAIL date={} weak={} pool={} passed={} target={} top10={}".format(
        context.current_dt.date(), g.is_a_share_weak, len(pool), len(rows), target, g.score_detail_log
    ))
    return target


def score_symbol(code, context):
    try:
        hist = get_price(code, end_date=context.previous_date, count=g.lookback_days, frequency="daily", fields=["close", "volume"])
        if hist is None or hist.empty or len(hist) < g.lookback_days:
            return None
        current_data = get_current_data()
        current_price = float(current_data[code].last_price)
        if current_data[code].paused or current_price <= 0:
            return None
        closes = np.append(hist["close"].astype(float).values[-g.lookback_days:], current_price)
        volumes = hist["volume"].astype(float).values[-g.volume_lookback:]
        score, annualized, r2 = momentum_score(closes)
        if not np.isfinite(score) or not (g.min_score_threshold <= score <= g.max_score_threshold):
            return None
        if (not g.is_a_share_weak) and r2 <= g.r2_threshold:
            return None
        if g.is_a_share_weak and current_price <= np.mean(closes[-g.ma_lookback:]) * g.ma_threshold:
            return None
        if len(volumes) < g.volume_lookback or np.any(volumes <= 0):
            return None
        today_volume = float(getattr(current_data[code], "volume", 0) or 0)
        if today_volume > 0 and today_volume / float(np.mean(volumes)) >= g.volume_threshold:
            return None
        if len(closes) >= 4 and np.min(closes[-3:] / closes[-4:-1]) < g.loss:
            return None
        return {"code": code, "score": score, "annualized": annualized, "r2": r2, "price": current_price, "today_volume": today_volume}
    except Exception:
        return None


def _last_trade_date(df):
    try:
        if "time" in df.columns:
            return pd.Timestamp(df["time"].iloc[-1]).strftime("%Y-%m-%d")
        return pd.Timestamp(df.index[-1]).strftime("%Y-%m-%d")
    except Exception:
        return "NA"


def _fmt_float_list(values):
    return ",".join(["{:.0f}".format(float(value)) for value in values if np.isfinite(value)])


def _rounded_lot_plan(code, value):
    try:
        current_data = get_current_data()
        price = float(current_data[code].last_price)
        if current_data[code].paused or price <= 0:
            return {"price": 0.0, "shares": 0, "order_value": 0.0, "estimated_cost": 0.0, "residual_cash": float(value)}
        budget = max(0.0, float(value) - 5.0)
        shares = int(budget / (price * (1.0 + EXECUTION_COST_RESERVE_RATE)) / ROUND_LOT) * ROUND_LOT
        order_value = max(0.0, shares * price)
        estimated_cost = 0.0 if shares <= 0 else max(order_value * 0.0001, 5.0) + order_value * 0.0001
        residual_cash = max(0.0, float(value) - order_value - estimated_cost)
        return {"price": float(price), "shares": int(shares), "order_value": order_value, "estimated_cost": estimated_cost, "residual_cash": residual_cash}
    except Exception:
        return {"price": 0.0, "shares": 0, "order_value": 0.0, "estimated_cost": 0.0, "residual_cash": 0.0}


def _rounded_lot_value(code, value):
    return _rounded_lot_plan(code, value)["order_value"]


def _position_detail(context):
    rows = []
    try:
        for code, position in context.portfolio.positions.items():
            amount = float(getattr(position, "total_amount", 0) or 0)
            if amount <= 0:
                continue
            value = float(getattr(position, "value", 0) or getattr(position, "market_value", 0) or 0)
            rows.append("{}:{:.0f}:{:.2f}".format(code, amount, value))
    except Exception:
        pass
    return "|".join(rows)


def _detail_log(message):
    date_match = None
    try:
        import re
        date_match = re.search(r"date=(\d{4}-\d{2}-\d{2})", message)
    except Exception:
        date_match = None
    today = date_match.group(1) if date_match else ""
    if DETAIL_LOG_ENABLED or today in DIAGNOSTIC_DATES:
        log.info(message)


def _weak_detail_log(message):
    should_log = DETAIL_LOG_ENABLED
    if not should_log and WEAK_DETAIL_LOG_ENABLED:
        for date_text in WEAK_DEBUG_DATES:
            if "date={}".format(date_text) in message:
                should_log = True
                break
    if should_log:
        log.info(message)


def momentum_score(prices):
    prices = np.asarray(prices, dtype=float)
    if len(prices) < g.lookback_days + 1 or np.any(prices <= 0):
        return np.nan, np.nan, np.nan
    y = np.log(prices[-(g.lookback_days + 1):])
    x = np.arange(len(y), dtype=float)
    w = np.linspace(1.0, 2.0, len(y))
    rw = w ** 2
    x_bar = np.sum(rw * x) / np.sum(rw)
    y_bar = np.sum(rw * y) / np.sum(rw)
    slope = np.sum(rw * (x - x_bar) * (y - y_bar)) / np.sum(rw * (x - x_bar) ** 2)
    intercept = y_bar - slope * x_bar
    annualized = math.exp(slope * 250.0) - 1.0
    fit = slope * x + intercept
    ss_res = np.sum(w * (y - fit) ** 2)
    ss_tot = np.sum(w * (y - np.mean(y)) ** 2)
    r2 = 1.0 - ss_res / ss_tot if ss_tot else 0.0
    return float(annualized * r2), float(annualized), float(r2)
