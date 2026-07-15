from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from tools.build_fixed11_gradual_next_stage_report import (
    REPORT_DIR,
    build_artifact,
    load_evidence,
)
from tools.verify_fixed11_gradual_next_stage import (
    VerificationError,
    validate_artifact,
    validate_evidence,
)


REQUIRED_HEADINGS = (
    "技术摘要",
    "关键发现",
    "范围、数据与指标定义",
    "实验设计与方法",
    "局限、不确定性与稳健性",
    "建议的下一步",
    "待回答问题",
)


@pytest.fixture(scope="module")
def evidence() -> dict[str, object]:
    return load_evidence(REPORT_DIR)


@pytest.fixture(scope="module")
def artifact(evidence: dict[str, object]) -> dict[str, object]:
    return build_artifact(evidence=evidence)


def _body(artifact: dict[str, object]) -> str:
    return "\n".join(
        str(block.get("body", ""))
        for block in artifact["manifest"]["blocks"]
        if block.get("type") == "markdown"
    )


def test_report_states_zero_qualified_routes_without_forced_winner(
    artifact: dict[str, object],
) -> None:
    body = _body(artifact)
    assert "0 条路线通过" in body
    assert "balanced__recovery_0.45_confirm_2" in body
    assert "return__one_factor_fixed_stop_loss_0p115__current" in body
    assert "defensive__crash_overlay_05" in body
    assert "样本内诊断" in body
    for forbidden in ("正式入选", "可部署", "样本外最优", "已通过路线"):
        assert forbidden not in body


def test_required_sections_and_visual_references_resolve(
    artifact: dict[str, object],
) -> None:
    body = _body(artifact)
    assert all(heading in body for heading in REQUIRED_HEADINGS)
    manifest = artifact["manifest"]
    datasets = artifact["snapshot"]["datasets"]
    source_ids = {source["id"] for source in manifest["sources"]}
    chart_ids = {chart["id"] for chart in manifest["charts"]}
    table_ids = {table["id"] for table in manifest["tables"]}
    assert len(chart_ids) >= 5
    assert len(table_ids) >= 7
    for item in [*manifest["charts"], *manifest["tables"]]:
        assert item["dataset"] in datasets
        assert item["sourceId"] in source_ids
    for block in manifest["blocks"]:
        if block["type"] == "chart":
            assert block["chartId"] in chart_ids
        if block["type"] == "table":
            assert block["tableId"] in table_ids


def test_source_evidence_counts_and_audit_facts(evidence: dict[str, object]) -> None:
    facts = validate_evidence(evidence)
    assert facts["qualified_route_count"] == 0
    assert facts["policy_fold_counts"] == {"balanced": 4, "return": 4, "defensive": 1}
    assert facts["full_sample_candidate_count"] == 66
    assert facts["train_run_count"] == 135
    assert facts["test_run_count"] == 24
    assert facts["non_anchor_test_run_count"] == 19
    assert facts["diagnostic_run_count"] == 36
    assert facts["executed_run_count"] == 261
    assert facts["stress_row_count"] == 57
    assert facts["database_snapshot_unchanged"] is True
    assert facts["test_selection_leakage_count"] == 0
    assert facts["anchor_max_abs_equity_diff"] == pytest.approx(3.725290298461914e-09)
    assert facts["max_account_reconciliation_error"] == pytest.approx(3.725290298461914e-09)
    assert facts["minimum_cash"] == pytest.approx(0.3723244983702898)


def test_frontier_monthly_and_sensitivity_datasets_are_complete(
    artifact: dict[str, object],
) -> None:
    datasets = artifact["snapshot"]["datasets"]
    assert len(datasets["candidate_frontier"]) == 66
    assert {row["series"] for row in datasets["monthly_wealth"]} == {
        "fixed11_gradual",
        "balanced__recovery_0.45_confirm_2",
        "return__one_factor_fixed_stop_loss_0p115__current",
        "defensive__crash_overlay_05",
    }
    assert len(datasets["core_one_factor_sensitivity"]) == 20
    assert all("parameter_name" in row and "parameter_value" in row for row in datasets["core_one_factor_sensitivity"])


def test_encoding_is_clean(artifact: dict[str, object]) -> None:
    text = json.dumps(artifact, ensure_ascii=False)
    assert "�" not in text
    for marker in ("锟絽", "缁滄", "閿炳", "鍒濆", "鏈烽"):
        assert marker not in text


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda e: e["manifest"].__setitem__("qualified_route_count", 1), "gate drift"),
        (lambda e: e["manifest"].__setitem__("max_account_reconciliation_error", 1e-3), "reconciliation"),
        (lambda e: e["manifest"].__setitem__("minimum_cash", -0.01), "negative cash"),
        (lambda e: e["manifest"].__setitem__("test_selection_leakage_count", 1), "leakage"),
        (lambda e: e["manifest"].__setitem__("database_snapshot_unchanged", False), "DB drift"),
        (lambda e: e["manifest"].__setitem__("anchor_max_abs_equity_diff", 1e-3), "baseline drift"),
        (lambda e: e["manifest"]["crash_mechanism_audit"]["defensive__crash_overlay_01"].__setitem__("passed", True), "crash audit"),
        (lambda e: e["manifest"]["crash_mechanism_audit"]["defensive__crash_overlay_04"].__setitem__("crash_trigger_ratio", 0.19), "crash audit"),
        (lambda e: e["stress_results"].pop(), "incomplete evidence"),
    ],
)
def test_verifier_rejects_integrity_failures(
    evidence: dict[str, object], mutation, match: str
) -> None:
    broken = copy.deepcopy(evidence)
    mutation(broken)
    with pytest.raises(VerificationError, match=match):
        validate_evidence(broken)


def test_artifact_verifier_rejects_missing_heading_and_mojibake(
    artifact: dict[str, object],
) -> None:
    missing = copy.deepcopy(artifact)
    missing["manifest"]["blocks"] = [
        block for block in missing["manifest"]["blocks"] if block["id"] != "scope"
    ]
    with pytest.raises(VerificationError, match="missing headings"):
        validate_artifact(missing)

    corrupt = copy.deepcopy(artifact)
    corrupt["manifest"]["title"] += "�锟絽"
    with pytest.raises(VerificationError, match="encoding corruption"):
        validate_artifact(corrupt)
