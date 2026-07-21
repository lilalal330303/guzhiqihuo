"""V3.0 original-replica adapters.

The default mode intentionally reproduces the original backtest date
semantics; STRICT_ASOF is provided only as a research comparison mode.
"""

from datetime import timedelta

import numpy as np
import pandas as pd

from jqdata import *


RUN_MODE = "ORIGINAL_REPLICA"
INDEX_2000 = "399303.XSHE"
INDEX_500 = "399905.XSHE"
MARKET_INDEX = "000985.XSHG"


def fundamental_date(context):
    return context.previous_date if RUN_MODE == "STRICT_ASOF" else None


def constituent_date(context):
    return context.previous_date if RUN_MODE == "STRICT_ASOF" else context.current_dt


def select_style_branch(mean_2000, mean_500, ratio_threshold=1.2):
    try:
        numerator = float(mean_2000)
        denominator = float(mean_500)
        threshold = float(ratio_threshold)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(numerator) or not np.isfinite(denominator):
        return None
    if abs(denominator) <= 1e-12:
        return None
    return "BIG" if numerator / denominator > threshold else "SMALL"


def _date_column(columns):
    preferred = {"date", "datetime", "time", "trade_date", "交易日期"}
    for column in columns:
        if str(column).lower() in preferred:
            return column
    return None


def _code_column(columns):
    preferred = {"code", "security", "symbol", "stock", "证券代码"}
    for column in columns:
        if str(column).lower() in preferred:
            return column
    return None


def _coerce_dates(values):
    return pd.to_datetime(values, errors="coerce")


def _finish_close_frame(frame):
    if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
        return None

    result = frame.copy()
    result.index = _coerce_dates(result.index)
    result = result.loc[~result.index.isna()]
    if result.empty:
        return None

    for column in result.columns:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    result = result.groupby(level=0, sort=True).last()
    result = result.dropna(axis=1, how="all")
    if result.empty:
        return None
    return result.sort_index()


def _multiindex_close_frame(raw_prices):
    if "close" not in raw_prices.columns or raw_prices.index.nlevels != 2:
        return None

    reset = raw_prices.reset_index()
    date_column = _date_column(reset.columns)
    code_column = _code_column(reset.columns)
    index_columns = list(reset.columns[:2]) if date_column is None else []

    if date_column is None:
        date_candidates = []
        for column in index_columns:
            parsed = _coerce_dates(reset[column])
            date_candidates.append((parsed.notna().sum(), column))
        if not date_candidates:
            return None
        date_column = max(date_candidates)[1]
    if code_column is None:
        code_candidates = [column for column in index_columns if column != date_column]
        if not code_candidates:
            code_candidates = [column for column in reset.columns if column != date_column and column != "close"]
        if not code_candidates:
            return None
        code_column = code_candidates[0]

    dates = _coerce_dates(reset[date_column])
    valid = reset.loc[dates.notna(), [date_column, code_column, "close"]].copy()
    valid[date_column] = dates.loc[valid.index]
    if valid.empty:
        return None
    valid["close"] = pd.to_numeric(valid["close"], errors="coerce")
    return valid.pivot_table(
        index=date_column,
        columns=code_column,
        values="close",
        aggfunc="last",
    )


def _long_close_frame(raw_prices):
    if "close" not in raw_prices.columns:
        return None

    date_column = _date_column(raw_prices.columns)
    code_column = _code_column(raw_prices.columns)
    if date_column is None:
        index_dates = _coerce_dates(raw_prices.index)
        if not index_dates.notna().any():
            return None
        working = raw_prices.reset_index()
        date_column = working.columns[0]
        working[date_column] = index_dates
    else:
        working = raw_prices.copy()
    if code_column is None or date_column == code_column:
        return None

    dates = _coerce_dates(working[date_column])
    valid = working.loc[dates.notna(), [date_column, code_column, "close"]].copy()
    valid[date_column] = dates.loc[valid.index]
    if valid.empty:
        return None
    valid["close"] = pd.to_numeric(valid["close"], errors="coerce")
    return valid.pivot_table(
        index=date_column,
        columns=code_column,
        values="close",
        aggfunc="last",
    )


def safe_close_frame(raw_prices):
    """Return a sorted date-indexed wide numeric close frame when usable."""
    if raw_prices is None:
        return None

    if not isinstance(raw_prices, pd.DataFrame):
        try:
            close = raw_prices["close"]
        except Exception:
            return None
        if isinstance(close, pd.Series):
            close = close.to_frame()
        if not isinstance(close, pd.DataFrame):
            return None
        return _finish_close_frame(close)

    if raw_prices.empty:
        return None

    if isinstance(raw_prices.index, pd.MultiIndex):
        normalized = _multiindex_close_frame(raw_prices)
        return _finish_close_frame(normalized)

    if "close" in raw_prices.columns and _code_column(raw_prices.columns) is not None:
        normalized = _long_close_frame(raw_prices)
        return _finish_close_frame(normalized)

    return _finish_close_frame(raw_prices)


def cross_sectional_mean_return(raw_prices):
    """Return the original cross-sectional mean percentage return."""
    close_frame = safe_close_frame(raw_prices)
    if close_frame is None or len(close_frame.index) < 2:
        return None

    first = close_frame.iloc[0]
    last = close_frame.iloc[-1]
    usable = first.notna() & last.notna() & first.ne(0)
    if not usable.any():
        return None

    returns = (last[usable] - first[usable]) / first[usable] * 100
    returns = returns[np.isfinite(returns)]
    if returns.empty:
        return None
    return float(returns.mean())


def initialize(context):
    """Configure the original monthly size-style strategy settings."""
    set_benchmark(MARKET_INDEX)
    set_option("use_real_price", True)
    set_option("avoid_future_data", True)
    set_slippage(FixedSlippage(0))
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
    log.set_level("order", "error")

    g.stock_num = 5
    g.no_trading_today_signal = False
    g.hold_list = []
    g.yesterday_HL_list = []

    run_daily(prepare_stock_list, time="09:05")
    run_monthly(weekly_adjustment, 1, time="09:30")
    run_daily(check_limit_up, time="14:00")
    run_daily(close_account, time="14:30")


def _position_symbols(context):
    return [position.security for position in context.portfolio.positions.values()]


def _price_codes(frame, holdings):
    """Extract security codes from JoinQuant's long, indexed, or single response."""
    if "code" in frame.columns:
        return list(frame["code"])
    if isinstance(frame.index, pd.MultiIndex):
        if "code" in frame.index.names:
            return list(frame.index.get_level_values("code"))
        return list(frame.index.get_level_values(-1))
    if len(holdings) == 1:
        return [holdings[0]] * len(frame)
    if frame.index.name == "code":
        return list(frame.index)
    return []


def prepare_stock_list(context):
    """Snapshot held symbols and yesterday's closing-limit-up positions."""
    g.hold_list = _position_symbols(context)
    g.yesterday_HL_list = []
    if not g.hold_list:
        return

    prices = get_price(
        g.hold_list,
        end_date=context.previous_date,
        frequency="daily",
        fields=["close", "high_limit"],
        count=1,
        panel=False,
        fill_paused=False,
    )
    if prices is None or getattr(prices, "empty", True):
        return
    if "close" not in prices.columns or "high_limit" not in prices.columns:
        return

    codes = _price_codes(prices, g.hold_list)
    if len(codes) != len(prices):
        return
    hit = prices["close"].eq(prices["high_limit"])
    g.yesterday_HL_list = list(
        dict.fromkeys(code for code, is_hit in zip(codes, hit) if is_hit)
    )


def filter_kcbj_stock(context, stock_list):
    return [
        stock
        for stock in stock_list
        if stock[0] not in ("3", "4", "8") and stock[:2] != "68"
    ]


def filter_st_stock(context, stock_list):
    current_data = get_current_data()
    return [
        stock
        for stock in stock_list
        if not current_data[stock].is_st
        and "ST" not in current_data[stock].name
        and "*" not in current_data[stock].name
        and "退" not in current_data[stock].name
    ]


def filter_paused_stock(context, stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list if not current_data[stock].paused]


def filter_new_stock(context, stock_list):
    return [
        stock
        for stock in stock_list
        if context.previous_date - get_security_info(stock).start_date
        >= timedelta(days=375)
    ]


def _last_minute_prices(stock_list):
    return history(1, unit="1m", field="close", security_list=stock_list)


def _last_price(prices, stock):
    values = prices[stock]
    return values.iloc[-1] if hasattr(values, "iloc") else values[-1]


def filter_limitup_stock(context, stock_list):
    last_prices = _last_minute_prices(stock_list)
    current_data = get_current_data()
    return [
        stock
        for stock in stock_list
        if stock in g.hold_list
        or _last_price(last_prices, stock) < current_data[stock].high_limit
    ]


def filter_limitdown_stock(context, stock_list):
    last_prices = _last_minute_prices(stock_list)
    current_data = get_current_data()
    return [
        stock
        for stock in stock_list
        if stock in g.hold_list
        or _last_price(last_prices, stock) > current_data[stock].low_limit
    ]


def filter_highprice_stock(context, stock_list):
    last_prices = _last_minute_prices(stock_list)
    return [
        stock
        for stock in stock_list
        if stock in g.hold_list or _last_price(last_prices, stock) < 10
    ]


def _codes_from_fundamentals(frame):
    if not isinstance(frame, pd.DataFrame):
        return None
    if frame.empty:
        return []
    if "code" in frame.columns:
        return list(frame["code"])
    return list(frame.index)


def get_peg(context, stocks):
    quality_query = query(valuation.code).filter(
        valuation.code.in_(stocks),
        indicator.roe > 0.15,
        indicator.roa > 0.10,
    )
    try:
        qualified = _codes_from_fundamentals(
            get_fundamentals(quality_query, date=fundamental_date(context))
        )
    except Exception:
        return None
    if qualified is None:
        return None
    if not qualified:
        return []

    rank_query = query(valuation.code).filter(
        valuation.code.in_(qualified)
    ).order_by(valuation.market_cap.asc())
    try:
        return _codes_from_fundamentals(
            get_fundamentals(rank_query, date=fundamental_date(context))
        )
    except Exception:
        return None


def get_recent_limit_up_stock(context, stock_list, recent_days):
    result = []
    for stock in stock_list:
        prices = get_price(
            stock,
            end_date=context.previous_date,
            frequency="daily",
            fields=["close", "high_limit"],
            count=recent_days,
            panel=False,
            fill_paused=False,
        )
        if prices is not None and not prices.empty and (
            prices["close"] == prices["high_limit"]
        ).any():
            result.append(stock)
    return result


def exclude_recent_limit_up_holdings(ranked, holdings, recent_limit_ups):
    blacklist = set(holdings or ()) & set(recent_limit_ups or ())
    return [stock for stock in ranked if stock not in blacklist]


def _all_stock_symbols(context):
    securities = get_all_securities("stock", date=context.previous_date)
    return list(securities.index)


def SMALL(context):
    stocks = _all_stock_symbols(context)
    stocks = filter_kcbj_stock(context, stocks)
    stocks = filter_st_stock(context, stocks)
    stocks = filter_paused_stock(context, stocks)
    stocks = filter_new_stock(context, stocks)
    stocks = filter_limitup_stock(context, stocks)
    stocks = filter_limitdown_stock(context, stocks)
    stocks = filter_highprice_stock(context, stocks)
    ranked = get_peg(context, stocks)
    if ranked is None:
        return None
    recent_limit_ups = get_recent_limit_up_stock(context, ranked, 40)
    return exclude_recent_limit_up_holdings(
        ranked, g.hold_list, recent_limit_ups
    )[: g.stock_num]


def BIG(context):
    stocks = _all_stock_symbols(context)
    stocks = filter_kcbj_stock(context, stocks)
    choice = filter_st_stock(context, stocks)
    choice = filter_paused_stock(context, choice)
    choice = filter_new_stock(context, choice)
    choice = filter_limitup_stock(context, choice)
    choice = filter_limitdown_stock(context, choice)

    big_query = query(valuation.code).filter(
        valuation.code.in_(stocks),
        valuation.pe_ratio_lyr.between(0, 30),
        valuation.ps_ratio.between(0, 8),
        valuation.pcf_ratio < 10,
        indicator.eps > 0.3,
        indicator.roe > 0.10,
        indicator.net_profit_margin > 0.10,
        indicator.gross_profit_margin > 0.30,
        indicator.inc_revenue_year_on_year > 0.25,
    ).order_by(valuation.market_cap.desc()).limit(g.stock_num)
    try:
        return _codes_from_fundamentals(
            get_fundamentals(big_query, date=fundamental_date(context))
        )
    except Exception:
        return None


def select_target_list(context, branch):
    if branch == "BIG":
        return BIG(context)
    if branch == "SMALL":
        return SMALL(context)
    return []


def rebalance_lists(holdings, target, protected):
    protected_set = set(protected or ())
    holdings = list(holdings or ())
    target = list(target or ())
    sell_list = [
        stock for stock in holdings if stock not in target and stock not in protected_set
    ]
    buy_list = [stock for stock in target if stock not in holdings]
    return sell_list, buy_list


def buy_allocation(position_count, target_num, cash):
    slot_count = target_num - position_count
    if slot_count <= 0:
        return 0.0, 0
    return cash / slot_count, slot_count


def order_target_value_(security, value):
    if value == 0:
        log.debug("Selling out %s" % security)
    else:
        log.debug("Order %s to value %f" % (security, value))
    try:
        order = order_target_value(security, value)
    except Exception as exc:
        log.warn("order failed for %s target=%s: %s" % (security, value, exc))
        return False
    if order is None:
        log.warn("order unavailable for %s target=%s" % (security, value))
        return False
    return order


def open_position(security, value):
    order = order_target_value_(security, value)
    filled = getattr(order, "filled", 0) or 0
    success = bool(order) and filled > 0
    if not success:
        log.warn("open order not filled for %s target=%s" % (security, value))
    return success


def close_position(position):
    order = order_target_value_(position.security, 0)
    order_status = globals().get("OrderStatus")
    held_status = getattr(order_status, "held", None)
    filled = getattr(order, "filled", None)
    amount = getattr(order, "amount", None)
    success = (
        bool(order)
        and held_status is not None
        and getattr(order, "status", None) == held_status
        and filled is not None
        and amount is not None
        and filled == amount
    )
    if not success:
        log.warn("close order not fully filled for %s" % position.security)
    return success


def _style_prices(stock_list, yesterday):
    try:
        return get_price(
            stock_list,
            end_date=yesterday,
            frequency="1d",
            fields=["close"],
            count=20,
            panel=False,
        )
    except TypeError as exc:
        if "panel" not in str(exc):
            raise
        return get_price(
            stock_list,
            end_date=yesterday,
            frequency="1d",
            fields=["close"],
            count=20,
        )


def weekly_adjustment(context):
    """Select the original style branch and rebalance its target list."""
    yesterday = context.previous_date
    stock_list_2000 = get_index_stocks(
        INDEX_2000, date=constituent_date(context)
    )
    stock_list_500 = get_index_stocks(
        INDEX_500, date=constituent_date(context)
    )
    mean_2000 = cross_sectional_mean_return(
        _style_prices(stock_list_2000, yesterday)
    )
    mean_500 = cross_sectional_mean_return(
        _style_prices(stock_list_500, yesterday)
    )
    branch = select_style_branch(mean_2000, mean_500, 1.2)
    if branch is None:
        log.warn("style signal unavailable; keep current holdings")
        return

    try:
        target = select_target_list(context, branch)
    except Exception as exc:
        log.warn("candidate-list-unavailable: %s" % exc)
        return
    if target is None:
        log.warn("candidate-list-unavailable")
        return

    sell_list, buy_list = rebalance_lists(
        g.hold_list, target, g.yesterday_HL_list
    )
    holdings_before = _position_symbols(context)
    log.info(
        "mode=%s mean_2000=%s mean_500=%s branch=%s target_count=%s "
        "target_list=%s holdings_before=%s sell_list=%s buy_list=%s"
        % (
            RUN_MODE,
            mean_2000,
            mean_500,
            branch,
            len(target),
            target,
            holdings_before,
            sell_list,
            buy_list,
        )
    )
    positions = context.portfolio.positions
    for stock in sell_list:
        position = positions.get(stock)
        if position is not None:
            log.info("sell order outcome stock=%s success=%s" % (
                stock, close_position(position)
            ))

    position_count = len(context.portfolio.positions)
    target_num = len(target)
    try:
        cash = context.portfolio.cash
    except AttributeError:
        cash = context.portfolio.available_cash
    value, slot_count = buy_allocation(position_count, target_num, cash)
    successful_opens = 0
    for stock in buy_list:
        if (
            successful_opens >= slot_count
            or len(context.portfolio.positions) >= target_num
        ):
            break
        opened = open_position(stock, value)
        log.info("buy order outcome stock=%s success=%s" % (stock, opened))
        if opened:
            successful_opens += 1

    log.info(
        "holdings_after=%s position_count=%s slot_count=%s"
        % (_position_symbols(context), len(context.portfolio.positions), slot_count)
    )


def check_limit_up(context):
    """Sell a protected limit-up holding only after its limit opens."""
    for stock in list(getattr(g, "yesterday_HL_list", [])):
        position = context.portfolio.positions.get(stock)
        if position is None:
            continue
        try:
            prices = get_price(
                stock,
                end_date=context.current_dt,
                frequency="1m",
                fields=["close", "high_limit"],
                count=1,
                panel=False,
                fill_paused=True,
            )
            if prices is None or getattr(prices, "empty", True):
                continue
            row = prices.iloc[-1]
            if float(row["close"]) < float(row["high_limit"]):
                log.info("[%s] limit opened; sell" % stock)
                log.info("limit-up sell outcome stock=%s success=%s" % (
                    stock, close_position(position)
                ))
            else:
                log.info("[%s] limit still locked; hold" % stock)
        except Exception as exc:
            log.warn("limit-up check failed for %s: %s" % (stock, exc))


def close_account(context):
    """Close ordinary holdings only when the original flag requests it."""
    if not getattr(g, "no_trading_today_signal", False):
        return
    protected = set(getattr(g, "yesterday_HL_list", []))
    for stock in list(getattr(g, "hold_list", [])):
        if stock in protected:
            continue
        position = context.portfolio.positions.get(stock)
        if position is not None:
            log.info("close-account outcome stock=%s success=%s" % (
                stock, close_position(position)
            ))
