from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass

import pandas as pd

from quant_lab.research.optimized_v3_runner import ExperimentCandidate, neighbor_stability


ROUTES = ("balanced", "return", "defensive")
METRIC_COLUMNS = (
    "total_return",
    "annualized_return",
    "max_drawdown",
    "sharpe",
    "calmar",
    "max_underwater_calendar_days",
)
SCORE_COLUMNS = ("candidate", "route", *METRIC_COLUMNS)
STABILITY_METRIC = {
    "balanced": "calmar",
    "return": "total_return",
    "defensive": "max_drawdown",
}


@dataclass(frozen=True)
class WalkForwardFold:
    name: str
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp


@dataclass(frozen=True)
class RouteGateResult:
    route: str
    passed: bool
    selected_candidate: str | None
    reasons: tuple[str, ...]
    summary: dict[str, float | int]


@dataclass(frozen=True)
class WalkForwardResult:
    training_scores: pd.DataFrame
    selections: pd.DataFrame
    test_scores: pd.DataFrame
    policy_scores: pd.DataFrame
    gate_results: tuple[RouteGateResult, ...]


def default_folds(last_trade_date: pd.Timestamp) -> list[WalkForwardFold]:
    last = pd.Timestamp(last_trade_date).normalize()
    if last < pd.Timestamp("2026-01-01"):
        raise ValueError("last_trade_date must be on or after 2026-01-01")
    periods = [
        (2020, 2021, 2022, pd.Timestamp("2022-12-31")),
        (2021, 2022, 2023, pd.Timestamp("2023-12-31")),
        (2022, 2023, 2024, pd.Timestamp("2024-12-31")),
        (2023, 2024, 2025, pd.Timestamp("2025-12-31")),
        (2024, 2025, 2026, last),
    ]
    return [
        WalkForwardFold(
            name=f"fold_{test_year}",
            train_start=pd.Timestamp(f"{train_year}-01-01"),
            train_end=pd.Timestamp(f"{train_end_year}-12-31"),
            test_start=pd.Timestamp(f"{test_year}-01-01"),
            test_end=test_end,
        )
        for train_year, train_end_year, test_year, test_end in periods
    ]


def _require_route(route: str) -> None:
    if route not in ROUTES:
        raise ValueError(f"unknown route: {route!r}")


def _validate_score_frame(frame: pd.DataFrame, *, folds: bool = False) -> None:
    required = set(SCORE_COLUMNS)
    if folds:
        required.add("fold")
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"missing score columns: {missing}")
    numeric = frame.loc[:, METRIC_COLUMNS].apply(pd.to_numeric, errors="coerce")
    if not numeric.map(math.isfinite).all().all():
        raise ValueError("score metrics must be finite")


def _validate_anchor_series(anchor: pd.Series) -> None:
    missing = sorted(set(METRIC_COLUMNS).difference(anchor.index))
    if missing:
        raise ValueError(f"missing anchor metrics: {missing}")
    if not all(math.isfinite(float(anchor[column])) for column in METRIC_COLUMNS):
        raise ValueError("anchor metrics must be finite")


def select_training_candidates(
    route: str,
    training_scores: pd.DataFrame,
    anchor_scores: pd.Series,
    limit: int = 3,
) -> list[str]:
    _require_route(route)
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be an integer of at least 1")
    _validate_score_frame(training_scores)
    _validate_anchor_series(anchor_scores)
    if training_scores["candidate"].duplicated().any():
        raise ValueError("duplicate candidate names are not allowed")
    if not training_scores["route"].eq(route).all():
        raise ValueError("training score route does not match requested route")

    eligible = training_scores.loc[training_scores["max_drawdown"].ge(-0.35)].copy()
    if route == "balanced":
        eligible = eligible.loc[
            eligible["annualized_return"].ge(.90 * float(anchor_scores["annualized_return"]) - 1e-12)
            & eligible["max_drawdown"].ge(float(anchor_scores["max_drawdown"]))
        ]
        order = ["calmar", "sharpe", "max_underwater_calendar_days", "candidate"]
        ascending = [False, False, True, True]
    elif route == "return":
        eligible = eligible.loc[eligible["max_drawdown"].ge(-.32)]
        order = ["total_return", "calmar", "candidate"]
        ascending = [False, False, True]
    else:
        eligible = eligible.loc[
            eligible["annualized_return"].ge(.70 * float(anchor_scores["annualized_return"]) - 1e-12)
            & eligible["max_drawdown"].sub(float(anchor_scores["max_drawdown"])).ge(.02 - 1e-12)
        ]
        order = ["max_drawdown", "calmar", "max_underwater_calendar_days", "candidate"]
        ascending = [False, False, True, True]
    return eligible.sort_values(order, ascending=ascending, kind="mergesort")["candidate"].head(limit).tolist()


def _parameter_vector(candidate: ExperimentCandidate) -> dict[str, object]:
    vector: dict[str, object] = {}
    for component_name in (
        "core", "recovery", "stock_profile", "crash_overlay", "profit_protection"
    ):
        component = getattr(candidate, component_name)
        if component is None:
            vector[component_name] = None
            continue
        if not is_dataclass(component):
            vector[component_name] = component
            continue
        for field in fields(component):
            if field.name != "name":
                vector[f"{component_name}.{field.name}"] = getattr(component, field.name)
    return vector


def candidate_neighbor_map(
    candidate_universe: Sequence[ExperimentCandidate],
) -> dict[str, tuple[str, ...]]:
    """Return deterministic same-route peers differing in at most one parameter."""
    candidates = list(candidate_universe)
    vectors = {candidate.name: _parameter_vector(candidate) for candidate in candidates}
    result: dict[str, tuple[str, ...]] = {}
    for candidate in candidates:
        neighbors: list[str] = []
        left = vectors[candidate.name]
        for other in candidates:
            if other.name == candidate.name or other.route != candidate.route:
                continue
            right = vectors[other.name]
            keys = set(left) | set(right)
            distance = sum(left.get(key) != right.get(key) for key in keys)
            if distance <= 1:
                neighbors.append(other.name)
        result[candidate.name] = tuple(sorted(neighbors))
    return result


def stable_training_scores(
    route: str,
    training_scores: pd.DataFrame,
    candidate_universe: Sequence[ExperimentCandidate],
    *,
    tolerance: float = .10,
) -> pd.DataFrame:
    """Keep only candidates supported by two close, structurally adjacent train peers."""
    _require_route(route)
    _validate_score_frame(training_scores)
    if not training_scores["route"].eq(route).all():
        raise ValueError("training score route does not match requested route")
    neighbor_map = candidate_neighbor_map(candidate_universe)
    metric = STABILITY_METRIC[route]
    scores = training_scores.set_index("candidate")[metric].astype(float).to_dict()
    stable: list[str] = []
    for name in training_scores["candidate"]:
        available = tuple(neighbor for neighbor in neighbor_map.get(name, ()) if neighbor in scores)
        # Task 5 deliberately rejects fewer than two neighbors. At orchestration
        # level that is a conservative exclusion, not an exception or fallback.
        if len(available) >= 2 and neighbor_stability(scores, name, available, tolerance):
            stable.append(name)
    return training_scores.loc[training_scores["candidate"].isin(stable)].copy()


def _validate_gate_frames(test_scores: pd.DataFrame, anchor_scores: pd.DataFrame) -> None:
    _validate_score_frame(test_scores, folds=True)
    _validate_score_frame(anchor_scores, folds=True)
    for label, frame in (("policy", test_scores), ("anchor", anchor_scores)):
        if len(frame) != 5:
            raise ValueError(f"{label} scores must contain exactly five folds")
        if frame["fold"].duplicated().any():
            raise ValueError(f"{label} scores must contain five unique folds")
    if set(test_scores["fold"]) != set(anchor_scores["fold"]):
        raise ValueError("policy and anchor fold sets must match")


def _aligned(test_scores: pd.DataFrame, anchor_scores: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    order = test_scores["fold"].tolist()
    policy = test_scores.set_index("fold").loc[order].reset_index()
    anchor = anchor_scores.set_index("fold").loc[order].reset_index()
    return policy, anchor


def _complete_test_year_mask(policy: pd.DataFrame) -> pd.Series:
    for column in ("test_end", "period_end"):
        if column in policy:
            ends = pd.to_datetime(policy[column], errors="raise")
            return ends.dt.is_year_end
    years = policy["fold"].astype(str).str.extract(r"((?:19|20)\d{2})", expand=False)
    if years.isna().any():
        raise ValueError("return gates require test_end metadata or a four-digit year in each fold")
    numeric_years = years.astype(int)
    return numeric_years.lt(numeric_years.max())


def _annualized_ratios(candidate: pd.Series, anchor: pd.Series) -> pd.Series:
    values = []
    for candidate_value, anchor_value in zip(candidate.astype(float), anchor.astype(float)):
        if anchor_value == 0:
            values.append(1.0 if candidate_value >= 0 else float("-inf"))
        else:
            values.append(candidate_value / anchor_value)
    return pd.Series(values, dtype=float)


def _final_gate_result(
    route: str,
    policy: pd.DataFrame,
    reasons: list[str],
    summary: dict[str, float | int],
) -> RouteGateResult:
    passed = not reasons
    selected: str | None = None
    if passed:
        names = policy["candidate"].astype(str).unique()
        selected = names[0] if len(names) == 1 else f"{route}_walk_forward_policy"
    return RouteGateResult(route, passed, selected, tuple(reasons), summary)


def evaluate_route_gates(
    route: str,
    test_scores: pd.DataFrame,
    anchor_scores: pd.DataFrame,
    *,
    cost_2x_scores: pd.DataFrame | None = None,
    stress_scores: pd.DataFrame | None = None,
) -> RouteGateResult:
    _require_route(route)
    _validate_gate_frames(test_scores, anchor_scores)
    policy, anchor = _aligned(test_scores, anchor_scores)
    reasons: list[str] = []
    summary: dict[str, float | int] = {}

    ratios = _annualized_ratios(policy["annualized_return"], anchor["annualized_return"])
    median_ratio = float(ratios.median())
    summary["median_annualized_return_ratio"] = median_ratio

    if route == "balanced":
        calmar_sharpe_wins = int(
            (policy["calmar"].gt(anchor["calmar"]) & policy["sharpe"].gt(anchor["sharpe"])).sum()
        )
        underwater_wins = int(
            policy["max_underwater_calendar_days"].lt(anchor["max_underwater_calendar_days"]).sum()
        )
        median_drawdown = float(policy["max_drawdown"].median())
        anchor_median_drawdown = float(anchor["max_drawdown"].median())
        summary.update({
            "calmar_sharpe_wins": calmar_sharpe_wins,
            "median_max_drawdown": median_drawdown,
            "anchor_median_max_drawdown": anchor_median_drawdown,
            "underwater_wins": underwater_wins,
        })
        if median_ratio < .90 - 1e-12:
            reasons.append("annualized_return_ratio")
        if calmar_sharpe_wins < 3:
            reasons.append("calmar_sharpe_wins")
        if median_drawdown < anchor_median_drawdown:
            reasons.append("median_max_drawdown")
        if underwater_wins < 3:
            reasons.append("underwater_wins")

    elif route == "return":
        return_wins = int(policy["total_return"].gt(anchor["total_return"]).sum())
        summary["total_return_wins"] = return_wins
        if return_wins < 3:
            reasons.append("total_return_wins")
        if "combined_max_drawdown" not in policy:
            reasons.append("missing_combined_max_drawdown")
        else:
            combined = pd.to_numeric(policy["combined_max_drawdown"], errors="coerce")
            if not combined.map(math.isfinite).all():
                raise ValueError("combined_max_drawdown must be finite")
            if combined.nunique(dropna=False) != 1:
                reasons.append("combined_max_drawdown_not_constant")
            else:
                value = float(combined.iloc[0])
                summary["combined_max_drawdown"] = value
                if value < -.32:
                    reasons.append("combined_max_drawdown")
        complete_years = _complete_test_year_mask(policy)
        yearly_lags = policy["total_return"].sub(anchor["total_return"])
        yearly_lag_failures = int(yearly_lags.loc[complete_years].lt(-.15 - 1e-12).sum())
        summary["complete_year_lag_failures"] = yearly_lag_failures
        if yearly_lag_failures:
            reasons.append("complete_year_return_lag")
        if cost_2x_scores is None:
            reasons.append("missing_cost_2x_scores")
        else:
            required = {"fold", "series", "total_return"}
            missing = sorted(required.difference(cost_2x_scores.columns))
            if missing:
                raise ValueError(f"missing cost_2x score columns: {missing}")
            if set(cost_2x_scores["fold"]) != set(policy["fold"]):
                raise ValueError("cost_2x fold set must match policy folds")
            counts = cost_2x_scores.groupby(["fold", "series"]).size()
            expected = pd.MultiIndex.from_product([policy["fold"], ["candidate", "anchor"]])
            if set(cost_2x_scores["series"]) != {"candidate", "anchor"} or not counts.reindex(expected).eq(1).all():
                raise ValueError("cost_2x scores require one candidate and anchor row per fold")
            wide = cost_2x_scores.pivot(index="fold", columns="series", values="total_return").loc[policy["fold"]]
            if not wide.map(lambda value: math.isfinite(float(value))).all().all():
                raise ValueError("cost_2x returns must be finite")
            cost_wins = int(wide["candidate"].gt(wide["anchor"]).sum())
            summary["cost_2x_return_wins"] = cost_wins
            if cost_wins < 3:
                reasons.append("cost_2x_return_wins")

    else:
        drawdown_improvement = float(
            policy["max_drawdown"].sub(anchor["max_drawdown"]).median()
        )
        underwater_wins = int(
            policy["max_underwater_calendar_days"].lt(anchor["max_underwater_calendar_days"]).sum()
        )
        summary.update({
            "median_drawdown_improvement": drawdown_improvement,
            "underwater_wins": underwater_wins,
        })
        if drawdown_improvement < .02 - 1e-12:
            reasons.append("median_drawdown_improvement")
        if median_ratio < .70 - 1e-12:
            reasons.append("annualized_return_ratio")
        if underwater_wins < 3:
            reasons.append("underwater_wins")
        if stress_scores is None:
            reasons.append("missing_stress_scores")
        else:
            required = {"window", "candidate_max_drawdown", "anchor_max_drawdown"}
            missing = sorted(required.difference(stress_scores.columns))
            if missing:
                raise ValueError(f"missing stress score columns: {missing}")
            if len(stress_scores) != 2 or set(stress_scores["window"]) != {"2024_q1", "2026_ytd"}:
                raise ValueError("stress scores require exactly 2024_q1 and 2026_ytd")
            numeric = stress_scores[["candidate_max_drawdown", "anchor_max_drawdown"]].apply(pd.to_numeric, errors="coerce")
            if not numeric.map(math.isfinite).all().all():
                raise ValueError("stress drawdowns must be finite")
            stress_passes = int(numeric["candidate_max_drawdown"].ge(numeric["anchor_max_drawdown"]).sum())
            summary["stress_windows_passed"] = stress_passes
            if stress_passes != 2:
                reasons.append("stress_drawdown")
    return _final_gate_result(route, policy, reasons, summary)


def _score_row(
    result: Mapping[str, object], candidate: ExperimentCandidate, fold: WalkForwardFold,
    phase: str, start: pd.Timestamp, end: pd.Timestamp,
) -> dict[str, object]:
    row = dict(result)
    row.update({
        "candidate": candidate.name,
        "route": candidate.route,
        "fold": fold.name,
        "phase": phase,
        "period_start": pd.Timestamp(start),
        "period_end": pd.Timestamp(end),
    })
    row.setdefault("observation_date", pd.Timestamp(end))
    frame = pd.DataFrame([row])
    _validate_score_frame(frame, folds=True)
    observation = pd.to_datetime(frame["observation_date"], errors="raise")
    if observation.max() > pd.Timestamp(end):
        raise ValueError(f"{phase} result contains an observation after its period end")
    return row


def run_walk_forward(
    candidate_universe: Sequence[ExperimentCandidate],
    folds: Sequence[WalkForwardFold],
    runner: Callable[..., Mapping[str, object]],
) -> WalkForwardResult:
    candidates = list(candidate_universe)
    anchors = [candidate for candidate in candidates if candidate.route == "anchor"]
    if len(anchors) != 1:
        raise ValueError("candidate_universe must contain exactly one anchor")
    if len({candidate.name for candidate in candidates}) != len(candidates):
        raise ValueError("candidate names must be unique")
    if any(candidate.route not in (*ROUTES, "anchor") for candidate in candidates):
        raise ValueError("candidate_universe contains an unknown route")
    fold_list = list(folds)
    if len({fold.name for fold in fold_list}) != len(fold_list):
        raise ValueError("fold names must be unique")
    if any(fold.train_end >= fold.test_start for fold in fold_list):
        raise ValueError("each train end must precede its test start")
    ordered_tests = sorted(fold_list, key=lambda fold: fold.test_start)
    if any(left.test_end >= right.test_start for left, right in zip(ordered_tests, ordered_tests[1:])):
        raise ValueError("test periods must not overlap")

    anchor = anchors[0]
    training_rows: list[dict[str, object]] = []
    selection_rows: list[dict[str, object]] = []
    test_rows: list[dict[str, object]] = []
    policy_rows: list[dict[str, object]] = []

    for fold in fold_list:
        fold_training: list[dict[str, object]] = []
        for candidate in candidates:
            result = runner(candidate=candidate, start=fold.train_start, end=fold.train_end,
                            phase="train", fold=fold.name)
            row = _score_row(result, candidate, fold, "train", fold.train_start, fold.train_end)
            fold_training.append(row)
            training_rows.append(row)
        train_frame = pd.DataFrame(fold_training)
        anchor_score = train_frame.loc[train_frame["candidate"].eq(anchor.name)].iloc[0]

        selected_by_route: dict[str, list[str]] = {}
        for route in ROUTES:
            route_frame = train_frame.loc[train_frame["route"].eq(route)].copy()
            stable_frame = stable_training_scores(route, route_frame, candidates)
            selected = select_training_candidates(route, stable_frame, anchor_score, limit=3)
            selected_by_route[route] = selected
            for rank, name in enumerate(selected, start=1):
                selected_train_row = stable_frame.loc[stable_frame["candidate"].eq(name)].iloc[0]
                selection_rows.append({
                    "fold": fold.name,
                    "route": route,
                    "candidate": name,
                    "train_rank": rank,
                    "selected_on_train_end": fold.train_end,
                    "test_start": fold.test_start,
                    "observation_date": pd.Timestamp(selected_train_row["observation_date"]),
                })

        anchor_test_result = runner(candidate=anchor, start=fold.test_start, end=fold.test_end,
                                    phase="test", fold=fold.name)
        anchor_test_row = _score_row(anchor_test_result, anchor, fold, "test", fold.test_start, fold.test_end)
        test_rows.append(anchor_test_row)
        by_name = {candidate.name: candidate for candidate in candidates}
        for route in ROUTES:
            for rank, name in enumerate(selected_by_route[route], start=1):
                candidate = by_name[name]
                result = runner(candidate=candidate, start=fold.test_start, end=fold.test_end,
                                phase="test", fold=fold.name)
                row = _score_row(result, candidate, fold, "test", fold.test_start, fold.test_end)
                row["train_rank"] = rank
                row["selected_on_train_end"] = fold.train_end
                test_rows.append(row)
                if rank == 1:
                    policy_rows.append(row.copy())

    training_scores = pd.DataFrame(training_rows)
    selections = pd.DataFrame(selection_rows, columns=[
        "fold", "route", "candidate", "train_rank",
        "selected_on_train_end", "test_start", "observation_date",
    ])
    test_scores = pd.DataFrame(test_rows)
    policy_scores = (
        pd.DataFrame(policy_rows)
        if policy_rows
        else pd.DataFrame(columns=[
            *SCORE_COLUMNS, "fold", "phase", "period_start", "period_end",
            "observation_date", "train_rank", "selected_on_train_end",
        ])
    )
    gate_results: list[RouteGateResult] = []
    anchor_tests = test_scores.loc[test_scores["route"].eq("anchor")]
    for route in ROUTES:
        route_policy = policy_scores.loc[policy_scores["route"].eq(route)]
        if len(route_policy) != 5:
            gate_results.append(RouteGateResult(
                route, False, None, ("missing_policy_fold",), {"policy_fold_count": len(route_policy)}
            ))
            continue
        gate_results.append(evaluate_route_gates(route, route_policy, anchor_tests))
    return WalkForwardResult(
        training_scores, selections, test_scores, policy_scores, tuple(gate_results)
    )
