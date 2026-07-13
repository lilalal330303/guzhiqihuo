# 实盘行情模拟盘与页面优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 自动以真实分钟行情推进两套冻结策略的模拟盘，并交付中文、紧凑、可扩展的运营页面。

**Architecture:** 新增行情刷新与交易日推进服务，在每个允许分钟对行情完整性进行审计后调用既有 `run_paper_minute`。静态页面从审计快照读取中文显示模型，汇总持仓并使用固定侧栏与自适应表格。

**Tech Stack:** Python、pytest、DuckDB、mootdx/腾讯行情、原生 HTML/CSS/JavaScript。

## Global Constraints

- V7K/V12D 信号逻辑、执行时点和参数不得修改。
- 缺失、非交易日或未校验行情不得生成虚假订单、成交、权益或页面数据。
- 本地审计库是事实来源；GitHub Pages 只展示已发布静态快照。
- 所有用户可见页面文案使用中文；审计策略 ID 仅出现在必要详情。

---

### Task 1: 交易日行情推进服务

**Files:** Create `src/quant_lab/research/live_paper_trading.py`, `reports/run_live_paper_trading.py`, `tests/test_live_paper_trading.py`.

**Interfaces:** `advance_live_paper_trading(repo, now, quote_provider) -> list[PaperMinuteResult]` returns no results on non-trading days, validates required minute bars before delegating to `run_paper_minute`, and persists a durable blocked status on incomplete data.

- [ ] Write a failing test proving a Sunday returns an empty result and a missing required minute creates a `data_missing` blocked audit record.
- [ ] Run `.venv\Scripts\python.exe -m pytest tests/test_live_paper_trading.py -q`; expect missing-module failure.
- [ ] Implement a narrow trading-session calendar, minute-bar refresh adapter with mootdx primary/tencent fallback, validation, and an argparse command with `--now` and `--once`; never touch adapter parameters.
- [ ] Run focused tests; expect pass. Commit scoped files as `feat: advance paper trading with live market data`.

### Task 2: 审计快照中文显示与合并持仓

**Files:** Modify `src/quant_lab/research/paper_trading_site_export.py`, `tests/test_paper_trading_site_export.py`.

**Interfaces:** Snapshot root gains `market_data_as_of`; each account gains `display_name`; root gains `combined_positions` keyed by symbol with `quantity`, `market_value`, and `strategy_names`.

- [ ] Write failing tests for Chinese display labels, merged same-symbol quantities across accounts, and separate audit generation vs market-data times.
- [ ] Run focused exporter tests; expect failure.
- [ ] Implement read-only aggregation and timestamp extraction from latest equity/position audit row; JSON remains safe and atomic.
- [ ] Run focused tests; expect pass. Commit as `feat: add Chinese paper trading summary data`.

### Task 3: 页面中文化与布局优化

**Files:** Modify `docs/paper-trading/app.js`, `docs/paper-trading/styles.css`, `tests/test_paper_trading_static_site.py`.

- [ ] Write failing source-contract tests for Chinese market/snapshot labels, `combined_positions`, sticky rail, overflowing table containment and compact long-value behavior.
- [ ] Run focused static tests; expect failure.
- [ ] Render Chinese labels, show market-data timestamp separately, use combined positions in overview, apply `position: sticky` rail and bounded/responsive table/chart styles; preserve details and filters.
- [ ] Run focused tests and local HTTP smoke check; expect pass. Commit as `feat: polish Chinese paper trading dashboard`.

### Task 4: 生成、验证与发布

- [ ] Export `docs/paper-trading/data/snapshot.json` from current DuckDB only after tests pass.
- [ ] Run focused and full pytest suites, then manually verify local route navigation, fixed left rail, combined holdings, data dates and narrow screen.
- [ ] Commit the snapshot, push `master`, and report both local HTTP and GitHub Pages entry points.
