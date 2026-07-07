# -*- coding: utf-8 -*-
"""
V69 股指期货固定版本地方案说明脚本。

用途：
- 固定当前股指期货策略的本地研究口径。
- 输出整体思路、交易模块、核心参数和十段结果摘要。
"""

from __future__ import annotations

from pprint import pprint


VERSION = "V69 股指期货固定版"

UNIVERSE = {
    "products": ["IF", "IH", "IC", "IM"],
    "frequency": "1m",
    "initial_cash": 1_000_000,
    "instrument_type": "index_futures",
}

STRATEGY_IDEA = {
    "core": "只交易趋势回踩和开盘区间突破；箱体与VWAP偏离只作为环境观察。",
    "lock_rule": "当天新开仓退出时允许反向开仓形成有效对锁。",
    "old_chip_rule": "昨日对锁旧仓可平单边作为开仓筹码，但必须方向匹配。",
    "today_position_guard": "如果同品种同方向今仓会挡住平昨，则不复用旧筹码，改为新开。",
}

MODULES = {
    "TREND_PULLBACK": {
        "name": "趋势回踩",
        "direction": "顺主趋势，等待价格回踩到EMA/VWAP附近后入场。",
        "entry_quality": "ADX达到趋势阈值，回踩幅度不过深，方向和品种强弱一致。",
        "take_profit": "1.20R",
    },
    "OPENING_RANGE_BREAKOUT": {
        "name": "开盘区间突破",
        "direction": "09:45后观察开盘区间，向上突破做多，向下突破做空。",
        "entry_quality": "开盘区间宽度达到最低ATR要求，突破方向与即时趋势不冲突。",
        "take_profit": "1.00R",
    },
}

PARAMETERS = {
    "first_open_hhmm": 945,
    "last_open_hhmm": 1435,
    "force_lock_hhmm": 1455,
    "open_range_end_hhmm": 945,
    "max_active_lots": 4,
    "max_same_direction_lots": 2,
    "max_lock_pairs_per_product": 4,
    "max_daily_open": 80,
    "min_available_cash_ratio": 0.05,
    "min_action_interval_min": 1,
    "cross_product_cool_min": 6,
    "atr_n": 14,
    "ema_n": 20,
    "adx_n": 14,
    "trend_adx_min": 18,
    "open_range_min_atr": 0.80,
    "pullback_buffer_atr": 0.20,
    "stop_floor_ratio": 0.35,
    "stop_atr_mult": 1.00,
    "trend_tp_r": 1.20,
    "opening_tp_r": 1.00,
    "multiplier": {"IF": 300, "IH": 300, "IC": 200, "IM": 200},
    "risk_points": {"IF": 66.7, "IH": 66.7, "IC": 100.0, "IM": 100.0},
}

BACKTEST_SUMMARY = {
    "candidate_signals": 14333,
    "closed_trades": 7331,
    "net_profit": 2048148.84,
    "gross_pnl": 2487229.30,
    "trade_fee": 412026.81,
    "release_fee": 27053.69,
    "total_fee": 439080.50,
    "win_rate_pct": 50.8389,
    "avoided_close_today": 3879,
    "chip_reused": 3366,
    "direct_close": 86,
    "old_chip_close_yesterday": 3366,
}

MODULE_SUMMARY = {
    "OPENING_RANGE_BREAKOUT": {
        "name": "开盘区间突破",
        "trades": 2816,
        "net_pnl": 482916.30,
        "gross_pnl": 637118.57,
        "fee": 154202.31,
        "win_rate_pct": 50.9588,
    },
    "TREND_PULLBACK": {
        "name": "趋势回踩",
        "trades": 4515,
        "net_pnl": 1592286.23,
        "gross_pnl": 1850110.73,
        "fee": 257824.50,
        "win_rate_pct": 50.7641,
    },
}


def describe() -> dict:
    return {
        "version": VERSION,
        "universe": UNIVERSE,
        "strategy_idea": STRATEGY_IDEA,
        "modules": MODULES,
        "parameters": PARAMETERS,
        "backtest_summary": BACKTEST_SUMMARY,
        "module_summary": MODULE_SUMMARY,
    }


if __name__ == "__main__":
    pprint(describe(), sort_dicts=False)
