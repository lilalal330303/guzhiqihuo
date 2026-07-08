# -*- coding:utf-8 -*-
"""
同花顺/SuperMind版：聚宽五福 ETF 轮动同步版

对齐本地第 6 轮参数：
- 回测标的：聚宽固定 ETF 池 + 每日动态行业 ETF 池 Top100；弱市切换到海外/商品/货币等全局池。
- 弱市状态：000300、399101、399006、000510，10 日均线，3 个指数跌破进入，3 个指数站上退出，最多 20 个交易日，信号滞后 1 天。
- 流动性阈值：全市场 ETF 前 3 个交易日成交额合计均值 / 20000，历史不足时 1000 万。
- 评分：25 日加权对数动量，年化收益 * R2；正常市场启用 R2>0.4，弱市改用 10 日均线过滤。
- 风控：5 日成交量突增过滤 <1.8，连续大跌过滤，分数 0~5，Top1 满仓轮动。
- 成本：ETF 佣金 0.01%，滑点 0.01%，最低佣金 5 元。若平台成本 API 不支持最低佣金，请在回测设置中手动配置。

建议使用分钟级回测。若 run_daily(time) 不可用，handle_bar 会在 09:40、13:10、15:10
附近自动触发一次。
"""

import math
import numpy as np
import pandas as pd


INIT_CASH = 1000000
HOLDINGS_NUM = 1
LOOKBACK_DAYS = 25
MIN_SCORE = 0.0
MAX_SCORE = 5.0
SCORE_THRESHOLD_RATIO = 0.9
R2_THRESHOLD = 0.4
MA_LOOKBACK = 10
MA_THRESHOLD = 1.0
VOLUME_LOOKBACK = 5
VOLUME_THRESHOLD = 1.8
LOSS_THRESHOLD = 0.97
WEAK_MA_LOOKBACK = 10
MAX_WEAK_DAYS = 20
LIQUIDITY_LOOKBACK = 3
LIQUIDITY_DIVISOR = 20000.0
LIQUIDITY_FALLBACK = 10000000.0
DYNAMIC_TOP_N = 100
COMMISSION_RATE = 0.0001
SLIPPAGE_RATE = 0.0001
MIN_COMMISSION = 5.0
WEAK_HHMM = 940
POOL_HHMM = 940
SIGNAL_HHMM = 1310
EXECUTE_HHMM = 1311
TRADE_HHMM = SIGNAL_HHMM
RESET_HHMM = 1510
DEFENSIVE_ETF = "511880.SH"
DEBUG_DETAIL_TOP_N = 10
DEBUG_DETAIL_SAMPLE_N = 20
DETAIL_LOG_ENABLED = False
FAST_BATCH_PRICE_ENABLED = True
USE_DYNAMIC_POOL = False
USE_FULL_MARKET_THRESHOLD = False
FAST_SCORE_HISTORY_CACHE = True
CACHE_LOG_ENABLED = False
WEAK_DETAIL_LOG_ENABLED = True
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

WEAK_INDEXES = ["000300.SH", "399101.SZ", "399006.SZ", "000510.SH"]

GLOBAL_ETF_POOL = ['518880.SH', '501018.SH', '161226.SZ', '159985.SZ', '159980.SZ', '513310.SH', '159518.SZ', '159509.SZ', '513100.SH', '513520.SH', '513500.SH', '159502.SZ', '513400.SH', '513030.SH', '513290.SH', '520830.SH', '159529.SZ']
CHINA_ETF_POOL = ['513090.SH', '513120.SH', '513180.SH', '513330.SH', '513750.SH', '159892.SZ', '513190.SH', '159605.SZ', '513630.SH', '159323.SZ', '510900.SH', '513920.SH', '513970.SH', '511380.SH', '512050.SH', '510500.SH', '159915.SZ', '510300.SH', '512100.SH', '159949.SZ', '588080.SH', '159967.SZ', '588220.SH', '563300.SH', '510760.SH', '588200.SH', '515880.SH', '159981.SZ', '512880.SH', '513350.SH', '159326.SZ', '159516.SZ', '159206.SZ', '512480.SH', '159363.SZ', '159870.SZ', '512400.SH', '159755.SZ', '588170.SH', '159992.SZ', '159995.SZ', '512890.SH', '515220.SH', '159566.SZ', '159819.SZ', '512800.SH', '512690.SH', '515050.SH', '562500.SH', '512170.SH', '517520.SH', '159869.SZ', '512070.SH', '159611.SZ', '562800.SH', '515120.SH', '512010.SH', '510880.SH', '515790.SH', '515980.SH', '512660.SH', '159928.SZ', '512710.SH', '560860.SH', '515030.SH', '159766.SZ', '159218.SZ', '159852.SZ', '516160.SZ', '516150.SZ', '159227.SZ', '159583.SZ', '588790.SH', '159865.SZ', '512980.SH', '159851.SZ', '561360.SH', '561980.SH', '562590.SH', '512200.SH', '159732.SZ', '159667.SZ', '516510.SH', '159840.SZ', '159998.SZ', '159825.SZ', '512670.SH', '159883.SZ', '515210.SH', '515400.SH', '159256.SZ', '561330.SH', '515170.SH', '159638.SZ', '516520.SH', '513360.SH', '516190.SH']
FIXED_ETF_POOL = GLOBAL_ETF_POOL + CHINA_ETF_POOL

FUND_COMPANIES = ["国海富兰克林", "交银施罗德", "光大保德信", "兴证全球", "华泰柏瑞", "汇添富", "易方达", "华安", "广发", "招商", "华宝", "嘉实", "华夏", "国泰", "博时", "富国", "南方", "鹏华", "银华", "平安", "大成", "华商"]
NOISE_WORDS = ["指数ETF", "上市开放式", "LOF基金", "ETF基金", "LOF连接", "ETF连接", "连接基金", "指数基金", "指数A", "指数C", "基本面", "ETF", "LOF", "央企", "全指", "场外", "量化", "指基", "国企", "上海", "产业", "连接", "四川", "指数", "智能", "精选", "民营", "指增", "基金", "民企", "板块", "场内", "增强", "低波", "策略", "主题", "龙头"]
EXCLUDE_DYNAMIC_KEYWORDS = ["现金流", "A500", "MSCI", "基准国债", "公司债", "企业债", "政金债", "信用债", "利率债", "国开债", "城投债", "美元债", "可转债", "科创债", "沪深", "货币", "国债", "转债", "双债", "城投", "深成", "中证", "深证", "上证", "短融", "地债", "债"]
SPECIAL_GROUPS = [
    {"name": "香港组", "keywords": ["HS科技", "港股通", "恒生", "恒指", "港股", "H股", "香港", "HK", "中概", "港"], "remove_words": ["港股通", "恒生", "恒指", "港股", "H股", "香港", "HK", "中概", "港", "HS"]},
    {"name": "科创组", "keywords": ["科创创业", "科创板", "科创", "科综", "双创", "创创"], "remove_words": ["科创创业", "科创板", "科创", "科综", "双创", "创创", "债券", "债"]},
    {"name": "美指组", "keywords": ["纳斯达克", "标普", "纳指"], "remove_words": ["纳斯达克", "标普", "纳指"]},
    {"name": "创业组", "keywords": ["创业板", "创成长", "创业", "创板"], "remove_words": ["创业板", "创成长", "创业", "创板"]},
]


def init(context):
    try:
        set_subportfolios([{"cash": INIT_CASH, "type": "stock"}])
    except Exception:
        pass
    try:
        set_commission(PerShare(type="stock", cost=COMMISSION_RATE))
        set_slippage(PriceSlippage(SLIPPAGE_RATE), "stock")
    except Exception:
        pass
    context.wufu_target = []
    context.wufu_pool = FIXED_ETF_POOL[:]
    context.wufu_dynamic_pool = []
    context.wufu_liquidity_threshold = LIQUIDITY_FALLBACK
    context.wufu_is_weak = False
    context.wufu_weak_start = ""
    context.wufu_last_weak_date = ""
    context.wufu_pool_date = ""
    context.wufu_signal_date = ""
    context.wufu_trade_date = ""
    context.wufu_execute_date = ""
    context.wufu_reset_date = ""
    context.wufu_top10 = ""
    context.wufu_code_map = {}
    context.wufu_etf_metadata_cache_date = ""
    context.wufu_etf_metadata_cache = []
    context.wufu_amount_cache_date = ""
    context.wufu_amount_cache = {}
    context.wufu_score_cache_date = ""
    context.wufu_score_history_cache = {}
    _subscribe_all(context)
    _register_schedule()
    log.info("聚宽五福ETF同步版 init: weak=09:40 pool=09:40 trade=13:10 reset=15:10")


def handle_bar(context, bar_dict):
    now = get_datetime()
    hhmm = int(now.strftime("%H%M"))
    today = now.strftime("%Y-%m-%d")
    if hhmm >= WEAK_HHMM and getattr(context, "wufu_last_weak_date", "") != today:
        morning_callback(context, bar_dict)
    if hhmm >= SIGNAL_HHMM and getattr(context, "wufu_signal_date", "") != today:
        signal_callback(context, bar_dict, source="handle_bar")
    if hhmm >= EXECUTE_HHMM and getattr(context, "wufu_execute_date", "") != today:
        execute_callback(context, bar_dict, source="handle_bar")
    if hhmm >= RESET_HHMM and getattr(context, "wufu_reset_date", "") != today:
        reset_callback(context, bar_dict)


def handle_data(context, data):
    handle_bar(context, data)


def before_trading(context):
    pass


def after_trading(context):
    log.info("五福ETF close value={:.2f} weak={} pool={} target={} top10={}".format(
        _account_value(context), getattr(context, "wufu_is_weak", False),
        len(getattr(context, "wufu_pool", [])), ",".join(getattr(context, "wufu_target", [])),
        getattr(context, "wufu_top10", "")
    ))


def morning_callback(context, data=None):
    today = get_datetime().strftime("%Y-%m-%d")
    if getattr(context, "wufu_last_weak_date", "") == today:
        return
    context.wufu_liquidity_threshold = calculate_global_etf_threshold(context)
    context.wufu_is_weak = check_weak_state(context)
    context.wufu_dynamic_pool = [] if context.wufu_is_weak or not USE_DYNAMIC_POOL else build_dynamic_pool(context)
    context.wufu_pool = filter_pool_by_amount(GLOBAL_ETF_POOL if context.wufu_is_weak else list(dict.fromkeys(FIXED_ETF_POOL + context.wufu_dynamic_pool)), context)
    context.wufu_last_weak_date = today
    context.wufu_pool_date = today
    log.info("五福ETF morning date={} weak={} threshold={:.0f} pool={}".format(today, context.wufu_is_weak, context.wufu_liquidity_threshold, len(context.wufu_pool)))


def trade_callback(context, data=None):
    signal_callback(context, data, source="legacy_trade_callback")
    execute_callback(context, data, source="legacy_trade_callback")


def signal_callback(context, data=None, source="run_daily"):
    today = get_datetime().strftime("%Y-%m-%d")
    now = get_datetime()
    if getattr(context, "wufu_signal_date", "") == today:
        return
    if getattr(context, "wufu_pool_date", "") != today:
        morning_callback(context, data)
    target = select_target(context, data)
    context.wufu_target = [target] if target else []
    context.wufu_signal_date = today
    log.info("WUFU_SIGNAL source={} now={} signal_date={} target={} top10={}".format(
        source, now.strftime("%Y-%m-%d %H:%M:%S"), today, ",".join(context.wufu_target), getattr(context, "wufu_top10", "")
    ))


def execute_callback(context, data=None, source="run_daily"):
    today = get_datetime().strftime("%Y-%m-%d")
    now = get_datetime()
    if getattr(context, "wufu_execute_date", "") == today:
        return
    if getattr(context, "wufu_signal_date", "") != today:
        signal_callback(context, data, source=source + "_auto_signal")
    target_resolved = [_resolve(context, code) for code in context.wufu_target]
    for code in _positions(context):
        if code not in target_resolved and code not in context.wufu_target:
            try:
                order_target_value(code, 0)
            except Exception:
                pass
    if context.wufu_target:
        _order_target_value(context, context.wufu_target[0], _account_value(context))
    context.wufu_execute_date = today
    context.wufu_trade_date = today
    log.info("WUFU_EXECUTE source={} now={} trade_date={} target={}".format(
        source, now.strftime("%Y-%m-%d %H:%M:%S"), today, ",".join(context.wufu_target)
    ))


def reset_callback(context, data=None):
    context.wufu_reset_date = get_datetime().strftime("%Y-%m-%d")


def _register_schedule():
    fn = globals().get("run_daily", None)
    if fn is None:
        log.info("WUFU_SCHEDULE run_daily unavailable; use handle_bar time gate only")
        return
    for func, tm in ((morning_callback, "09:40"), (signal_callback, "13:10"), (execute_callback, "13:11"), (reset_callback, "15:10")):
        try:
            fn(func, tm)
            log.info("WUFU_SCHEDULE registered {} at {}".format(getattr(func, "__name__", str(func)), tm))
        except Exception:
            log.info("WUFU_SCHEDULE failed {} at {}; use handle_bar fallback only".format(getattr(func, "__name__", str(func)), tm))


def calculate_global_etf_threshold(context):
    codes = get_all_etf_codes(context) if USE_FULL_MARKET_THRESHOLD else FIXED_ETF_POOL
    amount_cache = _ensure_daily_amount_cache(context, codes)
    daily_totals = []
    valid_codes = 0
    amount_codes = 0
    fallback_codes = 0
    for code in codes:
        money = amount_cache.get(code, [])
        if len(money) < LIQUIDITY_LOOKBACK:
            continue
        valid_codes += 1
        amount_codes += 1
        for i, value in enumerate(money[-LIQUIDITY_LOOKBACK:]):
            if len(daily_totals) <= i:
                daily_totals.append(0.0)
            if np.isfinite(value):
                daily_totals[i] += float(value)
    if len(daily_totals) < LIQUIDITY_LOOKBACK:
        _detail_log("WUFU_THRESHOLD_DETAIL date={} universe={} valid={} amount_codes={} fallback_codes={} totals={} threshold={:.0f} source=fallback".format(
            get_datetime().strftime("%Y-%m-%d"), len(codes), valid_codes, amount_codes, fallback_codes, _fmt_float_list(daily_totals), LIQUIDITY_FALLBACK
        ))
        return LIQUIDITY_FALLBACK
    threshold = float(np.mean(daily_totals[-LIQUIDITY_LOOKBACK:]) / LIQUIDITY_DIVISOR)
    _detail_log("WUFU_THRESHOLD_DETAIL date={} universe={} valid={} amount_codes={} fallback_codes={} totals={} threshold={:.0f} source={}".format(
        get_datetime().strftime("%Y-%m-%d"), len(codes), valid_codes, amount_codes, fallback_codes, _fmt_float_list(daily_totals[-LIQUIDITY_LOOKBACK:]), threshold,
        "ths_full_market_formula" if USE_FULL_MARKET_THRESHOLD else "ths_fixed_pool_formula"
    ))
    return threshold


def check_weak_state(context):
    today = get_datetime().strftime("%Y-%m-%d")
    below = 0
    above = 0
    details = []
    for code in WEAK_INDEXES:
        df = _previous_daily_rows(_get_price_1d(context, code, WEAK_MA_LOOKBACK + 2), today)
        if len(df) < WEAK_MA_LOOKBACK:
            details.append("{}:NA".format(code))
            continue
        closes = df["close"].astype(float).values
        current = closes[-1]
        ma = np.mean(closes[-WEAK_MA_LOOKBACK:])
        last_date = _last_trade_date(df)
        if current > ma:
            above += 1
            state = "above"
        elif current < ma:
            below += 1
            state = "below"
        else:
            state = "equal"
        details.append("{}:{}:{:.4f}:{:.4f}:{}".format(code, last_date, current, ma, state))
    is_weak = getattr(context, "wufu_is_weak", False)
    weak_start = getattr(context, "wufu_weak_start", "")
    weak_days = _days_between(weak_start, today) if is_weak and weak_start else 0
    before = is_weak
    if is_weak:
        if above >= 3 or weak_days >= MAX_WEAK_DAYS:
            context.wufu_weak_start = ""
            result = False
        elif below >= 3:
            context.wufu_weak_start = today
            result = True
        else:
            result = True
    elif below >= 3:
        context.wufu_weak_start = today
        result = True
    else:
        result = False
    _weak_detail_log("WUFU_WEAK_DETAIL date={} before={} after={} below={} above={} weak_start={} weak_days={} detail={}".format(
        today, before, result, below, above, getattr(context, "wufu_weak_start", ""), weak_days, "|".join(details)
    ))
    return result


def build_dynamic_pool(context):
    rows = []
    metadata = get_all_etf_metadata(context)
    amount_cache = _ensure_daily_amount_cache(context, [code for code, name in metadata])
    for code, name in metadata:
        key = dynamic_industry_key(name)
        if not key:
            continue
        money = amount_cache.get(code, [])
        if len(money) < LIQUIDITY_LOOKBACK:
            continue
        avg_amount = float(np.mean(money[-LIQUIDITY_LOOKBACK:]))
        if np.isfinite(avg_amount) and avg_amount > context.wufu_liquidity_threshold:
            rows.append({"code": code, "key": key, "amount": avg_amount})
    if not rows:
        _detail_log("WUFU_POOL_DETAIL date={} dynamic_candidates=0 dynamic_pool=".format(get_datetime().strftime("%Y-%m-%d")))
        return []
    frame = pd.DataFrame(rows).sort_values("amount", ascending=False)
    frame = frame.drop_duplicates("key", keep="first").sort_values("amount", ascending=False)
    pool = frame["code"].head(DYNAMIC_TOP_N).tolist()
    sample = ["{}:{}:{:.0f}".format(row.code, row.key, row.amount) for row in frame.head(DEBUG_DETAIL_SAMPLE_N).itertuples(index=False)]
    _detail_log("WUFU_POOL_DETAIL date={} dynamic_candidates={} dynamic_groups={} dynamic_pool={}".format(
        get_datetime().strftime("%Y-%m-%d"), len(rows), len(frame), "|".join(sample)
    ))
    for code in pool:
        try:
            subscribe(_resolve(context, code))
        except Exception:
            pass
    return pool


def dynamic_industry_key(name):
    raw = str(name)
    if any(word in raw for word in EXCLUDE_DYNAMIC_KEYWORDS):
        return ""
    group = None
    for item in SPECIAL_GROUPS:
        if any(k in raw for k in item["keywords"]):
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


def filter_pool_by_amount(pool, context):
    out = []
    amount_cache = _ensure_daily_amount_cache(context, pool)
    for code in pool:
        money = amount_cache.get(code, [])
        if len(money) < LIQUIDITY_LOOKBACK:
            continue
        avg_amount = float(np.mean(money[-LIQUIDITY_LOOKBACK:]))
        if np.isfinite(avg_amount) and avg_amount > context.wufu_liquidity_threshold:
            out.append(code)
    return out if out else pool


def select_target(context, data=None):
    rows = []
    is_weak = getattr(context, "wufu_is_weak", False)
    pool = getattr(context, "wufu_pool", [])
    _ensure_score_history_cache(context, pool)
    current_data = _current_data_snapshot()
    for code in pool:
        try:
            item = score_symbol(context, code, is_weak, data, current_data)
            if item:
                rows.append(item)
        except Exception:
            pass
    rows = sorted(rows, key=lambda x: x["score"], reverse=True)
    context.wufu_top10 = ",".join(["{}:{:.4f}".format(r["code"], r["score"]) for r in rows[:10]])
    context.wufu_score_detail = "|".join([
        "{}:{:.4f}:{:.4f}:{:.4f}:{:.4f}:{:.0f}".format(
            r["code"], r["score"], r["annualized"], r["r2"], r.get("price", np.nan), r.get("today_volume", np.nan)
        )
        for r in rows[:DEBUG_DETAIL_TOP_N]
    ])
    if not rows:
        _detail_log("WUFU_SCORE_DETAIL date={} pool={} passed=0 top10=".format(get_datetime().strftime("%Y-%m-%d"), len(getattr(context, "wufu_pool", []))))
        return DEFENSIVE_ETF
    ref = rows[HOLDINGS_NUM - 1]["score"] if len(rows) >= HOLDINGS_NUM else rows[0]["score"]
    ratio = 1.0 if is_weak else SCORE_THRESHOLD_RATIO
    candidates = [r for r in rows[:10] if r["score"] >= ref * ratio]
    target = candidates[0]["code"] if candidates else DEFENSIVE_ETF
    _detail_log("WUFU_SCORE_DETAIL date={} weak={} pool={} passed={} target={} top10={}".format(
        get_datetime().strftime("%Y-%m-%d"), is_weak, len(getattr(context, "wufu_pool", [])), len(rows), target, getattr(context, "wufu_score_detail", "")
    ))
    return target


def score_symbol(context, code, is_weak, data=None, current_data=None):
    df = _score_history(context, code)
    if len(df) < LOOKBACK_DAYS:
        return None
    p, today_volume = _current_price_volume(context, code, data, current_data)
    if not np.isfinite(p) or p <= 0:
        return None
    closes = np.append(df["close"].astype(float).values[-LOOKBACK_DAYS:], p)
    score, annualized, r2 = momentum_score(closes)
    if not np.isfinite(score) or score < MIN_SCORE or score > MAX_SCORE:
        return None
    if (not is_weak) and r2 <= R2_THRESHOLD:
        return None
    if is_weak and p <= float(pd.Series(closes).tail(MA_LOOKBACK).mean()) * MA_THRESHOLD:
        return None
    if not pass_volume_filter(df, p, today_volume):
        return None
    if not pass_loss_filter(closes):
        return None
    return {"code": code, "score": score, "annualized": annualized, "r2": r2, "price": p, "today_volume": today_volume}


def momentum_score(prices):
    prices = np.asarray(prices, dtype=float)
    if len(prices) < LOOKBACK_DAYS + 1 or np.any(prices <= 0):
        return np.nan, np.nan, np.nan
    y = np.log(prices[-(LOOKBACK_DAYS + 1):])
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


def pass_volume_filter(df, current_price, current_volume=None):
    if len(df) < VOLUME_LOOKBACK:
        return False
    volumes = df["volume"].astype(float).values
    trailing = volumes[-VOLUME_LOOKBACK:]
    if np.any(trailing <= 0):
        return False
    if current_volume is None or not np.isfinite(current_volume) or current_volume <= 0:
        current_volume = volumes[-1]
    return current_volume / np.mean(trailing) < VOLUME_THRESHOLD


def pass_loss_filter(closes):
    if len(closes) < 4:
        return True
    ratios = closes[-3:] / closes[-4:-1]
    return bool(np.min(ratios) >= LOSS_THRESHOLD)


def get_all_etf_metadata(context):
    today = get_datetime().strftime("%Y-%m-%d")
    if getattr(context, "wufu_etf_metadata_cache_date", "") == today:
        cached = getattr(context, "wufu_etf_metadata_cache", [])
        if cached:
            return cached
    try:
        df = get_all_securities(["etf"], date=get_datetime())
        if df is not None and len(df) > 0:
            rows = []
            for idx, row in df.iterrows():
                code = _to_ths_code(str(idx))
                name = str(row["display_name"] if "display_name" in df.columns else row.get("name", code))
                rows.append((code, name))
            context.wufu_etf_metadata_cache_date = today
            context.wufu_etf_metadata_cache = rows
            return rows
    except Exception:
        pass
    rows = [(code, code) for code in FIXED_ETF_POOL]
    context.wufu_etf_metadata_cache_date = today
    context.wufu_etf_metadata_cache = rows
    return rows


def get_all_etf_codes(context):
    return [code for code, name in get_all_etf_metadata(context)]


def _money_series(df):
    if "amount" in df.columns:
        amount = pd.to_numeric(df["amount"], errors="coerce")
        if amount.notna().sum() > 0 and float(amount.fillna(0).sum()) > 0:
            return amount
    return pd.to_numeric(df["close"], errors="coerce") * pd.to_numeric(df["volume"], errors="coerce")


def _ensure_daily_amount_cache(context, codes):
    today = get_datetime().strftime("%Y-%m-%d")
    unique_codes = list(dict.fromkeys([code for code in codes if code]))
    if getattr(context, "wufu_amount_cache_date", "") != today:
        context.wufu_amount_cache_date = today
        context.wufu_amount_cache = {}
    cache = getattr(context, "wufu_amount_cache", {})
    missing = [code for code in unique_codes if code not in cache]
    if missing:
        fetched = _fetch_amount_histories(context, missing, LIQUIDITY_LOOKBACK + 2)
        cache.update(fetched)
        for code in missing:
            cache.setdefault(code, [])
        context.wufu_amount_cache = cache
        _cache_log("WUFU_FAST_CACHE date={} requested={} fetched={} total_cached={}".format(
            today, len(missing), sum(1 for code in missing if cache.get(code)), len(cache)
        ))
    return cache


def _ensure_score_history_cache(context, codes):
    today = get_datetime().strftime("%Y-%m-%d")
    unique_codes = list(dict.fromkeys([code for code in codes if code]))
    if getattr(context, "wufu_score_cache_date", "") != today:
        context.wufu_score_cache_date = today
        context.wufu_score_history_cache = {}
    cache = getattr(context, "wufu_score_history_cache", {})
    missing = [code for code in unique_codes if code not in cache]
    if missing:
        frames = _get_price_1d_many(context, missing, LOOKBACK_DAYS + 2, fields=["close", "volume"])
        for code in missing:
            rows = _previous_daily_rows(frames.get(code, pd.DataFrame()), today)
            cache[code] = rows.tail(LOOKBACK_DAYS).copy() if len(rows) else pd.DataFrame()
        context.wufu_score_history_cache = cache
        _cache_log("WUFU_SCORE_CACHE date={} requested={} fetched={} total_cached={}".format(
            today, len(missing), sum(1 for code in missing if len(cache.get(code, pd.DataFrame())) >= LOOKBACK_DAYS), len(cache)
        ))
    return cache


def _score_history(context, code):
    if FAST_SCORE_HISTORY_CACHE:
        cache = getattr(context, "wufu_score_history_cache", {})
        if code in cache:
            return cache.get(code, pd.DataFrame())
    return _previous_daily_rows(_get_price_1d(context, code, LOOKBACK_DAYS + 2), get_datetime().strftime("%Y-%m-%d"))


def _fetch_amount_histories(context, codes, count):
    frames = _get_price_1d_many(context, codes, count, fields=["open", "high", "low", "close", "volume", "amount"])
    output = {}
    today = get_datetime().strftime("%Y-%m-%d")
    for code, df in frames.items():
        rows = _previous_daily_rows(df, today)
        if len(rows) < LIQUIDITY_LOOKBACK:
            output[code] = []
            continue
        money = _money_series(rows).tail(LIQUIDITY_LOOKBACK).astype(float)
        output[code] = [float(value) for value in money.values if np.isfinite(value)]
    return output


def _get_price_1d_many(context, codes, count, fields=None):
    fields = fields or ["open", "high", "low", "close", "volume", "amount"]
    if FAST_BATCH_PRICE_ENABLED:
        try:
            df = get_price(codes, None, get_datetime(), "1d", fields, bar_count=count)
            frames = _split_price_frame(codes, df)
            if frames:
                return frames
        except Exception:
            pass
        try:
            fallback_fields = [field for field in fields if field != "amount"]
            df = get_price(codes, None, get_datetime(), "1d", fallback_fields, bar_count=count)
            frames = _split_price_frame(codes, df)
            if frames:
                return frames
        except Exception:
            pass
    frames = {}
    for code in codes:
        frames[code] = _get_price_1d_raw(code, get_datetime(), count)
    return frames


def _split_price_frame(codes, df):
    if df is None:
        return {}
    if isinstance(df, dict):
        return {code: value for code, value in df.items() if value is not None}
    if not isinstance(df, pd.DataFrame) or df.empty:
        return {}
    code_set = set(codes)
    for col in ("code", "security", "symbol"):
        if col in df.columns:
            frames = {}
            for code, rows in df.groupby(col):
                normalized = _to_ths_code(str(code))
                if normalized in code_set:
                    frames[normalized] = rows.drop(columns=[col], errors="ignore")
            return frames
    if isinstance(df.index, pd.MultiIndex):
        for level in range(df.index.nlevels):
            values = set([_to_ths_code(str(value)) for value in df.index.get_level_values(level)])
            if values.intersection(code_set):
                frames = {}
                for raw_code, rows in df.groupby(level=level):
                    normalized = _to_ths_code(str(raw_code))
                    if normalized in code_set:
                        frames[normalized] = rows.reset_index(level=level, drop=True)
                return frames
    if len(codes) == 1:
        return {codes[0]: df}
    return {}


def _current_data_snapshot():
    try:
        return get_current_data()
    except Exception:
        return None


def _subscribe_all(context):
    codes = list(dict.fromkeys(FIXED_ETF_POOL + GLOBAL_ETF_POOL + WEAK_INDEXES + [DEFENSIVE_ETF]))
    resolved = []
    for code in codes:
        for c in _code_candidates(code):
            if c not in resolved:
                resolved.append(c)
    try:
        set_universe(resolved)
    except Exception:
        pass
    for code in resolved:
        try:
            subscribe(code)
        except Exception:
            pass


def _detail_log(message):
    if DETAIL_LOG_ENABLED:
        log.info(message)


def _cache_log(message):
    if CACHE_LOG_ENABLED:
        log.info(message)


def _weak_detail_log(message):
    today = get_datetime().strftime("%Y-%m-%d")
    if DETAIL_LOG_ENABLED or (WEAK_DETAIL_LOG_ENABLED and today in WEAK_DEBUG_DATES):
        log.info(message)


def _to_ths_code(code):
    base = code.split(".")[0]
    if code.endswith(".XSHG") or code.endswith(".SH"):
        return base + ".SH"
    if code.endswith(".XSHE") or code.endswith(".SZ"):
        return base + ".SZ"
    return base + (".SH" if base.startswith(("5", "6", "9")) else ".SZ")


def _code_candidates(code):
    base, ex = code.split(".")
    return [code, base + (".XSHG" if ex == "SH" else ".XSHE"), base]


def _resolve(context, code):
    mp = getattr(context, "wufu_code_map", {})
    if code in mp:
        return mp[code]
    for c in _code_candidates(code):
        df = _get_price_1d_raw(c, get_datetime(), 2)
        if df is not None and len(df) > 0:
            mp[code] = c
            context.wufu_code_map = mp
            return c
    return code


def _get_price_1d_raw(code, end_dt, count):
    try:
        df = get_price(code, None, end_dt, "1d", ["open", "high", "low", "close", "volume", "amount"], bar_count=count)
        if df is None:
            return pd.DataFrame()
        return df.dropna(subset=["close"])
    except Exception:
        try:
            df = get_price(code, None, end_dt, "1d", ["open", "high", "low", "close", "volume"], bar_count=count)
            if df is None:
                return pd.DataFrame()
            return df.dropna(subset=["close"])
        except Exception:
            return pd.DataFrame()


def _get_price_1d(context, code, count):
    return _get_price_1d_raw(_resolve(context, code), get_datetime(), count)


def _current_price(context, code, data=None):
    c = _resolve(context, code)
    try:
        if data is not None and c in data:
            bar = data[c]
            for attr in ("close", "price", "last_price"):
                if hasattr(bar, attr):
                    p = float(getattr(bar, attr))
                    if np.isfinite(p) and p > 0:
                        return p
    except Exception:
        pass
    try:
        df = get_price(c, None, get_datetime(), "1m", ["close"], bar_count=1)
        if df is not None and len(df) > 0:
            return float(df["close"].iloc[-1])
    except Exception:
        pass
    df = _get_price_1d(context, code, 1)
    return float(df["close"].iloc[-1]) if len(df) else np.nan


def _current_price_volume(context, code, data=None, current_data=None):
    c = _resolve(context, code)
    price = np.nan
    volume = np.nan
    try:
        if data is not None and c in data:
            bar = data[c]
            for attr in ("close", "price", "last_price"):
                if hasattr(bar, attr):
                    value = float(getattr(bar, attr))
                    if np.isfinite(value) and value > 0:
                        price = value
                        break
            for attr in ("volume", "vol"):
                if hasattr(bar, attr):
                    value = float(getattr(bar, attr))
                    if np.isfinite(value) and value > 0:
                        volume = value
                        break
            if np.isfinite(price) and price > 0:
                return price, volume
    except Exception:
        pass
    try:
        if current_data is not None:
            item = current_data[c]
            price = float(getattr(item, "last_price", np.nan))
            volume = float(getattr(item, "volume", 0) or 0)
            paused = bool(getattr(item, "paused", False))
            if (not paused) and np.isfinite(price) and price > 0:
                return price, volume
    except Exception:
        pass
    try:
        df = get_price(c, None, get_datetime(), "1m", ["close", "volume"], bar_count=1)
        if df is not None and len(df) > 0:
            price = float(df["close"].iloc[-1]) if "close" in df.columns else price
            volume = float(df["volume"].iloc[-1]) if "volume" in df.columns else volume
            if np.isfinite(price) and price > 0:
                return price, volume
    except Exception:
        pass
    df = _get_price_1d(context, code, 1)
    if len(df):
        price = float(df["close"].iloc[-1])
    return price, volume


def _current_volume(context, code, data=None):
    c = _resolve(context, code)
    try:
        if data is not None and c in data:
            bar = data[c]
            for attr in ("volume", "vol"):
                if hasattr(bar, attr):
                    value = float(getattr(bar, attr))
                    if np.isfinite(value) and value > 0:
                        return value
    except Exception:
        pass
    try:
        df = get_price(c, None, get_datetime(), "1m", ["volume"], bar_count=1)
        if df is not None and len(df) > 0:
            value = float(df["volume"].iloc[-1])
            if np.isfinite(value) and value > 0:
                return value
    except Exception:
        pass
    return np.nan


def _previous_daily_rows(df, today):
    if df is None or len(df) == 0:
        return pd.DataFrame()
    rows = df.copy()
    row_dates = _daily_dates(rows)
    if row_dates is not None:
        rows = rows[row_dates < pd.Timestamp(today)]
    return rows.dropna(subset=["close"])


def _daily_dates(df):
    try:
        if "time" in df.columns:
            return pd.to_datetime(df["time"]).dt.normalize()
        if "date" in df.columns:
            return pd.to_datetime(df["date"]).dt.normalize()
        if "trade_date" in df.columns:
            return pd.to_datetime(df["trade_date"]).dt.normalize()
        return pd.to_datetime(df.index).normalize()
    except Exception:
        return None


def _last_trade_date(df):
    dates = _daily_dates(df)
    if dates is None or len(dates) == 0:
        return "NA"
    try:
        return pd.Timestamp(list(dates)[-1]).strftime("%Y-%m-%d")
    except Exception:
        return "NA"


def _fmt_float_list(values):
    return ",".join(["{:.0f}".format(float(value)) for value in values if np.isfinite(value)])


def _positions(context):
    try:
        return list(context.portfolio.positions.keys())
    except Exception:
        return []


def _account_value(context):
    try:
        return float(context.portfolio.total_value)
    except Exception:
        return INIT_CASH


def _order_target_value(context, code, value):
    try:
        order_target_value(_resolve(context, code), value)
    except Exception as exc:
        log.info("五福ETF order failed {} {}".format(code, exc))


def _days_between(start, end):
    try:
        return int((pd.Timestamp(end) - pd.Timestamp(start)).days) + 1
    except Exception:
        return 0
