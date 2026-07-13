from __future__ import annotations

import pandas as pd
import importlib.util
from pathlib import Path

from quant_lab.data.repository import DuckDBRepository
from quant_lab.research.live_paper_trading import advance_live_paper_trading


def _live_script_module():
    path = Path("reports/run_live_paper_trading.py")
    spec = importlib.util.spec_from_file_location("run_live_paper_trading", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tencent_fallback_normalizes_the_requested_etf_minute(monkeypatch):
    module = _live_script_module()

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": {"sh510300": {"data": {"data": [
                ["202607131311", "3.80", "3.81", "3.82", "3.79", "1200", "4560"],
            ]}}}}

    monkeypatch.setattr(module.requests, "get", lambda *args, **kwargs: Response())
    bars = module._tencent_fallback("510300.SH", pd.Timestamp("2026-07-13 13:11"))

    assert bars.to_dict("records") == [{
        "symbol": "510300.SH", "trade_date": pd.Timestamp("2026-07-13"), "minute": 1311,
        "datetime": pd.Timestamp("2026-07-13 13:11"), "open": 3.8, "high": 3.82,
        "low": 3.79, "close": 3.81, "volume": 1200.0, "amount": 4560.0,
    }]


def test_tencent_fallback_returns_empty_frame_when_provider_payload_is_invalid(monkeypatch):
    module = _live_script_module()
    monkeypatch.setattr(module.requests, "get", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("offline")))

    assert module._tencent_fallback("510300.SH", pd.Timestamp("2026-07-13 13:11")).empty


def test_live_runner_skips_weekends_without_calling_quote_provider(tmp_path):
    repo = DuckDBRepository(tmp_path / "market.duckdb")
    calls: list[tuple[str, pd.Timestamp]] = []

    def quote_provider(symbol: str, now: pd.Timestamp) -> pd.DataFrame:
        calls.append((symbol, now))
        return pd.DataFrame()

    results = advance_live_paper_trading(repo, pd.Timestamp("2026-07-12 13:11"), quote_provider)

    assert results == []
    assert calls == []


def test_live_runner_durably_blocks_incomplete_minute_without_trading(tmp_path, monkeypatch):
    repo = DuckDBRepository(tmp_path / "market.duckdb")
    monkeypatch.setattr("quant_lab.research.live_paper_trading.fetch_etf_minute_bars_mootdx", lambda symbol: pd.DataFrame())

    results = advance_live_paper_trading(repo, pd.Timestamp("2026-07-13 13:11"), lambda symbol, now: pd.DataFrame())

    assert {result.status for result in results} == {"blocked"}
    assert {result.detail for result in results} == {"data_missing"}
    assert repo.load_paper_orders("v7k_wufu_qixing").empty
    assert repo.load_paper_fills("wufu_v12d").empty
    assert repo.load_paper_equity("v7k_wufu_qixing").empty
    assert set(repo.load_paper_exceptions("wufu_v12d")["reason"]) == {"data_missing"}
