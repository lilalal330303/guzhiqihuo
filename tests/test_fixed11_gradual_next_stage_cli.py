from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from quant_lab.backtest.portfolio import CostModel
from quant_lab.research.optimized_v3_runner import ExperimentCandidate
from tools.run_fixed11_gradual_next_stage import (
    REQUIRED_CANDIDATE_ARTIFACTS,
    build_candidate_catalog,
    build_run_manifest,
    candidate_run_hash,
    rank_core_variants,
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
    )
    first = candidate_run_hash(**kwargs)
    second = candidate_run_hash(**dict(reversed(list(kwargs.items()))))

    assert first == second
    assert len(first) == 64
    assert first != candidate_run_hash(**{**kwargs, "source_target_hash": "target-b"})
    assert first != candidate_run_hash(**{**kwargs, "costs": scale_cost_model(costs, 2.0)})


def test_resume_requires_exact_hash_audit_and_complete_artifacts(tmp_path: Path) -> None:
    run_dir = tmp_path / "candidate"
    run_dir.mkdir()
    for name in REQUIRED_CANDIDATE_ARTIFACTS:
        (run_dir / name).write_text("x", encoding="utf-8")
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
        rejected["candidate"].eq("one_factor_fixed_stop_loss_0p095"), "reason"
    ].item()
    assert "neighbor_stability" in reason
