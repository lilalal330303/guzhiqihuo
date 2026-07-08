import pandas as pd

from quant_lab.data.minute import _normalize_akshare_minute_bars
from quant_lab.data.repository import DuckDBRepository
from quant_lab.research.etf_minute_kline_store import (
    MinuteStoreConfig,
    _date_batches,
    _next_date,
    _next_fetch_start,
    select_etf_symbols_from_daily,
)


def test_normalize_akshare_minute_bars_outputs_standard_columns():
    raw = pd.DataFrame(
        {
            "时间": ["2026-07-07 09:31:00"],
            "开盘": [4.858],
            "最高": [4.858],
            "最低": [4.850],
            "收盘": [4.852],
            "成交量": [15_008_200.0],
            "成交额": [72_847_424.0],
        }
    )

    bars = _normalize_akshare_minute_bars(raw, "510300.SH")

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
    assert bars.iloc[0].to_dict() == {
        "symbol": "510300.SH",
        "trade_date": "2026-07-07",
        "minute": 931,
        "datetime": "2026-07-07 09:31:00",
        "open": 4.858,
        "high": 4.858,
        "low": 4.85,
        "close": 4.852,
        "volume": 15_008_200.0,
        "amount": 72_847_424.0,
    }


def test_select_etf_symbols_from_daily_prefers_liquid_etfs(tmp_path):
    repo = DuckDBRepository(tmp_path / "market.duckdb")
    repo.initialize()
    repo.upsert_prices(
        pd.DataFrame(
            {
                "symbol": ["510300", "159915", "000300"],
                "trade_date": ["2026-07-06", "2026-07-06", "2026-07-06"],
                "open": [1.0, 1.0, 1.0],
                "high": [1.0, 1.0, 1.0],
                "low": [1.0, 1.0, 1.0],
                "close": [1.0, 1.0, 1.0],
                "volume": [1.0, 1.0, 1.0],
                "amount": [20_000_000.0, 30_000_000.0, 100_000_000.0],
            }
        ),
        source="test",
    )

    symbols = select_etf_symbols_from_daily(tmp_path / "market.duckdb", "2026-07-01", "2026-07-31", top_n=2)

    assert symbols == ["159915", "510300"]


def test_minute_config_and_next_date():
    cfg = MinuteStoreConfig(start_date="2026-07-01", end_date="2026-07-07")

    assert cfg.sources[0] == "pandadata"
    assert _next_date("2026-07-06", "2026-07-01") == "2026-07-07"
    assert _next_date(None, "2026-07-01") == "2026-07-01"
    assert _next_fetch_start(("2026-07-07", "2026-07-07"), "2026-05-29") == "2026-05-29"
    assert _next_fetch_start(("2026-05-29", "2026-07-06"), "2026-05-29") == "2026-07-07"


def test_date_batches_split_history_ranges():
    assert _date_batches("2026-01-01", "2026-01-10", 4) == [
        ("2026-01-01", "2026-01-04"),
        ("2026-01-05", "2026-01-08"),
        ("2026-01-09", "2026-01-10"),
    ]
    assert _date_batches("2026-01-01", "2026-01-10", 0) == [("2026-01-01", "2026-01-10")]
