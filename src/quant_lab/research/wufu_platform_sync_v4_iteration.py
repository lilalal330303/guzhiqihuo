from __future__ import annotations

import html
import json
from pathlib import Path

import pandas as pd

from quant_lab.data.repository import DuckDBRepository
from quant_lab.research.wufu_etf_rotation import run_wufu_etf_rotation_experiment
from quant_lab.strategies.wufu_etf_rotation import (
    WufuEtfRotationConfig,
    calculate_joinquant_liquidity_thresholds,
)


def run_platform_sync_v4(
    db_path: str | Path = "data/market.duckdb",
    reports_dir: str | Path = "reports",
    start_date: str = "2020-01-01",
    end_date: str = "2026-07-06",
) -> dict[str, object]:
    reports = Path(reports_dir)
    reports.mkdir(parents=True, exist_ok=True)
    repo = DuckDBRepository(db_path)
    repo.initialize()

    config = WufuEtfRotationConfig()
    symbols = list(dict.fromkeys(config.etf_pool + config.global_etf_pool + [config.defensive_etf or ""]))
    prices = repo.load_prices_for_symbols(symbols, "2019-10-01", end_date)
    thresholds = calculate_joinquant_liquidity_thresholds(prices)

    result = run_wufu_etf_rotation_experiment(
        repo=repo,
        start_date=start_date,
        end_date=end_date,
        config=config,
        refresh_data=False,
        use_local_weak_states=True,
        dynamic_liquidity_thresholds=thresholds,
        commission_rate=0.0001,
        slippage_rate=0.0001,
        min_commission=5.0,
        etf_adjust="stored-qfq-or-repaired",
        target_cache_key="wufu_platform_sync_v4_fixed_pool_liquidity_lag1",
        use_target_cache=False,
        weak_state_signal_lag_days=1,
        apply_liquidity_filter=True,
        hypothesis=(
            "Platform sync V4: fixed ETF pool, fixed-pool JoinQuant-style liquidity threshold, "
            "local index weak state with previous-day signal boundary, ETF commission/slippage/min commission."
        ),
        next_research_note=(
            "Run SuperMind V4 and JoinQuant V4 minute logs. If SuperMind WUFU_INDEX_RESOLVE resolves 000510 "
            "to a valid index source, weak-state match should improve materially; then move to execution-order "
            "rounding and current-price/volume score detail isolation."
        ),
    )

    prefix = reports / "wufu_platform_sync_v4"
    result.targets.to_csv(prefix.with_name(prefix.name + "_targets.csv"), index=False, encoding="utf-8-sig")
    result.trades.to_csv(prefix.with_name(prefix.name + "_trades.csv"), index=False, encoding="utf-8-sig")
    result.equity_curve.to_csv(prefix.with_name(prefix.name + "_equity.csv"), index=False, encoding="utf-8-sig")
    thresholds.to_csv(prefix.with_name(prefix.name + "_liquidity_thresholds.csv"), index=False, encoding="utf-8-sig")

    ths_compare = _compare_with_signal(result.targets, reports / "ths_jq_fast_v3_ths_signals.csv", "ths")
    jq_compare = _compare_with_signal(result.targets, reports / "ths_jq_fast_v3_jq_signals.csv", "jq")
    platform_compare = _read_json(reports / "ths_jq_fast_v3_summary.json")
    if not ths_compare.empty:
        ths_compare.to_csv(prefix.with_name(prefix.name + "_ths_signal_compare.csv"), index=False, encoding="utf-8-sig")
    if not jq_compare.empty:
        jq_compare.to_csv(prefix.with_name(prefix.name + "_jq_signal_compare.csv"), index=False, encoding="utf-8-sig")

    summary = {
        "run_id": result.run_id,
        "start_date": start_date,
        "end_date": end_date,
        "metrics": result.metrics,
        "target_rows": int(len(result.targets)),
        "trade_rows": int(len(result.trades)),
        "data_quality_excluded_symbols": result.data_quality_excluded_symbols,
        "threshold_min": _float_or_none(thresholds["liquidity_threshold"].min()) if not thresholds.empty else None,
        "threshold_median": _float_or_none(thresholds["liquidity_threshold"].median()) if not thresholds.empty else None,
        "threshold_max": _float_or_none(thresholds["liquidity_threshold"].max()) if not thresholds.empty else None,
        "local_vs_ths": _match_summary(ths_compare),
        "local_vs_jq": _match_summary(jq_compare),
        "ths_vs_jq_v3": {
            "target_match_rate": platform_compare.get("signal", {}).get("target_match_rate"),
            "weak_match_rate": platform_compare.get("morning", {}).get("weak_match_rate"),
            "weak_mismatch_days": platform_compare.get("morning", {}).get("weak_mismatch_days"),
            "threshold_ratio_median": platform_compare.get("morning", {}).get("threshold_ratio_median"),
            "ths_total_return_from_first_close": platform_compare.get("ths_close", {}).get("total_return_from_first_close"),
        },
        "iteration_reading": [
            "V4 platform scripts isolate the remaining biggest platform mismatch: SuperMind missing 000510 weak-index data.",
            "Local V4 now applies fixed-pool liquidity filtering, so its pool construction is closer to both platforms than V1.",
            "Local still uses daily close for scoring, while both platform minute scripts use 13:10 current price/volume; this remains the largest local-platform scoring gap.",
        ],
    }
    summary_path = prefix.with_name(prefix.name + "_summary.json")
    md_path = prefix.with_name(prefix.name + "_analysis.md")
    html_path = prefix.with_name(prefix.name + "_analysis.html")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown = _analysis_markdown(summary)
    md_path.write_text(markdown, encoding="utf-8-sig")
    html_path.write_text(_html_report(markdown), encoding="utf-8-sig")
    return summary


def _compare_with_signal(local_targets: pd.DataFrame, signal_path: Path, platform: str) -> pd.DataFrame:
    if local_targets.empty or not signal_path.exists():
        return pd.DataFrame()
    signals = pd.read_csv(signal_path)
    if signals.empty:
        return pd.DataFrame()
    local = local_targets[["trade_date", "target_symbol", "is_weak", "candidates_json"]].copy()
    local["trade_date"] = pd.to_datetime(local["trade_date"]).dt.date
    local["local_target"] = local["target_symbol"].astype(str).str[:6]
    right = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(signals["date"]).dt.date,
            f"{platform}_target": signals["target"].astype(str).str[:6],
            f"{platform}_top10_raw": signals.get("top10_raw", ""),
        }
    ).drop_duplicates("trade_date")
    rows = local.merge(right, on="trade_date", how="inner")
    rows["target_match"] = rows["local_target"] == rows[f"{platform}_target"]
    return rows


def _match_summary(compare: pd.DataFrame) -> dict[str, object]:
    if compare.empty:
        return {"days": 0, "matched_days": 0, "match_rate": None, "weak_days": 0}
    by_weak = compare.groupby("is_weak")["target_match"].agg(["count", "mean"]).reset_index()
    return {
        "days": int(len(compare)),
        "matched_days": int(compare["target_match"].sum()),
        "match_rate": float(compare["target_match"].mean()),
        "weak_days": int(compare["is_weak"].sum()),
        "by_local_weak": [
            {"is_weak": bool(row.is_weak), "days": int(row["count"]), "match_rate": float(row["mean"])}
            for _, row in by_weak.iterrows()
        ],
    }


def _analysis_markdown(summary: dict[str, object]) -> str:
    metrics = summary["metrics"]
    return f"""# 五福 ETF 三端同步 V4 报告

## 本轮迭代

- 同花顺 V4：新增 `000510` 弱市指数多后缀解析，优先尝试 `.CSI`，并输出 `WUFU_INDEX_RESOLVE`。
- 同花顺 V4：ETF `.SH/.SZ` 标的不再逐只做后缀探测，减少日内评分前的无效历史查询。
- 聚宽 V4：保持固定池、固定池成交额阈值和弱市状态机不变，作为对照基准。
- 本地 V4：新增固定池成交额过滤，并按前一交易日指数状态计算弱市。

## 本地回测

- Run ID：`{summary["run_id"]}`
- 区间：`{summary["start_date"]}` 到 `{summary["end_date"]}`
- 总收益：`{metrics.get("total_return"):.6f}`
- 年化收益：`{metrics.get("annualized_return"):.6f}`
- 最大回撤：`{metrics.get("max_drawdown"):.6f}`
- 交易次数：`{metrics.get("trade_count")}`
- 胜率：`{metrics.get("win_rate"):.6f}`

## 同步结果

- 本地 vs 同花顺 V3 日数：`{summary["local_vs_ths"].get("days")}`，匹配率：`{summary["local_vs_ths"].get("match_rate")}`
- 本地 vs 聚宽 V3 日数：`{summary["local_vs_jq"].get("days")}`，匹配率：`{summary["local_vs_jq"].get("match_rate")}`
- 同花顺 vs 聚宽 V3 匹配率：`{summary["ths_vs_jq_v3"].get("target_match_rate")}`
- 同花顺 vs 聚宽 V3 弱市匹配率：`{summary["ths_vs_jq_v3"].get("weak_match_rate")}`，弱市不一致天数：`{summary["ths_vs_jq_v3"].get("weak_mismatch_days")}`
- 成交额阈值中位比值：`{summary["ths_vs_jq_v3"].get("threshold_ratio_median")}`

## 解释

本地 V4 已经补上固定池成交额过滤，但仍然不是平台分钟级的逐笔等价回放：本地用日线收盘价评分，平台在 13:10 使用当时价格和当日成交量。因此本地更适合做方向性研究和参数压力测试，平台日志更适合做执行层一致性校验。

下一轮重点看同花顺 V4 跑出的 `WUFU_INDEX_RESOLVE`：只要 `000510` 不再是 NA，弱市匹配率理论上应从 V3 的约 89.84% 明显上升，目标匹配率也会跟着改善。随后再开启 `WUFU_SCORE_DETAIL` 短区间对齐 13:10 价格、成交量、停牌和订单失败处理。
"""


def _html_report(markdown: str) -> str:
    body = "\n".join(
        f"<h1>{html.escape(line[2:])}</h1>" if line.startswith("# ")
        else f"<h2>{html.escape(line[3:])}</h2>" if line.startswith("## ")
        else f"<li>{html.escape(line[2:])}</li>" if line.startswith("- ")
        else f"<p>{html.escape(line)}</p>" if line.strip()
        else ""
        for line in markdown.splitlines()
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>五福 ETF 三端同步 V4 报告</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; line-height: 1.65; max-width: 980px; margin: 32px auto; padding: 0 24px; color: #202124; }}
    h1, h2 {{ line-height: 1.25; }}
    code {{ background: #f1f3f4; padding: 2px 5px; border-radius: 4px; }}
    li {{ margin: 6px 0; }}
  </style>
</head>
<body>{body}</body>
</html>
"""


def _read_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _float_or_none(value: object) -> float | None:
    return None if pd.isna(value) else float(value)


if __name__ == "__main__":
    print(json.dumps(run_platform_sync_v4(), ensure_ascii=False, indent=2))
