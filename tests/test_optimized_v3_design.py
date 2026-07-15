from dataclasses import FrozenInstanceError

import pytest

from quant_lab.research.optimized_v3_design import (
    CrashOverlayVariant,
    ProfitProtectionVariant,
    core_l18_variants,
    core_one_factor_variants,
    crash_overlay_variants,
    profit_protection_variants,
    recovery_variants,
    stock_count_profiles,
)


def _core_parameters(variant: object) -> tuple[float | int, ...]:
    return (
        variant.fixed_stop_loss,
        variant.cooldown_days,
        variant.warning_threshold,
        variant.reduced_budget,
        variant.confirmation_days,
        variant.clear_threshold,
    )


def test_core_one_factor_matrix_is_unique_and_contains_anchor() -> None:
    variants = core_one_factor_variants()

    assert len(variants) == 20
    assert len({variant.name for variant in variants}) == 20
    assert len({_core_parameters(variant) for variant in variants}) == 20
    anchor = next(item for item in variants if item.name == "fixed11_gradual")
    assert anchor.fixed_stop_loss == 0.11
    assert anchor.cooldown_days == 2
    assert anchor.warning_threshold == 0.48
    assert anchor.reduced_budget == 0.25
    assert anchor.confirmation_days == 2
    assert anchor.clear_threshold == 0.50


def test_core_variants_are_valid_one_factor_changes() -> None:
    variants = core_one_factor_variants()
    anchor = next(item for item in variants if item.name == "fixed11_gradual")
    anchor_parameters = _core_parameters(anchor)

    for variant in variants:
        assert 0 < variant.warning_threshold < variant.clear_threshold < 1
        assert 0 <= variant.reduced_budget <= 1
        changed_fields = sum(
            value != anchor_value
            for value, anchor_value in zip(
                _core_parameters(variant), anchor_parameters, strict=True
            )
        )
        assert changed_fields in {0, 1}


def test_core_l18_matrix_is_deterministic_unique_and_deduplicated() -> None:
    first = core_l18_variants()
    second = core_l18_variants()
    excluded = {_core_parameters(item) for item in core_one_factor_variants()}

    assert first == second
    assert len(first) == 17
    assert "core_l18_02" not in {item.name for item in first}
    assert len(first) == len({item.name for item in first})
    assert len(first) == len({_core_parameters(item) for item in first})
    assert not ({_core_parameters(item) for item in first} & excluded)
    for item in first:
        assert item.fixed_stop_loss in {0.105, 0.11, 0.115}
        assert item.cooldown_days in {1, 2, 3}
        assert item.warning_threshold in {0.47, 0.48, 0.49}
        assert item.reduced_budget in {0.15, 0.25, 0.35}
        assert item.confirmation_days in {1, 2, 3}
        assert item.clear_threshold in {0.50, 0.51, 0.52}


def test_recovery_matrix_is_cartesian_product_in_deterministic_order() -> None:
    variants = recovery_variants()

    assert [
        (item.recovery_threshold, item.confirmation_days, item.recovery_step_days)
        for item in variants
    ] == [
        (0.43, 1, 1),
        (0.43, 2, 1),
        (0.45, 1, 1),
        (0.45, 2, 1),
        (0.47, 1, 1),
        (0.47, 2, 1),
    ]


def test_route_specific_matrix_sizes() -> None:
    assert len(recovery_variants()) == 6
    assert [item.counts for item in stock_count_profiles()] == [
        (2, 3, 4, 5),
        (3, 4, 5, 6),
        (4, 5, 6, 7),
    ]
    assert len(crash_overlay_variants()) == 6
    assert len(profit_protection_variants()) == 4


def test_crash_overlays_cover_approved_levels() -> None:
    variants = crash_overlay_variants()

    assert {item.drawdown_threshold for item in variants} == {0.08, 0.10, 0.12}
    assert {item.defensive_budget for item in variants} == {0.60, 0.75}
    assert {item.recovery_confirmation_days for item in variants} == {3, 5}
    assert {item.lookback for item in variants} == {60}
    assert len(
        {
            (
                item.drawdown_threshold,
                item.defensive_budget,
                item.recovery_confirmation_days,
            )
            for item in variants
        }
    ) == 6


def test_profit_protection_pairs_match_approved_order() -> None:
    assert [
        (item.activation_threshold, item.floor) for item in profit_protection_variants()
    ] == [(0.20, 0.00), (0.30, 0.05), (0.30, 0.10), (0.40, 0.10)]


@pytest.mark.parametrize(
    "variant",
    [
        CrashOverlayVariant("immutable", 0.10, 0.60, 3, 60),
        ProfitProtectionVariant("immutable", 0.20, 0.00),
    ],
)
def test_variant_contracts_are_frozen(variant: object) -> None:
    with pytest.raises(FrozenInstanceError):
        variant.name = "changed"
