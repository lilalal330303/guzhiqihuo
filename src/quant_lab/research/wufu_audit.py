from __future__ import annotations

import json

import pandas as pd


def audit_joinquant_dynamic_pool(
    joinquant_targets: pd.DataFrame,
    local_targets: pd.DataFrame,
    dynamic_snapshots: pd.DataFrame,
) -> pd.DataFrame:
    """Compare JoinQuant's daily target with local dynamic pool and candidates."""
    if joinquant_targets.empty:
        return pd.DataFrame()
    jq = _normalize_target_frame(joinquant_targets, "jq_symbol")
    local = _normalize_target_frame(local_targets, "local_target")
    candidates = _candidate_lookup(local_targets)
    snapshots = _snapshot_lookup(dynamic_snapshots)

    rows: list[dict[str, object]] = []
    for row in jq.itertuples(index=False):
        trade_date = pd.Timestamp(row.trade_date).normalize()
        jq_symbol = getattr(row, "jq_symbol")
        local_row = local[local["trade_date"] == trade_date]
        local_target = None if local_row.empty else local_row.iloc[0]["local_target"]
        snapshot = snapshots.get(trade_date, {})
        candidate = candidates.get((trade_date, jq_symbol), {})
        in_dynamic = jq_symbol in snapshot
        in_candidates = bool(candidate)
        if jq_symbol == local_target:
            reason = "matched_target"
        elif in_candidates:
            reason = "in_candidates_not_top"
        elif in_dynamic:
            reason = "in_dynamic_pool_not_candidate"
        else:
            reason = "not_in_local_dynamic_pool"
        rows.append(
            {
                "trade_date": trade_date,
                "jq_symbol": jq_symbol,
                "local_target": local_target,
                "target_match": jq_symbol == local_target,
                "jq_in_dynamic_pool": in_dynamic,
                "jq_dynamic_rank": snapshot.get(jq_symbol, {}).get("rank"),
                "jq_industry_key": snapshot.get(jq_symbol, {}).get("industry_key"),
                "jq_avg_amount": snapshot.get(jq_symbol, {}).get("avg_amount"),
                "jq_in_candidates": in_candidates,
                "jq_candidate_rank": candidate.get("rank"),
                "jq_candidate_score": candidate.get("momentum_score"),
                "reason": reason,
            }
        )
    return pd.DataFrame(rows)


def _normalize_target_frame(frame: pd.DataFrame, output_column: str) -> pd.DataFrame:
    rows = frame.copy()
    rows["trade_date"] = pd.to_datetime(rows["trade_date"]).dt.normalize()
    source_column = "target_symbol" if "target_symbol" in rows.columns else output_column
    rows[output_column] = rows[source_column].astype(str).str[:6]
    return rows[["trade_date", output_column]].drop_duplicates("trade_date")


def _candidate_lookup(local_targets: pd.DataFrame) -> dict[tuple[pd.Timestamp, str], dict[str, object]]:
    if local_targets.empty or "candidates_json" not in local_targets.columns:
        return {}
    lookup: dict[tuple[pd.Timestamp, str], dict[str, object]] = {}
    rows = local_targets.copy()
    rows["trade_date"] = pd.to_datetime(rows["trade_date"]).dt.normalize()
    for row in rows.itertuples(index=False):
        raw = getattr(row, "candidates_json", "[]") or "[]"
        try:
            candidates = json.loads(raw)
        except json.JSONDecodeError:
            candidates = []
        for candidate in candidates:
            symbol = str(candidate.get("symbol", ""))[:6]
            if symbol:
                lookup[(row.trade_date, symbol)] = candidate
    return lookup


def _snapshot_lookup(dynamic_snapshots: pd.DataFrame) -> dict[pd.Timestamp, dict[str, dict[str, object]]]:
    if dynamic_snapshots.empty:
        return {}
    rows = dynamic_snapshots.copy()
    rows["trade_date"] = pd.to_datetime(rows["trade_date"]).dt.normalize()
    rows["symbol"] = rows["symbol"].astype(str).str[:6]
    lookup: dict[pd.Timestamp, dict[str, dict[str, object]]] = {}
    for row in rows.itertuples(index=False):
        date_lookup = lookup.setdefault(row.trade_date, {})
        date_lookup[row.symbol] = {
            "rank": int(row.rank),
            "industry_key": getattr(row, "industry_key", None),
            "avg_amount": float(row.avg_amount),
        }
    return lookup
