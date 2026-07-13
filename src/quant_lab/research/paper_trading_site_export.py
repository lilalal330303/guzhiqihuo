"""Export read-only paper-trading audit snapshots for the static site."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

import pandas as pd

from quant_lab.app.paper_trading_view_model import (
    build_command_center_snapshot,
    build_execution_timeline,
    decode_payload_frame,
)
from quant_lab.data.repository import DuckDBRepository
from quant_lab.paper.models import PaperAccount
from quant_lab.research.paper_trading import DEFAULT_PAPER_ACCOUNTS


STRATEGY_DISPLAY_NAMES = {
    "v7k_wufu_qixing": "福星ETF",
    "wufu_v12d": "五福ETF",
}

ORDER_STATUS_DISPLAY_NAMES = {
    "filled": "已成交",
    "rejected": "已拒绝（未执行）",
    "pending": "待处理",
    "submitted": "已提交",
    "cancelled": "已撤销",
}

SIDE_DISPLAY_NAMES = {"buy": "买入", "sell": "卖出"}


def build_site_snapshot(
    repo: DuckDBRepository,
    accounts: Iterable[PaperAccount] = DEFAULT_PAPER_ACCOUNTS,
    limit: int = 200,
) -> dict[str, object]:
    """Build a JSON-safe, source-backed snapshot without mutating paper audit data."""
    if limit < 1:
        raise ValueError("limit must be positive")
    account_list = tuple(accounts)
    panels = {
        panel.account_id: panel
        for panel in build_command_center_snapshot(repo, account_list).account_panels
    }
    account_snapshots = [_account_snapshot(repo, account, panels[account.account_id], limit) for account in account_list]
    market_data_as_of = _latest_market_timestamp(account_snapshots)
    _apply_latest_market_values(repo, account_snapshots, market_data_as_of)
    return {
        "source": "local_paper_trading_audit",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "market_data_as_of": market_data_as_of,
        "snapshot_schedule": {
            "label": "盘后快照", "time": "15:30", "timezone": "Asia/Shanghai",
        },
        "combined_holdings": _combine_holdings(account_snapshots),
        "accounts": account_snapshots,
    }


def export_site_snapshot(
    repo: DuckDBRepository,
    output_path: str | Path,
    accounts: Iterable[PaperAccount] = DEFAULT_PAPER_ACCOUNTS,
    limit: int = 200,
) -> Path:
    """Atomically replace a static-site snapshot after complete serialization succeeds."""
    destination = Path(output_path)
    snapshot = build_site_snapshot(repo, accounts=accounts, limit=limit)
    rendered = json.dumps(snapshot, ensure_ascii=False, indent=2, allow_nan=False)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(rendered, encoding="utf-8")
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return destination


def _account_snapshot(repo: DuckDBRepository, account: PaperAccount, panel: Any, limit: int) -> dict[str, object]:
    symbol_names = _symbol_names(repo)
    raw_position_frame = decode_payload_frame(repo.load_paper_positions(panel.account_id))
    raw_fill_frame = decode_payload_frame(repo.load_paper_fills(panel.account_id))
    raw_equity_frame = repo.load_paper_equity(panel.account_id)
    position_records = _records(raw_position_frame, max(len(raw_position_frame), 1))
    fill_ledger = _fill_ledger(_records(raw_fill_frame, max(len(raw_fill_frame), 1)))
    history_prices = _daily_close_prices(
        repo,
        [str(row.get("symbol") or "") for row in position_records],
        [str(row.get("timestamp") or "") for row in position_records],
    )
    positions = _enrich_records(
        _latest_position_records(repo, panel.account_id), symbol_names,
    )
    orders = _apply_order_profit_loss(_enrich_records(
        _visible_orders(_records(decode_payload_frame(repo.load_paper_orders(panel.account_id)), limit)), symbol_names,
    ), fill_ledger)
    fills = _enrich_records(fill_ledger[-limit:], symbol_names)
    equity_curve = _records(raw_equity_frame, max(len(raw_equity_frame), 1))
    position_history = _daily_position_history(position_records, fill_ledger, history_prices, symbol_names)
    return {
        "id": panel.account_id,
        "strategy_id": panel.strategy_id,
        "display": {
            "name": STRATEGY_DISPLAY_NAMES.get(panel.account_id, panel.display_name),
            "initial_cash": panel.initial_cash,
        },
        "metrics": {
            "cash": panel.cash,
            "equity": panel.equity,
            "position_market_value": panel.position_market_value,
            "total_return": panel.total_return,
            "today_return": panel.today_return,
            "position_count": panel.position_count,
            "order_status_counts": panel.order_status_counts,
            "latest_signal_intent": panel.latest_signal_intent,
            "readiness_reason": panel.readiness_reason,
        },
        "equity_curve": equity_curve,
        "daily_equity_bars": _daily_equity_bars(equity_curve),
        "five_day_equity_candles": _five_day_equity_candles(equity_curve),
        "positions": positions,
        "position_history": position_history,
        "orders": orders,
        "fills": fills,
        "timeline": _visible_timeline(_records(build_execution_timeline(repo, panel.account_id, panel.strategy_id), limit)),
        "exceptions": _records(decode_payload_frame(repo.load_paper_exceptions(panel.account_id)), limit),
    }


def _visible_orders(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Hide non-executed orders from the operating view without deleting audit rows."""
    return [row for row in rows if str(row.get("status") or "").lower() != "rejected"]


def _visible_timeline(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Remove repetitive no-intent heartbeats from the reader-facing activity feed."""
    return [row for row in rows if all(
        str(row.get(key) or "").lower() != "intent_missing" for key in ("event", "reason", "message", "exception_type")
    )]


def _fill_ledger(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Rebuild moving-average cost and realized P/L from durable fills."""
    states: dict[str, dict[str, float]] = {}
    enriched: list[dict[str, object]] = []
    ordered = sorted((dict(row) for row in rows), key=lambda row: str(row.get("timestamp") or ""))
    for row in ordered:
        symbol = str(row.get("symbol") or "")
        side = str(row.get("side") or "").lower()
        quantity = float(row.get("quantity") or 0)
        price = float(row.get("price") or 0)
        commission = float(row.get("commission") or 0)
        state = states.setdefault(symbol, {"quantity": 0.0, "cost": 0.0, "realized": 0.0})
        average_cost = state["cost"] / state["quantity"] if state["quantity"] > 0 else 0.0
        profit_loss: float | None = None
        if side == "buy" and quantity > 0:
            state["quantity"] += quantity
            state["cost"] += quantity * price + commission
        elif side == "sell" and quantity > 0:
            sold = min(quantity, state["quantity"])
            profit_loss = sold * price - commission - sold * average_cost
            durable = _durable_profit_loss(row)
            if durable is not None:
                profit_loss = durable
            state["quantity"] -= sold
            state["cost"] = max(0.0, state["cost"] - sold * average_cost)
            if state["quantity"] <= 1e-9:
                state["quantity"], state["cost"] = 0.0, 0.0
            state["realized"] += profit_loss
        row["average_cost"] = average_cost if side == "sell" else None
        row["average_cost_after"] = state["cost"] / state["quantity"] if state["quantity"] > 0 else 0.0
        row["remaining_quantity"] = state["quantity"]
        row["profit_loss"] = profit_loss
        row["cumulative_realized_pnl"] = state["realized"]
        enriched.append(row)
    return enriched


def _apply_order_profit_loss(
    orders: list[dict[str, object]], ledger: list[dict[str, object]],
) -> list[dict[str, object]]:
    pnl_by_key: dict[tuple[str, str, str], float] = {}
    for fill in ledger:
        if str(fill.get("side") or "").lower() != "sell" or fill.get("profit_loss") is None:
            continue
        key = (str(fill.get("timestamp") or ""), str(fill.get("symbol") or ""), "sell")
        pnl_by_key[key] = pnl_by_key.get(key, 0.0) + float(fill["profit_loss"])
    result = []
    for original in orders:
        row = dict(original)
        if str(row.get("side") or "").lower() == "sell":
            row["profit_loss"] = pnl_by_key.get((str(row.get("timestamp") or ""), str(row.get("symbol") or ""), "sell"))
        result.append(row)
    return result


def _daily_equity_bars(curve: list[dict[str, object]]) -> list[dict[str, object]]:
    if not curve:
        return []
    frame = pd.DataFrame(curve)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    frame["equity"] = pd.to_numeric(frame["equity"], errors="coerce")
    frame = frame.dropna(subset=["timestamp", "equity"]).sort_values("timestamp", kind="stable")
    bars: list[dict[str, object]] = []
    for day, group in frame.groupby(frame["timestamp"].dt.strftime("%Y-%m-%d"), sort=True):
        opening, closing = float(group.iloc[0]["equity"]), float(group.iloc[-1]["equity"])
        bars.append({
            "trade_date": day, "open": opening, "high": float(group["equity"].max()),
            "low": float(group["equity"].min()), "close": closing,
            "change": closing - opening, "return": (closing / opening - 1.0) if opening else 0.0,
        })
    return bars


def _five_day_equity_candles(curve: list[dict[str, object]]) -> list[dict[str, object]]:
    """Aggregate observed account equity into five-minute OHLC buckets for five trade days."""
    if not curve:
        return []
    frame = pd.DataFrame(curve)
    if not {"timestamp", "equity"}.issubset(frame.columns):
        return []
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
    frame["equity"] = pd.to_numeric(frame["equity"], errors="coerce")
    frame = frame.dropna(subset=["timestamp", "equity"]).sort_values("timestamp", kind="stable")
    if frame.empty:
        return []
    frame["trade_date"] = frame["timestamp"].dt.strftime("%Y-%m-%d")
    latest_days = sorted(frame["trade_date"].unique())[-5:]
    frame = frame[frame["trade_date"].isin(latest_days)].copy()
    frame["bucket"] = frame["timestamp"].dt.floor("5min")
    result: list[dict[str, object]] = []
    for (trade_date, bucket), group in frame.groupby(["trade_date", "bucket"], sort=True):
        result.append({
            "timestamp": pd.Timestamp(bucket).isoformat(),
            "trade_date": str(trade_date),
            "open": float(group.iloc[0]["equity"]),
            "high": float(group["equity"].max()),
            "low": float(group["equity"].min()),
            "close": float(group.iloc[-1]["equity"]),
        })
    return result


def _daily_close_prices(
    repo: DuckDBRepository, symbols: list[str], snapshot_timestamps: list[str],
) -> dict[tuple[str, str], float]:
    clean_symbols = sorted({symbol for symbol in symbols if symbol})
    cutoffs: dict[str, pd.Timestamp] = {}
    for value in snapshot_timestamps:
        if not value:
            continue
        timestamp = pd.Timestamp(value)
        day = timestamp.strftime("%Y-%m-%d")
        cutoffs[day] = max(cutoffs.get(day, timestamp), timestamp)
    clean_dates = sorted(cutoffs)
    if not clean_symbols or not clean_dates:
        return {}
    bars = repo.load_minute_bars(clean_symbols, clean_dates[0], clean_dates[-1])
    if bars.empty:
        return {}
    bars = bars.copy()
    bars["datetime"] = pd.to_datetime(bars["datetime"])
    bars["trade_date"] = pd.to_datetime(bars["trade_date"]).dt.strftime("%Y-%m-%d")
    bars = bars[bars.apply(lambda row: row["datetime"] <= cutoffs.get(row["trade_date"], row["datetime"]), axis=1)]
    latest = bars.sort_values(["symbol", "trade_date", "datetime"], kind="stable").groupby(
        ["symbol", "trade_date"], as_index=False,
    ).tail(1)
    return {(str(row.trade_date), str(row.symbol)): float(row.close) for row in latest.itertuples(index=False)}


def _daily_position_history(
    position_rows: list[dict[str, object]], ledger: list[dict[str, object]],
    prices: dict[tuple[str, str], float], symbol_names: dict[str, str],
) -> list[dict[str, object]]:
    if not position_rows:
        return []
    frame = pd.DataFrame(position_rows)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    frame["quantity"] = pd.to_numeric(frame["quantity"], errors="coerce").fillna(0.0)
    frame["trade_date"] = frame["timestamp"].dt.strftime("%Y-%m-%d")
    latest_times = frame.groupby("trade_date")["timestamp"].max()
    previous: dict[str, float] = {}
    history: list[dict[str, object]] = []
    for day in sorted(latest_times.index):
        snapshot = frame[(frame["trade_date"] == day) & (frame["timestamp"] == latest_times[day])]
        current = {str(row.symbol): float(row.quantity) for row in snapshot.itertuples(index=False)}
        holdings: list[dict[str, object]] = []
        for symbol in sorted(set(previous) | set(current)):
            quantity, prior = current.get(symbol, 0.0), previous.get(symbol, 0.0)
            changes = quantity - prior
            symbol_fills = [row for row in ledger if str(row.get("symbol") or "") == symbol and str(row.get("timestamp") or "")[:10] <= day]
            day_sells = [row for row in symbol_fills if str(row.get("timestamp") or "")[:10] == day and str(row.get("side") or "").lower() == "sell"]
            last_fill = symbol_fills[-1] if symbol_fills else {}
            average_cost = float(last_fill.get("average_cost_after") or 0)
            realized_day = sum(float(row.get("profit_loss") or 0) for row in day_sells)
            realized_total = sum(float(row.get("profit_loss") or 0) for row in symbol_fills if str(row.get("side") or "").lower() == "sell")
            price = prices.get((day, symbol))
            market_value = quantity * price if price is not None else None
            unrealized = quantity * (price - average_cost) if price is not None and quantity > 0 else 0.0
            action = "持有"
            if prior == 0 and quantity > 0: action = "新建"
            elif prior > 0 and quantity == 0: action = "清仓"
            elif changes > 0: action = "增持"
            elif changes < 0: action = "减持"
            holdings.append({
                "symbol": symbol, "display_name": symbol_names.get(symbol.split(".")[0], symbol),
                "quantity": quantity, "previous_quantity": prior, "quantity_change": changes,
                "action": action, "close": price, "market_value": market_value,
                "average_cost": average_cost, "realized_pnl": realized_day,
                "cumulative_realized_pnl": realized_total, "unrealized_pnl": unrealized,
                "total_pnl": realized_total + unrealized,
            })
        history.append({"trade_date": day, "timestamp": pd.Timestamp(latest_times[day]).isoformat(), "holdings": holdings})
        previous = current
    return history


def _latest_position_records(repo: DuckDBRepository, account_id: str) -> list[dict[str, object]]:
    """Expose one durable position snapshot only, omitting zero-quantity tombstones."""
    rows = decode_payload_frame(repo.load_paper_positions(account_id))
    if rows.empty:
        return []
    timestamps = pd.to_datetime(rows["timestamp"])
    latest = timestamps.max()
    latest_rows = rows.loc[timestamps == latest].copy()
    quantities = pd.to_numeric(latest_rows.get("quantity"), errors="coerce").fillna(0)
    return _records(latest_rows.loc[quantities > 0], len(latest_rows))


def _apply_latest_market_values(
    repo: DuckDBRepository, accounts: list[dict[str, object]], market_data_as_of: str | None,
) -> None:
    """Mark latest durable holdings with the last available local minute close at the audit timestamp."""
    if not market_data_as_of:
        return
    as_of = pd.Timestamp(market_data_as_of)
    positions = [
        row for account in accounts for row in account.get("positions", [])
        if isinstance(row, dict) and row.get("symbol")
    ]
    prices = _latest_minute_prices(repo, [str(row["symbol"]) for row in positions], as_of)
    for row in positions:
        price = prices.get(str(row["symbol"]))
        row["latest_price"] = price
        if price is not None:
            row["market_value"] = float(row.get("quantity") or 0) * price


def _latest_minute_prices(
    repo: DuckDBRepository, symbols: list[str], as_of: pd.Timestamp,
) -> dict[str, float]:
    unique_symbols = list(dict.fromkeys(symbols))
    if not unique_symbols:
        return {}
    start_date = (as_of.normalize() - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
    bars = repo.load_minute_bars(unique_symbols, start_date, as_of.strftime("%Y-%m-%d"))
    if bars.empty:
        return {}
    rows = bars[pd.to_datetime(bars["datetime"]) <= as_of].copy()
    if rows.empty:
        return {}
    rows["datetime"] = pd.to_datetime(rows["datetime"])
    latest = rows.sort_values(["symbol", "datetime"], kind="stable").groupby("symbol", as_index=False).tail(1)
    return {str(row.symbol): float(row.close) for row in latest.itertuples(index=False)}


def _symbol_names(repo: DuckDBRepository) -> dict[str, str]:
    """Resolve durable ETF names by normalized code; missing names remain auditable codes."""
    metadata = repo.load_etf_theme_metadata()
    if metadata.empty:
        metadata = repo.load_latest_etf_names()
    if metadata.empty:
        return {}
    return {
        str(row.symbol).split(".")[0]: str(row.name)
        for row in metadata.itertuples(index=False)
        if getattr(row, "name", None)
    }


def _enrich_records(rows: list[dict[str, object]], symbol_names: dict[str, str]) -> list[dict[str, object]]:
    """Add display-only labels while preserving the raw audit identifiers and values."""
    enriched: list[dict[str, object]] = []
    for original in rows:
        row = dict(original)
        symbol = str(row.get("symbol") or "")
        row["display_name"] = symbol_names.get(symbol.split(".")[0], symbol)
        side = str(row.get("side") or "").lower()
        if side:
            row["side_display"] = SIDE_DISPLAY_NAMES.get(side, side)
        status = str(row.get("status") or "").lower()
        if status:
            row["status_display"] = ORDER_STATUS_DISPLAY_NAMES.get(status, status)
        if side == "sell":
            row["profit_loss"] = _durable_profit_loss(row)
        else:
            row["profit_loss"] = None
        enriched.append(row)
    return enriched


def _durable_profit_loss(row: dict[str, object]) -> float | None:
    """Expose only strategy-persisted sell P/L values; never infer a cost basis in the UI."""
    for key in ("profit_loss", "realized_pnl", "realized_profit_loss", "pnl"):
        value = row.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _records(frame: pd.DataFrame, limit: int) -> list[dict[str, object]]:
    """Convert durable audit frames to browser-safe records, retaining newest rows."""
    return [_json_value(record) for record in frame.tail(limit).to_dict(orient="records")]


def _latest_market_timestamp(accounts: list[dict[str, object]]) -> str | None:
    """Use durable equity/position timestamps, never the export clock, as data-as-of."""
    timestamps: list[pd.Timestamp] = []
    for account in accounts:
        for key in ("equity_curve", "positions"):
            for row in account.get(key, []):
                value = row.get("timestamp") if isinstance(row, dict) else None
                if value:
                    parsed = pd.Timestamp(value)
                    if not pd.isna(parsed):
                        timestamps.append(parsed)
    return max(timestamps).isoformat() if timestamps else None


def _combine_holdings(accounts: list[dict[str, object]]) -> list[dict[str, object]]:
    """Aggregate current account snapshots by symbol for the portfolio view."""
    combined: dict[str, dict[str, object]] = {}
    for account in accounts:
        strategy = str(account.get("id") or account.get("strategy_id") or "")
        for row in account.get("positions", []):
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("symbol") or "")
            quantity = float(row.get("quantity") or 0)
            if not symbol or quantity <= 0:
                continue
            item = combined.setdefault(symbol, {
                "symbol": symbol,
                "display_name": row.get("display_name") or symbol,
                "quantity": 0.0,
                "market_value": 0.0,
                "strategies": [],
            })
            item["quantity"] = float(item["quantity"]) + quantity
            item["market_value"] = float(item["market_value"]) + float(row.get("market_value") or 0)
            if strategy and strategy not in item["strategies"]:
                item["strategies"].append(strategy)
    return [
        {**item, "strategy_count": len(item["strategies"])}
        for _, item in sorted(combined.items())
    ]


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if hasattr(value, "item"):
        return _json_value(value.item())
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value
