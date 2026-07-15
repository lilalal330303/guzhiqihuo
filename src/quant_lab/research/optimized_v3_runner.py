from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import pandas as pd

from quant_lab.backtest.portfolio import CostModel, DailyRiskConfig, PortfolioBacktestResult
from quant_lab.research.optimized_v2_grid import (
    build_gradual_crowding_budget,
    drawdown_diagnostics,
)
from quant_lab.research.optimized_v3_design import (
    _ANCHOR,
    CoreVariant,
    CrashOverlayVariant,
    ProfitProtectionVariant,
    RecoveryVariant,
    StockCountProfile,
)
from quant_lab.research.optimized_v3_overlays import build_crash_exposure_budget
from quant_lab.research.small_cap_experiment import (
    SmallCapExperimentConfig,
    SmallCapExperimentResult,
    run_small_cap_experiment,
)


@dataclass(frozen=True)
class ExperimentCandidate:
    name: str
    route: str
    core: CoreVariant
    recovery: RecoveryVariant | None = None
    stock_profile: StockCountProfile | None = None
    crash_overlay: CrashOverlayVariant | None = None
    profit_protection: ProfitProtectionVariant | None = None

    @classmethod
    def anchor(cls) -> "ExperimentCandidate":
        return cls(name="fixed11_gradual", route="anchor", core=_ANCHOR)


@dataclass(frozen=True)
class ExperimentInputs:
    bars: pd.DataFrame
    frozen_targets: pd.DataFrame
    crowding_daily: pd.DataFrame
    index_bars: pd.DataFrame
    market_daily: pd.DataFrame | None = None
    target_sets: Mapping[str, pd.DataFrame] | None = None


@dataclass(frozen=True)
class ExperimentResult:
    candidate: ExperimentCandidate
    experiment: SmallCapExperimentResult
    diagnostics: dict[str, float | int]
    exposure_budget: pd.DataFrame


def reconcile_account(result: PortfolioBacktestResult) -> float:
    curve = result.equity_curve
    if curve.empty:
        return 0.0
    required = curve.loc[:, ["equity", "cash", "market_value"]].astype(float)
    return float((required["equity"] - required["cash"] - required["market_value"]).abs().max())


def _build_exposure_budget(
    inputs: ExperimentInputs, candidate: ExperimentCandidate
) -> pd.DataFrame:
    recovery = candidate.recovery
    crowding = build_gradual_crowding_budget(
        inputs.crowding_daily,
        warning_threshold=candidate.core.warning_threshold,
        clear_threshold=candidate.core.clear_threshold,
        confirmation_days=candidate.core.confirmation_days,
        reduced_budget=candidate.core.reduced_budget,
        recovery_threshold=(recovery.recovery_threshold if recovery is not None else None),
        recovery_confirmation_days=(recovery.confirmation_days if recovery is not None else 1),
        recovery_step_days=(recovery.recovery_step_days if recovery is not None else 0),
    ).loc[:, ["trade_date", "exposure_budget"]]
    crowding = crowding.copy()
    crowding["trade_date"] = pd.to_datetime(crowding["trade_date"]).dt.normalize()

    if candidate.crash_overlay is not None:
        overlay = candidate.crash_overlay
        crash = build_crash_exposure_budget(
            inputs.index_bars,
            drawdown_threshold=overlay.drawdown_threshold,
            defensive_budget=overlay.defensive_budget,
            recovery_confirmation_days=overlay.recovery_confirmation_days,
            lookback=overlay.lookback,
        ).loc[:, ["trade_date", "exposure_budget"]]
        crash = crash.rename(columns={"exposure_budget": "crash_budget"})
        crash["trade_date"] = pd.to_datetime(crash["trade_date"]).dt.normalize()
        crowding = crowding.merge(crash, on="trade_date", how="left", validate="one_to_one")
        crowding["crash_budget"] = crowding["crash_budget"].fillna(1.0)
        crowding["exposure_budget"] = crowding[["exposure_budget", "crash_budget"]].min(axis=1)

    final = crowding.loc[:, ["trade_date", "exposure_budget"]].sort_values("trade_date")
    if final["trade_date"].duplicated().any():
        raise ValueError("exposure budget contains duplicate trade_date values")
    return final.reset_index(drop=True)


def _select_targets(
    inputs: ExperimentInputs, candidate: ExperimentCandidate
) -> pd.DataFrame:
    if candidate.stock_profile is None:
        return inputs.frozen_targets
    profile_name = candidate.stock_profile.name
    if inputs.target_sets is None or profile_name not in inputs.target_sets:
        raise KeyError(f"target set {profile_name!r} is required for stock profile")
    return inputs.target_sets[profile_name]


def run_candidate(
    inputs: ExperimentInputs,
    candidate: ExperimentCandidate,
    config: SmallCapExperimentConfig,
    *,
    costs: CostModel | None = None,
) -> ExperimentResult:
    final_budget = _build_exposure_budget(inputs, candidate)
    protection = candidate.profit_protection
    risk = DailyRiskConfig(
        enable_atr=False,
        fixed_stop_loss=candidate.core.fixed_stop_loss,
        enable_cooldown=True,
        cooldown_days=candidate.core.cooldown_days,
        enable_crowding_daily=False,
        repair_cost_protection=protection is not None,
        profit_activation=(protection.activation_threshold if protection is not None else 0.30),
        profit_floor=(protection.floor if protection is not None else 0.10),
    )
    experiment = run_small_cap_experiment(
        inputs.bars,
        _select_targets(inputs, candidate),
        config,
        risk=risk,
        market_daily=inputs.market_daily,
        index_bars=inputs.index_bars,
        crowding_daily=inputs.crowding_daily,
        exposure_budget_daily=final_budget,
        buy_new_only=True,
        costs=costs,
    )

    curve = experiment.backtest.equity_curve
    reconciliation_error = reconcile_account(experiment.backtest)
    minimum_cash = float(curve["cash"].min()) if not curve.empty else 0.0
    if reconciliation_error >= 1e-6:
        raise RuntimeError(
            f"account reconciliation error {reconciliation_error:.12g} is at least 1e-6"
        )
    if minimum_cash < -1e-9:
        raise RuntimeError(f"minimum cash {minimum_cash:.12g} is below -1e-9")

    diagnostics = drawdown_diagnostics(
        curve, float(experiment.metrics["annualized_return"])
    )
    diagnostics.update({
        "end_equity": float(curve["equity"].iloc[-1]) if not curve.empty else 0.0,
        "minimum_cash": minimum_cash,
        "account_reconciliation_error": reconciliation_error,
        "mean_exposure_budget": (
            float(final_budget["exposure_budget"].mean()) if not final_budget.empty else 0.0
        ),
        "defensive_budget_days": int(final_budget["exposure_budget"].lt(1.0).sum()),
    })
    return ExperimentResult(candidate, experiment, diagnostics, final_budget)


def neighbor_stability(
    scores: Mapping[str, float],
    candidate: str,
    neighbors: Sequence[str],
    tolerance: float = 0.10,
) -> bool:
    if candidate not in scores:
        raise KeyError(f"candidate {candidate!r} does not exist in scores")
    if not math.isfinite(float(tolerance)) or not 0 <= tolerance < 1:
        raise ValueError("tolerance must be finite and satisfy 0 <= tolerance < 1")
    if any(not math.isfinite(float(score)) for score in scores.values()):
        raise ValueError("scores must contain only finite values")

    distinct_neighbors = set(neighbors)
    if candidate in distinct_neighbors:
        distinct_neighbors.remove(candidate)
    missing = distinct_neighbors.difference(scores)
    if missing:
        raise KeyError(f"neighbors missing from scores: {sorted(missing)}")
    if len(distinct_neighbors) < 2:
        raise ValueError("at least two distinct neighbors must exist in scores")

    candidate_score = float(scores[candidate])
    denominator = max(abs(candidate_score), 1e-12)
    close_count = sum(
        abs(float(scores[name]) - candidate_score) / denominator <= tolerance
        for name in distinct_neighbors
    )
    return close_count >= 2
