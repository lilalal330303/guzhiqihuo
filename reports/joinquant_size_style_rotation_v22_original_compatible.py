"""Original-compatible JoinQuant size-style rotation strategy.

The default path preserves the original V2.0 signal, candidate rules, schedule,
and costs while making historical cutoffs and order failures explicit.  JoinQuant
API names are resolved only inside runtime functions so local tests can import
this file with an empty ``jqdata`` stub.
"""

import datetime
import numpy as np
import pandas as pd

from jqdata import *  # noqa: F401,F403 - provided by the JoinQuant runtime


INDEX_2000 = "399303.XSHE"
INDEX_500 = "399905.XSHE"
MARKET_INDEX = "000985.XSHG"

DEFAULT_PARAMS = {
    "stock_num": 5,
    "style_window": 20,
    "ratio_threshold": 1.2,
    "min_style_samples": 2,
    "max_price": 10.0,
    "min_listing_days": 375,
    "recent_limit_days": 40,
    "winsorize_returns": False,
    "market_guard": False,
    "market_guard_ma": 60,
    "slippage": 0.0,
    "use_historical_constituents": True,
    "big_use_filtered_pool": False,
}


def select_original_branch(mean_2000, mean_500, ratio_threshold):
    """Return the original strategy branch selected by the style ratio."""
    try:
        numerator = float(mean_2000)
        denominator = float(mean_500)
        threshold = float(ratio_threshold)
    except (TypeError, ValueError):
        return None

    if not all(np.isfinite(value) for value in (numerator, denominator, threshold)):
        return None
    if abs(denominator) <= 1e-8:
        return None
    return "BIG" if numerator / denominator > threshold else "SMALL"


def safe_mean_return(close_frame, min_samples=2, winsorize=False):
    """Calculate a safe cross-sectional mean return from first/last closes."""
    if not isinstance(close_frame, pd.DataFrame) or close_frame.empty:
        return None

    frame = close_frame.apply(pd.to_numeric, errors="coerce")
    first = frame.iloc[0]
    last = frame.iloc[-1]
    usable = (
        first.notna()
        & last.notna()
        & np.isfinite(first)
        & np.isfinite(last)
        & first.ne(0)
        & last.ne(0)
    )
    returns = (last[usable] / first[usable] - 1.0).replace(
        [np.inf, -np.inf], np.nan
    ).dropna()

    try:
        required_samples = int(min_samples)
    except (TypeError, ValueError):
        return None
    if required_samples < 0 or len(returns) < required_samples:
        return None

    if winsorize and len(returns) >= 5:
        lower = returns.quantile(0.05)
        upper = returns.quantile(0.95)
        returns = returns.clip(lower, upper)

    value = float(returns.mean())
    return value if np.isfinite(value) else None


def merge_target_with_holdings(holdings, ranked_candidates, target_count):
    """Keep still-ranked holdings first, then fill from candidate rank order."""
    try:
        count = int(target_count)
    except (TypeError, ValueError):
        return []
    if count <= 0:
        return []

    ranked = list(dict.fromkeys(ranked_candidates or ()))
    kept = []
    for stock in holdings or ():
        if stock in ranked and stock not in kept:
            kept.append(stock)
    filled = [stock for stock in ranked if stock not in kept]
    return (kept + filled)[:count]


def merge_target_with_protected_holdings(
    holdings, ranked_candidates, protected_holdings, target_count
):
    """Reserve target slots for protected holdings before ranked candidates."""
    protected = set(protected_holdings or ())
    protected_in_hold_order = [
        stock
        for stock in dict.fromkeys(holdings or ())
        if stock in protected
    ]
    ranked = protected_in_hold_order + [
        stock
        for stock in ranked_candidates or ()
        if stock not in protected
    ]
    return merge_target_with_holdings(holdings, ranked, target_count)


def _date_values(frame):
    """Extract date-like values from a price frame without inventing dates."""
    for column in ("time", "date", "trade_date"):
        if column in frame.columns:
            return frame[column]
    if isinstance(frame.index, pd.MultiIndex):
        for level_name in ("time", "date", "trade_date"):
            if level_name in frame.index.names:
                return frame.index.get_level_values(level_name)
        return frame.index.get_level_values(0)
    return frame.index


def _normalize_wide_close_frame(frame):
    """Convert a close matrix to numeric values on a sorted DatetimeIndex."""
    if isinstance(frame, pd.Series):
        frame = frame.to_frame()
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return None

    result = frame.copy()
    dates = pd.to_datetime(_date_values(result), errors="coerce")
    valid_dates = ~pd.isna(dates)
    if not np.any(valid_dates):
        return None
    result = result.loc[valid_dates].copy()
    result.index = pd.DatetimeIndex(dates[valid_dates])
    result = result.apply(pd.to_numeric, errors="coerce")
    result = result.replace([np.inf, -np.inf], np.nan).dropna(axis=1, how="all")
    if result.empty or result.shape[1] == 0:
        return None
    if result.index.has_duplicates:
        result = result.groupby(level=0, sort=False).last()
    return result.sort_index(kind="mergesort")


def _normalize_single_close_frame(frame):
    """Normalize a close-only frame without losing row dates or code levels."""
    if isinstance(frame.index, pd.MultiIndex) and "code" in frame.index.names:
        date_level = next(
            (
                level_name
                for level_name in ("time", "date", "trade_date")
                if level_name in frame.index.names
            ),
            None,
        )
        if date_level is not None:
            long_frame = pd.DataFrame(
                {
                    "date": frame.index.get_level_values(date_level),
                    "code": frame.index.get_level_values("code"),
                    "close": frame["close"].to_numpy(),
                }
            )
            long_frame["date"] = pd.to_datetime(
                long_frame["date"], errors="coerce"
            )
            long_frame["close"] = pd.to_numeric(
                long_frame["close"], errors="coerce"
            )
            long_frame = long_frame.dropna(subset=["date", "code"])
            if long_frame.empty:
                return None

            close_frame = long_frame.pivot_table(
                index="date",
                columns="code",
                values="close",
                aggfunc="last",
                sort=False,
            )
            close_frame.columns.name = None
            return _normalize_wide_close_frame(close_frame)

    close_frame = frame[["close"]].copy()
    close_frame.index = pd.DatetimeIndex(
        pd.to_datetime(_date_values(frame), errors="coerce")
    )
    return _normalize_wide_close_frame(close_frame)


def safe_close_frame(raw_prices):
    """Normalize supported JoinQuant price responses into a close matrix."""
    if raw_prices is None:
        return None

    if not isinstance(raw_prices, pd.DataFrame):
        try:
            close_values = raw_prices["close"]
        except (KeyError, TypeError, AttributeError):
            return None
        return _normalize_wide_close_frame(close_values)

    if raw_prices.empty:
        return None

    if isinstance(raw_prices.columns, pd.MultiIndex):
        try:
            return _normalize_wide_close_frame(raw_prices["close"])
        except KeyError:
            return None

    if "close" not in raw_prices.columns:
        return _normalize_wide_close_frame(raw_prices)

    if "code" not in raw_prices.columns:
        return _normalize_single_close_frame(raw_prices)

    long_frame = raw_prices[["code", "close"]].copy()
    long_frame["date"] = pd.to_datetime(_date_values(raw_prices), errors="coerce")
    long_frame["close"] = pd.to_numeric(long_frame["close"], errors="coerce")
    long_frame = long_frame.dropna(subset=["date", "code"])
    if long_frame.empty:
        return None

    close_frame = long_frame.pivot_table(
        index="date",
        columns="code",
        values="close",
        aggfunc="last",
        sort=False,
    )
    close_frame.columns.name = None
    return _normalize_wide_close_frame(close_frame)


def _configured_value(name, default):
    """Read runtime settings while remaining safe before ``initialize``."""
    runtime_config = globals().get("g")
    if isinstance(runtime_config, dict) and name in runtime_config:
        return runtime_config[name]
    if runtime_config is not None:
        params = getattr(runtime_config, "params", None)
        if isinstance(params, dict) and name in params:
            return params[name]
        if hasattr(runtime_config, name):
            return getattr(runtime_config, name)

    defaults = globals().get("DEFAULT_PARAMS", {})
    if isinstance(defaults, dict) and name in defaults:
        return defaults[name]
    return default


def get_style_mean_return(context, index_code):
    """Fetch cutoff-safe index closes and return their cross-sectional mean."""
    cutoff = context.previous_date
    try:
        style_window = int(_configured_value("style_window", 20))
        min_samples = int(_configured_value("min_style_samples", 2))
        winsorize = bool(_configured_value("winsorize_returns", False))
    except Exception as exc:
        log.warn("style signal configuration failed for %s: %s", index_code, exc)
        return None

    # Historical constituents remain mandatory for a cutoff-safe signal.  The
    # Task 3 default for use_historical_constituents is therefore honored here
    # without introducing a current-day constituent fallback.
    use_historical = bool(_configured_value("use_historical_constituents", True))
    if not use_historical:
        return None
    try:
        stocks = get_index_stocks(index_code, date=cutoff)
    except Exception as exc:
        log.warn("style constituent fetch failed for %s: %s", index_code, exc)
        return None
    if not stocks:
        return None

    request = {
        "end_date": cutoff,
        "frequency": "daily",
        "fields": ["close"],
        "count": style_window,
    }
    try:
        raw_prices = get_price(stocks, panel=False, **request)
    except TypeError as exc:
        if "panel" not in str(exc):
            log.warn("style price fetch failed for %s: %s", index_code, exc)
            return None
        try:
            raw_prices = get_price(stocks, **request)
        except Exception as fallback_exc:
            log.warn(
                "style price fallback failed for %s: %s",
                index_code,
                fallback_exc,
            )
            return None
    except Exception as exc:
        log.warn("style price fetch failed for %s: %s", index_code, exc)
        return None

    try:
        close_frame = safe_close_frame(raw_prices)
        return safe_mean_return(
            close_frame,
            min_samples=min_samples,
            winsorize=winsorize,
        )
    except Exception as exc:
        log.warn("style price data failed for %s: %s", index_code, exc)
        return None


# -----------------------------------------------------------------------------
# JoinQuant runtime: initialization, candidate selection, and orders.
# -----------------------------------------------------------------------------


def initialize(context):
    """Configure the original-compatible B0 runtime."""
    set_benchmark(MARKET_INDEX)
    set_option("use_real_price", True)
    set_option("avoid_future_data", True)
    log.set_level("order", "error")

    g.params = dict(DEFAULT_PARAMS)
    slippage = float(g.params["slippage"])
    if slippage == 0.0:
        set_slippage(FixedSlippage(0))
    else:
        set_slippage(PriceRelatedSlippage(slippage))
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

    g.hold_list = []
    g.yesterday_HL_list = []
    run_daily(prepare_stock_list, "09:05")
    run_monthly(monthly_adjustment, 1, "09:30")
    run_daily(check_limit_up, "14:00")


def _position_symbols(context):
    return list(context.portfolio.positions.keys())


def _frame_codes(frame):
    if frame is None or getattr(frame, "empty", True):
        return []
    if "code" in frame.columns:
        return list(frame["code"])
    if isinstance(frame.index, pd.MultiIndex):
        if "code" in frame.index.names:
            return list(frame.index.get_level_values("code"))
        if frame.index.nlevels >= 2:
            return list(frame.index.get_level_values(-1))
    if frame.index.name == "code":
        return list(frame.index)
    return []


def _latest_history_prices(stocks):
    if not stocks:
        return {}
    try:
        prices = history(1, unit="1m", field="close", security_list=stocks)
    except Exception as exc:
        log.warn("minute price fetch failed: %s", exc)
        return {}

    result = {}
    for stock in stocks:
        try:
            values = prices[stock]
            value = values.iloc[-1] if hasattr(values, "iloc") else values[-1]
            price = float(value)
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        if np.isfinite(price):
            result[stock] = price
    return result


def _exclude_kcbj_star_chinext(stocks):
    return [
        stock
        for stock in stocks
        if stock[0] not in ("3", "4", "8") and stock[:2] != "68"
    ]


def _filter_st_and_paused(stocks):
    current_data = get_current_data()
    result = []
    for stock in stocks:
        try:
            data = current_data[stock]
            name = data.name or ""
        except Exception:
            continue
        if data.paused or data.is_st or "ST" in name or "*" in name or "退" in name:
            continue
        result.append(stock)
    return result


def _filter_new_stocks(context, stocks):
    cutoff = context.previous_date
    minimum_age = datetime.timedelta(
        days=int(_configured_value("min_listing_days", 375))
    )
    result = []
    for stock in stocks:
        try:
            info = get_security_info(stock)
            start_date = info.start_date
        except Exception:
            continue
        if start_date is not None and cutoff - start_date >= minimum_age:
            result.append(stock)
    return result


def _filter_limit_stocks(context, stocks):
    prices = _latest_history_prices(stocks)
    current_data = get_current_data()
    held = set(_position_symbols(context))
    result = []
    for stock in stocks:
        if stock in held:
            result.append(stock)
            continue
        try:
            price = prices[stock]
            data = current_data[stock]
            high_limit = float(data.high_limit)
            low_limit = float(data.low_limit)
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        if price < high_limit and price > low_limit:
            result.append(stock)
    return result


def _filter_high_price(context, stocks):
    maximum = float(_configured_value("max_price", 10.0))
    prices = _latest_history_prices(stocks)
    held = set(_position_symbols(context))
    return [
        stock
        for stock in stocks
        if stock in held or (stock in prices and prices[stock] < maximum)
    ]


def _full_market_pool(context):
    cutoff = context.previous_date
    securities = get_all_securities("stock", date=cutoff)
    if securities is None or getattr(securities, "empty", True):
        return [], []
    stocks = _exclude_kcbj_star_chinext(list(securities.index))
    choice = _filter_st_and_paused(stocks)
    choice = _filter_new_stocks(context, choice)
    choice = _filter_limit_stocks(context, choice)
    return stocks, choice


def recent_limit_up_stocks(context, stocks, recent_days):
    """Return stocks that touched a closing limit-up in the historical window."""
    result = []
    for stock in stocks:
        try:
            frame = get_price(
                stock,
                end_date=context.previous_date,
                frequency="daily",
                fields=["close", "high_limit"],
                count=recent_days,
                panel=False,
                fill_paused=False,
            )
        except Exception as exc:
            log.warn("recent limit-up fetch failed for %s: %s", stock, exc)
            continue
        if frame is None or getattr(frame, "empty", True):
            continue
        try:
            if (frame["close"] == frame["high_limit"]).any():
                result.append(stock)
        except (KeyError, TypeError):
            continue
    return result


def _exclude_recent_limit_up_holdings(ranked_candidates, holdings, recent_limit_ups):
    """Remove original SMALL black-list holdings while preserving rank order."""
    black_list = set(holdings or ()) & set(recent_limit_ups or ())
    return [
        stock
        for stock in ranked_candidates or ()
        if stock not in black_list
    ]


def small_candidates(context):
    """Rank the original full-market SMALL branch candidates."""
    _, choice = _full_market_pool(context)
    choice = _filter_high_price(context, choice)
    if not choice:
        return []

    cutoff = context.previous_date
    quality_query = query(
        valuation.code,
        indicator.roe,
        indicator.roa,
    ).filter(
        indicator.roe > 0.15,
        indicator.roa > 0.10,
        valuation.code.in_(choice),
    )
    quality = get_fundamentals(quality_query, date=cutoff)
    qualified = _frame_codes(quality)
    if not qualified:
        return []

    rank_query = query(valuation.code).filter(
        valuation.code.in_(qualified)
    ).order_by(valuation.market_cap.asc())
    ranked = _frame_codes(get_fundamentals(rank_query, date=cutoff))
    if not ranked:
        return []

    recent = recent_limit_up_stocks(
        context,
        ranked,
        int(_configured_value("recent_limit_days", 40)),
    )
    return _exclude_recent_limit_up_holdings(
        ranked,
        _position_symbols(context),
        recent,
    )


def big_candidates(context):
    """Rank the original BIG branch, including its B0 universe behavior."""
    stocks, choice = _full_market_pool(context)
    universe = (
        choice
        if bool(_configured_value("big_use_filtered_pool", False))
        else stocks
    )
    if not universe:
        return []

    cutoff = context.previous_date
    big_query = query(valuation.code).filter(
        valuation.code.in_(universe),
        valuation.pe_ratio_lyr.between(0, 30),
        valuation.ps_ratio.between(0, 8),
        valuation.pcf_ratio < 10,
        indicator.eps > 0.3,
        indicator.roe > 0.10,
        indicator.net_profit_margin > 0.10,
        indicator.gross_profit_margin > 0.30,
        indicator.inc_revenue_year_on_year > 0.25,
    ).order_by(valuation.market_cap.desc()).limit(
        int(_configured_value("stock_num", 5))
    )
    return _frame_codes(get_fundamentals(big_query, date=cutoff))


def get_candidates(context, branch):
    if branch == "SMALL":
        return small_candidates(context)
    if branch == "BIG":
        return big_candidates(context)
    return []


def prepare_stock_list(context):
    """Record current holdings and yesterday's closing limit-up holdings."""
    g.hold_list = _position_symbols(context)
    g.yesterday_HL_list = []
    if not g.hold_list:
        return

    try:
        frame = get_price(
            g.hold_list,
            end_date=context.previous_date,
            frequency="daily",
            fields=["close", "high_limit"],
            count=1,
            panel=False,
            fill_paused=False,
        )
    except Exception as exc:
        log.warn("yesterday limit-up fetch failed: %s", exc)
        return
    if frame is None or getattr(frame, "empty", True):
        return

    try:
        hit = frame[frame["close"] == frame["high_limit"]]
        g.yesterday_HL_list = list(dict.fromkeys(_frame_codes(hit)))
    except (KeyError, TypeError):
        return


def _tradeable_now(stock, side):
    try:
        data = get_current_data()[stock]
        price = float(data.last_price)
        high_limit = float(data.high_limit)
        low_limit = float(data.low_limit)
    except Exception:
        return False
    if data.paused or not all(np.isfinite(v) for v in (price, high_limit, low_limit)):
        return False
    if side == "buy":
        return price > 0 and price < high_limit
    return price > low_limit


def safe_order_target_value(stock, value):
    """Submit an order only when its direction is currently tradeable."""
    side = "sell" if value == 0 else "buy"
    if not _tradeable_now(stock, side):
        log.info("skip untradeable %s order for %s", side, stock)
        return False
    try:
        order = order_target_value(stock, value)
    except Exception as exc:
        log.warn("order failed for %s target=%s: %s", stock, value, exc)
        return False
    if order is None:
        log.info("empty order for %s target=%s", stock, value)
        return False
    return bool((getattr(order, "filled", 0) or 0) > 0)


def _market_guard_passes(context):
    """Optional B2 guard; disabled B0 never calls this helper."""
    window = int(_configured_value("market_guard_ma", 60))
    try:
        raw = get_price(
            MARKET_INDEX,
            end_date=context.previous_date,
            frequency="daily",
            fields=["close"],
            count=window,
            panel=False,
        )
    except TypeError as exc:
        if "panel" not in str(exc):
            raise
        raw = get_price(
            MARKET_INDEX,
            end_date=context.previous_date,
            frequency="daily",
            fields=["close"],
            count=window,
        )
    except Exception as exc:
        log.warn("market guard fetch failed: %s", exc)
        return None

    close_frame = safe_close_frame(raw)
    if close_frame is None or len(close_frame) < window:
        return None
    values = pd.to_numeric(close_frame.iloc[:, 0], errors="coerce").dropna()
    if len(values) < window:
        return None
    return bool(values.iloc[-1] >= values.mean())


def monthly_adjustment(context):
    """Select the original style branch and rebalance missing target slots."""
    mean_2000 = get_style_mean_return(context, INDEX_2000)
    mean_500 = get_style_mean_return(context, INDEX_500)
    branch = select_original_branch(
        mean_2000,
        mean_500,
        _configured_value("ratio_threshold", 1.2),
    )
    if branch is None:
        log.warn("style signal unavailable; keep current holdings")
        return

    if bool(_configured_value("market_guard", False)):
        guard = _market_guard_passes(context)
        if guard is not True:
            log.info("market guard blocked this rebalance; keep current holdings")
            return

    ranked = get_candidates(context, branch)
    if not ranked:
        log.warn("%s candidate list unavailable; keep current holdings", branch)
        return

    holdings = _position_symbols(context)
    protected = set(getattr(g, "yesterday_HL_list", []))
    target = merge_target_with_protected_holdings(
        holdings,
        ranked,
        protected,
        int(_configured_value("stock_num", 5)),
    )
    if not target:
        log.warn("%s target list unavailable; keep current holdings", branch)
        return

    for stock in holdings:
        if stock not in target and stock not in protected:
            safe_order_target_value(stock, 0)

    positions = context.portfolio.positions
    missing = [
        stock
        for stock in target
        if stock not in positions
        or getattr(positions[stock], "total_amount", 0) <= 0
    ]
    if not missing:
        return
    cash = getattr(
        context.portfolio,
        "available_cash",
        getattr(context.portfolio, "cash", 0),
    )
    value = cash / len(missing)
    if value <= 0:
        return
    for stock in missing:
        safe_order_target_value(stock, value)


def check_limit_up(context):
    """Sell yesterday's limit-up holding after its intraday limit opens."""
    for stock in list(getattr(g, "yesterday_HL_list", [])):
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
            log.warn("limit-up check failed for %s: %s", stock, exc)
            continue
        if frame is None or getattr(frame, "empty", True):
            continue
        try:
            row = frame.iloc[-1]
            opened = float(row["close"]) < float(row["high_limit"])
        except (KeyError, TypeError, ValueError):
            continue
        if opened:
            safe_order_target_value(stock, 0)


def sell_stocks(context):
    """Original stop-loss/take-profit routine, intentionally unscheduled."""
    for stock, position in list(context.portfolio.positions.items()):
        if position.price >= position.avg_cost * 1.40:
            safe_order_target_value(stock, 0)
        elif position.price < position.avg_cost * 0.95:
            safe_order_target_value(stock, 0)
