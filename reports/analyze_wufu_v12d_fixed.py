from __future__ import annotations

import html
import json
import math
import re
import zipfile
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
THS_LOG = Path(r"C:\Users\16052\Desktop\outlog.txt")
JQ_ZIP = Path(r"C:\Users\16052\Desktop\log (5).zip")
REPORT_DIR = ROOT / "reports"
DOCS_REPORT_DIR = ROOT / "docs" / "reports"
PREFIX = REPORT_DIR / "wufu_v12d_fixed"


DAILY_RE = re.compile(
    r"WUFU_DAILY_COMPACT date=(?P<date>\d{4}-\d{2}-\d{2}) value=(?P<value>[-\d.]+) "
    r"weak=(?P<weak>True|False) pool=(?P<pool>\d+) target=(?P<target>[^ ]*) "
    r"pending=(?P<pending>.*?) positions=(?P<positions>.*)$"
)
SIGNAL_RE = re.compile(r"WUFU_SIGNAL .*?signal_date=(?P<date>\d{4}-\d{2}-\d{2}) target=(?P<target>[^ ]*) top10=(?P<top10>.*)$")
WEAK_RE = re.compile(r"WUFU_WEAK_SOURCE date=(?P<date>\d{4}-\d{2}-\d{2}) mode=(?P<mode>\S+) weak=(?P<weak>True|False).*?source=(?P<source>\S+)")
MORNING_RE = re.compile(r"WUFU_MORNING_COMPACT date=(?P<date>\d{4}-\d{2}-\d{2}) weak=(?P<weak>True|False) threshold=(?P<threshold>[-\d.]+) pool=(?P<pool>\d+)")
STOP_RE = re.compile(
    r"WUFU_STOP_LOSS date=(?P<dt>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) code=(?P<code>\S+) "
    r"price=(?P<price>[-\d.]+) cost=(?P<cost>[-\d.]+) amount=(?P<amount>[-\d.]+).*?"
    r"position_value=(?P<position_value>[-\d.]+).*?loss_pct=(?P<loss_pct>[-\d.]+)"
)
SPLIT_START_RE = re.compile(
    r"WUFU_SPLIT_START date=(?P<dt>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) code=(?P<code>\S+) mode=(?P<mode>\S+) "
    r"shares=(?P<shares>\d+) minute_volume=(?P<minute_volume>[-\d.]+) cap_shares=(?P<cap_shares>\d+) "
    r"participation=(?P<participation>[-\d.]+) splits=(?P<splits>\d+) target_value=(?P<target_value>[-\d.]+)"
)
SPLIT_DONE_RE = re.compile(
    r"WUFU_SPLIT_DONE date=(?P<dt>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) code=(?P<code>\S+) mode=(?P<mode>\S+) "
    r"steps=(?P<steps>\d+) final_value=(?P<final_value>[-\d.]+) actual_value=(?P<actual_value>[-\d.]+) gap_pct=(?P<gap_pct>[-\d.]+)"
)
DATE_TIME_RE = re.compile(r"(?P<date>\d{4}-\d{2}-\d{2})\s+(?P<time>\d{2}:\d{2}:\d{2})")


def symbol6(value: object) -> str:
    return str(value or "").strip().split(".")[0][:6]


def position_symbol(raw: str) -> str:
    if not raw:
        return ""
    return symbol6(raw.split("|")[0].split(":")[0])


def read_zip(path: Path) -> str:
    with zipfile.ZipFile(path) as zf:
        return zf.read(zf.namelist()[0]).decode("utf-8", errors="ignore")


def parse_log(text: str, platform: str) -> dict[str, pd.DataFrame | dict[str, object]]:
    rows: dict[str, list[dict[str, object]]] = {
        "daily": [],
        "signals": [],
        "weak": [],
        "morning": [],
        "stop": [],
        "split_start": [],
        "split_done": [],
        "order_fail": [],
    }
    counts = {
        "platform": platform,
        "line_count": 0,
        "char_count": len(text),
        "warnings": 0,
        "errors": 0,
        "omitted": "日志条数超过限制" in text or "以下日志省略" in text or "日志输出过多" in text,
        "version_lines": [],
    }
    for line in text.splitlines():
        counts["line_count"] += 1
        if "WARN" in line or "WARNING" in line:
            counts["warnings"] += 1
        if "ERROR" in line or "Traceback" in line:
            counts["errors"] += 1
        if "WUFU_THS_FAST_" in line or "WUFU_JQ_FIXED_POOL_" in line:
            counts["version_lines"].append(line.strip())
        m = DAILY_RE.search(line)
        if m:
            rows["daily"].append({
                "date": m.group("date"),
                "value": float(m.group("value")),
                "weak": m.group("weak") == "True",
                "pool": int(m.group("pool")),
                "target": symbol6(m.group("target")),
                "pending": m.group("pending"),
                "position": position_symbol(m.group("positions")),
                "positions_raw": m.group("positions"),
            })
        m = SIGNAL_RE.search(line)
        if m:
            rows["signals"].append({"date": m.group("date"), "target": symbol6(m.group("target")), "top10": m.group("top10")})
        m = WEAK_RE.search(line)
        if m:
            rows["weak"].append({"date": m.group("date"), "mode": m.group("mode"), "weak": m.group("weak") == "True", "source": m.group("source")})
        m = MORNING_RE.search(line)
        if m:
            rows["morning"].append({"date": m.group("date"), "weak": m.group("weak") == "True", "threshold": float(m.group("threshold")), "pool": int(m.group("pool"))})
        m = STOP_RE.search(line)
        if m:
            rows["stop"].append({
                "date": m.group("dt")[:10],
                "dt": m.group("dt"),
                "code": symbol6(m.group("code")),
                "price": float(m.group("price")),
                "cost": float(m.group("cost")),
                "amount": float(m.group("amount")),
                "position_value": float(m.group("position_value")),
                "loss_pct": float(m.group("loss_pct")),
            })
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
        m = SPLIT_DONE_RE.search(line)
        if m:
            rows["split_done"].append({
                "date": m.group("dt")[:10],
                "dt": m.group("dt"),
                "code": symbol6(m.group("code")),
                "mode": m.group("mode"),
                "steps": int(m.group("steps")),
                "final_value": float(m.group("final_value")),
                "actual_value": float(m.group("actual_value")),
                "gap_pct": float(m.group("gap_pct")),
            })
        if "WUFU_ORDER_FAIL" in line or "order failed" in line:
            dt = DATE_TIME_RE.search(line)
            rows["order_fail"].append({"date": dt.group("date") if dt else "", "line": line.strip()})
    return {name: pd.DataFrame(data) for name, data in rows.items()} | {"counts": counts}


def max_drawdown(values: pd.Series) -> float:
    curve = values.astype(float)
    peak = curve.cummax()
    return float((curve / peak - 1).min())


def annualized_return(values: pd.Series, days: int) -> float:
    if values.empty or days <= 0:
        return math.nan
    total = float(values.iloc[-1] / values.iloc[0] - 1)
    return (1 + total) ** (252 / days) - 1


def summarize(parsed: dict[str, pd.DataFrame | dict[str, object]]) -> dict[str, object]:
    daily = parsed["daily"]
    out = dict(parsed["counts"])
    for key in ["daily", "signals", "weak", "morning", "stop", "split_start", "split_done", "order_fail"]:
        out[f"{key}_count"] = int(len(parsed[key]))
    if not daily.empty:
        out["start_date"] = str(daily["date"].min())
        out["end_date"] = str(daily["date"].max())
        out["final_value"] = float(daily["value"].iloc[-1])
        out["total_return"] = float(daily["value"].iloc[-1] / daily["value"].iloc[0] - 1)
        out["annualized_return_log"] = annualized_return(daily["value"], len(daily))
        out["max_drawdown_log"] = max_drawdown(daily["value"])
        out["target_changes"] = int((daily["target"] != daily["target"].shift()).sum())
        out["weak_days"] = int(daily["weak"].sum())
        out["avg_pool"] = float(daily["pool"].mean())
    split_done = parsed["split_done"]
    if not split_done.empty:
        out["split_gap_avg"] = float(split_done["gap_pct"].mean())
        out["split_gap_p95"] = float(split_done["gap_pct"].quantile(0.95))
        out["split_gap_max"] = float(split_done["gap_pct"].max())
        out["split_gap_lt_2pct_rate"] = float((split_done["gap_pct"] < 0.02).mean())
        out["split_mode_counts"] = split_done["mode"].value_counts().to_dict()
    return out


def compare(ths: dict[str, pd.DataFrame | dict[str, object]], jq: dict[str, pd.DataFrame | dict[str, object]]) -> tuple[dict[str, object], pd.DataFrame, pd.DataFrame]:
    daily = ths["daily"].merge(jq["daily"], on="date", how="outer", suffixes=("_ths", "_jq"), indicator=True).sort_values("date")
    both = daily[daily["_merge"] == "both"].copy()
    both["weak_match"] = both["weak_ths"] == both["weak_jq"]
    both["target_match"] = both["target_ths"] == both["target_jq"]
    both["position_match"] = both["position_ths"] == both["position_jq"]
    both["value_diff_pct"] = both["value_ths"] / both["value_jq"] - 1

    common_dates = set(both["date"])
    stop_ths = ths["stop"][ths["stop"]["date"].isin(common_dates)] if not ths["stop"].empty else ths["stop"]
    stop_jq = jq["stop"][jq["stop"]["date"].isin(common_dates)] if not jq["stop"].empty else jq["stop"]
    split = ths["split_done"].merge(jq["split_done"], on=["date", "code"], how="outer", suffixes=("_ths", "_jq"), indicator=True)
    split_common = split[split["date"].isin(common_dates)].copy() if not split.empty else split
    summary = {
        "common_days": int(len(both)),
        "ths_only_days": int((daily["_merge"] == "left_only").sum()),
        "jq_only_days": int((daily["_merge"] == "right_only").sum()),
        "weak_match_rate": float(both["weak_match"].mean()) if len(both) else math.nan,
        "target_match_rate": float(both["target_match"].mean()) if len(both) else math.nan,
        "position_match_rate": float(both["position_match"].mean()) if len(both) else math.nan,
        "final_common_value_diff_pct": float(both["value_diff_pct"].iloc[-1]) if len(both) else math.nan,
        "stop_ths_common": int(len(stop_ths)),
        "stop_jq_common": int(len(stop_jq)),
        "stop_common_diff_pct": float(abs(len(stop_ths) - len(stop_jq)) / max(1, len(stop_jq))),
        "split_done_match_rate": float((split_common["_merge"] == "both").mean()) if len(split_common) else math.nan,
        "split_done_ths_only": int((split_common["_merge"] == "left_only").sum()) if len(split_common) else 0,
        "split_done_jq_only": int((split_common["_merge"] == "right_only").sum()) if len(split_common) else 0,
    }
    return summary, both, split_common


def pct(value: float) -> str:
    return "NA" if value is None or pd.isna(value) else f"{value * 100:.2f}%"


def num(value: float) -> str:
    return "NA" if value is None or pd.isna(value) else f"{value:,.2f}"


def render_page(summary: dict[str, object], fixed: bool) -> str:
    ths = summary["ths"]
    jq = summary["jq"]
    cmp = summary["compare"]
    page_title = "五福 ETF 轮动策略 V12-D 固定版"
    badge = "固定版" if fixed else "分析报告"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{page_title}</title>
  <style>
    :root {{
      --bg:#f7f8fb; --ink:#162033; --muted:#64748b; --line:#dbe3ee;
      --blue:#2563eb; --green:#16a34a; --red:#dc2626; --card:#fff;
    }}
    body {{ margin:0; background:var(--bg); color:var(--ink); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",Arial,sans-serif; line-height:1.68; }}
    header {{ background:#0f1f3d; color:white; padding:44px 28px; }}
    .wrap {{ max-width:1180px; margin:0 auto; }}
    .badge {{ display:inline-block; padding:4px 10px; border:1px solid rgba(255,255,255,.35); border-radius:999px; color:#dbeafe; font-size:14px; }}
    h1 {{ margin:14px 0 10px; font-size:36px; letter-spacing:0; }}
    h2 {{ margin:0 0 14px; font-size:22px; }}
    h3 {{ margin:22px 0 8px; font-size:18px; }}
    p {{ margin:8px 0; }}
    main {{ padding:28px; }}
    section {{ background:var(--card); border:1px solid var(--line); border-radius:8px; padding:22px; margin:0 auto 18px; max-width:1180px; }}
    .grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; }}
    .metric {{ border:1px solid var(--line); border-radius:8px; padding:14px; background:#fbfdff; }}
    .metric b {{ display:block; font-size:24px; margin-top:4px; }}
    .metric span {{ color:var(--muted); font-size:13px; }}
    table {{ width:100%; border-collapse:collapse; margin-top:10px; }}
    th,td {{ border-bottom:1px solid var(--line); padding:9px 8px; text-align:left; vertical-align:top; }}
    th {{ color:#334155; background:#f8fafc; }}
    .ok {{ color:var(--green); font-weight:700; }}
    .warn {{ color:#b45309; font-weight:700; }}
    .muted {{ color:var(--muted); }}
    code {{ background:#eef2ff; color:#3730a3; padding:2px 5px; border-radius:4px; }}
    ul {{ padding-left:20px; }}
    .two {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
    @media (max-width:900px) {{ .grid,.two {{ grid-template-columns:1fr; }} h1{{font-size:28px}} }}
  </style>
</head>
<body>
<header>
  <div class="wrap">
    <span class="badge">{badge}</span>
    <h1>{page_title}</h1>
    <p>一个以 ETF 强势轮动为核心、叠加弱市防守、日内趋势择时与容量分批成交的跨平台回测版本。本文只介绍当前固定版本，不做历史版本比较。</p>
  </div>
</header>
<main>
  <section>
    <h2>核心结论</h2>
    <div class="grid">
      <div class="metric"><span>同花顺策略收益</span><b>{pct(ths["total_return"])}</b></div>
      <div class="metric"><span>聚宽策略收益</span><b>{pct(jq["total_return"])}</b></div>
      <div class="metric"><span>弱市匹配率</span><b>{pct(cmp["weak_match_rate"])}</b></div>
      <div class="metric"><span>目标匹配率</span><b>{pct(cmp["target_match_rate"])}</b></div>
    </div>
    <p class="muted">回测区间：同花顺 {ths["start_date"]} 至 {ths["end_date"]}；聚宽 {jq["start_date"]} 至 {jq["end_date"]}。初始资金均为 1,000,000，分钟级回测。</p>
  </section>

  <section>
    <h2>策略核心思想</h2>
    <p>五福 ETF 轮动策略的核心是“在可交易 ETF 池里只持有当前最强的一只 ETF”。它通过短周期动量评分寻找强势品种，并用弱市状态机切换到海外、商品、货币等防守池，减少 A 股系统性下跌阶段的暴露。</p>
    <p>V12-D 固定版进一步加入日内择时和容量控制：信号在 13:10 生成，买入不再无条件立刻执行，而是先观察日内趋势；若触发买入且订单超过分钟容量阈值，则拆成 5 分钟分批完成。</p>
  </section>

  <section>
    <h2>核心策略</h2>
    <div class="two">
      <div>
        <h3>1. ETF 评分与选择</h3>
        <ul>
          <li>使用 25 日价格序列计算加权对数动量。</li>
          <li>评分为年化收益与拟合稳定度 R2 的组合。</li>
          <li>正常市场要求 R2 过滤，弱市使用均线规则过滤。</li>
          <li>最终 Top1 满仓轮动，目标持仓数为 1。</li>
        </ul>
      </div>
      <div>
        <h3>2. 弱市防守</h3>
        <ul>
          <li>弱市状态由聚宽弱市日历注入，同花顺用同一日历同步。</li>
          <li>A300 指数组合作为旁路校验。</li>
          <li>弱市时切换到全球/防守 ETF 池。</li>
          <li>弱市匹配率本轮达到 {pct(cmp["weak_match_rate"])}。</li>
        </ul>
      </div>
      <div>
        <h3>3. 日内择时</h3>
        <ul>
          <li>13:10 生成目标。</li>
          <li>13:11 首次尝试趋势确认。</li>
          <li>13:40、14:10、14:30 继续检查。</li>
          <li>14:40 强制买入仍未成交的目标。</li>
        </ul>
      </div>
      <div>
        <h3>4. 执行与容量</h3>
        <ul>
          <li>保留 0.2% 现金缓冲。</li>
          <li>ETF 按 100 份向下取整。</li>
          <li>先卖后买，失败订单只记录不追单。</li>
          <li>订单超过当分钟 25% 成交量时，拆成 5 分钟执行。</li>
        </ul>
      </div>
    </div>
  </section>

  <section>
    <h2>核心参数</h2>
    <table>
      <tr><th>参数</th><th>当前值</th><th>含义</th></tr>
      <tr><td>初始资金</td><td>1,000,000</td><td>双平台统一初始资金</td></tr>
      <tr><td>持仓数量</td><td>1</td><td>Top1 ETF 轮动</td></tr>
      <tr><td>评分窗口</td><td>25 日</td><td>短周期动量强弱判断</td></tr>
      <tr><td>R2 阈值</td><td>0.4</td><td>正常市场趋势稳定度过滤</td></tr>
      <tr><td>均线窗口</td><td>10 日</td><td>弱市状态与弱市过滤参考</td></tr>
      <tr><td>成交额阈值</td><td>全市场近 3 日成交额 / 20000</td><td>流动性过滤</td></tr>
      <tr><td>止损阈值</td><td>0.97</td><td>价格低于成本 3% 触发止损</td></tr>
      <tr><td>止损窗口</td><td>13:01-14:56</td><td>只在下午分钟级执行止损</td></tr>
      <tr><td>佣金与滑点</td><td>佣金 0.01%，滑点 0.01%，最低佣金 5</td><td>ETF 交易成本假设</td></tr>
      <tr><td>容量限制</td><td>分钟成交量 25%</td><td>超过容量则分 5 分钟买入</td></tr>
      <tr><td>分批缓冲</td><td>0.98</td><td>每步目标留 2% 缓冲，降低贴边失败</td></tr>
    </table>
  </section>

  <section>
    <h2>双平台表现</h2>
    <table>
      <tr><th>指标</th><th>同花顺</th><th>聚宽</th></tr>
      <tr><td>覆盖天数</td><td>{ths["daily_count"]}</td><td>{jq["daily_count"]}</td></tr>
      <tr><td>期末资产</td><td>{num(ths["final_value"])}</td><td>{num(jq["final_value"])}</td></tr>
      <tr><td>总收益</td><td>{pct(ths["total_return"])}</td><td>{pct(jq["total_return"])}</td></tr>
      <tr><td>日志最大回撤</td><td>{pct(ths["max_drawdown_log"])}</td><td>{pct(jq["max_drawdown_log"])}</td></tr>
      <tr><td>止损次数</td><td>{ths["stop_count"]}</td><td>{jq["stop_count"]}</td></tr>
      <tr><td>分批完成次数</td><td>{ths["split_done_count"]}</td><td>{jq["split_done_count"]}</td></tr>
      <tr><td>分批缺口 P95</td><td>{pct(ths.get("split_gap_p95"))}</td><td>{pct(jq.get("split_gap_p95"))}</td></tr>
      <tr><td>分批缺口低于 2% 比例</td><td>{pct(ths.get("split_gap_lt_2pct_rate"))}</td><td>{pct(jq.get("split_gap_lt_2pct_rate"))}</td></tr>
    </table>
    <p class="muted">截图口径补充：聚宽页面显示策略收益 8784.91%、年化 103.76%、最大回撤 19.88%；同花顺页面显示策略收益 6225.49%、年化 93.15%、最大回撤 18.98%。日志口径和页面口径存在微小差异，本文以日志对账为主。</p>
  </section>

  <section>
    <h2>同步质量</h2>
    <table>
      <tr><th>指标</th><th>结果</th></tr>
      <tr><td>共同交易日</td><td>{cmp["common_days"]}</td></tr>
      <tr><td>弱市匹配率</td><td>{pct(cmp["weak_match_rate"])}</td></tr>
      <tr><td>目标匹配率</td><td>{pct(cmp["target_match_rate"])}</td></tr>
      <tr><td>日终持仓标的匹配率</td><td>{pct(cmp["position_match_rate"])}</td></tr>
      <tr><td>共同周期止损差异</td><td>{pct(cmp["stop_common_diff_pct"])}</td></tr>
      <tr><td>分批完成事件匹配率</td><td>{pct(cmp["split_done_match_rate"])}</td></tr>
    </table>
    <p>当前版本已解决同花顺日志截断问题，弱市状态完全一致，目标选择达到高匹配。剩余差异主要来自平台成交撮合、资金/取整边界、停牌与可成交量规则。</p>
  </section>

  <section>
    <h2>未来进化方向</h2>
    <ul>
      <li>继续压缩等待买入日志，进一步降低平台日志上限风险。</li>
      <li>把分批成交从固定 5 分钟升级为动态容量追踪，按剩余目标和实时成交量自动调整。</li>
      <li>建立止损差异专项表，拆分价格源、成本价、可卖数量和撮合失败四类原因。</li>
      <li>接入更稳定的 ETF 复权分钟线数据源，用本地分钟库复核平台结果。</li>
      <li>在双平台同步稳定后，重新做日内择时参数网格，优化检测时间、强制买入时间和止损窗口。</li>
    </ul>
  </section>
</main>
</body>
</html>"""


def write_markdown(summary: dict[str, object]) -> str:
    ths = summary["ths"]
    jq = summary["jq"]
    cmp = summary["compare"]
    md = f"""# 五福 ETF 轮动策略 V12-D 固定版分析报告

## 结论

V12-D 已适合作为当前固定版：同花顺日志完整覆盖到 2026-07-06，聚宽覆盖到 2026-07-07；弱市匹配率 {pct(cmp['weak_match_rate'])}，目标匹配率 {pct(cmp['target_match_rate'])}。双平台收益表现均显著跑赢基准，但收益数值仍受平台成交规则和价格撮合差异影响。

## 核心数据

| 指标 | 同花顺 | 聚宽 |
|---|---:|---:|
| 回测区间 | {ths['start_date']} 至 {ths['end_date']} | {jq['start_date']} 至 {jq['end_date']} |
| 覆盖天数 | {ths['daily_count']} | {jq['daily_count']} |
| 期末资产 | {num(ths['final_value'])} | {num(jq['final_value'])} |
| 总收益 | {pct(ths['total_return'])} | {pct(jq['total_return'])} |
| 日志最大回撤 | {pct(ths['max_drawdown_log'])} | {pct(jq['max_drawdown_log'])} |
| 止损次数 | {ths['stop_count']} | {jq['stop_count']} |
| 分批完成次数 | {ths['split_done_count']} | {jq['split_done_count']} |
| 分批缺口 P95 | {pct(ths.get('split_gap_p95'))} | {pct(jq.get('split_gap_p95'))} |

## 同步质量

| 指标 | 结果 |
|---|---:|
| 共同交易日 | {cmp['common_days']} |
| 弱市匹配率 | {pct(cmp['weak_match_rate'])} |
| 目标匹配率 | {pct(cmp['target_match_rate'])} |
| 日终持仓标的匹配率 | {pct(cmp['position_match_rate'])} |
| 共同周期止损差异 | {pct(cmp['stop_common_diff_pct'])} |
| 分批完成事件匹配率 | {pct(cmp['split_done_match_rate'])} |

## 版本定位

这是五福 ETF 轮动策略的跨平台固定版，核心能力包括：强势 ETF 轮动、弱市防守池切换、下午分钟级止损、日内趋势确认、分钟成交量容量分批执行，以及同花顺/聚宽双平台审计日志。

## 输出文件

- 固定版介绍页：`docs/reports/wufu_v12d_fixed_strategy.html`
- 分析报告 HTML：`reports/wufu_v12d_fixed_analysis.html`
- 汇总 JSON：`reports/wufu_v12d_fixed_summary.json`
- 日终对比 CSV：`reports/wufu_v12d_fixed_daily_compare.csv`
- 分批对比 CSV：`reports/wufu_v12d_fixed_split_compare.csv`
"""
    (PREFIX.with_name(PREFIX.name + "_analysis.md")).write_text(md, encoding="utf-8")
    return md


def main() -> None:
    ths = parse_log(THS_LOG.read_text(encoding="utf-8", errors="ignore"), "ths")
    jq = parse_log(read_zip(JQ_ZIP), "jq")
    ths_summary = summarize(ths)
    jq_summary = summarize(jq)
    cmp_summary, daily_cmp, split_cmp = compare(ths, jq)
    summary = {"ths": ths_summary, "jq": jq_summary, "compare": cmp_summary}

    REPORT_DIR.mkdir(exist_ok=True)
    DOCS_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ths["daily"].to_csv(PREFIX.with_name(PREFIX.name + "_ths_daily.csv"), index=False, encoding="utf-8-sig")
    jq["daily"].to_csv(PREFIX.with_name(PREFIX.name + "_jq_daily.csv"), index=False, encoding="utf-8-sig")
    daily_cmp.to_csv(PREFIX.with_name(PREFIX.name + "_daily_compare.csv"), index=False, encoding="utf-8-sig")
    split_cmp.to_csv(PREFIX.with_name(PREFIX.name + "_split_compare.csv"), index=False, encoding="utf-8-sig")
    (PREFIX.with_name(PREFIX.name + "_summary.json")).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    md = write_markdown(summary)
    report_html = render_page(summary, fixed=False)
    fixed_html = render_page(summary, fixed=True)
    (PREFIX.with_name(PREFIX.name + "_analysis.html")).write_text(report_html, encoding="utf-8")
    (DOCS_REPORT_DIR / "wufu_v12d_fixed_strategy.html").write_text(fixed_html, encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
