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
    return {
        "source": "local_paper_trading_audit",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "accounts": [_account_snapshot(repo, account, panels[account.account_id], limit) for account in account_list],
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
    return {
        "id": panel.account_id,
        "strategy_id": panel.strategy_id,
        "display": {
            "name": panel.display_name,
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
        "positions": _records(decode_payload_frame(repo.load_paper_positions(panel.account_id)), limit),
        "orders": _records(decode_payload_frame(repo.load_paper_orders(panel.account_id)), limit),
        "fills": _records(decode_payload_frame(repo.load_paper_fills(panel.account_id)), limit),
        "timeline": _records(build_execution_timeline(repo, panel.account_id, panel.strategy_id), limit),
        "exceptions": _records(decode_payload_frame(repo.load_paper_exceptions(panel.account_id)), limit),
    }


def _records(frame: pd.DataFrame, limit: int) -> list[dict[str, object]]:
    """Convert durable audit frames to browser-safe records, retaining newest rows."""
    return [_json_value(record) for record in frame.tail(limit).to_dict(orient="records")]


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
