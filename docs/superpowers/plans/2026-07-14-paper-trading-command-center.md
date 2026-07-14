# Paper Trading Command Center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有模拟盘升级为默认深色的赛博量化作战中枢，并保持真实数据、移动适配和亮色主题完整可用。

**Architecture:** 保持当前静态HTML、快照JSON和原生SVG绘图架构，仅在 `app.js` 增加终端语义标记与图表准星，在 `styles.css` 建立可复用HUD视觉令牌、组件皮肤和受控动画。所有视觉行为通过静态回归测试、无缓存本地回读和GitHub Pages线上回读验证。

**Tech Stack:** 原生HTML/CSS/JavaScript、SVG、Python pytest、本地SimpleHTTPServer、GitHub Pages。

## Global Constraints

- 不修改V7K、V12D策略、参数、账户、订单、成交、持仓和快照结构。
- 首次访问默认深色，已保存主题选择时尊重用户选择。
- 保留亮色冰蓝银白主题和移动端360–480px适配。
- 不引入第三方框架、图表库、字体CDN或远程视觉资源。
- 所有非必要动画在 `prefers-reduced-motion: reduce` 下关闭。
- 图表数值、坐标算法、行情截止和15:05快照计划保持不变。

---

### Task 1: Dark-First Theme And Command Shell

**Files:**
- Modify: `tests/test_paper_trading_static_site.py`
- Modify: `docs/paper-trading/app.js`
- Modify: `docs/paper-trading/styles.css`

**Interfaces:**
- Consumes: existing `paper-theme` localStorage value, `shell(snapshot, accounts, current)` and current page route.
- Produces: default `data-theme="dark"`, `.command-status`, `.command-module`, HUD theme tokens.

- [ ] **Step 1: Write failing tests**

Add `test_command_center_defaults_dark_and_exposes_truthful_terminal_status()` asserting `savedTheme || "dark"`, `command-status`, `command-module`, and absence of unsupported realtime claims; add `test_command_center_css_defines_hud_tokens_and_reduced_motion()` asserting `--hud-glow`, `--hud-grid`, `.command-status`, `.hud-corner`, and `prefers-reduced-motion`.

- [ ] **Step 2: Verify red state**

Run: `.venv\Scripts\python.exe -m pytest tests/test_paper_trading_static_site.py::test_command_center_defaults_dark_and_exposes_truthful_terminal_status tests/test_paper_trading_static_site.py::test_command_center_css_defines_hud_tokens_and_reduced_motion -q`

Expected: FAIL because command-center markers and dark-first behavior do not exist.

- [ ] **Step 3: Implement dark-first shell markup**

Change theme initialization to:

```javascript
document.documentElement.dataset.theme = savedTheme || "dark";
```

In `shell()`, render `.command-module` using the current page label and `.command-status` using `snapshot.market_data_as_of` with the Chinese label `行情快照` rather than “实时”。Add `<i class="hud-corner" aria-hidden="true"></i>` to reusable account and KPI surfaces.

- [ ] **Step 4: Implement theme tokens and shell skin**

Define `--hud-glow`, `--hud-grid`, `--hud-surface`, `--hud-edge`, and `--hud-scan` on `:root`; skin top bar, body grid, account rail and current selection with blue/cyan terminal surfaces. Override the same tokens under `[data-theme="light"]` with ice-blue/silver values.

- [ ] **Step 5: Verify and commit**

Run the two focused tests, then all `tests/test_paper_trading_static_site.py`; commit `app.js`, `styles.css`, and tests with message `Build dark-first quant command shell`.

### Task 2: HUD Metrics, Charts, Tables, And Motion

**Files:**
- Modify: `tests/test_paper_trading_static_site.py`
- Modify: `docs/paper-trading/app.js`
- Modify: `docs/paper-trading/styles.css`

**Interfaces:**
- Consumes: existing `.kpi`, `.panel`, `.equity-chart`, `.data-table`, `.event`, `.mobile-nav` and `renderEquityChart()`.
- Produces: `.hud-label`, `.chart-crosshair-x`, `.chart-crosshair-y`, `.terminal-row`, command-center animations.

- [ ] **Step 1: Write failing component tests**

Add assertions for `chart-crosshair-x`, `chart-crosshair-y`, `hud-label`, `terminal-row`, `@keyframes hudIn`, `@keyframes scanPulse`, and scoped `filter:drop-shadow` chart effects.

- [ ] **Step 2: Verify red state**

Run the focused component test and confirm it fails because HUD chart/table markers do not exist.

- [ ] **Step 3: Add chart crosshair interaction**

In `renderEquityChart()`, create horizontal and vertical SVG lines with classes `chart-crosshair-x` and `chart-crosshair-y`, update their coordinates on `pointermove`, and hide them on `pointerleave`. Do not change `paddedDomain`, x/y scales or point values.

- [ ] **Step 4: Add reusable HUD semantics**

Update `kpis()` so each metric name uses `.hud-label`; add `.terminal-row` to audit rows/timeline events via existing markup helpers. Keep visible Chinese labels and all payload fields unchanged.

- [ ] **Step 5: Skin metrics, panels, charts and audit content**

Add controlled corner marks, scan-line hover, cyan chart glow, gradient series area, terminal table headers, status chips, timeline nodes, mobile control-capsule styling and 220–320ms `hudIn` transitions. Under reduced-motion, disable transforms, pulses and transitions.

- [ ] **Step 6: Verify and commit**

Run all static-site tests and commit scoped files with message `Polish command center HUD interactions`.

### Task 3: Cache Bust, Full Verification, And Publishing

**Files:**
- Modify: `docs/paper-trading/index.html`
- Modify: `docs/paper-trading/strategy.html`
- Modify: `docs/paper-trading/positions.html`
- Modify: `docs/paper-trading/orders.html`
- Modify: `docs/paper-trading/logs.html`
- Create: `reports/paper_trading_command_center_delivery_20260714.md`

**Interfaces:**
- Consumes: completed command-center JS/CSS and current snapshot.
- Produces: asset version `20260714-6`, local delivery, master commit and Pages main commit.

- [ ] **Step 1: Update asset versions**

Change every page from `styles.css?v=20260714-5` and `app.js?v=20260714-5` to `20260714-6`.

- [ ] **Step 2: Run complete relevant tests**

Run `.venv\Scripts\python.exe -m pytest tests/test_paper_trading_static_site.py tests/test_paper_after_close.py tests/test_paper_trading_site_export.py -q` and require zero failures.

- [ ] **Step 3: Verify local HTTP delivery**

Request local HTML, JS, CSS and snapshot; confirm no-cache headers, version `20260714-6`, default-dark code, crosshair classes, mobile safe areas, snapshot plan `15:05`, and market cutoff `2026-07-14T14:56:00`.

- [ ] **Step 4: Write delivery report**

Document the selectedA direction, default-dark behavior, HUD components, animation limits, tested breakpoints, unchanged strategy boundary, test count, URLs and final commits.

- [ ] **Step 5: Integrate and publish**

Commit scoped source/report files to a feature branch, merge to master after verification, push master, then publish only `docs/paper-trading` to Pages `main` through an isolated worktree.

- [ ] **Step 6: Verify Pages CDN**

Fetch deployed HTML, JS, CSS and snapshot with cache-busting query parameters and confirm all Task 3 Step 3 markers before declaring delivery complete.
