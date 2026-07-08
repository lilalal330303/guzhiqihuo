from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

import pandas as pd

from quant_lab.backtest.capacity import CapacityConfig, simulate_rebalance_capacity
from quant_lab.research.capacity_fullcycle import (
    ANALYSIS_DIR,
    BASE_OUTPUT_DIR,
    BASELINE_BUY_RATIO,
    OUTLOG8_DIR,
    REPLAY_DIR,
    _capacity_metrics,
    _curve_metrics,
    _ideal_order_fills,
    _merge_hybrid_minutes,
    _normalize_minute_frame,
    _summarize_order_fills,
)


SUBSTITUTION_DIR = BASE_OUTPUT_DIR / "capacity_substitution_experiments_20260706"
DAILY_CACHE = SUBSTITUTION_DIR / "daily_bars_cache.csv"
MINUTE_SHARE_FALLBACK = 0.006


@dataclass(frozen=True)
class SubstitutionRule:
    name: str
    mode: str
    trigger_exposure: float
    min_alt_exposure: float
    max_score_gap_pct: float
    max_rank: int = 5
    use_corr_group: bool = False
    use_score_capacity: bool = False
    scale_unresolved: bool = False
    min_corr: float = 0.85
    corr_window: int = 60
    corr_trigger_exposure: float | None = None
    require_corr_rank: bool = False
    corr_required_rank: int = 10
    momentum_window: int = 20
    max_momentum_lag: float | None = None
    partial_switch_ratio: float = 1.0


ETF_EQUIV_GROUPS: dict[str, set[str]] = {
    "hs300": {"510300.SH", "159919.SZ", "510330.SH"},
    "sz100": {"159901.SZ", "159902.SZ"},
    "cyb": {"159915.SZ", "159949.SZ", "159967.SZ"},
    "gold": {"518880.SH", "159934.SZ", "159937.SZ"},
    "nasdaq": {"513100.SH", "159941.SZ", "513300.SH", "513110.SH"},
    "sp500": {"513500.SH", "513650.SH"},
    "semiconductor": {"512480.SH", "512760.SH", "159995.SZ", "516920.SH"},
    "ai_cloud": {"159509.SZ", "513520.SH", "159851.SZ"},
    "star50": {"588000.SH", "588080.SH", "588010.SH", "588200.SH", "588290.SH", "588170.SH"},
    "broker": {"512880.SH", "512000.SH"},
    "military": {"512660.SH", "512710.SH"},
    "bank": {"512800.SH", "512700.SH"},
    "energy": {"159930.SZ", "159930.SH", "516160.SH"},
    "rare_metal": {"512400.SH", "159980.SZ"},
}


def run_capacity_substitution_experiments(output_dir: Path = SUBSTITUTION_DIR) -> dict[str, object]:
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
    return_matrix = _daily_return_matrix(daily_bars)

    rules = [
        SubstitutionRule("baseline_current", "none", 0.0, 0.0, 0.0),
        SubstitutionRule("rank_top5_gap15", "rank", 0.50, 0.80, 0.15, 5),
        SubstitutionRule("rank_top5_gap20", "rank", 0.50, 0.80, 0.20, 5),
        SubstitutionRule("same_group_v1", "group", 0.50, 0.80, 0.15, 5),
        SubstitutionRule("hybrid_group_then_rank15", "hybrid", 0.50, 0.80, 0.15, 5),
        SubstitutionRule("hybrid_group_then_rank20", "hybrid", 0.50, 0.80, 0.20, 5),
        SubstitutionRule("same_group_v2_corr", "group", 0.50, 0.80, 0.15, 5, use_corr_group=True),
        SubstitutionRule("hybrid_group_v2_then_rank15", "hybrid", 0.50, 0.80, 0.15, 5, use_corr_group=True),
        SubstitutionRule(
            "rank_top10_score_capacity_v1",
            "rank",
            0.50,
            0.60,
            0.15,
            10,
            use_score_capacity=True,
        ),
        SubstitutionRule(
            "hybrid_v2_score_capacity_v1",
            "hybrid",
            0.50,
            0.60,
            0.15,
            10,
            use_corr_group=True,
            use_score_capacity=True,
        ),
        SubstitutionRule(
            "hybrid_v2_score_capacity_scaling",
            "hybrid",
            0.50,
            0.60,
            0.15,
            10,
            use_corr_group=True,
            use_score_capacity=True,
            scale_unresolved=True,
        ),
        SubstitutionRule(
            "v3_oldbest_extreme_overlay",
            "hybrid",
            0.50,
            0.80,
            0.15,
            5,
            use_corr_group=True,
            corr_trigger_exposure=0.10,
        ),
        SubstitutionRule(
            "v3_rank_alpha_gate",
            "rank",
            0.50,
            0.80,
            0.10,
            10,
            use_score_capacity=True,
            momentum_window=20,
            max_momentum_lag=0.08,
        ),
        SubstitutionRule(
            "v3_corr_alpha_gate",
            "hybrid",
            0.50,
            0.80,
            0.15,
            10,
            use_corr_group=True,
            min_corr=0.90,
            require_corr_rank=True,
            corr_required_rank=10,
            momentum_window=20,
            max_momentum_lag=0.08,
        ),
        SubstitutionRule(
            "v3_pair_blacklist",
            "hybrid",
            0.50,
            0.80,
            0.15,
            10,
            use_corr_group=True,
            min_corr=0.90,
            require_corr_rank=True,
            corr_required_rank=10,
            momentum_window=20,
            max_momentum_lag=0.08,
        ),
        SubstitutionRule(
            "v3_partial_substitution",
            "hybrid",
            0.50,
            0.80,
            0.15,
            10,
            use_corr_group=True,
            min_corr=0.90,
            require_corr_rank=True,
            corr_required_rank=10,
            momentum_window=20,
            max_momentum_lag=0.08,
            partial_switch_ratio=0.50,
        ),
    ]

    scores: list[dict[str, object]] = []
    curves: list[pd.DataFrame] = []
    selections: list[pd.DataFrame] = []

    for rule in rules:
        selected = _select_orders(rule, orders, top_candidates, hybrid_minutes, daily_amount, return_matrix)
        selected.to_csv(output_dir / f"selected_orders_{rule.name}.csv", index=False)
        augmented_minutes = _augment_minutes_for_orders(hybrid_minutes, selected, daily_amount)

        sim_orders = selected[["trade_date", "selected_symbol", "trade_target_value", "slices"]].rename(
            columns={"selected_symbol": "symbol", "trade_target_value": "target_value"}
        )
        result = simulate_rebalance_capacity(
            sim_orders,
            augmented_minutes,
            CapacityConfig(participation_rate=0.25, buy_value_ratio=0.995, slice_count=None),
        )
        fills = _summarize_order_fills(result.fills, sim_orders)
        fills = fills.rename(columns={"symbol": "selected_symbol"})
        selected_fills = selected.merge(fills, on=["trade_date", "selected_symbol"], how="left", suffixes=("", "_fill"))
        for col in ["filled_value", "unfilled_value", "exposure_fraction"]:
            selected_fills[col] = selected_fills[col].fillna(0.0)
        selected_fills["exposure_fraction"] = (
            selected_fills["filled_value"] / selected_fills["target_value"]
        ).clip(lower=0.0, upper=1.0)
        curve = _substitution_equity_curve(closes, selected_fills, daily_return, rule.name)
        metrics = _curve_metrics(curve)
        cap_metrics = _capacity_metrics(result.fills, selected_fills)
        switch_count = int((selected["selected_symbol"] != selected["symbol"]).sum())
        score_row = {
            "name": rule.name,
            "mode": rule.mode,
            "trigger_exposure": rule.trigger_exposure,
            "min_alt_exposure": rule.min_alt_exposure,
            "max_score_gap_pct": rule.max_score_gap_pct,
            "max_rank": rule.max_rank,
            "use_corr_group": rule.use_corr_group,
            "use_score_capacity": rule.use_score_capacity,
            "scale_unresolved": rule.scale_unresolved,
            "corr_trigger_exposure": rule.corr_trigger_exposure,
            "require_corr_rank": rule.require_corr_rank,
            "max_momentum_lag": rule.max_momentum_lag,
            "partial_switch_ratio": rule.partial_switch_ratio,
            "switch_count": switch_count,
            "group_switch_count": int(selected["switch_reason"].str.contains("same_group", regex=False).sum()),
            "corr_group_switch_count": int(selected["switch_reason"].str.contains("corr_group", regex=False).sum()),
            "rank_switch_count": int(selected["switch_reason"].str.contains("rank", regex=False).sum()),
            "scaled_count": int(selected["switch_reason"].str.contains("scaled", regex=False).sum()),
            **metrics,
            **cap_metrics,
        }
        scores.append(score_row)
        curves.append(curve)
        selections.append(selected.assign(rule=rule.name))

    score_df = pd.DataFrame(scores).sort_values(["final_value", "max_drawdown_pct"], ascending=[False, False])
    curve_df = pd.concat(curves, ignore_index=True)
    selection_df = pd.concat(selections, ignore_index=True)
    score_df.to_csv(output_dir / "substitution_scores.csv", index=False)
    curve_df.to_csv(output_dir / "substitution_curves.csv", index=False)
    selection_df.to_csv(output_dir / "substitution_selections.csv", index=False)

    report = _build_substitution_report(score_df, selection_df, daily_bars)
    (output_dir / "capacity_substitution_CN.html").write_text(report, encoding="utf-8")
    (output_dir / "summary.txt").write_text(_summary(score_df), encoding="utf-8")
    return {
        "output_dir": output_dir,
        "scores": score_df,
        "best": score_df.iloc[0].to_dict(),
        "baseline": score_df[score_df["name"] == "baseline_current"].iloc[0].to_dict(),
    }


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


def _load_or_fetch_daily_bars(symbols: list[str], output_dir: Path) -> pd.DataFrame:
    if DAILY_CACHE.exists():
        cached = pd.read_csv(DAILY_CACHE)
    else:
        cached = pd.DataFrame()
    cached_symbols = set(cached["symbol"]) if not cached.empty else set()
    missing = [symbol for symbol in symbols if symbol not in cached_symbols]
    frames = [cached] if not cached.empty else []
    if missing:
        for symbol in missing:
            fetched = _fetch_daily_bar(symbol)
            if not fetched.empty:
                frames.append(fetched)
        combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        combined.drop_duplicates(["symbol", "trade_date"], keep="last").to_csv(DAILY_CACHE, index=False)
        return combined
    return cached


def _fetch_daily_bar(symbol: str) -> pd.DataFrame:
    import akshare as ak

    raw_symbol = symbol.split(".")[0]
    fetchers = [ak.fund_etf_hist_em, ak.fund_lof_hist_em]
    for fetcher in fetchers:
        try:
            raw = fetcher(symbol=raw_symbol, period="daily", start_date="20200101", end_date="20260706", adjust="")
            if raw.empty:
                continue
            rows = pd.DataFrame(
                {
                    "symbol": symbol,
                    "trade_date": pd.to_datetime(raw.iloc[:, 0]).dt.strftime("%Y-%m-%d"),
                    "close": pd.to_numeric(raw.iloc[:, 2], errors="coerce"),
                    "amount": pd.to_numeric(raw.iloc[:, 6], errors="coerce"),
                }
            )
            return rows.dropna(subset=["trade_date", "close"])
        except Exception:
            continue
    return pd.DataFrame(columns=["symbol", "trade_date", "close", "amount"])


def _daily_amount_map(daily_bars: pd.DataFrame) -> dict[tuple[str, str], float]:
    return {
        (row.trade_date, row.symbol): float(row.amount)
        for row in daily_bars.dropna(subset=["amount"]).itertuples(index=False)
    }


def _daily_return_map(daily_bars: pd.DataFrame) -> dict[tuple[str, str], float]:
    rows = daily_bars.sort_values(["symbol", "trade_date"]).copy()
    rows["daily_return"] = rows.groupby("symbol")["close"].pct_change()
    return {
        (row.trade_date, row.symbol): float(row.daily_return)
        for row in rows.dropna(subset=["daily_return"]).itertuples(index=False)
    }


def _daily_return_matrix(daily_bars: pd.DataFrame) -> pd.DataFrame:
    pivot = daily_bars.pivot_table(index="trade_date", columns="symbol", values="close", aggfunc="last").sort_index()
    return pivot.pct_change()


def _select_orders(
    rule: SubstitutionRule,
    orders: pd.DataFrame,
    top_candidates: pd.DataFrame,
    minute_bars: pd.DataFrame,
    daily_amount: dict[tuple[str, str], float],
    return_matrix: pd.DataFrame | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    candidate_map = {
        (date, target): group.sort_values("rank")
        for (date, target), group in top_candidates.groupby(["trade_date", "target"])
    }
    for order in orders.itertuples(index=False):
        date = str(order.trade_date)
        symbol = str(order.symbol)
        target_value = float(order.target_value)
        slices = int(order.slices)
        original_exposure = _estimate_exposure(symbol, date, target_value, slices, minute_bars, daily_amount)
        selected_symbol = symbol
        selected_exposure = original_exposure
        selected_rank = 1
        selected_gap = 0.0
        reason = "original"
        trade_target_value = target_value

        if rule.mode != "none" and original_exposure < rule.trigger_exposure:
            if rule.mode in {"group", "hybrid"}:
                candidates = candidate_map.get((date, symbol), pd.DataFrame())
                use_corr_group = rule.use_corr_group and (
                    rule.corr_trigger_exposure is None or original_exposure < rule.corr_trigger_exposure
                )
                group_choice = _choose_same_group(
                    symbol,
                    date,
                    target_value,
                    slices,
                    minute_bars,
                    daily_amount,
                    rule.min_alt_exposure,
                    rule=rule,
                    candidates=candidates,
                    return_matrix=return_matrix,
                    use_corr_group=use_corr_group,
                    min_corr=rule.min_corr,
                    corr_window=rule.corr_window,
                )
                if group_choice is not None:
                    selected_symbol, selected_exposure, reason = group_choice
            if reason == "original" and rule.mode in {"rank", "hybrid"}:
                candidates = candidate_map.get((date, symbol), pd.DataFrame())
                rank_choice = _choose_rank_candidate(
                    candidates, symbol, date, target_value, slices, minute_bars, daily_amount, return_matrix, rule
                )
                if rank_choice is not None:
                    selected_symbol, selected_exposure, selected_rank, selected_gap = rank_choice
                    reason = "rank"
            if reason == "original" and rule.scale_unresolved:
                scale = min(1.0, max(0.0, original_exposure / rule.min_alt_exposure))
                if scale < 1.0:
                    trade_target_value = target_value * scale
                    selected_exposure = original_exposure
                    reason = "scaled"

        if selected_symbol != symbol and 0.0 < rule.partial_switch_ratio < 1.0:
            alt_value = target_value * rule.partial_switch_ratio
            original_value = target_value - alt_value
            rows.append(
                _selection_row(
                    date,
                    symbol,
                    symbol,
                    original_value,
                    original_value,
                    slices,
                    original_exposure,
                    _estimate_exposure(symbol, date, original_value, slices, minute_bars, daily_amount),
                    1,
                    0.0,
                    "partial_original",
                )
            )
            rows.append(
                _selection_row(
                    date,
                    symbol,
                    selected_symbol,
                    alt_value,
                    alt_value,
                    slices,
                    original_exposure,
                    _estimate_exposure(selected_symbol, date, alt_value, slices, minute_bars, daily_amount),
                    selected_rank,
                    selected_gap,
                    f"partial_{reason}",
                )
            )
        else:
            rows.append(
                _selection_row(
                    date,
                    symbol,
                    selected_symbol,
                    target_value,
                    trade_target_value,
                    slices,
                    original_exposure,
                    selected_exposure,
                    selected_rank,
                    selected_gap,
                    reason,
                )
            )
    return pd.DataFrame(rows)


def _selection_row(
    date: str,
    symbol: str,
    selected_symbol: str,
    target_value: float,
    trade_target_value: float,
    slices: int,
    original_exposure: float,
    selected_exposure: float,
    selected_rank: int,
    selected_gap: float,
    reason: str,
) -> dict[str, object]:
    return {
        "trade_date": date,
        "symbol": symbol,
        "selected_symbol": selected_symbol,
        "target_value": target_value,
        "trade_target_value": trade_target_value,
        "slices": slices,
        "original_est_exposure": original_exposure,
        "selected_est_exposure": selected_exposure,
        "selected_rank": selected_rank,
        "selected_score_gap_pct": selected_gap,
        "switch_reason": reason,
    }


def _choose_same_group(
    symbol: str,
    date: str,
    target_value: float,
    slices: int,
    minute_bars: pd.DataFrame,
    daily_amount: dict[tuple[str, str], float],
    min_alt_exposure: float,
    rule: SubstitutionRule,
    candidates: pd.DataFrame,
    return_matrix: pd.DataFrame | None = None,
    use_corr_group: bool = False,
    min_corr: float = 0.85,
    corr_window: int = 60,
) -> tuple[str, float, str] | None:
    group = _equiv_group_for(symbol)
    reason = "same_group"
    if use_corr_group and return_matrix is not None:
        corr_group = _corr_group_for(symbol, date, return_matrix, min_corr=min_corr, window=corr_window)
        group = group | corr_group
        if corr_group:
            reason = "corr_group"
    if not group:
        return None
    choices = []
    manual_group = _equiv_group_for(symbol)
    for candidate in sorted(group - {symbol}):
        is_corr_candidate = candidate not in manual_group
        if is_corr_candidate and rule.name in {"v3_pair_blacklist", "v3_partial_substitution"} and _is_pair_blacklisted(symbol, candidate):
            continue
        if is_corr_candidate and not _passes_corr_alpha_gate(
            candidate, candidates, rule, symbol, date, return_matrix
        ):
            continue
        exposure = _estimate_exposure(candidate, date, target_value, slices, minute_bars, daily_amount)
        if exposure >= min_alt_exposure:
            choices.append((candidate, exposure, "corr_group" if is_corr_candidate else "same_group"))
    if not choices:
        return None
    return max(choices, key=lambda item: item[1])


def _choose_rank_candidate(
    candidates: pd.DataFrame,
    original_symbol: str,
    date: str,
    target_value: float,
    slices: int,
    minute_bars: pd.DataFrame,
    daily_amount: dict[tuple[str, str], float],
    return_matrix: pd.DataFrame | None,
    rule: SubstitutionRule,
) -> tuple[str, float, int, float] | None:
    if candidates.empty:
        return None
    candidates = candidates[(candidates["rank"] > 1) & (candidates["rank"] <= rule.max_rank)]
    candidates = candidates[candidates["score_gap_pct"] <= rule.max_score_gap_pct]
    choices = []
    for row in candidates.itertuples(index=False):
        candidate = str(row.symbol)
        if not _passes_momentum_gate(original_symbol, candidate, date, return_matrix, rule):
            continue
        exposure = _estimate_exposure(str(row.symbol), date, target_value, slices, minute_bars, daily_amount)
        if exposure >= rule.min_alt_exposure:
            score_quality = 1.0 - float(row.score_gap_pct)
            combined_score = score_quality * 0.7 + exposure * 0.3
            choices.append((str(row.symbol), exposure, int(row.rank), float(row.score_gap_pct), combined_score))
    if not choices:
        return None
    if rule.use_score_capacity:
        symbol, exposure, rank, gap, _score = max(choices, key=lambda item: item[4])
        return symbol, exposure, rank, gap
    symbol, exposure, rank, gap, _score = sorted(choices, key=lambda item: (item[2], -item[1]))[0]
    return symbol, exposure, rank, gap


def _passes_corr_alpha_gate(
    candidate: str,
    candidates: pd.DataFrame,
    rule: SubstitutionRule,
    original_symbol: str,
    date: str,
    return_matrix: pd.DataFrame | None,
) -> bool:
    if rule.require_corr_rank:
        if candidates.empty:
            return False
        ranked = candidates[
            (candidates["symbol"] == candidate)
            & (candidates["rank"] <= rule.corr_required_rank)
            & (candidates["score_gap_pct"] <= rule.max_score_gap_pct)
        ]
        if ranked.empty:
            return False
    return _passes_momentum_gate(original_symbol, candidate, date, return_matrix, rule)


def _passes_momentum_gate(
    original_symbol: str,
    candidate: str,
    date: str,
    return_matrix: pd.DataFrame | None,
    rule: SubstitutionRule,
) -> bool:
    if rule.max_momentum_lag is None or return_matrix is None:
        return True
    delta = _momentum_delta(original_symbol, candidate, date, return_matrix, rule.momentum_window)
    if delta is None:
        return True
    return delta >= -float(rule.max_momentum_lag)


def _momentum_delta(
    original_symbol: str,
    candidate: str,
    date: str,
    return_matrix: pd.DataFrame,
    window: int,
) -> float | None:
    if original_symbol not in return_matrix.columns or candidate not in return_matrix.columns:
        return None
    recent = return_matrix[return_matrix.index < date][[original_symbol, candidate]].tail(window).dropna()
    if len(recent) < max(5, window // 3):
        return None
    original_momentum = float((1.0 + recent[original_symbol]).prod() - 1.0)
    candidate_momentum = float((1.0 + recent[candidate]).prod() - 1.0)
    return candidate_momentum - original_momentum


def _is_pair_blacklisted(original_symbol: str, candidate: str) -> bool:
    review_blacklist = {
        ("516500.SH", "159682.SZ"),
        ("159509.SZ", "159941.SZ"),
    }
    return (original_symbol, candidate) in review_blacklist


def _equiv_group_for(symbol: str) -> set[str]:
    for group in ETF_EQUIV_GROUPS.values():
        if symbol in group:
            return group
    return set()


def _corr_group_for(
    symbol: str,
    date: str,
    return_matrix: pd.DataFrame,
    *,
    min_corr: float,
    window: int,
) -> set[str]:
    if symbol not in return_matrix.columns:
        return set()
    returns = return_matrix[return_matrix.index < date].tail(window)
    if symbol not in returns.columns:
        return set()
    base = returns[symbol]
    candidates: list[tuple[str, float]] = []
    for candidate in returns.columns:
        if candidate == symbol:
            continue
        joined = pd.concat([base, returns[candidate]], axis=1).dropna()
        if len(joined) < min(40, window // 2):
            continue
        corr = float(joined.iloc[:, 0].corr(joined.iloc[:, 1]))
        if corr >= min_corr:
            candidates.append((str(candidate), corr))
    return {symbol for symbol, _corr in sorted(candidates, key=lambda item: item[1], reverse=True)[:20]}


def _estimate_exposure(
    symbol: str,
    date: str,
    target_value: float,
    slices: int,
    minute_bars: pd.DataFrame,
    daily_amount: dict[tuple[str, str], float],
) -> float:
    desired = target_value * 0.995
    cap = 0.0
    for slice_no in range(1, slices + 1):
        minute = 931 + slice_no
        row = minute_bars[
            (minute_bars["trade_date"] == date)
            & (minute_bars["minute"] == minute)
            & (minute_bars["symbol"] == symbol)
        ]
        if not row.empty:
            bar_amount = float((row.iloc[0]["close"] * row.iloc[0]["volume"]))
        else:
            bar_amount = daily_amount.get((date, symbol), 0.0) * MINUTE_SHARE_FALLBACK
        cap += bar_amount * 0.25
    return min(1.0, cap / desired) if desired > 0 else 0.0


def _augment_minutes_for_orders(
    minute_bars: pd.DataFrame,
    orders: pd.DataFrame,
    daily_amount: dict[tuple[str, str], float],
) -> pd.DataFrame:
    existing = set(zip(minute_bars["trade_date"], minute_bars["minute"], minute_bars["symbol"]))
    rows = []
    for order in orders.itertuples(index=False):
        for slice_no in range(1, int(order.slices) + 1):
            minute = 931 + slice_no
            key = (str(order.trade_date), minute, str(order.selected_symbol))
            if key in existing:
                continue
            amount = daily_amount.get((str(order.trade_date), str(order.selected_symbol)), 0.0) * MINUTE_SHARE_FALLBACK
            rows.append(
                {
                    "trade_date": str(order.trade_date),
                    "minute": minute,
                    "symbol": str(order.selected_symbol),
                    "close": 1.0,
                    "volume": amount,
                    "source": "daily_synthetic",
                }
            )
    if not rows:
        return minute_bars
    return pd.concat([minute_bars, pd.DataFrame(rows)], ignore_index=True)


def _substitution_equity_curve(
    closes: pd.DataFrame,
    selected_fills: pd.DataFrame,
    daily_return: dict[tuple[str, str], float],
    scenario_name: str,
) -> pd.DataFrame:
    curve = closes[["date", "value", "target"]].copy()
    curve["date"] = pd.to_datetime(curve["date"]).dt.strftime("%Y-%m-%d")
    curve["ideal_return"] = curve["value"].astype(float).pct_change()
    curve.loc[0, "ideal_return"] = curve.loc[0, "value"] / 1_000_000.0 - 1.0
    decisions = {
        date: group.copy()
        for date, group in selected_fills.groupby("trade_date")
    }
    value = 1_000_000.0
    exposure = 1.0
    selected_symbol = None
    original_symbol = None
    current_positions: list[dict[str, float | str]] = []
    rows = []
    for row in curve.itertuples(index=False):
        date = str(row.date)
        if date in decisions:
            decision = decisions[date]
            total_target = float(decision["target_value"].sum())
            total_filled = float(decision["filled_value"].sum())
            exposure = total_filled / total_target if total_target > 0 else 0.0
            selected_symbol = ",".join(sorted(set(decision["selected_symbol"].astype(str))))
            original_symbol = ",".join(sorted(set(decision["symbol"].astype(str))))
            current_positions = []
            if total_target > 0:
                for leg in decision.itertuples(index=False):
                    current_positions.append(
                        {
                            "selected_symbol": str(leg.selected_symbol),
                            "original_symbol": str(leg.symbol),
                            "weight": float(leg.filled_value) / total_target,
                        }
                    )
        base_return = float(row.ideal_return)
        if current_positions:
            used_return = 0.0
            for leg in current_positions:
                leg_symbol = str(leg["selected_symbol"])
                leg_weight = float(leg["weight"])
                if leg_symbol == str(leg["original_symbol"]):
                    leg_return = base_return
                else:
                    leg_return = daily_return.get((date, leg_symbol), base_return)
                used_return += leg_weight * leg_return
        else:
            used_return = exposure * base_return
        value *= 1.0 + used_return
        rows.append(
            {
                "scenario": scenario_name,
                "date": date,
                "target": row.target,
                "selected_symbol": selected_symbol or row.target,
                "capacity_value": value,
                "ideal_value": float(row.value),
                "used_return": used_return,
                "ideal_return": base_return,
                "exposure_fraction": exposure,
            }
        )
    return pd.DataFrame(rows)


def _build_substitution_report(score_df: pd.DataFrame, selections: pd.DataFrame, daily_bars: pd.DataFrame) -> str:
    baseline = score_df[score_df["name"] == "baseline_current"].iloc[0]
    best = score_df.iloc[0]
    top = score_df.copy()
    table = top.to_html(index=False, escape=False)
    switch_summary = (
        selections.groupby(["rule", "switch_reason"]).size().reset_index(name="count").to_html(index=False)
    )
    title = "\u5bb9\u91cf\u66ff\u4ee3\u7b56\u7565\u5b9e\u9a8c"
    note = (
        "\u672c\u8f6e\u5b9e\u9a8c\u6bd4\u8f83\u5f53\u524d\u5bb9\u91cf\u57fa\u51c6\u3001\u8bc4\u5206 TopN "
        "\u987a\u5ef6\u3001\u540c\u54c1\u79cd\u5927\u5bb9\u91cf ETF \u66ff\u4ee3\u3001\u76f8\u5173 ETF "
        "\u66ff\u4ee3\u3001\u6781\u7aef\u5bb9\u91cf\u8865\u4e01\u3001alpha \u95e8\u69db\u3001\u914d\u5bf9\u9ed1\u540d\u5355\u548c\u90e8\u5206\u66ff\u4ee3\u3002"
        "\u66ff\u4ee3\u6807\u7684\u6536\u76ca\u4f7f\u7528 AkShare \u65e5\u7ebf\u6536\u76d8\u6536\u76ca\uff1b"
        "\u5bb9\u91cf\u4f18\u5148\u4f7f\u7528\u6df7\u5408\u5206\u949f\u6570\u636e\uff0c\u7f3a\u5931\u65f6\u7528\u65e5\u6210\u4ea4\u989d\u6298\u7b97\u7684\u4fdd\u5b88\u5206\u949f\u5bb9\u91cf\u3002"
    )
    core_result = "\u6838\u5fc3\u7ed3\u679c"
    baseline_label = "\u5f53\u524d\u5bb9\u91cf\u57fa\u51c6"
    best_label = "\u6700\u4f73\u65b9\u6848"
    relative_label = "\u76f8\u5bf9\u57fa\u51c6\u63d0\u5347"
    coverage_label = "\u65e5\u7ebf\u6570\u636e\u8986\u76d6"
    symbol_unit = "\u4e2a\u6807\u7684"
    row_unit = "\u884c"
    score_title = "\u65b9\u6848\u8bc4\u5206"
    switch_title = "\u66ff\u4ee3\u6b21\u6570"
    note_title = "\u53e3\u5f84\u8bf4\u660e"
    footnote = (
        "\u672c\u5b9e\u9a8c\u662f\u7814\u7a76\u6a21\u578b\uff0c\u4e0d\u662f\u4e0b\u5355\u81ea\u52a8\u5316\u3002"
        "TopN \u987a\u5ef6\u53ea\u5728 Top1 \u5bb9\u91cf\u4e0d\u8db3\u3001\u5019\u9009\u5206\u5dee\u5c0f\u4e14\u5bb9\u91cf\u8db3\u65f6\u89e6\u53d1\uff1b"
        "\u76f8\u5173 ETF \u66ff\u4ee3\u65b0\u589e\u6392\u540d\u3001\u52a8\u91cf\u548c\u9ed1\u540d\u5355\u7ea6\u675f\uff1b"
        "\u90e8\u5206\u66ff\u4ee3\u4f1a\u628a\u4e00\u6b21\u76ee\u6807\u62c6\u6210\u539f\u6807\u7684\u548c\u66ff\u4ee3\u6807\u7684\u4e24\u817f\uff0c\u7528\u6210\u4ea4\u91d1\u989d\u52a0\u6743\u8ba1\u7b97\u7ec4\u5408\u6536\u76ca\u3002"
        "\u82e5\u540e\u7eed\u8865\u9f50 Pandadata \u5168\u5386\u53f2\u5206\u949f\u6570\u636e\u548c\u66f4\u5b8c\u6574 ETF \u540c\u7c7b\u6620\u5c04\uff0c\u5bb9\u91cf\u7ed3\u8bba\u53ef\u4fe1\u5ea6\u4f1a\u8fdb\u4e00\u6b65\u63d0\u9ad8\u3002"
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>{title}</title>
<style>
body{{font-family:Arial,'Microsoft YaHei',sans-serif;margin:28px;line-height:1.55;color:#222}}
table{{border-collapse:collapse;width:100%;font-size:12px}} th,td{{border:1px solid #ddd;padding:6px 8px;text-align:right}} th:first-child,td:first-child{{text-align:left}} th{{background:#f5f5f5}}
.note{{background:#f8fafc;border-left:4px solid #4682b4;padding:10px 14px;margin:14px 0}}
</style></head>
<body>
<h1>{title}</h1>
<div class="note">{note}</div>
<h2>{core_result}</h2>
<ul>
<li>{baseline_label} final value: <b>{baseline['final_value']:,.2f}</b>.</li>
<li>{best_label}: <b>{best['name']}</b>, final value: <b>{best['final_value']:,.2f}</b>, {relative_label}: <b>{(best['final_value']/baseline['final_value']-1)*100:.2f}%</b>.</li>
<li>{coverage_label}: <b>{daily_bars['symbol'].nunique()}</b> {symbol_unit}, <b>{len(daily_bars)}</b> {row_unit}.</li>
</ul>
<h2>{score_title}</h2>
{table}
<h2>{switch_title}</h2>
{switch_summary}
<h2>{note_title}</h2>
<p>{footnote}</p>
</body></html>"""


def _summary(score_df: pd.DataFrame) -> str:
    baseline = score_df[score_df["name"] == "baseline_current"].iloc[0]
    best = score_df.iloc[0]
    return "\n".join(
        [
            f"baseline_final={baseline['final_value']:.2f}",
            f"best_name={best['name']}",
            f"best_final={best['final_value']:.2f}",
            f"best_vs_baseline_pct={(best['final_value']/baseline['final_value']-1)*100:.4f}",
            f"best_switch_count={int(best['switch_count'])}",
        ]
    )


if __name__ == "__main__":
    result = run_capacity_substitution_experiments()
    print(f"output_dir={result['output_dir']}")
    print(f"baseline={result['baseline']}")
    print(f"best={result['best']}")
