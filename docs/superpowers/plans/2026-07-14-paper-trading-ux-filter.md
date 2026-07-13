# Paper Trading UX And Date Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add date-scoped audit views, continuous five-day intraday candles, compact account money, a truthful 15:30 after-close status, and a richer trading-terminal UI.

**Architecture:** Extend the existing JSON exporter with deterministic 5-minute equity candles and refresh metadata. Keep filtering client-side over bounded account records, and use shared UI builders so strategy tabs and standalone pages behave identically.

**Tech Stack:** Python, pandas, pytest, static HTML/CSS/JavaScript, SVG, Windows Task Scheduler entry script.

## Global Constraints

- Do not change frozen strategy signals or parameters.
- Preserve real market timestamps; 15:30 is the snapshot schedule, not a trade timestamp.
- Write failing tests before production changes.
- Keep GitHub Pages dependency-free.

---

### Task 1: Five-minute candles and after-close metadata

**Files:** `tests/test_paper_trading_site_export.py`, `src/quant_lab/research/paper_trading_site_export.py`, `reports/run_paper_after_close.py`

- [ ] Add failing tests for five-day 5-minute OHLC and `after_close_refresh_time`.
- [ ] Run focused tests and confirm expected failures.
- [ ] Implement the exporter fields and a 15:30 export entry point.
- [ ] Run focused tests and confirm pass.

### Task 2: Date filters and compact metrics

**Files:** `tests/test_paper_trading_static_site.py`, `docs/paper-trading/app.js`

- [ ] Add failing contracts for shared order/fill date filtering, activity/log filtering, and integer money.
- [ ] Implement reusable date controls and filtered renderers.
- [ ] Replace daily-candle input with continuous `five_day_equity_candles`.
- [ ] Run static-site tests.

### Task 3: UI polish, QA, and delivery

**Files:** `docs/paper-trading/styles.css`, `docs/paper-trading/*.html`, `docs/paper-trading/data/snapshot.json`, `reports/paper_trading_ux_iteration_20260714.md`

- [ ] Add stable selected-state, hover, focus, table, card, filter and chart styles.
- [ ] Export the real snapshot and run the full test suite.
- [ ] Verify local interactions and responsive layout in the browser.
- [ ] Commit, push master, publish docs to main, and verify GitHub Pages HTTP 200.
