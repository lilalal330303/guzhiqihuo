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
    return {
        "source": "local_paper_trading_audit",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "market_data_as_of": _latest_market_timestamp(account_snapshots),
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
    positions = _enrich_records(
        _records(decode_payload_frame(repo.load_paper_positions(panel.account_id)), limit), symbol_names,
    )
    orders = _enrich_records(
        _records(decode_payload_frame(repo.load_paper_orders(panel.account_id)), limit), symbol_names,
    )
    fills = _enrich_records(
        _records(decode_payload_frame(repo.load_paper_fills(panel.account_id)), limit), symbol_names,
    )
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
        "equity_curve": _records(repo.load_paper_equity(panel.account_id), limit),
        "positions": positions,
        "orders": orders,
        "fills": fills,
        "timeline": _records(build_execution_timeline(repo, panel.account_id, panel.strategy_id), limit),
        "exceptions": _records(decode_payload_frame(repo.load_paper_exceptions(panel.account_id)), limit),
    }


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
