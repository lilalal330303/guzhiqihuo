# Wufu V12-D Pages Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the GitHub Pages presentation for the Wufu ETF V12-D fixed strategy as a polished static showcase.

**Architecture:** Keep the site fully static under `docs/` for GitHub Pages. Use self-contained HTML/CSS with lightweight CSS motion, inline visual panels, metric cards, and responsive sections. Preserve generated report data and links.

**Tech Stack:** Static HTML, CSS animations, GitHub Pages, no external runtime dependencies.

## Global Constraints

- Do not change strategy code.
- Keep GitHub Pages files under `docs/`.
- Use UTF-8 HTML.
- Avoid external CDN dependencies so pages work reliably from GitHub Pages.
- Keep pages readable on desktop and mobile.

---

### Task 1: Redesign Pages Home

**Files:**
- Modify: `docs/index.html`

**Interfaces:**
- Consumes: existing Pages paths under `docs/reports/`.
- Produces: a visual home page linking to V12-D fixed strategy, V12-D analysis, and historical archive.

- [ ] **Step 1: Replace the home layout**

Use a full-width hero, animated visual rail, metric cards, and a report navigation grid.

- [ ] **Step 2: Verify UTF-8 and links**

Run a local text check that the page contains `五福` and links to `reports/wufu_v12d_fixed_strategy.html`.

### Task 2: Redesign Fixed Strategy Page

**Files:**
- Modify: `docs/reports/wufu_v12d_fixed_strategy.html`

**Interfaces:**
- Consumes: V12-D summary metrics already embedded in the page.
- Produces: a segmented strategy showcase with hero, workflow, parameters, platform performance, and future roadmap.

- [ ] **Step 1: Replace the report-like layout**

Use section bands, animated metric cards, inline strategy visual, and clearly separated content blocks.

- [ ] **Step 2: Verify page copy and metrics**

Check for `6240.14%`, `8802.63%`, `98.48%`, and `100.00%`.

### Task 3: Redesign Analysis Page

**Files:**
- Modify: `docs/reports/wufu_v12d_fixed_analysis.html`

**Interfaces:**
- Consumes: V12-D analysis metrics already embedded in the page.
- Produces: a polished analysis page with executive summary, sync quality, execution diagnostics, and risk notes.

- [ ] **Step 1: Replace the layout**

Use the same design system as the fixed strategy page but with a more analytical narrative.

- [ ] **Step 2: Verify data visibility**

Check for weak match rate, target match rate, stop-loss difference, split gap statistics, and future actions.

### Task 4: Commit And Publish

**Files:**
- Modify: `docs/index.html`
- Modify: `docs/reports/wufu_v12d_fixed_strategy.html`
- Modify: `docs/reports/wufu_v12d_fixed_analysis.html`
- Create: `docs/superpowers/plans/2026-07-08-wufu-v12d-pages-redesign.md`

**Interfaces:**
- Consumes: local Git repository and remote `origin/main`.
- Produces: a commit pushed to GitHub Pages.

- [ ] **Step 1: Validate files**

Run a UTF-8/link sanity check.

- [ ] **Step 2: Commit only this redesign**

Stage the changed Pages files and this plan file.

- [ ] **Step 3: Push safely**

Use a temporary worktree from `origin/main`, cherry-pick the redesign commit, and push to `main`, preserving unrelated local changes.
