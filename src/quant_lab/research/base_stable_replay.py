from __future__ import annotations

import ast
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


BASE_OUTPUT_DIR = Path(r"C:\Users\16052\Documents\Codex\2026-07-01\new-chat\outputs")
BASE_SCRIPT = BASE_OUTPUT_DIR / "核心动态承接_同花顺100x框架_0931_基础稳定版_clean.py"
DAILY_CACHE = BASE_OUTPUT_DIR / "capacity_substitution_experiments_20260706" / "daily_bars_cache.csv"
OUTPUT_DIR = BASE_OUTPUT_DIR / "base_stable_local_replay_20260706"

INIT_CASH = 1_000_000.0
CORE_SIZE = 21
DYNAMIC_SIZE = 14
TOP_N = 1
MOMENTUM_DAYS = 25
MIN_PRICE = 0.30
COST_RATE = 0.0004


@dataclass(frozen=True)
class ReplayConfig:
    name: str
    min_avg_amount_60: float = 20_000_000.0
    amount_weight: float = 0.05
    new_productivity_limit: int = 8
    pool_size: int = CORE_SIZE + DYNAMIC_SIZE


def run_base_stable_replay(output_dir: Path = OUTPUT_DIR) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    constants = _load_strategy_constants(BASE_SCRIPT)
    bars = _load_daily_bars(constants["ETF_UNIVERSE"])

    configs = [
        ReplayConfig("base_stable_local", 20_000_000.0, 0.05),
        ReplayConfig("pool_amount_30m", 30_000_000.0, 0.05),
        ReplayConfig("pool_amount_50m", 50_000_000.0, 0.05),
        ReplayConfig("pool_amount_80m", 80_000_000.0, 0.05),
        ReplayConfig("amount_weight_10", 20_000_000.0, 0.10),
        ReplayConfig("amount_weight_15", 20_000_000.0, 0.15),
        ReplayConfig("amount_50m_weight_10", 50_000_000.0, 0.10),
        ReplayConfig("amount_80m_weight_10", 80_000_000.0, 0.10),
    ]

    curves: list[pd.DataFrame] = []
    selections: list[pd.DataFrame] = []
    rows: list[dict[str, Any]] = []
    for config in configs:
        curve, selected = _simulate_config(config, bars, constants)
        metrics = _metrics(curve, selected)
        rows.append({"name": config.name, **_config_row(config), **metrics})
        curves.append(curve.assign(scenario=config.name))
        selections.append(selected.assign(scenario=config.name))

    scores = pd.DataFrame(rows).sort_values(
        ["final_value", "capacity_pressure_25_days"], ascending=[False, True]
    )
    all_curves = pd.concat(curves, ignore_index=True)
    all_selections = pd.concat(selections, ignore_index=True)

    scores.to_csv(output_dir / "base_stable_replay_scores.csv", index=False)
    all_curves.to_csv(output_dir / "base_stable_replay_curves.csv", index=False)
    all_selections.to_csv(output_dir / "base_stable_replay_selections.csv", index=False)
    (output_dir / "base_stable_replay_CN.html").write_text(
        _build_report(scores, all_selections), encoding="utf-8"
    )
    (output_dir / "summary.txt").write_text(_summary(scores), encoding="utf-8")
    return {"output_dir": output_dir, "scores": scores, "best": scores.iloc[0].to_dict()}


def _load_strategy_constants(path: Path) -> dict[str, Any]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    wanted = {"CORE_ANCHORS", "NEW_PRODUCTIVITY", "ETF_UNIVERSE"}
    constants: dict[str, Any] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in wanted:
                    constants[target.id] = ast.literal_eval(node.value)
    missing = wanted - set(constants)
    if missing:
        raise ValueError(f"missing strategy constants: {sorted(missing)}")
    return constants


def _load_daily_bars(symbols: list[str]) -> pd.DataFrame:
    if not DAILY_CACHE.exists():
        raise FileNotFoundError(f"missing daily cache: {DAILY_CACHE}")
    bars = pd.read_csv(DAILY_CACHE)
    bars = bars[bars["symbol"].isin(symbols)].copy()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"]).dt.strftime("%Y-%m-%d")
    bars["close"] = pd.to_numeric(bars["close"], errors="coerce")
    bars["amount"] = pd.to_numeric(bars["amount"], errors="coerce")
    bars = bars.dropna(subset=["trade_date", "symbol", "close"]).sort_values(["symbol", "trade_date"])
    bars["daily_return"] = bars.groupby("symbol")["close"].pct_change().fillna(0.0)
    return bars


def _simulate_config(
    config: ReplayConfig,
    bars: pd.DataFrame,
    constants: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    by_symbol = {symbol: group.reset_index(drop=True) for symbol, group in bars.groupby("symbol")}
    dates = sorted(bars["trade_date"].unique())
    core = [c for c in constants["CORE_ANCHORS"] if c in constants["ETF_UNIVERSE"]][:CORE_SIZE]

    value = INIT_CASH
    target = ""
    quarter_key = ""
    pool: list[str] = []
    curve_rows: list[dict[str, Any]] = []
    selected_rows: list[dict[str, Any]] = []

    for date in dates:
        if not _has_enough_history(by_symbol, date):
            curve_rows.append({"trade_date": date, "value": value, "target": target, "daily_return": 0.0})
            continue

        key = _quarter_key(date)
        if key != quarter_key or not pool:
            pool = _build_pool(config, date, by_symbol, core, constants)
            quarter_key = key

        scored = _score_pool(pool, date, by_symbol)
        new_target = scored[0][0] if scored else ""
        avg_amount_60 = _avg_amount(new_target, date, by_symbol, 60) if new_target else np.nan
        capacity_pressure = value / avg_amount_60 if np.isfinite(avg_amount_60) and avg_amount_60 > 0 else np.nan

        cost = 0.0
        if new_target and new_target != target:
            cost = COST_RATE if not target else COST_RATE * 2
        target = new_target
        ret = _daily_return(target, date, by_symbol) if target else 0.0
        value = value * (1.0 + ret) * (1.0 - cost)

        curve_rows.append({"trade_date": date, "value": value, "target": target, "daily_return": ret - cost})
        selected_rows.append(
            {
                "trade_date": date,
                "target": target,
                "score": scored[0][1] if scored else np.nan,
                "rank2": scored[1][0] if len(scored) > 1 else "",
                "score_gap_12": scored[0][1] - scored[1][1] if len(scored) > 1 else np.nan,
                "pool_size": len(pool),
                "scored": len(scored),
                "avg_amount_60": avg_amount_60,
                "capacity_pressure": capacity_pressure,
                "low_amount_50m": bool(np.isfinite(avg_amount_60) and avg_amount_60 < 50_000_000),
                "capacity_pressure_25": bool(np.isfinite(capacity_pressure) and capacity_pressure > 0.25),
                "capacity_pressure_50": bool(np.isfinite(capacity_pressure) and capacity_pressure > 0.50),
                "top10": ",".join(f"{s}:{v:.4f}" for s, v in scored[:10]),
            }
        )

    return pd.DataFrame(curve_rows), pd.DataFrame(selected_rows)


def _has_enough_history(by_symbol: dict[str, pd.DataFrame], date: str) -> bool:
    for group in by_symbol.values():
        if np.searchsorted(group["trade_date"].to_numpy(), date, side="left") >= 61:
            return True
    return False


def _build_pool(
    config: ReplayConfig,
    date: str,
    by_symbol: dict[str, pd.DataFrame],
    core: list[str],
    constants: dict[str, Any],
) -> list[str]:
    adaptive = _adaptive_rows(config, date, by_symbol, constants["ETF_UNIVERSE"])
    core_set = set(core)
    new_candidates: list[str] = []
    if not adaptive.empty:
        for code in adaptive[adaptive["code"].isin(constants["NEW_PRODUCTIVITY"])]["code"].tolist():
            if code not in core_set and code not in new_candidates:
                new_candidates.append(code)
            if len(new_candidates) >= config.new_productivity_limit:
                break

    dynamic: list[str] = []
    if not adaptive.empty:
        for code in adaptive["code"].tolist():
            if code not in core_set and code not in new_candidates and code not in dynamic:
                dynamic.append(code)
            if len(dynamic) >= config.pool_size:
                break

    return (core + new_candidates + dynamic)[: config.pool_size]


def _adaptive_rows(
    config: ReplayConfig,
    date: str,
    by_symbol: dict[str, pd.DataFrame],
    universe: list[str],
) -> pd.DataFrame:
    rows: list[dict[str, float | str]] = []
    for code in universe:
        df = _history(code, date, by_symbol, 260)
        if len(df) < 61:
            continue
        px = float(df["close"].iloc[-1])
        if not np.isfinite(px) or px < MIN_PRICE:
            continue
        avg_amount = float(df["amount"].tail(60).mean())
        if not np.isfinite(avg_amount) or avg_amount < config.min_avg_amount_60:
            continue
        high120 = float(df["close"].tail(120).max())
        amount20 = float(df["amount"].tail(20).mean())
        ma20 = float(df["close"].tail(20).mean())
        ma60 = float(df["close"].tail(60).mean())
        ma120 = float(df["close"].tail(120).mean()) if len(df) >= 120 else ma60
        rows.append(
            {
                "code": code,
                "r60": _ret(df, 60),
                "r120": _ret(df, 120),
                "r250": _ret(df, 250),
                "near_high120": px / high120 if high120 > 0 else np.nan,
                "expand": amount20 / avg_amount if avg_amount > 0 else np.nan,
                "amount": avg_amount,
                "ma_stack": 1.0 if px >= ma20 and ma20 >= ma60 and ma60 >= ma120 else 0.0,
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    for col in ["r60", "r120", "r250", "near_high120", "expand", "amount", "ma_stack"]:
        frame[col + "_rank"] = _rank_pct(frame[col])
    weights = _adaptive_weights(config.amount_weight)
    frame["adaptive_score"] = sum(weights[col] * frame[col + "_rank"] for col in weights)
    return frame.sort_values(["adaptive_score", "amount"], ascending=False)


def _adaptive_weights(amount_weight: float) -> dict[str, float]:
    base = {
        "r60": 0.32,
        "r120": 0.28,
        "near_high120": 0.14,
        "expand": 0.10,
        "ma_stack": 0.08,
        "amount": 0.05,
        "r250": 0.03,
    }
    if abs(amount_weight - base["amount"]) < 1e-12:
        return base
    other_total = 1.0 - base["amount"]
    scale = (1.0 - amount_weight) / other_total
    out = {key: value * scale for key, value in base.items() if key != "amount"}
    out["amount"] = amount_weight
    return out


def _score_pool(pool: list[str], date: str, by_symbol: dict[str, pd.DataFrame]) -> list[tuple[str, float]]:
    rows: list[tuple[str, float]] = []
    for code in pool:
        hist = _history(code, date, by_symbol, MOMENTUM_DAYS)
        if len(hist) < MOMENTUM_DAYS:
            continue
        prices = np.append(hist["close"].values[-MOMENTUM_DAYS:], hist["close"].values[-1])
        score = _score_prices(prices)
        if np.isfinite(score) and score > 0:
            rows.append((code, float(score)))
    return sorted(rows, key=lambda item: item[1], reverse=True)[:20]


def _history(code: str, date: str, by_symbol: dict[str, pd.DataFrame], count: int) -> pd.DataFrame:
    group = by_symbol.get(code)
    if group is None:
        return pd.DataFrame()
    pos = int(np.searchsorted(group["trade_date"].to_numpy(), date, side="left"))
    return group.iloc[max(0, pos - count) : pos]


def _ret(df: pd.DataFrame, days: int) -> float:
    if len(df) < days + 1:
        return np.nan
    prev = float(df["close"].iloc[-days - 1])
    px = float(df["close"].iloc[-1])
    return px / prev - 1 if prev > 0 else np.nan


def _rank_pct(values: pd.Series) -> pd.Series:
    s = pd.Series(values, dtype=float)
    if s.notna().sum() == 0:
        return pd.Series(0.0, index=s.index)
    return s.rank(pct=True, ascending=False).fillna(0.0)


def _score_prices(prices: np.ndarray) -> float:
    prices = np.asarray(prices, dtype=float)
    if len(prices) < 4 or np.any(prices <= 0):
        return np.nan
    y = np.log(prices)
    x = np.arange(len(y))
    w = np.linspace(1, 2, len(y))
    slope, intercept = np.polyfit(x, y, 1, w=w)
    annualized = math.exp(slope * 250) - 1
    fit = slope * x + intercept
    ss_res = np.sum(w * (y - fit) ** 2)
    ss_tot = np.sum(w * (y - np.mean(y)) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot else 0
    score = annualized * r2
    crash_1 = min(prices[-1] / prices[-2], prices[-2] / prices[-3], prices[-3] / prices[-4]) < 0.95
    crash_2 = prices[-1] < prices[-2] < prices[-3] < prices[-4] and prices[-1] / prices[-4] < 0.95
    if crash_1 or crash_2:
        return 0.0
    return float(score) if 0 < score < 5 else np.nan


def _daily_return(code: str, date: str, by_symbol: dict[str, pd.DataFrame]) -> float:
    group = by_symbol.get(code)
    if group is None:
        return 0.0
    dates = group["trade_date"].to_numpy()
    pos = int(np.searchsorted(dates, date, side="left"))
    if pos >= len(group) or dates[pos] != date:
        return 0.0
    value = float(group["daily_return"].iloc[pos])
    return value if np.isfinite(value) else 0.0


def _avg_amount(code: str, date: str, by_symbol: dict[str, pd.DataFrame], count: int) -> float:
    hist = _history(code, date, by_symbol, count)
    if hist.empty:
        return np.nan
    value = float(hist["amount"].tail(count).mean())
    return value if np.isfinite(value) else np.nan


def _quarter_key(date: str) -> str:
    dt = pd.Timestamp(date)
    return f"{dt.year}Q{(dt.month - 1) // 3 + 1}"


def _metrics(curve: pd.DataFrame, selected: pd.DataFrame) -> dict[str, Any]:
    if curve.empty:
        return {}
    final_value = float(curve["value"].iloc[-1])
    total_return = final_value / INIT_CASH - 1.0
    days = max(1, len(curve))
    annual_return = (final_value / INIT_CASH) ** (250 / days) - 1
    peak = curve["value"].cummax()
    max_drawdown = float((curve["value"] / peak - 1).min())
    target_change = selected["target"].fillna("").ne(selected["target"].fillna("").shift()).sum() if not selected.empty else 0
    win_rate = float((curve["daily_return"] > 0).mean())
    return {
        "final_value": final_value,
        "total_return_pct": total_return * 100,
        "annual_return_pct": annual_return * 100,
        "max_drawdown_pct": max_drawdown * 100,
        "trade_count": int(target_change),
        "win_rate_pct": win_rate * 100,
        "low_amount_50m_days": int(selected["low_amount_50m"].sum()) if not selected.empty else 0,
        "capacity_pressure_25_days": int(selected["capacity_pressure_25"].sum()) if not selected.empty else 0,
        "capacity_pressure_50_days": int(selected["capacity_pressure_50"].sum()) if not selected.empty else 0,
        "avg_capacity_pressure": float(selected["capacity_pressure"].replace([np.inf, -np.inf], np.nan).mean())
        if not selected.empty
        else np.nan,
        "median_avg_amount_60": float(selected["avg_amount_60"].median()) if not selected.empty else np.nan,
    }


def _config_row(config: ReplayConfig) -> dict[str, Any]:
    return {
        "min_avg_amount_60": config.min_avg_amount_60,
        "amount_weight": config.amount_weight,
        "new_productivity_limit": config.new_productivity_limit,
        "pool_size": config.pool_size,
    }


def _build_report(scores: pd.DataFrame, selections: pd.DataFrame) -> str:
    best = scores.iloc[0]
    base = scores[scores["name"] == "base_stable_local"].iloc[0]
    capacity_delta = base["capacity_pressure_25_days"] - best["capacity_pressure_25_days"]
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>基础稳定版本地复刻与池子容量网格</title>
  <style>
    body {{ font-family: Arial, 'Microsoft YaHei', sans-serif; margin: 28px; color: #1f2937; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
    th, td {{ border: 1px solid #d1d5db; padding: 6px 8px; text-align: right; }}
    th:first-child, td:first-child {{ text-align: left; }}
    th {{ background: #f3f4f6; }}
    .note {{ line-height: 1.7; background: #f8fafc; padding: 12px 14px; border-left: 4px solid #64748b; }}
  </style>
</head>
<body>
  <h1>基础稳定版本地复刻与池子容量网格</h1>
  <div class="note">
    <p>本地基准使用日线缓存复刻核心参数：21核心 + 14动态、季度重建、25日动量拟合、60日均成交额过滤。由于没有同花顺09:31分钟价，本报告是日线近似基准，用来比较池子/容量方向，不等同于平台逐笔复现。</p>
    <p>当前网格最优按最终净值排序为 <b>{best['name']}</b>，最终净值 {best['final_value']:,.2f}；基础稳定本地基准为 {base['final_value']:,.2f}。25%容量压力天数变化：{capacity_delta:+.0f} 天。</p>
  </div>
  <h2>网格结果</h2>
  {scores.to_html(index=False, float_format=lambda x: f"{x:,.4f}")}
  <h2>容量压力最多的标的</h2>
  {_top_capacity_table(selections)}
</body>
</html>"""


def _top_capacity_table(selections: pd.DataFrame) -> str:
    if selections.empty:
        return "<p>无选择记录。</p>"
    base = selections[selections["scenario"] == "base_stable_local"]
    grouped = (
        base.groupby("target")
        .agg(
            days=("trade_date", "count"),
            low_amount_50m_days=("low_amount_50m", "sum"),
            pressure_25_days=("capacity_pressure_25", "sum"),
            median_amount=("avg_amount_60", "median"),
            avg_pressure=("capacity_pressure", "mean"),
        )
        .sort_values(["pressure_25_days", "low_amount_50m_days"], ascending=False)
        .head(12)
        .reset_index()
    )
    return grouped.to_html(index=False, float_format=lambda x: f"{x:,.4f}")


def _summary(scores: pd.DataFrame) -> str:
    best = scores.iloc[0]
    base = scores[scores["name"] == "base_stable_local"].iloc[0]
    return (
        f"base_final={base['final_value']:.2f}\n"
        f"best={best['name']}\n"
        f"best_final={best['final_value']:.2f}\n"
        f"base_capacity_pressure_25_days={int(base['capacity_pressure_25_days'])}\n"
        f"best_capacity_pressure_25_days={int(best['capacity_pressure_25_days'])}\n"
    )


if __name__ == "__main__":
    result = run_base_stable_replay()
    print(result["output_dir"])
    print(result["scores"].head(8).to_string(index=False))
