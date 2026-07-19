"""#39 大小盘反复横跳 V2.1：反转优先 + 趋势防守。

本脚本可直接复制到聚宽 Python3 策略编辑器运行。
核心变化：
1. 20 日相对表现采用反转方向，60 日相对表现作为趋势确认。
2. 风格切换使用领先幅度和最短持有期双重滞回。
3. SMALL/BIG 候选分别限制在历史国证2000/中证500成分股。
4. 市场与两个风格指数同时走弱时进入现金防守。
5. 候选缓冲区优先保留仍然合格的持仓，降低不必要的换手。

默认参数不是最终结论。请在聚宽用原始版、V1和本版做同区间、同成本的对照回测。
"""

from jqdata import *
import datetime

import numpy as np
import pandas as pd


SMALL_INDEX = "399303.XSHE"  # 国证2000
BIG_INDEX = "399905.XSHE"  # 中证500
MARKET_INDEX = "000985.XSHG"  # 中证全指


def initialize(context):
    set_benchmark(MARKET_INDEX)
    set_option("use_real_price", True)
    set_option("avoid_future_data", True)
    log.set_level("order", "error")

    g.params = {
        "stock_num": 5,
        "candidate_buffer": 2,
        "style_windows": (20, 60),
        "style_lookback_vol": 20,
        "switch_gap": 0.10,
        "min_style_months": 2,
        "min_listing_days": 375,
        "recent_limit_days": 40,
        "max_price": 0.0,
        "risk_off_enabled": True,
        "slippage": 0.001,
    }

    set_slippage(PriceRelatedSlippage(g.params["slippage"]))
    set_order_cost(
        OrderCost(
            open_tax=0,
            close_tax=0.001,
            open_commission=0.0003,
            close_commission=0.0003,
            close_today_commission=0,
            min_commission=5,
        ),
        type="stock",
    )

    g.current_style = None
    g.style_months = 0
    g.hold_list = []
    g.yesterday_HL_list = []

    run_daily(prepare_stock_list, "09:05")
    run_monthly(monthly_adjustment, 1, "09:35")
    run_daily(check_limit_up, "14:00")


# -----------------------------------------------------------------------------
# Pure functions: locally testable without jqdata.
# -----------------------------------------------------------------------------


def _safe_ratio(value, volatility):
    if value is None or volatility is None:
        return 0.0
    if not np.isfinite(value) or not np.isfinite(volatility) or volatility <= 1e-8:
        return 0.0
    return float(value) / float(volatility)


def compute_style_scores(small_returns, big_returns, small_vol, big_vol):
    """Return style scores; recent relative strength is intentionally reversed."""
    small_score = -0.65 * _safe_ratio(
        small_returns.get(20, 0.0), small_vol.get(20, 0.0)
    )
    small_score += 0.35 * _safe_ratio(
        small_returns.get(60, 0.0), small_vol.get(60, 0.0)
    )

    big_score = -0.65 * _safe_ratio(
        big_returns.get(20, 0.0), big_vol.get(20, 0.0)
    )
    big_score += 0.35 * _safe_ratio(
        big_returns.get(60, 0.0), big_vol.get(60, 0.0)
    )
    return {"SMALL": float(small_score), "BIG": float(big_score)}


def select_style_with_hysteresis(
    current_style, scores, switch_gap, hold_months, min_style_months
):
    """Keep the current style unless the challenger has a clear advantage."""
    challenger = "BIG" if current_style == "SMALL" else "SMALL"
    if hold_months < min_style_months:
        return current_style
    current_score = scores.get(current_style, -np.inf)
    challenger_score = scores.get(challenger, -np.inf)
    if challenger_score - current_score > switch_gap:
        return challenger
    return current_style


def market_risk_off(
    market_close, market_ma60, small_ma60, big_ma60, market_return20
):
    """The style indexes are passed as close/MA60 ratios."""
    return bool(
        market_close < market_ma60
        and small_ma60 < 1.0
        and big_ma60 < 1.0
        and market_return20 < 0.0
    )


def merge_target_with_holdings(
    holdings, ranked_candidates, target_count, buffer_count
):
    """Keep existing holdings in the candidate buffer before filling new slots."""
    buffer_set = set(ranked_candidates[:buffer_count])
    kept = [stock for stock in holdings if stock in buffer_set]
    filled = [stock for stock in ranked_candidates if stock not in kept]
    return (kept + filled)[:target_count]


# -----------------------------------------------------------------------------
# Market data and style signal.
# -----------------------------------------------------------------------------


def safe_close_series(raw_prices):
    if raw_prices is None or getattr(raw_prices, "empty", True):
        return None

    if isinstance(raw_prices, pd.DataFrame):
        if "close" not in raw_prices.columns:
            return None
        series = raw_prices["close"]
    else:
        try:
            series = raw_prices["close"]
        except (KeyError, TypeError, AttributeError):
            return None

    if isinstance(series, pd.DataFrame):
        if series.shape[1] != 1:
            return None
        series = series.iloc[:, 0]
    if not isinstance(series, pd.Series):
        return None

    series = pd.to_numeric(series, errors="coerce")
    series = series.replace([np.inf, -np.inf], np.nan).dropna()
    return series if not series.empty else None


def get_index_close(index_code, cutoff, count=61):
    """Read one index's daily close through compatible single-index APIs.

    ``attribute_history`` returns daily bars strictly before the current
    backtest date, so the 09:35 monthly schedule remains aligned with
    ``context.previous_date``.  Some backtest runtimes expose this API
    differently, so a plain single-index ``get_price`` call is the fallback.
    """
    errors = []
    try:
        raw_prices = attribute_history(
            index_code,
            count,
            unit="1d",
            fields=("close",),
            skip_paused=True,
            df=True,
        )
    except Exception as exc:
        raw_prices = None
        errors.append("attribute_history=%s" % exc)

    series = safe_close_series(raw_prices)
    if series is not None:
        return series
    if raw_prices is not None:
        errors.append(
            "attribute_history_shape=%s" % type(raw_prices).__name__
        )

    try:
        raw_prices = get_price(
            index_code,
            end_date=cutoff,
            frequency="daily",
            fields=["close"],
            count=count,
        )
    except Exception as exc:
        raw_prices = None
        errors.append("get_price=%s" % exc)

    series = safe_close_series(raw_prices)
    if series is not None:
        return series
    if raw_prices is not None:
        errors.append("get_price_shape=%s" % type(raw_prices).__name__)

    log.warn("指数历史行情无法解析 %s: %s", index_code, "; ".join(errors))
    return None


def index_statistics(index_code, cutoff):
    required_count = max(max(g.params["style_windows"]) + 1, 61)
    series = get_index_close(index_code, cutoff, count=required_count)
    if series is None:
        log.warn("指数统计失败 %s: close序列为空", index_code)
        return None
    if len(series) < required_count:
        log.warn(
            "指数统计失败 %s: close样本=%s，要求=%s",
            index_code,
            len(series),
            required_count,
        )
        return None

    latest = float(series.iloc[-1])
    if latest <= 0:
        return None

    returns = {}
    for window in g.params["style_windows"]:
        if len(series) <= window:
            return None
        base = float(series.iloc[-window - 1])
        if base <= 0:
            return None
        returns[window] = latest / base - 1.0

    daily_returns = series.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    volatility = {}
    for window in g.params["style_windows"]:
        lookback = max(g.params["style_lookback_vol"], window)
        if len(daily_returns) < lookback:
            return None
        volatility[window] = float(
            daily_returns.tail(lookback).std(ddof=1) * np.sqrt(252)
        )
    ma60 = float(series.tail(60).mean())
    if any(
        not np.isfinite(value) or value <= 1e-8 for value in volatility.values()
    ) or ma60 <= 0:
        return None

    return {
        "close": latest,
        "ma60": ma60,
        "returns": returns,
        "volatility": volatility,
    }


def determine_market_style(context):
    cutoff = context.previous_date
    small_stats = index_statistics(SMALL_INDEX, cutoff)
    big_stats = index_statistics(BIG_INDEX, cutoff)
    market_stats = index_statistics(MARKET_INDEX, cutoff)
    if small_stats is None or big_stats is None or market_stats is None:
        missing = []
        if small_stats is None:
            missing.append("SMALL")
        if big_stats is None:
            missing.append("BIG")
        if market_stats is None:
            missing.append("MARKET")
        log.warn("风格或市场行情不足，缺少=%s，保持当前风格", ",".join(missing))
        return None, False

    scores = compute_style_scores(
        small_stats["returns"],
        big_stats["returns"],
        small_stats["volatility"],
        big_stats["volatility"],
    )

    if g.current_style is None:
        g.current_style = "BIG" if scores["BIG"] > scores["SMALL"] else "SMALL"
        g.style_months = 1
        changed = True
    else:
        previous_style = g.current_style
        next_style = select_style_with_hysteresis(
            previous_style,
            scores,
            g.params["switch_gap"],
            g.style_months,
            g.params["min_style_months"],
        )
        changed = next_style != previous_style
        g.current_style = next_style
        g.style_months = 1 if changed else g.style_months + 1

    small_ratio = small_stats["close"] / small_stats["ma60"]
    big_ratio = big_stats["close"] / big_stats["ma60"]
    risk_off = False
    if g.params["risk_off_enabled"]:
        risk_off = market_risk_off(
            market_stats["close"],
            market_stats["ma60"],
            small_ratio,
            big_ratio,
            market_stats["returns"][20],
        )

    log.info(
        "风格 scores SMALL=%.3f BIG=%.3f -> %s; risk_off=%s; months=%s; changed=%s",
        scores["SMALL"],
        scores["BIG"],
        g.current_style,
        risk_off,
        g.style_months,
        changed,
    )
    return g.current_style, risk_off


# -----------------------------------------------------------------------------
# Candidate pools and ranking.
# -----------------------------------------------------------------------------


def style_index(style):
    return SMALL_INDEX if style == "SMALL" else BIG_INDEX


def base_style_pool(context, style):
    cutoff = context.previous_date
    try:
        stocks = list(get_index_stocks(style_index(style), date=cutoff) or [])
    except Exception as exc:
        log.warn("获取历史指数成分失败 %s: %s", style, exc)
        return []

    result = []
    listing_cutoff = cutoff - datetime.timedelta(days=g.params["min_listing_days"])
    for stock in stocks:
        if stock[0] in ("3", "4", "8") or stock[:2] == "68":
            continue
        try:
            info = get_security_info(stock)
        except Exception:
            continue
        if info is None or info.start_date >= listing_cutoff:
            continue
        result.append(stock)
    return result


def current_price(stock):
    try:
        price = get_current_data()[stock].last_price
    except Exception:
        return np.nan
    return float(price) if price is not None and np.isfinite(price) else np.nan


def is_tradeable(context, stock, side):
    try:
        data = get_current_data()[stock]
        price = float(data.last_price)
        high_limit = float(data.high_limit)
        low_limit = float(data.low_limit)
    except Exception:
        return False

    if data.paused or data.is_st:
        return False
    if not all(np.isfinite(value) for value in (price, high_limit, low_limit)):
        return False
    if price <= 0:
        return False
    if side == "buy" and price >= high_limit:
        return False
    if side == "sell" and price <= low_limit:
        return False
    return True


def recent_limit_up_stocks(context, stocks, days):
    result = []
    for stock in stocks:
        try:
            frame = get_price(
                stock,
                end_date=context.previous_date,
                frequency="daily",
                fields=["close", "high_limit"],
                count=days,
                panel=False,
                fill_paused=False,
            )
        except Exception:
            continue
        if frame is None or frame.empty:
            continue
        if (frame["close"] == frame["high_limit"]).any():
            result.append(stock)
    return result


def _candidate_limit():
    return max(
        g.params["stock_num"] * g.params["candidate_buffer"],
        g.params["stock_num"] + 3,
    )


def _apply_price_filter(stocks):
    max_price = g.params["max_price"]
    if max_price is None or max_price <= 0:
        return stocks
    return [stock for stock in stocks if current_price(stock) < max_price]


def small_candidates(context):
    stocks = [
        stock
        for stock in base_style_pool(context, "SMALL")
        if is_tradeable(context, stock, "buy")
    ]
    if not stocks:
        return []

    cutoff = context.previous_date
    q = (
        query(valuation.code, valuation.market_cap, indicator.roe, indicator.roa)
        .filter(
            valuation.code.in_(stocks),
            valuation.market_cap > 0,
            indicator.roe > 0.15,
            indicator.roa > 0.10,
        )
        .order_by(valuation.market_cap.asc())
        .limit(_candidate_limit())
    )
    frame = get_fundamentals(q, date=cutoff)
    if frame is None or frame.empty:
        return []

    ranked = _apply_price_filter(list(frame.code))
    recent = set(
        recent_limit_up_stocks(
            context,
            ranked,
            g.params["recent_limit_days"],
        )
    )
    held = set(g.hold_list)
    return [stock for stock in ranked if not (stock in recent and stock in held)]


def big_candidates(context):
    stocks = [
        stock
        for stock in base_style_pool(context, "BIG")
        if is_tradeable(context, stock, "buy")
    ]
    if not stocks:
        return []

    cutoff = context.previous_date
    q = (
        query(
            valuation.code,
            valuation.market_cap,
            valuation.pe_ratio_lyr,
            valuation.ps_ratio,
            valuation.pcf_ratio,
            indicator.eps,
            indicator.roe,
            indicator.net_profit_margin,
            indicator.gross_profit_margin,
            indicator.inc_revenue_year_on_year,
        )
        .filter(
            valuation.code.in_(stocks),
            valuation.market_cap > 0,
            valuation.pe_ratio_lyr.between(0, 30),
            valuation.ps_ratio.between(0, 8),
            valuation.pcf_ratio < 10,
            indicator.eps > 0.3,
            indicator.roe > 0.10,
            indicator.net_profit_margin > 0.10,
            indicator.gross_profit_margin > 0.30,
            indicator.inc_revenue_year_on_year > 0.25,
        )
        .order_by(valuation.market_cap.desc())
        .limit(_candidate_limit())
    )
    frame = get_fundamentals(q, date=cutoff)
    if frame is None or frame.empty:
        return []
    return _apply_price_filter(list(frame.code))


def get_candidates(context, style):
    return small_candidates(context) if style == "SMALL" else big_candidates(context)


# -----------------------------------------------------------------------------
# Orders and scheduled routines.
# -----------------------------------------------------------------------------


def prepare_stock_list(context):
    g.hold_list = list(context.portfolio.positions.keys())
    g.yesterday_HL_list = []
    if not g.hold_list:
        return

    try:
        prices = get_price(
            g.hold_list,
            end_date=context.previous_date,
            frequency="daily",
            fields=["close", "high_limit"],
            count=1,
            panel=False,
            fill_paused=False,
        )
    except Exception as exc:
        log.warn("昨日涨停列表获取失败: %s", exc)
        return

    if prices is None or prices.empty or "code" not in prices.columns:
        return
    hit = prices[prices["close"] == prices["high_limit"]]
    g.yesterday_HL_list = list(hit["code"])


def safe_order_target_value(context, stock, value):
    side = "sell" if value == 0 else "buy"
    if not is_tradeable(context, stock, side):
        log.info("跳过%s：当前不可%s", stock, "卖出" if value == 0 else "买入")
        return False

    try:
        order = order_target_value(stock, value)
    except Exception as exc:
        log.warn("订单异常 %s target=%.2f: %s", stock, value, exc)
        return False

    if order is None:
        log.info("订单为空 %s target=%.2f", stock, value)
        return False
    filled = getattr(order, "filled", 0) or 0
    success = filled > 0 or (value == 0 and order.status == OrderStatus.held)
    log.info("订单 %s target=%.2f filled=%s success=%s", stock, value, filled, success)
    return success


def monthly_adjustment(context):
    style, risk_off = determine_market_style(context)
    if style is None:
        log.warn("风格信号不可用，保持当前持仓")
        return

    if risk_off:
        target = []
        log.info("市场防守开启，目标持仓为空")
    else:
        ranked = get_candidates(context, style)
        if not ranked:
            log.warn("%s 候选为空，保持当前持仓", style)
            return
        target = merge_target_with_holdings(
            g.hold_list,
            ranked,
            g.params["stock_num"],
            g.params["stock_num"] * g.params["candidate_buffer"],
        )
        if not target:
            log.warn("%s 目标为空，保持当前持仓", style)
            return

    log.info("本月风格=%s risk_off=%s target=%s", style, risk_off, target)
    protected = set(g.yesterday_HL_list)
    for stock in list(context.portfolio.positions.keys()):
        if stock not in target and stock not in protected:
            safe_order_target_value(context, stock, 0)

    missing = [stock for stock in target if stock not in context.portfolio.positions]
    if not missing:
        return

    value = context.portfolio.available_cash / len(missing)
    for stock in missing:
        safe_order_target_value(context, stock, value)


def check_limit_up(context):
    for stock in list(g.yesterday_HL_list):
        if stock not in context.portfolio.positions:
            continue
        try:
            frame = get_price(
                stock,
                end_date=context.current_dt,
                frequency="1m",
                fields=["close", "high_limit"],
                count=1,
                panel=False,
                fill_paused=True,
            )
        except Exception as exc:
            log.warn("涨停检查失败 %s: %s", stock, exc)
            continue

        if frame is None or frame.empty:
            continue
        row = frame.iloc[-1]
        if row["close"] < row["high_limit"]:
            log.info("[%s] 昨日涨停今日开板，卖出", stock)
            safe_order_target_value(context, stock, 0)
