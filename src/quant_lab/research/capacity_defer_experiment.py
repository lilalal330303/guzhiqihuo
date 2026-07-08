from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

import pandas as pd

from quant_lab.research.capacity_fullcycle import (
    ANALYSIS_DIR,
    BASE_OUTPUT_DIR,
    BASELINE_BUY_RATIO,
    OUTLOG8_DIR,
    REPLAY_DIR,
    _curve_metrics,
    _merge_hybrid_minutes,
    _normalize_minute_frame,
)
from quant_lab.research.capacity_substitution import (
    DAILY_CACHE,
    ETF_EQUIV_GROUPS,
    MINUTE_SHARE_FALLBACK,
    _daily_amount_map,
    _daily_return_map,
    _load_or_fetch_daily_bars,
)


DEFER_OUTPUT_DIR = BASE_OUTPUT_DIR / "capacity_defer_experiments_20260706"
BUY_RATIO = 0.995
TRIGGER_CAPACITY_RATIO = 0.10
TARGET_CAPACITY_RATIO = 0.10
MIN_TARGET_RATIO = 0.20
MIN_ALT_CAPACITY_RATIO = 0.35
MAX_SCORE_GAP = 0.12
MAX_RANK = 10
MAX_EQUIV_RANK = 20
MIN_CAPACITY_MULTIPLE = 3.0

BAD_PAIRS = {
    ("561910.SH", "159509.SZ"),
    ("159326.SZ", "159509.SZ"),
    ("562590.SH", "159509.SZ"),
    ("513100.SH", "159941.SZ"),
    ("516500.SH", "159892.SZ"),
    ("159985.SZ", "513100.SH"),
    ("501018.SH", "159949.SZ"),
    ("515050.SH", "515030.SH"),
    ("515050.SH", "159892.SZ"),
    ("515050.SH", "515790.SH"),
    ("159509.SZ", "513520.SH"),
    ("513520.SH", "159509.SZ"),
}


@dataclass(frozen=True)
class DeferPolicy:
    name: str
    defer_low_capacity: bool
    guard: str = "none"
    max_defer_days: int | None = None
    defer_below_capacity: float | None = None
    symbol_defer_below: dict[str, float] | None = None


def run_capacity_defer_experiments(output_dir: Path = DEFER_OUTPUT_DIR) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    orders = _load_orders()
    closes = pd.read_csv(OUTLOG8_DIR / "closes.csv")
    signals = _load_signals()
    top_candidates = _parse_top10_candidates(signals)
    hybrid_minutes = pd.read_csv(ANALYSIS_DIR / "hybrid_minute_bars.csv")
    hybrid_minutes = _normalize_minute_frame(hybrid_minutes, source="proxy")

    symbols = sorted(
        set(orders["symbol"])
        | set(top_candidates["symbol"])
        | set().union(*ETF_EQUIV_GROUPS.values())
    )
    daily_bars = _load_or_fetch_daily_bars(symbols, output_dir)
    daily_amount = _daily_amount_map(daily_bars)
    daily_return = _daily_return_map(daily_bars)

    policies = [
        DeferPolicy("v42_formula_skip", defer_low_capacity=False),
        DeferPolicy("v45_defer_all", defer_low_capacity=True),
        DeferPolicy("v46_defer_below05", defer_low_capacity=True, defer_below_capacity=0.05),
        DeferPolicy("v47_defer_below06", defer_low_capacity=True, defer_below_capacity=0.06),
        DeferPolicy("v47_defer_below07", defer_low_capacity=True, defer_below_capacity=0.07),
        DeferPolicy("v46_defer_below08", defer_low_capacity=True, defer_below_capacity=0.08),
        DeferPolicy(
            "v47_symbol_hot_defer07",
            defer_low_capacity=True,
            defer_below_capacity=0.05,
            symbol_defer_below={"501018.SH": 0.07, "159985.SZ": 0.07},
        ),
        DeferPolicy(
            "v47_symbol_hot_defer08",
            defer_low_capacity=True,
            defer_below_capacity=0.05,
            symbol_defer_below={"501018.SH": 0.08, "159985.SZ": 0.08},
        ),
        DeferPolicy(
            "v48_nonhot_problem_defer07",
            defer_low_capacity=True,
            defer_below_capacity=0.05,
            symbol_defer_below={
                "513030.SH": 0.07,
                "515050.SH": 0.07,
                "159980.SZ": 0.07,
                "517520.SH": 0.07,
            },
        ),
        DeferPolicy(
            "v48_nonhot_problem_defer08",
            defer_low_capacity=True,
            defer_below_capacity=0.05,
            symbol_defer_below={
                "513030.SH": 0.08,
                "515050.SH": 0.08,
                "159980.SZ": 0.08,
                "517520.SH": 0.08,
            },
        ),
        DeferPolicy("v46_defer_rank_or_group", defer_low_capacity=True, guard="rank_or_group"),
        DeferPolicy("v46_defer_rank_or_group_max3", defer_low_capacity=True, guard="rank_or_group", max_defer_days=3),
        DeferPolicy("v46_defer_rank_only", defer_low_capacity=True, guard="rank"),
    ]

    curves = []
    rows: list[dict[str, object]] = []
    decisions = []
    for policy in policies:
        curve, decision = _simulate_policy(policy, orders, closes, top_candidates, hybrid_minutes, daily_amount, daily_return)
        metrics = _curve_metrics(curve.rename(columns={"capacity_value": "capacity_value"}))
        defer_count = int((decision["action"] == "defer").sum())
        cash_count = int((decision["action"] == "cash").sum())
        switch_count = int(decision["action"].isin(["substitute"]).sum())
        scale_count = int((decision["action"] == "scale").sum())
        rows.append(
            {
                "name": policy.name,
                "guard": policy.guard,
                "max_defer_days": policy.max_defer_days,
                "defer_count": defer_count,
                "cash_count": cash_count,
                "switch_count": switch_count,
                "scale_count": scale_count,
                **metrics,
            }
        )
        curves.append(curve.assign(scenario=policy.name))
        decisions.append(decision.assign(scenario=policy.name))

    score_df = pd.DataFrame(rows).sort_values(["final_value", "max_drawdown_pct"], ascending=[False, False])
    curve_df = pd.concat(curves, ignore_index=True)
    decision_df = pd.concat(decisions, ignore_index=True)
    score_df.to_csv(output_dir / "defer_scores.csv", index=False)
    curve_df.to_csv(output_dir / "defer_curves.csv", index=False)
    decision_df.to_csv(output_dir / "defer_decisions.csv", index=False)
    (output_dir / "capacity_defer_CN.html").write_text(_build_report(score_df, decision_df), encoding="utf-8")
    (output_dir / "summary.txt").write_text(_summary(score_df), encoding="utf-8")
    return {"output_dir": output_dir, "scores": score_df, "best": score_df.iloc[0].to_dict()}


def _simulate_policy(
    policy: DeferPolicy,
    orders: pd.DataFrame,
    closes: pd.DataFrame,
    top_candidates: pd.DataFrame,
    minute_bars: pd.DataFrame,
    daily_amount: dict[tuple[str, str], float],
    daily_return: dict[tuple[str, str], float],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    order_map = {str(row.trade_date): row for row in orders.itertuples(index=False)}
    candidate_map = {
        (date, target): group.sort_values("rank")
        for (date, target), group in top_candidates.groupby(["trade_date", "target"])
    }
    curve = closes[["date", "value", "target"]].copy()
    curve["date"] = pd.to_datetime(curve["date"]).dt.strftime("%Y-%m-%d")
    curve["ideal_return"] = curve["value"].astype(float).pct_change()
    curve.loc[0, "ideal_return"] = curve.loc[0, "value"] / 1_000_000.0 - 1.0

    value = 1_000_000.0
    positions: list[dict[str, object]] = []
    defer_streak = 0
    rows = []
    decisions = []
    for row in curve.itertuples(index=False):
        date = str(row.date)
        action = "hold"
        original_symbol = str(row.target)
        selected_symbol = ",".join(str(p["symbol"]) for p in positions) if positions else ""
        target_ratio = 1.0
        original_cap = float("nan")

        if date in order_map:
            order = order_map[date]
            original_symbol = str(order.symbol)
            candidates = candidate_map.get((date, original_symbol), pd.DataFrame())
            target_value = float(order.target_value)
            slices = int(order.slices)
            original_cap = _estimate_capacity(original_symbol, date, target_value, slices, minute_bars, daily_amount)
            selected = _choose_substitute(original_symbol, date, target_value, slices, candidates, minute_bars, daily_amount, original_cap)
            if original_cap >= TRIGGER_CAPACITY_RATIO:
                positions = [{"symbol": original_symbol, "original": original_symbol, "weight": BUY_RATIO}]
                action = "original"
                defer_streak = 0
            elif selected is not None:
                selected_symbol, selected_cap, selected_rank, selected_gap = selected
                positions = [{"symbol": selected_symbol, "original": original_symbol, "weight": BUY_RATIO}]
                action = "substitute"
                defer_streak = 0
            else:
                target_ratio = BUY_RATIO * original_cap / TARGET_CAPACITY_RATIO
                defer_threshold = _defer_threshold(policy, original_symbol)
                force_defer = (
                    policy.defer_low_capacity
                    and defer_threshold is not None
                    and original_cap < defer_threshold
                    and _can_defer(policy, positions, candidates, original_symbol, defer_streak)
                )
                if force_defer:
                    action = "defer"
                    defer_streak += 1
                elif target_ratio >= MIN_TARGET_RATIO:
                    positions = [{"symbol": original_symbol, "original": original_symbol, "weight": min(BUY_RATIO, target_ratio)}]
                    action = "scale"
                    defer_streak = 0
                elif policy.defer_low_capacity and _can_defer(policy, positions, candidates, original_symbol, defer_streak):
                    action = "defer"
                    defer_streak += 1
                else:
                    positions = []
                    action = "cash"
                    defer_streak = 0
            selected_symbol = ",".join(str(p["symbol"]) for p in positions) if positions else ""
            decisions.append(
                {
                    "trade_date": date,
                    "original_symbol": original_symbol,
                    "selected_symbol": selected_symbol,
                    "action": action,
                    "original_capacity": original_cap,
                    "target_ratio": target_ratio,
                    "defer_streak": defer_streak,
                }
            )

        daily_ret = 0.0
        if positions:
            for pos in positions:
                symbol = str(pos["symbol"])
                original = str(pos["original"])
                weight = float(pos["weight"])
                if symbol == original:
                    leg_ret = float(row.ideal_return)
                else:
                    leg_ret = daily_return.get((date, symbol), float(row.ideal_return))
                daily_ret += weight * leg_ret
        value *= 1.0 + daily_ret
        rows.append(
            {
                "date": date,
                "target": row.target,
                "selected_symbol": selected_symbol,
                "capacity_value": value,
                "ideal_value": float(row.value),
                "used_return": daily_ret,
                "ideal_return": float(row.ideal_return),
                "exposure_fraction": sum(float(p["weight"]) for p in positions) if positions else 0.0,
            }
        )
    return pd.DataFrame(rows), pd.DataFrame(decisions)


def _can_defer(
    policy: DeferPolicy,
    positions: list[dict[str, object]],
    candidates: pd.DataFrame,
    original_symbol: str,
    defer_streak: int,
) -> bool:
    if not positions:
        return False
    if policy.max_defer_days is not None and defer_streak >= policy.max_defer_days:
        return False
    if policy.guard == "none":
        return True
    held = str(positions[0]["symbol"])
    if held == original_symbol:
        return True
    if policy.guard in {"rank", "rank_or_group"}:
        if not candidates.empty:
            ranked = candidates[
                (candidates["symbol"] == held)
                & (candidates["rank"] <= MAX_RANK)
                & (candidates["score_gap_pct"] <= MAX_SCORE_GAP)
            ]
            if not ranked.empty:
                return True
    if policy.guard == "rank_or_group":
        return _same_equiv_group(held, original_symbol)
    return False


def _defer_threshold(policy: DeferPolicy, symbol: str) -> float | None:
    if policy.symbol_defer_below and symbol in policy.symbol_defer_below:
        return policy.symbol_defer_below[symbol]
    return policy.defer_below_capacity


def _choose_substitute(
    original: str,
    date: str,
    target_value: float,
    slices: int,
    candidates: pd.DataFrame,
    minute_bars: pd.DataFrame,
    daily_amount: dict[tuple[str, str], float],
    original_cap: float,
) -> tuple[str, float, int, float] | None:
    if candidates.empty:
        return None
    choices: list[tuple[str, float, int, float, float]] = []
    min_required = max(MIN_ALT_CAPACITY_RATIO, original_cap * MIN_CAPACITY_MULTIPLE if original_cap > 0 else MIN_ALT_CAPACITY_RATIO)
    for row in candidates.itertuples(index=False):
        candidate = str(row.symbol)
        rank = int(row.rank)
        gap = float(row.score_gap_pct)
        if candidate == original or (original, candidate) in BAD_PAIRS:
            continue
        if rank > MAX_EQUIV_RANK:
            continue
        if gap > MAX_SCORE_GAP:
            continue
        if rank > MAX_RANK and not _same_equiv_group(original, candidate):
            continue
        cap = _estimate_capacity(candidate, date, target_value, slices, minute_bars, daily_amount)
        if cap >= min_required:
            choices.append((candidate, cap, rank, gap, cap - gap * 2.0))
    if not choices:
        return None
    candidate, cap, rank, gap, _score = max(choices, key=lambda item: item[4])
    return candidate, cap, rank, gap


def _estimate_capacity(
    symbol: str,
    date: str,
    target_value: float,
    slices: int,
    minute_bars: pd.DataFrame,
    daily_amount: dict[tuple[str, str], float],
) -> float:
    desired = target_value * BUY_RATIO
    cap = 0.0
    for slice_no in range(1, slices + 1):
        minute = 931 + slice_no
        row = minute_bars[
            (minute_bars["trade_date"] == date)
            & (minute_bars["minute"] == minute)
            & (minute_bars["symbol"] == symbol)
        ]
        if not row.empty:
            bar_amount = float(row.iloc[0]["close"] * row.iloc[0]["volume"])
        else:
            bar_amount = daily_amount.get((date, symbol), 0.0) * MINUTE_SHARE_FALLBACK
        cap += bar_amount * 0.25
    return cap / desired if desired > 0 else 0.0


def _same_equiv_group(left: str, right: str) -> bool:
    for group in ETF_EQUIV_GROUPS.values():
        if left in group and right in group:
            return True
    return False


def _load_orders() -> pd.DataFrame:
    orders = pd.read_csv(REPLAY_DIR / "orders_from_outlog8.csv")
    orders["trade_date"] = pd.to_datetime(orders["trade_date"]).dt.strftime("%Y-%m-%d")
    orders["symbol"] = orders["symbol"].astype(str).str.upper()
    orders["target_value"] = orders["target_value"].astype(float) / BASELINE_BUY_RATIO
    return orders


def _load_signals() -> pd.DataFrame:
    signals = pd.read_csv(OUTLOG8_DIR / "signals.csv")
    signals["date"] = pd.to_datetime(signals["date"]).dt.strftime("%Y-%m-%d")
    signals["target"] = signals["target"].astype(str).str.upper()
    return signals


def _parse_top10_candidates(signals: pd.DataFrame) -> pd.DataFrame:
    pattern = re.compile(r"([0-9]{6}\.(?:SH|SZ)):([0-9.\-]+)")
    rows: list[dict[str, object]] = []
    for row in signals.itertuples(index=False):
        entries = pattern.findall(str(row.top10))
        target_score = None
        for rank, (symbol, score_text) in enumerate(entries, start=1):
            score = float(score_text)
            if rank == 1:
                target_score = score
            rows.append(
                {
                    "trade_date": row.date,
                    "target": row.target,
                    "rank": rank,
                    "symbol": symbol.upper(),
                    "score": score,
                    "target_score": target_score if target_score is not None else score,
                }
            )
    candidates = pd.DataFrame(rows)
    candidates["score_gap_pct"] = (
        (candidates["target_score"] - candidates["score"]) / candidates["target_score"].abs()
    ).clip(lower=0.0)
    return candidates


def _build_report(score_df: pd.DataFrame, decision_df: pd.DataFrame) -> str:
    table = score_df.to_html(index=False, escape=False)
    actions = decision_df.groupby(["scenario", "action"]).size().reset_index(name="count").to_html(index=False)
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>容量延迟换仓实验</title>
<style>body{{font-family:Arial,'Microsoft YaHei',sans-serif;margin:28px;line-height:1.55}}table{{border-collapse:collapse;width:100%;font-size:12px}}td,th{{border:1px solid #ddd;padding:6px 8px;text-align:right}}td:first-child,th:first-child{{text-align:left}}th{{background:#f5f5f5}}</style>
</head><body><h1>容量延迟换仓实验</h1>
<p>本地回测用于比较 V4.2 低容量转现金、V4.5 无条件延迟、以及 V4.6 候选延迟守门规则。收益路径沿用本地 replay 的目标收益，替代 ETF 使用日线收益。</p>
<h2>方案评分</h2>{table}<h2>动作次数</h2>{actions}</body></html>"""


def _summary(score_df: pd.DataFrame) -> str:
    best = score_df.iloc[0]
    return "\n".join(
        [
            f"best_name={best['name']}",
            f"best_final={best['final_value']:.2f}",
            f"best_total_return_pct={best['total_return_pct']:.4f}",
        ]
    )


if __name__ == "__main__":
    result = run_capacity_defer_experiments()
    print(f"output_dir={result['output_dir']}")
    print(f"best={result['best']}")
