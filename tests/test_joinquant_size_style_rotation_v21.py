from pathlib import Path
import pandas as pd
import runpy
import sys
import types


def load_strategy():
    jqdata_stub = types.ModuleType("jqdata")
    sys.modules["jqdata"] = jqdata_stub
    return runpy.run_path(
        Path("reports/joinquant_size_style_rotation_v21.py"),
        run_name="joinquant_size_style_rotation_v21_test",
    )


def test_reversal_dominates_when_recent_style_leads():
    ns = load_strategy()
    scores = ns["compute_style_scores"](
        small_returns={20: 0.20, 60: 0.04},
        big_returns={20: 0.04, 60: 0.08},
        small_vol={20: 0.25, 60: 0.22},
        big_vol={20: 0.20, 60: 0.18},
    )
    assert scores["BIG"] > scores["SMALL"]


def test_hysteresis_keeps_current_style_for_small_edge():
    ns = load_strategy()
    assert (
        ns["select_style_with_hysteresis"](
            "SMALL", {"SMALL": 0.12, "BIG": 0.16}, 0.10, 2, 2
        )
        == "SMALL"
    )


def test_hysteresis_switches_after_gap_and_minimum_hold():
    ns = load_strategy()
    assert (
        ns["select_style_with_hysteresis"](
            "SMALL", {"SMALL": 0.10, "BIG": 0.30}, 0.10, 2, 2
        )
        == "BIG"
    )


def test_risk_off_requires_both_style_indices_below_trend():
    ns = load_strategy()
    assert ns["market_risk_off"](0.98, 1.00, 1.05, 1.04, -0.04) is False
    assert ns["market_risk_off"](0.98, 1.00, 0.97, 0.96, -0.04) is True


def test_holdings_in_buffer_are_kept_before_new_candidates():
    ns = load_strategy()
    result = ns["merge_target_with_holdings"](
        holdings=["A", "Z"],
        ranked_candidates=["B", "A", "C", "D", "E", "F"],
        target_count=3,
        buffer_count=5,
    )
    assert result == ["A", "B", "C"]


def test_index_history_uses_single_index_history_api():
    ns = load_strategy()

    def fake_attribute_history(*args, **kwargs):
        return pd.DataFrame({"close": [100.0, 101.0, 102.0]})

    def rejected_get_price(*args, **kwargs):
        raise AssertionError("index history should not depend on panel=False")

    strategy_globals = ns["get_index_close"].__globals__
    strategy_globals["attribute_history"] = fake_attribute_history
    strategy_globals["get_price"] = rejected_get_price
    strategy_globals["log"] = types.SimpleNamespace(warn=lambda *args: None)
    result = ns["get_index_close"]("000985.XSHG", "2024-01-03", count=3)

    assert result is not None
    assert result.tolist() == [100.0, 101.0, 102.0]
