# Paper Trading Mobile UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为模拟盘静态站点增加360–480px移动端专用导航、紧凑账户选择和无溢出的指标、图表与审计内容布局，同时保持桌面端不变。

**Architecture:** 保留现有共享HTML和快照数据流，在 `app.js` 输出语义化移动导航与滚动提示，由 `styles.css` 在680px断点切换桌面/手机信息架构。所有移动行为通过静态结构测试、无缓存HTTP测试和四种目标宽度规则检查验证。

**Tech Stack:** 原生 HTML、CSS、JavaScript、Python pytest、本地 SimpleHTTPServer、GitHub Pages。

## Global Constraints

- 不修改V7K、V12D策略代码、参数、账户状态或快照结构。
- 360px、390px、430px、480px宽度不得出现页面级横向溢出或顶部中文竖排。
- 手机端使用底部四栏导航，桌面端保留顶部导航和左侧账户栏。
- 亮色默认、深色可切换且继续记忆。
- 触控目标最小高度44px，底部导航适配安全区域。

---

### Task 1: Mobile Navigation And Account Switcher

**Files:**
- Modify: `tests/test_paper_trading_static_site.py`
- Modify: `docs/paper-trading/app.js`
- Modify: `docs/paper-trading/styles.css`

**Interfaces:**
- Consumes: `page`, `accounts`, `current`, existing route URLs from `shell()`.
- Produces: `.mobile-context`, `.mobile-nav`, `.mobile-nav-link`, horizontally scrollable `.rail` account selector.

- [ ] **Step 1: Write failing structure tests**

Add assertions that `app.js` contains `mobile-context`, `mobile-nav`, four `mobile-nav-link` entries and `aria-current`, and that CSS contains `env(safe-area-inset-bottom)`, `scroll-snap-type:x mandatory`, and mobile-only visibility rules.

- [ ] **Step 2: Run the focused test and verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests/test_paper_trading_static_site.py::test_mobile_shell_uses_compact_context_bottom_navigation_and_safe_areas -q`

Expected: FAIL because the mobile shell and safe-area styles do not exist.

- [ ] **Step 3: Implement semantic mobile navigation**

In `shell()`, derive the current strategy display name and append:

```javascript
const mobileNav = navItems.map(([href, label, key, icon]) =>
  `<a class="mobile-nav-link" href="${href}" ${page === key ? 'aria-current="page"' : ""}><span aria-hidden="true">${icon}</span><b>${label}</b></a>`
).join("");
```

Render `.mobile-context` inside the top bar and `.mobile-nav` after the layout. Use icons `⌂`, `▤`, `⇄`, `≡` with the existing Chinese labels.

- [ ] **Step 4: Implement responsive account selector and safe-area navigation styles**

At `max-width:680px`, hide `.topnav` and `.source`, show `.mobile-context` and `.mobile-nav`, change `.rail` to horizontal grid-auto-flow columns with `overflow-x:auto`, and set account cards to `width:min(72vw,280px); scroll-snap-align:start`. Add `padding-bottom:calc(84px + env(safe-area-inset-bottom))` to `.main`.

- [ ] **Step 5: Run focused and full static tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_paper_trading_static_site.py -q`

Expected: all tests PASS.

### Task 2: Mobile Content, Charts, And Audit Tables

**Files:**
- Modify: `tests/test_paper_trading_static_site.py`
- Modify: `docs/paper-trading/app.js`
- Modify: `docs/paper-trading/styles.css`

**Interfaces:**
- Consumes: existing `.page-head`, `.kpis`, `.chart-wrap`, `.table-wrap`, `.tabs`, `.audit-filter` markup.
- Produces: `.mobile-scroll-hint`, mobile chart sizing, non-wrapping table headers and touch-sized controls.

- [ ] **Step 1: Write failing mobile content tests**

Assert CSS contains `overflow-x:clip`, `min-height:44px`, `-webkit-overflow-scrolling:touch`, mobile `.kpis` sizing, and `.chart-wrap` sizing; assert `app.js` emits `mobile-scroll-hint` before wide tables.

- [ ] **Step 2: Run the focused test and verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests/test_paper_trading_static_site.py::test_mobile_content_preserves_touch_targets_charts_and_wide_table_access -q`

Expected: FAIL because the hint and mobile constraints do not yet exist.

- [ ] **Step 3: Add the reusable table hint**

Update the table wrapper markup to include:

```html
<div class="mobile-scroll-hint" aria-hidden="true">左右滑动查看完整信息 →</div>
```

Keep the existing `.data-table` unchanged so desktop behavior and fields remain intact.

- [ ] **Step 4: Add compact content and touch styles**

For mobile: set `body{overflow-x:clip}`, `.main{padding:16px 14px}`, `.page-head{gap:10px}`, `.kpis{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}`, `.kpi{padding:13px}`, `.kpi b{font-size:clamp(18px,6vw,25px)}`, `.chart-wrap{height:260px}`, buttons/selects/tabs to `min-height:44px`, and scrolling containers to momentum scrolling.

- [ ] **Step 5: Run static tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_paper_trading_static_site.py -q`

Expected: all tests PASS.

### Task 3: Cache Bust, Local Verification, And GitHub Pages Delivery

**Files:**
- Modify: `docs/paper-trading/index.html`
- Modify: `docs/paper-trading/strategy.html`
- Modify: `docs/paper-trading/positions.html`
- Modify: `docs/paper-trading/orders.html`
- Modify: `docs/paper-trading/logs.html`
- Create: `reports/paper_trading_mobile_ui_delivery_20260714.md`

**Interfaces:**
- Consumes: completed `app.js`, `styles.css`, local no-cache server.
- Produces: cache-busted HTML references, local delivery report, GitHub Pages main-branch deployment.

- [ ] **Step 1: Update static asset version**

Change every HTML page from `app.js?v=20260714-4` to `app.js?v=20260714-5` and add `styles.css?v=20260714-5` so WeChat and mobile webviews fetch the new CSS.

- [ ] **Step 2: Run full relevant verification**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_paper_trading_static_site.py tests/test_paper_after_close.py tests/test_paper_trading_site_export.py -q
```

Expected: all tests PASS.

- [ ] **Step 3: Verify the local served files**

Request `http://127.0.0.1:8765/paper-trading/strategy.html?id=wufu_v12d&mobile=1` and confirm HTTP 200, `Cache-Control: no-store, no-cache, must-revalidate`, asset version `20260714-5`, and presence of the mobile navigation markers.

- [ ] **Step 4: Write delivery report**

Record the mobile breakpoints, navigation model, tested widths, unchanged strategy/data boundaries, test count, local URL, Pages URL, and commit hashes in `reports/paper_trading_mobile_ui_delivery_20260714.md`.

- [ ] **Step 5: Commit and publish**

Commit only scoped mobile files to `master`, push, then use an isolated worktree from `origin/main` to checkout `master -- docs/paper-trading`, commit and push `HEAD:main`.

- [ ] **Step 6: Verify GitHub Pages**

Fetch the deployed HTML, CSS and JS with cache-busting query parameters and confirm version `20260714-5`, `.mobile-nav`, safe-area CSS, current snapshot time `15:05`, and market data date `2026-07-14`.
