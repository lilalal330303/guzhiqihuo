from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from quant_lab.backtest.portfolio import CostModel
from quant_lab.research.optimized_v3_runner import ExperimentCandidate
from tools import run_fixed11_gradual_next_stage as cli
from tools.run_fixed11_gradual_next_stage import (
    REQUIRED_CANDIDATE_ARTIFACTS,
    build_candidate_catalog,
    build_route_candidates,
    build_run_manifest,
    audit_crash_mechanisms,
    candidate_run_hash,
    compare_equity_curves,
    completion_gate,
    combined_policy_max_drawdown,
    cost_stress_models,
    filter_route_candidates_for_walkforward,
    database_snapshot,
    global_experiment_fingerprint,
    rank_core_variants,
    rebuild_annual_returns,
    resume_manifest_for_snapshot,
    scale_cost_model,
    select_diagnostic_leaders,
    evaluate_stress_evidence,
    should_resume,
    write_csv,
    write_json,
)


def test_dry_run_manifest_lists_approved_counts(tmp_path: Path) -> None:
    manifest = build_run_manifest(output=tmp_path, execute=False)

    assert manifest["core_one_factor_count"] == 20
    assert manifest["core_orthogonal_max_count"] == 18
    assert manifest["recovery_count"] == 6
    assert manifest["stock_profile_count"] == 3
    assert manifest["crash_overlay_count"] == 6
    assert manifest["profit_protection_count"] == 4
    assert manifest["stress_evidence_schema"] == cli.STRESS_EVIDENCE_SCHEMA


def test_catalog_names_and_parameter_hashes_are_unique() -> None:
    catalog = build_candidate_catalog()

    assert catalog["name"].is_unique
    assert catalog["parameter_hash"].is_unique
    assert catalog.loc[catalog["name"].eq("fixed11_gradual"), "route"].item() == "anchor"
    assert len(catalog.loc[catalog["family"].eq("core")]) <= 38


def test_candidate_hash_is_canonical_and_sensitive_to_every_contract_field() -> None:
    candidate = ExperimentCandidate.anchor()
    costs = CostModel()
    kwargs = dict(
        candidate=candidate,
        source_target_hash="target-a",
        start="2020-01-01",
        end="2026-07-06",
        initial_cash=1_000_000.0,
        costs=costs,
        input_data_fingerprint="db-a",
    )
    first = candidate_run_hash(**kwargs)
    second = candidate_run_hash(**dict(reversed(list(kwargs.items()))))

    assert first == second
    assert len(first) == 64
    assert first != candidate_run_hash(**{**kwargs, "source_target_hash": "target-b"})
    assert first != candidate_run_hash(**{**kwargs, "input_data_fingerprint": "db-b"})
    assert first != candidate_run_hash(**{**kwargs, "costs": scale_cost_model(costs, 2.0)})
    assert first != candidate_run_hash(**{**kwargs, "evidence_schema": "diagnostic-v1"})


def test_diagnostic_leaders_are_full_sample_only_and_never_gate_qualified() -> None:
    scores = pd.DataFrame([
        {"candidate": "b1", "route": "balanced", "calmar": 2.0, "sharpe": 1.0,
         "max_underwater_calendar_days": 50, "total_return": 1.0,
         "max_drawdown": -0.20},
        {"candidate": "b2", "route": "balanced", "calmar": 2.0, "sharpe": 1.2,
         "max_underwater_calendar_days": 70, "total_return": 0.9,
         "max_drawdown": -0.21},
        {"candidate": "r1", "route": "return", "calmar": 2.0, "sharpe": 1.0,
         "max_underwater_calendar_days": 50, "total_return": 1.4,
         "max_drawdown": -0.25},
        {"candidate": "r2", "route": "return", "calmar": 3.0, "sharpe": 1.0,
         "max_underwater_calendar_days": 50, "total_return": 1.3,
         "max_drawdown": -0.20},
        {"candidate": "failed_crash", "route": "defensive", "calmar": 9.0,
         "sharpe": 2.0, "max_underwater_calendar_days": 10,
         "total_return": 2.0, "max_drawdown": -0.05,
         "crash_mechanism_passed": False},
        {"candidate": "d1", "route": "defensive", "calmar": 1.5,
         "sharpe": 1.0, "max_underwater_calendar_days": 80,
         "total_return": 0.8, "max_drawdown": -0.15,
         "crash_mechanism_passed": True},
        {"candidate": "d2", "route": "defensive", "calmar": 2.0,
         "sharpe": 1.0, "max_underwater_calendar_days": 70,
         "total_return": 0.9, "max_drawdown": -0.20},
    ])

    leaders = select_diagnostic_leaders(scores)

    assert {route: item["candidate"] for route, item in leaders.items()} == {
        "balanced": "b2", "return": "r1", "defensive": "d1",
    }
    assert all(item["diagnostic_only"] is True for item in leaders.values())
    assert all(item["qualified_for_gate"] is False for item in leaders.values())
    assert all(item["selection_basis"] == "full_sample_in_sample"
               for item in leaders.values())


@pytest.mark.parametrize("missing_route", ["return", "defensive"])
def test_diagnostic_leaders_allow_an_absent_route_without_inventing_candidate(
    missing_route: str,
) -> None:
    scores = pd.DataFrame([
        {"candidate": f"{route}_only", "route": route, "calmar": 1.0,
         "sharpe": 1.0, "max_underwater_calendar_days": 10,
         "total_return": 0.5, "max_drawdown": -0.2,
         "crash_mechanism_passed": True}
        for route in cli.ROUTES if route != missing_route
    ])

    leaders = select_diagnostic_leaders(scores)

    assert set(leaders) == set(cli.ROUTES)
    assert leaders[missing_route] is None
    assert all(leaders[route]["candidate"] == f"{route}_only"
               for route in cli.ROUTES if route != missing_route)


def test_all_absent_diagnostic_routes_are_anchor_only_and_audit_complete() -> None:
    empty = pd.DataFrame(columns=[
        "candidate", "route", "calmar", "sharpe", "max_underwater_calendar_days",
        "total_return", "max_drawdown", "crash_mechanism_passed",
    ])
    assert select_diagnostic_leaders(empty) == {route: None for route in cli.ROUTES}

    rows = []
    for route in cli.ROUTES:
        rows.append({
            "evidence_type": "diagnostic_unavailable", "route": route,
            "reason": "no_route_candidate", "diagnostic_only": True,
            "qualified_for_gate": False, "diagnostic_available": False,
            "diagnostic_reason": "no_route_candidate", "candidate": "",
            "selection_basis": "diagnostic_unavailable",
        })
        for cost_label in cli.cost_stress_models(CostModel()):
            rows.append({
                "evidence_type": "cost", "route": route, "series": "anchor",
                "candidate": "fixed11_gradual", "cost_label": cost_label,
                "diagnostic_only": True, "qualified_for_gate": False,
                "diagnostic_available": False,
                "diagnostic_reason": "no_route_candidate",
                "selection_basis": "diagnostic_unavailable",
            })
        for window in ("2024_q1", "2026_ytd"):
            rows.append({
                "evidence_type": "stress_window", "route": route, "series": "anchor",
                "candidate": "fixed11_gradual", "window": window,
                "diagnostic_only": True, "qualified_for_gate": False,
                "diagnostic_available": False,
                "diagnostic_reason": "no_route_candidate",
                "selection_basis": "diagnostic_unavailable",
            })
    gates = [{"route": route, "passed": False,
              "reasons": ("missing_policy_fold",)} for route in cli.ROUTES]

    assert evaluate_stress_evidence(
        pd.DataFrame(rows), {}, gates, cost_model_count=7,
    ) == (True, True)
    tampered = pd.DataFrame(rows)
    tampered.loc[tampered["evidence_type"].eq("diagnostic_unavailable"),
                 "diagnostic_only"] = False
    assert evaluate_stress_evidence(
        tampered, {}, gates, cost_model_count=7,
    ) == (False, False)


def test_incomplete_policy_diagnostic_evidence_requires_exact_counts_and_missing_gate() -> None:
    rows = []
    for route in cli.ROUTES:
        for cost_label in cli.cost_stress_models(CostModel()):
            for series in ("candidate", "anchor"):
                rows.append({
                    "evidence_type": "cost", "route": route,
                    "series": series, "candidate": f"{route}_leader",
                    "cost_label": cost_label, "diagnostic_only": True,
                    "qualified_for_gate": False,
                    "diagnostic_available": True,
                    "selection_basis": "full_sample_in_sample",
                })
        for window in ("2024_q1", "2026_ytd"):
            for series in ("candidate", "anchor"):
                rows.append({
                    "evidence_type": "stress_window", "route": route,
                    "series": series, "candidate": f"{route}_leader",
                    "window": window, "diagnostic_only": True,
                    "qualified_for_gate": False,
                    "diagnostic_available": True,
                    "selection_basis": "full_sample_in_sample",
                })
    gates = [{"route": route, "passed": False,
              "reasons": ("missing_policy_fold",)} for route in cli.ROUTES]

    cost_ok, stress_ok = evaluate_stress_evidence(
        pd.DataFrame(rows), {route: 4 for route in cli.ROUTES}, gates,
        cost_model_count=7,
    )

    assert cost_ok and stress_ok
    assert len([row for row in rows if row["evidence_type"] == "cost"]) == 42
    assert len([row for row in rows if row["evidence_type"] == "stress_window"]) == 12
    assert all(row["passed"] is False for row in gates)
    assert all(row["reasons"] == ("missing_policy_fold",) for row in gates)
    broken = pd.DataFrame(rows[:-1])
    assert evaluate_stress_evidence(
        broken, {route: 4 for route in cli.ROUTES}, gates, cost_model_count=7,
    ) == (True, False)


def test_resume_requires_exact_hash_audit_and_complete_artifacts(tmp_path: Path) -> None:
    run_dir = tmp_path / "candidate"
    run_dir.mkdir()
    write_csv(pd.DataFrame([{"trade_date": "2024-01-02", "equity": 100.0,
                             "cash": 100.0, "market_value": 0.0}]), run_dir / "equity.csv")
    write_csv(pd.DataFrame([{"trade_date": "2024-01-02", "exposure_budget": 1.0}]),
              run_dir / "exposure_budget.csv")
    write_csv(pd.DataFrame(columns=cli.TRADES_COLUMNS), run_dir / "trades.csv")
    write_csv(pd.DataFrame(columns=cli.REJECTIONS_COLUMNS), run_dir / "rejections.csv")
    write_csv(pd.DataFrame(columns=cli.POSITIONS_COLUMNS), run_dir / "positions.csv")
    write_json(run_dir / "parameters.json", {"name": "candidate"})
    (run_dir / "target_hash.txt").write_text("target", encoding="ascii")
    (run_dir / "run_hash.txt").write_text("abc", encoding="ascii")
    write_json(run_dir / "audit.json", {
        "candidate_hash": "abc",
        "passed": True,
        "account_reconciliation_error": 0.0,
        "minimum_cash": 0.0,
        "score": {"target_hash": "target"},
    })

    assert should_resume(run_dir, "abc")
    assert should_resume(run_dir, "abc", target_hash="target")
    assert not should_resume(run_dir, "abc", target_hash="other")
    assert not should_resume(run_dir, "changed")
    (run_dir / "trades.csv").unlink()
    assert not should_resume(run_dir, "abc")


def test_resume_rejects_failed_or_unreconciled_audit(tmp_path: Path) -> None:
    record = {
        "candidate_hash": "abc",
        "passed": False,
        "account_reconciliation_error": 0.0,
        "minimum_cash": 1.0,
        "artifacts_complete": True,
    }
    assert not should_resume(record, "abc")
    assert not should_resume({**record, "passed": True, "account_reconciliation_error": 1e-6}, "abc")
    assert not should_resume({**record, "passed": True, "minimum_cash": -1e-9}, "abc")


def test_cost_scaling_is_explicit_for_all_four_fields() -> None:
    baseline = CostModel()
    doubled = scale_cost_model(baseline, 2.0)

    assert doubled.commission_rate == baseline.commission_rate * 2
    assert doubled.minimum_commission == baseline.minimum_commission * 2
    assert doubled.sell_stamp_tax == baseline.sell_stamp_tax * 2
    assert doubled.fixed_slippage == baseline.fixed_slippage * 2


def test_writers_preserve_stable_utf8_columns_and_chinese(tmp_path: Path) -> None:
    csv_path = tmp_path / "rows.csv"
    json_path = tmp_path / "record.json"
    write_csv(pd.DataFrame([{"b": 2, "a": "均衡型"}]), csv_path, columns=["a", "b"])
    write_json(json_path, {"route": "防守型"})

    raw_csv = csv_path.read_bytes()
    assert raw_csv.startswith(b"\xef\xbb\xbf")
    assert pd.read_csv(csv_path).columns.tolist() == ["a", "b"]
    raw_json = json_path.read_text(encoding="utf-8-sig")
    assert "防守型" in raw_json
    assert "\\u9632" not in raw_json
    assert json.loads(raw_json)["route"] == "防守型"


def test_route_ranking_rejects_an_isolated_full_sample_spike() -> None:
    catalog = build_candidate_catalog()
    core = catalog.loc[catalog["family"].eq("core"), "name"].tolist()
    rows = []
    for name in core:
        rows.append({
            "candidate": name,
            "total_return": 2.0 if name == "one_factor_fixed_stop_loss_0p095" else 1.0,
            "annualized_return": 0.20,
            "max_drawdown": -0.20,
            "account_reconciliation_error": 0.0,
            "minimum_cash": 1.0,
        })

    selected_return, _, rejected = rank_core_variants(pd.DataFrame(rows))

    assert "one_factor_fixed_stop_loss_0p095" not in {item.name for item in selected_return}
    reason = rejected.loc[
        rejected["candidate"].eq("one_factor_fixed_stop_loss_0p095")
        & rejected["rejected_for_route"].eq("return"), "reason"
    ].item()
    assert "neighbor_stability" in reason


def test_database_snapshot_hash_detects_same_size_content_change(tmp_path: Path) -> None:
    db = tmp_path / "market.duckdb"
    db.write_bytes(b"abcd")
    before = database_snapshot(db)
    db.write_bytes(b"wxyz")
    after = database_snapshot(db)

    assert before["size"] == after["size"] == 4
    assert before["sha256"] != after["sha256"]


def test_current_reference_uses_independent_v2_grid_path(monkeypatch) -> None:
    calls = []
    expected = pd.DataFrame({"trade_date": ["2024-01-02"], "equity": [100.0]})

    def fake_grid(*args, **kwargs):
        calls.append((args, kwargs))
        return [SimpleNamespace(experiment=SimpleNamespace(
            backtest=SimpleNamespace(equity_curve=expected)
        ))]

    monkeypatch.setattr(cli, "run_grid", fake_grid)
    monkeypatch.setattr(cli, "build_gradual_crowding_budget", lambda frame: frame)
    inputs = SimpleNamespace(
        bars=pd.DataFrame(), frozen_targets=pd.DataFrame(), market_daily=pd.DataFrame(),
        index_bars=pd.DataFrame(), crowding_daily=pd.DataFrame(),
    )
    config = SimpleNamespace()

    actual = cli.run_current_db_v2_anchor_reference(inputs, config)

    assert calls
    assert calls[0][1]["variants"][0].name == "fixed11_gradual"
    pd.testing.assert_frame_equal(actual, expected)


def test_equity_comparison_requires_exact_date_coverage() -> None:
    current = pd.DataFrame({"trade_date": ["2024-01-02"], "equity": [100.0]})
    same = current.copy()
    missing = pd.DataFrame({"trade_date": ["2024-01-03"], "equity": [100.0]})

    assert compare_equity_curves(current, same) == 0.0
    assert compare_equity_curves(current, missing) == float("inf")


def test_explicit_empty_stable_core_rankings_do_not_backfill() -> None:
    candidates = build_route_candidates([], [])

    assert not [item for item in candidates if item.stock_profile is not None]
    assert not [item for item in candidates if item.profit_protection is not None]
    assert len([item for item in candidates if item.recovery is not None]) == 6
    assert len([item for item in candidates if item.crash_overlay is not None]) == 6
    assert len(candidates) == 12


def test_route_core_rankings_enforce_audit_drawdown_and_anchor_improvement() -> None:
    catalog = build_candidate_catalog()
    core = catalog.loc[catalog["family"].eq("core"), "name"].tolist()
    rows = [{
        "candidate": name, "total_return": (1.0 if name == "fixed11_gradual" else 1.1),
        "annualized_return": 0.20,
        "max_drawdown": (-0.25 if name == "fixed11_gradual" else -0.20),
        "account_reconciliation_error": 0.0, "minimum_cash": 1.0,
    } for name in core]
    bad_drawdown = next(row for row in rows if row["candidate"] == "one_factor_fixed_stop_loss_0p095")
    bad_drawdown.update(total_return=9.0, max_drawdown=-0.40)
    bad_audit = next(row for row in rows if row["candidate"] == "one_factor_fixed_stop_loss_0p105")
    bad_audit.update(total_return=8.0, account_reconciliation_error=1e-6)
    worse_return = next(row for row in rows if row["candidate"] == "one_factor_fixed_stop_loss_0p115")
    worse_return.update(total_return=0.90)

    selected_return, selected_defensive, rejected = rank_core_variants(pd.DataFrame(rows))

    return_names = {item.name for item in selected_return}
    defensive_names = {item.name for item in selected_defensive}
    assert bad_drawdown["candidate"] not in return_names | defensive_names
    assert bad_audit["candidate"] not in return_names | defensive_names
    assert worse_return["candidate"] not in return_names
    assert all(next(row for row in rows if row["candidate"] == name)["total_return"] > 1.0
               for name in return_names)
    assert all(next(row for row in rows if row["candidate"] == name)["max_drawdown"] > -0.25
               for name in defensive_names)
    assert {"account_audit", "drawdown_floor", "not_better_than_anchor"} <= set(
        ";".join(rejected["reason"].astype(str)).split(";")
    )


def test_neighbor_plateau_may_include_audited_peers_slightly_below_anchor() -> None:
    catalog = build_candidate_catalog()
    core = catalog.loc[catalog["family"].eq("core"), "name"].tolist()
    rows = [{
        "candidate": name, "total_return": 0.50, "annualized_return": 0.10,
        "max_drawdown": -0.20, "account_reconciliation_error": 0.0, "minimum_cash": 1.0,
    } for name in core]
    by_name = {row["candidate"]: row for row in rows}
    by_name["fixed11_gradual"].update(total_return=1.0, annualized_return=0.20,
                                      max_drawdown=-0.25)
    by_name["one_factor_fixed_stop_loss_0p105"].update(total_return=1.05)
    by_name["one_factor_fixed_stop_loss_0p095"].update(total_return=0.99)
    by_name["one_factor_fixed_stop_loss_0p115"].update(total_return=0.99)

    selected_return, _, _ = rank_core_variants(pd.DataFrame(rows))

    assert "one_factor_fixed_stop_loss_0p105" in {item.name for item in selected_return}


def test_resume_rejects_zero_byte_and_unparseable_artifacts(tmp_path: Path) -> None:
    run_dir = tmp_path / "candidate"
    run_dir.mkdir()
    for name in REQUIRED_CANDIDATE_ARTIFACTS:
        (run_dir / name).write_text("x", encoding="utf-8")
    write_json(run_dir / "audit.json", {
        "candidate_hash": "abc", "passed": True,
        "account_reconciliation_error": 0.0, "minimum_cash": 0.0,
    })
    (run_dir / "equity.csv").write_bytes(b"")
    assert not should_resume(run_dir, "abc")
    (run_dir / "equity.csv").write_text("not,a,valid,row\n\"", encoding="utf-8")
    assert not should_resume(run_dir, "abc")


def test_resume_rejects_header_only_equity_and_mismatched_run_hash(tmp_path: Path) -> None:
    run_dir = tmp_path / "candidate"
    run_dir.mkdir()
    for name in ("trades.csv", "rejections.csv", "positions.csv"):
        columns = {
            "trades.csv": cli.TRADES_COLUMNS,
            "rejections.csv": cli.REJECTIONS_COLUMNS,
            "positions.csv": cli.POSITIONS_COLUMNS,
        }[name]
        write_csv(pd.DataFrame(columns=columns), run_dir / name)
    write_csv(pd.DataFrame(columns=["trade_date", "equity"]), run_dir / "equity.csv")
    write_csv(pd.DataFrame([{"trade_date": "2024-01-02", "exposure_budget": 1.0}]),
              run_dir / "exposure_budget.csv")
    write_json(run_dir / "parameters.json", {"name": "candidate"})
    (run_dir / "target_hash.txt").write_text("target", encoding="ascii")
    (run_dir / "run_hash.txt").write_text("wrong", encoding="ascii")
    write_json(run_dir / "audit.json", {
        "candidate_hash": "abc", "passed": True, "account_reconciliation_error": 0.0,
        "minimum_cash": 0.0, "score": {"target_hash": "target"},
    })

    assert not should_resume(run_dir, "abc", target_hash="target")
    write_csv(pd.DataFrame([{"value": 1}]), run_dir / "equity.csv")
    (run_dir / "run_hash.txt").write_text("abc", encoding="ascii")
    assert not should_resume(run_dir, "abc", target_hash="target")
    write_csv(pd.DataFrame([{"trade_date": "2024-01-02", "equity": 100.0,
                             "cash": 100.0, "market_value": 0.0}]),
              run_dir / "equity.csv")
    (run_dir / "run_hash.txt").write_text("wrong", encoding="ascii")
    assert not should_resume(run_dir, "abc", target_hash="target")
    (run_dir / "run_hash.txt").write_text("abc", encoding="ascii")
    assert should_resume(run_dir, "abc", target_hash="target")


def test_cost_stress_matrix_separates_fees_slippage_and_combined() -> None:
    baseline = CostModel()
    models = cost_stress_models(baseline)

    assert list(models) == [
        "combined_1x", "combined_1p5x", "combined_2x",
        "fee_only_1p5x", "fee_only_2x", "slippage_only_1p5x", "slippage_only_2x",
    ]
    assert models["fee_only_2x"].fixed_slippage == baseline.fixed_slippage
    assert models["fee_only_2x"].commission_rate == baseline.commission_rate * 2
    assert models["slippage_only_2x"].fixed_slippage == baseline.fixed_slippage * 2
    assert models["slippage_only_2x"].commission_rate == baseline.commission_rate


def test_completion_gate_requires_all_stages_nonempty_artifacts_and_evidence(tmp_path: Path) -> None:
    manifest = {
        "stage_status": {name: "complete" for name in ("core", "routes", "walkforward", "stress")},
        "database_snapshot_unchanged": True,
        "anchor_max_abs_equity_diff": 0.0,
        "max_account_reconciliation_error": 0.0,
        "minimum_cash": 0.0,
        "test_selection_leakage_count": 0,
        "full_sample_candidate_count": 60,
        "normal_test_call_count": 40,
        "cost_evidence_complete": True,
        "stress_evidence_complete": True,
        "stress_evidence_schema": cli.STRESS_EVIDENCE_SCHEMA,
        "qualified_route_count": 0,
        "route_decisions": {
            route: {
                "passed": False, "qualified_for_gate": False,
                "diagnostic_only": True, "diagnostic_available": True,
                "candidate": f"{route}_leader",
                "selection_basis": "full_sample_in_sample",
            }
            for route in cli.ROUTES
        },
        "crash_mechanism_audit": {
            f"crash_{index}": {"crash_trigger_ratio": 0.10, "passed": True}
            for index in range(6)
        },
    }
    for name in cli.ROOT_ARTIFACTS:
        path = tmp_path / name
        if name == "run_manifest.json":
            write_json(path, manifest)
        elif name.endswith(".json"):
            write_json(path, {"value": 1})
        elif name == "route_scores.csv":
            write_csv(pd.DataFrame([{
                "candidate": f"crash_{index}", "crash_trigger_ratio": 0.10,
                "crash_mechanism_passed": True,
            } for index in range(6)]), path)
        else:
            write_csv(pd.DataFrame([{"value": 1}]), path)

    assert completion_gate(manifest, tmp_path)
    assert not completion_gate({**manifest, "crash_mechanism_audit": {}}, tmp_path)
    assert not completion_gate({**manifest, "cost_evidence_complete": False}, tmp_path)
    assert not completion_gate({**manifest, "stress_evidence_schema": "old"}, tmp_path)
    absent = json.loads(json.dumps(manifest))
    absent["route_decisions"]["return"] = {
        "passed": False, "qualified_for_gate": False,
        "diagnostic_only": True, "diagnostic_available": False,
        "candidate": None, "diagnostic_reason": "no_route_candidate",
        "selection_basis": "diagnostic_unavailable",
    }
    assert completion_gate(absent, tmp_path)
    absent["route_decisions"]["return"]["candidate"] = "invented"
    assert not completion_gate(absent, tmp_path)
    write_csv(pd.DataFrame(), tmp_path / "stress_results.csv")
    assert not completion_gate(manifest, tmp_path)


def test_walkforward_runner_routes_period_calls_through_persistent_resume_path(
    monkeypatch, tmp_path: Path
) -> None:
    captured = {}

    def fake_run(candidate, inputs, target_hashes, config, output, costs, resume,
                 input_data_fingerprint, run_context=None, evidence_schema=""):
        captured.update({"output": output, "resume": resume,
                         "fingerprint": input_data_fingerprint, "context": run_context,
                         "evidence_schema": evidence_schema})
        return {
            "total_return": 0.1, "annualized_return": 0.2, "max_drawdown": -0.1,
            "sharpe": 1.0, "calmar": 2.0, "max_underwater_calendar_days": 10,
            "candidate_hash": "period-hash",
        }

    monkeypatch.setattr(cli, "_run_full_candidate", fake_run)
    inputs = cli.ExperimentInputs(
        bars=pd.DataFrame({"trade_date": ["2024-01-02"], "symbol": ["000001"]}),
        frozen_targets=pd.DataFrame({"signal_date": ["2024-01-02"],
                                     "symbol": ["000001"], "target_weight": [1.0]}),
        crowding_daily=pd.DataFrame(), index_bars=pd.DataFrame(),
    )
    runner = cli._walkforward_runner(
        inputs, {"fixed11_gradual": "target"}, 1_000_000.0, CostModel(),
        output=tmp_path, resume=True, input_data_fingerprint="db-hash",
    )

    score = runner(candidate=ExperimentCandidate.anchor(), start=pd.Timestamp("2024-01-02"),
                   end=pd.Timestamp("2024-01-02"), phase="test", fold="fold_2024")

    assert score["observation_date"] == pd.Timestamp("2024-01-02")
    assert captured == {
        "output": tmp_path, "resume": True, "fingerprint": "db-hash",
        "context": {"phase": "test", "fold": "fold_2024"}, "evidence_schema": "",
    }


def test_annual_returns_rebuild_includes_full_and_period_runs(tmp_path: Path) -> None:
    for run_hash, phase, dates, equities in (
        ("a", "full_sample", ["2023-01-02", "2023-12-29"], [100.0, 110.0]),
        ("b", "test", ["2024-01-02", "2024-12-31"], [100.0, 120.0]),
    ):
        run_dir = tmp_path / "candidates" / "candidate" / run_hash
        write_csv(pd.DataFrame({"trade_date": dates, "equity": equities}), run_dir / "equity.csv")
        write_json(run_dir / "audit.json", {
            "candidate_hash": run_hash, "score": {"candidate": "candidate", "route": "return"},
            "run_context": {"phase": phase, "fold": "fold_2024" if phase == "test" else "",
                            "input_data_fingerprint": "current" if run_hash == "b" else "old"},
        })

    annual = rebuild_annual_returns(tmp_path)

    assert set(annual["phase"]) == {"full_sample", "test"}
    assert annual.set_index("year")["return"].to_dict() == {2023: 0.1, 2024: 0.2}
    current = rebuild_annual_returns(tmp_path, input_data_fingerprint="current")
    assert current["year"].tolist() == [2024]


def test_cross_snapshot_resume_resets_all_stage_evidence() -> None:
    base = cli.build_run_manifest("out", execute=True)
    prior = {
        **base,
        "database_snapshot_before": {"sha256": "same-db"},
        "experiment_fingerprint": "old-experiment",
        "stage_status": {stage: "complete" for stage in base["stage_status"]},
        "cost_evidence_complete": True,
        "stress_evidence_complete": True,
        "full_sample_candidate_count": 60,
        "normal_test_call_count": 40,
        "passed": True,
    }

    resumed, reset = resume_manifest_for_snapshot(base, prior, "new-experiment")

    assert reset
    assert set(resumed["stage_status"].values()) == {"pending"}
    assert resumed.get("cost_evidence_complete") is not True
    assert resumed.get("stress_evidence_complete") is not True
    assert "full_sample_candidate_count" not in resumed
    assert "normal_test_call_count" not in resumed
    assert resumed["passed"] is False


def test_global_experiment_fingerprint_covers_all_root_inputs() -> None:
    kwargs = dict(
        database_sha256="db", start="2020-01-01", end="2026-07-06",
        initial_cash=1_000_000.0, target_hashes={"anchor": "a", "profile": "b"},
        baseline_costs=CostModel(),
    )
    original = global_experiment_fingerprint(**kwargs)

    assert original != global_experiment_fingerprint(**{**kwargs, "database_sha256": "changed"})
    assert original != global_experiment_fingerprint(**{**kwargs, "start": "2021-01-01"})
    assert original != global_experiment_fingerprint(**{**kwargs, "end": "2025-12-31"})
    assert original != global_experiment_fingerprint(**{**kwargs, "initial_cash": 2_000_000.0})
    assert original != global_experiment_fingerprint(**{**kwargs, "target_hashes": {"anchor": "x"}})
    assert original != global_experiment_fingerprint(**{
        **kwargs, "baseline_costs": CostModel(minimum_commission=6.0),
    })
    assert original != global_experiment_fingerprint(**{**kwargs, "schema_version": "v-next"})


def test_crash_trigger_ratio_gate_includes_five_and_twenty_percent_boundaries(
    monkeypatch,
) -> None:
    candidates = [item for item in build_route_candidates() if item.crash_overlay is not None][:2]
    ratios = iter((0.05, 0.20))

    def fake_budget(*args, **kwargs):
        ratio = next(ratios)
        total = 20
        defensive_days = round(ratio * total)
        return pd.DataFrame({
            "trade_date": pd.date_range("2024-01-02", periods=total, freq="B"),
            "defensive": [True] * defensive_days + [False] * (total - defensive_days),
            "exposure_budget": [1.0] * total,
        })

    monkeypatch.setattr(cli, "build_crash_exposure_budget", fake_budget)
    audit = audit_crash_mechanisms(candidates, pd.DataFrame({"trade_date": [], "close": []}))

    assert audit["crash_trigger_ratio"].tolist() == [0.05, 0.20]
    assert audit["crash_mechanism_passed"].tolist() == [True, True]


def test_walkforward_filter_excludes_only_failed_crash_mechanisms() -> None:
    candidates = build_route_candidates()
    crash = [item for item in candidates if item.crash_overlay is not None]
    audit = pd.DataFrame({
        "candidate": [item.name for item in crash],
        "crash_trigger_ratio": [0.21, 0.19, 0.10, 0.10, 0.10, 0.10],
        "crash_mechanism_passed": [False, True, True, True, True, True],
    })

    filtered = filter_route_candidates_for_walkforward(candidates, audit)

    assert crash[0].name not in {item.name for item in filtered}
    assert crash[1].name in {item.name for item in filtered}
    assert all(item in filtered for item in candidates if item.crash_overlay is None)


def test_crash_trigger_ratio_excludes_indicator_warmup_dates(monkeypatch) -> None:
    candidate = next(item for item in build_route_candidates() if item.crash_overlay is not None)
    dates = pd.date_range("2019-12-16", periods=30, freq="B")

    monkeypatch.setattr(cli, "build_crash_exposure_budget", lambda *args, **kwargs: pd.DataFrame({
        "trade_date": dates,
        "defensive": [True] * 10 + [True] + [False] * 19,
        "exposure_budget": [1.0] * 30,
    }))
    index_dates = pd.date_range(end="2019-12-27", periods=60, freq="B")
    audit = audit_crash_mechanisms([candidate], pd.DataFrame({
        "trade_date": index_dates, "close": [100.0] * len(index_dates),
    }), start="2019-12-30", end=str(dates[-1].date()))

    # The first 10 warm-up rows are outside the 20-row evidence interval.
    assert audit.loc[0, "crash_trigger_ratio"] == 0.05


def test_crash_audit_rejects_fewer_than_sixty_prestart_trading_days() -> None:
    candidate = next(item for item in build_route_candidates() if item.crash_overlay is not None)
    dates = pd.date_range(end="2019-12-31", periods=59, freq="B")

    with pytest.raises(ValueError, match="60 pre-start"):
        audit_crash_mechanisms(
            [candidate], pd.DataFrame({"trade_date": dates, "close": [100.0] * 59}),
            start="2020-01-01", end="2020-12-31",
        )


def test_combined_policy_drawdown_uses_intraperiod_equity_not_only_fold_endpoints(
    tmp_path: Path,
) -> None:
    rows = []
    for fold, run_hash, equities in (
        ("fold_2022", "hash-a", [100.0, 70.0, 110.0]),
        ("fold_2023", "hash-b", [100.0, 80.0, 120.0]),
    ):
        run_dir = tmp_path / "candidates" / "candidate" / run_hash[:16]
        write_csv(pd.DataFrame({
            "trade_date": pd.date_range("2022-01-03", periods=3, freq="B"),
            "equity": equities,
        }), run_dir / "equity.csv")
        rows.append({"fold": fold, "candidate": "candidate", "candidate_hash": run_hash,
                     "total_return": equities[-1] / 100.0 - 1.0})

    drawdown = combined_policy_max_drawdown(pd.DataFrame(rows), tmp_path, initial_cash=100.0)

    assert drawdown == -0.30
