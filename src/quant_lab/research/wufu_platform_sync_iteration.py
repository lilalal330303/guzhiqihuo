from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from quant_lab.data.repository import DuckDBRepository
from quant_lab.research.wufu_audit import audit_joinquant_dynamic_pool
from quant_lab.research.wufu_etf_rotation import run_wufu_etf_rotation_experiment
from quant_lab.strategies.wufu_etf_rotation import (
    WufuEtfRotationConfig,
    calculate_joinquant_liquidity_thresholds,
)


def run_platform_sync_v1(
    db_path: str | Path = "data/market.duckdb",
    reports_dir: str | Path = "reports",
    start_date: str = "2020-01-01",
    end_date: str = "2026-07-06",
) -> dict[str, object]:
    reports = Path(reports_dir)
    reports.mkdir(parents=True, exist_ok=True)
    repo = DuckDBRepository(db_path)
    repo.initialize()

    metadata = _latest_metadata(repo.load_etf_universe_snapshots(start_date, end_date))
    config = WufuEtfRotationConfig()
    warmup_start = "2019-10-01"
    symbols = _configured_symbols(config, metadata)
    prices = repo.load_prices_for_symbols(symbols, warmup_start, end_date)
    thresholds = calculate_joinquant_liquidity_thresholds(prices)

    result = run_wufu_etf_rotation_experiment(
        repo=repo,
        start_date=start_date,
        end_date=end_date,
        config=config,
        refresh_data=False,
        use_local_weak_states=True,
        etf_metadata=metadata if not metadata.empty else None,
        dynamic_liquidity_thresholds=thresholds,
        commission_rate=0.0001,
        slippage_rate=0.0001,
        min_commission=5.0,
        etf_adjust="stored-qfq-or-repaired",
        target_cache_key="wufu_platform_sync_v1_lag1",
        use_target_cache=False,
        use_dynamic_snapshot_cache=True,
        weak_state_signal_lag_days=1,
        hypothesis="Platform sync V1: use JoinQuant-style previous-day weak-state boundary and existing cached full-market ETF data.",
        next_research_note="Next: compare WUFU_*_DETAIL logs from SuperMind and JoinQuant, then calibrate amount units and fixed-pool/threshold isolation.",
    )

    prefix = reports / "wufu_platform_sync_v1"
    result.targets.to_csv(prefix.with_name(prefix.name + "_targets.csv"), index=False, encoding="utf-8-sig")
    result.trades.to_csv(prefix.with_name(prefix.name + "_trades.csv"), index=False, encoding="utf-8-sig")
    result.equity_curve.to_csv(prefix.with_name(prefix.name + "_equity.csv"), index=False, encoding="utf-8-sig")
    thresholds.to_csv(prefix.with_name(prefix.name + "_liquidity_thresholds.csv"), index=False, encoding="utf-8-sig")

    jq_compare = _compare_with_platform_signal(result.targets, reports / "jq_minute_signal.csv", "jq")
    ths_compare = _compare_with_platform_signal(result.targets, reports / "ths_minute_signal.csv", "ths")
    if not jq_compare.empty:
        jq_compare.to_csv(prefix.with_name(prefix.name + "_jq_signal_compare.csv"), index=False, encoding="utf-8-sig")
    if not ths_compare.empty:
        ths_compare.to_csv(prefix.with_name(prefix.name + "_ths_signal_compare.csv"), index=False, encoding="utf-8-sig")

    dynamic_audit = pd.DataFrame()
    jq_signal = _load_platform_signal(reports / "jq_minute_signal.csv", "jq")
    dynamic_snapshots = repo.load_dynamic_pool_snapshots(start_date, end_date)
    if not jq_signal.empty and not dynamic_snapshots.empty:
        dynamic_audit = audit_joinquant_dynamic_pool(jq_signal, result.targets, dynamic_snapshots)
        dynamic_audit.to_csv(prefix.with_name(prefix.name + "_dynamic_audit.csv"), index=False, encoding="utf-8-sig")

    summary = {
        "run_id": result.run_id,
        "start_date": start_date,
        "end_date": end_date,
        "metrics": result.metrics,
        "target_rows": int(len(result.targets)),
        "trade_rows": int(len(result.trades)),
        "data_quality_excluded_symbols": result.data_quality_excluded_symbols,
        "metadata_symbols": int(metadata["symbol"].nunique()) if not metadata.empty else 0,
        "threshold_min": float(thresholds["liquidity_threshold"].min()) if not thresholds.empty else None,
        "threshold_median": float(thresholds["liquidity_threshold"].median()) if not thresholds.empty else None,
        "threshold_max": float(thresholds["liquidity_threshold"].max()) if not thresholds.empty else None,
        "jq_signal_match": _match_summary(jq_compare),
        "ths_signal_match": _match_summary(ths_compare),
        "dynamic_audit": _dynamic_audit_summary(dynamic_audit),
    }
    (prefix.with_name(prefix.name + "_summary.json")).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (prefix.with_name(prefix.name + "_analysis.md")).write_text(_analysis_markdown(summary), encoding="utf-8")
    return summary


def _latest_metadata(snapshots: pd.DataFrame) -> pd.DataFrame:
    if snapshots.empty:
        return pd.DataFrame(columns=["symbol", "name"])
    rows = snapshots.copy()
    rows["trade_date"] = pd.to_datetime(rows["trade_date"])
    rows = rows[rows["is_active"].astype(bool)]
    rows = rows.sort_values(["symbol", "trade_date"]).drop_duplicates("symbol", keep="last")
    return rows[["symbol", "name"]].reset_index(drop=True)


def _configured_symbols(config: WufuEtfRotationConfig, metadata: pd.DataFrame) -> list[str]:
    symbols = list(dict.fromkeys(config.etf_pool + config.global_etf_pool + ([config.defensive_etf] if config.defensive_etf else [])))
    if not metadata.empty:
        symbols.extend(symbol for symbol in metadata["symbol"].astype(str).tolist() if symbol not in symbols)
    return symbols


def _load_platform_signal(path: Path, platform: str) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    rows = pd.read_csv(path)
    if rows.empty:
        return pd.DataFrame()
    out = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(rows["date"]),
            "target_symbol": rows["target"].astype(str).str[:6],
            f"{platform}_top10_raw": rows.get("top10_raw", ""),
        }
    )
    return out.drop_duplicates("trade_date")


def _compare_with_platform_signal(local_targets: pd.DataFrame, path: Path, platform: str) -> pd.DataFrame:
    platform_signal = _load_platform_signal(path, platform)
    if platform_signal.empty or local_targets.empty:
        return pd.DataFrame()
    local = local_targets[["trade_date", "target_symbol", "is_weak", "candidates_json"]].copy()
    local["trade_date"] = pd.to_datetime(local["trade_date"])
    local["local_target"] = local["target_symbol"].astype(str).str[:6]
    merged = platform_signal.merge(local, on="trade_date", how="inner")
    merged[f"{platform}_target"] = merged["target_symbol_x"].astype(str).str[:6]
    merged["target_match"] = merged[f"{platform}_target"] == merged["local_target"]
    merged["local_top1"] = merged["local_target"]
    merged = merged.drop(columns=["target_symbol_x", "target_symbol_y"], errors="ignore")
    return merged


def _match_summary(compare: pd.DataFrame) -> dict[str, object]:
    if compare.empty:
        return {"days": 0, "matched_days": 0, "match_rate": None}
    return {
        "days": int(len(compare)),
        "matched_days": int(compare["target_match"].sum()),
        "match_rate": float(compare["target_match"].mean()),
        "weak_days": int(compare["is_weak"].sum()) if "is_weak" in compare.columns else 0,
    }


def _dynamic_audit_summary(audit: pd.DataFrame) -> dict[str, object]:
    if audit.empty:
        return {"rows": 0}
    return {
        "rows": int(len(audit)),
        "target_match_rate": float(audit["target_match"].mean()),
        "jq_in_dynamic_pool_rate": float(audit["jq_in_dynamic_pool"].mean()),
        "jq_in_candidates_rate": float(audit["jq_in_candidates"].mean()),
        "reason_counts": {str(k): int(v) for k, v in audit["reason"].value_counts().items()},
    }


def _analysis_markdown(summary: dict[str, object]) -> str:
    metrics = summary["metrics"]
    jq = summary["jq_signal_match"]
    ths = summary["ths_signal_match"]
    audit = summary["dynamic_audit"]
    return f"""# Wufu Platform Sync V1 Local Backtest

## Version plan

1. V1 diagnostics and boundary sync: add platform detail logs, use JoinQuant-style previous-day weak-state boundary locally, and rerun local backtest.
2. V2 amount calibration: compare `WUFU_THRESHOLD_DETAIL` rows, normalize SuperMind amount units, then rerun fixed-threshold isolation.
3. V3 pool isolation: replay a fixed daily ETF pool across both platforms and locate metadata/name-cleaning drift.
4. V4 scoring isolation: compare `WUFU_SCORE_DETAIL` top candidates, then align current price, volume, and adjustment rules.
5. V5 execution isolation: align minimum order, round lot, capacity, failed-order handling, commission, and slippage.

## Local run

- Run ID: `{summary["run_id"]}`
- Range: `{summary["start_date"]}` to `{summary["end_date"]}`
- Total return: `{metrics.get("total_return"):.6f}`
- Annualized return: `{metrics.get("annualized_return"):.6f}`
- Max drawdown: `{metrics.get("max_drawdown"):.6f}`
- Trade count: `{metrics.get("trade_count")}`
- Win rate: `{metrics.get("win_rate"):.6f}`

## Platform target comparison

- JoinQuant common days: `{jq.get("days")}`, matched days: `{jq.get("matched_days")}`, match rate: `{jq.get("match_rate")}`
- SuperMind common days: `{ths.get("days")}`, matched days: `{ths.get("matched_days")}`, match rate: `{ths.get("match_rate")}`

## Dynamic pool audit

- Rows: `{audit.get("rows")}`
- JoinQuant target in local dynamic pool rate: `{audit.get("jq_in_dynamic_pool_rate")}`
- JoinQuant target in local candidates rate: `{audit.get("jq_in_candidates_rate")}`
- Reason counts: `{audit.get("reason_counts")}`

## Reading

V1 should be judged by comparability, not only return. The expected next evidence is a pair of platform minute logs with `WUFU_WEAK_DETAIL`, `WUFU_THRESHOLD_DETAIL`, `WUFU_POOL_DETAIL`, and `WUFU_SCORE_DETAIL`; those rows will show whether the remaining target drift comes from index state, amount threshold, ETF universe, or scoring inputs.
"""


if __name__ == "__main__":
    print(json.dumps(run_platform_sync_v1(), ensure_ascii=False, indent=2))
