from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd

from quant_lab.backtest.capacity import CapacityConfig, simulate_rebalance_capacity
from quant_lab.data.minute import fetch_etf_minute_bars_mootdx, fetch_etf_minute_bars_pandadata


BASE_OUTPUT_DIR = Path(r"C:\Users\16052\Documents\Codex\2026-07-01\new-chat\outputs")
REPLAY_DIR = BASE_OUTPUT_DIR / "local_capacity_replay_20260706"
OUTLOG8_DIR = BASE_OUTPUT_DIR / "qd_best_outlog8_analysis_20260706"
ANALYSIS_DIR = BASE_OUTPUT_DIR / "capacity_fullcycle_hybrid_20260706"
BASELINE_BUY_RATIO = 0.995


@dataclass(frozen=True)
class Scenario:
    name: str
    participation_rate: float
    slice_count: int | None
    buy_value_ratio: float
    min_order_value: float = 0.0


def run_fullcycle_capacity_analysis(
    output_dir: Path = ANALYSIS_DIR,
    refresh_real_minutes: bool = True,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)

    orders_raw = pd.read_csv(REPLAY_DIR / "orders_from_outlog8.csv")
    proxy_minutes = pd.read_csv(REPLAY_DIR / "minute_bars_proxy_from_outlog8.csv")
    closes = pd.read_csv(OUTLOG8_DIR / "closes.csv")

    orders = orders_raw.copy()
    orders["trade_date"] = pd.to_datetime(orders["trade_date"]).dt.strftime("%Y-%m-%d")
    # The parsed strategy orders are already 99.5% of account value. Convert back
    # to account-level target so each scenario's buy_value_ratio has one meaning.
    orders["target_value"] = orders["target_value"].astype(float) / BASELINE_BUY_RATIO

    proxy_minutes = _normalize_minute_frame(proxy_minutes, source="proxy")
    real_minutes = _load_or_fetch_real_minutes(orders, output_dir, refresh=refresh_real_minutes)
    hybrid_minutes = _merge_hybrid_minutes(proxy_minutes, real_minutes)

    scenarios = _scenario_grid()
    scenario_rows: list[dict[str, object]] = []
    curves: list[pd.DataFrame] = []
    fills_by_scenario: dict[str, pd.DataFrame] = {}

    for scenario in scenarios:
        if scenario.name == "no_capacity_ideal":
            result_fills = pd.DataFrame()
            fill_by_order = _ideal_order_fills(orders)
        else:
            cfg = CapacityConfig(
                participation_rate=scenario.participation_rate,
                slice_count=scenario.slice_count,
                buy_value_ratio=scenario.buy_value_ratio,
                min_order_value=scenario.min_order_value,
            )
            result = simulate_rebalance_capacity(orders, hybrid_minutes, cfg)
            result_fills = result.fills
            fill_by_order = _summarize_order_fills(result_fills, orders)
        curve = _capacity_equity_curve(closes, fill_by_order, scenario.name)
        metrics = _curve_metrics(curve)
        capacity_metrics = _capacity_metrics(result_fills, fill_by_order)
        scenario_rows.append({**scenario.__dict__, **metrics, **capacity_metrics})
        curves.append(curve)
        fills_by_scenario[scenario.name] = fill_by_order

    scenario_scores = pd.DataFrame(scenario_rows).sort_values(
        ["final_value", "max_drawdown_pct"], ascending=[False, False]
    )
    curve_all = pd.concat(curves, ignore_index=True)

    actionable_scores = scenario_scores[scenario_scores["name"] != "no_capacity_ideal"]
    best_name = str(actionable_scores.iloc[0]["name"])
    baseline_name = "current_order_slices"
    fills_by_scenario[baseline_name].to_csv(output_dir / "baseline_order_fills.csv", index=False)
    fills_by_scenario[best_name].to_csv(output_dir / "best_order_fills.csv", index=False)
    scenario_scores.to_csv(output_dir / "scenario_scores.csv", index=False)
    curve_all.to_csv(output_dir / "scenario_curves.csv", index=False)
    hybrid_minutes.to_csv(output_dir / "hybrid_minute_bars.csv", index=False)

    report = _build_report(
        scenario_scores=scenario_scores,
        closes=closes,
        proxy_minutes=proxy_minutes,
        real_minutes=real_minutes,
        hybrid_minutes=hybrid_minutes,
        baseline_name=baseline_name,
        best_name=best_name,
    )
    (output_dir / "capacity_fullcycle_hybrid_CN.html").write_text(report, encoding="utf-8")
    (output_dir / "summary.txt").write_text(_plain_summary(scenario_scores, baseline_name, best_name), encoding="utf-8")

    return {
        "output_dir": output_dir,
        "scenario_scores": scenario_scores,
        "baseline": scenario_scores[scenario_scores["name"] == baseline_name].iloc[0].to_dict(),
        "best": actionable_scores.iloc[0].to_dict(),
        "real_minute_rows": int(len(real_minutes)),
        "hybrid_minute_rows": int(len(hybrid_minutes)),
    }


def _load_or_fetch_real_minutes(orders: pd.DataFrame, output_dir: Path, refresh: bool) -> pd.DataFrame:
    cache_path = output_dir / "real_minute_bars.csv"
    if cache_path.exists() and not refresh:
        return _normalize_minute_frame(pd.read_csv(cache_path), source="real")

    recent_orders = orders[orders["trade_date"] >= "2026-03-01"].copy()
    symbols = sorted(recent_orders["symbol"].unique())
    frames: list[pd.DataFrame] = []
    for symbol in symbols:
        try:
            frames.append(
                fetch_etf_minute_bars_pandadata(
                    symbol,
                    "2026-03-01",
                    "2026-07-06",
                    time_zone=("09:32", "09:42"),
                )
            )
            continue
        except Exception:
            pass
        try:
            frames.append(fetch_etf_minute_bars_mootdx(symbol, pages=35, page_size=800, timeout=5))
        except Exception:
            continue

    if not frames:
        real = pd.DataFrame(columns=["trade_date", "minute", "symbol", "close", "volume", "source"])
    else:
        real = pd.concat(frames, ignore_index=True)
        real = real[real["trade_date"].isin(set(recent_orders["trade_date"]))]
        real = real[real["minute"].between(932, 952)]
        real = real[["trade_date", "minute", "symbol", "close", "volume"]].copy()
        real["source"] = "real"
    real = _normalize_minute_frame(real, source="real")
    real.to_csv(cache_path, index=False)
    return real


def _normalize_minute_frame(frame: pd.DataFrame, source: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["trade_date", "minute", "symbol", "close", "volume", "source"])
    rows = frame.copy()
    rows["trade_date"] = pd.to_datetime(rows["trade_date"]).dt.strftime("%Y-%m-%d")
    rows["minute"] = pd.to_numeric(rows["minute"], errors="coerce").astype("Int64")
    rows["symbol"] = rows["symbol"].astype(str).str.upper()
    rows["close"] = pd.to_numeric(rows["close"], errors="coerce")
    rows["volume"] = pd.to_numeric(rows["volume"], errors="coerce")
    rows["source"] = rows.get("source", source)
    rows = rows.dropna(subset=["trade_date", "minute", "symbol", "close", "volume"])
    rows["minute"] = rows["minute"].astype(int)
    return rows[["trade_date", "minute", "symbol", "close", "volume", "source"]].drop_duplicates(
        ["trade_date", "minute", "symbol"], keep="last"
    )


def _merge_hybrid_minutes(proxy_minutes: pd.DataFrame, real_minutes: pd.DataFrame) -> pd.DataFrame:
    if real_minutes.empty:
        return proxy_minutes.copy()
    keys = ["trade_date", "minute", "symbol"]
    proxy = proxy_minutes.set_index(keys)
    real = real_minutes.set_index(keys)
    proxy.update(real[["close", "volume", "source"]])
    missing_real = real.loc[~real.index.isin(proxy.index)].reset_index()
    return pd.concat([proxy.reset_index(), missing_real], ignore_index=True).sort_values(keys).reset_index(drop=True)


def _scenario_grid() -> list[Scenario]:
    scenarios = [
        Scenario("no_capacity_ideal", 1.0, 1, 0.995, 0.0),
        Scenario("current_order_slices", 0.25, None, 0.995, 0.0),
    ]
    for participation in [0.10, 0.15, 0.20, 0.25, 0.35]:
        for slices in [1, 3, 5, 10, 15, 20]:
            for buy_ratio in [0.80, 0.90, 0.95, 0.995]:
                for min_order in [0.0, 20_000.0, 50_000.0]:
                    scenarios.append(
                        Scenario(
                            f"p{participation:.2f}_s{slices}_b{buy_ratio:.3f}_min{int(min_order)}",
                            participation,
                            slices,
                            buy_ratio,
                            min_order,
                        )
                    )
    return scenarios


def _summarize_order_fills(fills: pd.DataFrame, orders: pd.DataFrame) -> pd.DataFrame:
    grouped = fills.groupby(["trade_date", "symbol"], as_index=False).agg(
        desired_value=("desired_value", "sum"),
        filled_value=("filled_value", "sum"),
        unfilled_value=("unfilled_value", "sum"),
        min_capacity_ratio=("capacity_ratio", "min"),
        fill_slice_count=("slice_no", "count"),
        real_slice_count=("source", lambda s: int((s == "real").sum()) if "source" in fills.columns else 0),
    )
    order_base = orders[["trade_date", "symbol", "target_value"]].copy()
    merged = order_base.merge(grouped, on=["trade_date", "symbol"], how="left")
    for col in ["desired_value", "filled_value", "unfilled_value", "min_capacity_ratio", "fill_slice_count"]:
        merged[col] = merged[col].fillna(0.0)
    merged["exposure_fraction"] = (merged["filled_value"] / merged["target_value"]).clip(lower=0.0, upper=1.0)
    return merged


def _ideal_order_fills(orders: pd.DataFrame) -> pd.DataFrame:
    rows = orders[["trade_date", "symbol", "target_value"]].copy()
    rows["desired_value"] = rows["target_value"]
    rows["filled_value"] = rows["target_value"]
    rows["unfilled_value"] = 0.0
    rows["min_capacity_ratio"] = float("inf")
    rows["fill_slice_count"] = 0
    rows["real_slice_count"] = 0
    rows["exposure_fraction"] = 1.0
    return rows


def _capacity_equity_curve(closes: pd.DataFrame, fill_by_order: pd.DataFrame, scenario_name: str) -> pd.DataFrame:
    curve = closes[["date", "value", "target"]].copy()
    curve["date"] = pd.to_datetime(curve["date"]).dt.strftime("%Y-%m-%d")
    curve["ideal_return"] = curve["value"].astype(float).pct_change()
    curve.loc[0, "ideal_return"] = curve.loc[0, "value"] / 1_000_000.0 - 1.0
    exposure_by_date = dict(zip(fill_by_order["trade_date"], fill_by_order["exposure_fraction"]))

    value = 1_000_000.0
    exposure = 1.0
    rows: list[dict[str, object]] = []
    for item in curve.itertuples(index=False):
        date = str(item.date)
        if date in exposure_by_date:
            exposure = float(exposure_by_date[date])
        daily_return = float(item.ideal_return)
        value *= 1.0 + exposure * daily_return
        rows.append(
            {
                "scenario": scenario_name,
                "date": date,
                "target": item.target,
                "ideal_value": float(item.value),
                "capacity_value": value,
                "ideal_return": daily_return,
                "exposure_fraction": exposure,
            }
        )
    return pd.DataFrame(rows)


def _curve_metrics(curve: pd.DataFrame) -> dict[str, float]:
    final_value = float(curve["capacity_value"].iloc[-1])
    total_return = final_value / 1_000_000.0 - 1.0
    years = len(curve) / 252.0
    annual_return = (final_value / 1_000_000.0) ** (1.0 / years) - 1.0 if years > 0 else 0.0
    running_max = curve["capacity_value"].cummax()
    drawdown = curve["capacity_value"] / running_max - 1.0
    daily = curve["capacity_value"].pct_change().dropna()
    return {
        "final_value": final_value,
        "total_return_pct": total_return * 100.0,
        "annual_return_pct": annual_return * 100.0,
        "max_drawdown_pct": float(drawdown.min() * 100.0),
        "win_day_rate_pct": float((daily > 0).mean() * 100.0) if len(daily) else 0.0,
        "avg_exposure_pct": float(curve["exposure_fraction"].mean() * 100.0),
        "min_exposure_pct": float(curve["exposure_fraction"].min() * 100.0),
    }


def _capacity_metrics(fills: pd.DataFrame, fill_by_order: pd.DataFrame) -> dict[str, float | int]:
    return {
        "orders": int(len(fill_by_order)),
        "avg_order_fill_pct": float(fill_by_order["exposure_fraction"].mean() * 100.0),
        "low_fill_orders_lt50": int((fill_by_order["exposure_fraction"] < 0.5).sum()),
        "low_fill_orders_lt80": int((fill_by_order["exposure_fraction"] < 0.8).sum()),
        "capacity_warning_slices": int((fills["capacity_ratio"] < 1.0).sum()) if not fills.empty else 0,
        "severe_capacity_slices": int((fills["capacity_ratio"] < 0.1).sum()) if not fills.empty else 0,
    }


def _build_report(
    scenario_scores: pd.DataFrame,
    closes: pd.DataFrame,
    proxy_minutes: pd.DataFrame,
    real_minutes: pd.DataFrame,
    hybrid_minutes: pd.DataFrame,
    baseline_name: str,
    best_name: str,
) -> str:
    baseline = scenario_scores[scenario_scores["name"] == baseline_name].iloc[0]
    ideal = scenario_scores[scenario_scores["name"] == "no_capacity_ideal"].iloc[0]
    actionable_scores = scenario_scores[scenario_scores["name"] != "no_capacity_ideal"]
    best = actionable_scores.iloc[0]
    top = actionable_scores.head(15).copy()
    top_html = _format_table(top)
    real_keys = real_minutes[["trade_date", "minute", "symbol"]].drop_duplicates() if not real_minutes.empty else real_minutes
    hybrid_real_rows = int((hybrid_minutes.get("source", pd.Series(dtype=str)) == "real").sum())
    impact_vs_ideal = float(baseline["final_value"] / ideal["final_value"] - 1.0) * 100.0
    best_vs_baseline = float(best["final_value"] / baseline["final_value"] - 1.0) * 100.0
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>容量模型全周期混合回测</title>
<style>
body{{font-family:Arial,'Microsoft YaHei',sans-serif;margin:28px;line-height:1.55;color:#222}}
table{{border-collapse:collapse;width:100%;font-size:13px}}
th,td{{border:1px solid #ddd;padding:6px 8px;text-align:right}}
th:first-child,td:first-child{{text-align:left}}
th{{background:#f5f5f5}}
.note{{background:#f8fafc;border-left:4px solid #4682b4;padding:10px 14px;margin:14px 0}}
code{{background:#f3f3f3;padding:1px 4px}}
</style>
</head>
<body>
<h1>容量模型全周期混合回测</h1>
<div class="note">
本报告使用 outlog8 的目标序列和净值曲线作为无容量基准收益路径；容量模型决定换仓日实际买入比例，未成交部分按现金处理。
分钟成交额优先使用真实分钟数据，无法获取的历史区间使用上一轮日志反推代理分钟数据。
</div>
<h2>核心结论</h2>
<ul>
<li>无容量理想基准 final value: <b>{ideal['final_value']:,.2f}</b>，total return: <b>{ideal['total_return_pct']:.2f}%</b>。</li>
<li>当前切片方案 final value: <b>{baseline['final_value']:,.2f}</b>，total return: <b>{baseline['total_return_pct']:.2f}%</b>，相对无容量影响: <b>{impact_vs_ideal:.2f}%</b>。</li>
<li>网格最佳方案: <b>{best_name}</b>，final value: <b>{best['final_value']:,.2f}</b>，相对当前方案: <b>{best_vs_baseline:.2f}%</b>。</li>
<li>当前方案平均订单成交暴露: <b>{baseline['avg_order_fill_pct']:.2f}%</b>；低于 50% 的换仓次数: <b>{int(baseline['low_fill_orders_lt50'])}</b>。</li>
</ul>
<h2>数据覆盖</h2>
<ul>
<li>全周期交易日: <b>{len(closes)}</b>；换仓订单: <b>{int(baseline['orders'])}</b>。</li>
<li>代理分钟行数: <b>{len(proxy_minutes)}</b>；真实分钟行数: <b>{len(real_minutes)}</b>；真实分钟唯一键: <b>{len(real_keys)}</b>。</li>
<li>混合后分钟行数: <b>{len(hybrid_minutes)}</b>；其中真实分钟覆盖行数: <b>{hybrid_real_rows}</b>。</li>
</ul>
<h2>Top 15 参数组合</h2>
{top_html}
<h2>解释口径</h2>
<p>这里的容量影响不是同花顺撮合明细复刻，而是研究用现金拖累模型。它回答的是：在同样的目标选择和收益路径下，如果每次换仓只能按分钟成交额的一定参与率买入，最终净值大概会被拖累多少。若 Pandadata 全历史分钟数据配置成功，后续可以把代理分钟替换为真实分钟，模型结构不需要重写。</p>
</body>
</html>
"""


def _format_table(frame: pd.DataFrame) -> str:
    cols = [
        "name",
        "participation_rate",
        "slice_count",
        "buy_value_ratio",
        "min_order_value",
        "final_value",
        "total_return_pct",
        "annual_return_pct",
        "max_drawdown_pct",
        "avg_exposure_pct",
        "low_fill_orders_lt50",
    ]
    data = frame[cols].copy()
    for col in ["final_value", "total_return_pct", "annual_return_pct", "max_drawdown_pct", "avg_exposure_pct"]:
        data[col] = data[col].map(lambda value: f"{float(value):,.2f}")
    return data.to_html(index=False, escape=False)


def _plain_summary(scenario_scores: pd.DataFrame, baseline_name: str, best_name: str) -> str:
    baseline = scenario_scores[scenario_scores["name"] == baseline_name].iloc[0]
    ideal = scenario_scores[scenario_scores["name"] == "no_capacity_ideal"].iloc[0]
    best = scenario_scores[scenario_scores["name"] == best_name].iloc[0]
    return "\n".join(
        [
            f"ideal_final={ideal['final_value']:.2f}",
            f"baseline_final={baseline['final_value']:.2f}",
            f"baseline_vs_ideal_pct={(baseline['final_value'] / ideal['final_value'] - 1) * 100:.4f}",
            f"best_name={best_name}",
            f"best_final={best['final_value']:.2f}",
            f"best_vs_baseline_pct={(best['final_value'] / baseline['final_value'] - 1) * 100:.4f}",
            f"baseline_avg_order_fill_pct={baseline['avg_order_fill_pct']:.4f}",
            f"baseline_low_fill_orders_lt50={int(baseline['low_fill_orders_lt50'])}",
        ]
    )


if __name__ == "__main__":
    result = run_fullcycle_capacity_analysis()
    print(f"output_dir={result['output_dir']}")
    print(f"real_minute_rows={result['real_minute_rows']}")
    print(f"hybrid_minute_rows={result['hybrid_minute_rows']}")
    print(f"baseline={result['baseline']}")
    print(f"best={result['best']}")
