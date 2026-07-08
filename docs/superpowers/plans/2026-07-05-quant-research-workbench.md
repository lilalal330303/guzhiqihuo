# Quant Research Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local quant research workbench that fetches real A-share daily data, stores it in DuckDB, runs a moving-average crossover backtest, displays it in Streamlit, and records experiments.

**Architecture:** The app uses a small Python package under `src/quant_lab`. Data access, strategy logic, backtesting, metrics, experiment orchestration, and Streamlit UI are separate modules. DuckDB is the local database and akshare is the first real market data source.

**Tech Stack:** Python, uv, DuckDB, pandas, akshare, Streamlit, Plotly, pytest.

---

## File Structure

- `AGENTS.md`: Project rules and research workflow memory.
- `pyproject.toml`: Python project metadata and dependencies.
- `src/quant_lab/data/ingest.py`: Fetch and normalize akshare daily bars.
- `src/quant_lab/data/repository.py`: Create DuckDB schema and read/write prices and experiments.
- `src/quant_lab/strategies/ma_cross.py`: Generate moving-average crossover signals.
- `src/quant_lab/backtest/engine.py`: Simulate long-only signal-based backtests.
- `src/quant_lab/backtest/metrics.py`: Calculate backtest metrics.
- `src/quant_lab/research/experiment.py`: Run and persist a complete experiment.
- `src/quant_lab/app/main.py`: Streamlit app.
- `tests/test_ma_cross.py`: Strategy tests.
- `tests/test_backtest_engine.py`: Backtest tests.
- `tests/test_metrics.py`: Metrics tests.

## Tasks

### Task 1: Project Skeleton and Dependencies

- [ ] Create `pyproject.toml` with runtime dependencies and pytest config.
- [ ] Create Python package folders under `src/quant_lab`.
- [ ] Create `AGENTS.md` with project conventions.
- [ ] Run dependency sync with uv.

### Task 2: Strategy Signals

- [ ] Write failing tests for moving-average signals.
- [ ] Implement `generate_ma_cross_signals`.
- [ ] Run strategy tests until green.

### Task 3: Backtest and Metrics

- [ ] Write failing tests for deterministic backtest behavior.
- [ ] Implement long-only backtest engine.
- [ ] Write failing tests for metrics.
- [ ] Implement metrics.
- [ ] Run all unit tests until green.

### Task 4: DuckDB Repository

- [ ] Implement schema creation.
- [ ] Implement daily price upsert and reads.
- [ ] Implement backtest run and trade persistence.
- [ ] Smoke test repository with sample data.

### Task 5: akshare Ingestion

- [ ] Implement daily A-share fetch and normalization.
- [ ] Manually fetch `000001` to verify live data.
- [ ] Store fetched rows in DuckDB.

### Task 6: Experiment Runner

- [ ] Implement one function that fetches or reads data, runs strategy and backtest, calculates metrics, and persists results.
- [ ] Smoke test a full run for `000001`.

### Task 7: Streamlit UI

- [ ] Implement controls for symbol, dates, and moving-average windows.
- [ ] Render price chart, equity curve, metrics, and trades.
- [ ] Add clear user-facing error messages.
- [ ] Start Streamlit and provide the local URL.

### Task 8: Run the First Closed Loop

- [ ] Fetch real data for `000001`.
- [ ] Run a 20/60 moving-average backtest.
- [ ] Confirm prices, backtest run, and trades are saved in DuckDB.
- [ ] Show how to rerun with a changed parameter.
