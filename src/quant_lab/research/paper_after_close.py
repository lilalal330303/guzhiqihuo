"""Complete an ETF paper-trading day from verified after-close market data."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from quant_lab.data.minute import fetch_etf_minute_bars_mootdx
from quant_lab.data.repository import DuckDBRepository
from quant_lab.research.paper_trading import DEFAULT_PAPER_ACCOUNTS, _adapter_for, run_paper_range
from quant_lab.research.paper_trading_replay import PAPER_WINDOW_MINUTES


MinuteFetcher = Callable[[str], pd.DataFrame]


def already_completed(status: dict[str, object], trade_date: str) -> bool:
    return status.get("status") == "completed" and status.get("trade_date") == trade_date


def aggregate_daily_bars(minute_bars: pd.DataFrame) -> pd.DataFrame:
    """Build an unadjusted daily OHLCV row from observed one-minute bars."""
    required = {"symbol", "trade_date", "datetime", "open", "high", "low", "close", "volume", "amount"}
    missing = required.difference(minute_bars.columns)
    if missing:
        raise ValueError(f"minute bars missing columns: {sorted(missing)}")
    rows = minute_bars.copy()
    rows["trade_date"] = pd.to_datetime(rows["trade_date"]).dt.normalize()
    rows["datetime"] = pd.to_datetime(rows["datetime"])
    rows = rows.sort_values(["symbol", "trade_date", "datetime"], kind="stable")
    daily = rows.groupby(["symbol", "trade_date"], as_index=False).agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"),
        volume=("volume", "sum"), amount=("amount", "sum"),
    )
    daily[["open", "high", "low", "close", "volume", "amount"]] = daily[
        ["open", "high", "low", "close", "volume", "amount"]
    ].astype(float)
    return daily


def validate_close_window(bars: pd.DataFrame, symbols: Iterable[str], required_minutes: Iterable[int]) -> None:
    """Refuse strategy advancement unless every frozen symbol/minute pair exists."""
    present = set(zip(bars.get("symbol", pd.Series(dtype=str)).astype(str), bars.get("minute", pd.Series(dtype=int)).astype(int)))
    expected = {(_exchange_symbol(symbol), int(minute)) for symbol in symbols for minute in required_minutes}
    missing = sorted(expected.difference(present))
    if missing:
        preview = ", ".join(f"{symbol}@{minute}" for symbol, minute in missing[:12])
        raise RuntimeError(f"missing required close-window bars: {len(missing)} ({preview})")


def _exchange_symbol(symbol: str) -> str:
    value = str(symbol).upper()
    if value.endswith((".SH", ".SZ")):
        return value
    clean = value.split(".")[0]
    return f"{clean}.SH" if clean.startswith(("5", "6", "9")) else f"{clean}.SZ"


def required_paper_symbols() -> list[str]:
    return sorted({symbol for account in DEFAULT_PAPER_ACCOUNTS for symbol in _adapter_for(account).required_symbols()})


def fatal_replay_results(results: Iterable[object]) -> list[object]:
    """Return only failures that make the completed trading day unsafe."""
    return [item for item in results if getattr(item, "status", None) == "failed" or (
        getattr(item, "status", None) == "blocked" and getattr(item, "reason", None) != "intent_missing"
    )]


def download_trade_day(
    trade_date: str | pd.Timestamp,
    symbols: Iterable[str],
    fetcher: MinuteFetcher | None = None,
    workers: int = 6,
) -> pd.DataFrame:
    """Download the requested trade day concurrently from independent TDX connections."""
    day = pd.Timestamp(trade_date).normalize()
    fetch = fetcher or (lambda symbol: fetch_etf_minute_bars_mootdx(symbol, pages=6, page_size=240, timeout=6))
    frames: list[pd.DataFrame] = []
    failures: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(fetch, symbol): symbol for symbol in symbols}
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                frame = future.result()
                frame = frame[pd.to_datetime(frame["trade_date"]).dt.normalize() == day]
                if frame.empty:
                    failures[symbol] = "requested trade date absent"
                else:
                    frames.append(frame)
            except Exception as exc:  # source failures are summarized after all symbols finish
                failures[symbol] = str(exc)
    if failures:
        preview = "; ".join(f"{symbol}: {reason}" for symbol, reason in list(failures.items())[:10])
        raise RuntimeError(f"minute download failed for {len(failures)} symbols: {preview}")
    return pd.concat(frames, ignore_index=True).drop_duplicates(["symbol", "trade_date", "minute"], keep="last")


def complete_paper_trade_day(repo: DuckDBRepository, trade_date: str | pd.Timestamp) -> dict[str, object]:
    """Download, validate, persist and replay one day without changing strategy definitions."""
    day = pd.Timestamp(trade_date).normalize()
    symbols = required_paper_symbols()
    bars = download_trade_day(day, symbols)
    validate_close_window(bars, symbols, PAPER_WINDOW_MINUTES)
    source = f"mootdx-paper-auto-{day:%Y%m%d}"
    repo.upsert_minute_bars(bars, source)
    repo.upsert_prices(aggregate_daily_bars(bars), source)
    results = run_paper_range(repo, day + pd.Timedelta(hours=13, minutes=1), day + pd.Timedelta(hours=14, minutes=56))
    failed = fatal_replay_results(results)
    if failed:
        reasons = "; ".join(f"{item.account_id}@{item.timestamp:%H:%M}:{item.reason}" for item in failed[:20])
        raise RuntimeError(f"paper replay did not complete cleanly: {reasons}")
    return {
        "trade_date": day.strftime("%Y-%m-%d"), "symbols": len(symbols), "minute_rows": len(bars),
        "daily_rows": len(aggregate_daily_bars(bars)), "events": len(results),
    }
