from __future__ import annotations

import pandas as pd


def build_incremental_price_fetch_plan(
    symbols: list[str],
    coverage: pd.DataFrame,
    start_date: str,
    end_date: str,
    calendar_dates: pd.Series | list[pd.Timestamp] | None = None,
    first_active_dates: pd.DataFrame | dict[str, str | pd.Timestamp] | None = None,
) -> pd.DataFrame:
    """Plan only missing price fetch windows for a universe.

    The planner is intentionally conservative: it fetches a prefix when a
    symbol starts after the requested start, and a suffix when a symbol ends
    before the requested end. If a trading calendar is supplied, it also marks
    symbols with interior missing bars for a full refresh window.
    """
    required = {"symbol", "min_trade_date", "max_trade_date", "row_count"}
    if not coverage.empty:
        missing = required.difference(coverage.columns)
        if missing:
            raise ValueError(f"coverage missing required columns: {sorted(missing)}")

    requested_start = pd.Timestamp(start_date).normalize()
    requested_end = pd.Timestamp(end_date).normalize()
    if requested_start > requested_end:
        raise ValueError("start_date must be on or before end_date")

    coverage_by_symbol = {}
    if not coverage.empty:
        rows = coverage.copy()
        rows["symbol"] = rows["symbol"].astype(str)
        rows["min_trade_date"] = pd.to_datetime(rows["min_trade_date"]).dt.normalize()
        rows["max_trade_date"] = pd.to_datetime(rows["max_trade_date"]).dt.normalize()
        coverage_by_symbol = {row.symbol: row for row in rows.itertuples(index=False)}
    first_active_by_symbol = _first_active_by_symbol(first_active_dates)

    calendar: pd.Series | None = None
    if calendar_dates is not None:
        calendar = pd.to_datetime(pd.Series(calendar_dates)).dt.normalize().drop_duplicates().sort_values()

    plan_rows: list[dict[str, object]] = []
    for symbol in dict.fromkeys(str(item) for item in symbols):
        symbol_start = max(requested_start, first_active_by_symbol.get(symbol, requested_start))
        if symbol_start > requested_end:
            continue
        row = coverage_by_symbol.get(symbol)
        if row is None or pd.isna(row.min_trade_date) or pd.isna(row.max_trade_date):
            plan_rows.append(
                {
                    "symbol": symbol,
                    "start_date": symbol_start,
                    "end_date": requested_end,
                    "reason": "missing_symbol",
                }
            )
            continue

        min_date = pd.Timestamp(row.min_trade_date).normalize()
        max_date = pd.Timestamp(row.max_trade_date).normalize()
        row_count = int(row.row_count)

        if min_date > symbol_start:
            plan_rows.append(
                {
                    "symbol": symbol,
                    "start_date": symbol_start,
                    "end_date": min_date - pd.Timedelta(days=1),
                    "reason": "missing_prefix",
                }
            )
        if max_date < requested_end:
            plan_rows.append(
                {
                    "symbol": symbol,
                    "start_date": max_date + pd.Timedelta(days=1),
                    "end_date": requested_end,
                    "reason": "missing_suffix",
                }
            )
        expected_count = None
        if calendar is not None:
            expected_count = int(calendar.between(symbol_start, requested_end).sum())
        if expected_count is not None and row_count < expected_count and min_date <= symbol_start and max_date >= requested_end:
            plan_rows.append(
                {
                    "symbol": symbol,
                    "start_date": symbol_start,
                    "end_date": requested_end,
                    "reason": "interior_gaps",
                }
            )

    columns = ["symbol", "start_date", "end_date", "reason"]
    plan = pd.DataFrame(plan_rows, columns=columns)
    if plan.empty:
        return plan
    plan["start_date"] = pd.to_datetime(plan["start_date"]).dt.date
    plan["end_date"] = pd.to_datetime(plan["end_date"]).dt.date
    return plan[plan["start_date"] <= plan["end_date"]].reset_index(drop=True)


def _first_active_by_symbol(
    first_active_dates: pd.DataFrame | dict[str, str | pd.Timestamp] | None,
) -> dict[str, pd.Timestamp]:
    if first_active_dates is None:
        return {}
    if isinstance(first_active_dates, dict):
        return {str(symbol): pd.Timestamp(date).normalize() for symbol, date in first_active_dates.items()}
    if first_active_dates.empty:
        return {}
    required = {"symbol", "first_active_date"}
    missing = required.difference(first_active_dates.columns)
    if missing:
        raise ValueError(f"first_active_dates missing required columns: {sorted(missing)}")
    rows = first_active_dates.copy()
    rows["symbol"] = rows["symbol"].astype(str)
    rows["first_active_date"] = pd.to_datetime(rows["first_active_date"]).dt.normalize()
    return dict(zip(rows["symbol"], rows["first_active_date"], strict=False))
