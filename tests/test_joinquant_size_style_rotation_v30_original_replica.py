from datetime import date, datetime
import importlib.util
from pathlib import Path
import sys
import types

import pandas as pd
import pytest


@pytest.fixture
def module():
    missing = object()
    previous_jqdata = sys.modules.get("jqdata", missing)
    jqdata_stub = types.ModuleType("jqdata")
    sys.modules["jqdata"] = jqdata_stub

    module_path = (
        Path(__file__).resolve().parents[1]
        / "reports"
        / "joinquant_size_style_rotation_v30_original_replica.py"
    )
    module_name = "joinquant_size_style_rotation_v30_original_replica_test"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
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
