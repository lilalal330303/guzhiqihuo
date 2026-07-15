import math

import pytest

from quant_lab.research import small_cap_experiment
from quant_lab.research.small_cap_experiment import build_joinquant_v3_targets
from quant_lab.strategies.small_cap import SmallCapParams
from test_small_cap_experiment import _make_strict_inputs


def test_dynamic_stock_num_profiles_map_four_market_bands():
    dynamic_stock_num = small_cap_experiment.dynamic_stock_num
    assert dynamic_stock_num(300, (2, 3, 4, 5)) == 2
    assert dynamic_stock_num(0, (2, 3, 4, 5)) == 3
    assert dynamic_stock_num(-300, (2, 3, 4, 5)) == 4
    assert dynamic_stock_num(-600, (2, 3, 4, 5)) == 5


@pytest.mark.parametrize(
    "counts",
    [(), (1, 2, 3), (1, 2, 3, 4, 5), (1, 2, 3, 0), (1, 2, 3, -1), (1, 2, 3, 4.0)],
)
def test_dynamic_stock_num_rejects_invalid_count_tuples(counts):
    dynamic_stock_num = small_cap_experiment.dynamic_stock_num
    with pytest.raises(ValueError, match="four positive integers"):
        dynamic_stock_num(0, counts)


@pytest.mark.parametrize("index_diff", [math.nan, math.inf, -math.inf])
def test_dynamic_stock_num_rejects_non_finite_index_difference(index_diff):
    dynamic_stock_num = small_cap_experiment.dynamic_stock_num
    with pytest.raises(ValueError, match="finite"):
        dynamic_stock_num(index_diff)


def test_default_profile_keeps_baseline_target_schema():
    strict_inputs = _make_strict_inputs(
        ["000006", "000002", "000005", "000001", "000004", "000003"]
    )

    targets, diagnostics, _ = build_joinquant_v3_targets(
        strict_inputs,
        SmallCapParams(stock_num=5),
    )

    assert targets.columns.tolist() == ["signal_date", "symbol", "target_weight"]
    assert "profile_name" not in diagnostics
    assert targets["symbol"].tolist() == ["000006", "000002", "000005", "000001"]
    assert diagnostics["stock_num"].tolist() == [4]


def test_named_profile_exports_independent_target_metadata():
    strict_inputs = _make_strict_inputs(
        ["000006", "000002", "000005", "000001", "000004"]
    )

    targets, diagnostics, _ = build_joinquant_v3_targets(
        strict_inputs,
        SmallCapParams(stock_num=5),
        dynamic_stock_counts=(2, 3, 4, 5),
        profile_name="concentrated",
    )

    assert targets.columns.tolist() == [
        "signal_date", "symbol", "target_weight", "stock_num", "profile_name"
    ]
    assert targets["symbol"].tolist() == ["000006", "000002", "000005"]
    assert targets["symbol"].map(type).eq(str).all()
    assert targets["stock_num"].eq(3).all()
    assert targets["profile_name"].eq("concentrated").all()
    assert diagnostics["profile_name"].eq("concentrated").all()


def test_fixed_stock_count_ignores_profile_counts_but_exports_named_metadata():
    strict_inputs = _make_strict_inputs(
        ["000006", "000002", "000005", "000001", "000004", "000003"]
    )

    targets, diagnostics, _ = build_joinquant_v3_targets(
        strict_inputs,
        SmallCapParams(stock_num=5),
        enable_dynamic_stock_num=False,
        dynamic_stock_counts=(1, 2, 3, 4),
        profile_name="fixed-five",
    )

    assert targets["symbol"].tolist() == [
        "000006", "000002", "000005", "000001", "000004"
    ]
    assert targets["stock_num"].eq(5).all()
    assert diagnostics["stock_num"].tolist() == [5]
    assert diagnostics["profile_name"].eq("fixed-five").all()


@pytest.mark.parametrize("profile_name", ["", " ", "\t\n"])
def test_target_builder_rejects_whitespace_profile_names(profile_name):
    with pytest.raises(ValueError, match="profile_name"):
        build_joinquant_v3_targets(
            _make_strict_inputs(["000001"]),
            SmallCapParams(),
            profile_name=profile_name,
        )
