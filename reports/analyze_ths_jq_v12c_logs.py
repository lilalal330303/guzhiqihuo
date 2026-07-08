from __future__ import annotations

import html
import json
import math
import re
import zipfile
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
THS_LOG = Path(r"C:\Users\16052\Desktop\outlog (3).txt")
JQ_ZIP = Path(r"C:\Users\16052\Desktop\log (3).zip")
OUT_PREFIX = ROOT / "reports" / "ths_jq_v12c_latest"


DATE_TIME_RE = re.compile(r"(?P<date>\d{4}-\d{2}-\d{2})\s+(?P<time>\d{2}:\d{2}:\d{2})")
DAILY_RE = re.compile(
    r"WUFU_DAILY_COMPACT date=(?P<date>\d{4}-\d{2}-\d{2}) "
    r"value=(?P<value>[-\d.]+) weak=(?P<weak>True|False) pool=(?P<pool>\d+) "
    r"target=(?P<target>[^ ]*) pending=(?P<pending>.*?) positions=(?P<positions>.*)$"
)
SIGNAL_RE = re.compile(
    r"WUFU_SIGNAL .*?signal_date=(?P<date>\d{4}-\d{2}-\d{2}) "
    r"target=(?P<target>[^ ]*) top10=(?P<top10>.*)$"
)
MORNING_RE = re.compile(
    r"(?:WUFU_MORNING .*?|morning )date?=?now=?(?P<now>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})?.*?"
)
THS_MORNING_RE = re.compile(r"morning date=(?P<date>\d{4}-\d{2}-\d{2}) weak=(?P<weak>True|False) threshold=(?P<threshold>[-\d.]+) pool=(?P<pool>\d+)")
JQ_MORNING_RE = re.compile(r"WUFU_MORNING now=(?P<dt>\d{4}-\d{2}-\d{2}) .*?weak=(?P<weak>True|False) threshold=(?P<threshold>[-\d.]+) pool=(?P<pool>\d+)")
WEAK_RE = re.compile(r"WUFU_WEAK_SOURCE date=(?P<date>\d{4}-\d{2}-\d{2}) mode=(?P<mode>\S+) weak=(?P<weak>True|False).*?source=(?P<source>\S+)")
STOP_RE = re.compile(r"WUFU_STOP_LOSS date=(?P<dt>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) code=(?P<code>\S+)")
ORDER_RE = re.compile(
    r"WUFU_ORDER_PLAN date=(?P<date>\d{4}-\d{2}-\d{2}) mode=(?P<mode>\S+) code=(?P<code>\S+) "
    r"account_value=(?P<account_value>[-\d.]+) buffered_value=(?P<buffered_value>[-\d.]+) "
    r"price=(?P<price>[-\d.]+) shares=(?P<shares>\d+) order_value=(?P<order_value>[-\d.]+)"
)
SPLIT_START_RE = re.compile(
    r"WUFU_SPLIT_START date=(?P<dt>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) code=(?P<code>\S+) "
    r"mode=(?P<mode>\S+) shares=(?P<shares>\d+) minute_volume=(?P<minute_volume>[-\d.]+) "
    r"cap_shares=(?P<cap_shares>\d+) participation=(?P<participation>[-\d.]+) splits=(?P<splits>\d+) "
    r"target_value=(?P<target_value>[-\d.]+)"
)
SPLIT_STEP_RE = re.compile(
    r"WUFU_SPLIT_STEP date=(?P<dt>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) code=(?P<code>\S+) "
    r"step=(?P<step>\d+)/(?P<splits>\d+) target_value=(?P<target_value>[-\d.]+) "
    r"rounded_value=(?P<rounded_value>[-\d.]+) price=(?P<price>[-\d.]+) shares=(?P<shares>\d+)"
)
PENDING_RE = re.compile(r"WUFU_PENDING_BUY date=(?P<dt>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) mode=(?P<mode>\S+) bought=(?P<bought>.*?) pending=(?P<pending>.*)$")


def symbol6(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text.split(".")[0][:6]


def pos_symbol(raw: str) -> str:
    if not raw:
        return ""
    return symbol6(raw.split("|")[0].split(":")[0])


def read_zip(path: Path) -> str:
    with zipfile.ZipFile(path) as zf:
        name = zf.namelist()[0]
        return zf.read(name).decode("utf-8", errors="ignore")


def parse_log(text: str, platform: str) -> dict[str, pd.DataFrame | dict[str, object]]:
    rows: dict[str, list[dict[str, object]]] = {
        "daily": [],
        "signals": [],
        "morning": [],
        "weak": [],
        "stop": [],
        "orders": [],
        "split_start": [],
        "split_step": [],
        "pending": [],
        "fail": [],
    }
    counts = {
        "platform": platform,
        "line_count": 0,
        "char_count": len(text),
        "warnings": 0,
        "errors": 0,
        "version_lines": [],
        "omitted": "日志输出过多" in text or "日志条数超过限制" in text or "以下日志省略" in text or "部分日志被省略" in text or "omitted" in text.lower(),
        "omitted_at": "",
    }
    for line in text.splitlines():
        counts["line_count"] += 1
        if "WARNING" in line or "WARN" in line:
            counts["warnings"] += 1
        if "ERROR" in line or "Traceback" in line:
            counts["errors"] += 1
        if "WUFU_THS_FAST_" in line or "WUFU_JQ_FIXED_POOL_" in line:
            counts["version_lines"].append(line.strip())
        if "日志条数超过限制" in line or "以下日志省略" in line or "部分日志被省略" in line:
            dt = DATE_TIME_RE.search(line)
            if dt:
                counts["omitted_at"] = f"{dt.group('date')} {dt.group('time')}"
        if "WUFU_DAILY_COMPACT" in line:
            m = DAILY_RE.search(line)
            if m:
                rows["daily"].append({
                    "date": m.group("date"),
                    "value": float(m.group("value")),
                    "weak": m.group("weak") == "True",
                    "pool": int(m.group("pool")),
                    "target": symbol6(m.group("target")),
                    "pending": m.group("pending"),
                    "position": pos_symbol(m.group("positions")),
                    "positions_raw": m.group("positions"),
                })
        if "WUFU_SIGNAL" in line:
            m = SIGNAL_RE.search(line)
            if m:
                rows["signals"].append({"date": m.group("date"), "target": symbol6(m.group("target")), "top10_raw": m.group("top10")})
        if "WUFU_MORNING" in line:
            m = JQ_MORNING_RE.search(line)
            if m:
                rows["morning"].append({"date": m.group("dt"), "weak": m.group("weak") == "True", "threshold": float(m.group("threshold")), "pool": int(m.group("pool"))})
        elif "morning date=" in line:
            m = THS_MORNING_RE.search(line)
            if m:
                rows["morning"].append({"date": m.group("date"), "weak": m.group("weak") == "True", "threshold": float(m.group("threshold")), "pool": int(m.group("pool"))})
        if "WUFU_WEAK_SOURCE" in line:
            m = WEAK_RE.search(line)
            if m:
                rows["weak"].append({"date": m.group("date"), "mode": m.group("mode"), "weak": m.group("weak") == "True", "source": m.group("source")})
        if "WUFU_STOP_LOSS" in line:
            m = STOP_RE.search(line)
            if m:
                rows["stop"].append({"date": m.group("dt")[:10], "dt": m.group("dt"), "code": symbol6(m.group("code"))})
        if "WUFU_ORDER_PLAN" in line:
            m = ORDER_RE.search(line)
            if m:
                rows["orders"].append({
                    "date": m.group("date"),
                    "mode": m.group("mode"),
                    "code": symbol6(m.group("code")),
                    "account_value": float(m.group("account_value")),
                    "buffered_value": float(m.group("buffered_value")),
                    "price": float(m.group("price")),
                    "shares": int(m.group("shares")),
                    "order_value": float(m.group("order_value")),
                })
        if "WUFU_SPLIT_START" in line:
            m = SPLIT_START_RE.search(line)
            if m:
                rows["split_start"].append({
                    "date": m.group("dt")[:10],
                    "dt": m.group("dt"),
                    "code": symbol6(m.group("code")),
                    "mode": m.group("mode"),
                    "shares": int(m.group("shares")),
                    "minute_volume": float(m.group("minute_volume")),
                    "cap_shares": int(m.group("cap_shares")),
                    "participation": float(m.group("participation")),
                    "splits": int(m.group("splits")),
                    "target_value": float(m.group("target_value")),
                })
        if "WUFU_SPLIT_STEP" in line:
            m = SPLIT_STEP_RE.search(line)
            if m:
                rows["split_step"].append({
                    "date": m.group("dt")[:10],
                    "dt": m.group("dt"),
                    "code": symbol6(m.group("code")),
                    "step": int(m.group("step")),
                    "splits": int(m.group("splits")),
                    "target_value": float(m.group("target_value")),
                    "rounded_value": float(m.group("rounded_value")),
                    "price": float(m.group("price")),
                    "shares": int(m.group("shares")),
                })
        if "WUFU_PENDING_BUY" in line:
            m = PENDING_RE.search(line)
            if m:
                rows["pending"].append({"date": m.group("dt")[:10], "dt": m.group("dt"), "mode": m.group("mode"), "bought": symbol6(m.group("bought")), "pending": symbol6(m.group("pending"))})
        if "WUFU_ORDER_FAIL" in line or "order failed" in line:
            dt = DATE_TIME_RE.search(line)
            rows["fail"].append({"date": dt.group("date") if dt else "", "line": line.strip()})
    return {name: pd.DataFrame(data) for name, data in rows.items()} | {"counts": counts}


def max_drawdown(values: pd.Series) -> float:
    if values.empty:
        return math.nan
    curve = values.astype(float)
    peak = curve.cummax()
    dd = curve / peak - 1.0
    return float(dd.min())


def summarize_platform(parsed: dict[str, pd.DataFrame | dict[str, object]]) -> dict[str, object]:
    daily = parsed["daily"]
    signals = parsed["signals"]
    stops = parsed["stop"]
    split_start = parsed["split_start"]
    split_step = parsed["split_step"]
    pending = parsed["pending"]
    counts = dict(parsed["counts"])
    summary = counts.copy()
    for key, frame in [
        ("daily", daily),
        ("signals", signals),
        ("stop", stops),
        ("split_start", split_start),
        ("split_step", split_step),
        ("pending", pending),
        ("weak_log", parsed["weak"]),
        ("morning", parsed["morning"]),
        ("orders", parsed["orders"]),
        ("fail", parsed["fail"]),
    ]:
        summary[f"{key}_count"] = int(len(frame))
    if not daily.empty:
        summary["daily_start"] = str(daily["date"].min())
        summary["daily_end"] = str(daily["date"].max())
        summary["total_return"] = float(daily["value"].iloc[-1] / daily["value"].iloc[0] - 1.0)
        summary["max_drawdown"] = max_drawdown(daily["value"])
        summary["final_value"] = float(daily["value"].iloc[-1])
        summary["target_changes"] = int((daily["target"] != daily["target"].shift()).sum())
    if not split_start.empty and not split_step.empty:
        step_counts = split_step.groupby(["date", "code"]).size().reset_index(name="steps")
        summary["split_completed_5_count"] = int((step_counts["steps"] >= 5).sum())
        summary["split_avg_steps"] = float(step_counts["steps"].mean())
        summary["split_mode_counts"] = split_start["mode"].value_counts().to_dict()
    return summary


def compare_frames(ths: dict[str, pd.DataFrame | dict[str, object]], jq: dict[str, pd.DataFrame | dict[str, object]]) -> dict[str, object]:
    ths_daily = ths["daily"].copy()
    jq_daily = jq["daily"].copy()
    merged = ths_daily.merge(jq_daily, on="date", how="outer", suffixes=("_ths", "_jq"), indicator=True).sort_values("date")
    both = merged[merged["_merge"] == "both"].copy()
    both["weak_match"] = both["weak_ths"] == both["weak_jq"]
    both["target_match"] = both["target_ths"] == both["target_jq"]
    both["position_match"] = both["position_ths"] == both["position_jq"]
    both["value_diff"] = both["value_ths"] - both["value_jq"]
    both["value_diff_pct"] = both["value_diff"] / both["value_jq"].replace(0, pd.NA)

    ths_stop_dates = set(ths["stop"]["date"].tolist()) if not ths["stop"].empty else set()
    jq_stop_dates = set(jq["stop"]["date"].tolist()) if not jq["stop"].empty else set()
    common_dates = set(both["date"].tolist())
    ths_stop_common = ths["stop"][ths["stop"]["date"].isin(common_dates)] if not ths["stop"].empty else ths["stop"]
    jq_stop_common = jq["stop"][jq["stop"]["date"].isin(common_dates)] if not jq["stop"].empty else jq["stop"]
    ths_stop_dates_common = set(ths_stop_common["date"].tolist()) if not ths_stop_common.empty else set()
    jq_stop_dates_common = set(jq_stop_common["date"].tolist()) if not jq_stop_common.empty else set()
    ths_split = ths["split_start"].copy()
    jq_split = jq["split_start"].copy()
    split_cmp = ths_split.merge(jq_split, on=["date", "code"], how="outer", suffixes=("_ths", "_jq"), indicator=True)
    split_cmp_common = split_cmp[split_cmp["date"].isin(common_dates)].copy() if len(split_cmp) else split_cmp

    result = {
        "intersection_days": int(len(both)),
        "ths_only_days": int((merged["_merge"] == "left_only").sum()),
        "jq_only_days": int((merged["_merge"] == "right_only").sum()),
        "weak_match_rate": float(both["weak_match"].mean()) if len(both) else math.nan,
        "target_match_rate": float(both["target_match"].mean()) if len(both) else math.nan,
        "position_match_rate": float(both["position_match"].mean()) if len(both) else math.nan,
        "value_diff_mean": float(both["value_diff"].mean()) if len(both) else math.nan,
        "value_diff_abs_median": float(both["value_diff"].abs().median()) if len(both) else math.nan,
        "value_diff_pct_final": float(both["value_diff_pct"].iloc[-1]) if len(both) else math.nan,
        "stop_ths_count": int(len(ths["stop"])),
        "stop_jq_count": int(len(jq["stop"])),
        "stop_count_diff_pct": float(abs(len(ths["stop"]) - len(jq["stop"])) / max(1, len(jq["stop"]))),
        "stop_date_overlap": int(len(ths_stop_dates & jq_stop_dates)),
        "stop_ths_common_count": int(len(ths_stop_common)),
        "stop_jq_common_count": int(len(jq_stop_common)),
        "stop_common_count_diff_pct": float(abs(len(ths_stop_common) - len(jq_stop_common)) / max(1, len(jq_stop_common))),
        "stop_ths_common_dates": int(len(ths_stop_dates_common)),
        "stop_jq_common_dates": int(len(jq_stop_dates_common)),
        "stop_common_date_overlap": int(len(ths_stop_dates_common & jq_stop_dates_common)),
        "split_start_match_rate": float((split_cmp["_merge"] == "both").mean()) if len(split_cmp) else math.nan,
        "split_start_common_match_rate": float((split_cmp_common["_merge"] == "both").mean()) if len(split_cmp_common) else math.nan,
        "split_start_ths_only": int((split_cmp["_merge"] == "left_only").sum()) if len(split_cmp) else 0,
        "split_start_jq_only": int((split_cmp["_merge"] == "right_only").sum()) if len(split_cmp) else 0,
        "split_start_common_ths_only": int((split_cmp_common["_merge"] == "left_only").sum()) if len(split_cmp_common) else 0,
        "split_start_common_jq_only": int((split_cmp_common["_merge"] == "right_only").sum()) if len(split_cmp_common) else 0,
    }
    return {"summary": result, "daily_compare": both, "split_compare": split_cmp}


def pct(value: float) -> str:
    if value is None or pd.isna(value):
        return "NA"
    return f"{value * 100:.2f}%"


def money(value: float) -> str:
    if value is None or pd.isna(value):
        return "NA"
    return f"{value:,.2f}"


def write_report(ths: dict[str, object], jq: dict[str, object], cmp: dict[str, object]) -> None:
    s = cmp["summary"]
    target_ok = s["target_match_rate"] >= 0.98
    weak_ok = s["weak_match_rate"] >= 0.99
    stop_ok = s["stop_common_count_diff_pct"] < 0.05
    ths_full = ths["daily_count"] >= jq["daily_count"] * 0.99 and ths.get("daily_end") == jq.get("daily_end")

    verdict = "V12-C 同步验收基本达成" if all([target_ok, weak_ok, stop_ok, ths_full]) else "V12-C 仍未完全达到验收线"
    md = f"""# 五福 ETF V12-C 双平台日志对照报告

## 结论

{verdict}。

- 同花顺 compact 覆盖：{ths.get('daily_start')} 到 {ths.get('daily_end')}，{ths['daily_count']} 天；聚宽为 {jq.get('daily_start')} 到 {jq.get('daily_end')}，{jq['daily_count']} 天。
- 同花顺日志省略：{ths.get('omitted')}，省略触发点：{ths.get('omitted_at') or 'NA'}。
- 弱市匹配率：{pct(s['weak_match_rate'])}，验收线 99%。
- 目标匹配率：{pct(s['target_match_rate'])}，验收线 98%。
- 共同周期止损次数：同花顺 {s['stop_ths_common_count']} 次，聚宽 {s['stop_jq_common_count']} 次，差异 {pct(s['stop_common_count_diff_pct'])}，验收线小于 5%。
- 分批成交：同花顺触发 {ths['split_start_count']} 次，聚宽触发 {jq['split_start_count']} 次；共同周期按日期和标的匹配率 {pct(s['split_start_common_match_rate'])}。

## 日志完整性

| 指标 | 同花顺 | 聚宽 |
|---|---:|---:|
| 日志行数 | {ths['line_count']} | {jq['line_count']} |
| 日志字符数 | {ths['char_count']} | {jq['char_count']} |
| 日终 compact | {ths['daily_count']} | {jq['daily_count']} |
| 信号日志 | {ths['signals_count']} | {jq['signals_count']} |
| 弱市源日志 | {ths['weak_log_count']} | {jq['weak_log_count']} |
| pending 日志 | {ths['pending_count']} | {jq['pending_count']} |
| 错误数 | {ths['errors']} | {jq['errors']} |
| 警告数 | {ths['warnings']} | {jq['warnings']} |
| 是否触发省略 | {ths.get('omitted')} | {jq.get('omitted')} |

解读：V12-C 的 compact 主线比 V12-B 更有效，截断点从 2024-12-16 推迟到 2025-03-24，但仍没有全周期覆盖。关键原因不是策略报错，而是同花顺平台日志条数上限触发省略；下一版必须继续减日志。

## 同步效果

| 指标 | 数值 |
|---|---:|
| 共同交易日 | {s['intersection_days']} |
| 同花顺独有日 | {s['ths_only_days']} |
| 聚宽独有日 | {s['jq_only_days']} |
| 弱市匹配率 | {pct(s['weak_match_rate'])} |
| 目标匹配率 | {pct(s['target_match_rate'])} |
| 日终持仓标的匹配率 | {pct(s['position_match_rate'])} |
| 日终资产均值差 | {money(s['value_diff_mean'])} |
| 日终资产差异中位数 | {money(s['value_diff_abs_median'])} |
| 最后共同日资产差异比例 | {pct(s['value_diff_pct_final'])} |
| 共同周期止损次数差异 | {pct(s['stop_common_count_diff_pct'])} |
| 共同周期止损日期重合 | {s['stop_common_date_overlap']} / {max(s['stop_ths_common_dates'], s['stop_jq_common_dates'])} |

## 收益表现

| 指标 | 同花顺 | 聚宽 |
|---|---:|---:|
| 期末资产 | {money(ths.get('final_value'))} | {money(jq.get('final_value'))} |
| 总收益 | {pct(ths.get('total_return'))} | {pct(jq.get('total_return'))} |
| 最大回撤 | {pct(ths.get('max_drawdown'))} | {pct(jq.get('max_drawdown'))} |

收益差异现在还不能单独作为策略优劣结论。若 compact 覆盖、目标、弱市、止损和分批事件仍有差异，收益差异主要反映平台执行规则和日志截断，而不是策略本身。

## 分批成交效果

| 指标 | 同花顺 | 聚宽 |
|---|---:|---:|
| 分批开始次数 | {ths['split_start_count']} | {jq['split_start_count']} |
| 分批步骤日志 | {ths['split_step_count']} | {jq['split_step_count']} |
| 平均步骤数 | {ths.get('split_avg_steps', 'NA')} | {jq.get('split_avg_steps', 'NA')} |
| 完成 5 步事件 | {ths.get('split_completed_5_count', 0)} | {jq.get('split_completed_5_count', 0)} |

V12-C 已经把“容量问题”从隐形的平台成交失败，变成了显式的 `WUFU_SPLIT_START/WUFU_SPLIT_STEP` 可审计事件。这一版最重要的价值是定位同花顺 25% 成交量限制到底发生在哪些日子、哪些标的、分批后是否仍然少成交。

共同周期内，分批开始事件按日期和标的匹配率为 {pct(s['split_start_common_match_rate'])}，明显高于全日志口径的 {pct(s['split_start_match_rate'])}。全日志口径较低主要由同花顺 2025-03-24 后日志省略造成。

## 主要问题

1. `WUFU_PENDING_BUY` 仍然偏多。趋势等待日会在 13:11、13:40、14:10、14:30、14:40 多次输出，Ultra Compact 还可以继续压缩。本次同花顺在 2025-03-24 13:15 触发“日志条数超过限制，以下日志省略”。
2. 聚宽 `WUFU_DAILY_COMPACT` 的 pool 字段为 0，原因是聚宽脚本日终读取的是 `filtered_etf_list`，但实际池子字段是 `merged_etf_pool`。这不影响目标匹配，但影响池子审计。
3. 分批容量按“当前分钟成交量 25%”判断。若同花顺平台实际按全天成交量或不同成交撮合口径限制，分批事件会匹配，但实际成交仍可能不同。
4. 聚宽有 19 条平台订单错误，主要是停牌、资金不足和分批后最后几步取整边界，不是策略中断。下一版应增加分批现金缓冲和完成态审计。
5. 聚宽仍有 pandas/numpy 的无效值 warning，主要来自价格序列中存在 NaN，不影响本轮主流程，但下一版应清洗后再计算动量。

## 下个版本优化路径

### V12-D：日志极简验收版

- 默认只输出 `WUFU_DAILY_COMPACT`、`WUFU_STOP_LOSS`、`WUFU_SPLIT_START`、最后一步 `WUFU_SPLIT_DONE`、`WUFU_ORDER_FAIL`。
- `WUFU_PENDING_BUY` 改为只在状态变化时输出：首次进入等待、成功买入、强制买入、收盘仍未买入。
- 聚宽日终 pool 字段改为 `len(g.merged_etf_pool)`。

### V12-E：容量真实成交版

- 同花顺分批从固定 5 分钟改为“按剩余目标和当前分钟容量动态切片”，每分钟目标不超过 `minute_volume * participation * price`。
- 输出 `WUFU_SPLIT_DONE`：计划金额、最终目标金额、平台实际持仓、缺口比例。
- 对缺口超过 2% 的日期单独生成执行差异表。

### V12-F：收益验收版

- 在弱市 99%+、目标 98%+、止损差异小于 5%、分批事件匹配后，再比较收益。
- 收益差异拆成四类：价格源差、成交量容量差、100 份取整差、费用滑点差。

## 输出文件

- 汇总 JSON：`reports/ths_jq_v12c_latest_summary.json`
- 日终对比 CSV：`reports/ths_jq_v12c_latest_daily_compare.csv`
- 分批事件 CSV：`reports/ths_jq_v12c_latest_split_compare.csv`
- Markdown 报告：`reports/ths_jq_v12c_latest_report.md`
- HTML 报告：`reports/ths_jq_v12c_latest_report.html`
"""
    md_path = OUT_PREFIX.with_name(OUT_PREFIX.name + "_report.md")
    html_path = OUT_PREFIX.with_name(OUT_PREFIX.name + "_report.html")
    md_path.write_text(md, encoding="utf-8")
    body = "\n".join(
        f"<p>{html.escape(line)}</p>" if line and not line.startswith("|") and not line.startswith("#")
        else (f"<h1>{html.escape(line[2:])}</h1>" if line.startswith("# ") else f"<h2>{html.escape(line[3:])}</h2>" if line.startswith("## ") else f"<pre>{html.escape(line)}</pre>" if line.startswith("|") else "")
        for line in md.splitlines()
    )
    html_doc = f"<!doctype html><html><head><meta charset='utf-8'><title>V12-C Report</title><style>body{{font-family:Arial,'Microsoft YaHei',sans-serif;max-width:1100px;margin:32px auto;line-height:1.65;color:#1f2937}}h1,h2{{color:#111827}}pre{{background:#f8fafc;padding:8px;border-radius:6px;white-space:pre-wrap}}code{{background:#eef2ff;padding:1px 4px;border-radius:4px}}</style></head><body>{body}</body></html>"
    html_path.write_text(html_doc, encoding="utf-8")


def main() -> None:
    ths_text = THS_LOG.read_text(encoding="utf-8", errors="ignore")
    jq_text = read_zip(JQ_ZIP)
    ths = parse_log(ths_text, "ths")
    jq = parse_log(jq_text, "jq")
    ths_summary = summarize_platform(ths)
    jq_summary = summarize_platform(jq)
    cmp = compare_frames(ths, jq)

    ths["daily"].to_csv(OUT_PREFIX.with_name(OUT_PREFIX.name + "_ths_daily.csv"), index=False, encoding="utf-8-sig")
    jq["daily"].to_csv(OUT_PREFIX.with_name(OUT_PREFIX.name + "_jq_daily.csv"), index=False, encoding="utf-8-sig")
    cmp["daily_compare"].to_csv(OUT_PREFIX.with_name(OUT_PREFIX.name + "_daily_compare.csv"), index=False, encoding="utf-8-sig")
    cmp["split_compare"].to_csv(OUT_PREFIX.with_name(OUT_PREFIX.name + "_split_compare.csv"), index=False, encoding="utf-8-sig")
    summary = {"ths": ths_summary, "jq": jq_summary, "compare": cmp["summary"]}
    OUT_PREFIX.with_name(OUT_PREFIX.name + "_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(ths_summary, jq_summary, cmp)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
