from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from quant_lab.backtest.portfolio import CostModel
from quant_lab.research.optimized_v3_runner import ExperimentCandidate
from tools import run_fixed11_gradual_next_stage as cli
from tools.run_fixed11_gradual_next_stage import (
    REQUIRED_CANDIDATE_ARTIFACTS,
    build_candidate_catalog,
    build_route_candidates,
    build_run_manifest,
    candidate_run_hash,
    compare_equity_curves,
    completion_gate,
    cost_stress_models,
    database_snapshot,
    rank_core_variants,
    rebuild_annual_returns,
    scale_cost_model,
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


def test_resume_requires_exact_hash_audit_and_complete_artifacts(tmp_path: Path) -> None:
    run_dir = tmp_path / "candidate"
    run_dir.mkdir()
    for name in ("equity.csv", "trades.csv", "rejections.csv", "positions.csv",
                 "exposure_budget.csv"):
        write_csv(pd.DataFrame([{"value": 1}]), run_dir / name)
    write_json(run_dir / "parameters.json", {"name": "candidate"})
    (run_dir / "target_hash.txt").write_text("target", encoding="ascii")
    (run_dir / "run_hash.txt").write_text("abc", encoding="ascii")
    write_json(run_dir / "audit.json", {
        "candidate_hash": "abc",
        "passed": True,
        "account_reconciliation_error": 0.0,
        "minimum_cash": 0.0,
    })

    assert should_resume(run_dir, "abc")
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
    }
    for name in cli.ROOT_ARTIFACTS:
        path = tmp_path / name
        if name == "run_manifest.json":
            write_json(path, manifest)
        elif name.endswith(".json"):
            write_json(path, {"value": 1})
        else:
            write_csv(pd.DataFrame([{"value": 1}]), path)

    assert completion_gate(manifest, tmp_path)
    assert not completion_gate({**manifest, "cost_evidence_complete": False}, tmp_path)
    write_csv(pd.DataFrame(), tmp_path / "stress_results.csv")
    assert not completion_gate(manifest, tmp_path)


def test_walkforward_runner_routes_period_calls_through_persistent_resume_path(
    monkeypatch, tmp_path: Path
) -> None:
    captured = {}

    def fake_run(candidate, inputs, target_hashes, config, output, costs, resume,
                 input_data_fingerprint, run_context=None):
        captured.update({"output": output, "resume": resume,
                         "fingerprint": input_data_fingerprint, "context": run_context})
        return {
            "total_return": 0.1, "annualized_return": 0.2, "max_drawdown": -0.1,
            "sharpe": 1.0, "calmar": 2.0, "max_underwater_calendar_days": 10,
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
        "context": {"phase": "test", "fold": "fold_2024"},
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
            "run_context": {"phase": phase, "fold": "fold_2024" if phase == "test" else ""},
        })

    annual = rebuild_annual_returns(tmp_path)

    assert set(annual["phase"]) == {"full_sample", "test"}
    assert annual.set_index("year")["return"].to_dict() == {2023: 0.1, 2024: 0.2}
