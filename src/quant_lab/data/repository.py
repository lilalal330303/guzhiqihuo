from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd


class DuckDBRepository:
    def __init__(self, db_path: str | Path = "data/market.duckdb") -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS prices_daily (
                    symbol VARCHAR NOT NULL,
                    trade_date DATE NOT NULL,
                    open DOUBLE NOT NULL,
                    high DOUBLE NOT NULL,
                    low DOUBLE NOT NULL,
                    close DOUBLE NOT NULL,
                    volume DOUBLE,
                    amount DOUBLE,
                    source VARCHAR NOT NULL,
                    fetched_at TIMESTAMP NOT NULL,
                    PRIMARY KEY (symbol, trade_date)
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS prices_minute (
                    symbol VARCHAR NOT NULL,
                    trade_date DATE NOT NULL,
                    minute INTEGER NOT NULL,
                    datetime TIMESTAMP NOT NULL,
                    open DOUBLE NOT NULL,
                    high DOUBLE NOT NULL,
                    low DOUBLE NOT NULL,
                    close DOUBLE NOT NULL,
                    volume DOUBLE,
                    amount DOUBLE,
                    source VARCHAR NOT NULL,
                    fetched_at TIMESTAMP NOT NULL,
                    PRIMARY KEY (symbol, datetime)
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS backtest_runs (
                    run_id VARCHAR PRIMARY KEY,
                    symbol VARCHAR NOT NULL,
                    start_date DATE NOT NULL,
                    end_date DATE NOT NULL,
                    short_window INTEGER NOT NULL,
                    long_window INTEGER NOT NULL,
                    metrics_json VARCHAR NOT NULL,
                    created_at TIMESTAMP NOT NULL
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS backtest_trades (
                    run_id VARCHAR NOT NULL,
                    symbol VARCHAR NOT NULL,
                    entry_date DATE NOT NULL,
                    exit_date DATE NOT NULL,
                    entry_price DOUBLE NOT NULL,
                    exit_price DOUBLE NOT NULL,
                    return_pct DOUBLE NOT NULL
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS wufu_rotation_runs (
                    run_id VARCHAR PRIMARY KEY,
                    start_date DATE NOT NULL,
                    end_date DATE NOT NULL,
                    hypothesis VARCHAR NOT NULL,
                    params_json VARCHAR NOT NULL,
                    metrics_json VARCHAR NOT NULL,
                    next_research_note VARCHAR NOT NULL,
                    created_at TIMESTAMP NOT NULL
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS wufu_rotation_trades (
                    run_id VARCHAR NOT NULL,
                    symbol VARCHAR NOT NULL,
                    entry_date DATE NOT NULL,
                    exit_date DATE NOT NULL,
                    entry_price DOUBLE NOT NULL,
                    exit_price DOUBLE NOT NULL,
                    return_pct DOUBLE NOT NULL
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS wufu_dynamic_pool_snapshots (
                    trade_date DATE NOT NULL,
                    symbol VARCHAR NOT NULL,
                    rank INTEGER NOT NULL,
                    industry_key VARCHAR NOT NULL,
                    avg_amount DOUBLE NOT NULL,
                    source VARCHAR NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    PRIMARY KEY (trade_date, symbol)
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS wufu_target_cache (
                    cache_key VARCHAR NOT NULL,
                    trade_date DATE NOT NULL,
                    target_symbol VARCHAR,
                    is_weak BOOLEAN NOT NULL,
                    candidates_json VARCHAR NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    PRIMARY KEY (cache_key, trade_date)
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS etf_universe_snapshots (
                    trade_date DATE NOT NULL,
                    symbol VARCHAR NOT NULL,
                    name VARCHAR NOT NULL,
                    is_active BOOLEAN NOT NULL,
                    source VARCHAR NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    PRIMARY KEY (trade_date, symbol)
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS price_repair_events (
                    symbol VARCHAR NOT NULL,
                    event_date DATE NOT NULL,
                    previous_trade_date DATE NOT NULL,
                    previous_close DOUBLE NOT NULL,
                    current_close DOUBLE NOT NULL,
                    daily_return DOUBLE NOT NULL,
                    repair_ratio DOUBLE NOT NULL,
                    source VARCHAR NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    PRIMARY KEY (symbol, event_date, source)
                )
                """
            )

    def upsert_prices(self, prices: pd.DataFrame, source: str) -> None:
        if prices.empty:
            raise ValueError("prices must not be empty")
        required = {"symbol", "trade_date", "open", "high", "low", "close", "volume", "amount"}
        missing = required.difference(prices.columns)
        if missing:
            raise ValueError(f"prices missing required columns: {sorted(missing)}")

        rows = prices.copy()
        rows["trade_date"] = pd.to_datetime(rows["trade_date"]).dt.date
        rows["source"] = source
        rows["fetched_at"] = datetime.now(UTC)

        with self._connect() as con:
            con.register("price_rows", rows)
            con.execute(
                """
                INSERT OR REPLACE INTO prices_daily
                SELECT symbol, trade_date, open, high, low, close, volume, amount, source, fetched_at
                FROM price_rows
                """
            )

    def load_prices(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        self.initialize()
        with self._connect() as con:
            return con.execute(
                """
                SELECT symbol, trade_date, open, high, low, close, volume, amount, source, fetched_at
                FROM prices_daily
                WHERE symbol = ? AND trade_date BETWEEN ? AND ?
                ORDER BY trade_date
                """,
                [symbol, start_date, end_date],
            ).df()

    def load_prices_for_symbols(self, symbols: list[str], start_date: str, end_date: str) -> pd.DataFrame:
        self.initialize()
        if not symbols:
            return pd.DataFrame()
        placeholders = ", ".join(["?"] * len(symbols))
        with self._connect() as con:
            return con.execute(
                f"""
                SELECT symbol, trade_date, open, high, low, close, volume, amount, source, fetched_at
                FROM prices_daily
                WHERE symbol IN ({placeholders}) AND trade_date BETWEEN ? AND ?
                ORDER BY symbol, trade_date
                """,
                [*symbols, start_date, end_date],
            ).df()

    def load_price_coverage(self, symbols: list[str], start_date: str, end_date: str) -> pd.DataFrame:
        self.initialize()
        if not symbols:
            return pd.DataFrame(columns=["symbol", "min_trade_date", "max_trade_date", "row_count"])
        placeholders = ", ".join(["?"] * len(symbols))
        with self._connect() as con:
            return con.execute(
                f"""
                SELECT
                    symbol,
                    MIN(trade_date) AS min_trade_date,
                    MAX(trade_date) AS max_trade_date,
                    COUNT(*) AS row_count
                FROM prices_daily
                WHERE symbol IN ({placeholders}) AND trade_date BETWEEN ? AND ?
                GROUP BY symbol
                ORDER BY symbol
                """,
                [*symbols, start_date, end_date],
            ).df()

    def upsert_minute_bars(self, bars: pd.DataFrame, source: str) -> None:
        self.initialize()
        if bars.empty:
            raise ValueError("bars must not be empty")
        required = {
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
        }
        missing = required.difference(bars.columns)
        if missing:
            raise ValueError(f"minute bars missing required columns: {sorted(missing)}")

        rows = bars.copy()
        rows["trade_date"] = pd.to_datetime(rows["trade_date"]).dt.date
        rows["datetime"] = pd.to_datetime(rows["datetime"])
        rows["source"] = source
        rows["fetched_at"] = datetime.now(UTC)

        with self._connect() as con:
            con.register("minute_rows", rows)
            con.execute(
                """
                INSERT OR REPLACE INTO prices_minute
                SELECT symbol, trade_date, minute, datetime, open, high, low, close,
                       volume, amount, source, fetched_at
                FROM minute_rows
                """
            )

    def load_minute_bars(self, symbols: list[str], start_date: str, end_date: str) -> pd.DataFrame:
        self.initialize()
        if not symbols:
            return pd.DataFrame()
        placeholders = ", ".join(["?"] * len(symbols))
        with self._connect() as con:
            return con.execute(
                f"""
                SELECT symbol, trade_date, minute, datetime, open, high, low, close,
                       volume, amount, source, fetched_at
                FROM prices_minute
                WHERE symbol IN ({placeholders})
                  AND trade_date BETWEEN ? AND ?
                ORDER BY symbol, datetime
                """,
                [*symbols, start_date, end_date],
            ).df()

    def load_minute_coverage(
        self,
        symbols: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        self.initialize()
        filters: list[str] = []
        params: list[Any] = []
        if symbols:
            placeholders = ", ".join(["?"] * len(symbols))
            filters.append(f"symbol IN ({placeholders})")
            params.extend(symbols)
        if start_date:
            filters.append("trade_date >= ?")
            params.append(start_date)
        if end_date:
            filters.append("trade_date <= ?")
            params.append(end_date)
        where = f"WHERE {' AND '.join(filters)}" if filters else ""

        with self._connect() as con:
            return con.execute(
                f"""
                SELECT
                    symbol,
                    MIN(trade_date) AS min_trade_date,
                    MAX(trade_date) AS max_trade_date,
                    COUNT(*) AS row_count,
                    COUNT(DISTINCT trade_date) AS trade_days,
                    MAX(fetched_at) AS last_fetched_at,
                    STRING_AGG(DISTINCT source, ',') AS sources
                FROM prices_minute
                {where}
                GROUP BY symbol
                ORDER BY symbol
                """,
                params,
            ).df()

    def save_backtest_run(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        short_window: int,
        long_window: int,
        metrics: dict[str, Any],
        trades: pd.DataFrame,
    ) -> str:
        self.initialize()
        run_id = str(uuid.uuid4())
        created_at = datetime.now(UTC)

        with self._connect() as con:
            con.execute(
                """
                INSERT INTO backtest_runs
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    run_id,
                    symbol,
                    start_date,
                    end_date,
                    short_window,
                    long_window,
                    json.dumps(metrics, ensure_ascii=False),
                    created_at,
                ],
            )
            if not trades.empty:
                trade_rows = trades.copy()
                trade_rows["run_id"] = run_id
                trade_rows["symbol"] = symbol
                trade_rows["entry_date"] = pd.to_datetime(trade_rows["entry_date"]).dt.date
                trade_rows["exit_date"] = pd.to_datetime(trade_rows["exit_date"]).dt.date
                con.register("trade_rows", trade_rows)
                con.execute(
                    """
                    INSERT INTO backtest_trades
                    SELECT run_id, symbol, entry_date, exit_date, entry_price, exit_price, return_pct
                    FROM trade_rows
                    """
                )

        return run_id

    def load_trades(self, run_id: str) -> pd.DataFrame:
        self.initialize()
        with self._connect() as con:
            return con.execute(
                """
                SELECT run_id, symbol, entry_date, exit_date, entry_price, exit_price, return_pct
                FROM backtest_trades
                WHERE run_id = ?
                ORDER BY entry_date
                """,
                [run_id],
            ).df()

    def save_wufu_rotation_run(
        self,
        start_date: str,
        end_date: str,
        hypothesis: str,
        params: dict[str, Any],
        metrics: dict[str, Any],
        trades: pd.DataFrame,
        next_research_note: str,
    ) -> str:
        self.initialize()
        run_id = str(uuid.uuid4())
        created_at = datetime.now(UTC)
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO wufu_rotation_runs
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    run_id,
                    start_date,
                    end_date,
                    hypothesis,
                    json.dumps(params, ensure_ascii=False),
                    json.dumps(metrics, ensure_ascii=False),
                    next_research_note,
                    created_at,
                ],
            )
            if not trades.empty:
                trade_rows = trades.copy()
                trade_rows["run_id"] = run_id
                trade_rows["entry_date"] = pd.to_datetime(trade_rows["entry_date"]).dt.date
                trade_rows["exit_date"] = pd.to_datetime(trade_rows["exit_date"]).dt.date
                con.register("wufu_trade_rows", trade_rows)
                con.execute(
                    """
                    INSERT INTO wufu_rotation_trades
                    SELECT run_id, symbol, entry_date, exit_date, entry_price, exit_price, return_pct
                    FROM wufu_trade_rows
                    """
                )
        return run_id

    def load_wufu_rotation_trades(self, run_id: str) -> pd.DataFrame:
        self.initialize()
        with self._connect() as con:
            return con.execute(
                """
                SELECT run_id, symbol, entry_date, exit_date, entry_price, exit_price, return_pct
                FROM wufu_rotation_trades
                WHERE run_id = ?
                ORDER BY entry_date
                """,
                [run_id],
            ).df()

    def save_dynamic_pool_snapshot(self, snapshot: pd.DataFrame, source: str) -> None:
        self.initialize()
        if snapshot.empty:
            return
        required = {"trade_date", "symbol", "rank", "industry_key", "avg_amount"}
        missing = required.difference(snapshot.columns)
        if missing:
            raise ValueError(f"dynamic pool snapshot missing required columns: {sorted(missing)}")
        rows = snapshot.copy()
        rows["trade_date"] = pd.to_datetime(rows["trade_date"]).dt.date
        rows["source"] = source
        rows["created_at"] = datetime.now(UTC)
        with self._connect() as con:
            con.register("dynamic_pool_rows", rows)
            con.execute(
                """
                INSERT OR REPLACE INTO wufu_dynamic_pool_snapshots
                SELECT trade_date, symbol, rank, industry_key, avg_amount, source, created_at
                FROM dynamic_pool_rows
                """
            )

    def replace_dynamic_pool_snapshots(self, snapshot: pd.DataFrame, source: str) -> None:
        self.initialize()
        if snapshot.empty:
            return
        required = {"trade_date", "symbol", "rank", "industry_key", "avg_amount"}
        missing = required.difference(snapshot.columns)
        if missing:
            raise ValueError(f"dynamic pool snapshot missing required columns: {sorted(missing)}")
        start_date = pd.to_datetime(snapshot["trade_date"]).min().date()
        end_date = pd.to_datetime(snapshot["trade_date"]).max().date()
        with self._connect() as con:
            con.execute(
                "DELETE FROM wufu_dynamic_pool_snapshots WHERE trade_date BETWEEN ? AND ?",
                [start_date, end_date],
            )
        self.save_dynamic_pool_snapshot(snapshot, source=source)

    def load_dynamic_pool_snapshot(self, trade_date: str) -> pd.DataFrame:
        self.initialize()
        with self._connect() as con:
            return con.execute(
                """
                SELECT trade_date, symbol, rank, industry_key, avg_amount, source, created_at
                FROM wufu_dynamic_pool_snapshots
                WHERE trade_date = ?
                ORDER BY rank
                """,
                [trade_date],
            ).df()

    def load_dynamic_pool_snapshots(self, start_date: str, end_date: str) -> pd.DataFrame:
        self.initialize()
        with self._connect() as con:
            return con.execute(
                """
                SELECT trade_date, symbol, rank, industry_key, avg_amount, source, created_at
                FROM wufu_dynamic_pool_snapshots
                WHERE trade_date BETWEEN ? AND ?
                ORDER BY trade_date, rank
                """,
                [start_date, end_date],
            ).df()

    def save_wufu_target_cache(self, targets: pd.DataFrame) -> None:
        self.initialize()
        if targets.empty:
            return
        required = {"cache_key", "trade_date", "target_symbol", "is_weak", "candidates_json"}
        missing = required.difference(targets.columns)
        if missing:
            raise ValueError(f"target cache missing required columns: {sorted(missing)}")
        rows = targets.copy()
        rows["trade_date"] = pd.to_datetime(rows["trade_date"]).dt.date
        rows["created_at"] = datetime.now(UTC)
        with self._connect() as con:
            con.register("target_cache_rows", rows)
            con.execute(
                """
                INSERT OR REPLACE INTO wufu_target_cache
                SELECT cache_key, trade_date, target_symbol, is_weak, candidates_json, created_at
                FROM target_cache_rows
                """
            )

    def load_wufu_target_cache(self, cache_key: str, start_date: str, end_date: str) -> pd.DataFrame:
        self.initialize()
        with self._connect() as con:
            return con.execute(
                """
                SELECT cache_key, trade_date, target_symbol, is_weak, candidates_json, created_at
                FROM wufu_target_cache
                WHERE cache_key = ? AND trade_date BETWEEN ? AND ?
                ORDER BY trade_date
                """,
                [cache_key, start_date, end_date],
            ).df()

    def replace_etf_universe_snapshots(self, snapshots: pd.DataFrame, source: str) -> None:
        self.initialize()
        if snapshots.empty:
            return
        required = {"trade_date", "symbol", "name", "is_active"}
        missing = required.difference(snapshots.columns)
        if missing:
            raise ValueError(f"ETF universe snapshots missing required columns: {sorted(missing)}")
        rows = snapshots.copy()
        rows["trade_date"] = pd.to_datetime(rows["trade_date"]).dt.date
        rows["symbol"] = rows["symbol"].astype(str)
        rows["name"] = rows["name"].astype(str)
        rows["is_active"] = rows["is_active"].astype(bool)
        rows["source"] = source
        rows["created_at"] = datetime.now(UTC)
        start_date = rows["trade_date"].min()
        end_date = rows["trade_date"].max()
        with self._connect() as con:
            con.execute(
                "DELETE FROM etf_universe_snapshots WHERE trade_date BETWEEN ? AND ?",
                [start_date, end_date],
            )
            con.register("etf_universe_rows", rows)
            con.execute(
                """
                INSERT OR REPLACE INTO etf_universe_snapshots
                SELECT trade_date, symbol, name, is_active, source, created_at
                FROM etf_universe_rows
                """
            )

    def load_etf_universe_snapshots(self, start_date: str, end_date: str) -> pd.DataFrame:
        self.initialize()
        with self._connect() as con:
            return con.execute(
                """
                SELECT trade_date, symbol, name, is_active, source, created_at
                FROM etf_universe_snapshots
                WHERE trade_date BETWEEN ? AND ?
                ORDER BY trade_date, symbol
                """,
                [start_date, end_date],
            ).df()

    def load_etf_first_active_dates(self, start_date: str, end_date: str) -> pd.DataFrame:
        self.initialize()
        with self._connect() as con:
            return con.execute(
                """
                SELECT symbol, MIN(trade_date) AS first_active_date
                FROM etf_universe_snapshots
                WHERE is_active AND trade_date BETWEEN ? AND ?
                GROUP BY symbol
                ORDER BY symbol
                """,
                [start_date, end_date],
            ).df()

    def save_price_repair_events(self, events: pd.DataFrame, source: str) -> None:
        self.initialize()
        if events.empty:
            return
        required = {
            "symbol",
            "event_date",
            "previous_trade_date",
            "previous_close",
            "current_close",
            "daily_return",
            "repair_ratio",
        }
        missing = required.difference(events.columns)
        if missing:
            raise ValueError(f"price repair events missing required columns: {sorted(missing)}")
        rows = events.copy()
        rows["event_date"] = pd.to_datetime(rows["event_date"]).dt.date
        rows["previous_trade_date"] = pd.to_datetime(rows["previous_trade_date"]).dt.date
        rows["source"] = source
        rows["created_at"] = datetime.now(UTC)
        with self._connect() as con:
            con.register("repair_event_rows", rows)
            con.execute(
                """
                INSERT OR REPLACE INTO price_repair_events
                SELECT symbol, event_date, previous_trade_date, previous_close, current_close,
                       daily_return, repair_ratio, source, created_at
                FROM repair_event_rows
                """
            )

    def load_price_repair_events(self, start_date: str, end_date: str) -> pd.DataFrame:
        self.initialize()
        with self._connect() as con:
            return con.execute(
                """
                SELECT symbol, event_date, previous_trade_date, previous_close, current_close,
                       daily_return, repair_ratio, source, created_at
                FROM price_repair_events
                WHERE event_date BETWEEN ? AND ?
                ORDER BY event_date, symbol, source
                """,
                [start_date, end_date],
            ).df()

    def _connect(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(str(self.db_path))
