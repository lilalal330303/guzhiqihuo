from __future__ import annotations

import html
import itertools
import json
import math
import sys
import time
from dataclasses import asdict
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quant_lab.backtest.wufu_intraday import (  # noqa: E402
    WufuIntradayTimingConfig,
    run_wufu_intraday_proxy_backtest,
    run_wufu_intraday_real_backtest,
)
from quant_lab.data.repository import DuckDBRepository  # noqa: E402
from quant_lab.strategies.wufu_etf_rotation import (  # noqa: E402
    WufuEtfRotationConfig,
    generate_a_share_weak_states_joinquant_style,
    generate_wufu_targets,
)


SAMPLE_START_DATE = "2026-02-06"
LOAD_START_DATE = "2025-09-01"
REQUESTED_END_DATE = date.today().isoformat()
PREFIX = ROOT / "reports" / "wufu_v9_v10_recent_grid"


def main() -> None:
    started = time.perf_counter()
    print("stage 1/7: load coverage", flush=True)
    repo = DuckDBRepository(ROOT / "data" / "market.duckdb")
    wufu_config = WufuEtfRotationConfig()
    symbols = _configured_symbols(wufu_config)

    coverage = repo.load_price_coverage(symbols, SAMPLE_START_DATE, REQUESTED_END_DATE)
    if coverage.empty:
        raise RuntimeError("no local ETF daily prices found for recent sample")
    end_date = pd.to_datetime(coverage["max_trade_date"]).max().strftime("%Y-%m-%d")

    print(f"stage 2/7: load daily prices to {end_date}", flush=True)
    prices = repo.load_prices_for_symbols(symbols, LOAD_START_DATE, end_date)
    if prices.empty:
        raise RuntimeError("no local ETF daily prices found for target warmup")
    prices, excluded_symbols = _exclude_symbols_with_price_jumps(prices, max_abs_daily_return=0.25)
    active_symbols = [symbol for symbol in symbols if symbol not in set(excluded_symbols)]

    print("stage 3/7: build weak states and targets", flush=True)
    index_prices = repo.load_prices_for_symbols(["000300", "399101", "399006", "000510"], LOAD_START_DATE, end_date)
    weak_states = pd.DataFrame()
    if not index_prices.empty:
        weak_states = generate_a_share_weak_states_joinquant_style(
            index_prices,
            ma_lookback=wufu_config.weak_period_ma_lookback,
            max_weak_days=wufu_config.max_weak_days,
            signal_lag_days=0,
        )

    targets = generate_wufu_targets(prices, config=wufu_config, weak_states=weak_states)
    targets = targets[
        pd.to_datetime(targets["trade_date"]).between(pd.Timestamp(SAMPLE_START_DATE), pd.Timestamp(end_date))
    ].reset_index(drop=True)
    sample_prices = prices[
        pd.to_datetime(prices["trade_date"]).between(pd.Timestamp(SAMPLE_START_DATE), pd.Timestamp(end_date))
    ].reset_index(drop=True)

    print("stage 4/7: load minute bars", flush=True)
    minute_bars = repo.load_minute_bars(_with_exchange_suffixes(active_symbols), SAMPLE_START_DATE, end_date)

    print("stage 5/7: run V9 baseline and V10 default", flush=True)
    v9_config = WufuIntradayTimingConfig(
        fixed_stop_loss_threshold=0.0,
        trend_slope_threshold=-999.0,
        intraday_entry_weight=1.0,
    )
    v9_result = run_wufu_intraday_proxy_backtest(sample_prices, targets, v9_config)
    v9_metrics = _metrics(v9_result["equity"], v9_result["trades"])

    v10_default_config = WufuIntradayTimingConfig()
    v10_default_result = run_wufu_intraday_real_backtest(sample_prices, targets, minute_bars, v10_default_config)
    v10_default_metrics = _metrics(v10_default_result["equity"], v10_default_result["trades"])

    grid_rows: list[dict[str, object]] = []
    print("stage 6/7: run V10 coarse grid", flush=True)
    grid_params = list(
        itertools.product(
            [20, 30, 45],
            [0.001, 0.002],
            [0.0, 0.95, 0.97],
            [1440, 1455],
            [0.998],
        )
    )
    for idx, (lookback, slope, stop_loss, force_minute, cash_buffer) in enumerate(grid_params, start=1):
        cfg = WufuIntradayTimingConfig(
            trend_lookback_minutes=lookback,
            trend_slope_threshold=slope,
            fixed_stop_loss_threshold=stop_loss,
            force_buy_minute=force_minute,
            cash_buffer=cash_buffer,
        )
        result = run_wufu_intraday_real_backtest(sample_prices, targets, minute_bars, cfg)
        metrics = _metrics(result["equity"], result["trades"])
        grid_rows.append(
            {
                "grid_id": idx,
                "trend_lookback_minutes": lookback,
                "trend_slope_threshold": slope,
                "fixed_stop_loss_threshold": stop_loss,
                "force_buy_minute": force_minute,
                "cash_buffer": cash_buffer,
                **metrics,
                "score_return_drawdown": _return_drawdown_score(metrics),
                "entry_mode_breakdown": _value_counts(result["trades"], "entry_mode"),
                "execution_mode_breakdown": _value_counts(result["trades"], "execution_mode"),
            }
        )
        if idx % 6 == 0:
            print(f"grid progress {idx}/{len(grid_params)}", flush=True)

    grid = pd.DataFrame(grid_rows)
    grid = grid.sort_values(
        ["score_return_drawdown", "total_return", "max_drawdown"], ascending=[False, False, False]
    ).reset_index(drop=True)
    grid.insert(0, "rank", range(1, len(grid) + 1))

    best_row = grid.iloc[0].to_dict()
    best_config = WufuIntradayTimingConfig(
        trend_lookback_minutes=int(best_row["trend_lookback_minutes"]),
        trend_slope_threshold=float(best_row["trend_slope_threshold"]),
        fixed_stop_loss_threshold=float(best_row["fixed_stop_loss_threshold"]),
        force_buy_minute=int(best_row["force_buy_minute"]),
        cash_buffer=float(best_row["cash_buffer"]),
    )
    best_result = run_wufu_intraday_real_backtest(sample_prices, targets, minute_bars, best_config)

    print("stage 7/7: write outputs", flush=True)
    outputs = _write_outputs(
        end_date=end_date,
        wufu_config=wufu_config,
        v9_config=v9_config,
        v10_default_config=v10_default_config,
        best_config=best_config,
        v9_result=v9_result,
        v10_default_result=v10_default_result,
        best_result=best_result,
        v9_metrics=v9_metrics,
        v10_default_metrics=v10_default_metrics,
        best_metrics=_metrics(best_result["equity"], best_result["trades"]),
        grid=grid,
        targets=targets,
        minute_bars=minute_bars,
        prices=sample_prices,
        weak_states=weak_states,
        excluded_symbols=excluded_symbols,
        elapsed_seconds=time.perf_counter() - started,
    )
    print(json.dumps(outputs, ensure_ascii=False, indent=2))


def _write_outputs(
    *,
    end_date: str,
    wufu_config: WufuEtfRotationConfig,
    v9_config: WufuIntradayTimingConfig,
    v10_default_config: WufuIntradayTimingConfig,
    best_config: WufuIntradayTimingConfig,
    v9_result: dict[str, pd.DataFrame],
    v10_default_result: dict[str, pd.DataFrame],
    best_result: dict[str, pd.DataFrame],
    v9_metrics: dict[str, float | int | None],
    v10_default_metrics: dict[str, float | int | None],
    best_metrics: dict[str, float | int | None],
    grid: pd.DataFrame,
    targets: pd.DataFrame,
    minute_bars: pd.DataFrame,
    prices: pd.DataFrame,
    weak_states: pd.DataFrame,
    excluded_symbols: list[str],
    elapsed_seconds: float,
) -> dict[str, object]:
    PREFIX.parent.mkdir(parents=True, exist_ok=True)
    paths = {
        "summary_json": PREFIX.with_name(PREFIX.name + "_summary.json"),
        "grid_csv": PREFIX.with_name(PREFIX.name + "_scores.csv"),
        "targets_csv": PREFIX.with_name(PREFIX.name + "_targets.csv"),
        "v9_equity_csv": PREFIX.with_name(PREFIX.name + "_v9_equity.csv"),
        "v9_trades_csv": PREFIX.with_name(PREFIX.name + "_v9_trades.csv"),
        "v10_default_equity_csv": PREFIX.with_name(PREFIX.name + "_v10_default_equity.csv"),
        "v10_default_trades_csv": PREFIX.with_name(PREFIX.name + "_v10_default_trades.csv"),
        "v10_best_equity_csv": PREFIX.with_name(PREFIX.name + "_v10_best_equity.csv"),
        "v10_best_trades_csv": PREFIX.with_name(PREFIX.name + "_v10_best_trades.csv"),
        "report_md": PREFIX.with_name(PREFIX.name + "_report.md"),
        "report_html": PREFIX.with_name(PREFIX.name + "_report.html"),
    }

    grid_for_csv = grid.copy()
    for column in ["entry_mode_breakdown", "execution_mode_breakdown"]:
        grid_for_csv[column] = grid_for_csv[column].map(lambda value: json.dumps(value, ensure_ascii=False))
    grid_for_csv.to_csv(paths["grid_csv"], index=False, encoding="utf-8-sig")
    targets.to_csv(paths["targets_csv"], index=False, encoding="utf-8-sig")
    v9_result["equity"].to_csv(paths["v9_equity_csv"], index=False, encoding="utf-8-sig")
    v9_result["trades"].to_csv(paths["v9_trades_csv"], index=False, encoding="utf-8-sig")
    v10_default_result["equity"].to_csv(paths["v10_default_equity_csv"], index=False, encoding="utf-8-sig")
    v10_default_result["trades"].to_csv(paths["v10_default_trades_csv"], index=False, encoding="utf-8-sig")
    best_result["equity"].to_csv(paths["v10_best_equity_csv"], index=False, encoding="utf-8-sig")
    best_result["trades"].to_csv(paths["v10_best_trades_csv"], index=False, encoding="utf-8-sig")

    summary = {
        "sample_start_date": SAMPLE_START_DATE,
        "sample_end_date": end_date,
        "requested_end_date": REQUESTED_END_DATE,
        "method": {
            "v9_baseline": "daily close proxy, no intraday timing, no fixed stop loss",
            "v10_default": "real minute intraday timing with daily proxy fallback",
            "v10_grid": "same target generation, grid search on intraday execution parameters",
        },
        "data": {
            "daily_price_rows": int(len(prices)),
            "daily_symbols": int(prices["symbol"].nunique()) if not prices.empty else 0,
            "minute_rows": int(len(minute_bars)),
            "minute_symbols": int(minute_bars["symbol"].nunique()) if not minute_bars.empty else 0,
            "minute_start": ""
            if minute_bars.empty
            else pd.to_datetime(minute_bars["trade_date"]).min().strftime("%Y-%m-%d"),
            "minute_end": ""
            if minute_bars.empty
            else pd.to_datetime(minute_bars["trade_date"]).max().strftime("%Y-%m-%d"),
            "target_rows": int(len(targets)),
            "weak_state_rows": int(len(weak_states)),
            "excluded_symbols": excluded_symbols,
        },
        "params": {
            "wufu": asdict(wufu_config),
            "v9_baseline": asdict(v9_config),
            "v10_default": asdict(v10_default_config),
            "v10_best_grid": asdict(best_config),
        },
        "metrics": {
            "v9_baseline": v9_metrics,
            "v10_default": v10_default_metrics,
            "v10_best_grid": best_metrics,
            "v10_default_minus_v9": _metric_diff(v10_default_metrics, v9_metrics),
            "v10_best_minus_v9": _metric_diff(best_metrics, v9_metrics),
        },
        "trade_breakdown": {
            "v9": {
                "actions": _value_counts(v9_result["trades"], "action"),
                "entry_modes": _value_counts(v9_result["trades"], "entry_mode"),
            },
            "v10_default": {
                "actions": _value_counts(v10_default_result["trades"], "action"),
                "entry_modes": _value_counts(v10_default_result["trades"], "entry_mode"),
                "execution_modes": _value_counts(v10_default_result["trades"], "execution_mode"),
            },
            "v10_best_grid": {
                "actions": _value_counts(best_result["trades"], "action"),
                "entry_modes": _value_counts(best_result["trades"], "entry_mode"),
                "execution_modes": _value_counts(best_result["trades"], "execution_mode"),
            },
        },
        "grid": {
            "rows": int(len(grid)),
            "rank_rule": "score_return_drawdown desc, then total_return desc, then max_drawdown desc",
            "top10": _records(grid.head(10)),
        },
        "elapsed_seconds": float(elapsed_seconds),
    }
    paths["summary_json"].write_text(json.dumps(_jsonable(summary), ensure_ascii=False, indent=2), encoding="utf-8")
    markdown = _markdown_report(summary)
    paths["report_md"].write_text(markdown, encoding="utf-8")
    paths["report_html"].write_text(_html_report(markdown), encoding="utf-8")
    return {"summary": _jsonable(summary), "outputs": {key: str(value) for key, value in paths.items()}}


def _metrics(equity: pd.DataFrame, trades: pd.DataFrame) -> dict[str, float | int | None]:
    if equity.empty:
        return {
            "total_return": None,
            "annualized_return": None,
            "max_drawdown": None,
            "trade_count": int(len(trades)),
            "buy_count": 0,
            "sell_count": 0,
            "stop_loss_count": 0,
            "win_rate": None,
            "final_equity": None,
            "daily_volatility": None,
        }
    values = equity["equity"].astype(float)
    returns = values.pct_change().fillna(0.0)
    drawdown = values / values.cummax() - 1.0
    first_date = pd.to_datetime(equity["trade_date"]).iloc[0]
    last_date = pd.to_datetime(equity["trade_date"]).iloc[-1]
    years = max((last_date - first_date).days / 365.25, 1e-9)
    pair_returns = _paired_trade_returns(trades)
    return {
        "total_return": float(values.iloc[-1] / values.iloc[0] - 1.0),
        "annualized_return": float((values.iloc[-1] / values.iloc[0]) ** (1.0 / years) - 1.0),
        "max_drawdown": float(drawdown.min()),
        "trade_count": int(len(trades)),
        "buy_count": int((trades["action"] == "buy").sum()) if not trades.empty else 0,
        "sell_count": int((trades["action"] == "sell").sum()) if not trades.empty else 0,
        "stop_loss_count": int((trades["action"] == "stop_loss_sell").sum()) if not trades.empty else 0,
        "win_rate": None if not pair_returns else float(sum(1 for value in pair_returns if value > 0) / len(pair_returns)),
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


def _return_drawdown_score(metrics: dict[str, float | int | None]) -> float:
    total_return = float(metrics.get("total_return") or 0.0)
    max_drawdown = float(metrics.get("max_drawdown") or 0.0)
    return total_return / max(abs(max_drawdown), 0.01)


def _metric_diff(left: dict[str, float | int | None], right: dict[str, float | int | None]) -> dict[str, float | None]:
    keys = ["total_return", "annualized_return", "max_drawdown", "final_equity", "trade_count", "stop_loss_count"]
    diff: dict[str, float | None] = {}
    for key in keys:
        left_value = left.get(key)
        right_value = right.get(key)
        diff[key] = None if left_value is None or right_value is None else float(left_value) - float(right_value)
    return diff


def _exclude_symbols_with_price_jumps(prices: pd.DataFrame, max_abs_daily_return: float) -> tuple[pd.DataFrame, list[str]]:
    rows = prices.sort_values(["symbol", "trade_date"]).copy()
    rows["daily_return"] = rows.groupby("symbol")["close"].pct_change()
    broken = sorted(rows.loc[rows["daily_return"].abs() > max_abs_daily_return, "symbol"].unique().tolist())
    if not broken:
        return prices.reset_index(drop=True), []
    return prices[~prices["symbol"].isin(broken)].reset_index(drop=True), broken


def _configured_symbols(config: WufuEtfRotationConfig) -> list[str]:
    symbols = list(config.etf_pool) + list(config.global_etf_pool)
    if config.defensive_etf:
        symbols.append(config.defensive_etf)
    return list(dict.fromkeys(str(symbol) for symbol in symbols if symbol))


def _with_exchange_suffixes(symbols: list[str]) -> list[str]:
    expanded: list[str] = []
    for symbol in symbols:
        text = str(symbol).upper()
        expanded.append(text)
        if "." not in text:
            market = "SH" if text.startswith(("5", "6", "9")) else "SZ"
            expanded.append(f"{text}.{market}")
    return list(dict.fromkeys(expanded))


def _value_counts(frame: pd.DataFrame, column: str) -> dict[str, int]:
    if frame.empty or column not in frame.columns:
        return {}
    return {str(key): int(value) for key, value in frame[column].dropna().value_counts().items()}


def _records(frame: pd.DataFrame) -> list[dict[str, object]]:
    simple_columns = [
        "rank",
        "grid_id",
        "trend_lookback_minutes",
        "trend_slope_threshold",
        "fixed_stop_loss_threshold",
        "force_buy_minute",
        "cash_buffer",
        "total_return",
        "annualized_return",
        "max_drawdown",
        "final_equity",
        "trade_count",
        "stop_loss_count",
        "win_rate",
        "score_return_drawdown",
        "entry_mode_breakdown",
        "execution_mode_breakdown",
    ]
    return _jsonable(frame[simple_columns].to_dict(orient="records"))


def _jsonable(value):
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if hasattr(value, "item"):
        return _jsonable(value.item())
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _markdown_report(summary: dict[str, object]) -> str:
    metrics = summary["metrics"]
    data = summary["data"]
    top10 = summary["grid"]["top10"]
    return f"""# 五福 ETF V9/V10 近期样本回测与参数网格验证

## 样本与数据

- 样本期：{summary['sample_start_date']} 至 {summary['sample_end_date']}；用户要求“到现在”，但本地 ETF 日线最新到 {summary['sample_end_date']}，所以本轮以日线可估值日期为准。
- 日线数据：{data['daily_price_rows']} 行，{data['daily_symbols']} 个标的；分钟数据：{data['minute_rows']} 行，{data['minute_symbols']} 个标的，覆盖 {data['minute_start']} 至 {data['minute_end']}。
- 目标生成：V9 与 V10 共用同一套五福选标、弱市状态和 T+1 执行规则；本轮只比较执行层和日内择时参数。
- 剔除异常复权断点标的：{data['excluded_symbols'] if data['excluded_symbols'] else '无'}。

## 核心结论

V9 基线是日线收盘代理、无日内择时、无固定止损；V10 默认版切换为真实分钟线择时，缺口用日线代理兜底。短样本内，V10 的收益、回撤和交易次数变化主要来自三个执行参数：趋势斜率触发、固定止损、强制买入时间。

{_metric_table(metrics)}

## V10 网格搜索设计

- `trend_lookback_minutes`：20 / 30 / 45，用来验证趋势斜率观察窗口。
- `trend_slope_threshold`：0.001 / 0.002，用来控制趋势确认强弱。
- `fixed_stop_loss_threshold`：0 / 0.95 / 0.97，其中 0 代表关闭固定止损。
- `force_buy_minute`：14:40 / 14:55，用来比较更早强制进场和尾盘进场。
- `cash_buffer`：0.998，本轮先固定现金缓冲，下一轮再做执行层敏感性测试。

排序规则：先按 `总收益 / max(|最大回撤|, 1%)`，再按总收益和最大回撤排序。它不是最终实盘最优，只是本轮小样本参数筛选器。

## 网格 Top10

{_top_table(top10)}

## 分析总结

1. V9 与 V10 的差异已经不再是选股差异，本轮固定了同一套目标序列；差异集中在买入价格、止损触发、卖出价格和资金取整。
2. 如果 Top10 集中在关闭止损或更宽止损，说明近期 ETF 日内波动里“止损卖飞”成本高；如果集中在 0.95 或 0.97，则说明风控对这段行情有效。
3. `force_buy_minute` 的优劣反映了尾盘确认和更早入场之间的取舍；如果 14:40 占优，后续可考虑把同花顺脚本也改成更少轮询、更快执行的 14:40 强制买入版。
4. 这段样本只有 2026-02-06 以来的真实分钟线，适合验证执行逻辑和参数方向，不适合直接宣布长期最优参数。

## 下一轮优化路径

- 扩大分钟线历史后，按滚动窗口做 walk-forward：例如 2026-02 至 2026-04 训练、2026-05 至 2026-07 验证。
- 把最优参数限制为稳定区域，而不是单个最高收益点；优先选择回撤、交易次数和收益都不极端的组合。
- 对同花顺版本做速度优化时，优先减少盘中检查次数：保留 13:11、14:40、强制买入三个关键点，再和完整 V10 比较损失。
- 把网格结果同步回平台脚本前，需要用同一批分钟日志验证订单触发时间、100 份取整和资金不足记录是否一致。
"""


def _metric_table(metrics: dict[str, object]) -> str:
    rows = [
        ("最终权益", "final_equity", ".2f"),
        ("总收益", "total_return", ".2%"),
        ("年化收益", "annualized_return", ".2%"),
        ("最大回撤", "max_drawdown", ".2%"),
        ("交易数", "trade_count", "d"),
        ("止损次数", "stop_loss_count", "d"),
        ("胜率", "win_rate", ".2%"),
    ]
    versions = [
        ("V9 基线", metrics["v9_baseline"]),
        ("V10 默认", metrics["v10_default"]),
        ("V10 网格最优", metrics["v10_best_grid"]),
    ]
    lines = ["| 指标 | V9 基线 | V10 默认 | V10 网格最优 |", "|---|---:|---:|---:|"]
    for label, key, fmt in rows:
        values = []
        for _, item in versions:
            value = item.get(key)
            if value is None:
                values.append("-")
            elif fmt == "d":
                values.append(str(int(value)))
            else:
                values.append(format(float(value), fmt))
        lines.append(f"| {label} | {values[0]} | {values[1]} | {values[2]} |")
    return "\n".join(lines)


def _top_table(rows: list[dict[str, object]]) -> str:
    lines = [
        "| 排名 | 窗口 | 斜率阈值 | 止损 | 强制买入 | 现金缓冲 | 总收益 | 最大回撤 | 交易数 | 止损数 |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| {rank} | {trend_lookback_minutes} | {trend_slope_threshold:.4f} | {fixed_stop_loss_threshold:.2f} | "
            "{force_buy_minute} | {cash_buffer:.3f} | {total_return:.2%} | {max_drawdown:.2%} | "
            "{trade_count} | {stop_loss_count} |".format(**row)
        )
    return "\n".join(lines)


def _html_report(markdown: str) -> str:
    body: list[str] = []
    in_table = False
    for line in markdown.splitlines():
        if line.startswith("|"):
            if not in_table:
                body.append("<pre>")
                in_table = True
            body.append(html.escape(line))
            continue
        if in_table:
            body.append("</pre>")
            in_table = False
        if line.startswith("# "):
            body.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("## "):
            body.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("- "):
            body.append(f"<p>{html.escape(line)}</p>")
        elif line and line[0].isdigit() and ". " in line[:4]:
            body.append(f"<p>{html.escape(line)}</p>")
        elif line:
            body.append(f"<p>{html.escape(line)}</p>")
    if in_table:
        body.append("</pre>")
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        "<title>五福 ETF V9/V10 近期样本回测与参数网格验证</title>"
        "<style>body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',sans-serif;"
        "line-height:1.75;max-width:1180px;margin:32px auto;padding:0 24px;color:#1f2937}"
        "h1{font-size:30px}h2{margin-top:32px;font-size:22px}"
        "pre{background:#f6f8fa;padding:12px;overflow:auto;border-radius:6px}"
        "p{margin:10px 0}</style></head><body>"
        + "\n".join(body)
        + "</body></html>"
    )


if __name__ == "__main__":
    main()
