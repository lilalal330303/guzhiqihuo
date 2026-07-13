from __future__ import annotations

import pandas as pd
import quant_lab.research.paper_trading as paper_trading

from quant_lab.data.repository import DuckDBRepository
from quant_lab.research.paper_trading import (
    _consume_plan,
    _plans_for_event,
    _callback_participation_cap,
    _remaining_plan,
    _is_execution_minute,
    initialize_default_paper_accounts,
    run_paper_minute,
    run_paper_range,
)
from quant_lab.paper.execution import PaperOrder
from quant_lab.strategies.paper_v7k import V7KPaperAdapter
from quant_lab.strategies.paper_wufu_v12d import V12DPaperAdapter


def test_runner_isolates_accounts_when_one_is_data_blocked(tmp_path):
    repo = DuckDBRepository(tmp_path / "market.duckdb")
    initialize_default_paper_accounts(repo)

    results = run_paper_range(repo, "2026-07-13 13:10", "2026-07-13 13:11")

    assert {result.account_id for result in results} == {"v7k_wufu_qixing", "wufu_v12d"}
    assert {result.status for result in results} == {"blocked"}
    assert repo.load_paper_orders("v7k_wufu_qixing").empty
    assert repo.load_paper_orders("wufu_v12d").empty
    assert len(repo.load_paper_exceptions("v7k_wufu_qixing")) == 2
    assert len(repo.load_paper_exceptions("wufu_v12d")) == 2


def test_runner_is_idempotent_after_a_blocked_claim(tmp_path):
    repo = DuckDBRepository(tmp_path / "market.duckdb")
    initialize_default_paper_accounts(repo)
    timestamp = pd.Timestamp("2026-07-13 13:11")

    first = run_paper_minute(repo, "wufu_v12d", timestamp)
    second = run_paper_minute(repo, "wufu_v12d", timestamp)

    assert first.status == "blocked"
    assert second.status == "already_processed"
    assert len(repo.load_paper_exceptions("wufu_v12d")) == 1


def test_runner_releases_failed_blocked_minute_for_a_clean_retry(tmp_path, monkeypatch):
    repo = DuckDBRepository(tmp_path / "market.duckdb")
    initialize_default_paper_accounts(repo)
    timestamp = pd.Timestamp("2026-07-13 13:11")
    original_commit = repo.commit_paper_blocked_minute

    def fail_before_commit(*args, **kwargs):
        raise RuntimeError("simulated durable-write failure")

    monkeypatch.setattr(repo, "commit_paper_blocked_minute", fail_before_commit)
    failed = run_paper_minute(repo, "wufu_v12d", timestamp)
    monkeypatch.setattr(repo, "commit_paper_blocked_minute", original_commit)
    retried = run_paper_minute(repo, "wufu_v12d", timestamp)

    assert failed.status == "failed"
    assert retried.status == "blocked"
    assert repo.load_paper_exceptions("wufu_v12d")["reason"].tolist() == ["intent_missing"]


def test_runner_does_not_trade_outside_strategy_schedule(tmp_path):
    repo = DuckDBRepository(tmp_path / "market.duckdb")
    initialize_default_paper_accounts(repo)

    result = run_paper_minute(repo, "v7k_wufu_qixing", pd.Timestamp("2026-07-13 10:30"))

    assert result.status == "idle"
    assert repo.load_paper_orders("v7k_wufu_qixing").empty


def test_v7k_frozen_schedule_executes_on_the_same_trade_date_after_signal():
    adapter = V7KPaperAdapter()

    assert adapter.signal_minute == 1310
    assert _is_execution_minute(adapter, 1311)
    assert _is_execution_minute(adapter, 1340)
    assert _is_execution_minute(adapter, 1440)


def test_v12d_frozen_schedule_links_same_day_signal_to_full_execution_window():
    adapter = V12DPaperAdapter()

    assert adapter.signal_minute == 1310
    assert _is_execution_minute(adapter, 1311)
    assert _is_execution_minute(adapter, 1340)
    assert _is_execution_minute(adapter, 1410)
    assert _is_execution_minute(adapter, 1430)
    assert _is_execution_minute(adapter, 1440)
    assert _is_execution_minute(adapter, 1456)  # residual capacity continuation


def test_pending_plan_consumes_only_fills_from_its_own_callback():
    initial = _remaining_plan([PaperOrder("510300.SH", "buy", 1_000, 200, "partial")])
    remaining = _consume_plan(initial, [PaperOrder("510300.SH", "buy", 800, 200, "partial")])

    assert initial == [{"symbol": "510300.SH", "side": "buy", "remaining_quantity": 800, "plan_state": "capacity_split_active"}]
    assert remaining == [{"symbol": "510300.SH", "side": "buy", "remaining_quantity": 600, "plan_state": "capacity_split_active"}]


def test_v12d_force_callback_keeps_participation_cap_after_bypassing_trend_gate():
    payload = {"participation_cap": 0.25, "execution_rules": {"capacity_step_buffer": 0.98}}

    assert _callback_participation_cap(payload, event="force") == 0.245
    assert _callback_participation_cap(payload, event="capacity") == 0.245


def test_trend_and_force_release_waiting_orders_into_capacity_splits_for_later_minutes():
    waiting = [{"symbol": "510300.SH", "side": "buy", "remaining_quantity": 400, "plan_state": "trend_waiting"}]

    assert _plans_for_event(waiting, "capacity") == []
    released = _plans_for_event(waiting, "trend")
    continued = _consume_plan(released, [PaperOrder("510300.SH", "buy", 400, 100, "partial")])

    assert continued == [{"symbol": "510300.SH", "side": "buy", "remaining_quantity": 300, "plan_state": "capacity_split_active"}]
    assert _plans_for_event(continued, "capacity") == continued


def test_initial_rebalance_is_not_short_circuited_when_old_holding_hits_stop():
    stopped = {"588220"}

    assert paper_trading._should_execute_stop_only("initial", stopped) is False
    assert paper_trading._should_execute_stop_only("stop_monitor", stopped) is True
    assert paper_trading._should_execute_stop_only("capacity", stopped) is True
