from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta
import os

import pandas as pd
import requests


def fetch_a_share_daily(
    symbol: str,
    start_date: str,
    end_date: str,
    adjust: str = "qfq",
) -> pd.DataFrame:
    """Fetch A-share daily bars from akshare and normalize columns."""
    import akshare as ak

    fetch_kwargs = {
        "symbol": symbol,
        "period": "daily",
        "start_date": start_date.replace("-", ""),
        "end_date": end_date.replace("-", ""),
        "adjust": adjust,
    }
    try:
        raw = ak.stock_zh_a_hist(**fetch_kwargs)
    except requests.exceptions.RequestException:
        try:
            with _without_proxy_environment():
                raw = ak.stock_zh_a_hist(**fetch_kwargs)
        except requests.exceptions.RequestException:
            try:
                raw = _fetch_eastmoney_direct(symbol, start_date, end_date, adjust)
            except requests.exceptions.RequestException:
                raw = _fetch_tencent_direct(symbol, start_date, end_date, adjust)
    if raw.empty:
        raise ValueError(f"akshare returned no rows for {symbol} from {start_date} to {end_date}")

    return _normalize_daily_bars(raw, symbol)


def fetch_etf_daily(
    symbol: str,
    start_date: str,
    end_date: str,
    adjust: str = "qfq",
) -> pd.DataFrame:
    """Fetch ETF daily bars from akshare and normalize columns.

    akshare's ETF endpoint returns Chinese column names in normal terminals, but
    some Windows shells render them with a different code page. The mapping is
    therefore positional and follows fund_etf_hist_em's documented order:
    date, open, close, high, low, volume, amount.
    """
    import akshare as ak

    fetch_kwargs = {
        "symbol": _strip_exchange_suffix(symbol),
        "period": "daily",
        "start_date": start_date.replace("-", ""),
        "end_date": end_date.replace("-", ""),
        "adjust": adjust,
    }
    try:
        raw = ak.fund_etf_hist_em(**fetch_kwargs)
    except requests.exceptions.RequestException:
        try:
            with _without_proxy_environment():
                raw = ak.fund_etf_hist_em(**fetch_kwargs)
        except requests.exceptions.RequestException:
            try:
                raw = _fetch_eastmoney_direct(_strip_exchange_suffix(symbol), start_date, end_date, adjust)
            except requests.exceptions.RequestException:
                raw = _fetch_sina_etf_daily(_strip_exchange_suffix(symbol), start_date, end_date)
    if raw.empty:
        raise ValueError(f"akshare returned no ETF rows for {symbol} from {start_date} to {end_date}")
    return _normalize_etf_daily_bars(raw, _strip_exchange_suffix(symbol))


def fetch_etf_daily_eastmoney_qfq(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Fetch ETF daily bars from Eastmoney direct K-line API using qfq adjustment."""
    clean_symbol = _strip_exchange_suffix(symbol)
    raw = _fetch_eastmoney_direct(clean_symbol, start_date, end_date, "qfq")
    if raw.empty:
        raise ValueError(f"eastmoney returned no ETF rows for {symbol} from {start_date} to {end_date}")
    return _normalize_etf_daily_bars(raw, clean_symbol)


def fetch_etf_universe_spot() -> pd.DataFrame:
    """Fetch current full-market ETF metadata snapshot from Eastmoney via akshare."""
    import akshare as ak

    raw = ak.fund_etf_spot_em()
    if raw.empty:
        raise ValueError("akshare returned no ETF universe rows")
    required = {"代码", "名称"}
    missing = required.difference(raw.columns)
    if missing:
        if len(raw.columns) < 2:
            raise ValueError(f"ETF universe response has too few columns: {list(raw.columns)}")
        rows = raw.iloc[:, :2].copy()
        rows.columns = ["symbol", "name"]
    else:
        rows = raw.rename(columns={"代码": "symbol", "名称": "name"})[["symbol", "name"]].copy()
    rows["symbol"] = rows["symbol"].astype(str).str.zfill(6)
    rows["name"] = rows["name"].astype(str)
    rows["amount"] = _optional_numeric_column(raw, "成交额")
    rows["float_market_value"] = _optional_numeric_column(raw, "流通市值")
    rows["snapshot_time"] = _optional_column(raw, "更新时间")
    return rows.drop_duplicates("symbol").reset_index(drop=True)


def fetch_index_daily(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Fetch broad index daily bars from Sina through akshare and normalize columns."""
    import akshare as ak

    raw = ak.stock_zh_index_daily(symbol=f"{_infer_index_exchange_prefix(symbol)}{symbol}")
    if raw.empty:
        raise ValueError(f"akshare returned no index rows for {symbol}")
    rows = raw.rename(
        columns={
            "date": "trade_date",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "volume": "volume",
        }
    )[["trade_date", "open", "high", "low", "close", "volume"]].copy()
    rows["trade_date"] = pd.to_datetime(rows["trade_date"])
    rows["symbol"] = _strip_exchange_suffix(symbol)
    rows["amount"] = 0.0
    for col in ["open", "high", "low", "close", "volume", "amount"]:
        rows[col] = pd.to_numeric(rows[col], errors="coerce")
    mask = rows["trade_date"].between(pd.Timestamp(start_date), pd.Timestamp(end_date))
    bars = rows.loc[mask, ["symbol", "trade_date", "open", "high", "low", "close", "volume", "amount"]]
    return bars.dropna(subset=["open", "high", "low", "close"]).sort_values("trade_date").reset_index(drop=True)


def _normalize_daily_bars(raw: pd.DataFrame, symbol: str) -> pd.DataFrame:
    column_map = {
        "日期": "trade_date",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
        "成交额": "amount",
    }
    missing = set(column_map).difference(raw.columns)
    if missing:
        raise ValueError(f"akshare response missing columns: {sorted(missing)}")

    bars = raw.rename(columns=column_map)[list(column_map.values())].copy()
    bars["symbol"] = symbol
    bars["trade_date"] = pd.to_datetime(bars["trade_date"])
    numeric_cols = ["open", "high", "low", "close", "volume", "amount"]
    for col in numeric_cols:
        bars[col] = pd.to_numeric(bars[col], errors="coerce")

    bars = bars[["symbol", "trade_date", "open", "high", "low", "close", "volume", "amount"]]
    return bars.dropna(subset=["open", "high", "low", "close"]).sort_values("trade_date").reset_index(drop=True)


def _normalize_etf_daily_bars(raw: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if len(raw.columns) < 7:
        raise ValueError(f"akshare ETF response has too few columns: {list(raw.columns)}")
    selected = raw.iloc[:, :7].copy()
    selected.columns = ["trade_date", "open", "close", "high", "low", "volume", "amount"]
    selected["symbol"] = symbol
    selected["trade_date"] = pd.to_datetime(selected["trade_date"])
    for col in ["open", "high", "low", "close", "volume", "amount"]:
        selected[col] = pd.to_numeric(selected[col], errors="coerce")
    bars = selected[["symbol", "trade_date", "open", "high", "low", "close", "volume", "amount"]]
    return bars.dropna(subset=["open", "high", "low", "close"]).sort_values("trade_date").reset_index(drop=True)


def _strip_exchange_suffix(symbol: str) -> str:
    return symbol.split(".")[0]


def _optional_column(raw: pd.DataFrame, column: str) -> pd.Series:
    if column in raw.columns:
        return raw[column]
    return pd.Series([None] * len(raw), index=raw.index)


def _optional_numeric_column(raw: pd.DataFrame, column: str) -> pd.Series:
    if column in raw.columns:
        return pd.to_numeric(raw[column], errors="coerce")
    return pd.Series([pd.NA] * len(raw), index=raw.index, dtype="Float64")


def _fetch_sina_etf_daily(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    import akshare as ak

    sina_symbol = f"{_infer_exchange_prefix(symbol)}{symbol}"
    raw = ak.fund_etf_hist_sina(symbol=sina_symbol)
    if raw.empty:
        return raw
    rows = raw.rename(
        columns={
            "date": "trade_date",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "volume": "volume",
            "amount": "amount",
        }
    )[["trade_date", "open", "close", "high", "low", "volume", "amount"]].copy()
    rows["trade_date"] = pd.to_datetime(rows["trade_date"])
    mask = rows["trade_date"].between(pd.Timestamp(start_date), pd.Timestamp(end_date))
    return rows.loc[mask].reset_index(drop=True)


def _infer_exchange_prefix(symbol: str) -> str:
    return "sh" if symbol.startswith(("5", "6", "9")) else "sz"


def _infer_index_exchange_prefix(symbol: str) -> str:
    return "sz" if symbol.startswith(("399", "159")) else "sh"


def _fetch_eastmoney_direct(symbol: str, start_date: str, end_date: str, adjust: str) -> pd.DataFrame:
    market_prefix = "1" if symbol.startswith(("5", "6", "9")) else "0"
    adjust_map = {"": "0", "qfq": "1", "hfq": "2"}
    session = requests.Session()
    session.trust_env = False
    response = session.get(
        "https://push2his.eastmoney.com/api/qt/stock/kline/get",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://quote.eastmoney.com/",
        },
        params={
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f116",
            "ut": "7eea3edcaed734bea9cbfc24409ed989",
            "klt": "101",
            "fqt": adjust_map.get(adjust, "1"),
            "secid": f"{market_prefix}.{symbol}",
            "beg": start_date.replace("-", ""),
            "end": end_date.replace("-", ""),
        },
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    klines = (payload.get("data") or {}).get("klines") or []
    rows = []
    for item in klines:
        fields = item.split(",")
        rows.append(
            {
                "日期": fields[0],
                "开盘": fields[1],
                "收盘": fields[2],
                "最高": fields[3],
                "最低": fields[4],
                "成交量": fields[5],
                "成交额": fields[6],
            }
        )
    return pd.DataFrame(rows)


def _fetch_tencent_direct(symbol: str, start_date: str, end_date: str, adjust: str) -> pd.DataFrame:
    market_prefix = "sh" if symbol.startswith(("6", "9")) else "sz"
    code = f"{market_prefix}{symbol}"
    adjust_prefix = {"": "", "qfq": "qfq", "hfq": "hfq"}.get(adjust, "qfq")
    day_key = f"{adjust_prefix}day" if adjust_prefix else "day"

    all_klines = []
    requested_start = pd.Timestamp(start_date)
    current_end = pd.Timestamp(end_date)

    while current_end >= requested_start:
        klines = _fetch_tencent_window(code, day_key, start_date, current_end.strftime("%Y-%m-%d"), adjust_prefix)
        if not klines:
            break
        all_klines.extend(klines)
        earliest = pd.Timestamp(klines[0][0])
        if earliest <= requested_start or len(klines) < 640:
            break
        current_end = earliest - timedelta(days=1)

    deduped = {item[0]: item for item in all_klines}
    rows = []
    for item in sorted(deduped.values(), key=lambda row: row[0]):
        trade_date = pd.Timestamp(item[0])
        if trade_date < requested_start or trade_date > pd.Timestamp(end_date):
            continue
        rows.append(
            {
                "日期": item[0],
                "开盘": item[1],
                "收盘": item[2],
                "最高": item[3],
                "最低": item[4],
                "成交量": item[5],
                "成交额": 0.0,
            }
        )
    return pd.DataFrame(rows)


def _fetch_tencent_window(
    code: str,
    day_key: str,
    start_date: str,
    end_date: str,
    adjust_prefix: str,
) -> list[list[str]]:
    session = requests.Session()
    session.trust_env = False
    response = session.get(
        "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
        params={"param": f"{code},day,{start_date},{end_date},640,{adjust_prefix}"},
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    stock_data = (payload.get("data") or {}).get(code) or {}
    return stock_data.get(day_key) or stock_data.get("day") or []


@contextmanager
def _without_proxy_environment():
    proxy_keys = [key for key in os.environ if "proxy" in key.lower()]
    saved = {key: os.environ[key] for key in proxy_keys}
    for key in proxy_keys:
        os.environ.pop(key, None)
    try:
        yield
    finally:
        for key in proxy_keys:
            os.environ.pop(key, None)
        os.environ.update(saved)
