from __future__ import annotations

import base64
import gzip
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
REPORT_DIR = ROOT / "reports" / "small_cap_fixed11_gradual_next_stage"
ARTIFACT_PATH = REPORT_DIR / "artifact.json"
HTML_PATH = REPORT_DIR / "report.html"
VERIFICATION_PATH = REPORT_DIR / "verification.json"

REQUIRED_HEADINGS = (
    "技术摘要",
    "关键发现",
    "范围、数据与指标定义",
    "实验设计与方法",
    "局限、不确定性与稳健性",
    "建议的下一步",
    "待回答问题",
)
MOJIBAKE_MARKERS = ("�", "锟絽", "缁滄", "閿炳", "鍒濆", "鏈烽")


class VerificationError(RuntimeError):
    pass


def _fail(message: str) -> None:
    raise VerificationError(message)


def validate_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    manifest = evidence["manifest"]
    decisions = manifest.get("route_decisions", {})
    expected_routes = {"balanced", "return", "defensive"}
    if manifest.get("qualified_route_count") != 0 or set(decisions) != expected_routes:
        _fail("gate drift: qualified route state is not the reviewed zero-route decision")
    policy_counts = {route: int(decisions[route]["policy_fold_count"]) for route in expected_routes}
    if policy_counts != {"balanced": 4, "return": 4, "defensive": 1}:
        _fail("gate drift: route policy-fold coverage changed")
    for route, decision in decisions.items():
        if decision.get("passed") or decision.get("qualified_for_gate") or not decision.get("diagnostic_only"):
            _fail(f"gate drift: {route} is no longer diagnostic-only and rejected")
        if decision.get("reasons") != ["missing_policy_fold"]:
            _fail(f"gate drift: {route} rejection reason changed")
    selected_test_counts = {route: 0 for route in expected_routes}
    for row in evidence.get("walkforward_test", []):
        rank = row.get("train_rank")
        if row.get("route") in selected_test_counts and rank is not None and float(rank) == 1.0:
            selected_test_counts[row["route"]] += 1
    if selected_test_counts != policy_counts:
        _fail("gate drift: route coverage disagrees with walk-forward test evidence")

    if float(manifest.get("max_account_reconciliation_error", 1.0)) > 1e-6:
        _fail("reconciliation error exceeds tolerance")
    if float(manifest.get("minimum_cash", -1.0)) < 0:
        _fail("negative cash detected")
    if int(manifest.get("test_selection_leakage_count", -1)) != 0:
        _fail("leakage detected in test selection")
    if not manifest.get("database_snapshot_unchanged") or manifest.get("database_snapshot_before") != manifest.get("database_snapshot_after"):
        _fail("DB drift detected during experiment")
    if float(manifest.get("anchor_max_abs_equity_diff", 1.0)) > 1e-6:
        _fail("baseline drift exceeds same-snapshot tolerance")

    crash = manifest.get("crash_mechanism_audit", {})
    expected_names = [f"defensive__crash_overlay_0{i}" for i in range(1, 7)]
    if list(crash) != expected_names:
        _fail("crash audit candidates are incomplete or reordered")
    expected_pass = {name: index >= 4 for index, name in enumerate(expected_names, start=1)}
    if any(bool(crash[name].get("passed")) != expected_pass[name] for name in expected_names):
        _fail("crash audit pass states changed")
    if any(not 0 <= float(crash[name].get("crash_trigger_ratio", -1)) <= 1 for name in expected_names):
        _fail("crash audit trigger ratios are invalid")
    if int(manifest.get("index_warmup_trading_days", -1)) != 60:
        _fail("crash audit warmup denominator changed")
    crash_scores = {row["candidate"]: row for row in evidence.get("route_scores", []) if row.get("candidate") in expected_names}
    if set(crash_scores) != set(expected_names):
        _fail("crash audit route-score evidence is incomplete")
    for name in expected_names:
        score = crash_scores[name]
        if abs(float(score["crash_trigger_ratio"]) - float(crash[name]["crash_trigger_ratio"])) > 1e-9:
            _fail("crash audit trigger ratios disagree with route scores")
        if bool(score["crash_mechanism_passed"]) != bool(crash[name]["passed"]):
            _fail("crash audit pass states disagree with route scores")

    reference = evidence.get("current_db_anchor_reference", [])
    anchor_equity = evidence.get("candidate_runs", {}).get("fixed11_gradual", {}).get("equity", [])
    if len(reference) != len(anchor_equity) or not reference:
        _fail("baseline drift: same-snapshot anchor series is incomplete")
    reference_by_date = {row["trade_date"]: float(row["equity"]) for row in reference}
    try:
        computed_anchor_diff = max(
            abs(float(row["equity"]) - reference_by_date[row["trade_date"]])
            for row in anchor_equity
        )
    except KeyError as exc:
        raise VerificationError(f"baseline drift: anchor date missing from reference: {exc}") from exc
    if computed_anchor_diff > 1e-6:
        _fail("baseline drift: same-snapshot equity series exceeds tolerance")

    core_count = len(evidence.get("core_scores", []))
    route_count = len(evidence.get("route_scores", []))
    train_count = len(evidence.get("walkforward_training", []))
    test_count = len(evidence.get("walkforward_test", []))
    non_anchor_test = sum(row.get("route") != "anchor" for row in evidence.get("walkforward_test", []))
    stress_count = len(evidence.get("stress_results", []))
    stress_types: dict[str, int] = {}
    for row in evidence.get("stress_results", []):
        kind = str(row.get("evidence_type"))
        stress_types[kind] = stress_types.get(kind, 0) + 1
    diagnostic_count = int(manifest.get("executed_run_count", -1)) - core_count - route_count - train_count - test_count
    if (core_count + route_count, train_count, test_count, non_anchor_test, diagnostic_count) != (66, 135, 24, 19, 36):
        _fail("incomplete evidence: run counts do not match the reviewed experiment")
    if stress_count != 57 or stress_types != {"missing_policy": 3, "cost": 42, "stress_window": 12}:
        _fail("incomplete evidence: stress rows are not 3+42+12")
    if int(manifest.get("executed_run_count", -1)) != 261:
        _fail("incomplete evidence: total executed run count changed")
    if not manifest.get("cost_evidence_complete") or not manifest.get("stress_evidence_complete"):
        _fail("incomplete evidence: cost/stress completeness flags are false")

    expected_leaders = {
        "balanced": "balanced__recovery_0.45_confirm_2",
        "return": "return__one_factor_fixed_stop_loss_0p115__current",
        "defensive": "defensive__crash_overlay_05",
    }
    if any(decisions[route].get("candidate") != candidate for route, candidate in expected_leaders.items()):
        _fail("gate drift: diagnostic leader identity changed")

    candidate_runs = evidence.get("candidate_runs", {})
    required_runs = {"fixed11_gradual", *expected_leaders.values()}
    if set(candidate_runs) != required_runs:
        _fail("incomplete evidence: current-fingerprint equity/audit files are missing")
    for candidate, run in candidate_runs.items():
        audit = run.get("audit", {})
        if not audit.get("passed") or not audit.get("artifacts_complete"):
            _fail(f"incomplete evidence: candidate audit failed for {candidate}")
        if audit.get("run_context", {}).get("experiment_fingerprint") != manifest.get("experiment_fingerprint"):
            _fail(f"incomplete evidence: stale candidate audit for {candidate}")

    return {
        "qualified_route_count": 0,
        "policy_fold_counts": {route: policy_counts[route] for route in ("balanced", "return", "defensive")},
        "full_sample_candidate_count": core_count + route_count,
        "train_run_count": train_count,
        "test_run_count": test_count,
        "non_anchor_test_run_count": non_anchor_test,
        "diagnostic_run_count": diagnostic_count,
        "executed_run_count": int(manifest["executed_run_count"]),
        "stress_row_count": stress_count,
        "database_snapshot_unchanged": True,
        "test_selection_leakage_count": 0,
        "anchor_max_abs_equity_diff": float(manifest["anchor_max_abs_equity_diff"]),
        "max_account_reconciliation_error": float(manifest["max_account_reconciliation_error"]),
        "minimum_cash": float(manifest["minimum_cash"]),
        "historical_snapshot_max_abs_diff": float(manifest["historical_snapshot_drift"]["max_abs_equity_diff"]),
        "crash_mechanism_audit": crash,
    }


def validate_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    if artifact.get("surface") != "report" or artifact.get("manifest", {}).get("surface") != "report":
        _fail("artifact surface is not report")
    manifest = artifact["manifest"]
    body = "\n".join(str(block.get("body", "")) for block in manifest.get("blocks", []) if block.get("type") == "markdown")
    missing = [heading for heading in REQUIRED_HEADINGS if heading not in body]
    if missing:
        _fail(f"missing headings: {missing}")
    text = json.dumps(artifact, ensure_ascii=False)
    if any(marker in text for marker in MOJIBAKE_MARKERS):
        _fail("encoding corruption detected")
    if "0 条路线通过" not in body or "样本内诊断" not in body:
        _fail("gate drift: report does not state zero qualified routes and diagnostic-only leaders")
    for phrase in ("正式入选", "样本外最优", "已通过路线"):
        if phrase in body:
            _fail(f"forced-winner language detected: {phrase}")

    datasets = artifact.get("snapshot", {}).get("datasets", {})
    source_ids = {source.get("id") for source in manifest.get("sources", [])}
    top_source_ids = {source.get("id") for source in artifact.get("sources", [])}
    if source_ids != top_source_ids:
        _fail("source references do not resolve consistently")
    chart_ids = {chart.get("id") for chart in manifest.get("charts", [])}
    table_ids = {table.get("id") for table in manifest.get("tables", [])}
    for item in [*manifest.get("charts", []), *manifest.get("tables", [])]:
        if item.get("dataset") not in datasets or item.get("sourceId") not in source_ids:
            _fail(f"dataset/source reference does not resolve for {item.get('id')}")
    for block in manifest.get("blocks", []):
        if block.get("type") == "chart" and block.get("chartId") not in chart_ids:
            _fail(f"chart block reference does not resolve: {block}")
        if block.get("type") == "table" and block.get("tableId") not in table_ids:
            _fail(f"table block reference does not resolve: {block}")
        if block.get("sourceId") and block.get("sourceId") not in source_ids:
            _fail(f"markdown source reference does not resolve: {block.get('id')}")
    if len(datasets.get("candidate_frontier", [])) != 66:
        _fail("incomplete evidence: frontier does not contain 66 candidates")
    if len(datasets.get("core_one_factor_sensitivity", [])) != 20:
        _fail("incomplete evidence: one-factor sensitivity does not contain 20 rows")
    if len(datasets.get("fold_evidence", [])) != 15:
        _fail("incomplete evidence: fold table does not contain 3x5 route-fold rows")
    if len(datasets.get("cost_exact", [])) != 42 or len(datasets.get("stress_windows", [])) != 12:
        _fail("incomplete evidence: report cost/stress datasets are incomplete")
    if len(datasets.get("crash_audit", [])) != 6 or len(datasets.get("route_decisions", [])) != 3:
        _fail("incomplete evidence: crash/route decision datasets are incomplete")
    return {
        "headings_present": True,
        "references_resolve": True,
        "encoding_clean": True,
        "qualified_route_count": 0,
    }


def _embedded_artifact(html_text: str) -> dict[str, Any]:
    match = re.search(
        r'<template id="data-analytics-portable-artifact-payload-source"[^>]*data-compression="gzip-base64"[^>]*>\s*([^<]+?)\s*</template>',
        html_text,
        flags=re.DOTALL,
    )
    if not match:
        _fail("portable HTML payload is missing")
    try:
        raw = gzip.decompress(base64.b64decode("".join(match.group(1).split())))
        return json.loads(raw.decode("utf-8"))
    except Exception as exc:  # pragma: no cover - error detail is useful in CLI verification
        raise VerificationError(f"portable HTML payload cannot be decoded: {exc}") from exc


def validate_html(html_text: str, artifact: dict[str, Any]) -> dict[str, Any]:
    lower = html_text.lower()
    if 'charset="utf-8"' not in lower and "charset=utf-8" not in lower:
        _fail("portable HTML does not declare UTF-8")
    if any(marker in html_text for marker in MOJIBAKE_MARKERS):
        _fail("encoding corruption detected in HTML")
    embedded = _embedded_artifact(html_text)
    if any(embedded[key] != artifact[key] for key in ("surface", "manifest", "snapshot")):
        _fail("embedded canonical artifact differs from artifact.json")
    embedded_sources = {source["id"]: source for source in embedded["sources"]}
    for source in artifact["sources"]:
        actual_source = embedded_sources.get(source["id"], {})
        if any(actual_source.get(key) != value for key, value in source.items()):
            _fail("embedded canonical artifact differs from artifact.json")
    package_info = embedded.get("package_info", {})
    verification = package_info.get("verification") or package_info.get("stages", {}).get("verification") or "structural_only"
    return {"utf8": True, "payload_equal": True, "packaging_verification": verification}


def verify(
    report_dir: Path = REPORT_DIR,
    artifact_path: Path = ARTIFACT_PATH,
    html_path: Path = HTML_PATH,
    output_path: Path = VERIFICATION_PATH,
) -> dict[str, Any]:
    from tools.build_fixed11_gradual_next_stage_report import load_evidence

    evidence = load_evidence(report_dir)
    evidence_facts = validate_evidence(evidence)
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    artifact_checks = validate_artifact(artifact)
    html_checks = validate_html(html_path.read_text(encoding="utf-8"), artifact)
    result = {
        "passed": True,
        "status": "passed" if html_checks["packaging_verification"] == "passed" else "structural_only",
        "evidence": evidence_facts,
        "artifact": artifact_checks,
        "html": html_checks,
    }
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps(verify(), ensure_ascii=False, indent=2))
