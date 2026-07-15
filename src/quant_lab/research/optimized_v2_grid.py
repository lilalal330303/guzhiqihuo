from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from quant_lab.backtest.portfolio import DailyRiskConfig
from quant_lab.research.small_cap_experiment import (
    SmallCapExperimentConfig,
    SmallCapExperimentResult,
    run_small_cap_experiment,
)


@dataclass(frozen=True)
class GridVariant:
    name: str
    fixed_stop_loss: float = 0.09
    enable_atr: bool = False
    enable_cooldown: bool = True
    cooldown_days: int = 2
    crowding_danger: float = 0.48
    enable_crowding_daily: bool = True


@dataclass(frozen=True)
class GridRunResult:
    variant: GridVariant
    experiment: SmallCapExperimentResult
    diagnostics: dict[str, float | int]


def load_frozen_targets(path: str | Path) -> pd.DataFrame:
    targets = pd.read_csv(path, dtype={"symbol": str}, parse_dates=["signal_date"])
    required = {"signal_date", "symbol", "target_weight"}
    missing = required.difference(targets.columns)
    if missing:
        raise ValueError(f"frozen targets missing columns: {sorted(missing)}")
    if not bool(targets["symbol"].str.fullmatch(r"\d{6}").fillna(False).all()):
        raise ValueError("frozen target symbols must be six digit strings")
    return targets.reset_index(drop=True)


def first_round_variants() -> list[GridVariant]:
    return [
        GridVariant("baseline"),
        GridVariant("fixed_stop_07", fixed_stop_loss=0.07),
        GridVariant("fixed_stop_11", fixed_stop_loss=0.11),
        GridVariant("fixed_stop_13", fixed_stop_loss=0.13),
        GridVariant("cooldown_0", enable_cooldown=False, cooldown_days=0),
        GridVariant("cooldown_1", cooldown_days=1),
        GridVariant("cooldown_3", cooldown_days=3),
        GridVariant("crowding_50", crowding_danger=0.50),
        GridVariant("crowding_52", crowding_danger=0.52),
        GridVariant("package_defensive", fixed_stop_loss=0.07, cooldown_days=3, crowding_danger=0.48),
        GridVariant("package_balanced", fixed_stop_loss=0.09, cooldown_days=1, crowding_danger=0.50),
        GridVariant(
            "package_aggressive", fixed_stop_loss=0.13, enable_cooldown=False,
            cooldown_days=0, crowding_danger=0.52,
        ),
    ]


def drawdown_diagnostics(
    equity_curve: pd.DataFrame, annualized_return: float
) -> dict[str, float | int]:
    if equity_curve.empty:
        return {"max_drawdown": 0.0, "calmar": 0.0, "max_underwater_calendar_days": 0}
    curve = equity_curve.loc[:, ["trade_date", "equity"]].copy()
    curve["trade_date"] = pd.to_datetime(curve["trade_date"])
    curve = curve.sort_values("trade_date").reset_index(drop=True)
    running_peak = curve["equity"].cummax()
    drawdown = curve["equity"] / running_peak - 1.0
    max_drawdown = round(float(drawdown.min()), 12)
    calmar = round(
        float(annualized_return / abs(max_drawdown)) if max_drawdown < 0 else 0.0,
        12,
    )
    peak_date = curve.iloc[0]["trade_date"]
    underwater_peak_date: pd.Timestamp | None = None
    max_days = 0
    for row, peak, decline in zip(curve.itertuples(), running_peak, drawdown, strict=True):
        date = pd.Timestamp(row.trade_date)
        if float(row.equity) >= float(peak):
            if underwater_peak_date is not None:
                max_days = max(max_days, int((date - underwater_peak_date).days))
                underwater_peak_date = None
            peak_date = date
        elif decline < 0 and underwater_peak_date is None:
            underwater_peak_date = peak_date
    if underwater_peak_date is not None:
        max_days = max(
            max_days,
            int((pd.Timestamp(curve.iloc[-1]["trade_date"]) - underwater_peak_date).days),
        )
    return {
        "max_drawdown": max_drawdown,
        "calmar": calmar,
        "max_underwater_calendar_days": max_days,
    }


def run_grid(
    bars: pd.DataFrame,
    targets: pd.DataFrame,
    config: SmallCapExperimentConfig,
    *,
    variants: list[GridVariant] | None = None,
    market_daily: pd.DataFrame | None = None,
    index_bars: pd.DataFrame | None = None,
    crowding_daily: pd.DataFrame | None = None,
    exposure_budget_daily: pd.DataFrame | None = None,
) -> list[GridRunResult]:
    runs: list[GridRunResult] = []
    for variant in variants or first_round_variants():
        risk = DailyRiskConfig(
            enable_atr=variant.enable_atr,
            fixed_stop_loss=variant.fixed_stop_loss,
            enable_cooldown=variant.enable_cooldown,
            cooldown_days=variant.cooldown_days,
            crowding_danger=variant.crowding_danger,
            enable_crowding_daily=variant.enable_crowding_daily,
        )
        experiment = run_small_cap_experiment(
            bars,
            targets,
            config,
            risk=risk,
            market_daily=market_daily,
            index_bars=index_bars,
            crowding_daily=crowding_daily,
            exposure_budget_daily=exposure_budget_daily,
            buy_new_only=True,
        )
        diagnostics = drawdown_diagnostics(
            experiment.backtest.equity_curve,
            float(experiment.metrics["annualized_return"]),
        )
        runs.append(GridRunResult(variant, experiment, diagnostics))
    return runs


def build_gradual_crowding_budget(
    crowding_daily: pd.DataFrame,
    *,
    warning_threshold: float = 0.48,
    clear_threshold: float = 0.50,
    confirmation_days: int = 2,
    reduced_budget: float = 0.25,
    recovery_threshold: float | None = None,
    recovery_confirmation_days: int = 1,
    recovery_step_days: int = 0,
) -> pd.DataFrame:
    required = {"trade_date", "concentration"}
    missing = required.difference(crowding_daily.columns)
    if missing:
        raise ValueError(f"crowding daily missing columns: {sorted(missing)}")
    if not 0 < warning_threshold < clear_threshold < 1:
        raise ValueError("require 0 < warning_threshold < clear_threshold < 1")
    if not 0 <= reduced_budget <= 1:
        raise ValueError("reduced_budget must be between 0 and 1")
    if confirmation_days < 1:
        raise ValueError("confirmation_days must be at least 1")
    if recovery_threshold is not None and not 0 < recovery_threshold < warning_threshold:
        raise ValueError("recovery_threshold must be between 0 and warning_threshold")
    if recovery_confirmation_days < 1:
        raise ValueError("recovery_confirmation_days must be at least 1")
    if recovery_step_days < 0:
        raise ValueError("recovery_step_days must be non-negative")

    frame = crowding_daily.loc[:, ["trade_date", "concentration"]].copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    if bool(frame["trade_date"].duplicated().any()):
        raise ValueError("crowding daily contains duplicate trade_date values")
    concentrations = pd.to_numeric(frame["concentration"], errors="coerce")
    if not bool(concentrations.map(math.isfinite).all()):
        raise ValueError("concentration must contain only finite values")
    frame["concentration"] = concentrations
    frame = frame.sort_values("trade_date").reset_index(drop=True)
    high_run = 0
    safe_run = 0
    recovery_stage_days_emitted = 0
    current_budget = 1.0
    budgets: list[float] = []
    for concentration in frame["concentration"]:
        if concentration >= clear_threshold:
            high_run += 1
            safe_run = 0
            recovery_stage_days_emitted = 0
            current_budget = 0.0
        elif concentration >= warning_threshold:
            high_run += 1
            safe_run = 0
            recovery_stage_days_emitted = 0
            current_budget = (
                0.0 if high_run >= confirmation_days else float(reduced_budget)
            )
        else:
            high_run = 0
            if recovery_threshold is None:
                safe_run = 0
                recovery_stage_days_emitted = 0
                current_budget = 1.0
            elif current_budget >= 1.0:
                safe_run = 0
                recovery_stage_days_emitted = 0
            elif concentration >= recovery_threshold:
                safe_run = 0
            else:
                safe_run += 1
                if safe_run >= recovery_confirmation_days:
                    if recovery_step_days == 0:
                        current_budget = 1.0
                        safe_run = 0
                        recovery_stage_days_emitted = 0
                    elif recovery_stage_days_emitted == 0:
                        current_budget = 0.5
                        recovery_stage_days_emitted = 1
                    elif recovery_stage_days_emitted < recovery_step_days:
                        current_budget = 0.5
                        recovery_stage_days_emitted += 1
                    else:
                        current_budget = 1.0
                        safe_run = 0
                        recovery_stage_days_emitted = 0
        budgets.append(current_budget)
    frame["exposure_budget"] = budgets
    return frame[["trade_date", "exposure_budget"]]


def build_market_state_budget(
    index_bars: pd.DataFrame,
    *,
    ma_short: int = 20,
    ma_long: int = 60,
    moderate_exposure: float = 0.70,
    defensive_exposure: float = 0.30,
    drawdown_threshold: float = 0.10,
) -> pd.DataFrame:
    frame = index_bars.loc[:, ["trade_date", "close"]].copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    frame = frame.sort_values("trade_date").reset_index(drop=True)
    close = frame["close"].astype(float)
    ma20 = close.rolling(ma_short, min_periods=ma_short).mean()
    ma60 = close.rolling(ma_long, min_periods=ma_long).mean()
    drawdown = close / close.cummax() - 1.0
    budget = pd.Series(1.0, index=frame.index)
    budget.loc[ma20.notna() & close.lt(ma20)] = moderate_exposure
    severe = (ma60.notna() & close.lt(ma60)) | drawdown.le(-drawdown_threshold)
    budget.loc[severe] = defensive_exposure
    frame["exposure_budget"] = budget
    return frame[["trade_date", "exposure_budget"]]
