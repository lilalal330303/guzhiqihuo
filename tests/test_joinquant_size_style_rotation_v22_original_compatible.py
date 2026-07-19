from pathlib import Path
import runpy
import sys
import types

import numpy as np
import pandas as pd
import pytest


def load_strategy():
    jqdata_stub = types.ModuleType("jqdata")
    sys.modules["jqdata"] = jqdata_stub
    return runpy.run_path(
        Path("reports/joinquant_size_style_rotation_v22_original_compatible.py"),
        run_name="joinquant_size_style_rotation_v22_original_compatible_test",
    )


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
    result = ns["safe_mean_return"](frame, min_samples=2, winsorize=False)
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
