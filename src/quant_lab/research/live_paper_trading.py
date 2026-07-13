"""Advance ETF paper accounts from locally stored and live minute bars."""
from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

import pandas as pd

from quant_lab.data.minute import fetch_etf_minute_bars_mootdx
from quant_lab.data.repository import DuckDBRepository
from quant_lab.research.paper_trading import (
    DEFAULT_PAPER_ACCOUNTS,
    PaperMinuteResult,
    _adapter_for,
    _execution_event,
    initialize_default_paper_accounts,
    run_paper_minute,
)


class MinuteQuoteProvider(Protocol):
    """Fallback seam, for example a Tencent real-time minute-bar client."""

    def __call__(self, symbol: str, now: pd.Timestamp) -> pd.DataFrame: ...


def advance_live_paper_trading(
    repo: DuckDBRepository,
    now: str | pd.Timestamp,
    quote_provider: MinuteQuoteProvider,
) -> list[PaperMinuteResult]:
    """Refresh due ETF bars and advance only fully evidenced strategy minutes.

    Local DuckDB bars are always preferred.  mootdx is the primary live
    refresh path and ``quote_provider`` is deliberately a narrow fallback seam
    so Tencent can be used without coupling execution to an HTTP provider.
    """
    timestamp = pd.Timestamp(now).floor("min")
    if timestamp.weekday() >= 5:
        return []

    initialize_default_paper_accounts(repo)
    results: list[PaperMinuteResult] = []
    for account in DEFAULT_PAPER_ACCOUNTS:
        adapter = _adapter_for(account)
        minute = int(timestamp.strftime("%H%M"))
        if minute != adapter.signal_minute and _execution_event(adapter, minute) is None:
            continue
        symbols = adapter.required_symbols(timestamp)
        missing = _refresh_required_minute_bars(repo, symbols, timestamp, quote_provider)
        if missing:
            result = _commit_data_missing(repo, account.account_id, adapter.strategy_id, timestamp, missing)
        else:
            result = run_paper_minute(repo, account.account_id, timestamp)
        results.append(result)
    return results


def _refresh_required_minute_bars(
    repo: DuckDBRepository,
    symbols: list[str],
    timestamp: pd.Timestamp,
    quote_provider: MinuteQuoteProvider,
) -> list[str]:
    """Store live rows only when they include this exact requested minute."""
    day = timestamp.strftime("%Y-%m-%d")
    minute = int(timestamp.strftime("%H%M"))
    missing = _missing_symbols(repo, symbols, day, minute)
    for symbol in missing:
        bars = _fetch_primary(symbol)
        if _has_requested_bar(bars, symbol, timestamp):
            repo.upsert_minute_bars(bars, "mootdx")
    missing = _missing_symbols(repo, symbols, day, minute)
    for symbol in missing:
        try:
            bars = quote_provider(symbol, timestamp)
        except Exception:
            continue
        if _has_requested_bar(bars, symbol, timestamp):
            repo.upsert_minute_bars(bars, "tencent")
    return _missing_symbols(repo, symbols, day, minute)


def _fetch_primary(symbol: str) -> pd.DataFrame:
    try:
        return fetch_etf_minute_bars_mootdx(symbol)
    except Exception:
        return pd.DataFrame()


def _missing_symbols(repo: DuckDBRepository, symbols: list[str], day: str, minute: int) -> list[str]:
    bars = repo.load_minute_bars(symbols, day, day)
    present = set()
    if not bars.empty:
        present = set(bars.loc[bars["minute"] == minute, "symbol"].astype(str))
    return [symbol for symbol in symbols if symbol not in present]


def _has_requested_bar(bars: pd.DataFrame, symbol: str, timestamp: pd.Timestamp) -> bool:
    required = {"symbol", "trade_date", "minute", "datetime", "open", "high", "low", "close", "volume", "amount"}
    if bars.empty or not required.issubset(bars.columns):
        return False
    day = timestamp.normalize()
    minute = int(timestamp.strftime("%H%M"))
    rows = bars.copy()
    rows["trade_date"] = pd.to_datetime(rows["trade_date"]).dt.normalize()
    return bool(((rows["symbol"].astype(str) == symbol) & (rows["trade_date"] == day) & (rows["minute"] == minute)).any())


def _commit_data_missing(
    repo: DuckDBRepository,
    account_id: str,
    strategy_id: str,
    timestamp: pd.Timestamp,
    missing_symbols: list[str],
) -> PaperMinuteResult:
    if not repo.claim_paper_minute(account_id, strategy_id, timestamp):
        return PaperMinuteResult(account_id, timestamp, "already_processed")
    repo.commit_paper_blocked_minute(
        account_id,
        strategy_id,
        timestamp,
        "data_missing",
        {"missing_minutes": [{"symbol": symbol, "minute": int(timestamp.strftime("%H%M"))} for symbol in missing_symbols]},
    )
    return PaperMinuteResult(account_id, timestamp, "blocked", "data_missing")
