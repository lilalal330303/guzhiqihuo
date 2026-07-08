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
PREFIX = ROOT / "reports" / "wufu_intraday_morning_time_grid"


STOP_WINDOWS = {
    "full": ((941, 1028), (1041, 1129), (1301, 1456)),
    "afternoon": ((1301, 1456),),
    "post_1000": ((1001, 1129), (1301, 1456)),
    "post_1030": ((1031, 1129), (1301, 1456)),
}
TREND_CHECK_SETS = {
    "1000_1030_1100": (1000, 1030, 1100),
    "1030_1100_1340": (1030, 1100, 1340),
    "1100_1340_1410": (1100, 1340, 1410),
    "1340_1410_1430": (1340, 1410, 1430),
}
INITIAL_ENTRY_MINUTES = {
    "none": None,
    "0945": 945,
    "1000": 1000,
    "1030": 1030,
    "1100": 1100,
    "1320": 1320,
}
FORCE_BUY_MINUTES = [1340, 1440, 1455]


def main() -> None:
    started = time.perf_counter()
    print("stage 1/6: load data coverage", flush=True)
    repo = DuckDBRepository(ROOT / "data" / "market.duckdb")
    wufu_config = WufuEtfRotationConfig()
    symbols = _configured_symbols(wufu_config)

    coverage = repo.load_price_coverage(symbols, SAMPLE_START_DATE, REQUESTED_END_DATE)
    if coverage.empty:
        raise RuntimeError("no local ETF daily prices found for recent sample")
    end_date = pd.to_datetime(coverage["max_trade_date"]).max().strftime("%Y-%m-%d")

    print(f"stage 2/6: load prices to {end_date}", flush=True)
    prices = repo.load_prices_for_symbols(symbols, LOAD_START_DATE, end_date)
    if prices.empty:
        raise RuntimeError("no local ETF daily prices found for target warmup")
    prices, excluded_symbols = _exclude_symbols_with_price_jumps(prices, max_abs_daily_return=0.25)
    active_symbols = [symbol for symbol in symbols if symbol not in set(excluded_symbols)]

    print("stage 3/6: build targets", flush=True)
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

    print("stage 4/6: load minute bars", flush=True)
    minute_bars = repo.load_minute_bars(_with_exchange_suffixes(active_symbols), SAMPLE_START_DATE, end_date)

    print("stage 5/6: run time grid", flush=True)
    grid_rows: list[dict[str, object]] = []
    grid_params = list(
        itertools.product(
            INITIAL_ENTRY_MINUTES.items(),
            STOP_WINDOWS.items(),
            TREND_CHECK_SETS.items(),
            FORCE_BUY_MINUTES,
        )
    )
    for idx, ((entry_label, entry_minute), (stop_label, stop_windows), (trend_label, trend_checks), force_minute) in enumerate(
        grid_params, start=1
    ):
        cfg = WufuIntradayTimingConfig(
            trend_lookback_minutes=30,
            trend_slope_threshold=0.002,
            fixed_stop_loss_threshold=0.97,
            initial_entry_minute=entry_minute,
            trend_check_minutes=trend_checks,
            force_buy_minute=force_minute,
            stop_loss_windows=stop_windows,
            cash_buffer=0.998,
        )
        result = run_wufu_intraday_real_backtest(sample_prices, targets, minute_bars, cfg)
        metrics = _metrics(result["equity"], result["trades"])
        grid_rows.append(
            {
                "grid_id": idx,
                "initial_entry_label": entry_label,
                "initial_entry_minute": entry_minute,
                "stop_loss_profile": stop_label,
                "stop_loss_windows": stop_windows,
                "trend_check_label": trend_label,
                "trend_check_minutes": trend_checks,
                "force_buy_minute": force_minute,
                **metrics,
                "score_return_drawdown": _return_drawdown_score(metrics),
                "entry_mode_breakdown": _value_counts(result["trades"], "entry_mode"),
                "execution_mode_breakdown": _value_counts(result["trades"], "execution_mode"),
            }
        )
        if idx % 9 == 0:
            print(f"grid progress {idx}/{len(grid_params)}", flush=True)

    grid = pd.DataFrame(grid_rows).sort_values(
        ["score_return_drawdown", "total_return", "max_drawdown"], ascending=[False, False, False]
    )
    grid = grid.reset_index(drop=True)
    grid.insert(0, "rank", range(1, len(grid) + 1))
    best_row = grid.iloc[0].to_dict()
    best_config = WufuIntradayTimingConfig(
        trend_lookback_minutes=30,
        trend_slope_threshold=0.002,
        fixed_stop_loss_threshold=0.97,
        initial_entry_minute=None
        if pd.isna(best_row["initial_entry_minute"])
        else int(best_row["initial_entry_minute"]),
        trend_check_minutes=tuple(best_row["trend_check_minutes"]),
        force_buy_minute=int(best_row["force_buy_minute"]),
        stop_loss_windows=tuple(tuple(item) for item in best_row["stop_loss_windows"]),
        cash_buffer=0.998,
    )
    best_result = run_wufu_intraday_real_backtest(sample_prices, targets, minute_bars, best_config)

    print("stage 6/6: write outputs", flush=True)
    outputs = _write_outputs(
        end_date=end_date,
        elapsed_seconds=time.perf_counter() - started,
        wufu_config=wufu_config,
        best_config=best_config,
        best_result=best_result,
        best_metrics=_metrics(best_result["equity"], best_result["trades"]),
        grid=grid,
        targets=targets,
        prices=sample_prices,
        minute_bars=minute_bars,
        weak_states=weak_states,
        excluded_symbols=excluded_symbols,
    )
    print(json.dumps(outputs, ensure_ascii=False, indent=2))


def _write_outputs(
    *,
    end_date: str,
    elapsed_seconds: float,
    wufu_config: WufuEtfRotationConfig,
    best_config: WufuIntradayTimingConfig,
    best_result: dict[str, pd.DataFrame],
    best_metrics: dict[str, float | int | None],
    grid: pd.DataFrame,
    targets: pd.DataFrame,
    prices: pd.DataFrame,
    minute_bars: pd.DataFrame,
    weak_states: pd.DataFrame,
    excluded_symbols: list[str],
) -> dict[str, object]:
    PREFIX.parent.mkdir(parents=True, exist_ok=True)
    paths = {
        "summary_json": PREFIX.with_name(PREFIX.name + "_summary.json"),
        "grid_csv": PREFIX.with_name(PREFIX.name + "_scores.csv"),
        "targets_csv": PREFIX.with_name(PREFIX.name + "_targets.csv"),
        "best_equity_csv": PREFIX.with_name(PREFIX.name + "_best_equity.csv"),
        "best_trades_csv": PREFIX.with_name(PREFIX.name + "_best_trades.csv"),
        "report_md": PREFIX.with_name(PREFIX.name + "_report.md"),
        "report_html": PREFIX.with_name(PREFIX.name + "_report.html"),
    }
    grid_for_csv = grid.copy()
    for column in ["stop_loss_windows", "trend_check_minutes", "entry_mode_breakdown", "execution_mode_breakdown"]:
        grid_for_csv[column] = grid_for_csv[column].map(lambda value: json.dumps(_jsonable(value), ensure_ascii=False))
    grid_for_csv.to_csv(paths["grid_csv"], index=False, encoding="utf-8-sig")
    targets.to_csv(paths["targets_csv"], index=False, encoding="utf-8-sig")
    best_result["equity"].to_csv(paths["best_equity_csv"], index=False, encoding="utf-8-sig")
    best_result["trades"].to_csv(paths["best_trades_csv"], index=False, encoding="utf-8-sig")

    summary = {
        "sample_start_date": SAMPLE_START_DATE,
        "sample_end_date": end_date,
        "requested_end_date": REQUESTED_END_DATE,
        "method": {
            "engine": "real minute intraday timing with daily proxy fallback",
            "grid_scope": "initial detection time, stop-loss time window, trend check times, force-buy time",
            "fixed_params": {
                "trend_lookback_minutes": 30,
                "trend_slope_threshold": 0.002,
                "fixed_stop_loss_threshold": 0.97,
                "cash_buffer": 0.998,
            },
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
        "grid": {
            "count": int(len(grid)),
            "params": {
                "initial_entry_minutes": INITIAL_ENTRY_MINUTES,
                "stop_windows": STOP_WINDOWS,
                "trend_check_sets": TREND_CHECK_SETS,
                "force_buy_minutes": FORCE_BUY_MINUTES,
            },
            "top10": _records(grid.head(10)),
        },
        "params": {
            "wufu": asdict(wufu_config),
            "best": asdict(best_config),
        },
        "metrics": {
            "best": best_metrics,
        },
        "trade_breakdown": {
            "best": {
                "actions": _value_counts(best_result["trades"], "action"),
                "entry_modes": _value_counts(best_result["trades"], "entry_mode"),
                "execution_modes": _value_counts(best_result["trades"], "execution_mode"),
            }
        },
        "outputs": {key: str(path) for key, path in paths.items()},
        "elapsed_seconds": elapsed_seconds,
    }
    paths["summary_json"].write_text(json.dumps(_jsonable(summary), ensure_ascii=False, indent=2), encoding="utf-8")
    markdown = _markdown_report(summary)
    paths["report_md"].write_text(markdown, encoding="utf-8")
    paths["report_html"].write_text(_html_report(markdown), encoding="utf-8")
    return summary["outputs"]


def _metrics(equity: pd.DataFrame, trades: pd.DataFrame) -> dict[str, float | int | None]:
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
        "win_rate": None
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


def _return_drawdown_score(metrics: dict[str, float | int | None]) -> float:
    total_return = float(metrics["total_return"] or 0.0)
    max_drawdown = abs(float(metrics["max_drawdown"] or 0.0))
    return total_return / max(max_drawdown, 0.01)


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
    columns = [
        "rank",
        "grid_id",
        "initial_entry_label",
        "initial_entry_minute",
        "stop_loss_profile",
        "trend_check_label",
        "force_buy_minute",
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
    return _jsonable(frame[columns].to_dict(orient="records"))


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
    data = summary["data"]
    top10 = summary["grid"]["top10"]
    best = summary["metrics"]["best"]
    return f"""# 五福 ETF 上午检测/买入时间参数网格报告

## 样本

- 区间：{summary['sample_start_date']} 至 {summary['sample_end_date']}
- 日线：{data['daily_price_rows']} 行，{data['daily_symbols']} 个标的
- 分钟线：{data['minute_rows']} 行，{data['minute_symbols']} 个标的，覆盖 {data['minute_start']} 至 {data['minute_end']}
- 目标序列：{data['target_rows']} 行
- 剔除复权断点标的：{data['excluded_symbols'] if data['excluded_symbols'] else '无'}

## 网格设计

本轮只搜索执行时间参数，选标、弱市、成本、趋势斜率阈值和止损阈值保持固定。

- 检测/初始买入时间：不启用、09:45、10:00、10:30、11:00、13:20
- 止损时间：全日窗口、仅下午、10:00 后、10:30 后
- 趋势判断时间：10:00/10:30/11:00，10:30/11:00/13:40，11:00/13:40/14:10，13:40/14:10/14:30
- 强制买入时间：13:40、14:40、14:55
- 组合数：{summary['grid']['count']}

排序规则：先按 `总收益 / max(|最大回撤|, 1%)`，再按总收益和最大回撤排序。

## 最佳组合

- 初始买入：{summary['params']['best']['initial_entry_minute']}
- 止损窗口：{summary['params']['best']['stop_loss_windows']}
- 趋势判断：{summary['params']['best']['trend_check_minutes']}
- 强制买入：{summary['params']['best']['force_buy_minute']}
- 总收益：{best['total_return']:.2%}
- 年化收益：{best['annualized_return']:.2%}
- 最大回撤：{best['max_drawdown']:.2%}
- 交易次数：{best['trade_count']}
- 止损次数：{best['stop_loss_count']}

## Top10

{_top_table(top10)}

## 解读

本轮样本只覆盖近期真实分钟线，适合判断上午进场方向，不适合直接作为长期最终参数。若 Top10 集中在上午初始买入或上午趋势确认，说明早进场在这段样本中有优势；若仍集中在 `none` 或下午检测，说明等待下午确认更稳。

止损时间若偏向“仅下午”或“买入后下午”，通常意味着上午止损容易卖飞；若“全日窗口”占优，则说明盘中防守对这段样本有效。

下一步建议用 V12-A 双平台脚本重跑，并把本轮 Top3 时间组合分别迁移到同花顺和聚宽脚本做平台日志验证；如果上午进场占优，还要重点检查同花顺 25% 分钟成交量限制是否更频繁触发。
"""


def _top_table(rows: list[dict[str, object]]) -> str:
    lines = [
        "| 排名 | 初始买入 | 止损窗口 | 趋势判断 | 强制买入 | 总收益 | 最大回撤 | 交易数 | 止损数 |",
        "|---:|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| {rank} | {initial_entry_label} | {stop_loss_profile} | {trend_check_label} | "
            "{force_buy_minute} | {total_return:.2%} | {max_drawdown:.2%} | {trade_count} | {stop_loss_count} |".format(
                **row
            )
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
        elif line:
            body.append(f"<p>{html.escape(line)}</p>")
    if in_table:
        body.append("</pre>")
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        "<title>五福 ETF 上午检测/买入时间参数网格报告</title>"
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
