import sys
import types

import pandas as pd
import pytest
import requests

from quant_lab.data.ingest import fetch_a_share_daily, fetch_etf_daily, fetch_etf_daily_eastmoney_qfq, fetch_etf_universe_spot


def test_fetch_a_share_daily_retries_without_proxy_environment(monkeypatch):
    calls = []

    def fake_stock_zh_a_hist(symbol, period, start_date, end_date, adjust):
        calls.append(symbol)
        if len(calls) == 1:
            raise requests.exceptions.ProxyError("proxy failed")
        return pd.DataFrame(
            {
                "日期": ["2024-01-02"],
                "开盘": [10.0],
                "收盘": [10.5],
                "最高": [10.8],
                "最低": [9.9],
                "成交量": [1000.0],
                "成交额": [10000.0],
            }
        )

    fake_akshare = types.SimpleNamespace(stock_zh_a_hist=fake_stock_zh_a_hist)
    monkeypatch.setitem(sys.modules, "akshare", fake_akshare)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7897")

    bars = fetch_a_share_daily("000001", "2024-01-01", "2024-01-31")

    assert len(calls) == 2
    assert bars["symbol"].tolist() == ["000001"]
    assert bars["close"].tolist() == [10.5]


def test_fetch_a_share_daily_falls_back_to_direct_eastmoney_request(monkeypatch):
    def fake_stock_zh_a_hist(symbol, period, start_date, end_date, adjust):
        raise requests.exceptions.ProxyError("proxy failed")

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": {
                    "klines": [
                        "2024-01-02,10.00,10.50,10.80,9.90,1000,10000,0,0,0,0"
                    ]
                }
            }

    def fake_get(self, url, params, timeout, **kwargs):
        assert self.trust_env is False
        return FakeResponse()

    fake_akshare = types.SimpleNamespace(stock_zh_a_hist=fake_stock_zh_a_hist)
    monkeypatch.setitem(sys.modules, "akshare", fake_akshare)
    monkeypatch.setattr(requests.Session, "get", fake_get)

    bars = fetch_a_share_daily("000001", "2024-01-01", "2024-01-31")

    assert bars["trade_date"].tolist() == [pd.Timestamp("2024-01-02")]
    assert bars["close"].tolist() == [10.5]


def test_fetch_a_share_daily_falls_back_to_tencent_when_eastmoney_fails(monkeypatch):
    def fake_stock_zh_a_hist(symbol, period, start_date, end_date, adjust):
        raise requests.exceptions.ProxyError("proxy failed")

    class FakeEastmoneyResponse:
        def raise_for_status(self):
            raise requests.exceptions.ConnectionError("eastmoney failed")

    class FakeTencentResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": {
                    "sz000001": {
                        "qfqday": [["2024-01-02", "10.00", "10.50", "10.80", "9.90", "1000"]]
                    }
                }
            }

    calls = []

    def fake_get(self, url, params, timeout, **kwargs):
        calls.append(url)
        assert self.trust_env is False
        if "eastmoney" in url:
            return FakeEastmoneyResponse()
        return FakeTencentResponse()

    fake_akshare = types.SimpleNamespace(stock_zh_a_hist=fake_stock_zh_a_hist)
    monkeypatch.setitem(sys.modules, "akshare", fake_akshare)
    monkeypatch.setattr(requests.Session, "get", fake_get)

    bars = fetch_a_share_daily("000001", "2024-01-01", "2024-01-31")

    assert len(calls) == 2
    assert bars["close"].tolist() == [10.5]
    assert bars["amount"].tolist() == [0.0]


def test_fetch_etf_daily_normalizes_akshare_columns_by_position(monkeypatch):
    def fake_fund_etf_hist_em(symbol, period, start_date, end_date, adjust):
        return pd.DataFrame(
            [
                ["2024-01-02", 1.0, 1.1, 1.2, 0.9, 1000.0, 1100.0],
            ],
            columns=["date", "open", "close", "high", "low", "volume", "amount"],
        )

    fake_akshare = types.SimpleNamespace(fund_etf_hist_em=fake_fund_etf_hist_em)
    monkeypatch.setitem(sys.modules, "akshare", fake_akshare)

    bars = fetch_etf_daily("510300", "2024-01-01", "2024-01-31")

    assert bars["symbol"].tolist() == ["510300"]
    assert bars["trade_date"].tolist() == [pd.Timestamp("2024-01-02")]
    assert bars["close"].tolist() == [1.1]


def test_fetch_etf_daily_eastmoney_qfq_uses_direct_qfq(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": {"klines": ["2024-01-02,1.00,1.10,1.20,0.90,1000,1100,0,0,0,0"]}}

    def fake_get(self, url, headers, params, timeout):
        assert params["fqt"] == "1"
        assert params["secid"] == "1.510300"
        return FakeResponse()

    monkeypatch.setattr(requests.Session, "get", fake_get)

    bars = fetch_etf_daily_eastmoney_qfq("510300", "2024-01-01", "2024-01-31")

    assert bars["symbol"].tolist() == ["510300"]
    assert bars["close"].tolist() == [1.1]


def test_fetch_etf_universe_spot_normalizes_current_metadata(monkeypatch):
    def fake_fund_etf_spot_em():
        return pd.DataFrame(
            {
                "代码": ["510300", "159915"],
                "名称": ["沪深300ETF", "创业板ETF"],
                "成交额": [1000.0, 2000.0],
                "流通市值": [10_000.0, 20_000.0],
                "更新时间": ["2026-07-06 15:00:00+08:00", "2026-07-06 15:00:00+08:00"],
            }
        )

    fake_akshare = types.SimpleNamespace(fund_etf_spot_em=fake_fund_etf_spot_em)
    monkeypatch.setitem(sys.modules, "akshare", fake_akshare)

    metadata = fetch_etf_universe_spot()

    assert metadata["symbol"].tolist() == ["510300", "159915"]
    assert metadata["name"].tolist() == ["沪深300ETF", "创业板ETF"]
    assert "amount" in metadata.columns
