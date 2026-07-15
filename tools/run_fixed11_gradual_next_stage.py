from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from dataclasses import asdict, fields, is_dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from quant_lab.backtest.portfolio import CostModel
from quant_lab.data.repository import DuckDBRepository
from quant_lab.research.optimized_v2_grid import (
    GridVariant,
    build_gradual_crowding_budget,
    load_frozen_targets,
    run_grid,
)
from quant_lab.research.optimized_v3_design import (
    _ANCHOR,
    core_l18_variants,
    core_one_factor_variants,
    crash_overlay_variants,
    profit_protection_variants,
    recovery_variants,
    stock_count_profiles,
)
from quant_lab.research.optimized_v3_runner import (
    ExperimentCandidate,
    ExperimentInputs,
    ExperimentResult,
    run_candidate,
)
from quant_lab.research.optimized_v3_walkforward import (
    ROUTES,
    default_folds,
    evaluate_route_gates,
    run_walk_forward,
)
from quant_lab.research.small_cap_experiment import (
    SmallCapExperimentConfig,
    build_joinquant_v3_targets,
)
from quant_lab.strategies.small_cap import SmallCapParams


SCHEMA_VERSION = "fixed11-gradual-v3.1"
DEFAULT_OUTPUT = ROOT / "reports" / "small_cap_fixed11_gradual_next_stage"
DEFAULT_TARGETS = ROOT / "reports" / "small_cap_strict_daily" / "optimized_source_bugs_targets.csv"
BASELINE_CANDIDATES = (
    ROOT / "reports" / "small_cap_strict_daily" / "fixed11_gradual_equity.csv",
    ROOT / "reports" / "small_cap_optimized_v2_mechanisms" / "fixed11_gradual_equity.csv",
)
ROOT_ARTIFACTS = (
    "run_manifest.json", "candidate_catalog.csv", "core_scores.csv", "route_scores.csv",
    "walkforward_training.csv", "walkforward_test.csv", "route_gate_results.csv",
    "annual_returns.csv", "stress_results.csv", "target_manifest.csv",
    "rejected_candidates.csv",
)
REQUIRED_CANDIDATE_ARTIFACTS = (
    "equity.csv", "trades.csv", "rejections.csv", "positions.csv",
    "exposure_budget.csv", "parameters.json", "target_hash.txt", "run_hash.txt",
)
SCORE_COLUMNS = (
    "candidate", "route", "family", "total_return", "annualized_return",
    "max_drawdown", "sharpe", "calmar", "max_underwater_calendar_days",
    "trade_count", "win_rate", "turnover", "minimum_cash",
    "account_reconciliation_error", "mean_exposure_budget", "defensive_budget_days",
    "target_hash", "candidate_hash",
)


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {field.name: _jsonable(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def _sha256_json(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(_jsonable(payload), ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def target_frame_hash(targets: pd.DataFrame) -> str:
    frame = targets.copy()
    for column in frame.columns:
        if pd.api.types.is_datetime64_any_dtype(frame[column]):
            frame[column] = pd.to_datetime(frame[column]).dt.strftime("%Y-%m-%d")
    raw = frame.to_csv(index=False, lineterminator="\n").encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def database_snapshot(path: str | Path) -> dict[str, Any]:
    database = Path(path).resolve()
    stat = database.stat()
    digest = hashlib.sha256()
    with database.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return {
        "path": str(database), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns,
        "sha256": digest.hexdigest(),
    }


def scale_cost_model(costs: CostModel, multiplier: float) -> CostModel:
    if not math.isfinite(multiplier) or multiplier <= 0:
        raise ValueError("cost multiplier must be positive and finite")
    return CostModel(
        commission_rate=costs.commission_rate * multiplier,
        minimum_commission=costs.minimum_commission * multiplier,
        sell_stamp_tax=costs.sell_stamp_tax * multiplier,
        fixed_slippage=costs.fixed_slippage * multiplier,
    )


def cost_stress_models(costs: CostModel) -> dict[str, CostModel]:
    combined_1p5 = scale_cost_model(costs, 1.5)
    combined_2 = scale_cost_model(costs, 2.0)
    return {
        "combined_1x": costs,
        "combined_1p5x": combined_1p5,
        "combined_2x": combined_2,
        "fee_only_1p5x": CostModel(
            commission_rate=combined_1p5.commission_rate,
            minimum_commission=combined_1p5.minimum_commission,
            sell_stamp_tax=combined_1p5.sell_stamp_tax,
            fixed_slippage=costs.fixed_slippage,
        ),
        "fee_only_2x": CostModel(
            commission_rate=combined_2.commission_rate,
            minimum_commission=combined_2.minimum_commission,
            sell_stamp_tax=combined_2.sell_stamp_tax,
            fixed_slippage=costs.fixed_slippage,
        ),
        "slippage_only_1p5x": CostModel(
            commission_rate=costs.commission_rate,
            minimum_commission=costs.minimum_commission,
            sell_stamp_tax=costs.sell_stamp_tax,
            fixed_slippage=combined_1p5.fixed_slippage,
        ),
        "slippage_only_2x": CostModel(
            commission_rate=costs.commission_rate,
            minimum_commission=costs.minimum_commission,
            sell_stamp_tax=costs.sell_stamp_tax,
            fixed_slippage=combined_2.fixed_slippage,
        ),
    }


def candidate_run_hash(
    *, candidate: ExperimentCandidate, source_target_hash: str, start: str, end: str,
    initial_cash: float, costs: CostModel, input_data_fingerprint: str,
    schema_version: str = SCHEMA_VERSION,
) -> str:
    return _sha256_json({
        "route": candidate.route,
        "family": candidate_family(candidate),
        "parameters": candidate,
        "source_target_hash": source_target_hash,
        "input_data_fingerprint": input_data_fingerprint,
        "start": str(start),
        "end": str(end),
        "initial_cash": float(initial_cash),
        "cost_model": costs,
        "schema_version": schema_version,
    })


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_jsonable(value), ensure_ascii=False, indent=2,
                               allow_nan=False), encoding="utf-8-sig")


def write_csv(frame: pd.DataFrame, path: Path, columns: Sequence[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    output = frame.copy()
    if columns is not None:
        for column in columns:
            if column not in output:
                output[column] = pd.NA
        output = output.loc[:, list(columns)]
    output.to_csv(path, index=False, encoding="utf-8-sig", lineterminator="\n")


def should_resume(record_or_path: Mapping[str, Any] | str | Path, candidate_hash: str) -> bool:
    if isinstance(record_or_path, Mapping):
        audit = dict(record_or_path)
        complete = bool(audit.get("artifacts_complete", False))
    else:
        run_dir = Path(record_or_path)
        audit_path = run_dir / "audit.json"
        if not audit_path.exists():
            return False
        try:
            audit = json.loads(audit_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return False
        paths = [run_dir / name for name in REQUIRED_CANDIDATE_ARTIFACTS]
        complete = all(path.is_file() and path.stat().st_size > 0 for path in paths)
        if complete:
            try:
                for name in ("equity.csv", "trades.csv", "rejections.csv", "positions.csv",
                             "exposure_budget.csv"):
                    pd.read_csv(run_dir / name, encoding="utf-8-sig")
                json.loads((run_dir / "parameters.json").read_text(encoding="utf-8-sig"))
                complete = bool((run_dir / "target_hash.txt").read_text(encoding="ascii").strip()
                                and (run_dir / "run_hash.txt").read_text(encoding="ascii").strip())
            except (OSError, UnicodeError, json.JSONDecodeError, pd.errors.ParserError,
                    pd.errors.EmptyDataError):
                complete = False
    try:
        reconciliation = float(audit.get("account_reconciliation_error", math.inf))
        minimum_cash = float(audit.get("minimum_cash", -math.inf))
    except (TypeError, ValueError):
        return False
    return bool(
        audit.get("candidate_hash") == candidate_hash
        and audit.get("passed") is True
        and complete
        and reconciliation < 1e-6
        and minimum_cash >= 0
    )


def candidate_family(candidate: ExperimentCandidate) -> str:
    if candidate.route == "anchor":
        return "core"
    if candidate.recovery is not None:
        return "recovery"
    if candidate.stock_profile is not None:
        return "stock_profile"
    if candidate.crash_overlay is not None:
        return "crash_overlay"
    if candidate.profit_protection is not None:
        return "profit_protection"
    return "core"


def _candidate_parameter_hash(candidate: ExperimentCandidate) -> str:
    payload = _jsonable(candidate)
    payload.pop("name", None)
    return _sha256_json(payload)


def _core_candidates() -> list[ExperimentCandidate]:
    variants = core_one_factor_variants() + core_l18_variants()
    return [
        ExperimentCandidate(
            name=variant.name,
            route=("anchor" if variant.name == "fixed11_gradual" else "core"),
            core=variant,
        )
        for variant in variants
    ]


def build_route_candidates(
    ranked_return_cores: Sequence[Any] | None = None,
    ranked_defensive_cores: Sequence[Any] | None = None,
) -> list[ExperimentCandidate]:
    core_pool = core_one_factor_variants() + core_l18_variants()
    return_cores = list(core_pool[:3] if ranked_return_cores is None else ranked_return_cores)[:3]
    defensive_cores = list(core_pool[:2] if ranked_defensive_cores is None else ranked_defensive_cores)[:2]
    candidates: list[ExperimentCandidate] = []
    candidates.extend(
        ExperimentCandidate(f"balanced__{variant.name}", "balanced", _ANCHOR, recovery=variant)
        for variant in recovery_variants()
    )
    candidates.extend(
        ExperimentCandidate(
            f"return__{core.name}__{profile.name}", "return", core,
            stock_profile=profile,
        )
        for core in return_cores for profile in stock_count_profiles()
    )
    candidates.extend(
        ExperimentCandidate(f"defensive__{variant.name}", "defensive", _ANCHOR,
                            crash_overlay=variant)
        for variant in crash_overlay_variants()
    )
    candidates.extend(
        ExperimentCandidate(
            f"defensive__{core.name}__{protection.name}", "defensive", core,
            profit_protection=protection,
        )
        for core in defensive_cores for protection in profit_protection_variants()
    )
    return candidates


def build_candidate_catalog(
    ranked_return_cores: Sequence[Any] | None = None,
    ranked_defensive_cores: Sequence[Any] | None = None,
) -> pd.DataFrame:
    candidates = _core_candidates() + build_route_candidates(ranked_return_cores, ranked_defensive_cores)
    rows = [{
        "name": candidate.name,
        "route": candidate.route,
        "family": candidate_family(candidate),
        "parameter_hash": _candidate_parameter_hash(candidate),
        "parameters_json": json.dumps(_jsonable(candidate), ensure_ascii=False, sort_keys=True),
    } for candidate in candidates]
    frame = pd.DataFrame(rows)
    if not frame["name"].is_unique or not frame["parameter_hash"].is_unique:
        raise ValueError("candidate catalog contains duplicate names or parameter hashes")
    return frame


def build_run_manifest(output: str | Path = DEFAULT_OUTPUT, execute: bool = False) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "output": str(Path(output)),
        "execute": bool(execute),
        "core_one_factor_count": len(core_one_factor_variants()),
        "core_orthogonal_count": len(core_l18_variants()),
        "core_orthogonal_max_count": 18,
        "recovery_count": len(recovery_variants()),
        "stock_profile_count": len(stock_count_profiles()),
        "crash_overlay_count": len(crash_overlay_variants()),
        "profit_protection_count": len(profit_protection_variants()),
        "full_sample_candidate_limit": 70,
        "test_call_limit": 45,
        "stage_status": {stage: "pending" for stage in ("core", "routes", "walkforward", "stress")},
        "passed": False,
    }


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def _score_result(result: ExperimentResult, target_hash: str, run_hash: str) -> dict[str, Any]:
    metrics = result.experiment.metrics
    diagnostics = result.diagnostics
    return {
        "candidate": result.candidate.name,
        "route": result.candidate.route,
        "family": candidate_family(result.candidate),
        "total_return": float(metrics["total_return"]),
        "annualized_return": float(metrics["annualized_return"]),
        "max_drawdown": float(metrics["max_drawdown"]),
        "sharpe": float(metrics["sharpe"]),
        "calmar": float(diagnostics["calmar"]),
        "max_underwater_calendar_days": int(diagnostics["max_underwater_calendar_days"]),
        "trade_count": int(metrics["trade_count"]),
        "win_rate": float(metrics["win_rate"]),
        "turnover": float(metrics["turnover"]),
        "minimum_cash": float(diagnostics["minimum_cash"]),
        "account_reconciliation_error": float(diagnostics["account_reconciliation_error"]),
        "mean_exposure_budget": float(diagnostics["mean_exposure_budget"]),
        "defensive_budget_days": int(diagnostics["defensive_budget_days"]),
        "target_hash": target_hash,
        "candidate_hash": run_hash,
    }


def run_current_db_v2_anchor_reference(
    inputs: ExperimentInputs, config: SmallCapExperimentConfig
) -> pd.DataFrame:
    """Execute the pre-existing V2 grid path independently for same-snapshot audit."""
    budget = build_gradual_crowding_budget(inputs.crowding_daily)
    result = run_grid(
        inputs.bars, inputs.frozen_targets, config,
        variants=[GridVariant("fixed11_gradual", fixed_stop_loss=0.11,
                              enable_atr=False, enable_crowding_daily=False)],
        market_daily=inputs.market_daily, index_bars=inputs.index_bars,
        crowding_daily=inputs.crowding_daily, exposure_budget_daily=budget,
    )[0]
    return result.experiment.backtest.equity_curve.copy()


def compare_equity_curves(actual: pd.DataFrame, expected: pd.DataFrame) -> float:
    left = actual.loc[:, ["trade_date", "equity"]].copy()
    right = expected.loc[:, ["trade_date", "equity"]].copy()
    left["trade_date"] = pd.to_datetime(left["trade_date"])
    right["trade_date"] = pd.to_datetime(right["trade_date"])
    aligned = left.merge(right, on="trade_date", suffixes=("_actual", "_expected"),
                         validate="one_to_one")
    if len(aligned) != len(left) or len(aligned) != len(right):
        return math.inf
    return float((aligned["equity_actual"] - aligned["equity_expected"]).abs().max())


def _read_score(run_dir: Path) -> dict[str, Any]:
    return json.loads((run_dir / "audit.json").read_text(encoding="utf-8-sig"))["score"]


def persist_candidate_result(
    output: Path, result: ExperimentResult, target_hash: str, run_hash: str,
    *, cost_model: CostModel, run_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    context = {"phase": "full_sample", "fold": "", **dict(run_context or {})}
    run_dir = output / "candidates" / _safe_name(result.candidate.name) / run_hash[:16]
    curve = result.experiment.backtest.equity_curve
    write_csv(curve, run_dir / "equity.csv")
    write_csv(result.experiment.backtest.trades, run_dir / "trades.csv")
    write_csv(result.experiment.backtest.rejections, run_dir / "rejections.csv")
    write_csv(result.experiment.backtest.positions, run_dir / "positions.csv")
    write_csv(result.exposure_budget, run_dir / "exposure_budget.csv")
    write_json(run_dir / "parameters.json", {
        "candidate": result.candidate, "cost_model": cost_model,
        "schema_version": SCHEMA_VERSION, "run_context": context,
    })
    (run_dir / "target_hash.txt").write_text(target_hash, encoding="ascii")
    (run_dir / "run_hash.txt").write_text(run_hash, encoding="ascii")
    score = _score_result(result, target_hash, run_hash)
    write_json(run_dir / "audit.json", {
        "candidate_hash": run_hash,
        "passed": score["account_reconciliation_error"] < 1e-6 and score["minimum_cash"] >= 0,
        "account_reconciliation_error": score["account_reconciliation_error"],
        "minimum_cash": score["minimum_cash"],
        "artifacts_complete": True,
        "run_context": context,
        "score": score,
    })
    return {"run_dir": str(run_dir), **score}


def _period_inputs(inputs: ExperimentInputs, targets: pd.DataFrame, start: str, end: str) -> ExperimentInputs:
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    bars = inputs.bars.loc[pd.to_datetime(inputs.bars["trade_date"]).between(start_ts, end_ts)].copy()
    selected = targets.loc[pd.to_datetime(targets["signal_date"]).between(start_ts, end_ts)].copy()
    target_sets = None
    if inputs.target_sets:
        target_sets = {
            name: frame.loc[pd.to_datetime(frame["signal_date"]).between(start_ts, end_ts)].copy()
            for name, frame in inputs.target_sets.items()
        }
    market = inputs.market_daily
    if market is not None and not market.empty:
        market = market.loc[pd.to_datetime(market["trade_date"]).between(start_ts, end_ts)].copy()
    return ExperimentInputs(bars, selected, inputs.crowding_daily, inputs.index_bars,
                            market_daily=market, target_sets=target_sets)


def _load_context(db: Path, start: str, end: str, initial_cash: float) -> tuple[ExperimentInputs, dict[str, str], pd.DataFrame]:
    repo = DuckDBRepository(db)
    strict_inputs = repo.load_strict_small_cap_selection_inputs(start, end)
    frozen = load_frozen_targets(DEFAULT_TARGETS)
    target_sets: dict[str, pd.DataFrame] = {}
    target_hashes = {"fixed11_gradual": target_frame_hash(frozen)}
    for profile in stock_count_profiles():
        targets, _, _ = build_joinquant_v3_targets(
            strict_inputs, SmallCapParams(), fix_known_source_bugs=True,
            dynamic_stock_counts=profile.counts, profile_name=profile.name,
        )
        target_sets[profile.name] = targets
        target_hashes[profile.name] = target_frame_hash(targets)
    symbols = sorted(set(frozen["symbol"].astype(str)).union(
        *(set(frame["symbol"].astype(str)) for frame in target_sets.values())
    ).union({"511880"}))
    bars = repo.load_execution_bars(symbols, start, end)
    inputs = ExperimentInputs(
        bars=bars, frozen_targets=frozen,
        crowding_daily=strict_inputs["crowding"],
        index_bars=strict_inputs["index_prices"],
        market_daily=strict_inputs["market_down"], target_sets=target_sets,
    )
    return inputs, target_hashes, strict_inputs["snapshots"]


def _candidate_target_hash(candidate: ExperimentCandidate, target_hashes: Mapping[str, str]) -> str:
    return target_hashes[candidate.stock_profile.name] if candidate.stock_profile else target_hashes["fixed11_gradual"]


def _run_full_candidate(
    candidate: ExperimentCandidate, inputs: ExperimentInputs, target_hashes: Mapping[str, str],
    config: SmallCapExperimentConfig, output: Path, costs: CostModel, resume: bool,
    input_data_fingerprint: str,
    run_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    target_hash = _candidate_target_hash(candidate, target_hashes)
    run_hash = candidate_run_hash(candidate=candidate, source_target_hash=target_hash,
                                  start=config.start_date, end=config.end_date,
                                  initial_cash=config.initial_cash, costs=costs,
                                  input_data_fingerprint=input_data_fingerprint)
    run_dir = output / "candidates" / _safe_name(candidate.name) / run_hash[:16]
    if resume and should_resume(run_dir, run_hash):
        return _read_score(run_dir)
    result = run_candidate(inputs, candidate, config, costs=costs)
    context = {"input_data_fingerprint": input_data_fingerprint, **dict(run_context or {})}
    return persist_candidate_result(output, result, target_hash, run_hash, cost_model=costs,
                                    run_context=context)


def _core_vector(core: Any) -> tuple[Any, ...]:
    return tuple(getattr(core, field.name) for field in fields(core) if field.name != "name")


def _stable_core_names(scores: pd.DataFrame, metric: str, tolerance: float = 0.10) -> set[str]:
    cores = {item.name: item for item in core_one_factor_variants() + core_l18_variants()}
    values = scores.set_index("candidate")[metric].astype(float).to_dict()
    stable: set[str] = set()
    for name, core in cores.items():
        if name not in values:
            continue
        vector = _core_vector(core)
        neighbors = [
            other_name for other_name, other in cores.items()
            if other_name != name and other_name in values
            and sum(left != right for left, right in zip(vector, _core_vector(other), strict=True)) <= 1
        ]
        denominator = max(abs(values[name]), 1e-12)
        close = sum(abs(values[neighbor] - values[name]) / denominator <= tolerance
                    for neighbor in neighbors)
        if close >= 2:
            stable.add(name)
    return stable


def rank_core_variants(scores: pd.DataFrame) -> tuple[list[Any], list[Any], pd.DataFrame]:
    anchors = scores.loc[scores["candidate"].eq("fixed11_gradual")]
    if len(anchors) != 1:
        raise ValueError("core scores must contain exactly one fixed11_gradual anchor")
    anchor = anchors.iloc[0]
    audit_mask = scores["account_reconciliation_error"].lt(1e-6) & scores["minimum_cash"].ge(0)
    drawdown_mask = scores["max_drawdown"].ge(-0.35)
    audited = scores.loc[audit_mask & drawdown_mask].copy()
    return_eligible = audited.loc[
        audited["total_return"].gt(float(anchor["total_return"]))
    ].copy()
    defensive_eligible = audited.loc[
        audited["max_drawdown"].gt(float(anchor["max_drawdown"]))
    ].copy()
    core_by_name = {item.name: item for item in core_one_factor_variants() + core_l18_variants()}
    return_stable = _stable_core_names(return_eligible, "total_return")
    defensive_stable = _stable_core_names(defensive_eligible, "max_drawdown")
    return_names = return_eligible.loc[return_eligible["candidate"].isin(return_stable)].sort_values(
        ["total_return", "max_drawdown"], ascending=[False, False]
    )["candidate"].tolist()
    defensive_names = defensive_eligible.loc[
        defensive_eligible["candidate"].isin(defensive_stable)
    ].sort_values(
        ["max_drawdown", "annualized_return"], ascending=[False, False]
    )["candidate"].tolist()
    selected_return = [core_by_name[name] for name in return_names if name in core_by_name][:3]
    selected_defensive = [core_by_name[name] for name in defensive_names if name in core_by_name][:2]
    audited_names = set(audited["candidate"])
    return_eligible_names = set(return_eligible["candidate"])
    defensive_eligible_names = set(defensive_eligible["candidate"])
    rejected_rows: list[dict[str, Any]] = []
    for route, stable_names, ranked_names, limit in (
        ("return", return_stable, return_names, 3),
        ("defensive", defensive_stable, defensive_names, 2),
    ):
        selected_names = set(ranked_names[:limit])
        for row in scores.to_dict("records"):
            name = str(row["candidate"])
            if name in selected_names:
                continue
            parts = []
            if name not in audited_names:
                if not bool(audit_mask.loc[scores["candidate"].eq(name)].iloc[0]):
                    parts.append("account_audit")
                if not bool(drawdown_mask.loc[scores["candidate"].eq(name)].iloc[0]):
                    parts.append("drawdown_floor")
            eligible_names = return_eligible_names if route == "return" else defensive_eligible_names
            if name in audited_names and name not in eligible_names:
                parts.append("not_better_than_anchor")
            if name not in stable_names:
                parts.append("neighbor_stability")
            if not parts:
                parts.append("not_route_ranked")
            rejected_rows.append({**row, "rejected_for_route": route,
                                  "reason": ";".join(parts)})
    rejected = pd.DataFrame(rejected_rows)
    return selected_return, selected_defensive, rejected


def _existing_or_empty(path: Path) -> pd.DataFrame:
    if not path.exists() or not path.stat().st_size:
        return pd.DataFrame()
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def append_rejected(output: Path, rows: pd.DataFrame) -> None:
    if rows.empty:
        return
    path = output / "rejected_candidates.csv"
    existing = _existing_or_empty(path)
    combined = pd.concat([existing, rows], ignore_index=True, sort=False)
    combined = combined.drop_duplicates().reset_index(drop=True)
    write_csv(combined, path)


def _ensure_root_artifacts(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for name in ROOT_ARTIFACTS:
        path = output / name
        if path.exists():
            continue
        if name.endswith(".json"):
            write_json(path, {})
        else:
            write_csv(pd.DataFrame(), path)


def completion_gate(manifest: Mapping[str, Any], output: str | Path) -> bool:
    required_stages = ("core", "routes", "walkforward", "stress")
    if any(manifest.get("stage_status", {}).get(stage) != "complete" for stage in required_stages):
        return False
    checks = (
        bool(manifest.get("database_snapshot_unchanged")),
        float(manifest.get("anchor_max_abs_equity_diff", math.inf)) < 1e-6,
        float(manifest.get("max_account_reconciliation_error", math.inf)) < 1e-6,
        float(manifest.get("minimum_cash", -math.inf)) >= 0,
        int(manifest.get("test_selection_leakage_count", 1)) == 0,
        int(manifest.get("full_sample_candidate_count", 71)) <= 70,
        int(manifest.get("normal_test_call_count", 46)) <= 45,
        bool(manifest.get("cost_evidence_complete")),
        bool(manifest.get("stress_evidence_complete")),
    )
    if not all(checks):
        return False
    root = Path(output)
    try:
        for name in ROOT_ARTIFACTS:
            path = root / name
            if not path.is_file() or path.stat().st_size == 0:
                return False
            if name.endswith(".json"):
                if not json.loads(path.read_text(encoding="utf-8-sig")):
                    return False
            elif pd.read_csv(path, encoding="utf-8-sig").empty:
                return False
    except (OSError, UnicodeError, json.JSONDecodeError, pd.errors.ParserError,
            pd.errors.EmptyDataError, TypeError, ValueError):
        return False
    return True


def _baseline_path() -> Path | None:
    return next((path for path in BASELINE_CANDIDATES if path.exists()), None)


def _anchor_curve(output: Path, anchor_score: Mapping[str, Any]) -> pd.DataFrame:
    run_dir = output / "candidates" / "fixed11_gradual" / str(anchor_score["candidate_hash"])[:16]
    return pd.read_csv(run_dir / "equity.csv", encoding="utf-8-sig")


def _historical_anchor_drift(output: Path, anchor_score: Mapping[str, Any]) -> dict[str, Any]:
    baseline = _baseline_path()
    if baseline is None:
        return {"path": None, "file_sha256": None, "end_equity": None,
                "max_abs_equity_diff": None}
    actual = _anchor_curve(output, anchor_score)
    expected = pd.read_csv(baseline, encoding="utf-8-sig")
    return {
        "path": str(baseline),
        "file_sha256": hashlib.sha256(baseline.read_bytes()).hexdigest(),
        "end_equity": float(expected["equity"].iloc[-1]),
        "max_abs_equity_diff": compare_equity_curves(actual, expected),
    }


def _append_annual(output: Path, candidate: str, result_dir: Path) -> pd.DataFrame:
    curve = pd.read_csv(result_dir / "equity.csv", encoding="utf-8-sig")
    curve["trade_date"] = pd.to_datetime(curve["trade_date"])
    curve["year"] = curve["trade_date"].dt.year
    annual = curve.groupby("year")["equity"].agg(["first", "last"]).reset_index()
    annual.insert(0, "candidate", candidate)
    annual["return"] = annual["last"] / annual["first"] - 1
    return annual[["candidate", "year", "return"]]


def rebuild_annual_returns(
    output: str | Path, *, input_data_fingerprint: str | None = None,
) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for audit_path in sorted(Path(output).glob("candidates/*/*/audit.json")):
        try:
            audit = json.loads(audit_path.read_text(encoding="utf-8-sig"))
            curve = pd.read_csv(audit_path.parent / "equity.csv", encoding="utf-8-sig")
        except (OSError, UnicodeError, json.JSONDecodeError, pd.errors.ParserError,
                pd.errors.EmptyDataError):
            continue
        if curve.empty:
            continue
        context = audit.get("run_context", {})
        if (input_data_fingerprint is not None
                and context.get("input_data_fingerprint") != input_data_fingerprint):
            continue
        curve["trade_date"] = pd.to_datetime(curve["trade_date"])
        curve["year"] = curve["trade_date"].dt.year
        annual = curve.groupby("year")["equity"].agg(["first", "last"]).reset_index()
        annual["return"] = (annual["last"] / annual["first"] - 1.0).round(12)
        score = audit.get("score", {})
        annual.insert(0, "run_hash", audit.get("candidate_hash"))
        annual.insert(0, "fold", context.get("fold", ""))
        annual.insert(0, "phase", context.get("phase", "full_sample"))
        annual.insert(0, "route", score.get("route", ""))
        annual.insert(0, "candidate", score.get("candidate", audit_path.parents[1].name))
        rows.append(annual[["candidate", "route", "phase", "fold", "run_hash", "year", "return"]])
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=[
        "candidate", "route", "phase", "fold", "run_hash", "year", "return",
    ])


def _walkforward_runner(
    inputs: ExperimentInputs, target_hashes: Mapping[str, str], initial_cash: float,
    costs: CostModel, *, output: Path, resume: bool, input_data_fingerprint: str,
):
    def runner(*, candidate: ExperimentCandidate, start: pd.Timestamp, end: pd.Timestamp,
               phase: str, fold: str) -> dict[str, Any]:
        targets = inputs.target_sets[candidate.stock_profile.name] if candidate.stock_profile else inputs.frozen_targets
        period = _period_inputs(inputs, targets, str(pd.Timestamp(start).date()), str(pd.Timestamp(end).date()))
        config = SmallCapExperimentConfig(start_date=str(pd.Timestamp(start).date()),
                                          end_date=str(pd.Timestamp(end).date()), initial_cash=initial_cash)
        score = _run_full_candidate(
            candidate, period, target_hashes, config, output, costs, resume,
            input_data_fingerprint, run_context={"phase": phase, "fold": fold},
        )
        return {key: score[key] for key in (
            "total_return", "annualized_return", "max_drawdown", "sharpe", "calmar",
            "max_underwater_calendar_days",
        )} | {"observation_date": pd.Timestamp(end)}
    return runner


def _combined_drawdown(returns: Iterable[float]) -> float:
    wealth = pd.Series([1.0, *pd.Series(list(returns), dtype=float).add(1.0).cumprod().tolist()])
    return float((wealth / wealth.cummax() - 1.0).min())


def run_stages(args: argparse.Namespace) -> dict[str, Any]:
    output = Path(args.output).resolve()
    _ensure_root_artifacts(output)
    manifest_path = output / "run_manifest.json"
    manifest = build_run_manifest(output, execute=True)
    if args.resume and manifest_path.exists():
        try:
            prior = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            manifest.update(prior)
        except json.JSONDecodeError:
            pass
    DuckDBRepository(Path(args.db)).initialize()
    db_before = database_snapshot(args.db)
    manifest.update({"requested_start": args.start, "requested_end": args.end,
                     "initial_cash": args.initial_cash, "db": str(Path(args.db).resolve())})
    manifest["database_snapshot_before"] = db_before
    write_json(manifest_path, manifest)
    inputs, target_hashes, snapshots = _load_context(Path(args.db), args.start, args.end, args.initial_cash)
    manifest["input_date_coverage"] = {
        "bars_start": str(pd.to_datetime(inputs.bars["trade_date"]).min().date()),
        "bars_end": str(pd.to_datetime(inputs.bars["trade_date"]).max().date()),
        "snapshot_start": str(pd.to_datetime(snapshots["signal_date"]).min().date()),
        "snapshot_end": str(pd.to_datetime(snapshots["signal_date"]).max().date()),
    }
    manifest["target_hashes"] = target_hashes
    target_rows = [{"target_name": name, "target_hash": value,
                    "row_count": len(inputs.frozen_targets if name == "fixed11_gradual" else inputs.target_sets[name])}
                   for name, value in target_hashes.items()]
    write_csv(pd.DataFrame(target_rows), output / "target_manifest.csv",
              ["target_name", "target_hash", "row_count"])
    costs = CostModel()
    config = SmallCapExperimentConfig(start_date=args.start, end_date=args.end,
                                      initial_cash=args.initial_cash)
    requested = {args.stage} if args.stage != "all" else {"core", "routes", "walkforward", "stress"}

    if "core" in requested or any(stage in requested for stage in ("routes", "walkforward", "stress")):
        rows = []
        annual = []
        for index, candidate in enumerate(_core_candidates(), start=1):
            score = _run_full_candidate(candidate, inputs, target_hashes, config, output, costs,
                                        args.resume, db_before["sha256"])
            rows.append(score)
            run_dir = output / "candidates" / _safe_name(candidate.name) / score["candidate_hash"][:16]
            annual.append(_append_annual(output, candidate.name, run_dir))
            print(f"core {index}/{len(_core_candidates())}: {candidate.name}", flush=True)
        core_scores = pd.DataFrame(rows)
        write_csv(core_scores, output / "core_scores.csv", SCORE_COLUMNS)
        write_csv(pd.concat(annual, ignore_index=True), output / "annual_returns.csv",
                  ["candidate", "year", "return"])
        anchor = core_scores.loc[core_scores["candidate"].eq("fixed11_gradual")].iloc[0]
        reference = run_current_db_v2_anchor_reference(inputs, config)
        reference_path = output / "current_db_anchor_reference.csv"
        write_csv(reference, reference_path)
        actual_anchor = _anchor_curve(output, anchor)
        manifest.update({"anchor_source": str(reference_path),
                         "anchor_reference_sha256": hashlib.sha256(reference_path.read_bytes()).hexdigest(),
                         "anchor_max_abs_equity_diff": compare_equity_curves(actual_anchor, reference),
                         "historical_snapshot_drift": _historical_anchor_drift(output, anchor),
                         "core_full_sample_call_count": len(core_scores)})
        manifest["stage_status"]["core"] = "complete"
        write_json(manifest_path, manifest)
    else:
        core_scores = _existing_or_empty(output / "core_scores.csv")

    if any(stage in requested for stage in ("routes", "walkforward", "stress")):
        if core_scores.empty:
            raise RuntimeError("core scores are required before route stages")
        ranked_return, ranked_defensive, rejected = rank_core_variants(core_scores)
        missing_stable_rows = []
        if not ranked_return:
            missing_stable_rows.append({"rejected_for_route": "return", "candidate": "",
                                        "reason": "no_stable_core", "phase": "core_ranking"})
        if not ranked_defensive:
            missing_stable_rows.append({"rejected_for_route": "defensive_profit", "candidate": "",
                                        "reason": "no_stable_core", "phase": "core_ranking"})
        route_candidates = build_route_candidates(ranked_return, ranked_defensive)
        write_csv(build_candidate_catalog(ranked_return, ranked_defensive), output / "candidate_catalog.csv",
                  ["name", "route", "family", "parameter_hash", "parameters_json"])
        if "routes" in requested or args.stage in ("walkforward", "stress"):
            route_rows = []
            for index, candidate in enumerate(route_candidates, start=1):
                score = _run_full_candidate(candidate, inputs, target_hashes, config, output, costs,
                                            args.resume, db_before["sha256"])
                route_rows.append(score)
                print(f"routes {index}/{len(route_candidates)}: {candidate.name}", flush=True)
            route_scores = pd.DataFrame(route_rows)
            write_csv(route_scores, output / "route_scores.csv", SCORE_COLUMNS)
            append_rejected(output, pd.concat([
                rejected, pd.DataFrame(missing_stable_rows)
            ], ignore_index=True, sort=False))
            manifest["route_full_sample_call_count"] = len(route_scores)
            manifest["full_sample_candidate_count"] = len(core_scores) + len(route_scores)
            manifest["stage_status"]["routes"] = "complete"
            write_json(manifest_path, manifest)

        if any(stage in requested for stage in ("walkforward", "stress")):
            universe = [ExperimentCandidate.anchor(), *route_candidates]
            folds = default_folds(pd.Timestamp(args.end))
            wf = run_walk_forward(universe, folds, _walkforward_runner(
                inputs, target_hashes, args.initial_cash, costs, output=output,
                resume=args.resume, input_data_fingerprint=db_before["sha256"],
            ))
            write_csv(wf.training_scores, output / "walkforward_training.csv")
            test_frame = wf.test_scores.copy()
            write_csv(test_frame, output / "walkforward_test.csv")
            gates = [asdict(item) for item in wf.gate_results]
            write_csv(pd.DataFrame(gates), output / "route_gate_results.csv")
            selected_keys = set(
                zip(wf.selections["fold"], wf.selections["route"], wf.selections["candidate"])
            ) if not wf.selections.empty else set()
            training_rejections = []
            for row in wf.training_scores.loc[wf.training_scores["route"].isin(ROUTES)].itertuples(index=False):
                if (row.fold, row.route, row.candidate) not in selected_keys:
                    training_rejections.append({
                        "candidate": row.candidate, "rejected_for_route": row.route,
                        "fold": row.fold, "phase": "walkforward_training",
                        "reason": "not_selected_training",
                    })
            append_rejected(output, pd.DataFrame(training_rejections))
            selected_test_count = len(test_frame.loc[~test_frame["route"].eq("anchor")])
            leakage = 0
            if not wf.selections.empty:
                leakage = int((pd.to_datetime(wf.selections["observation_date"]) >
                               pd.to_datetime(wf.selections["selected_on_train_end"])).sum())
            manifest.update({"normal_test_call_count": selected_test_count,
                             "test_selection_leakage_count": leakage})
            manifest["stage_status"]["walkforward"] = "complete"
            write_json(manifest_path, manifest)

        if "stress" in requested:
            policy = wf.policy_scores
            anchor_tests = wf.test_scores.loc[wf.test_scores["route"].eq("anchor")]
            stress_rows: list[dict[str, Any]] = []
            gate_rows: list[dict[str, Any]] = []
            by_name = {item.name: item for item in universe}
            fold_by_name = {fold.name: fold for fold in folds}
            model_matrix = cost_stress_models(costs)
            cost_rows: list[dict[str, Any]] = []
            stress_gate_by_route: dict[str, pd.DataFrame] = {}
            policy_counts = policy.groupby("route").size().to_dict() if not policy.empty else {}
            for route in ROUTES:
                route_policy = policy.loc[policy["route"].eq(route)].copy()
                if len(route_policy) != 5:
                    stress_rows.append({"evidence_type": "missing_policy", "route": route,
                                        "status": "no_stable_training_policy",
                                        "policy_fold_count": len(route_policy)})
                    continue
                for policy_row in route_policy.itertuples(index=False):
                    fold = fold_by_name[policy_row.fold]
                    for cost_label, cost_model in model_matrix.items():
                        runner = _walkforward_runner(
                            inputs, target_hashes, args.initial_cash, cost_model,
                            output=output, resume=args.resume,
                            input_data_fingerprint=db_before["sha256"],
                        )
                        for series, candidate in (
                            ("candidate", by_name[policy_row.candidate]),
                            ("anchor", ExperimentCandidate.anchor()),
                        ):
                            score = runner(
                                candidate=candidate, start=fold.test_start, end=fold.test_end,
                                phase=f"cost_{cost_label}", fold=fold.name,
                            )
                            row = {
                                "evidence_type": "cost", "route": route,
                                "fold": fold.name, "series": series,
                                "candidate": candidate.name, "cost_label": cost_label,
                                **{key: score[key] for key in (
                                    "total_return", "annualized_return", "max_drawdown",
                                    "sharpe", "calmar", "max_underwater_calendar_days",
                                )},
                            }
                            cost_rows.append(row)
                            stress_rows.append(row)

                window_rows: list[dict[str, Any]] = []
                for window, fold_name, start, end in (
                    ("2024_q1", "fold_2024", "2024-01-01", "2024-03-31"),
                    ("2026_ytd", "fold_2026", "2026-01-01", args.end),
                ):
                    selected_name = route_policy.loc[
                        route_policy["fold"].eq(fold_name), "candidate"
                    ].item()
                    runner = _walkforward_runner(
                        inputs, target_hashes, args.initial_cash, costs, output=output,
                        resume=args.resume, input_data_fingerprint=db_before["sha256"],
                    )
                    results = {}
                    for series, candidate in (
                        ("candidate", by_name[selected_name]),
                        ("anchor", ExperimentCandidate.anchor()),
                    ):
                        results[series] = runner(
                            candidate=candidate, start=pd.Timestamp(start), end=pd.Timestamp(end),
                            phase="stress", fold=window,
                        )
                        stress_rows.append({
                            "evidence_type": "stress_window", "route": route,
                            "window": window, "fold": fold_name, "series": series,
                            "candidate": candidate.name, **results[series],
                        })
                    window_rows.append({
                        "window": window,
                        "candidate_max_drawdown": results["candidate"]["max_drawdown"],
                        "anchor_max_drawdown": results["anchor"]["max_drawdown"],
                    })
                stress_gate_by_route[route] = pd.DataFrame(window_rows)

            return_policy = policy.loc[policy["route"].eq("return")].copy()
            for route in ROUTES:
                route_policy = policy.loc[policy["route"].eq(route)].copy()
                if len(route_policy) != 5:
                    gate_rows.append(asdict(next(item for item in wf.gate_results if item.route == route)))
                    continue
                if route == "return":
                    route_policy["combined_max_drawdown"] = _combined_drawdown(
                        route_policy["total_return"]
                    )
                    gate_costs = pd.DataFrame(cost_rows)
                    gate_costs = gate_costs.loc[
                        gate_costs["route"].eq("return")
                        & gate_costs["cost_label"].eq("combined_2x"),
                        ["fold", "series", "total_return"],
                    ]
                    gate = evaluate_route_gates(route, route_policy, anchor_tests,
                                                cost_2x_scores=gate_costs)
                elif route == "defensive":
                    gate = evaluate_route_gates(
                        route, route_policy, anchor_tests,
                        stress_scores=stress_gate_by_route[route],
                    )
                else:
                    gate = evaluate_route_gates(route, route_policy, anchor_tests)
                gate_rows.append(asdict(gate))
            write_csv(pd.DataFrame(stress_rows), output / "stress_results.csv")
            write_csv(pd.DataFrame(gate_rows), output / "route_gate_results.csv")
            gate_rejections = [{
                "candidate": row.get("selected_candidate") or "",
                "rejected_for_route": row["route"], "phase": "route_gate",
                "reason": ";".join(row.get("reasons", ())),
            } for row in gate_rows if not row.get("passed")]
            append_rejected(output, pd.DataFrame(gate_rejections))
            eligible_route_count = sum(policy_counts.get(route, 0) == 5 for route in ROUTES)
            manifest["cost_models"] = {name: _jsonable(model)
                                       for name, model in model_matrix.items()}
            manifest["cost_evidence_complete"] = bool(
                all(policy_counts.get(route, 0) in (0, 5) for route in ROUTES)
                and len(cost_rows) == eligible_route_count * 5 * 2 * len(model_matrix)
            )
            stress_window_rows = [row for row in stress_rows
                                  if row.get("evidence_type") == "stress_window"]
            manifest["stress_evidence_complete"] = bool(
                all(policy_counts.get(route, 0) in (0, 5) for route in ROUTES)
                and len(stress_window_rows) == eligible_route_count * 2 * 2
            )
            manifest["stage_status"]["stress"] = "complete"

    write_csv(rebuild_annual_returns(output, input_data_fingerprint=db_before["sha256"]),
              output / "annual_returns.csv",
              ["candidate", "route", "phase", "fold", "run_hash", "year", "return"])
    all_scores = pd.concat([_existing_or_empty(output / "core_scores.csv"),
                            _existing_or_empty(output / "route_scores.csv")], ignore_index=True)
    audit_rows = []
    for audit_path in output.glob("candidates/*/*/audit.json"):
        try:
            audit = json.loads(audit_path.read_text(encoding="utf-8-sig"))
            if audit.get("run_context", {}).get("input_data_fingerprint") == db_before["sha256"]:
                audit_rows.append(audit)
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
    if audit_rows:
        manifest["max_account_reconciliation_error"] = max(
            float(row.get("account_reconciliation_error", math.inf)) for row in audit_rows
        )
        manifest["minimum_cash"] = min(
            float(row.get("minimum_cash", -math.inf)) for row in audit_rows
        )
    manifest["executed_run_count"] = len(audit_rows)
    db_after = database_snapshot(args.db)
    manifest["database_snapshot_after"] = db_after
    manifest["database_snapshot_unchanged"] = db_before == db_after
    manifest["passed"] = False
    write_json(manifest_path, manifest)
    manifest["passed"] = completion_gate(manifest, output)
    write_json(manifest_path, manifest)
    return manifest


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run fixed11_gradual next-stage research")
    parser.add_argument("--db", default=str(ROOT / "data" / "market.duckdb"))
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default="2026-07-06")
    parser.add_argument("--initial-cash", type=float, default=1_000_000.0)
    parser.add_argument("--stage", choices=("core", "routes", "walkforward", "stress", "all"), default="all")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.dry_run:
        manifest = build_run_manifest(args.output, execute=False)
        _ensure_root_artifacts(Path(args.output))
        write_json(Path(args.output) / "run_manifest.json", manifest)
    else:
        manifest = run_stages(args)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
