# Paper Trading History And Professional Charts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver filtered audit views, reconstructed sell P/L, daily position history, daily bars, five-day equity candlesticks, and correct same-minute stop/rebalance behavior.

**Architecture:** Keep raw DuckDB audit records unchanged. Extend the static snapshot exporter with deterministic ledger and daily aggregation helpers, then render the new fields in the existing dependency-free HTML dashboard. Correct only the paper execution orchestration branch that currently returns before applying a frozen initial rebalance.

**Tech Stack:** Python, pandas, DuckDB, pytest, static HTML/CSS/JavaScript, SVG.

## Global Constraints

- Do not change V7K or V12D strategy signal logic or frozen parameters.
- Every production behavior starts with a failing test.
- Display only source-backed values; do not invent P/L or prices.
- Preserve rejected orders and low-value audit events in DuckDB.

---

### Task 1: Snapshot ledger and daily aggregates

**Files:**
- Modify: `tests/test_paper_trading_site_export.py`
- Modify: `src/quant_lab/research/paper_trading_site_export.py`

**Interfaces:**
- Produces: account fields `position_history`, `daily_equity_bars`; enriched sell `profit_loss`; filtered `orders` and `timeline`.

- [ ] Write failing exporter tests for rejection filtering, intent-missing filtering, average-cost realized P/L, historical position changes, and equity OHLC.
- [ ] Run the focused tests and confirm feature assertions fail.
- [ ] Implement deterministic ledger and daily aggregation helpers.
- [ ] Run focused exporter tests and confirm they pass.

### Task 2: Stop-loss and initial rebalance orchestration

**Files:**
- Modify: `tests/test_paper_trading_runner.py`
- Modify: `src/quant_lab/research/paper_trading.py`

**Interfaces:**
- Consumes: frozen daily intent and existing `execute_target_weights` sell-before-buy behavior.
- Produces: initial callback executes the frozen rebalance even when the prior holding breaches its stop.

- [ ] Write a failing test with a stopped old holding and a different positive target.
- [ ] Confirm the test fails because the new target is absent.
- [ ] Remove only the premature initial-callback stop return while retaining stop-monitor behavior.
- [ ] Confirm runner and execution tests pass.

### Task 3: Historical holdings and chart UI

**Files:**
- Modify: `tests/test_paper_trading_static_site.py`
- Modify: `docs/paper-trading/app.js`
- Modify: `docs/paper-trading/styles.css`
- Modify: `docs/paper-trading/*.html`

**Interfaces:**
- Consumes: `position_history` and `daily_equity_bars` from Task 1.
- Produces: date selector/history table, daily columns, five-day candlesticks, filtered orders/events.

- [ ] Write failing static-site contract tests for the new controls and SVG chart modes.
- [ ] Confirm the contract tests fail.
- [ ] Implement the date history view and SVG bar/candlestick renderers.
- [ ] Confirm static-site tests pass.

### Task 4: Real snapshot, QA, and publication

**Files:**
- Modify: `docs/paper-trading/data/snapshot.json`
- Create: `reports/paper_trading_iteration_20260714.md`

**Interfaces:**
- Produces: local and GitHub Pages deliverables backed by the audited database.

- [ ] Export the snapshot and reconcile July 13 liquidation, target, P/L, and position history.
- [ ] Run the full pytest suite.
- [ ] Test interactions in the browser at desktop width.
- [ ] Commit scoped files, push development history, synchronize `docs/paper-trading` to `main`, and verify GitHub Pages HTTP 200.
