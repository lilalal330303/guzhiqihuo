# Paper Trading Titanium Light Theme Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a premium titanium-silver and ice-blue light theme that matches the existing dark quant command center without changing strategy behavior or data.

**Architecture:** Extend the existing CSS theme-token and `[data-theme="light"]` override layer. Preserve the shared HTML and JavaScript rendering path, add static contract tests for the light-theme materials, then cache-bust all five pages and publish the same assets locally and on GitHub Pages.

**Tech Stack:** Static HTML, CSS custom properties, vanilla JavaScript, pytest static-contract tests, GitHub Pages.

## Global Constraints

- Modify presentation files and their static tests only.
- Do not change strategy code, strategy parameters, market snapshots, account calculations, chart data, or trading logic.
- Preserve the existing theme switch and stored user preference.
- Preserve 360, 390, 430, and 480 pixel mobile behavior and reduced-motion support.
- Use test-first development and a new cache-busting resource version.

---

### Task 1: Define the Titanium Light Theme Contract

**Files:**
- Modify: `tests/test_paper_trading_static_site.py`
- Modify: `docs/paper-trading/styles.css`

**Interfaces:**
- Consumes: existing `[data-theme="light"]` CSS selector contract.
- Produces: light-theme tokens `--light-metal`, `--light-edge`, `--light-glow`, and component overrides consumed by all five pages.

- [ ] **Step 1: Write the failing static contract test**

Add a test that reads `styles.css` and asserts the presence of the titanium tokens plus light-theme rules for `body`, `.topbar`, `.rail`, `.account-link`, `.kpi`, `.panel`, `.strategy-card`, `.data-table`, `.event.terminal-row`, `.chart-tooltip`, `.period`, `.tab`, and `.mobile-nav`.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `.venv\Scripts\python.exe -m pytest tests/test_paper_trading_static_site.py -q`

Expected: failure because the new titanium token names and complete component contract do not exist.

- [ ] **Step 3: Implement the minimal titanium theme layer**

Add a final, grouped `[data-theme="light"]` override section in `styles.css`. Define cool silver surfaces, blue metallic borders, restrained shadows, readable chart axes, light table selection, light activity cards, metallic controls, and mobile navigation. Keep animation durations between 220ms and 320ms and retain the existing reduced-motion block.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run: `.venv\Scripts\python.exe -m pytest tests/test_paper_trading_static_site.py -q`

Expected: all static page tests pass.

- [ ] **Step 5: Commit the tested light theme**

Commit only `styles.css` and the static test with message `Polish titanium light theme`.

### Task 2: Cache-Bust and Validate Every Page

**Files:**
- Modify: `docs/paper-trading/index.html`
- Modify: `docs/paper-trading/strategy.html`
- Modify: `docs/paper-trading/positions.html`
- Modify: `docs/paper-trading/orders.html`
- Modify: `docs/paper-trading/logs.html`
- Modify: `tests/test_paper_trading_static_site.py`

**Interfaces:**
- Consumes: shared `styles.css` and `app.js` asset references.
- Produces: identical resource version references on all five pages.

- [ ] **Step 1: Update the resource-version assertion first**

Change the static test to require `styles.css?v=20260714-7` and `app.js?v=20260714-7` on every HTML page.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `.venv\Scripts\python.exe -m pytest tests/test_paper_trading_static_site.py -q`

Expected: failure because pages still reference `20260714-6`.

- [ ] **Step 3: Update all five HTML entry points**

Replace both resource query versions with `20260714-7` in each page. Do not modify page structure or scripts.

- [ ] **Step 4: Run integrated verification**

Run: `.venv\Scripts\python.exe -m pytest tests/test_paper_trading_static_site.py tests/test_paper_after_close.py tests/test_paper_trading_site_export.py -q`

Expected: all tests pass with no strategy or data changes.

- [ ] **Step 5: Commit the release assets**

Commit the five HTML files and updated test with message `Release titanium light dashboard`.

### Task 3: Publish and Verify Delivery

**Files:**
- Modify: `reports/paper_trading_command_center_delivery_20260714.md`

**Interfaces:**
- Consumes: validated local HTML and CSS assets.
- Produces: local deployment, GitHub Pages deployment, and an updated delivery record.

- [ ] **Step 1: Update the delivery report**

Record the titanium-light design, resource version `20260714-7`, unchanged strategy/data boundary, test count, local URL, Pages URL, and release commits.

- [ ] **Step 2: Verify the local HTTP delivery**

Fetch the local HTML and CSS and assert HTTP 200, no-cache headers, `20260714-7`, titanium tokens, reduced-motion support, market cutoff `2026-07-14T14:56:00`, and snapshot schedule `15:05`.

- [ ] **Step 3: Commit and push the master deliverable**

Commit the report, push `master`, and preserve all unrelated dirty-worktree files.

- [ ] **Step 4: Publish the static site to GitHub Pages**

Copy only `docs/paper-trading` from `master` into an isolated worktree based on `origin/main`, commit, and push to `main`.

- [ ] **Step 5: Verify the public deployment**

Fetch public HTML and CSS with a cache-busting query and confirm `20260714-7` plus the titanium token markers are served.

