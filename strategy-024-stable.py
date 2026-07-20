# 克隆自聚宽文章：https://www.joinquant.com/post/47566
# 标题：大容量低回撤价值投资-排除小市值因子
# 作者：Ahfu
#
# 本版只做轻缓冲执行迭代：保持原始四因子、MinMax评分、40只持仓、季度调仓、
# 涨停保护、零滑点和原始交易成本不变。补位范围由前60名收窄为前50名。

from jqdata import *
from jqfactor import get_factor_values
from jqlib.technical_analysis import *
import numpy as np
import pandas as pd
import statsmodels.api as sm
import datetime as dt
from sklearn.preprocessing import MinMaxScaler


EXECUTION_BUFFER_NUM = 50
STAR_MARKET_PREFIX = '688'
CAPACITY_DIAGNOSTIC_ENABLED = True
CAPACITY_LOOKBACK = 20
CAPACITY_PARTICIPATION_LIMIT = 0.10


def _quote_field(quote, field, default=None):
    if quote is None:
        return default
    if isinstance(quote, dict):
        return quote.get(field, default)
    return getattr(quote, field, default)


def preflight_order(security, value, quote):
    """在调用聚宽下单接口前检查明显不可执行的开仓。"""
    if quote is None or bool(_quote_field(quote, 'paused', False)):
        return 'paused', 0
    try:
        price = float(_quote_field(quote, 'last_price', 0) or 0)
    except (TypeError, ValueError):
        price = 0
    if price <= 0 or value <= 0:
        return 'missing_price', 0
    if str(security).startswith(STAR_MARKET_PREFIX):
        return 'star_market_order_protection', 0
    amount = int(float(value) / price / 100.0) * 100
    if amount < 100:
        return 'lot_less_100', 0
    return 'ok', amount


def execution_candidates(ranked, target_num, buffer_num):
    limit = min(len(ranked), max(int(target_num), int(buffer_num)))
    return list(ranked[:limit])


def new_rebalance_audit(target_count, before_count):
    return {
        'target_count': int(target_count),
        'before_count': int(before_count),
        'actual_count': int(before_count),
        'attempts': 0,
        'filled': 0,
        'paused': 0,
        'missing_price': 0,
        'lot_less_100': 0,
        'star_market_order_protection': 0,
        'other_failed': 0,
        'fallbacks': [],
        'fallback_ranks': [],
        'cash_ratio': None,
    }


def rank_capacity_rows(rows):
    return sorted(rows, key=lambda row: float(row[1]), reverse=True)


def _record_preflight_failure(audit, reason):
    if reason in audit:
        audit[reason] += 1
    else:
        audit['other_failed'] += 1


def _live_position_amount(context, security):
    try:
        position = context.portfolio.positions[security]
    except Exception:
        return 0
    return getattr(position, 'total_amount', 0) or 0


def _live_position_count(context):
    count = 0
    for position in list(context.portfolio.positions.values()):
        if (getattr(position, 'total_amount', 0) or 0) > 0:
            count += 1
    return count


def _get_quote(current_data, security):
    try:
        return current_data[security]
    except Exception:
        return None


# 初始化函数
def initialize(context):
    set_benchmark('000905.XSHG')
    set_option('use_real_price', True)
    set_option("avoid_future_data", True)
    set_slippage(FixedSlippage(0))
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001, open_commission=0.00012,
                             close_commission=0.00012, close_today_commission=0,
                             min_commission=5), type='stock')
    log.set_level('order', 'error')
    log.set_level('system', 'error')
    g.stock_num = 40
    g.limit_up_list = []
    g.hold_list = []
    g.history_hold_list = []
    g.not_buy_again_list = []
    g.limit_days = 20
    g.target_list = []
    g.execution_candidate_list = []
    g.capacity_stats = {}
    g.rebalance_audit = {}
    run_daily(prepare_stock_list, time='9:05', reference_security='000300.XSHG')
    run_monthly(adjust_position, 1, time='9:30', reference_security='000300.XSHG')
    run_daily(check_limit_up, time='14:00', reference_security='000300.XSHG')
    run_monthly(print_position_info, 1, time='15:10', reference_security='000300.XSHG')


# 1-2 选股模块：原始四因子和原始评分公式保持不变
def get_stock_list(context):
    yesterday = str(context.previous_date)
    end_date = context.previous_date
    last_days = end_date - timedelta(days=300)
    securities_df = get_all_securities(date=last_days)
    initial_list = securities_df.index.tolist()

    factor_values = get_factor_values(initial_list, [
        'roic_ttm',
        'gross_income_ratio',
        'sales_to_price_ratio',
        'Variance120',
    ], end_date=yesterday, count=1)
    df = pd.DataFrame(index=initial_list, columns=factor_values.keys())
    df['roic_ttm'] = list(factor_values['roic_ttm'].T.iloc[:, 0])
    df['gross_income_ratio'] = list(factor_values['gross_income_ratio'].T.iloc[:, 0])
    df['sales_to_price_ratio'] = list(1 / factor_values['sales_to_price_ratio'].T.iloc[:, 0])
    df['Variance120'] = list(factor_values['Variance120'].T.iloc[:, 0])
    df = df.dropna()

    scaler = MinMaxScaler()
    df2 = pd.DataFrame(scaler.fit_transform(df), columns=df.columns, index=df.index)
    df2['total_score'] = df2['roic_ttm'] + df2['gross_income_ratio'] - df2['sales_to_price_ratio'] - df2['Variance120']
    df2 = df2.sort_values(by=['total_score'], ascending=False)
    ms_list = list(df2.index)
    return ms_list


# 1-3 准备股票池
def prepare_stock_list(context):
    g.hold_list = []
    for position in list(context.portfolio.positions.values()):
        stock = position.security
        g.hold_list.append(stock)

    g.history_hold_list.append(g.hold_list)
    if len(g.history_hold_list) >= g.limit_days:
        g.history_hold_list = g.history_hold_list[-g.limit_days:]
    temp_set = set()
    for hold_list in g.history_hold_list:
        for stock in hold_list:
            temp_set.add(stock)
    g.not_buy_again_list = list(temp_set)

    if g.hold_list != []:
        df = get_price(g.hold_list, end_date=context.previous_date, frequency='daily',
                       fields=['close', 'high_limit'], count=1, panel=False,
                       fill_paused=False)
        df = df[df['close'] == df['high_limit']]
        g.high_limit_list = list(df.code)
    else:
        g.high_limit_list = []


def diagnose_order_capacity(context, stocks, order_value):
    """只记录逐股票成交额参与率，不改变任何订单。"""
    if not CAPACITY_DIAGNOSTIC_ENABLED or not stocks or order_value <= 0:
        return
    try:
        history = get_price(
            stocks,
            end_date=context.previous_date,
            frequency='daily',
            fields=['money'],
            count=CAPACITY_LOOKBACK,
            panel=False,
            fill_paused=True,
        )
    except Exception as exc:
        log.info("容量诊断数据不可用：%s" % exc)
        return
    if history is None or history.empty or 'code' not in history.columns:
        return

    rows = []
    missing_codes = []
    for stock in stocks:
        stock_rows = history[history['code'] == stock]
        if stock_rows.empty or 'money' not in stock_rows.columns:
            missing_codes.append(stock)
            continue
        average_money = pd.to_numeric(stock_rows['money'], errors='coerce').dropna().mean()
        if pd.notna(average_money) and average_money > 0:
            participation = float(order_value) / float(average_money)
            rows.append((stock, participation, float(average_money)))
        else:
            missing_codes.append(stock)

    if not rows:
        return

    ranked_rows = rank_capacity_rows(rows)
    participation = [row[1] for row in rows]
    g.capacity_stats = {
        'order_value': float(order_value),
        'median_participation': float(np.median(participation)),
        'max_participation': float(np.max(participation)),
        'over_limit_count': int(sum(x > CAPACITY_PARTICIPATION_LIMIT for x in participation)),
        'sample_count': len(rows),
        'missing_count': len(missing_codes),
        'missing_codes': missing_codes[:10],
        'top5': ranked_rows[:5],
    }
    log.info("容量诊断：%s" % g.capacity_stats)


# 1-5 整体调整持仓
def adjust_position(context):
    if context.previous_date.month not in [1, 4, 7, 10]:
        return

    ranked_list = get_stock_list(context)
    g.target_list = ranked_list[:min(g.stock_num, len(ranked_list))]
    g.execution_candidate_list = execution_candidates(
        ranked_list, len(g.target_list), EXECUTION_BUFFER_NUM
    )

    for stock in g.hold_list:
        if (stock not in g.target_list) and (stock not in g.high_limit_list):
            log.info("卖出[%s]" % stock)
            position = context.portfolio.positions[stock]
            close_position(position)
        else:
            log.info("已持有[%s]" % stock)

    before_count = _live_position_count(context)
    target_num = len(g.target_list)
    audit = new_rebalance_audit(target_num, before_count)
    g.rebalance_audit = audit

    if target_num > before_count:
        value = context.portfolio.cash / (target_num - before_count)
        diagnose_order_capacity(context, g.execution_candidate_list, value)
        current_data = get_current_data()

        for candidate_rank, stock in enumerate(g.execution_candidate_list, start=1):
            if _live_position_amount(context, stock) > 0:
                continue

            reason, amount = preflight_order(stock, value, _get_quote(current_data, stock))
            if reason != 'ok':
                _record_preflight_failure(audit, reason)
                log.info("跳过候选[%s]，原因：%s" % (stock, reason))
                continue

            audit['attempts'] += 1
            is_fallback = stock not in g.target_list
            if open_position(stock, value):
                audit['filled'] += 1
                if is_fallback:
                    audit['fallbacks'].append(stock)
                    audit['fallback_ranks'].append(candidate_rank)
                if _live_position_count(context) >= target_num:
                    break
            else:
                audit['other_failed'] += 1

    audit['actual_count'] = _live_position_count(context)
    total_value = getattr(context.portfolio, 'total_value', 0) or 0
    if total_value > 0:
        audit['cash_ratio'] = float(context.portfolio.cash) / float(total_value)
    log.info("调仓审计：%s" % audit)


# 1-6 调整昨日涨停股票
def check_limit_up(context):
    now_time = context.current_dt
    if g.high_limit_list != []:
        for stock in g.high_limit_list:
            current_data = get_price(
                stock,
                end_date=now_time,
                frequency='1m',
                fields=['close', 'high_limit'],
                skip_paused=False,
                fq='pre',
                count=1,
                panel=False,
                fill_paused=True,
            )
            if current_data.iloc[0, 0] < current_data.iloc[0, 1]:
                log.info("[%s]涨停打开，卖出" % stock)
                position = context.portfolio.positions[stock]
                close_position(position)
            else:
                log.info("[%s]涨停，继续持有" % stock)


# 3-1 交易模块-自定义下单
def order_target_value_(security, value):
    if value == 0:
        log.debug("Selling out %s" % security)
    else:
        log.debug("Order %s to value %f" % (security, value))
    return order_target_value(security, value)


# 3-2 交易模块-开仓
def open_position(security, value):
    order = order_target_value_(security, value)
    if order != None and order.filled > 0:
        return True
    return False


# 3-3 交易模块-平仓
def close_position(position):
    security = position.security
    order = order_target_value_(security, 0)
    if order != None:
        if order.status == OrderStatus.held and order.filled == order.amount:
            return True
    return False


# 4-1 打印每日持仓信息
def print_position_info(context):
    c = get_current_data()
    positions_dict = context.portfolio.positions
    for position in list(positions_dict.values()):
        log.info("当前持仓：{0}:{1}, 市值：{2}, 盈利：{3}%, 建仓时间：{4}".format(c[position.security].name, position.security[:6], round(position.value, 0), round((position.value-(position.avg_cost*position.total_amount))/(position.avg_cost*position.total_amount)*100, 1), position.init_time))
    log.info('#########################################################################################\n\n')
