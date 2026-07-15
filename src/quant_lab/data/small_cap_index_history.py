from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd


def load_index_history_with_trading_warmup(
    db: str | Path,
    symbol: str,
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
    *,
    lookback: int = 60,
) -> pd.DataFrame:
    """Load a canonical index close series plus exact pre-start trading warmup."""
    if not isinstance(lookback, int) or isinstance(lookback, bool) or lookback < 1:
        raise ValueError("lookback must be a positive integer")
    start_ts, end_ts = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    if start_ts > end_ts:
        raise ValueError("start must not be after end")
    with duckdb.connect(str(Path(db)), read_only=True) as con:
        frame = con.execute(
            """
            WITH canonical AS (
                SELECT trade_date, close
                FROM prices_daily
                WHERE symbol = ? AND trade_date <= ?
                QUALIFY ROW_NUMBER() OVER (
                    PARTITION BY trade_date ORDER BY fetched_at DESC, source
                ) = 1
            ),
            warmup AS (
                SELECT trade_date, close FROM canonical
                WHERE trade_date < ?
                ORDER BY trade_date DESC
                LIMIT ?
            ),
            formal AS (
                SELECT trade_date, close FROM canonical
                WHERE trade_date BETWEEN ? AND ?
            )
            SELECT trade_date, close FROM (
                SELECT * FROM warmup
                UNION ALL
                SELECT * FROM formal
            )
            ORDER BY trade_date
            """,
            [symbol, end_ts, start_ts, lookback, start_ts, end_ts],
        ).df()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    prestart_count = int(frame["trade_date"].lt(start_ts).sum())
    if prestart_count < lookback:
        raise ValueError(
            f"index history requires {lookback} pre-start trading days; found {prestart_count}"
        )
    if frame["trade_date"].duplicated().any():
        raise RuntimeError("canonical index history contains duplicate trade dates")
    return frame.loc[:, ["trade_date", "close"]].reset_index(drop=True)
