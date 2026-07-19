# 铁矿石 CTA 本地数据与回测 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立聚宽研究端导出、DuckDB 入库、质量审计和 V1.6 日频近似回测的一体化本地流程。

**Architecture:** 聚宽端脚本只负责读取点时数据并导出 CSV；本地数据模块负责 schema、导入和质量检查；回测模块负责信号截断、T+1 开盘成交、多空持仓和指标输出。四者通过固定文件名和显式 DataFrame 字段连接，不把聚宽 API 引入本地核心逻辑。

**Tech Stack:** Python 3.11、pandas、DuckDB、pytest、JoinQuant Research API。

## Global Constraints

- 聚宽研究端必须使用 `get_price(..., end_date=...)` 和 `get_all_securities(["futures"], date=...)`，不使用 `get_bars`。
- 本地数据保存到 `data/market.duckdb`，字段使用 `symbol, trade_date, open, high, low, close, volume, amount` 标准命名。
- 回测信号日 T 只能使用 T 及之前的数据，成交默认在 T+1 开盘。
- 不覆盖用户已有桌面文件；导出目录和数据库路径均可通过 CLI 参数修改。

---

### Task 1: 锁定导入、点时和回测验收行为

**Files:**
- Create: `tests/test_iron_ore_data_pipeline.py`
- Create: `tests/test_iron_ore_cta_local_backtest.py`

**Interfaces:**
- Tests will import `IronOreDataStore`, `run_iron_ore_v16_backtest`, and `select_near_contract_local`.
- Tests will use a temporary DuckDB path and synthetic CSV fixtures; no network or聚宽 API is used.

- [ ] **Step 1: Write tests** for CSV import, duplicate rejection, point-in-time contract selection, short signal, next-open execution, and no-future-data behavior.
- [ ] **Step 2: Run the two new test files** and confirm collection fails because the local modules do not exist yet.

### Task 2: Implement the JoinQuant Research export

**Files:**
- Create: `reports/jq_research_export_iron_ore_v1_6.py`
- Test: `tests/test_iron_ore_data_pipeline.py`

**Interfaces:**
- `export_iron_ore_v16_bundle(start_date, end_date, output_dir, metadata_stride=1)` writes the five named export files.
- The script uses daily `I8888.XDCE`, all discovered `I####.XDCE` contracts, dated futures metadata snapshots, and a manifest containing source, date range, fields, and row counts.

- [ ] **Step 1: Implement date warmup and OHLC normalization** with required fields `open, high, low, close` and optional `volume, money, open_interest`.
- [ ] **Step 2: Implement point-in-time universe snapshots** using `get_all_securities(["futures"], date=asof_date)` and an anchored iron ore code regex.
- [ ] **Step 3: Implement per-contract daily downloads** and write deterministic CSVs plus `manifest.json`.
- [ ] **Step 4: Run Python compilation and static checks** for no future import, no `get_bars`, and explicit date arguments.

### Task 3: Implement local DuckDB import and quality checks

**Files:**
- Create: `src/quant_lab/data/iron_ore.py`
- Create: `tools/import_iron_ore_v1_6.py`
- Test: `tests/test_iron_ore_data_pipeline.py`

**Interfaces:**
- `IronOreDataStore(db_path="data/market.duckdb")` creates the four iron ore tables.
- `import_bundle(export_dir, source="joinquant_research")` returns `IronOreImportResult` with row counts and quality findings.
- `quality_report()` returns serializable coverage, uniqueness, date, and point-in-time coverage metrics.

- [ ] **Step 1: Add schemas** for main daily, contract daily, static metadata, and dated universe tables with source/fetched timestamps.
- [ ] **Step 2: Normalize and validate CSVs**; reject missing required columns, duplicate primary keys, non-positive OHLC, and malformed contract codes.
- [ ] **Step 3: Implement idempotent upsert** so importing the same bundle twice does not duplicate rows.
- [ ] **Step 4: Implement CLI output** as JSON for later automation.

### Task 4: Implement local V1.6 daily futures backtest

**Files:**
- Create: `src/quant_lab/backtest/iron_ore_cta.py`
- Create: `tools/run_iron_ore_v1_6_local.py`
- Test: `tests/test_iron_ore_cta_local_backtest.py`

**Interfaces:**
- `select_near_contract_local(universe, signal_date, roll_days_before_expiry=8)` returns an eligible `I####.XDCE` code or `None`.
- `run_iron_ore_v16_backtest(main_daily, contract_daily, contracts, universe_daily, config)` returns `IronOreBacktestResult` with `signals`, `trades`, `equity_curve`, and `metrics`.
- The CLI loads from DuckDB and writes `signals.csv`, `trades.csv`, `equity_curve.csv`, and `metrics.json`.

- [ ] **Step 1: Implement V1.6 pure signal helpers** matching the production script: pre/post parameters, efficiency ratio, direction consistency, dual-speed signal, ATR, volatility sizing, drawdown multiplier, and symmetric trailing stop.
- [ ] **Step 2: Implement next-open execution** with close-first reversal/rollover, long/short P&L, commissions, slippage, margin and available-cash limits.
- [ ] **Step 3: Record every signal decision**, including `flat`, `no_contract`, `cooldown`, and risk-block reasons.
- [ ] **Step 4: Add CLI and result files** with explicit warning that execution is a daily approximation of the JoinQuant minute backtest.

### Task 5: End-to-end verification and documentation

**Files:**
- Create: `docs/iron_ore_local_backtest.md`
- Modify: none outside the files above.

- [ ] **Step 1: Run focused tests** for the importer and local backtest.
- [ ] **Step 2: Run Python compilation and static audit** on the research export script.
- [ ] **Step 3: Run the existing CTA tests** to ensure V1.6 production script remains unchanged.
- [ ] **Step 4: Document the exact JoinQuant and local commands**, expected files, quality checks, and split-backtest procedure.
- [ ] **Step 5: Commit only this task's files**, preserving unrelated dirty-worktree changes.
