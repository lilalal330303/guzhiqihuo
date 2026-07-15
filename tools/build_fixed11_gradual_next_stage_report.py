from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
REPORT_DIR = ROOT / "reports" / "small_cap_fixed11_gradual_next_stage"
OUTPUT_ARTIFACT = REPORT_DIR / "artifact.json"

ROOT_CSV_FILES = (
    "annual_returns.csv",
    "candidate_catalog.csv",
    "core_scores.csv",
    "current_db_anchor_reference.csv",
    "rejected_candidates.csv",
    "route_gate_results.csv",
    "route_scores.csv",
    "stress_results.csv",
    "target_manifest.csv",
    "walkforward_test.csv",
    "walkforward_training.csv",
)

DIAGNOSTIC_CANDIDATES = (
    "balanced__recovery_0.45_confirm_2",
    "return__one_factor_fixed_stop_loss_0p115__current",
    "defensive__crash_overlay_05",
)
CURVE_CANDIDATES = ("fixed11_gradual", *DIAGNOSTIC_CANDIDATES)
ROUTES = ("balanced", "return", "defensive")
ROUTE_CN = {"balanced": "平衡", "return": "收益", "defensive": "防守", "anchor": "基准", "core": "核心"}


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    clean = frame.copy()
    for column in clean.columns:
        if pd.api.types.is_datetime64_any_dtype(clean[column]):
            clean[column] = clean[column].dt.strftime("%Y-%m-%d")
    clean = clean.where(pd.notna(clean), None)
    return json.loads(clean.to_json(orient="records", force_ascii=False, double_precision=15))


def _safe_rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _full_sample_score_map(frames: dict[str, pd.DataFrame]) -> dict[str, dict[str, Any]]:
    scores = pd.concat([frames["core_scores.csv"], frames["route_scores.csv"]], ignore_index=True)
    return {str(row["candidate"]): row for row in _records(scores)}


def _load_current_run(candidate: str, score: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    run_dir = REPORT_DIR / "candidates" / candidate / str(score["candidate_hash"])[:16]
    audit_path = run_dir / "audit.json"
    equity_path = run_dir / "equity.csv"
    if not audit_path.exists() or not equity_path.exists():
        raise FileNotFoundError(f"Missing current-fingerprint artifacts for {candidate}: {run_dir}")
    audit = _load_json(audit_path)
    context = audit.get("run_context", {})
    if context.get("experiment_fingerprint") != manifest.get("experiment_fingerprint"):
        raise RuntimeError(f"Stale candidate audit for {candidate}")
    if context.get("phase") != "full_sample" or audit.get("candidate_hash") != score.get("candidate_hash"):
        raise RuntimeError(f"Candidate audit mismatch for {candidate}")
    equity = pd.read_csv(equity_path, parse_dates=["trade_date"])
    return {
        "audit": audit,
        "audit_path": _safe_rel(audit_path),
        "equity": _records(equity),
        "equity_path": _safe_rel(equity_path),
    }


def load_evidence(report_dir: Path = REPORT_DIR) -> dict[str, Any]:
    if report_dir.resolve() != REPORT_DIR.resolve():
        raise ValueError("This report is bound to the reviewed Task 7 artifact directory")
    manifest = _load_json(report_dir / "run_manifest.json")
    frames = {name: pd.read_csv(report_dir / name) for name in ROOT_CSV_FILES}
    scores = _full_sample_score_map(frames)
    candidate_runs = {
        candidate: _load_current_run(candidate, scores[candidate], manifest)
        for candidate in CURVE_CANDIDATES
    }
    return {
        "manifest": manifest,
        **{name.removesuffix(".csv"): _records(frame) for name, frame in frames.items()},
        "candidate_runs": candidate_runs,
    }


def _flatten(value: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    flattened: dict[str, Any] = {}
    for key, item in value.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(item, dict):
            flattened.update(_flatten(item, path))
        else:
            flattened[path] = item
    return flattened


def _one_factor_rows(evidence: dict[str, Any], anchor: dict[str, Any]) -> list[dict[str, Any]]:
    catalog = {row["name"]: json.loads(row["parameters_json"]) for row in evidence["candidate_catalog"]}
    anchor_params = _flatten(catalog["fixed11_gradual"])
    rows: list[dict[str, Any]] = [{
        "candidate": "fixed11_gradual",
        "parameter_name": "anchor",
        "parameter_value": "fixed11_gradual",
        "total_return": anchor["total_return"],
        "max_drawdown": anchor["max_drawdown"],
        "total_return_delta": 0.0,
        "drawdown_improvement": 0.0,
    }]
    for score in evidence["core_scores"]:
        name = str(score["candidate"])
        if not name.startswith("one_factor_"):
            continue
        params = _flatten(catalog[name])
        ignored = {"name", "core.name", "route"}
        changed = [(key, value) for key, value in params.items() if key not in ignored and anchor_params.get(key) != value]
        if len(changed) != 1:
            raise RuntimeError(f"Expected exactly one changed parameter for {name}, got {changed}")
        parameter_name, parameter_value = changed[0]
        rows.append({
            "candidate": name,
            "parameter_name": parameter_name,
            "parameter_value": parameter_value,
            "total_return": score["total_return"],
            "max_drawdown": score["max_drawdown"],
            "total_return_delta": float(score["total_return"]) - float(anchor["total_return"]),
            "drawdown_improvement": abs(float(anchor["max_drawdown"])) - abs(float(score["max_drawdown"])),
        })
    if len(rows) != 20:
        raise RuntimeError(f"Expected 20 one-factor rows, got {len(rows)}")
    return rows


def _monthly_wealth(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for candidate in CURVE_CANDIDATES:
        frame = pd.DataFrame(evidence["candidate_runs"][candidate]["equity"])
        frame["trade_date"] = pd.to_datetime(frame["trade_date"])
        monthly = frame.groupby(frame["trade_date"].dt.to_period("M"), as_index=False).tail(1).copy()
        monthly["wealth_multiple"] = monthly["equity"] / 1_000_000.0
        monthly["series"] = candidate
        output.extend(_records(monthly[["trade_date", "series", "wealth_multiple"]]))
    return output


def _fold_evidence(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    test = pd.DataFrame(evidence["walkforward_test"])
    folds = sorted(test["fold"].dropna().unique())
    anchor = test[test["route"] == "anchor"].set_index("fold")
    selected = test[pd.to_numeric(test["train_rank"], errors="coerce") == 1]
    rows: list[dict[str, Any]] = []
    for route in ROUTES:
        for fold in folds:
            match = selected[(selected["route"] == route) & (selected["fold"] == fold)]
            if match.empty:
                rows.append({"route": route, "route_label": ROUTE_CN[route], "fold": fold, "status": "缺失稳定训练策略"})
                continue
            row = match.iloc[0]
            base = anchor.loc[fold]
            rows.append({
                "route": route,
                "route_label": ROUTE_CN[route],
                "fold": fold,
                "status": "训练集第1名已冻结",
                "candidate": row["candidate"],
                "return_difference": float(row["total_return"]) - float(base["total_return"]),
                "drawdown_difference": float(row["max_drawdown"]) - float(base["max_drawdown"]),
                "calmar": float(row["calmar"]),
                "sharpe": float(row["sharpe"]),
            })
    return rows


def _route_decisions(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    catalog = {row["name"]: json.loads(row["parameters_json"]) for row in evidence["candidate_catalog"]}
    rows = []
    for route in ROUTES:
        decision = evidence["manifest"]["route_decisions"][route]
        candidate = decision["candidate"]
        rows.append({
            "route": route,
            "route_label": ROUTE_CN[route],
            "candidate": candidate,
            "policy_fold_count": decision["policy_fold_count"],
            "passed": decision["passed"],
            "diagnostic_only": decision["diagnostic_only"],
            "selection_basis": decision["selection_basis"],
            "reasons": ", ".join(decision["reasons"]),
            "parameters_json": json.dumps(catalog[candidate], ensure_ascii=False, sort_keys=True),
        })
    return rows


def _source(source_id: str, label: str, path: str, description: str) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest_source = {"id": source_id, "label": label, "path": path}
    query_source = {
        "id": source_id,
        "query": {
            "engine": "duckdb",
            "language": "sql",
            "sql": f"SELECT * FROM read_csv_auto('{path}')" if path.endswith(".csv") else "SELECT 1 AS reviewed_artifact",
            "description": description,
            "tables": [path],
        },
    }
    return manifest_source, query_source


def build_artifact(evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    evidence = load_evidence() if evidence is None else evidence
    from tools.verify_fixed11_gradual_next_stage import validate_evidence

    facts = validate_evidence(evidence)
    all_scores = [*evidence["core_scores"], *evidence["route_scores"]]
    anchor = next(row for row in all_scores if row["candidate"] == "fixed11_gradual")
    frontier = [{**row, "route_label": ROUTE_CN.get(row["route"], row["route"])} for row in all_scores]
    sensitivity = _one_factor_rows(evidence, anchor)
    sensitivity_chart = [
        {
            "candidate": row["candidate"],
            "parameter": f"{row['parameter_name']}={row['parameter_value']}",
            "metric": metric,
            "delta": row[field],
        }
        for row in sensitivity
        for metric, field in (("总收益差", "total_return_delta"), ("回撤改善", "drawdown_improvement"))
    ]
    route_coverage = [
        {"route": route, "route_label": ROUTE_CN[route], "covered_folds": facts["policy_fold_counts"][route], "required_folds": 5}
        for route in ROUTES
    ]
    fold_rows = _fold_evidence(evidence)
    stress = evidence["stress_results"]
    combined_cost = [
        {**row, "route_label": ROUTE_CN[row["route"]]}
        for row in stress
        if row["evidence_type"] == "cost" and row["series"] == "candidate" and str(row["cost_label"]).startswith("combined_")
    ]
    exact_cost = [{**row, "route_label": ROUTE_CN[row["route"]]} for row in stress if row["evidence_type"] == "cost"]
    stress_windows = [
        {**row, "route_label": ROUTE_CN[row["route"]], "route_series": f"{ROUTE_CN[row['route']]}-{row['series']}"}
        for row in stress if row["evidence_type"] == "stress_window"
    ]
    crash_rows = [
        {"candidate": name, "crash_trigger_ratio": audit["crash_trigger_ratio"], "passed": audit["passed"], "warmup_trading_days": evidence["manifest"]["index_warmup_trading_days"]}
        for name, audit in evidence["manifest"]["crash_mechanism_audit"].items()
    ]
    decisions = _route_decisions(evidence)
    audit_facts = [
        {"item": "研究区间", "value": f"{evidence['manifest']['requested_start']} 至 {evidence['manifest']['requested_end']}", "interpretation": "严格日线近似"},
        {"item": "初始资金", "value": f"CNY {float(evidence['manifest']['initial_cash']):,.0f}", "interpretation": "全实验统一"},
        {"item": "全样本候选", "value": str(facts["full_sample_candidate_count"]), "interpretation": "37个核心/锚点 + 29个路线"},
        {"item": "训练/测试/诊断运行", "value": f"{facts['train_run_count']} / {facts['test_run_count']} / {facts['diagnostic_run_count']}", "interpretation": f"测试中非锚点 {facts['non_anchor_test_run_count']}"},
        {"item": "总运行数", "value": str(facts["executed_run_count"]), "interpretation": "过程完整性计数"},
        {"item": "同快照锚点最大绝对差", "value": repr(facts["anchor_max_abs_equity_diff"]), "interpretation": "低于 1e-6"},
        {"item": "最大账户勾稽误差", "value": repr(facts["max_account_reconciliation_error"]), "interpretation": "低于 1e-6"},
        {"item": "最低现金", "value": repr(facts["minimum_cash"]), "interpretation": "非负"},
        {"item": "数据库快照", "value": "运行前后一致", "interpretation": "SHA-256、大小和 mtime 一致"},
        {"item": "测试选择泄漏", "value": str(facts["test_selection_leakage_count"]), "interpretation": "不允许使用测试结果重选"},
        {"item": "压力证据行", "value": str(facts["stress_row_count"]), "interpretation": "42成本 + 12窗口 + 3缺失策略"},
        {"item": "历史早间快照漂移", "value": repr(facts["historical_snapshot_max_abs_diff"]), "interpretation": "单独报告，不归因为策略差异"},
    ]
    rejected_counts = (
        pd.DataFrame(evidence["rejected_candidates"])
        .groupby(["rejected_for_route", "reason"], dropna=False)
        .size().reset_index(name="count")
    )
    rejected_counts = rejected_counts.where(pd.notna(rejected_counts), "未分类")

    sources: list[dict[str, Any]] = []
    source_queries: list[dict[str, Any]] = []
    source_specs = [
        ("run_manifest", "运行与完整性审计", "reports/small_cap_fixed11_gradual_next_stage/run_manifest.json", "Task 7 严格运行清单与审计门禁"),
        ("scores", "全样本候选得分", "logical/full_sample_scores", "核心和路线全样本得分"),
        ("catalog", "单因子参数与得分", "logical/one_factor_sensitivity", "预注册候选参数与核心全样本得分"),
        ("walkforward", "严格滚动样本外", "reports/small_cap_fixed11_gradual_next_stage/walkforward_test.csv", "五个滚动窗口的训练冻结与测试证据"),
        ("stress", "成本与压力证据", "reports/small_cap_fixed11_gradual_next_stage/stress_results.csv", "七种成本模型、两个压力窗口与缺失策略标记"),
        ("rejections", "拒绝原因审计", "reports/small_cap_fixed11_gradual_next_stage/rejected_candidates.csv", "路线候选拒绝原因"),
        ("equity", "当前指纹全样本净值", "logical/current_fingerprint_monthly_equity", "基准与三个样本内诊断冠军的当前指纹净值文件"),
    ]
    for spec in source_specs:
        manifest_source, query_source = _source(*spec)
        sources.append(manifest_source)
        source_queries.append(query_source)
    query_by_id = {source["id"]: source["query"] for source in source_queries}
    query_by_id["scores"].update({
        "sql": "SELECT * FROM read_csv_auto('reports/small_cap_fixed11_gradual_next_stage/core_scores.csv') UNION ALL BY NAME SELECT * FROM read_csv_auto('reports/small_cap_fixed11_gradual_next_stage/route_scores.csv')",
        "tables": ["reports/small_cap_fixed11_gradual_next_stage/core_scores.csv", "reports/small_cap_fixed11_gradual_next_stage/route_scores.csv"],
    })
    query_by_id["catalog"].update({
        "sql": "SELECT c.*, s.total_return, s.max_drawdown FROM read_csv_auto('reports/small_cap_fixed11_gradual_next_stage/candidate_catalog.csv') c JOIN read_csv_auto('reports/small_cap_fixed11_gradual_next_stage/core_scores.csv') s ON c.name = s.candidate WHERE c.name = 'fixed11_gradual' OR c.name LIKE 'one_factor_%'",
        "tables": ["reports/small_cap_fixed11_gradual_next_stage/candidate_catalog.csv", "reports/small_cap_fixed11_gradual_next_stage/core_scores.csv"],
    })
    equity_paths = [evidence["candidate_runs"][candidate]["equity_path"] for candidate in CURVE_CANDIDATES]
    query_by_id["equity"].update({
        "sql": " UNION ALL BY NAME ".join(
            f"SELECT *, '{candidate}' AS series FROM read_csv_auto('{path}')"
            for candidate, path in zip(CURVE_CANDIDATES, equity_paths)
        ),
        "tables": equity_paths,
    })

    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    summary = (
        f"## 技术摘要：0 条路线通过，保留 fixed11_gradual 作为研究锚点\n\n"
        f"本轮研究的过程完整性门禁已通过，但策略资格门禁结论是 **0 条路线通过**。"
        f"平衡、收益、防守路线只有 {facts['policy_fold_counts']['balanced']}/5、{facts['policy_fold_counts']['return']}/5 和 {facts['policy_fold_counts']['defensive']}/5 的稳定策略覆盖，"
        "因此均在正式成本/压力门禁之前失败。`run_manifest.json` 中的 `passed=true` 只代表运行和证据完整，不代表任何路线通过。\n\n"
        "`balanced__recovery_0.45_confirm_2`、`return__one_factor_fixed_stop_loss_0p115__current` 和 `defensive__crash_overlay_05` 仅是**样本内诊断**对照，不是被选中的样本外策略。"
    )

    charts = [
        {"id": "frontier", "title": "66 个全样本候选的收益—回撤前沿", "subtitle": "2020-01-01至2026-07-06；全样本排名不等于样本外资格", "type": "scatter", "dataset": "candidate_frontier", "sourceId": "scores", "encodings": {"x": {"field": "max_drawdown", "type": "quantitative", "label": "最大回撤"}, "y": {"field": "total_return", "type": "quantitative", "label": "总收益"}, "color": {"field": "route_label", "type": "nominal", "label": "路线"}, "tooltip": [{"field": "candidate", "type": "nominal", "label": "候选"}, {"field": "family", "type": "nominal", "label": "家族"}, {"field": "calmar", "type": "quantitative", "label": "Calmar"}] }},
        {"id": "sensitivity", "title": "核心单因子参数相对锚点的变化", "subtitle": "每次只改一个参数；正的回撤改善表示回撤绝对值缩小", "type": "bar", "dataset": "one_factor_deltas", "sourceId": "catalog", "encodings": {"x": {"field": "parameter", "type": "nominal", "label": "参数值"}, "y": {"field": "delta", "type": "quantitative", "label": "相对变化"}, "color": {"field": "metric", "type": "nominal", "label": "指标"}}},
        {"id": "coverage", "title": "路线滚动样本外策略覆盖", "subtitle": "通过资格需要5/5个测试窗口均有稳定训练策略", "type": "bar", "dataset": "route_coverage", "sourceId": "run_manifest", "encodings": {"x": {"field": "route_label", "type": "nominal", "label": "路线"}, "y": {"field": "covered_folds", "type": "quantitative", "label": "已覆盖窗口"}}},
        {"id": "wealth", "title": "锚点与三个诊断对照的月末财富曲线", "subtitle": "全样本内诊断曲线，不是被选候选的样本外曲线", "type": "line", "dataset": "monthly_wealth", "sourceId": "equity", "encodings": {"x": {"field": "trade_date", "type": "temporal", "label": "日期"}, "y": {"field": "wealth_multiple", "type": "quantitative", "label": "财富倍数"}, "color": {"field": "series", "type": "nominal", "label": "系列"}}},
        {"id": "combined_cost", "title": "三条路线诊断对照的组合成本总收益", "subtitle": "1x、1.5x、2x为离散成本场景；不用于候选资格判定", "type": "bar", "dataset": "combined_cost", "sourceId": "stress", "encodings": {"x": {"field": "cost_label", "type": "nominal", "label": "成本场景"}, "y": {"field": "total_return", "type": "quantitative", "label": "总收益"}, "color": {"field": "route_label", "type": "nominal", "label": "路线"}}},
        {"id": "stress_windows", "title": "2024年一季度与2026年年初至今压力窗口", "subtitle": "诊断候选与锚点同窗口对比", "type": "bar", "dataset": "stress_windows", "sourceId": "stress", "encodings": {"x": {"field": "window", "type": "nominal", "label": "压力窗口"}, "y": {"field": "total_return", "type": "quantitative", "label": "总收益"}, "color": {"field": "route_series", "type": "nominal", "label": "路线-系列"}}},
    ]

    def table(table_id: str, title: str, subtitle: str, dataset: str, source_id: str, columns: list[tuple[str, str, str]]) -> dict[str, Any]:
        return {"id": table_id, "title": title, "subtitle": subtitle, "dataset": dataset, "sourceId": source_id, "columns": [{"field": field, "label": label, "format": fmt} for field, label, fmt in columns]}

    tables = [
        table("one_factor", "单因子参数完整明细", "20个预注册单因子值，相对 fixed11_gradual", "core_one_factor_sensitivity", "catalog", [("parameter_name", "参数", "text"), ("parameter_value", "参数值", "text"), ("total_return_delta", "总收益差", "percent"), ("drawdown_improvement", "回撤改善", "percent")]),
        table("folds", "五窗口训练冻结证据", "明示稳定策略缺失的路线-窗口", "fold_evidence", "walkforward", [("route_label", "路线", "text"), ("fold", "窗口", "text"), ("status", "状态", "text"), ("candidate", "训练第1名", "text"), ("return_difference", "测试收益差", "percent"), ("drawdown_difference", "测试回撤差", "percent"), ("calmar", "Calmar", "number"), ("sharpe", "夏普", "number")]),
        table("cost_exact", "七种成本模型完整明细", "三条路线各含诊断候选和锚点，共42行", "cost_exact", "stress", [("route_label", "路线", "text"), ("series", "系列", "text"), ("cost_label", "成本模型", "text"), ("total_return", "总收益", "percent"), ("max_drawdown", "最大回撤", "percent"), ("calmar", "Calmar", "number")]),
        table("stress_exact", "压力窗口完整对照", "两个压力窗口×三条路线×候选/锚点", "stress_windows", "stress", [("window", "窗口", "text"), ("route_label", "路线", "text"), ("series", "系列", "text"), ("total_return", "总收益", "percent"), ("max_drawdown", "最大回撤", "percent")]),
        table("crash", "崩盘覆盖机制审计", "分母为精确60个交易日预热后的正式区间", "crash_audit", "run_manifest", [("candidate", "覆盖方案", "text"), ("crash_trigger_ratio", "触发比例", "percent"), ("passed", "机制审计通过", "text"), ("warmup_trading_days", "预热交易日", "number")]),
        table("decisions", "三条路线决策与诊断参数", "诊断冠军仅用于解释，全部因 missing_policy_fold 失败", "route_decisions", "run_manifest", [("route_label", "路线", "text"), ("candidate", "样本内诊断对照", "text"), ("policy_fold_count", "策略覆盖", "number"), ("passed", "通过", "text"), ("reasons", "拒绝原因", "text"), ("parameters_json", "精确参数", "text")]),
        table("rejections", "拒绝原因计数", "按路线和原因聚合的审计计数", "rejection_counts", "rejections", [("rejected_for_route", "路线", "text"), ("reason", "原因", "text"), ("count", "数量", "number")]),
        table("audit_facts", "数据、运行与账户审计事实", "重现门禁所需的精确区间、计数与容差", "audit_facts", "run_manifest", [("item", "审计项", "text"), ("value", "精确值", "text"), ("interpretation", "口径/结论", "text")]),
    ]

    blocks = [
        {"id": "title", "type": "markdown", "body": "# fixed11_gradual 下一阶段严格优化研究报告"},
        {"id": "summary", "type": "markdown", "body": summary, "sourceId": "run_manifest"},
        {"id": "findings", "type": "markdown", "body": "## 关键发现：全样本领先没有转化为滚动样本外资格\n\n全样本前沿能帮助定位收益和风险的取舍，但不能代替训练窗口稳定性和样本外门禁。"},
        {"id": "frontier_intro", "type": "markdown", "body": f"66个全样本点显示多个局部领先者，其中 `fixed11_gradual` 是审计锚点。读图时应同时看收益、回撤、路线和 Calmar，不应将右上角个体解读为样本外资格。"},
        {"id": "frontier_chart", "type": "chart", "chartId": "frontier"},
        {"id": "frontier_after", "type": "markdown", "body": "**含义：**前沿只是样本内诊断工具。本轮最终决策依据是五窗口训练冻结后的覆盖，而不是全样本排名。"},
        {"id": "sensitivity_intro", "type": "markdown", "body": "单因子峰值往往是孤立的；对相邻参数进行稳定性过滤后，排名会改变。下图和明细保留了每个精确参数名和参数值。"},
        {"id": "sensitivity_chart", "type": "chart", "chartId": "sensitivity"},
        {"id": "sensitivity_table", "type": "table", "tableId": "one_factor"},
        {"id": "sensitivity_after", "type": "markdown", "body": "**含义：**下一轮不应扩大搜索空间，而应缩小为预注册且相邻值可支持的参数家族。"},
        {"id": "coverage_intro", "type": "markdown", "body": "平衡和收益路线各缺1个稳定窗口，防守路线只覆盖1/5。这一结果使三条路线均在正式成本和压力门禁前失败。"},
        {"id": "coverage_chart", "type": "chart", "chartId": "coverage"},
        {"id": "fold_table", "type": "table", "tableId": "folds"},
        {"id": "coverage_after", "type": "markdown", "body": "**含义：**平衡/收益是稳定性近失败，防守是结构性薄弱；后者不宜被视为“差一步”。"},
        {"id": "wealth_intro", "type": "markdown", "body": "月末财富曲线用于观察全区间的路径差异。三条非锚点曲线均按全样本结果挑选，因而只能标注为样本内诊断。"},
        {"id": "wealth_chart", "type": "chart", "chartId": "wealth"},
        {"id": "wealth_after", "type": "markdown", "body": "**局限：**这些曲线不是滚动策略串联后的可投资样本外曲线，不能用来声称任何路线具备实盘资格。"},
        {"id": "cost_intro", "type": "markdown", "body": "成本诊断保留了1x、1.5x和2x的组合场景，以及费用单变量和滑点单变量的七种完整模型。"},
        {"id": "cost_chart", "type": "chart", "chartId": "combined_cost"},
        {"id": "cost_table", "type": "table", "tableId": "cost_exact"},
        {"id": "cost_after", "type": "markdown", "body": "**重要解释：**成本结果的非单调性来自100股整手、现金余额与交易路径的离散变化，不是“成本越高越好”的经济证据。在做固定交易清单反事实前，不应对非单调性作经济解读。"},
        {"id": "stress_intro", "type": "markdown", "body": "2024年一季度和2026年年初至今的压力窗口用同一日线执行口径对比诊断对照与锚点。"},
        {"id": "stress_chart", "type": "chart", "chartId": "stress_windows"},
        {"id": "stress_table", "type": "table", "tableId": "stress_exact"},
        {"id": "stress_after", "type": "markdown", "body": "**含义：**窗口表现只是压力诊断，不能修复缺失的滚动样本外策略覆盖。"},
        {"id": "crash_intro", "type": "markdown", "body": "崩盘覆盖机制的触发分母严格从60个交易日预热后开始。01—03因触发比例过高被拒绝，04—06通过机制审计。"},
        {"id": "crash_table", "type": "table", "tableId": "crash"},
        {"id": "decision_intro", "type": "markdown", "body": "路线决策表显示的候选是全样本内诊断领先者，全部带有 `diagnostic_only=true` 且因 `missing_policy_fold` 被拒绝。"},
        {"id": "decision_table", "type": "table", "tableId": "decisions"},
        {"id": "rejection_table", "type": "table", "tableId": "rejections"},
        {"id": "scope", "type": "markdown", "body": "## 范围、数据与指标定义\n\n研究区间为2020-01-01至2026-07-06，初始资金为人民币100万元，属于严格日线近似。总收益是区间末净值相对初始资金的变化；最大回撤是净值从历史峰值到后续谷值的最大降幅；Calmar为年化收益除以最大回撤绝对值。滚动覆盖分母固定为5个测试窗口。"},
        {"id": "method", "type": "markdown", "body": "## 实验设计与方法\n\n信号在T日收盘生成，在T+1第一个可交易开盘价执行；使用100股整手、当前成本、`buy_new_only=True`，ATR关闭。五个滚动窗口各用24个月训练期与后续测试期；候选只能在训练期排名并通过相邻参数稳定性检查，不允许回退候选。测试选择泄漏计数为0。"},
        {"id": "audit_intro", "type": "markdown", "body": "下表把策略结论与运行完整性分开：261次运行、同快照锚点复现、账户勾稽、现金下界、数据库不变和无泄漏检查都是“证据可用”的条件，不是“策略通过”的证明。"},
        {"id": "audit_table", "type": "table", "tableId": "audit_facts"},
        {"id": "audit_after", "type": "markdown", "body": "**含义：**历史早间快照与当前数据库的漂移已单列；策略锚点门禁仅使用同一当前快照的参考曲线。"},
        {"id": "limitations", "type": "markdown", "body": "## 局限、不确定性与稳健性\n\n本研究不是完整的聚宽分钟回放：它未建模开盘集合竞价排队优先级、盘中涨跌停排队、盘中止损、部分成交/容量和精确分钟滑点。当前数据库与历史早间产物存在快照漂移；这一漂移必须与策略表现分开报告，锚点门禁只使用同一当前快照的V2参考。账户勾稽误差、现金下界、数据库不变性和泄漏检查均通过，但不能抵消多重比较和日线执行近似的不确定性。"},
        {"id": "next_steps", "type": "markdown", "body": "## 建议的下一步\n\n- 保留 `fixed11_gradual` 作为研究锚点，不用任何本轮诊断候选替换。\n- 暂不为替代候选进入分钟级验证；先缩小为预注册参数家族，重跑同样的5个窗口。\n- 优先修复平衡/收益路线各一个缺失窗口；将防守路线视为结构性弱项。\n- 增加固定交易清单成本反事实，之后再调查分钟执行和容量。\n- 任何未来候选都必须通过同样的无泄漏、同快照、成本/压力和账户审计门禁。"},
        {"id": "questions", "type": "markdown", "body": "## 待回答问题\n\n1. 哪一个最小预注册参数家族能同时修复平衡和收益路线的缺失窗口？\n2. 在固定交易清单下，费率和滑点对经济结果的单调影响是多少？\n3. 加入开盘排队、涨跌停排队、部分成交和容量后，锚点与稳定候选的差异会如何改变？"},
    ]

    chart_map = [
        {"section": "关键发现", "chart": chart["id"], "family": chart["type"], "dataset": chart["dataset"], "claim": chart["subtitle"]}
        for chart in charts
    ]
    evidence_inventory = [
        "reports/small_cap_fixed11_gradual_next_stage/run_manifest.json",
        *[f"reports/small_cap_fixed11_gradual_next_stage/{name}" for name in ROOT_CSV_FILES],
        *[
            evidence["candidate_runs"][candidate][kind]
            for candidate in CURVE_CANDIDATES
            for kind in ("audit_path", "equity_path")
        ],
    ]
    manifest = {
        "version": 1,
        "surface": "report",
        "title": "fixed11_gradual 下一阶段严格优化研究报告",
        "description": "技术受众；严格滚动样本外、成本/压力与审计门禁的答案先行报告。",
        "generatedAt": generated_at,
        "charts": charts,
        "tables": tables,
        "cards": [],
        "sources": sources,
        "blocks": blocks,
        "notes": {"audience": "technical", "delivery_mode": "portable_html", "chart_map": chart_map, "evidence_inventory": evidence_inventory},
    }
    datasets = {
        "candidate_frontier": frontier,
        "core_one_factor_sensitivity": sensitivity,
        "one_factor_deltas": sensitivity_chart,
        "route_coverage": route_coverage,
        "fold_evidence": fold_rows,
        "monthly_wealth": _monthly_wealth(evidence),
        "combined_cost": combined_cost,
        "cost_exact": exact_cost,
        "stress_windows": stress_windows,
        "crash_audit": crash_rows,
        "route_decisions": decisions,
        "rejection_counts": _records(rejected_counts),
        "audit_facts": audit_facts,
    }
    return {
        "surface": "report",
        "manifest": manifest,
        "snapshot": {"version": 1, "generatedAt": generated_at, "status": "ready", "datasets": datasets, "accessIssues": []},
        "sources": source_queries,
    }


def main() -> None:
    artifact = build_artifact()
    OUTPUT_ARTIFACT.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    print(OUTPUT_ARTIFACT)


if __name__ == "__main__":
    main()
