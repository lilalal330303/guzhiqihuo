from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class CoreVariant:
    name: str
    fixed_stop_loss: float
    cooldown_days: int
    warning_threshold: float
    reduced_budget: float
    confirmation_days: int
    clear_threshold: float


@dataclass(frozen=True)
class RecoveryVariant:
    name: str
    recovery_threshold: float
    confirmation_days: int
    recovery_step_days: int


@dataclass(frozen=True)
class StockCountProfile:
    name: str
    counts: tuple[int, int, int, int]


@dataclass(frozen=True)
class CrashOverlayVariant:
    name: str
    drawdown_threshold: float
    defensive_budget: float
    recovery_confirmation_days: int
    lookback: int


@dataclass(frozen=True)
class ProfitProtectionVariant:
    name: str
    activation_threshold: float
    floor: float


_ANCHOR = CoreVariant(
    name="fixed11_gradual",
    fixed_stop_loss=0.11,
    cooldown_days=2,
    warning_threshold=0.48,
    reduced_budget=0.25,
    confirmation_days=2,
    clear_threshold=0.50,
)


def _core_parameters(variant: CoreVariant) -> tuple[float | int, ...]:
    return (
        variant.fixed_stop_loss,
        variant.cooldown_days,
        variant.warning_threshold,
        variant.reduced_budget,
        variant.confirmation_days,
        variant.clear_threshold,
    )


def core_one_factor_variants() -> list[CoreVariant]:
    variants = [_ANCHOR]
    factor_levels: tuple[tuple[str, tuple[float | int, ...]], ...] = (
        ("fixed_stop_loss", (0.095, 0.105, 0.11, 0.115, 0.125)),
        ("cooldown_days", (0, 1, 2, 3, 5)),
        ("warning_threshold", (0.46, 0.47, 0.48, 0.49)),
        ("reduced_budget", (0.15, 0.25, 0.35, 0.50)),
        ("confirmation_days", (1, 2, 3)),
        ("clear_threshold", (0.49, 0.50, 0.51, 0.52)),
    )
    for field_name, levels in factor_levels:
        for level in levels:
            if getattr(_ANCHOR, field_name) == level:
                continue
            level_name = str(level).replace(".", "p")
            variants.append(
                replace(
                    _ANCHOR,
                    name=f"one_factor_{field_name}_{level_name}",
                    **{field_name: level},
                )
            )
    return variants


_L18_LEVEL_MATRIX: tuple[tuple[int, int, int, int, int, int], ...] = (
    (1, 1, 1, 1, 1, 1),
    (2, 2, 2, 2, 2, 2),
    (3, 3, 3, 3, 3, 3),
    (1, 1, 2, 2, 3, 3),
    (2, 2, 3, 3, 1, 1),
    (3, 3, 1, 1, 2, 2),
    (1, 2, 1, 3, 2, 3),
    (2, 3, 2, 1, 3, 1),
    (3, 1, 3, 2, 1, 2),
    (1, 3, 3, 2, 2, 1),
    (2, 1, 1, 3, 3, 2),
    (3, 2, 2, 1, 1, 3),
    (1, 2, 3, 1, 3, 2),
    (2, 3, 1, 2, 1, 3),
    (3, 1, 2, 3, 2, 1),
    (1, 3, 2, 3, 1, 2),
    (2, 1, 3, 1, 2, 3),
    (3, 2, 1, 2, 3, 1),
)


def core_l18_variants() -> list[CoreVariant]:
    levels: tuple[tuple[float | int, ...], ...] = (
        (0.105, 0.11, 0.115),
        (1, 2, 3),
        (0.47, 0.48, 0.49),
        (0.15, 0.25, 0.35),
        (1, 2, 3),
        (0.50, 0.51, 0.52),
    )
    excluded = {_core_parameters(item) for item in core_one_factor_variants()}
    variants: list[CoreVariant] = []
    seen: set[tuple[float | int, ...]] = set()
    for row_number, row in enumerate(_L18_LEVEL_MATRIX, start=1):
        parameters = tuple(
            factor_levels[level - 1]
            for factor_levels, level in zip(levels, row, strict=True)
        )
        if parameters in excluded or parameters in seen:
            continue
        seen.add(parameters)
        variants.append(
            CoreVariant(f"core_l18_{row_number:02d}", *parameters)
        )
    return variants


def recovery_variants() -> list[RecoveryVariant]:
    return [
        RecoveryVariant(
            name=f"recovery_{threshold:.2f}_confirm_{confirmation_days}",
            recovery_threshold=threshold,
            confirmation_days=confirmation_days,
            recovery_step_days=1,
        )
        for threshold in (0.43, 0.45, 0.47)
        for confirmation_days in (1, 2)
    ]


def stock_count_profiles() -> list[StockCountProfile]:
    return [
        StockCountProfile("concentrated", (2, 3, 4, 5)),
        StockCountProfile("current", (3, 4, 5, 6)),
        StockCountProfile("diversified", (4, 5, 6, 7)),
    ]


def crash_overlay_variants() -> list[CrashOverlayVariant]:
    combinations = (
        (0.08, 0.60, 3),
        (0.08, 0.75, 5),
        (0.10, 0.60, 5),
        (0.10, 0.75, 3),
        (0.12, 0.60, 3),
        (0.12, 0.75, 5),
    )
    return [
        CrashOverlayVariant(
            name=f"crash_overlay_{index:02d}",
            drawdown_threshold=drawdown_threshold,
            defensive_budget=defensive_budget,
            recovery_confirmation_days=recovery_confirmation_days,
            lookback=60,
        )
        for index, (
            drawdown_threshold,
            defensive_budget,
            recovery_confirmation_days,
        ) in enumerate(combinations, start=1)
    ]


def profit_protection_variants() -> list[ProfitProtectionVariant]:
    return [
        ProfitProtectionVariant(
            name=f"profit_protection_{index:02d}",
            activation_threshold=activation_threshold,
            floor=floor,
        )
        for index, (activation_threshold, floor) in enumerate(
            ((0.20, 0.00), (0.30, 0.05), (0.30, 0.10), (0.40, 0.10)),
            start=1,
        )
    ]
