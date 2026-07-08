# Quant Research Workbench Rules

## Project Goal

Build a lightweight local quant research workbench for A-share research, backtesting, visualization, and experiment recording.

## Architecture Rules

- Keep core research logic out of Streamlit pages.
- Put data fetching and database code under `src/quant_lab/data/`.
- Put strategy signal logic under `src/quant_lab/strategies/`.
- Put backtest simulation and metrics under `src/quant_lab/backtest/`.
- Put experiment orchestration under `src/quant_lab/research/`.
- Streamlit should call these modules and focus on controls, charts, tables, and user-facing errors.

## Data Rules

- Store local research data in `data/market.duckdb`.
- Use normalized column names: `symbol`, `trade_date`, `open`, `high`, `low`, `close`, `volume`, `amount`.
- Preserve the source name and fetch timestamp when writing market data.
- Do not overwrite raw source meaning silently; document any column mapping in code.

## Backtest Rules

- Avoid future data leakage.
- Signals generated on day T are executed on day T+1 by default.
- Backtests must report total return, annualized return, maximum drawdown, trade count, and win rate.
- Record each experiment with parameters and metrics.

## UI Rules

- Use Streamlit for the local research workbench.
- Keep the first screen usable for research, not as a landing page.
- Use charts and tables that help compare strategy behavior, not decorative layout.

## Research Workflow

For each experiment, capture:

- Hypothesis.
- Symbol and date range.
- Strategy parameters.
- Metrics.
- Trade list.
- Next research note.
