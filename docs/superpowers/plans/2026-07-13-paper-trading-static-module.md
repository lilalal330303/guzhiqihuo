# 模拟盘静态前端模块 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从本地模拟盘审计库导出真实快照，并构建可交互、可扩展、可发布的 GitHub Pages 模拟盘模块。

**Architecture:** Python 导出器只读 DuckDB 并生成 `docs/paper-trading/data/snapshot.json`。静态页面以一个共享 JavaScript 应用加载该快照，通过页面路径与查询参数渲染策略总览、详情、持仓、订单和日志；SVG 在浏览器端生成带坐标和悬浮提示的图表。

**Tech Stack:** Python、pytest、DuckDB、Pandas、HTML5、CSS、原生 JavaScript、SVG、GitHub Pages。

## Global Constraints

- 只读模拟盘审计数据；不得修改 V7K、V12D 的信号逻辑、执行时点或策略参数。
- 页面数据必须来自 `data/market.duckdb` 导出的审计快照，不得写死账户、订单、成交或指标数值。
- GitHub Pages 仅展示发布时的静态快照；本地 Streamlit 继续承担实时运行和推进。
- 新增账户出现在账户配置和审计库后，导出器与前端无需复制策略模板即可展示它。
- 不使用同花顺品牌资产、代码或登录内容；视觉只借鉴模拟盘信息结构。
- 导出内容不得包含绝对本地路径、密钥或供应商凭证；导出失败不得覆盖既有快照。

---

## File Structure

- `src/quant_lab/research/paper_trading_site_export.py`：读取审计记录、序列化为稳定 JSON、原子写入。
- `reports/export_paper_trading_site.py`：本地命令入口，默认读取 `data/market.duckdb`。
- `tests/test_paper_trading_site_export.py`：导出器的动态账户、审计字段、无写库和失败保护测试。
- `docs/paper-trading/index.html`：策略总览。
- `docs/paper-trading/strategy.html`、`positions.html`、`orders.html`、`logs.html`：静态子页壳。
- `docs/paper-trading/styles.css`：共享布局与响应式视觉。
- `docs/paper-trading/app.js`：加载、导航、筛选、页签、SVG 图表、错误与空态。
- `docs/paper-trading/data/snapshot.json`：导出得到的发布快照。
- `tests/test_paper_trading_static_site.py`：静态资源、入口和页面数据引用检查。

### Task 1: 审计快照导出器

**Files:**
- Create: `src/quant_lab/research/paper_trading_site_export.py`
- Create: `reports/export_paper_trading_site.py`
- Create: `tests/test_paper_trading_site_export.py`

**Interfaces:**
- Consumes: `DuckDBRepository`、`DEFAULT_PAPER_ACCOUNTS`、`build_command_center_snapshot()`、`build_execution_timeline()`。
- Produces: `build_site_snapshot(repo, accounts=DEFAULT_PAPER_ACCOUNTS, limit=200) -> dict[str, object]` and `export_site_snapshot(repo, output_path, accounts=DEFAULT_PAPER_ACCOUNTS) -> Path`.

- [ ] **Step 1: Write the failing test**

```python
def test_build_site_snapshot_uses_every_supplied_account_and_audit_rows(tmp_path, monkeypatch):
    repo = DuckDBRepository(tmp_path / "market.duckdb")
    accounts = (PaperAccount("alpha", "alpha_strategy", 1000.0),)
    repo.ensure_paper_account(accounts[0])
    repo.save_paper_equity("alpha", "alpha_strategy", "2026-07-13 13:10", 750, 1125)
    repo.record_paper_orders("alpha", "alpha_strategy", "2026-07-13 13:10", [{"symbol": "510300.SH", "side": "buy", "quantity": 100, "status": "filled"}])
    monkeypatch.setattr(exporter, "assess_readiness", lambda _: pd.DataFrame([{"account_id": "alpha", "ready": True, "reason": None}]))
    snapshot = exporter.build_site_snapshot(repo, accounts)
    assert snapshot["source"] == "local_paper_trading_audit"
    assert snapshot["accounts"][0]["account_id"] == "alpha"
    assert snapshot["accounts"][0]["equity_curve"][-1]["equity"] == 1125.0
    assert snapshot["accounts"][0]["orders"][0]["symbol"] == "510300.SH"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_paper_trading_site_export.py -q`

Expected: FAIL because `quant_lab.research.paper_trading_site_export` does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
def build_site_snapshot(repo, accounts=DEFAULT_PAPER_ACCOUNTS, limit=200):
    panels = build_command_center_snapshot(repo, accounts).account_panels
    return {"source": "local_paper_trading_audit", "generated_at": pd.Timestamp.now(tz="Asia/Shanghai").isoformat(),
            "accounts": [_account_payload(repo, panel, limit) for panel in panels]}

def export_site_snapshot(repo, output_path, accounts=DEFAULT_PAPER_ACCOUNTS):
    output_path = Path(output_path)
    payload = build_site_snapshot(repo, accounts)
    temporary = output_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(output_path)
    return output_path
```

`_account_payload` serializes panels, `load_paper_equity`, `load_latest_paper_position_state`, `load_paper_orders`, `load_paper_fills`, `build_execution_timeline`, and `load_paper_exceptions`; it converts timestamps to ISO strings, NumPy values to Python values, and limits each audit list to the latest `limit` rows. The command script constructs `DuckDBRepository(Path("data/market.duckdb"))`, calls `export_site_snapshot`, and prints the output path.

- [ ] **Step 4: Run tests to verify exporter behavior**

Run: `.venv\Scripts\python.exe -m pytest tests/test_paper_trading_site_export.py -q`

Expected: PASS, including a test that a failed JSON serialization leaves the prior output unchanged and a test that database row counts are unchanged before and after export.

- [ ] **Step 5: Commit**

```powershell
git add src/quant_lab/research/paper_trading_site_export.py reports/export_paper_trading_site.py tests/test_paper_trading_site_export.py
git commit -m "feat: export paper trading audit snapshot"
```

### Task 2: 静态页面壳与共享交互应用

**Files:**
- Modify: `docs/paper-trading/index.html`
- Create: `docs/paper-trading/strategy.html`
- Create: `docs/paper-trading/positions.html`
- Create: `docs/paper-trading/orders.html`
- Create: `docs/paper-trading/logs.html`
- Create: `docs/paper-trading/styles.css`
- Create: `docs/paper-trading/app.js`
- Create: `tests/test_paper_trading_static_site.py`

**Interfaces:**
- Consumes: `data/snapshot.json`, whose root has `generated_at`, `source`, `accounts`; each account has `account_id`, `strategy_id`, `metrics`, `equity_curve`, `positions`, `orders`, `fills`, `timeline`, `exceptions`.
- Produces: `loadSnapshot()`, `renderPage(snapshot)`, `renderEquityChart(container, points)`, and page navigation that uses `strategy.html?id=<account_id>`.

- [ ] **Step 1: Write the failing test**

```python
def test_static_site_has_all_routes_and_uses_shared_snapshot_application():
    root = Path("docs/paper-trading")
    for name in ["index.html", "strategy.html", "positions.html", "orders.html", "logs.html"]:
        content = (root / name).read_text(encoding="utf-8")
        assert 'styles.css' in content and 'app.js' in content
    script = (root / "app.js").read_text(encoding="utf-8")
    assert 'fetch("data/snapshot.json")' in script
    assert 'createElementNS("http://www.w3.org/2000/svg", "text")' in script
    assert 'pointermove' in script
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_paper_trading_static_site.py -q`

Expected: FAIL because child routes and shared application files do not exist.

- [ ] **Step 3: Write minimal implementation**

Create the five HTML shells with common `<header>`, `<aside id="strategy-nav">`, `<main id="app">`, `<link rel="stylesheet" href="styles.css">`, and `<script defer src="app.js"></script>`. `app.js` must:

```javascript
async function loadSnapshot() {
  const response = await fetch("data/snapshot.json", { cache: "no-store" });
  if (!response.ok) throw new Error("快照暂不可用");
  const snapshot = await response.json();
  if (!Array.isArray(snapshot.accounts) || snapshot.accounts.length === 0) throw new Error("快照没有可展示的账户");
  return snapshot;
}

function selectedAccount(snapshot) {
  const id = new URLSearchParams(location.search).get("id");
  return snapshot.accounts.find((account) => account.account_id === id) || snapshot.accounts[0];
}
```

`renderEquityChart` creates SVG grid lines, ISO-date X-axis labels, numeric Y-axis labels, a line path, and a `pointermove` tooltip based on the closest point. Detail tabs use buttons with `data-tab` and render actual positions/orders/fills/timeline/exceptions. Positions, orders, and logs each render a native `<select>` account filter and update count plus table on `change`. CSS supplies responsive grid, accessible focus states, color semantics and scrollable tables.

- [ ] **Step 4: Run tests to verify static application contracts**

Run: `.venv\Scripts\python.exe -m pytest tests/test_paper_trading_static_site.py -q`

Expected: PASS, including checks that no V7K/V12D account identifier is hardcoded in HTML or JavaScript and that the strategy page reads `id` from the query string.

- [ ] **Step 5: Commit**

```powershell
git add docs/paper-trading/index.html docs/paper-trading/strategy.html docs/paper-trading/positions.html docs/paper-trading/orders.html docs/paper-trading/logs.html docs/paper-trading/styles.css docs/paper-trading/app.js tests/test_paper_trading_static_site.py
git commit -m "feat: add interactive paper trading pages"
```

### Task 3: 生成发布快照、浏览器验证与发布

**Files:**
- Create: `docs/paper-trading/data/snapshot.json`
- Modify: `docs/paper-trading/app.js` only if browser validation exposes a defect.

**Interfaces:**
- Consumes: `reports/export_paper_trading_site.py`, static app pages and local `data/market.duckdb`.
- Produces: a versioned source-backed GitHub Pages snapshot and verified navigation.

- [ ] **Step 1: Write the failing test**

```python
def test_exported_snapshot_is_renderable_by_the_static_site():
    snapshot = json.loads(Path("docs/paper-trading/data/snapshot.json").read_text(encoding="utf-8"))
    assert snapshot["source"] == "local_paper_trading_audit"
    assert snapshot["accounts"]
    assert all("metrics" in account and "equity_curve" in account for account in snapshot["accounts"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_paper_trading_static_site.py::test_exported_snapshot_is_renderable_by_the_static_site -q`

Expected: FAIL because the exported snapshot file is absent.

- [ ] **Step 3: Generate the page snapshot**

Run: `.venv\Scripts\python.exe reports/export_paper_trading_site.py --output docs/paper-trading/data/snapshot.json`

The command must retain a valid prior snapshot if the export fails.

- [ ] **Step 4: Run test and browser checks**

Run: `.venv\Scripts\python.exe -m pytest tests/test_paper_trading_site_export.py tests/test_paper_trading_static_site.py -q`

Expected: PASS.

Open the local static site through an HTTP server, verify both account cards, every subpage, strategy navigation, detail tabs, table filters, SVG axes and tooltip, then verify narrow-screen layout. Confirm the page source label says the data is a static local-audit snapshot.

- [ ] **Step 5: Run regression suite and publish only scoped files**

Run: `.venv\Scripts\python.exe -m pytest -q`

Expected: PASS (the known SQLAlchemy deprecation warning is non-failing).

```powershell
git add docs/paper-trading/data/snapshot.json
git commit -m "docs: publish paper trading audit snapshot"
git push origin master
```

Report the GitHub Pages URL and clearly state the timestamp is a static snapshot, not a live service.

