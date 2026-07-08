import pandas as pd
import pytest

from quant_lab.data.minute import (
    _normalize_mootdx_minute_bars,
    _normalize_pandadata_minute_bars,
    _with_exchange_suffix,
    fetch_etf_minute_bars_pandadata,
)
from quant_lab.data.repository import DuckDBRepository


def test_normalize_mootdx_minute_bars_outputs_capacity_ready_columns():
    raw = pd.DataFrame(
        {
            "datetime": ["2026-07-06 09:32", "2026-07-06 09:33"],
            "open": [2.6, 2.61],
            "high": [2.62, 2.63],
            "low": [2.59, 2.60],
            "close": [2.61, 2.62],
            "vol": [100_000.0, 200_000.0],
            "amount": [261_000.0, 524_000.0],
        }
    )

    bars = _normalize_mootdx_minute_bars(raw, "159663.SZ")

    assert bars.columns.tolist() == [
        "symbol",
        "trade_date",
        "minute",
        "datetime",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
    ]
    assert bars["symbol"].tolist() == ["159663.SZ", "159663.SZ"]
    assert bars["trade_date"].tolist() == ["2026-07-06", "2026-07-06"]
    assert bars["minute"].tolist() == [932, 933]
    assert bars["volume"].tolist() == [100_000.0, 200_000.0]
    assert bars["amount"].tolist() == [261_000.0, 524_000.0]


def test_with_exchange_suffix_for_etf_codes():
    assert _with_exchange_suffix("159663") == "159663.SZ"
    assert _with_exchange_suffix("516500") == "516500.SH"
    assert _with_exchange_suffix("510300.SH") == "510300.SH"


def test_normalize_pandadata_minute_bars_outputs_capacity_ready_columns():
    raw = pd.DataFrame(
        {
            "symbol": ["510300.SH"],
            "date": ["20260701"],
            "datetime": ["2026-07-01 09:32:00"],
            "minute": ["093200"],
            "amount": [20_000_000.0],
            "volume": [4_000_000.0],
        }
    )

    bars = _normalize_pandadata_minute_bars(raw, "510300.SH")

    assert bars["symbol"].tolist() == ["510300.SH"]
    assert bars["trade_date"].tolist() == ["2026-07-01"]
    assert bars["minute"].tolist() == [932]
    assert bars["amount"].tolist() == [20_000_000.0]
    assert bars["volume"].tolist() == [4_000_000.0]
    assert bars[["open", "high", "low", "close"]].iloc[0].tolist() == [0.0, 0.0, 0.0, 0.0]


def test_fetch_pandadata_minute_bars_reports_missing_credentials(monkeypatch, tmp_path):
    monkeypatch.delenv("DEFAULT_USERNAME", raising=False)
    monkeypatch.delenv("DEFAULT_PASSWORD", raising=False)

    with pytest.raises(RuntimeError, match="Pandadata credentials are missing"):
        fetch_etf_minute_bars_pandadata(
            "510300",
            "2026-07-01",
            "2026-07-01",
            env_file=tmp_path / "missing.env",
        )


def test_repository_upserts_and_loads_minute_bars(tmp_path):
    repo = DuckDBRepository(tmp_path / "market.duckdb")
    bars = pd.DataFrame(
        {
            "symbol": ["159663.SZ"],
            "trade_date": ["2026-07-06"],
            "minute": [932],
            "datetime": ["2026-07-06 09:32:00"],
            "open": [2.60],
            "high": [2.62],
            "low": [2.59],
            "close": [2.61],
            "volume": [100_000.0],
            "amount": [261_000.0],
        }
    )

    repo.upsert_minute_bars(bars, source="mootdx")
    loaded = repo.load_minute_bars(["159663.SZ"], "2026-07-01", "2026-07-31")

    assert loaded["symbol"].tolist() == ["159663.SZ"]
    assert loaded["minute"].tolist() == [932]
    assert loaded["source"].tolist() == ["mootdx"]
