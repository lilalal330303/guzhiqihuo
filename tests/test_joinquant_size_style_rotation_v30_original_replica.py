import ast
from datetime import date, datetime
import importlib.util
from pathlib import Path
import sys
import types

import pandas as pd
import pytest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "reports"
    / "joinquant_size_style_rotation_v30_original_replica.py"
)
README = (
    Path(__file__).resolve().parents[1]
    / "reports"
    / "joinquant_size_style_rotation_v30_original_replica_readme.md"
)


class _Field:
    def __init__(self, name, captured):
        self.name = name
        self.captured = captured

    def in_(self, values):
        self.captured.setdefault("in_values", {})[self.name] = list(values)
        return self

    def between(self, _lower, _upper):
        return self

    def asc(self):
        return self

    def desc(self):
        return self

    def __gt__(self, _value):
        return self

    def __lt__(self, _value):
        return self


class _Query:
    def filter(self, *_conditions):
        return self

    def order_by(self, *_fields):
        return self

    def limit(self, _count):
        return self


def _install_fundamental_query_stubs(module):
    captured = {}
    module.valuation = types.SimpleNamespace(
        code=_Field("valuation.code", captured),
        pe_ratio_lyr=_Field("valuation.pe_ratio_lyr", captured),
        ps_ratio=_Field("valuation.ps_ratio", captured),
        pcf_ratio=_Field("valuation.pcf_ratio", captured),
        market_cap=_Field("valuation.market_cap", captured),
    )
    module.indicator = types.SimpleNamespace(
        roe=_Field("indicator.roe", captured),
        roa=_Field("indicator.roa", captured),
        eps=_Field("indicator.eps", captured),
        net_profit_margin=_Field("indicator.net_profit_margin", captured),
        gross_profit_margin=_Field("indicator.gross_profit_margin", captured),
        inc_revenue_year_on_year=_Field(
            "indicator.inc_revenue_year_on_year", captured
        ),
    )
    module.query = lambda *_fields: _Query()
    return captured


@pytest.fixture
def module():
    missing = object()
    previous_jqdata = sys.modules.get("jqdata", missing)
    jqdata_stub = types.ModuleType("jqdata")
    sys.modules["jqdata"] = jqdata_stub

    module_name = "joinquant_size_style_rotation_v30_original_replica_test"
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT)
    loaded_module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = loaded_module
    try:
        spec.loader.exec_module(loaded_module)
        yield loaded_module
    finally:
        if hasattr(loaded_module, "RUN_MODE"):
            loaded_module.RUN_MODE = "ORIGINAL_REPLICA"
        sys.modules.pop(module_name, None)
        if previous_jqdata is missing:
            sys.modules.pop("jqdata", None)
        else:
            sys.modules["jqdata"] = previous_jqdata


def test_default_mode_and_date_semantics(module):
    context = types.SimpleNamespace(
        previous_date=date(2020, 1, 1),
        current_dt=datetime(2020, 1, 2, 9, 30),
    )
    assert module.RUN_MODE == "ORIGINAL_REPLICA"
    assert module.fundamental_date(context) is None
    assert module.constituent_date(context) == context.current_dt


def test_strict_asof_changes_only_the_two_date_adapters(module):
    context = types.SimpleNamespace(
        previous_date=date(2020, 1, 1),
        current_dt=datetime(2020, 1, 2, 9, 30),
    )
    module.RUN_MODE = "STRICT_ASOF"
    assert module.fundamental_date(context) == context.previous_date
    assert module.constituent_date(context) == context.previous_date


def test_original_branch_direction_and_zero_denominator(module):
    assert module.select_style_branch(30.0, 20.0) == "BIG"
    assert module.select_style_branch(20.0, 30.0) == "SMALL"
    assert module.select_style_branch(1.0, 0.0) is None


def test_price_normalizer_accepts_long_multiindex_without_sort_keyword(module):
    index = pd.MultiIndex.from_tuples(
        [
            (date(2020, 1, 1), "000001.XSHE"),
            (date(2020, 1, 2), "000001.XSHE"),
        ],
        names=["time", "code"],
    )
    raw = pd.DataFrame({"close": [10.0, 11.0]}, index=index)
    result = module.safe_close_frame(raw)
    assert list(result.columns) == ["000001.XSHE"]
    assert result["000001.XSHE"].tolist() == [10.0, 11.0]


def test_price_normalizer_accepts_legacy_mapping_close_response(module):
    class PanelLike:
        def __init__(self, close):
            self.close = close

        def __getitem__(self, key):
            if key != "close":
                raise KeyError(key)
            return self.close

    raw = PanelLike(
        pd.DataFrame(
            {"000001.XSHE": [10.0, 11.0]},
            index=pd.to_datetime(["2020-01-01", "2020-01-02"]),
        )
    )
    result = module.safe_close_frame(raw)
    assert list(result.columns) == ["000001.XSHE"]
    assert result["000001.XSHE"].tolist() == [10.0, 11.0]


def test_recent_limit_up_blacklist_removes_only_held_recent_limit_up(module):
    assert module.exclude_recent_limit_up_holdings(
        ["A", "B", "C"], ["A", "C"], ["A"]
    ) == ["B", "C"]


def test_target_selection_does_not_keep_non_target_holdings(module):
    assert module.rebalance_lists(
        holdings=["OLD"], target=["NEW"], protected=[]
    ) == (["OLD"], ["NEW"])


def test_target_selection_keeps_protected_yesterday_limit_up(module):
    assert module.rebalance_lists(
        holdings=["OLD"], target=["NEW"], protected=["OLD"]
    ) == ([], ["NEW"])


def test_style_return_uses_arithmetic_mean_in_original_percentage_scale(module):
    raw_prices = pd.DataFrame(
        {"A": [100.0, 110.0], "B": [100.0, 90.0]},
        index=pd.to_datetime(["2020-01-01", "2020-01-02"]),
    )
    assert module.cross_sectional_mean_return(raw_prices) == 0.0


def test_big_query_excludes_kcbj_symbols_from_its_fundamental_pool(module):
    captured = _install_fundamental_query_stubs(module)
    module.g = types.SimpleNamespace(stock_num=5)
    module._all_stock_symbols = lambda _context: [
        "300001.XSHE",
        "688001.XSHG",
        "000001.XSHE",
        "600001.XSHG",
    ]
    module.filter_st_stock = lambda _context, stocks: stocks
    module.filter_paused_stock = lambda _context, stocks: stocks
    module.filter_new_stock = lambda _context, stocks: stocks
    module.filter_limitup_stock = lambda _context, stocks: stocks
    module.filter_limitdown_stock = lambda _context, stocks: stocks
    module.get_fundamentals = lambda *_args, **_kwargs: pd.DataFrame(
        {"code": ["000001.XSHE"]}
    )

    assert module.BIG(types.SimpleNamespace(previous_date=date(2020, 1, 1))) == [
        "000001.XSHE"
    ]
    assert captured["in_values"]["valuation.code"] == [
        "000001.XSHE",
        "600001.XSHG",
    ]


def test_buy_allocation_reserves_capacity_for_protected_live_positions(module):
    assert module.buy_allocation(1, 5, 100000) == (25000.0, 4)
    assert module.buy_allocation(5, 5, 100000) == (0.0, 0)


def test_get_peg_marks_unavailable_fundamentals_as_unavailable(module):
    _install_fundamental_query_stubs(module)
    module.get_fundamentals = lambda *_args, **_kwargs: None

    assert module.get_peg(
        types.SimpleNamespace(previous_date=date(2020, 1, 1)), ["000001.XSHE"]
    ) is None


def test_weekly_adjustment_keeps_holdings_when_candidates_are_unavailable(module):
    warnings = []
    module.g = types.SimpleNamespace(hold_list=["HELD"], yesterday_HL_list=[])
    module.log = types.SimpleNamespace(
        warn=warnings.append,
        info=lambda _message: None,
    )
    module.get_index_stocks = lambda *_args, **_kwargs: ["000001.XSHE"]
    module._style_prices = lambda *_args, **_kwargs: None
    means = iter([30.0, 20.0])
    module.cross_sectional_mean_return = lambda _prices: next(means)
    module.select_target_list = lambda *_args, **_kwargs: None
    module.close_position = lambda _position: pytest.fail("must not liquidate")
    context = types.SimpleNamespace(
        previous_date=date(2020, 1, 1),
        current_dt=datetime(2020, 1, 2, 9, 30),
        portfolio=types.SimpleNamespace(
            positions={"HELD": types.SimpleNamespace(security="HELD")}
        ),
    )

    module.weekly_adjustment(context)

    assert warnings == ["candidate-list-unavailable"]
    assert list(context.portfolio.positions) == ["HELD"]


def _pivot_table_sort_keywords(source):
    root = ast.parse(source)
    return [
        keyword.arg
        for call in ast.walk(root)
        if isinstance(call, ast.Call)
        and (
            isinstance(call.func, ast.Name) and call.func.id == "pivot_table"
            or isinstance(call.func, ast.Attribute)
            and call.func.attr == "pivot_table"
        )
        for keyword in call.keywords
        if keyword.arg == "sort"
    ]


def test_original_runtime_source_guards_are_preserved():
    source = Path(SCRIPT).read_text(encoding="utf-8")
    ast.parse(source)

    assert _pivot_table_sort_keywords(source) == []
    assert "risk_off" not in source
    assert "candidate_buffer" not in source
    assert "winsorize" not in source
    assert "market_guard" not in source
    assert "hysteresis" not in source
    assert "PriceRelatedSlippage" not in source
    assert "date=constituent_date(context)" in source
    assert "count=20" in source
    assert "style signal unavailable" in source
    assert 'run_monthly(weekly_adjustment, 1, time="09:30")' in source
    assert "FixedSlippage(0)" in source
    assert "close_tax=0.001" in source
    assert "open_commission=0.0003" in source


def test_ast_pivot_table_guard_detects_sort_keyword():
    assert _pivot_table_sort_keywords("frame.pivot_table(sort=True)") == ["sort"]


def test_readme_explicitly_preserves_the_monthly_0930_rebalance_time():
    assert "monthly rebalance at 09:30" in README.read_text(encoding="utf-8")
