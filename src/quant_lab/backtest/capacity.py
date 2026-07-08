from __future__ import annotations

from dataclasses import dataclass
from itertools import product

import pandas as pd


@dataclass(frozen=True)
class CapacityConfig:
    participation_rate: float = 0.25
    buy_value_ratio: float = 0.995
    slice_count: int | None = 10
    min_order_value: float = 0.0


@dataclass(frozen=True)
class CapacitySimulationResult:
    fills: pd.DataFrame
    summary: dict[str, float | int]


def simulate_rebalance_capacity(
    orders: pd.DataFrame,
    minute_bars: pd.DataFrame,
    config: CapacityConfig | None = None,
) -> CapacitySimulationResult:
    """Simulate capacity-capped execution for rebalance orders.

    `orders` requires `trade_date`, `symbol`, and `target_value`.
    `minute_bars` requires `trade_date`, `minute`, `symbol`, `close`, and `volume`.
    The model caps each minute's fill by `close * volume * participation_rate`.
    """
    cfg = config or CapacityConfig()
    _validate_orders(orders)
    _validate_minute_bars(minute_bars)
    if not (0 < cfg.participation_rate <= 1):
        raise ValueError("participation_rate must be in (0, 1]")
    if cfg.slice_count is not None and cfg.slice_count <= 0:
        raise ValueError("slice_count must be positive")

    bars = minute_bars.copy()
    bars["bar_amount"] = bars["close"].astype(float) * bars["volume"].astype(float)
    bar_map = {
        (row.trade_date, row.minute, row.symbol): float(row.bar_amount)
        for row in bars.itertuples(index=False)
    }
    source_map = {
        (row.trade_date, row.minute, row.symbol): str(getattr(row, "source", "unknown"))
        for row in bars.itertuples(index=False)
    }

    rows: list[dict[str, object]] = []
    for order in orders.sort_values(["trade_date", "symbol"]).itertuples(index=False):
        trade_date = getattr(order, "trade_date")
        symbol = str(getattr(order, "symbol"))
        target_value = float(getattr(order, "target_value")) * cfg.buy_value_ratio
        slice_count = _order_slice_count(order, cfg)
        remaining = target_value
        intended_slice = target_value / slice_count

        for slice_no in range(1, slice_count + 1):
            minute = _slice_minute(slice_no)
            desired = min(intended_slice, remaining)
            if desired <= 0:
                break
            if desired < cfg.min_order_value:
                rows.append(
                    {
                        "trade_date": trade_date,
                        "minute": minute,
                        "symbol": symbol,
                        "slice_no": slice_no,
                        "desired_value": desired,
                        "bar_amount": 0.0,
                        "capacity_value": 0.0,
                        "filled_value": 0.0,
                        "unfilled_value": desired,
                        "capacity_ratio": 0.0,
                        "skipped_min_order": 1,
                        "source": "skipped",
                    }
                )
                continue

            bar_amount = bar_map.get((trade_date, minute, symbol), 0.0)
            capacity_value = bar_amount * cfg.participation_rate
            filled = min(desired, capacity_value)
            remaining -= filled
            rows.append(
                {
                    "trade_date": trade_date,
                    "minute": minute,
                    "symbol": symbol,
                    "slice_no": slice_no,
                    "desired_value": desired,
                    "bar_amount": bar_amount,
                    "capacity_value": capacity_value,
                    "filled_value": filled,
                    "unfilled_value": desired - filled,
                    "capacity_ratio": capacity_value / desired if desired > 0 else 0.0,
                    "skipped_min_order": 0,
                    "source": source_map.get((trade_date, minute, symbol), "missing"),
                }
            )

    fills = pd.DataFrame(rows)
    if fills.empty:
        summary = {
            "order_count": int(len(orders)),
            "fill_ratio": 0.0,
            "capacity_warning_count": 0,
            "severe_capacity_count": 0,
            "skipped_min_order_count": 0,
        }
        return CapacitySimulationResult(fills=fills, summary=summary)

    desired_total = float(fills["desired_value"].sum())
    filled_total = float(fills["filled_value"].sum())
    summary = {
        "order_count": int(len(orders)),
        "fill_slice_count": int(len(fills)),
        "desired_value": desired_total,
        "filled_value": filled_total,
        "unfilled_value": float(fills["unfilled_value"].sum()),
        "fill_ratio": filled_total / desired_total if desired_total > 0 else 0.0,
        "capacity_warning_count": int((fills["capacity_ratio"] < 1.0).sum()),
        "severe_capacity_count": int((fills["capacity_ratio"] < 0.1).sum()),
        "skipped_min_order_count": int(fills["skipped_min_order"].sum()),
    }
    return CapacitySimulationResult(fills=fills, summary=summary)


def build_capacity_grid(
    participation_rates: list[float],
    slice_counts: list[int],
    buy_value_ratios: list[float],
    min_order_values: list[float] | None = None,
) -> pd.DataFrame:
    """Create a parameter grid for capacity experiments."""
    min_values = min_order_values or [0.0]
    rows = [
        {
            "participation_rate": participation_rate,
            "slice_count": slice_count,
            "buy_value_ratio": buy_value_ratio,
            "min_order_value": min_order_value,
        }
        for participation_rate, slice_count, buy_value_ratio, min_order_value in product(
            participation_rates, slice_counts, buy_value_ratios, min_values
        )
    ]
    return pd.DataFrame(rows)


def score_capacity_grid(
    orders: pd.DataFrame,
    minute_bars: pd.DataFrame,
    grid: pd.DataFrame,
) -> pd.DataFrame:
    """Run capacity simulations for each grid row and return comparable metrics."""
    required = {"participation_rate", "slice_count", "buy_value_ratio", "min_order_value"}
    missing = required.difference(grid.columns)
    if missing:
        raise ValueError(f"grid missing required columns: {sorted(missing)}")

    rows: list[dict[str, float | int]] = []
    for params in grid.itertuples(index=False):
        cfg = CapacityConfig(
            participation_rate=float(getattr(params, "participation_rate")),
            slice_count=int(getattr(params, "slice_count")),
            buy_value_ratio=float(getattr(params, "buy_value_ratio")),
            min_order_value=float(getattr(params, "min_order_value")),
        )
        result = simulate_rebalance_capacity(orders, minute_bars, cfg)
        rows.append({**cfg.__dict__, **result.summary})
    return pd.DataFrame(rows)


def _slice_minute(slice_no: int) -> int:
    return 931 + slice_no


def _order_slice_count(order: object, cfg: CapacityConfig) -> int:
    if cfg.slice_count is not None:
        return cfg.slice_count
    for attr in ("slice_count", "slices"):
        try:
            value = int(getattr(order, attr))
            if value > 0:
                return value
        except Exception:
            pass
    raise ValueError("orders must include positive slice_count or slices when config.slice_count is None")


def _validate_orders(orders: pd.DataFrame) -> None:
    required = {"trade_date", "symbol", "target_value"}
    missing = required.difference(orders.columns)
    if missing:
        raise ValueError(f"orders missing required columns: {sorted(missing)}")


def _validate_minute_bars(minute_bars: pd.DataFrame) -> None:
    required = {"trade_date", "minute", "symbol", "close", "volume"}
    missing = required.difference(minute_bars.columns)
    if missing:
        raise ValueError(f"minute_bars missing required columns: {sorted(missing)}")
