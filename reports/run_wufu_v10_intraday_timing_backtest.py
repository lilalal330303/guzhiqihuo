from __future__ import annotations

import html
import json
import sys
from dataclasses import asdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quant_lab.backtest.wufu_intraday import (  # noqa: E402
    WufuIntradayTimingConfig,
    run_wufu_intraday_real_backtest,
)
from quant_lab.data.repository import DuckDBRepository  # noqa: E402
from quant_lab.strategies.wufu_etf_rotation import (  # noqa: E402
    WufuEtfRotationConfig,
    generate_a_share_weak_states_joinquant_style,
    generate_wufu_targets,
)


START_DATE = "2020-01-02"
END_DATE = "2026-07-06"
PREFIX = ROOT / "reports" / "wufu_v10_intraday_timing"


def main() -> None:
    repo = DuckDBRepository(ROOT / "data" / "market.duckdb")
    config = WufuEtfRotationConfig()
    symbols = list(dict.fromkeys(config.etf_pool + config.global_etf_pool + [config.defensive_etf]))
    prices = repo.load_prices_for_symbols(symbols, START_DATE, END_DATE)
    if prices.empty:
        raise RuntimeError("no local ETF daily prices found")
    prices, excluded_symbols = _exclude_symbols_with_price_jumps(prices, max_abs_daily_return=0.25)

    index_prices = repo.load_prices_for_symbols(["000300", "399101", "399006", "000510"], START_DATE, END_DATE)
    weak_states = pd.DataFrame()
    if not index_prices.empty:
        weak_states = generate_a_share_weak_states_joinquant_style(
            index_prices,
            ma_lookback=config.weak_period_ma_lookback,
            max_weak_days=config.max_weak_days,
            signal_lag_days=0,
        )
    targets = generate_wufu_targets(prices, config=config, weak_states=weak_states)
    targets = targets[pd.to_datetime(targets["trade_date"]).between(pd.Timestamp(START_DATE), pd.Timestamp(END_DATE))]

    minute_symbols = _with_exchange_suffixes(symbols)
    minute_bars = repo.load_minute_bars(minute_symbols, START_DATE, END_DATE)

    timing_config = WufuIntradayTimingConfig()
    baseline = run_wufu_intraday_real_backtest(
        prices,
        targets,
        minute_bars,
        WufuIntradayTimingConfig(
            fixed_stop_loss_threshold=0.0,
            trend_slope_threshold=-999.0,
            intraday_entry_weight=1.0,
        ),
    )
    timing = run_wufu_intraday_real_backtest(prices, targets, minute_bars, timing_config)
    baseline_metrics = _metrics(baseline["equity"], baseline["trades"])
    timing_metrics = _metrics(timing["equity"], timing["trades"])
    diff = {
        key: timing_metrics[key] - baseline_metrics[key]
        for key in ["total_return", "annualized_return", "max_drawdown", "final_equity"]
        if key in timing_metrics and key in baseline_metrics
    }

    targets.to_csv(PREFIX.with_name(PREFIX.name + "_targets.csv"), index=False, encoding="utf-8-sig")
    baseline["equity"].to_csv(PREFIX.with_name(PREFIX.name + "_baseline_equity.csv"), index=False, encoding="utf-8-sig")
    timing["equity"].to_csv(PREFIX.with_name(PREFIX.name + "_timing_equity.csv"), index=False, encoding="utf-8-sig")
    timing["trades"].to_csv(PREFIX.with_name(PREFIX.name + "_timing_trades.csv"), index=False, encoding="utf-8-sig")
    baseline["trades"].to_csv(PREFIX.with_name(PREFIX.name + "_baseline_trades.csv"), index=False, encoding="utf-8-sig")

    summary = {
        "start_date": START_DATE,
        "end_date": END_DATE,
        "local_minute_rows": int(len(minute_bars)),
        "local_minute_symbols": int(minute_bars["symbol"].nunique()) if not minute_bars.empty else 0,
        "local_minute_start": ""
        if minute_bars.empty
        else pd.to_datetime(minute_bars["trade_date"]).min().strftime("%Y-%m-%d"),
        "local_minute_end": ""
        if minute_bars.empty
        else pd.to_datetime(minute_bars["trade_date"]).max().strftime("%Y-%m-%d"),
        "method": "real_minute_with_daily_proxy_fallback",
        "params": {
            "wufu": asdict(config),
            "intraday_timing": asdict(timing_config),
        },
        "rows": {
            "prices": int(len(prices)),
            "symbols": int(prices["symbol"].nunique()),
            "targets": int(len(targets)),
            "weak_states": int(len(weak_states)),
            "excluded_symbols": int(len(excluded_symbols)),
        },
        "excluded_symbols": excluded_symbols,
        "baseline_metrics": baseline_metrics,
        "timing_metrics": timing_metrics,
        "diff": diff,
        "timing_trade_breakdown": timing["trades"]["action"].value_counts().to_dict() if not timing["trades"].empty else {},
        "entry_mode_breakdown": timing["trades"].get("entry_mode", pd.Series(dtype=str)).value_counts().to_dict()
        if not timing["trades"].empty
        else {},
        "execution_mode_breakdown": timing["trades"].get("execution_mode", pd.Series(dtype=str)).value_counts().to_dict()
        if not timing["trades"].empty
        else {},
    }
    PREFIX.with_name(PREFIX.name + "_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown = _markdown_report(summary)
    PREFIX.with_name(PREFIX.name + "_report.md").write_text(markdown, encoding="utf-8")
    PREFIX.with_name(PREFIX.name + "_report.html").write_text(_html_report(markdown), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def _metrics(equity: pd.DataFrame, trades: pd.DataFrame) -> dict[str, float | int]:
    values = equity["equity"].astype(float)
    returns = values.pct_change().fillna(0.0)
    drawdown = values / values.cummax() - 1.0
    years = max(
        (pd.to_datetime(equity["trade_date"]).iloc[-1] - pd.to_datetime(equity["trade_date"]).iloc[0]).days / 365.25,
        1e-9,
    )
    pair_returns = _paired_trade_returns(trades)
    return {
        "total_return": float(values.iloc[-1] / values.iloc[0] - 1.0),
        "annualized_return": float((values.iloc[-1] / values.iloc[0]) ** (1.0 / years) - 1.0),
        "max_drawdown": float(drawdown.min()),
        "trade_count": int(len(trades)),
        "buy_count": int((trades["action"] == "buy").sum()) if not trades.empty else 0,
        "sell_count": int((trades["action"] == "sell").sum()) if not trades.empty else 0,
        "stop_loss_count": int((trades["action"] == "stop_loss_sell").sum()) if not trades.empty else 0,
        "win_rate": float("nan")
        if not pair_returns
        else float(sum(1 for value in pair_returns if value > 0) / len(pair_returns)),
        "final_equity": float(values.iloc[-1]),
        "daily_volatility": float(returns.std()),
    }


def _paired_trade_returns(trades: pd.DataFrame) -> list[float]:
    if trades.empty:
        return []
    open_by_symbol: dict[str, tuple[float, int]] = {}
    returns: list[float] = []
    for row in trades.itertuples(index=False):
        action = str(getattr(row, "action"))
        symbol = str(getattr(row, "symbol"))
        price = float(getattr(row, "price"))
        shares = int(getattr(row, "shares"))
        if action == "buy":
            open_by_symbol[symbol] = (price, shares)
        elif action in {"sell", "stop_loss_sell"} and symbol in open_by_symbol:
            entry_price, entry_shares = open_by_symbol.pop(symbol)
            matched_shares = min(entry_shares, shares)
            if matched_shares > 0 and entry_price > 0:
                returns.append(price / entry_price - 1.0)
    return returns


def _exclude_symbols_with_price_jumps(prices: pd.DataFrame, max_abs_daily_return: float) -> tuple[pd.DataFrame, list[str]]:
    rows = prices.sort_values(["symbol", "trade_date"]).copy()
    rows["daily_return"] = rows.groupby("symbol")["close"].pct_change()
    broken = sorted(rows.loc[rows["daily_return"].abs() > max_abs_daily_return, "symbol"].unique().tolist())
    if not broken:
        return prices, []
    return prices[~prices["symbol"].isin(broken)].reset_index(drop=True), broken


def _with_exchange_suffixes(symbols: list[str]) -> list[str]:
    expanded: list[str] = []
    for symbol in symbols:
        text = str(symbol).upper()
        expanded.append(text)
        if "." not in text:
            market = "SH" if text.startswith(("5", "6", "9")) else "SZ"
            expanded.append(f"{text}.{market}")
    return list(dict.fromkeys(expanded))


def _markdown_report(summary: dict[str, object]) -> str:
    b = summary["baseline_metrics"]
    t = summary["timing_metrics"]
    d = summary["diff"]
    return f"""# 五福 ETF V10 日内择时本地真实分钟回测

## 结论

本轮已将 V10 本地回测从“日线 OHLC 代理”切到“真实分钟线优先、缺口日期代理兜底”：

- 本地 `prices_minute` 命中 {summary['local_minute_rows']} 行，覆盖 {summary['local_minute_symbols']} 个标的，区间 {summary['local_minute_start']} 至 {summary['local_minute_end']}。
- 真实分钟逻辑复刻聚宽 V10：13:11、13:40、14:10、14:40 逐次检查 30 根 1 分钟收盘斜率，14:55 强制买入。
- 固定止损改为真实分钟 low/close 触发；没有分钟数据的日期继续使用旧的日线代理，保证全周期可运行。

## 指标对比

| 指标 | 基准：真实 13:11 买入 | V10：真实分钟择时 | 差异 |
|---|---:|---:|---:|
| 最终权益 | {b['final_equity']:.2f} | {t['final_equity']:.2f} | {d['final_equity']:.2f} |
| 总收益 | {b['total_return']:.2%} | {t['total_return']:.2%} | {d['total_return']:.2%} |
| 年化收益 | {b['annualized_return']:.2%} | {t['annualized_return']:.2%} | {d['annualized_return']:.2%} |
| 最大回撤 | {b['max_drawdown']:.2%} | {t['max_drawdown']:.2%} | {d['max_drawdown']:.2%} |
| 交易数 | {b['trade_count']} | {t['trade_count']} | {t['trade_count'] - b['trade_count']} |
| 止损次数 | {b['stop_loss_count']} | {t['stop_loss_count']} | {t['stop_loss_count'] - b['stop_loss_count']} |

## 交易分布

- V10 动作分布：{summary['timing_trade_breakdown']}
- V10 买入模式分布：{summary['entry_mode_breakdown']}
- V10 卖出/止损执行模式：{summary['execution_mode_breakdown']}

## 解读

这版结果已经能验证真实分钟执行链路，但还不是完整分钟历史结论。当前真实分钟主要覆盖最近一段，2020-2026 大多数历史日期仍依赖代理兜底。下一步应继续用 Pandadata/JQData/Tushare Pro 等长周期分钟源补全全池历史，再重新评估择时有效性。
"""


def _html_report(markdown: str) -> str:
    body = []
    for line in markdown.splitlines():
        if line.startswith("# "):
            body.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("## "):
            body.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("|"):
            body.append(f"<pre>{html.escape(line)}</pre>")
        elif line.startswith("- "):
            body.append(f"<p>{html.escape(line)}</p>")
        elif line:
            body.append(f"<p>{html.escape(line)}</p>")
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        "<title>五福 ETF V10 日内择时本地真实分钟回测</title>"
        "<style>body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',sans-serif;"
        "line-height:1.7;max-width:1080px;margin:32px auto;padding:0 24px;color:#1f2933}"
        "pre{background:#f6f8fa;padding:8px;overflow:auto}</style></head><body>"
        + "\n".join(body)
        + "</body></html>"
    )


if __name__ == "__main__":
    main()
