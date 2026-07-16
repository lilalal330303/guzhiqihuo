# -*- coding: utf-8 -*-
"""SuperMind/同花顺 Python 3.8 版本：near_n1_q20 小市值策略。

本文件不依赖 jqdata/jqfactor，也不读取本地回放目标。
平台接口优先使用同花顺常见的 init/handle_bar/get_price/order_target_value。
如果平台没有财务因子接口，脚本会明确记录 QUALITY_FALLBACK，并退化为市值临界排序。
"""

import math

import numpy as np
import pandas as pd


STRATEGY_NAME = "near_n1_q20"
SCRIPT_VERSION = "ths_v4_pretrade_signal"
INDEX_CODE = "399101.SZ"
DEFENSIVE_ETF = "511880.SH"
STOCK_COUNT = 5
SHORTLIST_EXTRA = 1
EXPOSURE = 1.0
QUALITY_WEIGHT = 0.20
SIZE_WEIGHT = 0.80
ROUND_LOT = 100
STOP_LOSS_RATIO = 0.89
MARKET_STOP_RATIO = 0.95
COMMISSION_RATE = 0.00085 / 100.0
SLIPPAGE_RATE = 0.0002
MIN_COMMISSION = 5.0


def _api(name):
    """读取平台注入的全局函数；本地导入脚本时不会因缺少平台 API 而失败。"""
    return globals().get(name)


def _log(level, message):
    logger = globals().get("log")
    fn = getattr(logger, level, None) if logger is not None else None
    if callable(fn):
        try:
            fn(message)
            return
        except Exception:
            pass
    print(message)


def _now(context=None):
    fn = _api("get_datetime")
    if callable(fn):
        try:
            return pd.Timestamp(fn()).to_pydatetime()
        except Exception:
            pass
    for attr in ("current_dt", "current_time"):
        value = getattr(context, attr, None) if context is not None else None
        if value is not None:
            return pd.Timestamp(value).to_pydatetime()
    return pd.Timestamp.utcnow().to_pydatetime()


def _today(context=None):
    return _now(context).strftime("%Y-%m-%d")


def _hhmm(context=None):
    return int(_now(context).strftime("%H%M"))


def _to_ths_code(code):
    text = str(code or "").strip().upper()
    if not text:
        return text
    text = text.replace(".XSHG", ".SH").replace(".XSHE", ".SZ")
    if "." in text:
        return text
    if text.startswith(("5", "6", "68", "9")):
        return text + ".SH"
    return text + ".SZ"


def _code_candidates(code):
    resolved = _to_ths_code(code)
    raw = resolved.split(".")[0]
    suffix = resolved.split(".")[1] if "." in resolved else ""
    values = [resolved, raw]
    if suffix == "SH":
        values.extend([raw + ".XSHG"])
    elif suffix == "SZ":
        values.extend([raw + ".XSHE"])
    return list(dict.fromkeys(values))


def _call_get_price(codes, count, fields, context=None, frequency="1d"):
    fn = _api("get_price")
    now = _now(context)
    values = list(codes) if isinstance(codes, (list, tuple, set, pd.Index)) else codes
    def usable(frame):
        if frame is None:
            return False
        if isinstance(frame, (pd.DataFrame, dict)):
            return not frame.empty if isinstance(frame, pd.DataFrame) else bool(frame)
        return True

    if callable(fn):
        # SuperMind 的多标的 get_price(is_panel=False) 返回 {code: DataFrame}，
        # 不能先强制 pd.DataFrame(frame)，否则会丢失证券维度。
        attempts = [
            lambda: fn(values, None, now, frequency, fields, False, "pre", count, False),
            lambda: fn(values, end_date=now, bar_count=count, fre_step=frequency, fields=fields, skip_paused=False, fq="pre", is_panel=False),
            lambda: fn(values, end_date=now, count=count, frequency=frequency, fields=fields, panel=False, skip_paused=True),
            lambda: fn(values, end_date=now, count=count, frequency=frequency, fields=fields),
        ]
        for attempt in attempts:
            try:
                frame = attempt()
                if usable(frame):
                    return frame
            except Exception:
                continue

    # 部分 SuperMind 回测环境对 history 的支持比 get_price 更稳定，作为同口径兜底。
    history_fn = _api("history")
    if callable(history_fn):
        attempts = [
            lambda: history_fn(values, fields, count, frequency, False, "pre", 0),
            lambda: history_fn(values, fields, count, frequency, skip_paused=False, fq="pre", is_panel=0),
        ]
        for attempt in attempts:
            try:
                frame = attempt()
                if usable(frame):
                    return frame
            except Exception:
                continue
    return pd.DataFrame()


def _date_series(frame):
    if frame is None or frame.empty:
        return pd.Series(dtype="datetime64[ns]")
    if "time" in frame.columns:
        return pd.to_datetime(frame["time"], errors="coerce")
    if "datetime" in frame.columns:
        return pd.to_datetime(frame["datetime"], errors="coerce")
    if "date" in frame.columns:
        return pd.to_datetime(frame["date"], errors="coerce")
    return pd.to_datetime(frame.index, errors="coerce")


def _split_price_frame(codes, frame):
    """适配 SuperMind 批量 get_price 的 code 列、MultiIndex 和 dict 三种返回形态。"""
    if frame is None:
        return {}
    if isinstance(frame, dict):
        return {_to_ths_code(code): value for code, value in frame.items() if value is not None}
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return {}
    code_set = set([_to_ths_code(code) for code in codes])
    for column in ("code", "security", "symbol"):
        if column in frame.columns:
            output = {}
            for raw_code, rows in frame.groupby(column):
                normalized = _to_ths_code(raw_code)
                if normalized in code_set:
                    output[normalized] = rows.drop(columns=[column], errors="ignore")
            if output:
                return output
    if isinstance(frame.index, pd.MultiIndex):
        for level in range(frame.index.nlevels):
            values = set([_to_ths_code(value) for value in frame.index.get_level_values(level)])
            if values.intersection(code_set):
                output = {}
                for raw_code, rows in frame.groupby(level=level):
                    normalized = _to_ths_code(raw_code)
                    if normalized in code_set:
                        output[normalized] = rows.reset_index(level=level, drop=True)
                if output:
                    return output
    if len(codes) == 1:
        return {_to_ths_code(codes[0]): frame}
    return {}


def _previous_close_map(codes, context=None):
    """批量提取 T-1 收盘，失败时返回空映射而不是读取当日未来价格。"""
    frame = _call_get_price(codes, 3, ["close"], context=context, frequency="1d")
    today = pd.Timestamp(_today(context))
    out = {}
    frames = _split_price_frame(codes, frame)
    for code, group in frames.items():
        if not isinstance(group, pd.DataFrame) or "close" not in group.columns:
            continue
        work = group.copy()
        work["_date"] = _date_series(work)
        work = work.loc[work["_date"].lt(today)].copy()
        values = pd.to_numeric(work["close"], errors="coerce").dropna()
        if not values.empty:
            out[_to_ths_code(code)] = float(values.iloc[-1])
    return out


def _current_data():
    fn = _api("get_current_data")
    if not callable(fn):
        return {}
    try:
        return fn() or {}
    except Exception:
        return {}


def _current_item(data, code):
    if data is None:
        return None
    for candidate in _code_candidates(code):
        try:
            if candidate in data:
                return data[candidate]
        except Exception:
            continue
    return None


def _value(item, *names, default=None):
    for name in names:
        try:
            value = getattr(item, name)
        except Exception:
            try:
                value = item[name]
            except Exception:
                continue
        if value is not None:
            return value
    return default


def _is_bad_security(code, item):
    raw = _to_ths_code(code).split(".")[0]
    if raw.startswith(("30", "68", "8", "4")):
        return True
    if item is None:
        return False
    if bool(_value(item, "paused", default=False)) or bool(_value(item, "is_st", default=False)):
        return True
    name = str(_value(item, "name", "display_name", default="") or "").upper()
    return "ST" in name or "退" in name or "PT" in name


def _listing_date_map(context):
    fn = _api("get_all_securities")
    if not callable(fn):
        return {}
    try:
        frame = fn(["stock"], date=_now(context))
    except Exception:
        try:
            frame = fn(["stock"])
        except Exception:
            return {}
    if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
        return {}
    out = {}
    for code, row in frame.iterrows():
        value = row.get("start_date") if hasattr(row, "get") else None
        if value is not None:
            out[_to_ths_code(code)] = pd.Timestamp(value)
    return out


def _index_components(context):
    fn = _api("get_index_stocks")
    if callable(fn):
        for candidate in [INDEX_CODE, "399101", "399101.XSHE"]:
            try:
                rows = fn(candidate)
                if rows:
                    return [_to_ths_code(code) for code in rows]
            except Exception:
                continue
    fn = _api("get_all_securities")
    if callable(fn):
        try:
            frame = fn(["stock"], date=_now(context))
        except Exception:
            frame = pd.DataFrame()
        if isinstance(frame, pd.DataFrame):
            return [_to_ths_code(code) for code in frame.index.tolist()]
    return []


def _try_factor_frame(context, codes):
    """尝试读取同花顺环境的因子/财务表；接口差异由多组调用方式吸收。"""
    factor_fn = _api("get_factor_values")
    if callable(factor_fn):
        for kwargs in (
            {"security": codes, "factors": ["market_cap", "roe", "roa", "operating_revenue", "net_profit"], "date": _now(context)},
            {"securities": codes, "factors": ["market_cap", "roe", "roa", "operating_revenue", "net_profit"], "date": _now(context)},
        ):
            try:
                raw = factor_fn(**kwargs)
                if isinstance(raw, pd.DataFrame) and not raw.empty:
                    return raw.reset_index() if raw.index.name else raw.copy()
            except Exception:
                continue
    gf = _api("get_fundamentals")
    query_fn = _api("query")
    valuation = _api("valuation")
    income = _api("income")
    indicator = _api("indicator")
    if callable(gf) and callable(query_fn) and valuation is not None:
        try:
            fields = [valuation.code, valuation.market_cap]
            for obj, name in ((income, "operating_revenue"), (income, "net_profit"), (indicator, "roe"), (indicator, "roa")):
                if obj is not None and hasattr(obj, name):
                    fields.append(getattr(obj, name))
            query_obj = query_fn(*fields).filter(valuation.code.in_(codes))
            raw = gf(query_obj)
            if isinstance(raw, pd.DataFrame) and not raw.empty:
                return raw.copy()
        except Exception:
            pass
    return pd.DataFrame()


def _pct_rank(values, higher_is_better=True):
    series = pd.to_numeric(pd.Series(values), errors="coerce")
    if series.notna().sum() == 0:
        return pd.Series(0.5, index=series.index)
    return series.rank(pct=True, ascending=higher_is_better, method="average").fillna(0.5)


def quality_rank_score(values):
    """将质量值转为 0~1 排名；空输入返回中性 0.5。"""
    if not values:
        return 0.5
    frame = pd.Series(values, dtype="float64")
    ranked = frame.rank(pct=True, method="average").fillna(0.5)
    return {str(code): float(score) for code, score in ranked.items()}


def _quality_from_frame(frame, codes):
    if frame is None or frame.empty:
        return {}
    work = frame.copy()
    if "code" not in work.columns:
        for col in ("security", "symbol"):
            if col in work.columns:
                work = work.rename(columns={col: "code"})
                break
    if "code" not in work.columns:
        return {}
    required = {"market_cap", "operating_revenue", "net_profit", "roe", "roa"}
    if not required.issubset(set(work.columns)):
        return {}
    work["code"] = work["code"].map(_to_ths_code)
    work = work.drop_duplicates("code", keep="last").set_index("code").reindex(codes)
    cap = pd.to_numeric(work.get("market_cap"), errors="coerce")
    revenue = pd.to_numeric(work.get("operating_revenue"), errors="coerce")
    profit = pd.to_numeric(work.get("net_profit"), errors="coerce")
    roe = pd.to_numeric(work.get("roe"), errors="coerce")
    roa = pd.to_numeric(work.get("roa"), errors="coerce")
    cap = cap.replace(0, np.nan)
    revenue = revenue.replace(0, np.nan)
    values = pd.DataFrame(index=codes)
    values["value"] = _pct_rank(np.log(revenue / cap), True)
    values["profit"] = 0.5 * _pct_rank(roe, True) + 0.5 * _pct_rank(roa, True)
    values["quality"] = 0.45 * values["value"] + 0.55 * values["profit"]
    return values["quality"].fillna(0.5).to_dict()


def quality_scores(context, codes):
    frame = _try_factor_frame(context, codes)
    scores = _quality_from_frame(frame, codes)
    if not scores:
        context.ths_quality_fallback = True
        _log("info", "QUALITY_FALLBACK date={} reason=no_ths_factor_or_finance_api codes={}".format(_today(context), len(codes)))
        return {code: 0.5 for code in codes}
    context.ths_quality_fallback = False
    return {code: float(scores.get(code, 0.5)) for code in codes}


def select_from_ranked(ranked, quality, n=STOCK_COUNT):
    ranked = list(dict.fromkeys([_to_ths_code(code) for code in ranked]))
    shortlist = ranked[: max(int(n), 0) + SHORTLIST_EXTRA]
    if not shortlist:
        return []
    quality_values = {code: float(quality.get(code, 0.5)) for code in shortlist} if isinstance(quality, dict) else {}
    qrank = quality_rank_score(quality_values)
    if not isinstance(qrank, dict):
        qrank = {code: 0.5 for code in shortlist}
    rows = []
    for index, code in enumerate(shortlist):
        size_score = 1.0 - (float(index) / max(len(shortlist) - 1, 1))
        score = SIZE_WEIGHT * size_score + QUALITY_WEIGHT * float(qrank.get(code, 0.5))
        rows.append((score, -index, code))
    rows.sort(reverse=True)
    return [row[2] for row in rows[: int(n)]]


def build_stock_pool(context):
    codes = _index_components(context)
    if not codes:
        context.ths_ranked = []
        _log("info", "POOL_EMPTY date={} reason=no_index_components".format(_today(context)))
        return []
    current = _current_data()
    starts = _listing_date_map(context)
    today = pd.Timestamp(_today(context))
    eligible = []
    for code in codes:
        item = _current_item(current, code)
        if _is_bad_security(code, item):
            continue
        if code in starts and (today - starts[code]).days < 375:
            continue
        eligible.append(code)
    closes = _previous_close_map(eligible, context)
    eligible_before_close = len(eligible)
    eligible = [code for code in eligible if code in closes and closes[code] > 0]
    if not eligible:
        context.ths_ranked = []
        _log("info", "POOL_EMPTY date={} reason=no_previous_close components={} eligible_before_close={} eligible_after_close={} close_map={}".format(_today(context), len(codes), eligible_before_close, len(eligible), len(closes)))
        return []
    _log("info", "POOL_STAGE date={} components={} eligible={} close_map={}".format(_today(context), len(codes), len(eligible), len(closes)))
    frame = _try_factor_frame(context, eligible)
    if frame is not None and not frame.empty and "market_cap" in frame.columns and "code" in frame.columns:
        work = frame.copy()
        work["code"] = work["code"].map(_to_ths_code)
        work["market_cap"] = pd.to_numeric(work["market_cap"], errors="coerce")
        work = work.loc[work["code"].isin(eligible)].dropna(subset=["market_cap"])
        ranked = work.sort_values(["market_cap", "code"], ascending=[True, True])["code"].tolist()
        ranked.extend([code for code in sorted(eligible) if code not in ranked])
        context.ths_cap_fallback = False
    else:
        ranked = sorted(eligible, key=lambda code: (closes.get(code, math.inf), code))
        context.ths_cap_fallback = True
        _log("info", "CAP_FALLBACK date={} reason=no_market_cap_factor codes={}".format(_today(context), len(eligible)))
    context.ths_ranked = ranked
    return ranked


def select_near_n1_q20(context):
    ranked = build_stock_pool(context)
    if not ranked:
        context.ths_last_signal = [DEFENSIVE_ETF]
        _log("info", "NEAR_SIGNAL date={} variant={} target={} reason=empty_pool".format(_today(context), STRATEGY_NAME, DEFENSIVE_ETF))
        return [DEFENSIVE_ETF]
    shortlist = ranked[: STOCK_COUNT + SHORTLIST_EXTRA]
    quality = quality_scores(context, shortlist)
    selected = select_from_ranked(ranked, quality, STOCK_COUNT)
    context.ths_last_quality = quality
    context.ths_last_signal = selected
    _log(
        "info",
        "NEAR_SIGNAL date={} variant={} ranked_top={} shortlist={} selected={} quality_fallback={} cap_fallback={}".format(
            _today(context), STRATEGY_NAME, ",".join(ranked[:10]), ",".join(shortlist), ",".join(selected),
            bool(getattr(context, "ths_quality_fallback", True)), bool(getattr(context, "ths_cap_fallback", True)),
        ),
    )
    return selected


def sellable_amount(position):
    total = int(max(float(_value(position, "total_amount", "amount", default=0) or 0), 0))
    closeable = _value(position, "closeable_amount", default=None)
    if closeable is None:
        return total
    return int(max(min(float(closeable), total), 0))


def round_lot_value(price, budget, lot=ROUND_LOT):
    price = float(price or 0)
    budget = float(budget or 0)
    if price <= 0 or budget <= 0 or lot <= 0:
        return 0.0
    shares = int(budget / price / lot) * lot
    return float(shares * price)


def _position_price(code, context, bar_dict=None):
    if bar_dict is not None:
        for candidate in _code_candidates(code):
            try:
                item = bar_dict[candidate]
                value = _value(item, "close", "price", "last", default=None)
                if value is not None and float(value) > 0:
                    return float(value)
            except Exception:
                continue
    item = _current_item(_current_data(), code)
    value = _value(item, "last", "last_price", "close", default=None)
    if value is not None:
        try:
            if float(value) > 0:
                return float(value)
        except Exception:
            pass
    frame = _call_get_price(_code_candidates(code)[0], 1, ["close"], context=context, frequency="1m")
    if not frame.empty and "close" in frame.columns:
        values = pd.to_numeric(frame["close"], errors="coerce").dropna()
        if not values.empty:
            return float(values.iloc[-1])
    previous = _previous_close_map([code], context=context)
    if previous.get(_to_ths_code(code), 0.0) > 0:
        _log("info", "PRICE_FALLBACK_T1 date={} code={} price={:.4f}".format(_today(context), _to_ths_code(code), previous[_to_ths_code(code)]))
        return float(previous[_to_ths_code(code)])
    return 0.0


def _position_items(context):
    positions = getattr(getattr(context, "portfolio", None), "positions", {}) or {}
    try:
        return list(positions.items())
    except Exception:
        return []


def _account_value(context):
    portfolio = getattr(context, "portfolio", None)
    value = _value(portfolio, "total_value", "value", default=None)
    try:
        return float(value) if value is not None and float(value) > 0 else 1000000.0
    except Exception:
        return 1000000.0


def _place_target_value(code, value, action, reason):
    fn = _api("order_target_value")
    if not callable(fn):
        _log("info", "THS_ORDER_FAIL action={} code={} reason=order_target_value_missing".format(action, code))
        return False
    try:
        fn(_to_ths_code(code), float(max(value, 0.0)))
        _log("info", "THS_ORDER action={} code={} target_value={:.2f} reason={}".format(action, _to_ths_code(code), float(max(value, 0.0)), reason))
        return True
    except Exception as exc:
        _log("info", "THS_ORDER_FAIL action={} code={} reason={}".format(action, _to_ths_code(code), exc))
        return False


def rebalance(context, target, bar_dict=None):
    target = list(dict.fromkeys([_to_ths_code(code) for code in target]))
    target_set = set(target)
    positions = _position_items(context)
    for code, position in positions:
        normalized = _to_ths_code(code)
        if normalized in target_set:
            continue
        amount = sellable_amount(position)
        total = int(max(float(_value(position, "total_amount", "amount", default=0) or 0), 0))
        price = _position_price(normalized, context, bar_dict)
        if amount <= 0 or price <= 0:
            continue
        remaining_value = max(float(total - amount) * price, 0.0)
        _place_target_value(normalized, remaining_value, "sell", "rebalance_tplus1")
    if not target:
        return
    per_target = _account_value(context) * EXPOSURE / float(len(target))
    for code in target:
        price = _position_price(code, context, bar_dict)
        value = round_lot_value(price, per_target, ROUND_LOT)
        if value > 0:
            _place_target_value(code, value, "buy_or_adjust", "near_n1_q20")
        else:
            _log("info", "THS_ORDER_SKIP action=buy_or_adjust code={} reason=no_current_price price={:.6f} budget={:.2f}".format(_to_ths_code(code), price, per_target))
    context.ths_last_execute = _today(context)


def _market_ratio(context, bar_dict=None):
    frame = _call_get_price(INDEX_CODE, 2, ["open", "close"], context=context, frequency="1d")
    if frame.empty or not {"open", "close"}.issubset(frame.columns):
        return None
    row = frame.iloc[-1]
    try:
        return float(row["close"]) / float(row["open"]) if float(row["open"]) > 0 else None
    except Exception:
        return None


def _stop_position(context, code, position, price, reason):
    amount = sellable_amount(position)
    total = int(max(float(_value(position, "total_amount", "amount", default=0) or 0), 0))
    if amount <= 0 or price <= 0:
        return
    remaining_value = max(float(total - amount) * price, 0.0)
    _place_target_value(code, remaining_value, "risk_sell", reason)


def risk_checks(context, bar_dict=None):
    for code, position in _position_items(context):
        normalized = _to_ths_code(code)
        price = _position_price(normalized, context, bar_dict)
        avg_cost = _value(position, "avg_cost", "cost_basis", default=0)
        try:
            if price > 0 and float(avg_cost) > 0 and price <= float(avg_cost) * STOP_LOSS_RATIO:
                _log("info", "THS_RISK date={} code={} type=fixed_stop price={:.4f} cost={:.4f}".format(_today(context), normalized, price, float(avg_cost)))
                _stop_position(context, normalized, position, price, "fixed_stop_11pct")
        except Exception:
            pass
    ratio = _market_ratio(context, bar_dict)
    if ratio is not None and ratio <= MARKET_STOP_RATIO:
        _log("info", "THS_RISK date={} type=market_stop index={} ratio={:.4f}".format(_today(context), INDEX_CODE, ratio))
        for code, position in _position_items(context):
            _stop_position(context, _to_ths_code(code), position, _position_price(code, context, bar_dict), "market_stop_5pct")


def check_limit_up_reopen(context, bar_dict=None):
    data = _current_data()
    for code, position in _position_items(context):
        normalized = _to_ths_code(code)
        closeable = sellable_amount(position)
        if closeable <= 0:
            continue
        item = _current_item(data, normalized)
        high_limit = _value(item, "high_limit", default=None)
        price = _position_price(normalized, context, bar_dict)
        try:
            if high_limit is not None and price > 0 and price < float(high_limit) * 0.999:
                _stop_position(context, normalized, position, price, "limit_up_reopen")
        except Exception:
            continue


def _record(context):
    fn = _api("record")
    if callable(fn):
        try:
            fn(near_n1_q20_value=_account_value(context))
        except Exception:
            pass


def init(context):
    """SuperMind 初始化入口。"""
    context.ths_signal_date = ""
    context.ths_execute_date = ""
    context.ths_risk_date = ""
    context.ths_limit_date = ""
    context.ths_record_date = ""
    context.ths_last_signal = []
    context.ths_ranked = []
    context.ths_last_quality = {}
    context.ths_quality_fallback = True
    context.ths_cap_fallback = True
    for name, args in (
        ("set_benchmark", (INDEX_CODE,)),
        ("set_option", ("avoid_future_data", True)),
        ("set_commission", (None,)),
        ("set_slippage", (None, "stock")),
    ):
        fn = _api(name)
        if callable(fn):
            try:
                if name in ("set_commission", "set_slippage"):
                    continue
                fn(*args)
            except Exception:
                pass
    commission_cls = _api("PerShare")
    commission_fn = _api("set_commission")
    if callable(commission_cls) and callable(commission_fn):
        try:
            commission_fn(commission_cls(type="stock", cost=COMMISSION_RATE))
        except Exception:
            pass
    slippage_cls = _api("PriceSlippage")
    slippage_fn = _api("set_slippage")
    if callable(slippage_cls) and callable(slippage_fn):
        try:
            slippage_fn(slippage_cls(SLIPPAGE_RATE), "stock")
        except Exception:
            pass
    universe_fn = _api("set_universe")
    if callable(universe_fn):
        try:
            universe_fn([INDEX_CODE, DEFENSIVE_ETF])
        except Exception:
            pass
    _log("info", "THS_INIT strategy={} version={} initial_cash_target=1000000 stock_count={} quality_weight={:.2f}".format(STRATEGY_NAME, SCRIPT_VERSION, STOCK_COUNT, QUALITY_WEIGHT))


def before_trading(context):
    context.ths_signal_date = ""
    context.ths_execute_date = ""
    context.ths_risk_date = ""
    context.ths_limit_date = ""
    context.ths_record_date = ""
    _log("info", "THS_BEFORE_TRADING date={}".format(_today(context)))
    # 选股只依赖 T-1 数据，放在开盘前准备，避免 09:31 handle_bar 批量查询
    # 961 只股票后错过 09:45 执行事件。
    context.ths_last_signal = select_near_n1_q20(context)
    context.ths_signal_date = _today(context)
    _log("info", "THS_SIGNAL_READY date={} target={}".format(_today(context), ",".join(context.ths_last_signal or [])))


def handle_bar(context, bar_dict):
    """分钟级入口；每个阶段通过日期标记只执行一次。"""
    today = _today(context)
    hhmm = _hhmm(context)
    if hhmm >= 905 and getattr(context, "ths_signal_date", "") != today:
        context.ths_last_signal = select_near_n1_q20(context)
        context.ths_signal_date = today
    if hhmm >= 945 and getattr(context, "ths_execute_date", "") != today:
        _log("info", "THS_EXECUTE date={} time={} target={}".format(today, hhmm, ",".join(getattr(context, "ths_last_signal", []) or [])))
        rebalance(context, context.ths_last_signal, bar_dict)
        context.ths_execute_date = today
    if 1000 <= hhmm <= 1450 and getattr(context, "ths_risk_date", "") != today + str(hhmm):
        risk_checks(context, bar_dict)
        context.ths_risk_date = today + str(hhmm)
    if hhmm >= 1400 and getattr(context, "ths_limit_date", "") != today:
        check_limit_up_reopen(context, bar_dict)
        context.ths_limit_date = today
    if hhmm >= 1510 and getattr(context, "ths_record_date", "") != today:
        _record(context)
        _log("info", "THS_DAILY date={} value={:.2f} target={} positions={}".format(today, _account_value(context), ",".join(context.ths_last_signal), len(_position_items(context))))
        context.ths_record_date = today


def after_trading(context):
    _record(context)
    _log("info", "THS_AFTER_TRADING date={} value={:.2f} target={}".format(_today(context), _account_value(context), ",".join(getattr(context, "ths_last_signal", []) or [])))


def handle_data(context, data):
    """兼容部分 SuperMind 版本使用 handle_data 的入口。"""
    handle_bar(context, data)
