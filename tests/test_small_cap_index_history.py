from __future__ import annotations

import duckdb
import pandas as pd
import pytest

from quant_lab.data.small_cap_index_history import load_index_history_with_trading_warmup


def _make_db(path, prestart_days: int) -> None:
    pre = pd.bdate_range(end="2019-12-31", periods=prestart_days)
    formal = pd.bdate_range(start="2020-01-01", periods=10)
    rows = pd.DataFrame({
        "symbol": "399101",
        "trade_date": [*pre, *formal],
        "close": range(len(pre) + len(formal)),
        "source": "unit",
        "fetched_at": pd.Timestamp("2026-01-01"),
    })
    with duckdb.connect(str(path)) as con:
        con.execute("""
            CREATE TABLE prices_daily(
                symbol VARCHAR, trade_date DATE, close DOUBLE,
                source VARCHAR, fetched_at TIMESTAMP
            )
        """)
        con.register("rows", rows)
        con.execute("INSERT INTO prices_daily SELECT * FROM rows")


def test_load_index_history_returns_exact_trading_day_warmup_and_formal_period(tmp_path) -> None:
    db = tmp_path / "market.duckdb"
    _make_db(db, 70)

    result = load_index_history_with_trading_warmup(
        db, "399101", "2020-01-01", "2020-01-14", lookback=60
    )

    assert result.columns.tolist() == ["trade_date", "close"]
    assert result["trade_date"].lt(pd.Timestamp("2020-01-01")).sum() == 60
    assert result["trade_date"].between("2020-01-01", "2020-01-14").sum() == 10
    assert result["trade_date"].is_monotonic_increasing
    assert result["trade_date"].is_unique


def test_load_index_history_rejects_insufficient_trading_warmup(tmp_path) -> None:
    db = tmp_path / "market.duckdb"
    _make_db(db, 59)

    with pytest.raises(ValueError, match="requires 60 pre-start trading days"):
        load_index_history_with_trading_warmup(
            db, "399101", "2020-01-01", "2020-01-14", lookback=60
        )
