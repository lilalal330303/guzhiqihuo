import sys
import types

import pandas as pd

from quant_lab.data.ingest import fetch_index_daily


def test_fetch_index_daily_normalizes_sina_index_data(monkeypatch):
    def fake_stock_zh_index_daily(symbol):
        assert symbol == "sh000300"
        return pd.DataFrame(
            {
                "date": ["2024-01-02", "2024-01-03"],
                "open": [1.0, 1.1],
                "high": [1.2, 1.3],
                "low": [0.9, 1.0],
                "close": [1.1, 1.2],
                "volume": [1000.0, 1200.0],
            }
        )

    monkeypatch.setitem(sys.modules, "akshare", types.SimpleNamespace(stock_zh_index_daily=fake_stock_zh_index_daily))

    bars = fetch_index_daily("000300", "2024-01-01", "2024-01-31")

    assert bars["symbol"].tolist() == ["000300", "000300"]
    assert bars["trade_date"].tolist() == [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03")]
    assert bars["amount"].tolist() == [0.0, 0.0]
