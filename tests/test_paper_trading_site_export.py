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
        "symbol": "510300.SH", "quantity": 200.0, "market_value": 400.0,
        "strategy_count": 2, "strategies": ["alpha", "beta"],
    }]
