from pathlib import Path

import pandas as pd
import pytest

from quant_lab.research.optimized_v2_grid import (
    build_gradual_crowding_budget,
    build_market_state_budget,
    drawdown_diagnostics,
    first_round_variants,
    load_frozen_targets,
    run_grid,
)
from quant_lab.research.small_cap_experiment import SmallCapExperimentConfig


def test_frozen_target_loader_preserves_leading_zero_symbols(tmp_path: Path) -> None:
    target_file = tmp_path / "targets.csv"
    target_file.write_text(
        "signal_date,symbol,target_weight\n"
        "2020-01-07,002009,0.5\n"
        "2020-01-07,002001,0.5\n",
        encoding="utf-8",
    )

    targets = load_frozen_targets(target_file)

    assert targets["symbol"].tolist() == ["002009", "002001"]


def test_frozen_target_loader_rejects_symbols_without_six_digits(tmp_path: Path) -> None:
    target_file = tmp_path / "targets.csv"
    target_file.write_text(
        "signal_date,symbol,target_weight\n2020-01-07,2001,0.5\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="six digit"):
        load_frozen_targets(target_file)


def test_first_round_variants_are_unique_and_include_frozen_baseline() -> None:
    variants = first_round_variants()

    assert len(variants) == 12
    assert len({variant.name for variant in variants}) == len(variants)
    baseline = next(variant for variant in variants if variant.name == "baseline")
    assert baseline.fixed_stop_loss == 0.09
    assert baseline.enable_cooldown is True
    assert baseline.cooldown_days == 2
    assert baseline.crowding_danger == 0.48
    assert baseline.enable_crowding_daily is True
    assert baseline.enable_atr is False


def test_drawdown_diagnostics_reports_calmar_and_calendar_underwater_days() -> None:
    curve = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(
                ["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-06"]
            ),
            "equity": [100.0, 90.0, 95.0, 110.0],
        }
    )

    diagnostics = drawdown_diagnostics(curve, annualized_return=0.20)

    assert diagnostics["max_drawdown"] == -0.10
    assert diagnostics["calmar"] == 2.0
    assert diagnostics["max_underwater_calendar_days"] == 5


def test_run_grid_uses_variant_risk_settings_and_returns_one_result() -> None:
    bars = pd.DataFrame(
        [
            {"trade_date": "2020-01-01", "symbol": "002001", "open": 10.0, "high": 10.2, "low": 9.8, "close": 10.0, "paused": False, "is_st": False, "high_limit": 11.0, "low_limit": 9.0},
            {"trade_date": "2020-01-02", "symbol": "002001", "open": 10.0, "high": 10.3, "low": 9.9, "close": 10.2, "paused": False, "is_st": False, "high_limit": 11.0, "low_limit": 9.0},
            {"trade_date": "2020-01-03", "symbol": "002001", "open": 10.1, "high": 10.3, "low": 9.9, "close": 10.1, "paused": False, "is_st": False, "high_limit": 11.2, "low_limit": 9.2},
        ]
    )
    targets = pd.DataFrame(
        [{"signal_date": "2020-01-01", "symbol": "002001", "target_weight": 1.0}]
    )
    variant = first_round_variants()[0]

    runs = run_grid(
        bars,
        targets,
        SmallCapExperimentConfig(
            start_date="2020-01-01", end_date="2020-01-03", initial_cash=10_000.0
        ),
        variants=[variant],
        exposure_budget_daily=pd.DataFrame({
            "trade_date": pd.to_datetime(["2020-01-02"]),
            "exposure_budget": [0.25],
        }),
    )

    assert len(runs) == 1
    assert runs[0].variant == variant
    assert runs[0].experiment.metrics["trade_count"] == 2
    assert "risk_budget_reduce" in runs[0].experiment.backtest.trades["reason"].tolist()
    assert runs[0].diagnostics["calmar"] >= 0


def test_gradual_crowding_budget_reduces_then_clears_on_confirmation() -> None:
    crowding = pd.DataFrame({
        "trade_date": pd.date_range("2024-01-01", periods=5, freq="D"),
        "concentration": [0.47, 0.49, 0.49, 0.47, 0.51],
    })

    budget = build_gradual_crowding_budget(crowding)

    assert budget["exposure_budget"].tolist() == [1.0, 0.25, 0.0, 1.0, 0.0]


def test_gradual_budget_preserves_anchor_behavior() -> None:
    crowding = pd.DataFrame({
        "trade_date": pd.date_range("2024-01-02", periods=4, freq="D"),
        "concentration": [0.47, 0.48, 0.48, 0.47],
    })

    result = build_gradual_crowding_budget(crowding)

    assert result["exposure_budget"].tolist() == [1.0, 0.25, 0.0, 1.0]


def test_recovery_hysteresis_requires_safe_confirmation_and_steps_up() -> None:
    crowding = pd.DataFrame({
        "trade_date": pd.date_range("2024-01-02", periods=7, freq="D"),
        "concentration": [0.48, 0.48, 0.46, 0.44, 0.44, 0.44, 0.44],
    })

    result = build_gradual_crowding_budget(
        crowding,
        recovery_threshold=0.45,
        recovery_confirmation_days=2,
        recovery_step_days=1,
    )

    assert result["exposure_budget"].tolist() == [0.25, 0.0, 0.0, 0.0, 0.5, 1.0, 1.0]


def test_gradual_budget_rejects_duplicate_dates() -> None:
    crowding = pd.DataFrame({
        "trade_date": ["2024-01-02", "2024-01-02"],
        "concentration": [0.47, 0.48],
    })

    with pytest.raises(ValueError, match="duplicate"):
        build_gradual_crowding_budget(crowding)


@pytest.mark.parametrize(
    ("warning_threshold", "clear_threshold"),
    [(0.0, 0.50), (0.50, 0.50), (0.51, 0.50), (0.48, 1.0)],
)
def test_gradual_budget_rejects_invalid_threshold_ordering(
    warning_threshold: float, clear_threshold: float
) -> None:
    crowding = pd.DataFrame({
        "trade_date": ["2024-01-02"],
        "concentration": [0.47],
    })

    with pytest.raises(ValueError, match="warning_threshold"):
        build_gradual_crowding_budget(
            crowding,
            warning_threshold=warning_threshold,
            clear_threshold=clear_threshold,
        )


@pytest.mark.parametrize("concentration", [None, float("nan"), float("inf")])
def test_gradual_budget_rejects_missing_or_non_finite_concentration(
    concentration: float | None,
) -> None:
    crowding = pd.DataFrame({
        "trade_date": ["2024-01-02"],
        "concentration": [concentration],
    })

    with pytest.raises(ValueError, match="concentration"):
        build_gradual_crowding_budget(crowding)


def test_warning_interrupts_staged_recovery() -> None:
    crowding = pd.DataFrame({
        "trade_date": pd.date_range("2024-01-02", periods=8, freq="D"),
        "concentration": [0.48, 0.48, 0.44, 0.44, 0.48, 0.44, 0.44, 0.44],
    })

    result = build_gradual_crowding_budget(
        crowding,
        recovery_threshold=0.45,
        recovery_confirmation_days=2,
        recovery_step_days=2,
    )

    assert result["exposure_budget"].tolist() == [
        0.25, 0.0, 0.0, 0.5, 0.25, 0.25, 0.5, 0.5,
    ]


def test_market_state_budget_uses_only_current_and_prior_index_closes() -> None:
    index_bars = pd.DataFrame({
        "trade_date": pd.date_range("2024-01-01", periods=61, freq="D"),
        "close": [100.0] * 60 + [85.0],
    })

    budget = build_market_state_budget(index_bars)

    assert budget.iloc[-1]["exposure_budget"] == 0.30
    assert budget.iloc[19]["exposure_budget"] == 1.0
