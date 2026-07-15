from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pytest

from quant_lab.backtest.portfolio import CostModel, PortfolioBacktestResult
from quant_lab.research.optimized_v2_grid import (
    GridVariant,
    build_gradual_crowding_budget,
    run_grid,
)
from quant_lab.research.optimized_v3_design import (
    CrashOverlayVariant,
    ProfitProtectionVariant,
    RecoveryVariant,
    StockCountProfile,
    core_one_factor_variants,
)
from quant_lab.research import optimized_v3_runner as runner
from quant_lab.research.small_cap_experiment import (
    SmallCapExperimentConfig,
    SmallCapExperimentResult,
)


def _bars() -> pd.DataFrame:
    rows = []
    for date, open_price, close in (
        ("2024-01-02", 10.0, 10.0),
        ("2024-01-03", 10.0, 10.2),
        ("2024-01-04", 10.1, 10.1),
        ("2024-01-05", 10.0, 9.9),
    ):
        rows.append({
            "trade_date": date,
            "symbol": "002001",
            "open": open_price,
            "high": max(open_price, close) + 0.2,
            "low": min(open_price, close) - 0.2,
            "close": close,
            "paused": False,
            "is_st": False,
            "high_limit": 11.5,
            "low_limit": 8.5,
        })
    return pd.DataFrame(rows)


def _targets(symbol: str = "002001") -> pd.DataFrame:
    return pd.DataFrame({
        "signal_date": ["2024-01-02"],
        "symbol": [symbol],
        "target_weight": [1.0],
    })


def _inputs(**overrides) -> runner.ExperimentInputs:
    values = {
        "bars": _bars(),
        "frozen_targets": _targets(),
        "crowding_daily": pd.DataFrame({
            "trade_date": ["2024-01-05", "2024-01-02", "2024-01-04", "2024-01-03"],
            "concentration": [0.47, 0.47, 0.48, 0.47],
        }),
        "index_bars": pd.DataFrame({
            "trade_date": pd.date_range("2023-10-02", periods=70, freq="B"),
            "close": [100.0] * 70,
        }),
    }
    values.update(overrides)
    return runner.ExperimentInputs(**values)


def _config() -> SmallCapExperimentConfig:
    return SmallCapExperimentConfig(
        start_date="2024-01-02", end_date="2024-01-05", initial_cash=10_000.0
    )


def _experiment(
    *, cash: tuple[float, ...] = (10_000.0, 9_000.0),
    market_value: tuple[float, ...] = (0.0, 1_100.0),
    equity: tuple[float, ...] = (10_000.0, 10_100.0),
) -> SmallCapExperimentResult:
    curve = pd.DataFrame({
        "trade_date": pd.date_range("2024-01-02", periods=len(equity), freq="B"),
        "cash": cash,
        "market_value": market_value,
        "equity": equity,
    })
    backtest = PortfolioBacktestResult(
        curve,
        pd.DataFrame(columns=["return_pct"]),
        pd.DataFrame(),
        pd.DataFrame(),
    )
    return SmallCapExperimentResult(
        _config(), backtest, {"annualized_return": 0.20}, pd.DataFrame()
    )


def test_anchor_contract_and_exact_risk_settings(monkeypatch) -> None:
    captured = {}

    def fake_run(bars, targets, config, **kwargs):
        captured.update(kwargs)
        return _experiment()

    monkeypatch.setattr(runner, "run_small_cap_experiment", fake_run)
    candidate = runner.ExperimentCandidate.anchor()

    result = runner.run_candidate(_inputs(), candidate, _config())

    assert candidate.name == "fixed11_gradual"
    assert candidate.route == "anchor"
    assert candidate.core == core_one_factor_variants()[0]
    risk = captured["risk"]
    assert risk.enable_atr is False
    assert risk.fixed_stop_loss == 0.11
    assert risk.enable_cooldown is True
    assert risk.cooldown_days == 2
    assert risk.enable_crowding_daily is False
    assert risk.enable_market_stop is True
    assert risk.enable_divergence is True
    assert risk.repair_cost_protection is False
    assert captured["buy_new_only"] is True
    assert result.exposure_budget.columns.tolist() == ["trade_date", "exposure_budget"]
    assert result.exposure_budget["trade_date"].is_monotonic_increasing
    assert result.exposure_budget["trade_date"].is_unique
    assert set(result.diagnostics) == {
        "max_drawdown", "calmar", "max_underwater_calendar_days", "end_equity",
        "minimum_cash", "account_reconciliation_error", "mean_exposure_budget",
        "defensive_budget_days",
    }


def test_anchor_equity_matches_existing_grid_path() -> None:
    inputs = _inputs()
    budget = build_gradual_crowding_budget(
        inputs.crowding_daily,
        warning_threshold=0.48,
        clear_threshold=0.50,
        confirmation_days=2,
        reduced_budget=0.25,
    )
    v2 = run_grid(
        inputs.bars,
        inputs.frozen_targets,
        _config(),
        variants=[GridVariant(
            "fixed11_gradual", fixed_stop_loss=0.11, enable_atr=False,
            enable_cooldown=True, cooldown_days=2, crowding_danger=0.48,
            enable_crowding_daily=False,
        )],
        index_bars=inputs.index_bars,
        crowding_daily=inputs.crowding_daily,
        exposure_budget_daily=budget,
    )[0]

    v3 = runner.run_candidate(inputs, runner.ExperimentCandidate.anchor(), _config())

    assert v3.experiment.backtest.equity_curve["equity"].tolist() == pytest.approx(
        v2.experiment.backtest.equity_curve["equity"].tolist(), abs=1e-6
    )


def test_recovery_parameters_reach_budget_builder(monkeypatch) -> None:
    captured = {}

    def fake_budget(frame, **kwargs):
        captured.update(kwargs)
        return pd.DataFrame({"trade_date": ["2024-01-02"], "exposure_budget": [1.0]})

    monkeypatch.setattr(runner, "build_gradual_crowding_budget", fake_budget)
    monkeypatch.setattr(runner, "run_small_cap_experiment", lambda *a, **k: _experiment())
    recovery = RecoveryVariant("slow", 0.45, 2, 3)

    runner.run_candidate(
        _inputs(), replace(runner.ExperimentCandidate.anchor(), recovery=recovery), _config()
    )

    assert captured["recovery_threshold"] == 0.45
    assert captured["recovery_confirmation_days"] == 2
    assert captured["recovery_step_days"] == 3


def test_crash_and_crowding_budgets_use_rowwise_minimum(monkeypatch) -> None:
    dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    monkeypatch.setattr(
        runner,
        "build_gradual_crowding_budget",
        lambda *a, **k: pd.DataFrame({
            "trade_date": dates, "exposure_budget": [1.0, 0.25, 0.5]
        }),
    )
    monkeypatch.setattr(
        runner,
        "build_crash_exposure_budget",
        lambda *a, **k: pd.DataFrame({
            "trade_date": dates[:2], "exposure_budget": [0.6, 0.75]
        }),
    )
    monkeypatch.setattr(runner, "run_small_cap_experiment", lambda *a, **k: _experiment())
    crash = CrashOverlayVariant("crash", 0.10, 0.60, 3, 60)

    result = runner.run_candidate(
        _inputs(), replace(runner.ExperimentCandidate.anchor(), crash_overlay=crash), _config()
    )

    assert result.exposure_budget["exposure_budget"].tolist() == [0.6, 0.25, 0.5]


def test_named_stock_profile_selects_independent_target_set(monkeypatch) -> None:
    selected = _targets().assign(research_bucket="independent")
    captured = {}

    def fake_run(bars, targets, config, **kwargs):
        captured["targets"] = targets
        return _experiment()

    monkeypatch.setattr(runner, "run_small_cap_experiment", fake_run)
    profile = StockCountProfile("diversified", (4, 5, 6, 7))
    candidate = replace(runner.ExperimentCandidate.anchor(), stock_profile=profile)

    runner.run_candidate(_inputs(target_sets={"diversified": selected}), candidate, _config())

    pd.testing.assert_frame_equal(captured["targets"], selected)

    with pytest.raises(KeyError, match="diversified"):
        runner.run_candidate(_inputs(target_sets={}), candidate, _config())


def test_profit_protection_reaches_risk_config(monkeypatch) -> None:
    captured = {}

    def fake_run(*args, **kwargs):
        captured["risk"] = kwargs["risk"]
        return _experiment()

    monkeypatch.setattr(runner, "run_small_cap_experiment", fake_run)
    protection = ProfitProtectionVariant("repair", 0.30, 0.05)

    runner.run_candidate(
        _inputs(),
        replace(runner.ExperimentCandidate.anchor(), profit_protection=protection),
        _config(),
    )

    assert captured["risk"].repair_cost_protection is True
    assert captured["risk"].profit_activation == 0.30
    assert captured["risk"].profit_floor == 0.05


def test_candidate_runner_threads_explicit_cost_model(monkeypatch) -> None:
    captured = {}

    def fake_run(*args, **kwargs):
        captured["costs"] = kwargs.get("costs")
        return _experiment()

    monkeypatch.setattr(runner, "run_small_cap_experiment", fake_run)
    costs = CostModel(commission_rate=0.001, minimum_commission=7.0,
                      sell_stamp_tax=0.002, fixed_slippage=0.003)

    runner.run_candidate(_inputs(), runner.ExperimentCandidate.anchor(), _config(), costs=costs)

    assert captured["costs"] is costs


def test_account_reconciliation_and_hard_failures(monkeypatch) -> None:
    good = _experiment()
    assert runner.reconcile_account(good.backtest) == pytest.approx(0.0)
    assert runner.reconcile_account(PortfolioBacktestResult(
        pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    )) == 0.0

    bad_account = _experiment(equity=(10_000.0, 10_100.000001))
    monkeypatch.setattr(runner, "run_small_cap_experiment", lambda *a, **k: bad_account)
    with pytest.raises(RuntimeError, match="reconciliation"):
        runner.run_candidate(_inputs(), runner.ExperimentCandidate.anchor(), _config())

    negative_cash = _experiment(cash=(10_000.0, -0.000000002), market_value=(0.0, 10_100.000000002))
    monkeypatch.setattr(runner, "run_small_cap_experiment", lambda *a, **k: negative_cash)
    with pytest.raises(RuntimeError, match="cash"):
        runner.run_candidate(_inputs(), runner.ExperimentCandidate.anchor(), _config())


def test_neighbor_stability_examples_and_validation() -> None:
    assert not runner.neighbor_stability(
        {"left": 1.00, "winner": 1.30, "right": 1.02},
        "winner", ["left", "right"], tolerance=0.10,
    )
    assert runner.neighbor_stability(
        {"left": 1.20, "winner": 1.30, "right": 1.18},
        "winner", ["left", "right"], tolerance=0.10,
    )
    with pytest.raises(KeyError, match="winner"):
        runner.neighbor_stability({"left": 1.0, "right": 1.0}, "winner", ["left", "right"])
    with pytest.raises(ValueError, match="two distinct"):
        runner.neighbor_stability({"winner": 1.0, "left": 1.0}, "winner", ["left", "left"])
    with pytest.raises(ValueError, match="tolerance"):
        runner.neighbor_stability({"winner": 1.0, "left": 1.0, "right": 1.0}, "winner", ["left", "right"], 1.0)
    with pytest.raises(ValueError, match="finite"):
        runner.neighbor_stability({"winner": 1.0, "left": float("nan"), "right": 1.0}, "winner", ["left", "right"])
    with pytest.raises(KeyError, match="missing"):
        runner.neighbor_stability({"winner": 1.0, "left": 1.0, "right": 1.0}, "winner", ["left", "missing"])
