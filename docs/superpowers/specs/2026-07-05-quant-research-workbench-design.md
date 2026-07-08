# Quant Research Workbench Design

## Goal

Build a lightweight local quant research workbench that uses real A-share daily data from akshare, stores research data in DuckDB, runs a simple moving-average crossover backtest, displays results in Streamlit, and records each experiment for later review.

## Scope

The first version focuses on one complete loop:

1. Fetch daily A-share price data for a selected symbol.
2. Save normalized bars into DuckDB.
3. Generate moving-average crossover signals.
4. Run a long-only backtest.
5. Show price, signals, equity curve, trades, and metrics in Streamlit.
6. Save experiment metadata and results.

Out of scope for the first version:

- Intraday data.
- Live trading.
- Multi-factor ranking.
- Portfolio optimization.
- Scheduled jobs.
- User accounts or deployment.

## Architecture

The project is a local Python application managed by uv. DuckDB is the local analytical database. Streamlit is the interactive interface. Strategy and backtest logic live in importable Python modules so they can be tested and reused outside the UI.

Streamlit must not contain core research logic. It should call data, strategy, backtest, and experiment modules.

## Components

### Data Layer

`src/quant_lab/data/ingest.py` fetches daily A-share price data through akshare and normalizes column names.

`src/quant_lab/data/repository.py` owns DuckDB schema creation, price upsert, price reads, and experiment result writes.

### Strategy Layer

`src/quant_lab/strategies/ma_cross.py` creates long-only moving-average crossover signals.

The strategy uses adjusted close if available, otherwise close.

### Backtest Layer

`src/quant_lab/backtest/engine.py` simulates a simple long-only strategy with full capital allocation when the signal is long and cash otherwise.

`src/quant_lab/backtest/metrics.py` calculates total return, annualized return, maximum drawdown, trade count, and win rate.

### Research Layer

`src/quant_lab/research/experiment.py` coordinates a full experiment and persists the result in DuckDB.

### UI Layer

`src/quant_lab/app/main.py` provides a Streamlit app with:

- Symbol input.
- Date range inputs.
- Short and long moving-average parameters.
- Data refresh button.
- Backtest run button.
- Price chart with buy/sell markers where practical.
- Equity curve.
- Metrics table.
- Trades table.

## Data Model

DuckDB stores:

- `prices_daily`: symbol, trade_date, open, high, low, close, volume, amount, source, fetched_at.
- `backtest_runs`: run_id, symbol, start_date, end_date, short_window, long_window, metrics_json, created_at.
- `backtest_trades`: run_id, symbol, entry_date, exit_date, entry_price, exit_price, return_pct.

## Error Handling

The data fetcher should raise a clear error when akshare returns no rows. The repository should create tables before reads or writes. The strategy should reject invalid moving-average windows. The app should show user-facing errors without crashing the whole page.

## Testing

Unit tests cover:

- Moving-average signal generation.
- Backtest equity and trade behavior on deterministic sample data.
- Metric calculations for known equity curves.

The data fetcher is not unit-tested against the live network in the first version. Manual verification will fetch one real symbol through the app or command line.

## First Manual Loop

The first full loop will use symbol `000001`, a recent multi-year date range, a short moving average of 20, and a long moving average of 60. The loop is successful when DuckDB contains fetched prices, a backtest run is saved, Streamlit renders the charts and tables, and the experiment can be repeated with a changed parameter.
