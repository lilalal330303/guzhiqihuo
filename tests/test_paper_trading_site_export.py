import importlib.util
import json
import subprocess
import sys
import types

import pandas as pd
import pytest

import quant_lab.research.paper_trading_site_export as site_export
from quant_lab.data.repository import DuckDBRepository
from quant_lab.paper.models import PaperAccount


def test_site_exporter_module_is_available():
    """The static-site snapshot exporter is a supported research interface."""
    assert importlib.util.find_spec("quant_lab.research.paper_trading_site_export") is not None


def test_site_exporter_exposes_the_snapshot_and_export_interfaces():
    assert callable(getattr(site_export, "build_site_snapshot", None))
    assert callable(getattr(site_export, "export_site_snapshot", None))


def _seed_audit(repo, account):
    timestamp = pd.Timestamp("2026-07-13 14:40")
    repo.ensure_paper_account(account)
    repo.update_paper_account_cash(account.account_id, 800)
    repo.record_paper_intent(account.account_id, account.strategy_id, timestamp, {"signal": "risk_on"})
    repo.save_paper_positions(account.account_id, account.strategy_id, timestamp, [
        {"symbol": "510300.SH", "quantity": 100, "market_value": 200},
    ])
    repo.record_paper_orders(account.account_id, account.strategy_id, timestamp, [
        {"order_id": f"order-{account.account_id}", "symbol": "510300.SH", "side": "buy", "status": "filled"},
    ])
    repo.record_paper_fills(account.account_id, account.strategy_id, timestamp, [
        {"fill_id": f"fill-{account.account_id}", "symbol": "510300.SH", "quantity": 100, "price": 2.0},
    ])
    repo.save_paper_equity(account.account_id, account.strategy_id, timestamp, cash=800, equity=1_000)
    repo.record_paper_exception(
        account.account_id, account.strategy_id, timestamp, "capacity_limited", {"remaining": 200},
    )


def test_build_snapshot_dynamically_includes_all_accounts_and_durable_audit_data(tmp_path, monkeypatch):
    repo = DuckDBRepository(tmp_path / "market.duckdb")
    accounts = (PaperAccount("alpha", "alpha_strategy", 1_000), PaperAccount("beta", "beta_strategy", 2_000))
    for account in accounts:
        _seed_audit(repo, account)
    monkeypatch.setattr(
        "quant_lab.app.paper_trading_view_model.assess_readiness",
        lambda _: pd.DataFrame([{"account_id": account.account_id, "reason": None} for account in accounts]),
    )
    database_before = (tmp_path / "market.duckdb").read_bytes()

    snapshot = site_export.build_site_snapshot(repo, accounts=accounts)

    assert snapshot["source"] == "local_paper_trading_audit"
    assert pd.Timestamp(snapshot["generated_at"]).tzinfo is not None
    assert [account["id"] for account in snapshot["accounts"]] == ["alpha", "beta"]
    alpha = snapshot["accounts"][0]
    assert alpha["strategy_id"] == "alpha_strategy"
    assert alpha["metrics"]["cash"] == 800.0
    assert alpha["equity_curve"][0]["timestamp"] == "2026-07-13T14:40:00"
    assert alpha["positions"][0]["symbol"] == "510300.SH"
    assert alpha["orders"][0]["order_id"] == "order-alpha"
    assert alpha["fills"][0]["fill_id"] == "fill-alpha"
    assert [event["event_type"] for event in alpha["timeline"]] == ["signal", "order", "fill", "exception"]
    assert alpha["exceptions"][0]["reason"] == "capacity_limited"
    assert json.loads(json.dumps(snapshot)) == snapshot
    assert (tmp_path / "market.duckdb").read_bytes() == database_before


def test_export_is_atomic_and_preserves_existing_file_when_serialization_fails(tmp_path, monkeypatch):
    repo = DuckDBRepository(tmp_path / "market.duckdb")
    account = PaperAccount("alpha", "alpha_strategy", 1_000)
    _seed_audit(repo, account)
    monkeypatch.setattr(
        "quant_lab.app.paper_trading_view_model.assess_readiness",
        lambda _: pd.DataFrame([{"account_id": "alpha", "reason": None}]),
    )
    output_path = tmp_path / "snapshot.json"
    output_path.write_text("prior snapshot", encoding="utf-8")
    monkeypatch.setattr(
        site_export,
        "json",
        types.SimpleNamespace(dumps=lambda *args, **kwargs: (_ for _ in ()).throw(TypeError("bad json"))),
        raising=False,
    )

    with pytest.raises(TypeError, match="bad json"):
        site_export.export_site_snapshot(repo, output_path, accounts=[account])

    assert output_path.read_text(encoding="utf-8") == "prior snapshot"


def test_export_cli_exposes_an_output_option():
    result = subprocess.run(
        [sys.executable, "reports/export_paper_trading_site.py", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "--output" in result.stdout


def test_snapshot_exposes_market_data_as_of_and_combines_holdings_by_symbol(tmp_path, monkeypatch):
    repo = DuckDBRepository(tmp_path / "market.duckdb")
    accounts = (PaperAccount("alpha", "alpha_strategy", 1_000), PaperAccount("beta", "beta_strategy", 1_000))
    for account in accounts:
        _seed_audit(repo, account)
    monkeypatch.setattr(
        "quant_lab.app.paper_trading_view_model.assess_readiness",
        lambda _: pd.DataFrame([{"account_id": account.account_id, "reason": None} for account in accounts]),
    )

    snapshot = site_export.build_site_snapshot(repo, accounts=accounts)

    assert snapshot["market_data_as_of"] == "2026-07-13T14:40:00"
    assert snapshot["combined_holdings"] == [{
        "symbol": "510300.SH", "display_name": "510300.SH", "quantity": 200.0, "market_value": 400.0,
        "strategy_count": 2, "strategies": ["alpha", "beta"],
    }]


def test_snapshot_uses_chinese_strategy_and_etf_display_fields_without_replacing_audit_ids(tmp_path, monkeypatch):
    repo = DuckDBRepository(tmp_path / "market.duckdb")
    accounts = (
        PaperAccount("v7k_wufu_qixing", "v7k_wufu_qixing", 1_000),
        PaperAccount("wufu_v12d", "wufu_v12d", 1_000),
    )
    for account in accounts:
        _seed_audit(repo, account)
    repo.replace_etf_theme_metadata(
        pd.DataFrame([{
            "symbol": "510300", "name": "沪深300ETF", "theme_bucket": "宽基",
            "theme_confidence": 1.0, "classification_method": "test",
            "is_risk_excluded": False, "is_defensive": False,
        }]),
        source="test",
    )
    monkeypatch.setattr(
        "quant_lab.app.paper_trading_view_model.assess_readiness",
        lambda _: pd.DataFrame([{"account_id": account.account_id, "reason": None} for account in accounts]),
    )

    snapshot = site_export.build_site_snapshot(repo, accounts=accounts)

    assert [item["display"]["name"] for item in snapshot["accounts"]] == ["福星ETF", "五福ETF"]
    assert snapshot["accounts"][0]["id"] == "v7k_wufu_qixing"
    assert snapshot["accounts"][0]["positions"][0]["display_name"] == "沪深300ETF"
    assert snapshot["accounts"][0]["orders"][0]["display_name"] == "沪深300ETF"
    assert snapshot["combined_holdings"][0]["display_name"] == "沪深300ETF"


def test_snapshot_keeps_sell_profit_loss_empty_unless_durable_fill_supplies_it(tmp_path, monkeypatch):
    repo = DuckDBRepository(tmp_path / "market.duckdb")
    account = PaperAccount("alpha", "alpha", 1_000)
    _seed_audit(repo, account)
    timestamp = pd.Timestamp("2026-07-13 14:45")
    repo.record_paper_fills(account.account_id, account.strategy_id, timestamp, [{
        "fill_id": "sell-fill", "symbol": "510300.SH", "side": "sell", "quantity": 50,
        "price": 2.2, "realized_pnl": 10.0,
    }])
    monkeypatch.setattr(
        "quant_lab.app.paper_trading_view_model.assess_readiness",
        lambda _: pd.DataFrame([{"account_id": "alpha", "reason": None}]),
    )

    snapshot = site_export.build_site_snapshot(repo, accounts=[account])

    fills = {row["fill_id"]: row for row in snapshot["accounts"][0]["fills"]}
    assert fills["sell-fill"]["profit_loss"] == 10.0
    assert fills["fill-alpha"]["profit_loss"] is None


def test_snapshot_uses_only_latest_position_snapshot_and_latest_minute_price(tmp_path, monkeypatch):
    repo = DuckDBRepository(tmp_path / "market.duckdb")
    account = PaperAccount("alpha", "alpha", 1_000)
    _seed_audit(repo, account)
    latest = pd.Timestamp("2026-07-13 14:50")
    repo.save_paper_positions(account.account_id, account.strategy_id, latest, [
        {"symbol": "510300.SH", "quantity": 40, "market_value": 0},
        {"symbol": "159915.SZ", "quantity": 0, "market_value": 0},
    ])
    repo.save_paper_equity(account.account_id, account.strategy_id, latest, cash=800, equity=940)
    repo.upsert_minute_bars(pd.DataFrame([{
        "symbol": "510300.SH", "trade_date": latest.date(), "minute": 1449,
        "datetime": latest - pd.Timedelta(minutes=1), "open": 3.4, "high": 3.6,
        "low": 3.3, "close": 3.5, "volume": 100, "amount": 350,
    }]), source="test")
    monkeypatch.setattr(
        "quant_lab.app.paper_trading_view_model.assess_readiness",
        lambda _: pd.DataFrame([{"account_id": "alpha", "reason": None}]),
    )

    snapshot = site_export.build_site_snapshot(repo, accounts=[account])

    positions = snapshot["accounts"][0]["positions"]
    assert len(positions) == 1
    assert positions[0]["timestamp"] == "2026-07-13T14:50:00"
    assert positions[0]["symbol"] == "510300.SH"
    assert positions[0]["quantity"] == 40
    assert positions[0]["latest_price"] == 3.5
    assert positions[0]["market_value"] == 140.0
    assert snapshot["combined_holdings"] == [{
        "symbol": "510300.SH", "display_name": "510300.SH", "quantity": 40.0,
        "market_value": 140.0, "strategies": ["alpha"], "strategy_count": 1,
    }]


def test_visible_audit_records_hide_rejected_orders_and_intent_missing_noise():
    orders = [
        {"order_id": "ok", "status": "filled"},
        {"order_id": "partial", "status": "partial"},
        {"order_id": "hidden", "status": "rejected"},
    ]
    timeline = [
        {"audit_id": "keep", "event": "filled"},
        {"audit_id": "hide-event", "event": "intent_missing"},
        {"audit_id": "hide-reason", "reason": "intent_missing"},
    ]

    assert [row["order_id"] for row in site_export._visible_orders(orders)] == ["ok", "partial"]
    assert [row["audit_id"] for row in site_export._visible_timeline(timeline)] == ["keep"]


def test_fill_ledger_reconstructs_average_cost_and_realized_sell_profit_after_commissions():
    fills = [
        {"fill_id": "b1", "timestamp": "2026-07-07T13:11:00", "symbol": "510300", "side": "buy", "quantity": 100, "price": 2.0, "commission": 5.0},
        {"fill_id": "b2", "timestamp": "2026-07-08T13:11:00", "symbol": "510300", "side": "buy", "quantity": 100, "price": 3.0, "commission": 5.0},
        {"fill_id": "s1", "timestamp": "2026-07-09T13:11:00", "symbol": "510300", "side": "sell", "quantity": 150, "price": 4.0, "commission": 6.0},
    ]

    enriched = site_export._fill_ledger(fills)

    sell = enriched[-1]
    assert sell["average_cost"] == pytest.approx(2.55)
    assert sell["profit_loss"] == pytest.approx(211.5)
    assert sell["remaining_quantity"] == 50


def test_daily_equity_bars_aggregate_intraday_equity_to_ohlc():
    curve = [
        {"timestamp": "2026-07-13T13:11:00", "equity": 1000},
        {"timestamp": "2026-07-13T14:10:00", "equity": 980},
        {"timestamp": "2026-07-13T14:56:00", "equity": 1010},
        {"timestamp": "2026-07-14T13:11:00", "equity": 1020},
        {"timestamp": "2026-07-14T14:56:00", "equity": 1005},
    ]

    bars = site_export._daily_equity_bars(curve)

    assert {key: value for key, value in bars[0].items() if key != "return"} == {
        "trade_date": "2026-07-13", "open": 1000.0, "high": 1010.0,
        "low": 980.0, "close": 1010.0, "change": 10.0,
    }
    assert bars[0]["return"] == pytest.approx(0.01)
    assert bars[1]["open"] == 1020.0
    assert bars[1]["close"] == 1005.0


def test_daily_position_history_keeps_zero_quantity_exit_and_symbol_pnl():
    position_rows = [
        {"timestamp": "2026-07-10T14:56:00", "symbol": "510300", "quantity": 100},
        {"timestamp": "2026-07-13T13:11:00", "symbol": "510300", "quantity": 0},
    ]
    ledger = [
        {"timestamp": "2026-07-10T13:11:00", "symbol": "510300", "side": "buy", "quantity": 100, "price": 2.0, "commission": 5.0, "average_cost_after": 2.05, "remaining_quantity": 100, "profit_loss": None},
        {"timestamp": "2026-07-13T13:11:00", "symbol": "510300", "side": "sell", "quantity": 100, "price": 2.2, "commission": 5.0, "average_cost": 2.05, "average_cost_after": 0.0, "remaining_quantity": 0, "profit_loss": 10.0},
    ]
    prices = {("2026-07-10", "510300"): 2.1, ("2026-07-13", "510300"): 2.2}

    history = site_export._daily_position_history(position_rows, ledger, prices, {"510300": "沪深300ETF"})

    assert history[0]["holdings"][0]["quantity_change"] == 100
    assert history[0]["holdings"][0]["unrealized_pnl"] == pytest.approx(5.0)
    exit_row = history[1]["holdings"][0]
    assert exit_row["action"] == "清仓"
    assert exit_row["quantity"] == 0
    assert exit_row["realized_pnl"] == pytest.approx(10.0)


def test_history_price_never_uses_a_minute_after_the_position_snapshot(tmp_path):
    repo = DuckDBRepository(tmp_path / "market.duckdb")
    repo.upsert_minute_bars(pd.DataFrame([
        {"symbol": "510300", "trade_date": "2026-07-13", "minute": 1456, "datetime": "2026-07-13 14:56", "open": 2.0, "high": 2.0, "low": 2.0, "close": 2.0, "volume": 100, "amount": 200},
        {"symbol": "510300", "trade_date": "2026-07-13", "minute": 1500, "datetime": "2026-07-13 15:00", "open": 3.0, "high": 3.0, "low": 3.0, "close": 3.0, "volume": 100, "amount": 300},
    ]), source="test")

    prices = site_export._daily_close_prices(repo, ["510300"], ["2026-07-13T14:56:00"])

    assert prices[("2026-07-13", "510300")] == 2.0
