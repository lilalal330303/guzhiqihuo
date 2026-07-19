import ast
from pathlib import Path
import runpy
import sys
import types

import numpy as np
import pandas as pd
import pytest


def load_strategy():
    missing = object()
    previous_jqdata = sys.modules.get("jqdata", missing)
    jqdata_stub = types.ModuleType("jqdata")
    sys.modules["jqdata"] = jqdata_stub
    try:
        namespace = runpy.run_path(
            Path("reports/joinquant_size_style_rotation_v22_original_compatible.py"),
            run_name="joinquant_size_style_rotation_v22_original_compatible_test",
        )
        return namespace["select_original_branch"].__globals__
    finally:
        if previous_jqdata is missing:
            sys.modules.pop("jqdata", None)
        else:
            sys.modules["jqdata"] = previous_jqdata


class QueryFieldStub:
    def __gt__(self, other):
        return ("gt", other)

    def in_(self, values):
        return ("in", tuple(values))

    def asc(self):
        return ("asc",)


class QueryStub:
    def filter(self, *conditions):
        return self

    def order_by(self, *fields):
        return self


def test_strategy_calls_use_explicit_historical_dates():
    source = Path(
        "reports/joinquant_size_style_rotation_v22_original_compatible.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {"get_fundamentals", "get_index_stocks"}
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in names
    ]

    assert calls
    assert all(
        any(keyword.arg == "date" for keyword in call.keywords)
        for call in calls
    )


def test_style_signal_requests_constituents_and_prices_at_previous_date():
    ns = load_strategy()
    cutoff = pd.Timestamp("2024-01-31").date()
    requests = []
    params = dict(ns["DEFAULT_PARAMS"])
    params["style_window"] = 2
    ns["g"] = types.SimpleNamespace(params=params)
    ns["log"] = types.SimpleNamespace(warn=lambda *args: None)

    def get_index_stocks(index_code, **kwargs):
        requests.append(("index", index_code, kwargs))
        return ["A", "B"]

    def get_price(stocks, **kwargs):
        requests.append(("price", stocks, kwargs))
        return pd.DataFrame(
            {"A": [100.0, 110.0], "B": [200.0, 220.0]},
            index=pd.to_datetime(["2024-01-30", "2024-01-31"]),
        )

    ns["get_index_stocks"] = get_index_stocks
    ns["get_price"] = get_price
    context = types.SimpleNamespace(previous_date=cutoff)

    result = ns["get_style_mean_return"](context, "INDEX")

    assert result == pytest.approx(0.10)
    assert requests == [
        ("index", "INDEX", {"date": cutoff}),
        (
            "price",
            ["A", "B"],
            {
                "panel": False,
                "end_date": cutoff,
                "frequency": "daily",
                "fields": ["close"],
                "count": 2,
            },
        ),
    ]


def test_original_ratio_preserves_branch_direction():
    ns = load_strategy()
    assert ns["select_original_branch"](0.30, 0.20, 1.2) == "BIG"
    assert ns["select_original_branch"](0.24, 0.20, 1.2) == "SMALL"


def test_original_ratio_rejects_invalid_denominator():
    ns = load_strategy()
    assert ns["select_original_branch"](0.30, 0.0, 1.2) is None


def test_cross_sectional_mean_return_ignores_missing_values():
    ns = load_strategy()
    frame = pd.DataFrame(
        [[100.0, 100.0], [110.0, np.nan]],
        columns=["A", "B"],
    )
    result = ns["safe_mean_return"](frame, min_samples=1, winsorize=False)
    assert result == pytest.approx(0.10)


def test_cross_sectional_mean_return_returns_none_when_sample_is_too_small():
    ns = load_strategy()
    frame = pd.DataFrame([[100.0, np.nan], [110.0, np.nan]], columns=["A", "B"])
    assert ns["safe_mean_return"](frame, min_samples=2, winsorize=False) is None


def test_existing_holdings_are_kept_in_ranked_target():
    ns = load_strategy()
    assert ns["merge_target_with_holdings"](
        ["A"], ["B", "A", "C"], 2
    ) == ["A", "B"]


def test_default_parameters_are_original_compatible():
    ns = load_strategy()
    assert ns["DEFAULT_PARAMS"] == {
        "stock_num": 5,
        "style_window": 20,
        "ratio_threshold": 1.2,
        "min_style_samples": 2,
        "max_price": 10.0,
        "min_listing_days": 375,
        "recent_limit_days": 40,
        "winsorize_returns": False,
        "market_guard": False,
        "market_guard_ma": 60,
        "slippage": 0.0,
        "use_historical_constituents": True,
        "big_use_filtered_pool": False,
    }


def test_market_guard_is_disabled_by_default():
    ns = load_strategy()
    assert ns["DEFAULT_PARAMS"]["market_guard"] is False


def test_merge_target_does_not_duplicate_existing_holdings():
    ns = load_strategy()
    assert ns["merge_target_with_holdings"](
        ["A", "A"], ["A", "B", "C"], 3
    ) == ["A", "B", "C"]


def test_protected_holding_counts_toward_target_size():
    ns = load_strategy()
    assert ns["merge_target_with_protected_holdings"](
        ["A", "B"], ["C", "D", "E"], ["A"], 3
    ) == ["A", "C", "D"]


def test_small_candidate_blacklist_excludes_recent_limit_up_holdings():
    ns = load_strategy()
    assert ns["_exclude_recent_limit_up_holdings"](
        ["A", "B", "C"], ["B", "D"], ["B", "E"]
    ) == ["A", "C"]


def test_small_candidates_limit_ranked_universe_so_sixth_holding_is_replaced():
    ns = load_strategy()
    ranked = ["A", "B", "C", "D", "E", "F", "G"]
    fundamentals = iter(
        [
            pd.DataFrame({"code": ranked}),
            pd.DataFrame({"code": ranked}),
        ]
    )
    field = QueryFieldStub()
    ns["g"] = types.SimpleNamespace(
        params={"stock_num": 5, "recent_limit_days": 40}
    )
    ns["valuation"] = types.SimpleNamespace(code=field, market_cap=field)
    ns["indicator"] = types.SimpleNamespace(roe=field, roa=field)
    ns["query"] = lambda *fields: QueryStub()
    ns["get_fundamentals"] = lambda *args, **kwargs: next(fundamentals)
    ns["_full_market_pool"] = lambda context: (ranked, ranked)
    ns["_filter_high_price"] = lambda context, stocks: stocks
    ns["recent_limit_up_stocks"] = (
        lambda context, stocks, days: ["C"]
    )
    context = types.SimpleNamespace(
        previous_date=pd.Timestamp("2024-01-31").date(),
        portfolio=types.SimpleNamespace(
            positions={"C": object(), "G": object()}
        ),
    )

    candidates = ns["small_candidates"](context)
    target = ns["merge_target_with_protected_holdings"](
        list(context.portfolio.positions), candidates, [], 5
    )

    assert candidates == ["A", "B", "D", "E", "F"]
    assert target == ["A", "B", "D", "E", "F"]


def test_style_signal_returns_none_when_constituent_api_fails():
    ns = load_strategy()
    warnings = []

    def fail_constituents(*args, **kwargs):
        raise RuntimeError("constituent API unavailable")

    ns["get_index_stocks"] = fail_constituents
    ns["log"] = types.SimpleNamespace(warn=lambda *args: warnings.append(args))
    context = types.SimpleNamespace(previous_date=pd.Timestamp("2024-01-02").date())

    assert ns["get_style_mean_return"](context, "INDEX") is None
    assert warnings


def test_style_signal_returns_none_when_panel_fallback_fails():
    ns = load_strategy()
    warnings = []
    calls = []

    def fail_price_fetch(*args, **kwargs):
        calls.append(kwargs)
        if "panel" in kwargs:
            raise TypeError("unexpected keyword argument 'panel'")
        raise RuntimeError("fallback API unavailable")

    ns["get_index_stocks"] = lambda *args, **kwargs: ["A", "B"]
    ns["get_price"] = fail_price_fetch
    ns["log"] = types.SimpleNamespace(warn=lambda *args: warnings.append(args))
    context = types.SimpleNamespace(previous_date=pd.Timestamp("2024-01-02").date())

    assert ns["get_style_mean_return"](context, "INDEX") is None
    assert len(calls) == 2
    assert warnings


def test_style_signal_returns_none_when_price_shape_normalization_fails():
    ns = load_strategy()
    warnings = []

    def fail_normalization(raw_prices):
        raise ValueError("unsupported price shape")

    ns["get_index_stocks"] = lambda *args, **kwargs: ["A", "B"]
    ns["get_price"] = lambda *args, **kwargs: object()
    ns["safe_close_frame"] = fail_normalization
    ns["log"] = types.SimpleNamespace(warn=lambda *args: warnings.append(args))
    context = types.SimpleNamespace(previous_date=pd.Timestamp("2024-01-02").date())

    assert ns["get_style_mean_return"](context, "INDEX") is None
    assert warnings


def test_style_signal_rejects_twenty_rows_with_only_nineteen_unique_dates():
    ns = load_strategy()
    cutoff = pd.Timestamp("2024-01-31").date()
    dates = list(pd.date_range("2024-01-01", periods=19))
    raw = pd.DataFrame(
        {
            "A": np.linspace(100.0, 119.0, 20),
            "B": np.linspace(200.0, 219.0, 20),
        },
        index=pd.DatetimeIndex(dates + [dates[-1]]),
    )
    requests = []
    ns["g"] = types.SimpleNamespace(params=dict(ns["DEFAULT_PARAMS"]))
    ns["get_index_stocks"] = lambda *args, **kwargs: ["A", "B"]

    def get_price(*args, **kwargs):
        requests.append(kwargs)
        return raw

    ns["get_price"] = get_price
    ns["log"] = types.SimpleNamespace(warn=lambda *args: None)
    context = types.SimpleNamespace(previous_date=cutoff)

    assert ns["get_style_mean_return"](context, "INDEX") is None
    assert requests == [
        {
            "end_date": cutoff,
            "frequency": "daily",
            "fields": ["close"],
            "count": 20,
            "panel": False,
        }
    ]


def test_style_signal_uses_only_the_trailing_configured_window():
    ns = load_strategy()
    raw = pd.DataFrame(
        {
            "A": [50.0, 100.0, 110.0, 121.0],
            "B": [100.0, 100.0, 100.0, 100.0],
        },
        index=pd.date_range("2024-01-01", periods=4),
    )
    params = dict(ns["DEFAULT_PARAMS"])
    params["style_window"] = 3
    ns["g"] = types.SimpleNamespace(params=params)
    ns["get_index_stocks"] = lambda *args, **kwargs: ["A", "B"]
    ns["get_price"] = lambda *args, **kwargs: raw
    ns["log"] = types.SimpleNamespace(warn=lambda *args: None)
    context = types.SimpleNamespace(
        previous_date=pd.Timestamp("2024-01-31").date()
    )

    result = ns["get_style_mean_return"](context, "INDEX")

    assert result == pytest.approx(0.105)


@pytest.mark.parametrize(
    "index",
    [
        pd.MultiIndex.from_tuples(
            [("A", "2024-01-02"), ("B", "2024-01-02")],
            names=["code", "time"],
        ),
        pd.MultiIndex.from_tuples(
            [("2024-01-02", "A"), ("2024-01-02", "B")],
            names=[None, None],
        ),
    ],
    ids=["named-code-level", "unnamed-time-code-levels"],
)
def test_prepare_stock_list_extracts_limit_up_codes_from_multiindex(index):
    ns = load_strategy()
    frame = pd.DataFrame(
        {"close": [10.0, 9.0], "high_limit": [10.0, 10.0]},
        index=index,
    )
    runtime = types.SimpleNamespace(stock_list_ready=False)
    ns["g"] = runtime
    ns["get_price"] = lambda *args, **kwargs: frame
    context = types.SimpleNamespace(
        previous_date=pd.Timestamp("2024-01-02").date(),
        portfolio=types.SimpleNamespace(positions={"A": object(), "B": object()}),
    )

    ns["prepare_stock_list"](context)

    assert runtime.hold_list == ["A", "B"]
    assert runtime.yesterday_HL_list == ["A"]
    assert runtime.stock_list_ready is True


def test_prepare_stock_list_failure_preserves_protection_and_marks_not_ready():
    ns = load_strategy()
    runtime = types.SimpleNamespace(
        hold_list=["OLD"],
        yesterday_HL_list=["A"],
        stock_list_ready=True,
    )
    ns["g"] = runtime

    def fail_price_fetch(*args, **kwargs):
        raise RuntimeError("daily prices unavailable")

    ns["get_price"] = fail_price_fetch
    ns["log"] = types.SimpleNamespace(warn=lambda *args: None)
    context = types.SimpleNamespace(
        previous_date=pd.Timestamp("2024-01-02").date(),
        portfolio=types.SimpleNamespace(positions={"A": object()}),
    )

    ns["prepare_stock_list"](context)

    assert runtime.hold_list == ["A"]
    assert runtime.yesterday_HL_list == ["A"]
    assert runtime.stock_list_ready is False


def test_prepare_stock_list_marks_not_ready_before_failed_holdings_snapshot():
    ns = load_strategy()
    readiness_at_snapshot = []
    warnings = []
    runtime = types.SimpleNamespace(
        hold_list=["OLD"],
        yesterday_HL_list=["OLD"],
        stock_list_ready=True,
    )
    ns["g"] = runtime
    ns["log"] = types.SimpleNamespace(warn=lambda *args: warnings.append(args))
    ns["get_price"] = lambda *args, **kwargs: pytest.fail(
        "failed holdings snapshot must not fetch prices"
    )

    class FailingPortfolio:
        @property
        def positions(self):
            readiness_at_snapshot.append(runtime.stock_list_ready)
            raise RuntimeError("positions unavailable")

    context = types.SimpleNamespace(portfolio=FailingPortfolio())

    ns["prepare_stock_list"](context)

    assert readiness_at_snapshot == [False]
    assert runtime.hold_list == ["OLD"]
    assert runtime.yesterday_HL_list == ["OLD"]
    assert runtime.stock_list_ready is False
    assert warnings


@pytest.mark.parametrize(
    "codes",
    [
        ["A", "A"],
        ["A"],
        ["A", "C"],
    ],
    ids=["duplicate", "missing", "unexpected"],
)
def test_prepare_stock_list_rejects_non_bijective_rows(codes):
    ns = load_strategy()
    frame = pd.DataFrame(
        {
            "code": codes,
            "close": [10.0] * len(codes),
            "high_limit": [10.0] * len(codes),
        }
    )
    runtime = types.SimpleNamespace(
        hold_list=["OLD"],
        yesterday_HL_list=["OLD"],
        stock_list_ready=True,
    )
    ns["g"] = runtime
    ns["get_price"] = lambda *args, **kwargs: frame
    context = types.SimpleNamespace(
        previous_date=pd.Timestamp("2024-01-02").date(),
        portfolio=types.SimpleNamespace(
            positions={"A": object(), "B": object()}
        ),
    )

    ns["prepare_stock_list"](context)

    assert runtime.hold_list == ["A", "B"]
    assert runtime.yesterday_HL_list == ["OLD"]
    assert runtime.stock_list_ready is False


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("close", np.nan),
        ("close", np.inf),
        ("close", -np.inf),
        ("close", 0.0),
        ("close", -1.0),
        ("high_limit", np.nan),
        ("high_limit", np.inf),
        ("high_limit", -np.inf),
        ("high_limit", 0.0),
        ("high_limit", -1.0),
    ],
    ids=[
        "close-nan",
        "close-positive-inf",
        "close-negative-inf",
        "close-zero",
        "close-negative",
        "high-limit-nan",
        "high-limit-positive-inf",
        "high-limit-negative-inf",
        "high-limit-zero",
        "high-limit-negative",
    ],
)
def test_prepare_stock_list_rejects_non_positive_or_non_finite_prices(
    field, invalid_value
):
    ns = load_strategy()
    values = {
        "code": ["A", "B"],
        "close": [10.0, 9.0],
        "high_limit": [10.0, 10.0],
    }
    values[field][0] = invalid_value
    frame = pd.DataFrame(values)
    runtime = types.SimpleNamespace(
        hold_list=["OLD"],
        yesterday_HL_list=["OLD"],
        stock_list_ready=True,
    )
    ns["g"] = runtime
    ns["get_price"] = lambda *args, **kwargs: frame
    context = types.SimpleNamespace(
        previous_date=pd.Timestamp("2024-01-02").date(),
        portfolio=types.SimpleNamespace(
            positions={"A": object(), "B": object()}
        ),
    )

    ns["prepare_stock_list"](context)

    assert runtime.hold_list == ["A", "B"]
    assert runtime.yesterday_HL_list == ["OLD"]
    assert runtime.stock_list_ready is False


def test_prepare_stock_list_without_holdings_is_ready():
    ns = load_strategy()
    runtime = types.SimpleNamespace(
        hold_list=["OLD"],
        yesterday_HL_list=["OLD"],
        stock_list_ready=False,
    )
    ns["g"] = runtime
    ns["get_price"] = lambda *args, **kwargs: pytest.fail(
        "empty holdings must not fetch prices"
    )
    context = types.SimpleNamespace(
        previous_date=pd.Timestamp("2024-01-02").date(),
        portfolio=types.SimpleNamespace(positions={}),
    )

    ns["prepare_stock_list"](context)

    assert runtime.hold_list == []
    assert runtime.yesterday_HL_list == []
    assert runtime.stock_list_ready is True


def test_monthly_adjustment_keeps_holdings_when_preparation_is_not_ready():
    ns = load_strategy()
    orders = []
    runtime = types.SimpleNamespace(
        params=dict(ns["DEFAULT_PARAMS"]),
        yesterday_HL_list=[],
        stock_list_ready=False,
    )
    ns["g"] = runtime
    ns["log"] = types.SimpleNamespace(
        warn=lambda *args: None,
        info=lambda *args: None,
    )
    ns["get_style_mean_return"] = (
        lambda context, index_code: 0.10
        if index_code == ns["INDEX_2000"]
        else 0.20
    )
    ns["get_candidates"] = lambda context, branch: ["B", "C", "D", "E", "F"]
    ns["safe_order_target_value"] = (
        lambda stock, value: orders.append((stock, value))
    )
    context = types.SimpleNamespace(
        portfolio=types.SimpleNamespace(
            positions={"A": types.SimpleNamespace(total_amount=100)},
            available_cash=10000.0,
        )
    )

    ns["monthly_adjustment"](context)

    assert orders == []


def test_monthly_adjustment_keeps_empty_portfolio_when_preparation_is_not_ready():
    ns = load_strategy()
    downstream_calls = []
    orders = []
    ns["g"] = types.SimpleNamespace(
        params=dict(ns["DEFAULT_PARAMS"]),
        yesterday_HL_list=[],
        stock_list_ready=False,
    )
    ns["log"] = types.SimpleNamespace(
        warn=lambda *args: None,
        info=lambda *args: None,
    )

    def style_return(context, index_code):
        downstream_calls.append(("style", index_code))
        return 0.10 if index_code == ns["INDEX_2000"] else 0.20

    def candidates(context, branch):
        downstream_calls.append(("candidates", branch))
        return ["A"]

    ns["get_style_mean_return"] = style_return
    ns["get_candidates"] = candidates
    ns["safe_order_target_value"] = (
        lambda stock, value: orders.append((stock, value))
    )
    context = types.SimpleNamespace(
        portfolio=types.SimpleNamespace(
            positions={},
            available_cash=10000.0,
        )
    )

    ns["monthly_adjustment"](context)

    assert downstream_calls == []
    assert orders == []


def test_monthly_adjustment_catches_candidate_errors_without_orders():
    ns = load_strategy()
    orders = []
    runtime = types.SimpleNamespace(
        params=dict(ns["DEFAULT_PARAMS"]),
        yesterday_HL_list=[],
        stock_list_ready=True,
    )
    ns["g"] = runtime
    ns["log"] = types.SimpleNamespace(
        warn=lambda *args: None,
        info=lambda *args: None,
    )
    ns["get_style_mean_return"] = (
        lambda context, index_code: 0.10
        if index_code == ns["INDEX_2000"]
        else 0.20
    )

    def fail_candidates(context, branch):
        raise RuntimeError("fundamentals unavailable")

    ns["get_candidates"] = fail_candidates
    ns["safe_order_target_value"] = (
        lambda stock, value: orders.append((stock, value))
    )
    context = types.SimpleNamespace(
        portfolio=types.SimpleNamespace(
            positions={"A": types.SimpleNamespace(total_amount=100)},
            available_cash=10000.0,
        )
    )

    ns["monthly_adjustment"](context)

    assert orders == []


def test_check_limit_up_ignores_stale_protection_when_preparation_is_not_ready():
    ns = load_strategy()
    price_requests = []
    orders = []
    ns["g"] = types.SimpleNamespace(
        yesterday_HL_list=["A"],
        stock_list_ready=False,
    )
    ns["log"] = types.SimpleNamespace(warn=lambda *args: None)

    def get_price(stock, **kwargs):
        price_requests.append((stock, kwargs))
        return pd.DataFrame({"close": [9.0], "high_limit": [10.0]})

    ns["get_price"] = get_price
    ns["safe_order_target_value"] = (
        lambda stock, value: orders.append((stock, value))
    )
    context = types.SimpleNamespace(
        current_dt=pd.Timestamp("2024-01-02 14:00"),
        portfolio=types.SimpleNamespace(positions={"A": object()}),
    )

    ns["check_limit_up"](context)

    assert price_requests == []
    assert orders == []


def test_safe_close_frame_pivots_panel_false_multi_stock_frame():
    ns = load_strategy()
    raw = pd.DataFrame(
        {
            "code": ["A", "B", "A", "B"],
            "close": [100.0, 200.0, 110.0, 220.0],
        },
        index=pd.to_datetime(
            ["2024-01-01", "2024-01-01", "2024-01-02", "2024-01-02"]
        ),
    )

    result = ns["safe_close_frame"](raw)

    assert list(result.columns) == ["A", "B"]
    assert result.iloc[-1].to_dict() == {"A": 110.0, "B": 220.0}


def test_safe_close_frame_preserves_explicit_date_column_for_single_close():
    ns = load_strategy()
    raw = pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-02"],
            "close": [100.0, 110.0],
        }
    )

    result = ns["safe_close_frame"](raw)

    assert list(result.index) == [
        pd.Timestamp("2024-01-01"),
        pd.Timestamp("2024-01-02"),
    ]
    assert result["close"].tolist() == [100.0, 110.0]


@pytest.mark.parametrize(
    ("index", "case"),
    [
        (
            pd.MultiIndex.from_tuples(
                [
                    ("2024-01-01", "A"),
                    ("2024-01-01", "B"),
                    ("2024-01-02", "A"),
                    ("2024-01-02", "B"),
                ],
                names=["time", "code"],
            ),
            "named-time-code",
        ),
        (
            pd.MultiIndex.from_tuples(
                [
                    ("A", "2024-01-01"),
                    ("B", "2024-01-01"),
                    ("A", "2024-01-02"),
                    ("B", "2024-01-02"),
                ],
                names=["code", "time"],
            ),
            "named-code-time",
        ),
        (
            pd.MultiIndex.from_tuples(
                [
                    ("2024-01-01", "A"),
                    ("2024-01-01", "B"),
                    ("2024-01-02", "A"),
                    ("2024-01-02", "B"),
                ],
                names=[None, None],
            ),
            "unnamed-time-code",
        ),
        (
            pd.MultiIndex.from_tuples(
                [
                    ("A", "2024-01-01"),
                    ("B", "2024-01-01"),
                    ("A", "2024-01-02"),
                    ("B", "2024-01-02"),
                ],
                names=[None, None],
            ),
            "unnamed-code-time",
        ),
    ],
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_safe_close_frame_pivots_multiindex_close_only_frame(index, case):
    ns = load_strategy()
    raw = pd.DataFrame(
        {"close": [100.0, 200.0, 110.0, 220.0]},
        index=index,
    )

    result = ns["safe_close_frame"](raw)

    assert result is not None, case
    assert list(result.index) == [
        pd.Timestamp("2024-01-01"),
        pd.Timestamp("2024-01-02"),
    ]
    assert list(result.columns) == ["A", "B"]
    assert result.iloc[-1].to_dict() == {"A": 110.0, "B": 220.0}


@pytest.mark.parametrize(
    "columns",
    [
        pd.MultiIndex.from_tuples(
            [("close", "A"), ("close", "B")],
            names=["field", "code"],
        ),
        pd.MultiIndex.from_tuples(
            [("A", "close"), ("B", "close")],
            names=["code", "field"],
        ),
        pd.MultiIndex.from_tuples(
            [("close", "A"), ("close", "B")],
            names=[None, None],
        ),
        pd.MultiIndex.from_tuples(
            [("A", "close"), ("B", "close")],
            names=[None, None],
        ),
    ],
    ids=[
        "named-close-code",
        "named-code-close",
        "unnamed-close-code",
        "unnamed-code-close",
    ],
)
def test_safe_close_frame_accepts_close_in_either_multiindex_column_level(columns):
    ns = load_strategy()
    raw = pd.DataFrame(
        [[100.0, 200.0], [110.0, 220.0]],
        index=pd.to_datetime(["2024-01-01", "2024-01-02"]),
        columns=columns,
    )

    result = ns["safe_close_frame"](raw)

    assert result is not None
    assert list(result.columns) == ["A", "B"]
    assert result.iloc[-1].to_dict() == {"A": 110.0, "B": 220.0}
