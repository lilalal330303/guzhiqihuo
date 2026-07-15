from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pytest

from quant_lab.research.optimized_v3_runner import ExperimentCandidate
from quant_lab.research import optimized_v3_walkforward as wf


METRICS = {
    "total_return": 1.0,
    "annualized_return": 0.20,
    "max_drawdown": -0.20,
    "sharpe": 1.0,
    "calmar": 1.0,
    "max_underwater_calendar_days": 100,
}


def _scores(route: str, rows: list[tuple[str, dict]]) -> pd.DataFrame:
    return pd.DataFrame([
        {"candidate": name, "route": route, **METRICS, **values}
        for name, values in rows
    ])


def _gate_frames(route: str, candidate: str = "candidate") -> tuple[pd.DataFrame, pd.DataFrame]:
    folds = [f"fold_{year}" for year in range(2022, 2027)]
    policy = pd.DataFrame([
        {"fold": fold, "candidate": candidate, "route": route, **METRICS}
        for fold in folds
    ])
    anchor = policy.copy()
    anchor["candidate"] = "fixed11_gradual"
    anchor["route"] = "anchor"
    return policy, anchor


def test_default_folds_are_exact_and_non_overlapping() -> None:
    folds = wf.default_folds(pd.Timestamp("2026-07-06"))
    assert [
        (f.train_start.date().isoformat(), f.train_end.date().isoformat(),
         f.test_start.date().isoformat(), f.test_end.date().isoformat())
        for f in folds
    ] == [
        ("2020-01-01", "2021-12-31", "2022-01-01", "2022-12-31"),
        ("2021-01-01", "2022-12-31", "2023-01-01", "2023-12-31"),
        ("2022-01-01", "2023-12-31", "2024-01-01", "2024-12-31"),
        ("2023-01-01", "2024-12-31", "2025-01-01", "2025-12-31"),
        ("2024-01-01", "2025-12-31", "2026-01-01", "2026-07-06"),
    ]
    assert all(f.train_end < f.test_start for f in folds)
    assert all(left.test_end < right.test_start for left, right in zip(folds, folds[1:]))
    with pytest.raises(ValueError, match="2026-01-01"):
        wf.default_folds(pd.Timestamp("2025-12-31"))


@pytest.mark.parametrize(
    ("route", "rows", "anchor", "expected"),
    [
        ("balanced", [
            ("z", {"annualized_return": .18, "max_drawdown": -.20, "calmar": 2, "sharpe": 1}),
            ("a", {"annualized_return": .18, "max_drawdown": -.20, "calmar": 2, "sharpe": 1}),
            ("bad", {"annualized_return": .179}),
        ], {**METRICS, "annualized_return": .20, "max_drawdown": -.20}, ["a", "z"]),
        ("return", [
            ("b", {"total_return": 2, "calmar": 1}),
            ("a", {"total_return": 2, "calmar": 1}),
            ("bad", {"total_return": 9, "max_drawdown": -.321}),
        ], METRICS, ["a", "b"]),
        ("defensive", [
            ("z", {"annualized_return": .14, "max_drawdown": -.18, "calmar": 2}),
            ("a", {"annualized_return": .14, "max_drawdown": -.18, "calmar": 2}),
            ("bad", {"annualized_return": .139, "max_drawdown": -.10}),
        ], {**METRICS, "annualized_return": .20, "max_drawdown": -.20}, ["a", "z"]),
    ],
)
def test_route_selectors_are_deterministic_and_never_fallback(route, rows, anchor, expected) -> None:
    assert wf.select_training_candidates(route, _scores(route, rows), pd.Series(anchor)) == expected


def test_selection_validation_and_empty_result() -> None:
    valid = _scores("balanced", [("a", {})])
    assert wf.select_training_candidates("balanced", valid.assign(max_drawdown=-.36), pd.Series(METRICS)) == []
    with pytest.raises(ValueError, match="limit"):
        wf.select_training_candidates("balanced", valid, pd.Series(METRICS), 0)
    with pytest.raises(ValueError, match="unknown route"):
        wf.select_training_candidates("growth", valid, pd.Series(METRICS))
    with pytest.raises(ValueError, match="missing"):
        wf.select_training_candidates("balanced", valid.drop(columns="calmar"), pd.Series(METRICS))
    with pytest.raises(ValueError, match="duplicate"):
        wf.select_training_candidates("balanced", pd.concat([valid, valid]), pd.Series(METRICS))
    with pytest.raises(ValueError, match="finite"):
        wf.select_training_candidates("balanced", valid.assign(sharpe=float("nan")), pd.Series(METRICS))


def test_balanced_gate_boundaries_and_policy_labels() -> None:
    policy, anchor = _gate_frames("balanced")
    policy["annualized_return"] = .18
    policy["calmar"] = [1.1, 1.1, 1.1, .9, .9]
    policy["sharpe"] = [1.1, 1.1, 1.1, .9, .9]
    policy["max_underwater_calendar_days"] = [99, 99, 99, 101, 101]
    result = wf.evaluate_route_gates("balanced", policy, anchor)
    assert result.passed
    assert result.selected_candidate == "candidate"

    mixed = policy.copy()
    mixed.loc[1:, "candidate"] = ["b", "c", "d", "e"]
    result = wf.evaluate_route_gates("balanced", mixed, anchor)
    assert result.selected_candidate == "balanced_walk_forward_policy"

    failed = policy.assign(annualized_return=.179)
    result = wf.evaluate_route_gates("balanced", failed, anchor)
    assert not result.passed and result.selected_candidate is None
    assert "annualized_return_ratio" in result.reasons


def test_zero_anchor_annualized_return_uses_defined_ratio() -> None:
    policy, anchor = _gate_frames("balanced")
    anchor["annualized_return"] = 0.0
    policy["annualized_return"] = 0.0
    policy["calmar"] = 2.0
    policy["sharpe"] = 2.0
    policy["max_underwater_calendar_days"] = 99
    assert wf.evaluate_route_gates("balanced", policy, anchor).passed


def test_return_gate_boundaries_and_required_cost_evidence() -> None:
    policy, anchor = _gate_frames("return")
    policy["total_return"] = [1.01, 1.01, 1.01, .85, .50]
    policy["combined_max_drawdown"] = -.32
    missing = wf.evaluate_route_gates("return", policy, anchor)
    assert not missing.passed and missing.reasons == ("missing_cost_2x_scores",)

    cost = pd.DataFrame([
        {"fold": fold, "series": series, "total_return": value}
        for fold in policy["fold"]
        for series, value in (("candidate", 1.01), ("anchor", 1.0))
    ])
    assert wf.evaluate_route_gates("return", policy, anchor, cost_2x_scores=cost).passed
    bad_constant = policy.copy()
    bad_constant.loc[0, "combined_max_drawdown"] = -.31
    failed = wf.evaluate_route_gates("return", bad_constant, anchor, cost_2x_scores=cost)
    assert "combined_max_drawdown_not_constant" in failed.reasons


def test_return_gate_is_order_independent_and_exempts_only_incomplete_fold() -> None:
    policy, anchor = _gate_frames("return")
    policy["total_return"] = [1.01, 1.01, 1.01, 1.01, .50]
    policy["combined_max_drawdown"] = -.32
    cost = pd.DataFrame([
        {"fold": fold, "series": series, "total_return": value}
        for fold in policy["fold"]
        for series, value in (("candidate", 1.01), ("anchor", 1.0))
    ])
    order = [4, 0, 1, 2, 3]

    result = wf.evaluate_route_gates(
        "return", policy.iloc[order].reset_index(drop=True), anchor.iloc[order].reset_index(drop=True),
        cost_2x_scores=cost,
    )

    assert result.passed
    assert "complete_year_return_lag" not in result.reasons


def test_major_gate_failure_boundaries_are_enforced() -> None:
    balanced, anchor = _gate_frames("balanced")
    balanced["annualized_return"] = .18
    balanced["calmar"] = [1.1, 1.1, .9, .9, .9]
    balanced["sharpe"] = [1.1, 1.1, .9, .9, .9]
    balanced["max_underwater_calendar_days"] = [99, 99, 101, 101, 101]
    balanced_result = wf.evaluate_route_gates("balanced", balanced, anchor)
    assert {"calmar_sharpe_wins", "underwater_wins"}.issubset(balanced_result.reasons)

    returns, anchor = _gate_frames("return")
    returns["total_return"] = [1.01, 1.01, 1.01, .849, .50]
    returns["combined_max_drawdown"] = -.320001
    cost = pd.DataFrame([
        {"fold": fold, "series": series, "total_return": value}
        for index, fold in enumerate(returns["fold"])
        for series, value in (("candidate", 1.01 if index < 2 else .99), ("anchor", 1.0))
    ])
    return_result = wf.evaluate_route_gates("return", returns, anchor, cost_2x_scores=cost)
    assert {
        "combined_max_drawdown", "complete_year_return_lag", "cost_2x_return_wins"
    }.issubset(return_result.reasons)

    defensive, anchor = _gate_frames("defensive")
    defensive["max_drawdown"] = -.1801
    defensive["annualized_return"] = .1399
    defensive["max_underwater_calendar_days"] = [99, 99, 101, 101, 101]
    stress = pd.DataFrame({
        "window": ["2024_q1", "2026_ytd"],
        "candidate_max_drawdown": [-.20, -.10],
        "anchor_max_drawdown": [-.20, -.10],
    })
    defensive_result = wf.evaluate_route_gates(
        "defensive", defensive, anchor, stress_scores=stress
    )
    assert {
        "median_drawdown_improvement", "annualized_return_ratio", "underwater_wins"
    }.issubset(defensive_result.reasons)


def test_defensive_gate_boundaries_and_required_stress_evidence() -> None:
    policy, anchor = _gate_frames("defensive")
    policy["max_drawdown"] = -.18
    policy["annualized_return"] = .14
    policy["max_underwater_calendar_days"] = [99, 99, 99, 101, 101]
    missing = wf.evaluate_route_gates("defensive", policy, anchor)
    assert not missing.passed and missing.reasons == ("missing_stress_scores",)
    stress = pd.DataFrame({
        "window": ["2024_q1", "2026_ytd"],
        "candidate_max_drawdown": [-.20, -.10],
        "anchor_max_drawdown": [-.20, -.10],
    })
    assert wf.evaluate_route_gates("defensive", policy, anchor, stress_scores=stress).passed
    stress.loc[0, "candidate_max_drawdown"] = -.201
    failed = wf.evaluate_route_gates("defensive", policy, anchor, stress_scores=stress)
    assert not failed.passed and failed.selected_candidate is None
    assert "stress_drawdown" in failed.reasons


def test_gate_frames_require_exactly_five_matching_unique_folds() -> None:
    policy, anchor = _gate_frames("balanced")
    with pytest.raises(ValueError, match="five"):
        wf.evaluate_route_gates("balanced", policy.iloc[:4], anchor.iloc[:4])
    anchor.loc[4, "fold"] = anchor.loc[3, "fold"]
    with pytest.raises(ValueError, match="unique"):
        wf.evaluate_route_gates("balanced", policy, anchor)


def test_walk_forward_freezes_each_fold_selection_and_never_runs_rejected_candidates(monkeypatch) -> None:
    candidates = [ExperimentCandidate.anchor()]
    for route in ("balanced", "return", "defensive"):
        candidates.extend(
            replace(ExperimentCandidate.anchor(), name=f"{route}_{i}", route=route)
            for i in range(4)
        )
    folds = wf.default_folds(pd.Timestamp("2026-07-06"))
    calls = []
    selector_max_dates = []
    real_selector = wf.select_training_candidates

    def spy_selector(route, training_scores, anchor_scores, limit=3):
        selector_max_dates.append((route, training_scores["observation_date"].max()))
        return real_selector(route, training_scores, anchor_scores, limit)

    monkeypatch.setattr(wf, "select_training_candidates", spy_selector)

    def runner(*, candidate, start, end, phase, fold):
        calls.append((candidate.name, phase, fold, pd.Timestamp(start), pd.Timestamp(end)))
        index = int(candidate.name.rsplit("_", 1)[-1]) if candidate.route != "anchor" else 0
        values = {**METRICS, "observation_date": pd.Timestamp(end)}
        if phase == "train" and candidate.route != "anchor":
            values["total_return"] = values["calmar"] = 1.0 - .03 * index
            values["max_drawdown"] = -.20
        return values

    result = wf.run_walk_forward(candidates, folds, runner)
    assert len(selector_max_dates) == 15
    assert all(date <= fold.train_end for (_, date), fold in zip(selector_max_dates, [f for f in folds for _ in range(3)]))
    test_candidate_calls = [c for c in calls if c[1] == "test" and not c[0].startswith("fixed11")]
    assert len(test_candidate_calls) <= 45
    assert not any(name.endswith("_3") for name, *_ in test_candidate_calls)
    assert (result.selections["selected_on_train_end"] < result.selections["test_start"]).all()
    assert set(result.policy_scores["train_rank"]) == {1}
    assert {gate.route for gate in result.gate_results} == {"balanced", "return", "defensive"}


def test_walk_forward_does_not_fallback_when_every_candidate_misses_training_gates() -> None:
    candidates = [
        ExperimentCandidate.anchor(),
        replace(ExperimentCandidate.anchor(), name="balanced_bad", route="balanced"),
    ]

    def runner(*, candidate, start, end, phase, fold):
        values = {**METRICS, "observation_date": pd.Timestamp(end)}
        if candidate.route != "anchor":
            values["max_drawdown"] = -.40
        return values

    result = wf.run_walk_forward(
        candidates, wf.default_folds(pd.Timestamp("2026-07-06")), runner
    )

    assert result.selections.empty
    assert result.policy_scores.empty
    assert all(gate.reasons == ("missing_policy_fold",) for gate in result.gate_results)


def test_walk_forward_filters_training_only_isolated_spike_before_test_runner() -> None:
    candidates = [ExperimentCandidate.anchor()]
    candidates.extend(
        replace(ExperimentCandidate.anchor(), name=name, route="return")
        for name in ("spike", "stable_a", "stable_b", "stable_c")
    )
    calls = []

    def runner(*, candidate, start, end, phase, fold):
        calls.append((candidate.name, phase, fold, pd.Timestamp(end)))
        values = {**METRICS, "observation_date": pd.Timestamp(end)}
        if phase == "train" and candidate.name == "spike":
            values["total_return"] = 2.0
        if phase == "test" and candidate.name == "spike":
            raise AssertionError("training-isolated spike reached the test runner")
        return values

    result = wf.run_walk_forward(
        candidates, wf.default_folds(pd.Timestamp("2026-07-06")), runner
    )

    assert "spike" not in set(result.selections["candidate"])
    assert not any(name == "spike" and phase == "test" for name, phase, *_ in calls)
    assert all(
        row.observation_date <= row.selected_on_train_end
        for row in result.selections.itertuples()
    )


def test_stability_conservatively_excludes_candidate_without_two_defined_neighbors() -> None:
    candidates = [
        replace(ExperimentCandidate.anchor(), name="only_a", route="balanced"),
        replace(ExperimentCandidate.anchor(), name="only_b", route="balanced"),
    ]
    training = _scores("balanced", [("only_a", {}), ("only_b", {})])

    stable = wf.stable_training_scores("balanced", training, candidates)

    assert stable.empty
    assert wf.candidate_neighbor_map(candidates) == {
        "only_a": ("only_b",),
        "only_b": ("only_a",),
    }
