from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from quant_lab.backtest.engine import run_long_only_backtest
from quant_lab.backtest.metrics import calculate_metrics
from quant_lab.data.ingest import fetch_a_share_daily
from quant_lab.data.repository import DuckDBRepository
from quant_lab.strategies.ma_cross import generate_ma_cross_signals


@dataclass(frozen=True)
class ExperimentResult:
    run_id: str
    prices: pd.DataFrame
    signals: pd.DataFrame
    equity_curve: pd.DataFrame
    trades: pd.DataFrame
    metrics: dict[str, float | int]


def run_ma_cross_experiment(
    repo: DuckDBRepository,
    symbol: str,
    start_date: str,
    end_date: str,
    short_window: int,
    long_window: int,
    refresh_data: bool = True,
) -> ExperimentResult:
    repo.initialize()
    if refresh_data:
        fetched = fetch_a_share_daily(symbol=symbol, start_date=start_date, end_date=end_date)
        repo.upsert_prices(fetched, source="akshare")

    prices = repo.load_prices(symbol=symbol, start_date=start_date, end_date=end_date)
    if prices.empty:
        raise ValueError(f"no stored prices for {symbol} from {start_date} to {end_date}")

    signals = generate_ma_cross_signals(prices, short_window=short_window, long_window=long_window)
    backtest = run_long_only_backtest(signals)
    metrics = calculate_metrics(backtest.equity_curve, backtest.trades)
    run_id = repo.save_backtest_run(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        short_window=short_window,
        long_window=long_window,
        metrics=metrics,
        trades=backtest.trades,
    )

    return ExperimentResult(
        run_id=run_id,
        prices=prices,
        signals=signals,
        equity_curve=backtest.equity_curve,
        trades=backtest.trades,
        metrics=metrics,
    )
