from __future__ import annotations

import pandas as pd

from quant_lab.data.repository import DuckDBRepository
from quant_lab.research.live_paper_trading import advance_live_paper_trading


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
