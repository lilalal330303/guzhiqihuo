(() => {
  "use strict";

  const page = document.body.dataset.page;
  const app = document.getElementById("app");
  const money = new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY", maximumFractionDigits: 2 });
  const number = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 });

  fetch("data/snapshot.json")
    .then((response) => {
      if (!response.ok) throw new Error(`快照读取失败（${response.status}）`);
      return response.json();
    })
    .then((snapshot) => renderApp(snapshot))
    .catch((error) => {
      app.innerHTML = `<main class="main"><section class="error"><h1>无法加载模拟盘快照</h1><p>${escapeHtml(error.message)}</p><p>请在本地运行快照导出后重试；GitHub Pages 仅展示最近一次发布的审计快照。</p></section></main>`;
    });

  function renderApp(snapshot) {
    const accounts = Array.isArray(snapshot.accounts) ? snapshot.accounts : [];
    if (!accounts.length) {
      app.innerHTML = `<main class="main"><section class="empty"><h1>暂无可展示的模拟盘账户</h1><p>导出的审计快照中尚未发现账户数据。</p></section></main>`;
      return;
    }
    app.innerHTML = shell(snapshot, accounts) + `<main id="content" class="main" tabindex="-1"><div id="view"></div></main>`;
    const view = document.getElementById("view");
    if (page === "strategy") renderStrategy(view, accounts, snapshot);
    else if (page === "positions") renderPositions(view, accounts);
    else if (page === "orders") renderOrders(view, accounts);
    else if (page === "logs") renderLogs(view, accounts);
    else renderOverview(view, accounts, snapshot);
  }

  function shell(snapshot, accounts) {
    const generated = snapshot.generated_at ? formatTime(snapshot.generated_at) : "未提供时间";
    const nav = [
      ["index.html", "总览", "overview"], ["positions.html", "持仓", "positions"],
      ["orders.html", "订单成交", "orders"], ["logs.html", "运行日志", "logs"],
    ].map(([href, label, key]) => `<a href="${href}" class="${page === key ? "active" : ""}">${label}</a>`).join("");
    const cards = accounts.map((account) => {
      const metrics = account.metrics || {};
      return `<a class="account-link" href="strategy.html?id=${encodeURIComponent(account.id)}"><div class="account-name">${escapeHtml(account.display?.name || account.strategy_id || account.id)}</div><div class="account-value">${formatMoney(metrics.equity ?? account.display?.initial_cash)}</div><div class="account-meta">持仓 ${number.format(metrics.position_count || 0)} · ${escapeHtml(account.strategy_id || "未标记策略")}</div></a>`;
    }).join("");
    return `<header class="topbar"><div class="brand">QUANT LAB <small>/ PAPER TRADING</small></div><nav class="topnav" aria-label="模拟盘导航">${nav}</nav><div class="source">审计快照 · ${escapeHtml(generated)}</div></header><div class="layout"><aside class="rail"><div class="rail-label">策略账户 / ${accounts.length}</div>${cards}</aside>`;
  }

  function renderOverview(root, accounts, snapshot) {
    const selected = accounts[0];
    const metrics = aggregateMetrics(accounts);
    root.innerHTML = pageHead("模拟盘指挥中心", "账户、收益与执行活动均来自本地审计快照。GitHub Pages 为只读发布版本。", snapshot) +
      kpis([
        ["账户总权益", formatMoney(metrics.equity)], ["可用现金", formatMoney(metrics.cash)],
        ["持仓标的", number.format(metrics.positions)], ["订单总数", number.format(metrics.orders)], ["成交笔数", number.format(metrics.fills)],
      ]) + `<section class="grid"><section class="panel"><h2>账户权益走势</h2><div class="chart-wrap" id="equity-chart"></div></section><section class="panel"><h2>最近执行活动</h2><div class="timeline">${timelineMarkup(flatten(accounts, "timeline").slice(-8).reverse())}</div></section></section>`;
    renderEquityChart(document.getElementById("equity-chart"), selected?.equity_curve || [], selected?.display?.name || "账户权益");
  }

  function renderStrategy(root, accounts, snapshot) {
    const wanted = new URLSearchParams(window.location.search).get("id");
    const account = accounts.find((item) => item.id === wanted) || accounts[0];
    const metrics = account.metrics || {};
    root.innerHTML = pageHead(account.display?.name || account.strategy_id || account.id, `策略标识：${account.strategy_id || "未提供"} · 查看该账户的完整审计轨迹。`, snapshot) +
      kpis([["账户权益", formatMoney(metrics.equity)], ["初始资金", formatMoney(account.display?.initial_cash)], ["可用现金", formatMoney(metrics.cash)], ["持仓数", number.format(metrics.position_count || 0)], ["累计收益", formatPercent(metrics.total_return)]]) +
      `<section class="panel"><h2>权益走势</h2><div class="chart-wrap" id="equity-chart"></div></section><div class="tabs" role="tablist"><button class="tab" role="tab" aria-selected="true" data-tab="positions">持仓</button><button class="tab" role="tab" aria-selected="false" data-tab="orders">订单</button><button class="tab" role="tab" aria-selected="false" data-tab="fills">成交</button><button class="tab" role="tab" aria-selected="false" data-tab="timeline">执行时间线</button><button class="tab" role="tab" aria-selected="false" data-tab="logs">运行日志</button></div><section class="panel" id="tab-content"></section>`;
    renderEquityChart(document.getElementById("equity-chart"), account.equity_curve || [], account.display?.name || "账户权益");
    const content = document.getElementById("tab-content");
    const show = (tab) => {
      content.innerHTML = tab === "positions" ? tableMarkup(account.positions, ["symbol", "quantity", "market_value", "timestamp"])
        : tab === "orders" ? orderTable(account.orders)
        : tab === "fills" ? tableMarkup(account.fills, ["symbol", "side", "quantity", "price", "timestamp"])
        : tab === "timeline" ? `<div class="timeline">${timelineMarkup((account.timeline || []).slice().reverse())}</div>`
        : exceptionMarkup(account.exceptions);
    };
    show("positions");
    root.querySelectorAll(".tab").forEach((button) => button.addEventListener("click", () => {
      root.querySelectorAll(".tab").forEach((tab) => tab.setAttribute("aria-selected", String(tab === button)));
      show(button.dataset.tab);
    }));
  }

  function renderPositions(root, accounts) {
    root.innerHTML = globalHead("持仓汇总", "按策略查看当前可审计持仓。", accounts);
    wireFilter(root, accounts, "positions", (rows) => tableMarkup(rows, ["account", "symbol", "quantity", "market_value", "timestamp"]));
  }

  function renderOrders(root, accounts) {
    root.innerHTML = globalHead("订单与成交", "订单行可展开查看原始审计字段。", accounts);
    wireFilter(root, accounts, "orders", (rows) => orderTable(rows));
  }

  function renderLogs(root, accounts) {
    root.innerHTML = globalHead("运行日志与异常", "展示各账户执行时间线及异常审计记录。", accounts);
    wireFilter(root, accounts, "logs", (rows) => `<div class="timeline">${timelineMarkup(rows)}</div>`);
  }

  function globalHead(title, description, accounts) {
    const options = [`<option value="">全部策略</option>`, ...accounts.map((account) => `<option value="${escapeAttr(account.id)}">${escapeHtml(account.display?.name || account.strategy_id || account.id)}</option>`)].join("");
    return `<div class="page-head"><div><div class="eyebrow">全局审计</div><h1>${title}</h1><p class="snapshot-note">${description}</p></div></div><section class="panel"><div class="filters"><label for="strategy-filter">策略筛选</label><select id="strategy-filter">${options}</select><span class="result-count" id="result-count">0 条结果</span></div><div id="global-results"></div></section>`;
  }

  function wireFilter(root, accounts, mode, renderRows) {
    const select = root.querySelector("#strategy-filter");
    const results = root.querySelector("#global-results");
    const count = root.querySelector("#result-count");
    const apply = () => {
      const selected = select.value ? accounts.filter((item) => item.id === select.value) : accounts;
      let rows;
      if (mode === "logs") rows = selected.flatMap((account) => [...withAccount(account, account.timeline), ...withAccount(account, account.exceptions)]).sort((a, b) => String(b.timestamp || "").localeCompare(String(a.timestamp || "")));
      else rows = selected.flatMap((account) => withAccount(account, account[mode]));
      count.textContent = `${rows.length} 条结果`;
      results.innerHTML = rows.length ? renderRows(rows) : `<div class="empty">当前筛选条件下暂无审计记录。</div>`;
    };
    select.addEventListener("change", apply); apply();
  }

  function renderEquityChart(container, curve, label) {
    container.innerHTML = "";
    if (!Array.isArray(curve) || !curve.length) { container.innerHTML = `<div class="empty">暂无权益快照，图表会在审计数据写入后显示。</div>`; return; }
    const values = curve.map((row) => numeric(row.equity ?? row.total_equity ?? row.value)).filter(Number.isFinite);
    if (!values.length) { container.innerHTML = `<div class="empty">权益快照缺少可绘制数值。</div>`; return; }
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.classList.add("equity-chart"); svg.setAttribute("viewBox", "0 0 760 300"); svg.setAttribute("role", "img"); svg.setAttribute("aria-label", `${label}权益走势`);
    const left = 64, top = 20, width = 670, height = 220, bottom = top + height;
    const min = Math.min(...values), max = Math.max(...values), range = max - min || Math.max(Math.abs(max) * .01, 1);
    const x = (index) => left + (values.length === 1 ? width / 2 : index * width / (values.length - 1));
    const y = (value) => top + height - (value - min) / range * height;
    const add = (name, attrs, text) => { const node = document.createElementNS("http://www.w3.org/2000/svg", name); Object.entries(attrs || {}).forEach(([key, value]) => node.setAttribute(key, value)); if (text !== undefined) node.textContent = text; svg.appendChild(node); return node; };
    add("line", { x1: left, y1: top, x2: left, y2: bottom, class: "axis" }); add("line", { x1: left, y1: bottom, x2: left + width, y2: bottom, class: "axis" });
    for (let i = 0; i < 4; i += 1) { const value = min + range * (i / 3); const yy = y(value); add("line", { x1: left, y1: yy, x2: left + width, y2: yy, class: "axis", opacity: ".45" }); add("text", { x: 4, y: yy + 4, class: "axis-label" }, compactMoney(value)); }
    const tickIndices = [...new Set([0, Math.floor((values.length - 1) / 2), values.length - 1])];
    tickIndices.forEach((index) => add("text", { x: x(index), y: bottom + 25, "text-anchor": "middle", class: "axis-label" }, formatShortTime(curve[index].timestamp || curve[index].trade_date)));
    const points = values.map((value, index) => `${x(index)},${y(value)}`).join(" ");
    add("polygon", { points: `${left},${bottom} ${points} ${left + width},${bottom}`, class: "series-area" }); add("polyline", { points, class: "series" });
    const focus = add("circle", { cx: x(0), cy: y(values[0]), r: 4, class: "point", opacity: "0" });
    const tooltip = document.createElement("div"); tooltip.className = "chart-tooltip"; container.appendChild(svg); container.appendChild(tooltip);
    const updateTooltip = (event) => { const rect = svg.getBoundingClientRect(); const px = (event.clientX - rect.left) / rect.width * 760; const nearest = Math.max(0, Math.min(values.length - 1, Math.round((px - left) / width * (values.length - 1)))); focus.setAttribute("cx", x(nearest)); focus.setAttribute("cy", y(values[nearest])); focus.setAttribute("opacity", "1"); tooltip.style.display = "block"; tooltip.style.left = `${Math.min(container.clientWidth - 150, Math.max(5, event.clientX - rect.left + 10))}px`; tooltip.style.top = `${Math.max(4, event.clientY - rect.top - 44)}px`; tooltip.textContent = `${formatShortTime(curve[nearest].timestamp || curve[nearest].trade_date)} · ${formatMoney(values[nearest])}`; };
    svg.addEventListener("pointermove", updateTooltip); svg.addEventListener("pointerleave", () => { tooltip.style.display = "none"; focus.setAttribute("opacity", "0"); });
  }

  function pageHead(title, description, snapshot) { return `<div class="page-head"><div><div class="eyebrow">本地模拟盘</div><h1>${escapeHtml(title)}</h1><p class="snapshot-note">${escapeHtml(description)}</p></div><div class="snapshot-note">数据源：${escapeHtml(snapshot.source || "本地审计")}</div></div>`; }
  function kpis(items) { return `<section class="kpis">${items.map(([name, value]) => `<div class="kpi"><span>${name}</span><b>${value}</b></div>`).join("")}</section>`; }
  function aggregateMetrics(accounts) { return accounts.reduce((all, account) => { const m = account.metrics || {}; all.equity += numeric(m.equity); all.cash += numeric(m.cash); all.positions += numeric(m.position_count); all.orders += (account.orders || []).length; all.fills += (account.fills || []).length; return all; }, { equity: 0, cash: 0, positions: 0, orders: 0, fills: 0 }); }
  function flatten(accounts, key) { return accounts.flatMap((account) => withAccount(account, account[key])); }
  function withAccount(account, rows) { return (Array.isArray(rows) ? rows : []).map((row) => ({ ...row, account: account.display?.name || account.strategy_id || account.id, account_id: account.id })); }
  function tableMarkup(rows, columns) { if (!rows?.length) return `<div class="empty">暂无可展示的审计记录。</div>`; return `<div class="table-wrap"><table class="data-table"><thead><tr>${columns.map((column) => `<th>${labelFor(column)}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${columns.map((column) => `<td>${formatCell(row[column], column)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`; }
  function orderTable(rows) { if (!rows?.length) return `<div class="empty">暂无订单审计记录。</div>`; return `<div class="table-wrap"><table class="data-table"><thead><tr><th>策略</th><th>标的</th><th>方向</th><th>数量</th><th>状态</th><th>时间</th><th>审计详情</th></tr></thead><tbody>${rows.map((row) => `<tr><td>${escapeHtml(row.account || "—")}</td><td>${formatCell(row.symbol)}</td><td>${formatCell(row.side)}</td><td>${formatCell(row.quantity)}</td><td><span class="status">${formatCell(row.status)}</span></td><td>${formatCell(row.timestamp)}</td><td><details class="audit-detail"><summary>展开</summary>${escapeHtml(JSON.stringify(row, null, 2))}</details></td></tr>`).join("")}</tbody></table></div>`; }
  function timelineMarkup(rows) { if (!rows?.length) return `<div class="empty">暂无执行时间线或异常记录。</div>`; return rows.map((row) => `<article class="event"><time>${escapeHtml(formatTime(row.timestamp || row.created_at))}</time>${escapeHtml(row.message || row.event || row.exception_type || row.status || JSON.stringify(row))}</article>`).join(""); }
  function exceptionMarkup(rows) { return rows?.length ? tableMarkup(rows, ["timestamp", "exception_type", "message"]) : `<div class="empty">暂无异常记录。</div>`; }
  function formatMoney(value) { return Number.isFinite(numeric(value)) ? money.format(numeric(value)) : "—"; }
  function compactMoney(value) { return `${(numeric(value) / 10000).toFixed(1)}万`; }
  function formatPercent(value) { const n = numeric(value); return Number.isFinite(n) ? `${(n * 100).toFixed(2)}%` : "—"; }
  function numeric(value) { const n = Number(value); return Number.isFinite(n) ? n : 0; }
  function formatTime(value) { const date = value ? new Date(value) : null; return date && !Number.isNaN(date.valueOf()) ? date.toLocaleString("zh-CN", { hour12: false }) : (value || "—"); }
  function formatShortTime(value) { const date = value ? new Date(value) : null; return date && !Number.isNaN(date.valueOf()) ? `${String(date.getMonth()+1).padStart(2,"0")}-${String(date.getDate()).padStart(2,"0")} ${String(date.getHours()).padStart(2,"0")}:${String(date.getMinutes()).padStart(2,"0")}` : (value || "—"); }
  function labelFor(key) { return ({ account: "策略", symbol: "标的", quantity: "数量", market_value: "市值", timestamp: "时间", side: "方向", price: "价格", exception_type: "异常类型", message: "消息" })[key] || key; }
  function formatCell(value, key) { if (value === null || value === undefined || value === "") return "—"; if (key === "timestamp") return escapeHtml(formatTime(value)); if (["market_value", "price"].includes(key)) return escapeHtml(formatMoney(value)); return escapeHtml(typeof value === "object" ? JSON.stringify(value) : String(value)); }
  function escapeHtml(value) { return String(value ?? "").replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]); }
  function escapeAttr(value) { return escapeHtml(value); }
})();
