"""Idempotent, local-only minute runner for the two ETF paper accounts."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
import ast
import json
from functools import lru_cache
from pathlib import Path

import pandas as pd

from quant_lab.data.repository import DuckDBRepository
from quant_lab.paper.data_guard import validate_strategy_data
from quant_lab.paper.execution import ExecutionConfig, execute_order_plan, execute_target_weights
from quant_lab.paper.models import PaperAccount
from quant_lab.paper.state import AccountState
from quant_lab.strategies.paper_v7k import StrategyIntent, V7KInputContext, V7KPaperAdapter
from quant_lab.strategies.paper_wufu_v12d import V12DInputContext, V12DPaperAdapter


DEFAULT_PAPER_ACCOUNTS = (
    PaperAccount("v7k_wufu_qixing", "v7k_wufu_qixing", 1_000_000.0),
    PaperAccount("wufu_v12d", "wufu_v12d", 1_000_000.0),
)


@dataclass(frozen=True)
class PaperMinuteResult:
    account_id: str
    timestamp: pd.Timestamp
    status: str
    detail: str | None = None


def initialize_default_paper_accounts(repo: DuckDBRepository) -> None:
    """Create the two independently funded accounts without resetting either."""
    for account in DEFAULT_PAPER_ACCOUNTS:
        repo.ensure_paper_account(account)


def run_paper_minute(repo: DuckDBRepository, account_id: str, timestamp: pd.Timestamp) -> PaperMinuteResult:
    """Process at most one allowed strategy event and persist its complete audit trail."""
    timestamp = pd.Timestamp(timestamp).floor("min")
    account = repo.load_paper_account(account_id)
    adapter = _adapter_for(account)
    minute = int(timestamp.strftime("%H%M"))
    is_signal = minute == adapter.signal_minute
    event = _execution_event(adapter, minute)
    is_execution = event in {"initial", "capacity", "trend", "force"}
    is_stop_monitor = event == "stop_monitor"
    if not (is_signal or is_execution or is_stop_monitor):
        return PaperMinuteResult(account_id, timestamp, "idle")
    if not repo.claim_paper_minute(account_id, adapter.strategy_id, timestamp):
        return PaperMinuteResult(account_id, timestamp, "already_processed")

    try:
        positions = repo.load_latest_paper_position_state(account_id)
        payload = None if is_signal else repo.load_paper_intent(account_id, adapter.strategy_id, timestamp.normalize())
        if not is_signal and payload is None:
            repo.commit_paper_blocked_minute(account_id, adapter.strategy_id, timestamp, "intent_missing", {"trade_date": timestamp.strftime("%Y-%m-%d")})
            return PaperMinuteResult(account_id, timestamp, "blocked", "intent_missing")
        intent_symbols = [] if payload is None else list(payload.get("target_weights", {}))
        plan = [] if payload is None else repo.load_paper_pending_order_plan(account_id, adapter.strategy_id, timestamp)
        symbols = list(dict.fromkeys(adapter.required_symbols(timestamp) + intent_symbols + list(positions) + [str(row["symbol"]) for row in plan]))
        check = validate_strategy_data(
            repo, symbols, timestamp.normalize(), adapter.required_minutes(timestamp), adapter.daily_lookback
        )
        if not check.ok:
            repo.commit_paper_blocked_minute(account_id, adapter.strategy_id, timestamp, check.reason or "data_missing", check.details)
            return PaperMinuteResult(account_id, timestamp, "blocked", check.reason)

        if is_signal:
            intent = _generate_intent(repo, adapter, timestamp, symbols)
            repo.commit_paper_signal_minute(account_id, adapter.strategy_id, timestamp, _intent_payload(intent))
            return PaperMinuteResult(account_id, timestamp, "signaled")

        if event == "trend" and not _has_complete_minute_window(repo, symbols, timestamp, 30):
            repo.commit_paper_blocked_minute(account_id, adapter.strategy_id, timestamp, "data_missing", {"reason": "incomplete_trend_window", "minutes": 30})
            return PaperMinuteResult(account_id, timestamp, "blocked", "data_missing")

        stopped_symbols = _stopped_symbols(repo, account_id, timestamp, positions, symbols, _stop_threshold(adapter))
        if is_stop_monitor:
            if stopped_symbols:
                result = execute_order_plan(AccountState(account.cash, positions), _stop_plan(positions, stopped_symbols), repo.load_minute_bars(symbols, timestamp.strftime("%Y-%m-%d"), timestamp.strftime("%Y-%m-%d")).query("minute == @minute"), ExecutionConfig(), participation_cap=None)
                _commit_execution(repo, account, adapter, timestamp, positions, result, _without_stopped_plan(plan, stopped_symbols))
                return PaperMinuteResult(account_id, timestamp, "stopped")
            repo.complete_paper_minute(account_id, adapter.strategy_id, timestamp)
            return PaperMinuteResult(account_id, timestamp, "monitored")

        target_weights = {str(symbol): float(weight) for symbol, weight in payload["target_weights"].items()}
        bars = repo.load_minute_bars(symbols, timestamp.strftime("%Y-%m-%d"), timestamp.strftime("%Y-%m-%d")).query("minute == @minute")
        if _should_execute_stop_only(event, stopped_symbols):
            result = execute_order_plan(AccountState(account.cash, positions), _stop_plan(positions, stopped_symbols), bars, ExecutionConfig(), participation_cap=None)
            _commit_execution(repo, account, adapter, timestamp, positions, result, _without_stopped_plan(plan, stopped_symbols))
            return PaperMinuteResult(account_id, timestamp, "stopped")
        cfg = ExecutionConfig(cash_buffer=float(payload.get("execution_rules", {}).get("cash_buffer", 0.998)))
        cap = _callback_participation_cap(payload, event=event)
        if event == "initial":
            result = execute_target_weights(AccountState(account.cash, positions), target_weights, bars, cfg, participation_cap=cap)
            pending = _remaining_plan(result.orders)
        elif target_weights == {}:
            result = execute_target_weights(AccountState(account.cash, positions), {}, bars, cfg, participation_cap=None)
            pending = []
        else:
            # A later callback consumes only the durable residual plan.  It must
            # never run a fresh target-weight rebalance.
            executable_plan = _plans_for_event(plan, event)
            result = execute_order_plan(AccountState(account.cash, positions), executable_plan, bars, cfg, participation_cap=cap)
            pending = _merge_unexecuted_plan(plan, executable_plan, _consume_plan(executable_plan, result.orders))
        _commit_execution(repo, account, adapter, timestamp, positions, result, pending)
        return PaperMinuteResult(account_id, timestamp, "executed")
    except Exception as exc:  # An account error is durable and never aborts the range runner.
        # Terminal-minute commits are all-or-nothing.  Releasing an uncompleted
        # claim makes the same minute safely retryable; completed transactions
        # are unaffected because release only removes a claimed clock row.
        repo.release_paper_minute(account_id, adapter.strategy_id, timestamp)
        return PaperMinuteResult(account_id, timestamp, "failed", str(exc))


def run_paper_range(
    repo: DuckDBRepository, start: str | pd.Timestamp, end: str | pd.Timestamp, account_ids: list[str] | None = None
) -> list[PaperMinuteResult]:
    """Run every minute in a range; a failure in one account cannot stop another."""
    initialize_default_paper_accounts(repo)
    ids = account_ids or [account.account_id for account in DEFAULT_PAPER_ACCOUNTS]
    results: list[PaperMinuteResult] = []
    for timestamp in pd.date_range(pd.Timestamp(start).floor("min"), pd.Timestamp(end).floor("min"), freq="min"):
        for account_id in ids:
            try:
                result = run_paper_minute(repo, account_id, timestamp)
            except Exception as exc:
                # Unknown/misconfigured accounts are isolated from the rest.
                result = PaperMinuteResult(account_id, timestamp, "failed", str(exc))
            if result.status != "idle":
                results.append(result)
    return results


def _adapter_for(account: PaperAccount) -> V7KPaperAdapter | V12DPaperAdapter:
    if account.account_id == "v7k_wufu_qixing" and account.strategy_id == "v7k_wufu_qixing":
        return V7KPaperAdapter()
    if account.account_id == "wufu_v12d" and account.strategy_id == "wufu_v12d":
        return V12DPaperAdapter()
    raise ValueError(f"unsupported paper account: {account.account_id}/{account.strategy_id}")


def _is_execution_minute(adapter: V7KPaperAdapter | V12DPaperAdapter, minute: int) -> bool:
    return _execution_event(adapter, minute) in {"initial", "capacity", "trend", "force"}


def _execution_event(adapter: V7KPaperAdapter | V12DPaperAdapter, minute: int) -> str | None:
    if minute == adapter.execution_start_minute:
        return "initial"
    # Frozen five-slice plan: the four remaining slices are its only automatic
    # capacity callbacks; later orders are explicit trend/force callbacks.
    if 1312 <= minute <= 1315:
        return "capacity"
    if minute in (1340, 1410, 1430):
        return "trend"
    if minute == 1440:
        return "force"
    # After force bypasses the trend gate, residual lots still follow the same
    # minute-volume cap through the permitted stop-monitor close window.
    if 1441 <= minute <= 1456:
        return "capacity"
    if 1301 <= minute <= 1456 and 0 <= minute % 100 < 60:
        return "stop_monitor"
    return None


def _stop_threshold(adapter: V7KPaperAdapter | V12DPaperAdapter) -> float:
    rules = adapter.execution_rules
    return float(rules.get("stop_loss_threshold", rules.get("fixed_stop_loss_threshold", 0.0)))


def _should_execute_stop_only(event: str | None, stopped_symbols: set[str]) -> bool:
    """A frozen initial rebalance still runs after selling a stopped old holding.

    ``execute_target_weights`` already sells before buying, so the initial event
    can safely rotate from the stopped symbol into the day's frozen target.
    Later callbacks must remain stop-only to avoid recalculating target weights.
    """
    return bool(stopped_symbols) and event != "initial"


def _generate_intent(repo: DuckDBRepository, adapter: V7KPaperAdapter | V12DPaperAdapter, timestamp: pd.Timestamp, symbols: list[str]) -> StrategyIntent:
    # The query ends on T-1. This duplicates the adapter's own defensive filter
    # and makes same-day daily-close leakage impossible at the assembly boundary.
    day = timestamp.normalize()
    prices = repo.load_prices_for_symbols(
        symbols, (day - pd.Timedelta(days=max(adapter.daily_lookback * 4, 180))).strftime("%Y-%m-%d"),
        (day - pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
    )
    if isinstance(adapter, V7KPaperAdapter):
        metadata = repo.load_etf_theme_metadata(symbols)
        theme_by_symbol = {str(row.symbol): str(row.theme_bucket) for row in metadata.itertuples()}
        context = V7KInputContext(
            dynamic_snapshots=repo.load_dynamic_pool_snapshots("1900-01-01", (day - pd.Timedelta(days=1)).strftime("%Y-%m-%d")),
            theme_by_symbol=theme_by_symbol,
        )
        return adapter.intent(prices, day, context)
    return adapter.intent(prices, day, V12DInputContext(weak_states=_v12d_frozen_weak_states(prices["trade_date"])))


@lru_cache(maxsize=1)
def _v12d_frozen_weak_ranges() -> tuple[tuple[str, str], ...]:
    """Read only the frozen V12D calendar literal; never execute platform code."""
    source = Path(__file__).resolve().parents[3] / "reports" / "ths_wufu_fast_v12d_compact_capacity.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "EXTERNAL_WEAK_RANGES" for target in node.targets):
            return tuple(tuple(item) for item in ast.literal_eval(node.value))
    raise ValueError("frozen V12D weak calendar is missing")


def _v12d_frozen_weak_states(trade_dates: pd.Series) -> pd.DataFrame:
    days = pd.to_datetime(trade_dates).dt.normalize().drop_duplicates()
    ranges = [(pd.Timestamp(start), pd.Timestamp(end)) for start, end in _v12d_frozen_weak_ranges()]
    return pd.DataFrame({"trade_date": days, "is_weak": [any(start <= day <= end for start, end in ranges) for day in days]})


def _stop_loss_due(repo: DuckDBRepository, account_id: str, timestamp: pd.Timestamp, positions: dict[str, int], symbols: list[str], threshold: float) -> bool:
    return bool(_stopped_symbols(repo, account_id, timestamp, positions, symbols, threshold))


def _stopped_symbols(repo: DuckDBRepository, account_id: str, timestamp: pd.Timestamp, positions: dict[str, int], symbols: list[str], threshold: float) -> set[str]:
    if not positions or threshold <= 0:
        return set()
    bars = repo.load_minute_bars(symbols, timestamp.strftime("%Y-%m-%d"), timestamp.strftime("%Y-%m-%d"))
    closes = {str(row.symbol): float(row.close) for row in bars[bars["minute"] == int(timestamp.strftime("%H%M"))].itertuples()}
    fills = repo.load_paper_fills(account_id)
    stopped: set[str] = set()
    for symbol in positions:
        rows = fills[fills["symbol"] == symbol]
        prices: list[float] = []
        for payload in rows.get("payload", []):
            value = json.loads(payload) if isinstance(payload, str) else payload
            if str(value.get("side")) == "buy":
                prices.append(float(value["price"]))
        if prices and closes.get(symbol, float("inf")) <= prices[-1] * threshold:
            stopped.add(symbol)
    return stopped


def _stop_plan(positions: dict[str, int], stopped_symbols: set[str]) -> list[dict[str, Any]]:
    return [{"symbol": symbol, "side": "sell", "remaining_quantity": int(positions[symbol])} for symbol in sorted(stopped_symbols) if positions.get(symbol, 0) >= 100]


def _without_stopped_plan(plan: list[dict[str, Any]], stopped_symbols: set[str]) -> list[dict[str, Any]]:
    return [row for row in plan if str(row["symbol"]) not in stopped_symbols]


def _intent_payload(intent: StrategyIntent) -> dict[str, Any]:
    payload = asdict(intent)
    payload["trade_date"] = pd.Timestamp(intent.trade_date).isoformat()
    return payload


def _callback_participation_cap(payload: dict[str, Any], *, event: str | None = None) -> float | None:
    """Return the frozen per-minute capacity cap (V12D's 0.25 * 0.98)."""
    cap = payload.get("participation_cap")
    if cap is None:
        cap = payload.get("execution_rules", {}).get("participation_cap")
    if cap is None:
        return None
    rules = payload.get("execution_rules", {})
    return float(cap) * float(rules.get("capacity_step_buffer", 1.0))


def _remaining_plan(orders: list[Any]) -> list[dict[str, Any]]:
    """Turn the initial callback's unfilled quantities into durable rows."""
    rows = []
    for order in orders:
        requested = int(order.requested_quantity)
        remaining = max(0, requested - int(order.quantity))
        if remaining >= 100:
            rows.append({"symbol": order.symbol, "side": order.side, "remaining_quantity": remaining, "plan_state": "capacity_split_active"})
    return rows


def _consume_plan(plan: list[dict[str, Any]], orders: list[Any]) -> list[dict[str, Any]]:
    """Subtract this callback's fills from its persisted plan, without replanning."""
    filled = {(str(order.symbol), str(order.side)): int(order.quantity) for order in orders}
    remaining = []
    for row in plan:
        quantity = int(row["remaining_quantity"]) - filled.get((str(row["symbol"]), str(row["side"])), 0)
        if quantity >= 100:
            remaining.append({"symbol": str(row["symbol"]), "side": str(row["side"]), "remaining_quantity": quantity, "plan_state": "capacity_split_active"})
    return remaining


def _plans_for_event(plan: list[dict[str, Any]], event: str | None) -> list[dict[str, Any]]:
    """Capacity minutes consume active splits; gates release waiting residuals."""
    if event in {"trend", "force"}:
        return [dict(row, plan_state="capacity_split_active") for row in plan]
    return [row for row in plan if row.get("plan_state", "capacity_split_active") == "capacity_split_active"]


def _merge_unexecuted_plan(original: list[dict[str, Any]], executed: list[dict[str, Any]], residual: list[dict[str, Any]]) -> list[dict[str, Any]]:
    executed_keys = {(str(row["symbol"]), str(row["side"])) for row in executed}
    untouched = [row for row in original if (str(row["symbol"]), str(row["side"])) not in executed_keys]
    return untouched + residual


def _has_complete_minute_window(repo: DuckDBRepository, symbols: list[str], timestamp: pd.Timestamp, minutes: int) -> bool:
    if not symbols:
        return True
    window = repo.load_minute_window(symbols, timestamp, minutes)
    expected = set(pd.date_range(timestamp - pd.Timedelta(minutes=minutes - 1), timestamp, freq="min"))
    return all(set(pd.to_datetime(window[window["symbol"] == symbol]["datetime"])) == expected for symbol in symbols)


def _persist_execution(repo: DuckDBRepository, account: PaperAccount, adapter: Any, timestamp: pd.Timestamp, prior_positions: dict[str, int], execution: Any) -> None:
    repo.record_paper_orders(account.account_id, adapter.strategy_id, timestamp, [asdict(order) for order in execution.orders])
    repo.record_paper_fills(account.account_id, adapter.strategy_id, timestamp, [asdict(fill) for fill in execution.fills])
    # Store zero quantity tombstones so a later restart reconstructs this exact snapshot.
    symbols = sorted(set(prior_positions) | set(execution.state.positions))
    repo.save_paper_positions(
        account.account_id, adapter.strategy_id, timestamp,
        [{"symbol": symbol, "quantity": int(execution.state.positions.get(symbol, 0))} for symbol in symbols],
    )
    bars = repo.load_minute_bars(symbols, timestamp.strftime("%Y-%m-%d"), timestamp.strftime("%Y-%m-%d")) if symbols else pd.DataFrame()
    close_by_symbol = {str(row.symbol): float(row.close) for row in bars[bars["minute"] == int(timestamp.strftime("%H%M"))].itertuples()} if not bars.empty else {}
    equity = execution.state.cash + sum(quantity * close_by_symbol.get(symbol, 0.0) for symbol, quantity in execution.state.positions.items())
    repo.update_paper_account_cash(account.account_id, execution.state.cash)
    repo.save_paper_equity(account.account_id, adapter.strategy_id, timestamp, execution.state.cash, equity)


def _commit_execution(repo: DuckDBRepository, account: PaperAccount, adapter: Any, timestamp: pd.Timestamp, prior_positions: dict[str, int], execution: Any, pending_plan: list[dict[str, Any]]) -> None:
    symbols = sorted(set(prior_positions) | set(execution.state.positions))
    bars = repo.load_minute_bars(symbols, timestamp.strftime("%Y-%m-%d"), timestamp.strftime("%Y-%m-%d")) if symbols else pd.DataFrame()
    close_by_symbol = {str(row.symbol): float(row.close) for row in bars[bars["minute"] == int(timestamp.strftime("%H%M"))].itertuples()} if not bars.empty else {}
    equity = execution.state.cash + sum(quantity * close_by_symbol.get(symbol, 0.0) for symbol, quantity in execution.state.positions.items())
    repo.commit_paper_minute(
        account.account_id, adapter.strategy_id, timestamp,
        cash=execution.state.cash, orders=[asdict(order) for order in execution.orders], fills=[asdict(fill) for fill in execution.fills],
        positions=[{"symbol": symbol, "quantity": int(execution.state.positions.get(symbol, 0))} for symbol in symbols],
        equity=equity, pending_order_plan=pending_plan,
    )
