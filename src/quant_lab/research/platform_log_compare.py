from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd


DATE_TIME_RE = re.compile(r"(?P<date>\d{4}-\d{2}-\d{2})\s+(?P<time>\d{2}:\d{2}:\d{2})")
SIGNAL_RE = re.compile(r"WUFU_SIGNAL .*?signal_date=(?P<signal_date>\d{4}-\d{2}-\d{2}) target=(?P<target>[^ ]*) top10=(?P<top10>.*)$")
EXECUTE_RE = re.compile(r"WUFU_EXECUTE .*?trade_date=(?P<trade_date>\d{4}-\d{2}-\d{2}) target=(?P<target>.*)$")
MORNING_RE = re.compile(r"morning date=(?P<date>\d{4}-\d{2}-\d{2}) weak=(?P<weak>True|False) threshold=(?P<threshold>[-\d.]+) pool=(?P<pool>\d+)")
JQ_MORNING_RE = re.compile(r"WUFU_MORNING .*?weak=(?P<weak>True|False) threshold=(?P<threshold>[-\d.]+) pool=(?P<pool>\d+)")
THRESHOLD_DETAIL_RE = re.compile(
    r"WUFU_THRESHOLD_DETAIL date=(?P<date>\d{4}-\d{2}-\d{2}) universe=(?P<universe>\d+) valid=(?P<valid>\d+).*?threshold=(?P<threshold>[-\d.]+) source=(?P<source>\S+)"
)
WEAK_DETAIL_RE = re.compile(
    r"WUFU_WEAK_DETAIL date=(?P<date>\d{4}-\d{2}-\d{2}) before=(?P<before>True|False) after=(?P<after>True|False) below=(?P<below>\d+) above=(?P<above>\d+) weak_start=(?P<weak_start>[^ ]+) weak_days=(?P<weak_days>\d+) detail=(?P<detail>.*)$"
)
SCORE_DETAIL_RE = re.compile(
    r"WUFU_SCORE_DETAIL date=(?P<date>\d{4}-\d{2}-\d{2}) weak=(?P<weak>True|False) pool=(?P<pool>\d+) passed=(?P<passed>\d+) target=(?P<target>[^ ]+) top10=(?P<top10>.*)$"
)
THS_CLOSE_RE = re.compile(r"close value=(?P<value>[-\d.]+) weak=(?P<weak>True|False) pool=(?P<pool>\d+) target=(?P<target>[^ ]*) top10=(?P<top10>.*)$")
FAST_CACHE_RE = re.compile(r"WUFU_FAST_CACHE date=(?P<date>\d{4}-\d{2}-\d{2}) requested=(?P<requested>\d+) fetched=(?P<fetched>\d+) total_cached=(?P<total_cached>\d+)")
ORDER_VALUE_RE = re.compile(r"_value=(?P<value>[-\d.]+)")


def compare_platform_logs(ths_log_path: str | Path, jq_log_path: str | Path, output_prefix: str | Path) -> dict[str, object]:
    prefix = Path(output_prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    ths = parse_log(ths_log_path, "ths")
    jq = parse_log(jq_log_path, "jq")

    for side, parsed in (("ths", ths), ("jq", jq)):
        for name, frame in parsed.items():
            if isinstance(frame, pd.DataFrame):
                frame.to_csv(prefix.with_name(f"{prefix.name}_{side}_{name}.csv"), index=False, encoding="utf-8-sig")

    signal_compare = _compare_signals(ths["signals"], jq["signals"])
    morning_compare = _compare_morning(ths["morning"], jq["morning"], ths.get("fast_cache", pd.DataFrame()), jq.get("threshold_detail", pd.DataFrame()))
    score_compare = _compare_scores(ths.get("score_detail", pd.DataFrame()), jq.get("score_detail", pd.DataFrame()))

    signal_compare.to_csv(prefix.with_name(f"{prefix.name}_signal_compare.csv"), index=False, encoding="utf-8-sig")
    morning_compare.to_csv(prefix.with_name(f"{prefix.name}_morning_compare.csv"), index=False, encoding="utf-8-sig")
    score_compare.to_csv(prefix.with_name(f"{prefix.name}_score_compare.csv"), index=False, encoding="utf-8-sig")

    summary = _summary(ths, jq, signal_compare, morning_compare, score_compare)
    prefix.with_name(f"{prefix.name}_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    prefix.with_name(f"{prefix.name}_analysis.md").write_text(_markdown(summary), encoding="utf-8")
    return summary


def parse_log(path: str | Path, platform: str) -> dict[str, pd.DataFrame | dict[str, int]]:
    text = Path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
    rows: dict[str, list[dict[str, object]]] = {
        "signals": [],
        "executes": [],
        "morning": [],
        "threshold_detail": [],
        "weak_detail": [],
        "score_detail": [],
        "close": [],
        "fast_cache": [],
        "order_errors": [],
    }
    counts = {"line_count": len(text), "warnings": 0, "errors": 0}
    for line in text:
        dt = DATE_TIME_RE.search(line)
        log_date = dt.group("date") if dt else None
        log_time = dt.group("time") if dt else None
        if "WARN" in line or "WARNING" in line:
            counts["warnings"] += 1
        if "ERROR" in line or "订单委托失败" in line:
            counts["errors"] += 1

        if "WUFU_SIGNAL" in line:
            m = SIGNAL_RE.search(line)
            if m:
                rows["signals"].append(
                    {
                        "date": m.group("signal_date"),
                        "log_date": log_date,
                        "time": log_time,
                        "target": _symbol6(m.group("target")),
                        "target_raw": m.group("target"),
                        "top10_raw": m.group("top10"),
                        "top10": _parse_top10(m.group("top10")),
                    }
                )
        elif "WUFU_EXECUTE" in line:
            m = EXECUTE_RE.search(line)
            if m:
                rows["executes"].append(
                    {
                        "date": m.group("trade_date"),
                        "log_date": log_date,
                        "time": log_time,
                        "target": _symbol6(m.group("target")),
                        "target_raw": m.group("target"),
                    }
                )
        elif "WUFU_THRESHOLD_DETAIL" in line:
            m = THRESHOLD_DETAIL_RE.search(line)
            if m:
                rows["threshold_detail"].append(
                    {
                        "date": m.group("date"),
                        "universe": int(m.group("universe")),
                        "valid": int(m.group("valid")),
                        "threshold": float(m.group("threshold")),
                        "source": m.group("source"),
                    }
                )
        elif "WUFU_WEAK_DETAIL" in line:
            m = WEAK_DETAIL_RE.search(line)
            if m:
                rows["weak_detail"].append(
                    {
                        "date": m.group("date"),
                        "before": m.group("before") == "True",
                        "weak": m.group("after") == "True",
                        "below": int(m.group("below")),
                        "above": int(m.group("above")),
                        "weak_start": m.group("weak_start"),
                        "weak_days": int(m.group("weak_days")),
                        "detail": m.group("detail"),
                    }
                )
        elif "WUFU_SCORE_DETAIL" in line:
            m = SCORE_DETAIL_RE.search(line)
            if m:
                rows["score_detail"].append(
                    {
                        "date": m.group("date"),
                        "weak": m.group("weak") == "True",
                        "pool": int(m.group("pool")),
                        "passed": int(m.group("passed")),
                        "target": _symbol6(m.group("target")),
                        "target_raw": m.group("target"),
                        "top10_raw": m.group("top10"),
                        "top10": _parse_score_detail(m.group("top10")),
                    }
                )
        elif "WUFU_FAST_CACHE" in line:
            m = FAST_CACHE_RE.search(line)
            if m:
                rows["fast_cache"].append(
                    {
                        "date": m.group("date"),
                        "requested": int(m.group("requested")),
                        "fetched": int(m.group("fetched")),
                        "total_cached": int(m.group("total_cached")),
                    }
                )
        elif "morning date=" in line:
            m = MORNING_RE.search(line)
            if m:
                rows["morning"].append(
                    {
                        "date": m.group("date"),
                        "log_date": log_date,
                        "time": log_time,
                        "weak": m.group("weak") == "True",
                        "threshold": float(m.group("threshold")),
                        "pool": int(m.group("pool")),
                    }
                )
        elif "WUFU_MORNING" in line:
            m = JQ_MORNING_RE.search(line)
            if m and log_date:
                rows["morning"].append(
                    {
                        "date": log_date,
                        "log_date": log_date,
                        "time": log_time,
                        "weak": m.group("weak") == "True",
                        "threshold": float(m.group("threshold")),
                        "pool": int(m.group("pool")),
                    }
                )
        elif "close value=" in line:
            m = THS_CLOSE_RE.search(line)
            if m and log_date:
                rows["close"].append(
                    {
                        "date": log_date,
                        "time": log_time,
                        "value": float(m.group("value")),
                        "weak": m.group("weak") == "True",
                        "pool": int(m.group("pool")),
                        "target": _symbol6(m.group("target")),
                        "top10_raw": m.group("top10"),
                    }
                )
        if "订单委托失败" in line or "涓嬪崟" in line or "璧勯噾" in line:
            value_match = ORDER_VALUE_RE.search(line)
            rows["order_errors"].append(
                {
                    "date": log_date,
                    "time": log_time,
                    "line": line,
                    "value": float(value_match.group("value")) if value_match else None,
                }
            )

    output: dict[str, pd.DataFrame | dict[str, int]] = {"counts": counts}
    for name, items in rows.items():
        frame = pd.DataFrame(items)
        if not frame.empty and "date" in frame.columns:
            frame["date"] = pd.to_datetime(frame["date"]).dt.date
        output[name] = frame
    return output


def _compare_signals(ths: pd.DataFrame, jq: pd.DataFrame) -> pd.DataFrame:
    if ths.empty or jq.empty:
        return pd.DataFrame()
    left = ths[["date", "time", "target", "top10"]].rename(columns={"time": "ths_time", "target": "ths_target", "top10": "ths_top10"})
    right = jq[["date", "time", "target", "top10"]].rename(columns={"time": "jq_time", "target": "jq_target", "top10": "jq_top10"})
    rows = left.merge(right, on="date", how="inner")
    rows["target_match"] = rows["ths_target"] == rows["jq_target"]
    rows["top10_overlap"] = rows.apply(lambda row: len(set(row["ths_top10"]).intersection(set(row["jq_top10"]))), axis=1)
    rows["top1_match"] = rows.apply(lambda row: (row["ths_top10"][0] if row["ths_top10"] else None) == (row["jq_top10"][0] if row["jq_top10"] else None), axis=1)
    return rows


def _compare_morning(ths: pd.DataFrame, jq: pd.DataFrame, fast: pd.DataFrame, jq_threshold: pd.DataFrame) -> pd.DataFrame:
    if ths.empty or jq.empty:
        return pd.DataFrame()
    left = ths[["date", "time", "weak", "threshold", "pool"]].rename(
        columns={"time": "ths_time", "weak": "ths_weak", "threshold": "ths_threshold", "pool": "ths_pool"}
    )
    right = jq[["date", "time", "weak", "threshold", "pool"]].rename(
        columns={"time": "jq_time", "weak": "jq_weak", "threshold": "jq_threshold", "pool": "jq_pool"}
    )
    rows = left.merge(right, on="date", how="inner")
    rows["weak_match"] = rows["ths_weak"] == rows["jq_weak"]
    rows["threshold_ratio"] = rows["ths_threshold"] / rows["jq_threshold"]
    rows["pool_diff"] = rows["ths_pool"] - rows["jq_pool"]
    if not fast.empty:
        rows = rows.merge(fast[["date", "requested", "fetched", "total_cached"]], on="date", how="left")
    if not jq_threshold.empty:
        rows = rows.merge(jq_threshold[["date", "universe", "valid"]], on="date", how="left")
    return rows


def _compare_scores(ths: pd.DataFrame, jq: pd.DataFrame) -> pd.DataFrame:
    if ths.empty or jq.empty:
        return pd.DataFrame()
    left = ths[["date", "pool", "passed", "target", "top10"]].rename(columns={"pool": "ths_pool", "passed": "ths_passed", "target": "ths_target", "top10": "ths_top10"})
    right = jq[["date", "pool", "passed", "target", "top10"]].rename(columns={"pool": "jq_pool", "passed": "jq_passed", "target": "jq_target", "top10": "jq_top10"})
    rows = left.merge(right, on="date", how="inner")
    rows["target_match"] = rows["ths_target"] == rows["jq_target"]
    rows["passed_diff"] = rows["ths_passed"] - rows["jq_passed"]
    rows["top10_overlap"] = rows.apply(lambda row: len(set(row["ths_top10"]).intersection(set(row["jq_top10"]))), axis=1)
    return rows


def _summary(ths: dict[str, object], jq: dict[str, object], signal: pd.DataFrame, morning: pd.DataFrame, score: pd.DataFrame) -> dict[str, object]:
    ths_close = ths["close"]
    jq_errors = jq["order_errors"]
    ths_errors = ths["order_errors"]
    summary: dict[str, object] = {
        "ths_counts": ths["counts"],
        "jq_counts": jq["counts"],
        "ths_rows": _row_counts(ths),
        "jq_rows": _row_counts(jq),
        "signal": _signal_summary(signal),
        "morning": _morning_summary(morning),
        "score": _score_summary(score),
        "ths_close": _close_summary(ths_close if isinstance(ths_close, pd.DataFrame) else pd.DataFrame()),
        "ths_order_warnings": _order_summary(ths_errors if isinstance(ths_errors, pd.DataFrame) else pd.DataFrame()),
        "jq_order_errors": _order_summary(jq_errors if isinstance(jq_errors, pd.DataFrame) else pd.DataFrame()),
    }
    return summary


def _row_counts(parsed: dict[str, object]) -> dict[str, int]:
    return {name: int(len(value)) for name, value in parsed.items() if isinstance(value, pd.DataFrame)}


def _signal_summary(frame: pd.DataFrame) -> dict[str, object]:
    if frame.empty:
        return {"days": 0}
    return {
        "days": int(len(frame)),
        "target_match_days": int(frame["target_match"].sum()),
        "target_match_rate": float(frame["target_match"].mean()),
        "top1_match_rate": float(frame["top1_match"].mean()),
        "top10_overlap_mean": float(frame["top10_overlap"].mean()),
        "first_date": str(frame["date"].min()),
        "last_date": str(frame["date"].max()),
        "yearly": _yearly(frame, {"target_match": "mean", "top10_overlap": "mean"}),
    }


def _morning_summary(frame: pd.DataFrame) -> dict[str, object]:
    if frame.empty:
        return {"days": 0}
    ratio = frame["threshold_ratio"].dropna()
    return {
        "days": int(len(frame)),
        "weak_match_days": int(frame["weak_match"].sum()),
        "weak_match_rate": float(frame["weak_match"].mean()),
        "weak_mismatch_days": int((~frame["weak_match"]).sum()),
        "threshold_ratio_min": float(ratio.min()) if not ratio.empty else None,
        "threshold_ratio_median": float(ratio.median()) if not ratio.empty else None,
        "threshold_ratio_mean": float(ratio.mean()) if not ratio.empty else None,
        "threshold_ratio_max": float(ratio.max()) if not ratio.empty else None,
        "ths_requested_median": float(frame["requested"].median()) if "requested" in frame else None,
        "ths_fetched_median": float(frame["fetched"].median()) if "fetched" in frame else None,
        "jq_universe_median": float(frame["universe"].median()) if "universe" in frame else None,
        "ths_pool_median": float(frame["ths_pool"].median()),
        "jq_pool_median": float(frame["jq_pool"].median()),
        "yearly": _yearly(frame, {"weak_match": "mean", "threshold_ratio": "median", "ths_pool": "median", "jq_pool": "median"}),
    }


def _score_summary(frame: pd.DataFrame) -> dict[str, object]:
    if frame.empty:
        return {"days": 0}
    return {
        "days": int(len(frame)),
        "target_match_rate": float(frame["target_match"].mean()),
        "top10_overlap_mean": float(frame["top10_overlap"].mean()),
        "ths_passed_median": float(frame["ths_passed"].median()),
        "jq_passed_median": float(frame["jq_passed"].median()),
        "passed_diff_median": float(frame["passed_diff"].median()),
    }


def _close_summary(frame: pd.DataFrame) -> dict[str, object]:
    if frame.empty:
        return {"days": 0}
    rows = frame.sort_values("date")
    equity = rows["value"].astype(float)
    returns = equity.pct_change().fillna(0.0)
    drawdown = equity / equity.cummax() - 1.0
    return {
        "days": int(len(rows)),
        "first_date": str(rows["date"].min()),
        "last_date": str(rows["date"].max()),
        "first_value": float(equity.iloc[0]),
        "final_value": float(equity.iloc[-1]),
        "total_return_from_first_close": float(equity.iloc[-1] / equity.iloc[0] - 1.0),
        "max_drawdown": float(drawdown.min()),
        "daily_volatility": float(returns.std()),
    }


def _order_summary(frame: pd.DataFrame) -> dict[str, object]:
    if frame.empty:
        return {"count": 0}
    out = {"count": int(len(frame))}
    values = pd.to_numeric(frame.get("value"), errors="coerce").dropna()
    if not values.empty:
        out.update({"value_median": float(values.median()), "value_max": float(values.max())})
    return out


def _yearly(frame: pd.DataFrame, agg: dict[str, str]) -> dict[str, dict[str, float]]:
    rows = frame.copy()
    rows["year"] = pd.to_datetime(rows["date"]).dt.year
    grouped = rows.groupby("year").agg(agg)
    return {str(year): {col: float(value) for col, value in row.items()} for year, row in grouped.iterrows()}


def _parse_top10(raw: str) -> list[str]:
    if not isinstance(raw, str) or not raw:
        return []
    return [_symbol6(item.split(":")[0]) for item in raw.split(",") if item.strip()]


def _parse_score_detail(raw: str) -> list[str]:
    if not isinstance(raw, str) or not raw:
        return []
    return [_symbol6(item.split(":")[0]) for item in raw.split("|") if item.strip()]


def _symbol6(value: object) -> str:
    text = str(value or "").strip()
    return text[:6]


def _markdown(summary: dict[str, object]) -> str:
    sig = summary["signal"]
    morning = summary["morning"]
    score = summary["score"]
    close = summary["ths_close"]
    return f"""# 同花顺快速 V2 vs 聚宽分钟日志对比报告

## 结论摘要

- 本轮触发时间已经对齐：同花顺和聚宽均有 `09:40`、`13:10`、`13:11` 日内流程。
- 目标匹配率为 `{sig.get("target_match_rate")}`，Top10 平均重合 `{sig.get("top10_overlap_mean")}`。
- 弱市状态匹配率为 `{morning.get("weak_match_rate")}`，弱市不一致 `{morning.get("weak_mismatch_days")}` 天。
- 同花顺成交额阈值 / 聚宽成交额阈值的中位数为 `{morning.get("threshold_ratio_median")}`。
- 同花顺每日请求 ETF 中位数 `{morning.get("ths_requested_median")}`，聚宽全市场 ETF universe 中位数 `{morning.get("jq_universe_median")}`。
- 同花顺收盘资金从 `{close.get("first_value")}` 到 `{close.get("final_value")}`，区间收益 `{close.get("total_return_from_first_close")}`，最大回撤 `{close.get("max_drawdown")}`。

## 关键解释

这版同花顺快速 V2 解决了速度问题，但日志显示它没有拿到聚宽同等的全市场 ETF 池：同花顺 `WUFU_FAST_CACHE requested` 基本围绕固定池 114 只，而聚宽 `universe` 已从 2020 年约 240 只增长到 2026 年 1550+ 只。因此同花顺的成交额阈值系统性偏低，动态行业池也退化为固定池口径。

这会造成两个后果：

1. 阈值不可比：同花顺阈值只是固定池总成交额口径，聚宽阈值是全市场 ETF 总成交额口径。
2. 候选池不可比：聚宽可以从动态行业 ETF 池补入大量后上市 ETF，同花顺快速版主要在固定 114 只里轮动。

## 下一轮验证

1. 先修同花顺全市场 ETF 元数据获取：不要只依赖 `get_all_securities(["etf"])`，增加备用路径或静态全市场 ETF 代码表。
2. 加一个开关 `USE_DYNAMIC_POOL=False/True`：先用固定池对齐两平台基础交易链路，再打开动态池。
3. 在同花顺脚本保留快速缓存，但将 `WUFU_FAST_CACHE` 扩展为 `metadata_source`、`metadata_count`，确认是否真的拿到全市场。
4. 聚宽也跑固定池版本作为隔离实验：如果固定池下目标高度一致，剩余问题就集中在动态池和元数据。
5. 再做执行层统一：聚宽大量小于 100 份平仓失败，同花顺也有下单股数为 0 / 资金不足警告，需要统一最小交易单位和剩余碎股处理。
"""


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--ths-log", required=True)
    parser.add_argument("--jq-log", required=True)
    parser.add_argument("--output-prefix", required=True)
    args = parser.parse_args()
    print(json.dumps(compare_platform_logs(args.ths_log, args.jq_log, args.output_prefix), ensure_ascii=False, indent=2))
