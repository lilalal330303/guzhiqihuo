(() => {
  "use strict";

  const page = document.body.dataset.page || "overview";
  const app = document.getElementById("app");
  const currency = new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY", maximumFractionDigits: 2 });
  const numeric = (value) => Number.isFinite(Number(value)) ? Number(value) : 0;

  fetch("data/snapshot.json")
    .then((response) => response.ok ? response.json() : Promise.reject(new Error(`快照读取失败：${response.status}`)))
    .then(renderApp)
    .catch((error) => {
      app.innerHTML = `<main class="main"><section class="error"><h1>无法加载模拟盘审计快照</h1><p>${escapeHtml(error.message)}</p><p>请先运行 <code>.venv\\Scripts\\python.exe reports/serve_paper_trading_site.py</code>，再访问 <code>http://127.0.0.1:8765/paper-trading/</code>。</p></section></main>`;
    });

  function renderApp(snapshot) {
    const accounts = Array.isArray(snapshot.accounts) ? snapshot.accounts : [];
    if (!accounts.length) {
      app.innerHTML = `<main class="main"><section class="empty"><h1>暂无模拟盘账户</h1><p>请先导出本地模拟盘审计快照。</p></section></main>`;
      return;
    }
    const account = selectedAccountFromRoute(accounts);
    app.innerHTML = shell(snapshot, accounts, account) + `<main id="content" class="main" tabindex="-1"><div id="view"></div></main>`;
    const view = document.getElementById("view");
    if (page === "strategy") renderStrategy(view, account, snapshot);
    else if (page === "positions") renderPositions(view, account, snapshot);
    else if (page === "orders") renderOrders(view, account, snapshot);
    else if (page === "logs") renderLogs(view, account, snapshot);
    else renderOverview(view, accounts, account, snapshot);
  }

  function selectedAccountFromRoute(accounts) {
    const wanted = new URLSearchParams(window.location.search).get("id");
    return accounts.find((item) => item.id === wanted) || accounts[0];
  }

  function shell(snapshot, accounts, current) {
    const currentId = encodeURIComponent(current.id);
    const nav = [
      ["index.html", "策略总览", "overview"],
      [`positions.html?id=${currentId}`, "持仓", "positions"],
      [`orders.html?id=${currentId}`, "订单与成交", "orders"],
      [`logs.html?id=${currentId}`, "运行日志", "logs"],
    ].map(([href, label, key]) => `<a href="${href}" class="${page === key ? "active" : ""}">${label}</a>`).join("");
    const cards = accounts.map((item) => {
      const metrics = item.metrics || {};
      const active = item.id === current.id ? " active" : "";
      return `<a class="account-link${active}" href="strategy.html?id=${encodeURIComponent(item.id)}"><div class="account-name">${escapeHtml(item.display?.name || item.id)}</div><div class="account-value">${money(metrics.equity ?? item.display?.initial_cash)}</div><div class="account-meta">持仓 ${numeric(metrics.position_count)} 个 · 独立账户</div></a>`;
    }).join("");
    return `<header class="topbar"><div class="brand">量化研究 <small>模拟盘</small></div><nav class="topnav" aria-label="模拟盘导航">${nav}</nav><div class="source">审计快照 · ${escapeHtml(formatTime(snapshot.generated_at))}</div></header><div class="layout"><aside class="rail"><div class="rail-label">策略账户 / ${accounts.length}</div>${cards}</aside>`;
  }

  function renderOverview(root, accounts, current, snapshot) {
    root.innerHTML = pageHead("模拟盘策略总览", "账户之间独立核算；点击左侧策略进入其独立详情。", snapshot) +
      `<section class="strategy-summary">${accounts.map(accountCard).join("")}</section>` +
      `<section class="panel"><div class="section-title"><div><h2>${escapeHtml(current.display?.name || current.id)} · 权益走势</h2><p>当前策略</p></div>${periodControls()}</div><div class="chart-wrap" id="equity-chart"></div></section>` +
      `<section class="grid"><section class="panel"><h2>当前策略最近执行活动</h2><div class="timeline">${timelineMarkup((current.timeline || []).slice(-8).reverse())}</div></section><section class="panel"><h2>当前持仓</h2>${positionTable(latestPositions(current))}</section></section>`;
    wireChartPeriod(root, current.equity_curve || [], current.display?.name || current.id);
  }

  function accountCard(account) {
    const m = account.metrics || {};
    return `<a class="strategy-card" href="strategy.html?id=${encodeURIComponent(account.id)}"><div class="eyebrow">独立策略账户</div><h2>${escapeHtml(account.display?.name || account.id)}</h2>${kpis([["账户权益", money(m.equity)], ["可用现金", money(m.cash)], ["持仓市值", money(m.position_market_value)], ["累计收益", percent(m.total_return)]])}</a>`;
  }

  function renderStrategy(root, account, snapshot) {
    const m = account.metrics || {};
    root.innerHTML = pageHead(account.display?.name || account.id, "独立策略视图：总览、持仓、订单和日志均只显示当前策略。", snapshot) +
      kpis([["账户权益", money(m.equity)], ["初始资金", money(account.display?.initial_cash)], ["可用现金", money(m.cash)], ["持仓市值", money(m.position_market_value)], ["累计收益", percent(m.total_return)]]) +
      `<section class="panel"><div class="section-title"><div><h2>权益走势</h2><p>当前策略</p></div>${periodControls()}</div><div class="chart-wrap" id="equity-chart"></div></section>` +
      `<div class="tabs" role="tablist"><button class="tab" role="tab" aria-selected="true" data-tab="positions">持仓</button><button class="tab" role="tab" aria-selected="false" data-tab="orders">订单</button><button class="tab" role="tab" aria-selected="false" data-tab="fills">成交</button><button class="tab" role="tab" aria-selected="false" data-tab="timeline">执行活动</button><button class="tab" role="tab" aria-selected="false" data-tab="logs">运行日志</button></div><section class="panel" id="tab-content"></section>`;
    wireChartPeriod(root, account.equity_curve || [], account.display?.name || account.id);
    const content = root.querySelector("#tab-content");
    const show = (tab) => {
      content.innerHTML = tab === "positions" ? positionTable(latestPositions(account))
        : tab === "orders" ? orderTable(account.orders || [])
        : tab === "fills" ? fillTable(account.fills || [])
        : tab === "timeline" ? `<div class="timeline">${timelineMarkup((account.timeline || []).slice().reverse())}</div>`
        : logMarkup(account);
    };
    show("positions");
    root.querySelectorAll(".tab").forEach((button) => button.addEventListener("click", () => {
      root.querySelectorAll(".tab").forEach((tab) => tab.setAttribute("aria-selected", String(tab === button)));
      show(button.dataset.tab);
    }));
  }

  function renderPositions(root, account, snapshot) {
    root.innerHTML = scopedHead("持仓", account, snapshot, "显示当前策略的最新持仓快照，不混入其他策略。") + `<section class="panel">${positionTable(latestPositions(account))}</section>`;
  }

  function renderOrders(root, account, snapshot) {
    root.innerHTML = scopedHead("订单与成交", account, snapshot, "订单和成交均来自当前策略的持久化审计记录。") + `<section class="panel"><h2>订单</h2>${orderTable(account.orders || [])}</section><section class="panel"><h2>成交</h2>${fillTable(account.fills || [])}</section>`;
  }

  function renderLogs(root, account, snapshot) {
    root.innerHTML = scopedHead("运行日志", account, snapshot, "执行活动和异常记录仅属于当前策略。") + `<section class="panel">${logMarkup(account)}</section>`;
  }

  function scopedHead(title, account, snapshot, description) {
    return pageHead(title, description, snapshot) + `<div class="scope-label">当前策略：<b>${escapeHtml(account.display?.name || account.id)}</b></div>`;
  }

  function pageHead(title, description, snapshot) {
    const asOf = snapshot.market_data_as_of ? formatTime(snapshot.market_data_as_of) : "暂无可用行情时点";
    return `<div class="page-head"><div><div class="eyebrow">本地模拟盘</div><h1>${escapeHtml(title)}</h1><p class="snapshot-note">${escapeHtml(description)}</p></div><div class="snapshot-note">行情数据截至：${escapeHtml(asOf)}<br>快照导出时间：${escapeHtml(formatTime(snapshot.generated_at))}</div></div>`;
  }

  function kpis(items) { return `<section class="kpis">${items.map(([name, value]) => `<div class="kpi"><span>${name}</span><b>${value}</b></div>`).join("")}</section>`; }
  function periodControls() { return `<div class="period-controls" role="group" aria-label="权益图周期"><button data-period="intraday" class="period active">日内</button><button data-period="daily" class="period">按日</button><button data-period="five-day" class="period">近5日</button></div>`; }

  function wireChartPeriod(root, curve, label) {
    const chart = root.querySelector("#equity-chart");
    const draw = (period) => renderEquityChart(chart, filterEquityCurve(curve, period), label, period);
    draw("intraday");
    root.querySelectorAll(".period").forEach((button) => button.addEventListener("click", () => {
      root.querySelectorAll(".period").forEach((item) => item.classList.toggle("active", item === button));
      draw(button.dataset.period);
    }));
  }

  function filterEquityCurve(curve, period) {
    const records = (Array.isArray(curve) ? curve : []).filter((row) => Number.isFinite(Number(row.equity)));
    if (period === "intraday") return records;
    const daily = new Map();
    records.forEach((row) => { const key = String(row.timestamp || row.trade_date || "").slice(0, 10); if (key) daily.set(key, row); });
    const rows = [...daily.values()];
    return period === "five-day" ? rows.slice(-5) : rows;
  }

  function latestPositions(account) {
    const rows = Array.isArray(account.positions) ? account.positions : [];
    const newest = rows.reduce((result, row) => Math.max(result, Date.parse(row.timestamp || "") || 0), 0);
    return rows.filter((row) => (Date.parse(row.timestamp || "") || 0) === newest && numeric(row.quantity) > 0);
  }

  function positionTable(rows) {
    return tableMarkup(rows, ["symbol_display", "quantity", "market_value", "timestamp"]);
  }

  function orderTable(rows) {
    if (!rows.length) return empty("暂无订单审计记录。");
    return `<div class="table-wrap"><table class="data-table"><thead><tr><th>标的</th><th>方向</th><th>数量</th><th>状态</th><th>卖出盈亏</th><th>时间</th><th>审计详情</th></tr></thead><tbody>${rows.map((row) => `<tr><td>${symbolCell(row)}</td><td>${sideCell(row)}</td><td>${escapeHtml(String(row.quantity ?? "—"))}</td><td>${statusCell(row)}</td><td>${profitCell(row)}</td><td>${escapeHtml(formatTime(row.timestamp))}</td><td>${details(row)}</td></tr>`).join("")}</tbody></table></div>`;
  }

  function fillTable(rows) {
    if (!rows.length) return empty("暂无成交审计记录。");
    return `<div class="table-wrap"><table class="data-table"><thead><tr><th>标的</th><th>方向</th><th>数量</th><th>成交价格</th><th>卖出盈亏</th><th>成交时间</th></tr></thead><tbody>${rows.map((row) => `<tr><td>${symbolCell(row)}</td><td>${sideCell(row)}</td><td>${escapeHtml(String(row.quantity ?? "—"))}</td><td>${money(row.price)}</td><td>${profitCell(row)}</td><td>${escapeHtml(formatTime(row.timestamp))}</td></tr>`).join("")}</tbody></table></div>`;
  }

  function logMarkup(account) {
    const rows = [...(account.timeline || []), ...(account.exceptions || [])].sort((a, b) => String(b.timestamp || "").localeCompare(String(a.timestamp || "")));
    return `<div class="timeline">${timelineMarkup(rows)}</div>`;
  }

  function tableMarkup(rows, columns) {
    if (!rows?.length) return empty("暂无可展示的审计记录。");
    return `<div class="table-wrap"><table class="data-table"><thead><tr>${columns.map((column) => `<th>${labelFor(column)}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${columns.map((column) => `<td>${formatCell(row, column)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  }

  function timelineMarkup(rows) {
    if (!rows?.length) return empty("暂无执行活动或异常记录。");
    return rows.map((row) => `<article class="event"><time>${escapeHtml(formatTime(row.timestamp || row.created_at))}</time>${escapeHtml(eventMessage(row))}</article>`).join("");
  }

  function eventMessage(row) {
    if (String(row.status).toLowerCase() === "rejected") return `未执行：${rejectionReason(row)}`;
    return row.message || row.reason || row.event || row.exception_type || row.status_display || row.status || "已记录审计事件";
  }
  function rejectionReason(row) { return row.reason || row.reject_reason || row.message || "订单未通过执行条件或容量校验，未产生成交。"; }
  function symbolCell(row) { return `<b>${escapeHtml(row.display_name || row.symbol || "—")}</b><small class="code">${escapeHtml(row.symbol || "")}</small>`; }
  function sideCell(row) { return escapeHtml(row.side_display || ({ buy: "买入", sell: "卖出" }[String(row.side).toLowerCase()] || row.side || "—")); }
  function statusCell(row) { const rejected = String(row.status).toLowerCase() === "rejected"; return `<span class="status${rejected ? " rejected" : ""}">${escapeHtml(row.status_display || (rejected ? "已拒绝（未执行）" : row.status || "—"))}</span>${rejected ? `<small class="status-note">未执行：${escapeHtml(rejectionReason(row))}</small>` : ""}`; }
  function profitCell(row) { return row.profit_loss === null || row.profit_loss === undefined ? "—" : `<span class="${numeric(row.profit_loss) >= 0 ? "positive" : "negative"}">${money(row.profit_loss)}</span>`; }
  function details(row) { return `<details class="audit-detail"><summary>展开</summary>${escapeHtml(JSON.stringify(row, null, 2))}</details>`; }
  function empty(message) { return `<div class="empty">${escapeHtml(message)}</div>`; }

  function renderEquityChart(container, curve, label, period) {
    if (!container) return;
    container.innerHTML = "";
    const pointsData = curve.map((row) => ({ row, value: numeric(row.equity) })).filter((point) => Number.isFinite(point.value));
    if (!pointsData.length) { container.innerHTML = empty("暂无权益快照；审计数据写入后将自动显示。"); return; }
    const values = pointsData.map((point) => point.value);
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.classList.add("equity-chart"); svg.setAttribute("viewBox", "0 0 760 300"); svg.setAttribute("role", "img"); svg.setAttribute("aria-label", `${label}${period}权益走势`);
    const left = 74, top = 20, width = 650, height = 220, bottom = top + height;
    const min = Math.min(...values), max = Math.max(...values), range = max - min || Math.max(Math.abs(max) * 0.01, 1);
    const x = (index) => left + (values.length === 1 ? width / 2 : index * width / (values.length - 1));
    const y = (value) => top + height - (value - min) / range * height;
    const add = (name, attrs, text) => { const node = document.createElementNS("http://www.w3.org/2000/svg", name); Object.entries(attrs || {}).forEach(([key, value]) => node.setAttribute(key, value)); if (text !== undefined) node.textContent = text; svg.appendChild(node); return node; };
    add("line", { x1: left, y1: top, x2: left, y2: bottom, class: "axis" }); add("line", { x1: left, y1: bottom, x2: left + width, y2: bottom, class: "axis" });
    for (let index = 0; index < 4; index += 1) { const value = min + range * index / 3; const yy = y(value); add("line", { x1: left, y1: yy, x2: left + width, y2: yy, class: "axis", opacity: ".45" }); add("text", { x: 4, y: yy + 4, class: "axis-label" }, compactMoney(value)); }
    [...new Set([0, Math.floor((values.length - 1) / 2), values.length - 1])].forEach((index) => add("text", { x: x(index), y: bottom + 25, "text-anchor": "middle", class: "axis-label" }, shortTime(pointsData[index].row.timestamp || pointsData[index].row.trade_date)));
    const points = values.map((value, index) => `${x(index)},${y(value)}`).join(" "); add("polygon", { points: `${left},${bottom} ${points} ${left + width},${bottom}`, class: "series-area" }); add("polyline", { points, class: "series" });
    const focus = add("circle", { cx: x(0), cy: y(values[0]), r: 4, class: "point", opacity: "0" }); const tooltip = document.createElement("div"); tooltip.className = "chart-tooltip"; container.append(svg, tooltip);
    svg.addEventListener("pointermove", (event) => { const rect = svg.getBoundingClientRect(); const px = (event.clientX - rect.left) / rect.width * 760; const nearest = Math.max(0, Math.min(values.length - 1, Math.round((px - left) / width * (values.length - 1)))); focus.setAttribute("cx", x(nearest)); focus.setAttribute("cy", y(values[nearest])); focus.setAttribute("opacity", "1"); tooltip.style.display = "block"; tooltip.style.left = `${Math.min(container.clientWidth - 150, Math.max(5, event.clientX - rect.left + 10))}px`; tooltip.style.top = `${Math.max(4, event.clientY - rect.top - 44)}px`; tooltip.textContent = `${shortTime(pointsData[nearest].row.timestamp || pointsData[nearest].row.trade_date)} · ${money(values[nearest])}`; });
    svg.addEventListener("pointerleave", () => { tooltip.style.display = "none"; focus.setAttribute("opacity", "0"); });
  }

  function formatCell(row, key) { if (key === "symbol_display") return symbolCell(row); if (key === "market_value") return money(row.market_value); if (key === "timestamp") return escapeHtml(formatTime(row.timestamp)); return escapeHtml(String(row[key] ?? "—")); }
  function labelFor(key) { return ({ symbol_display: "标的", quantity: "数量", market_value: "市值", timestamp: "快照时间" })[key] || key; }
  function money(value) { return Number.isFinite(Number(value)) ? currency.format(Number(value)) : "—"; }
  function percent(value) { return Number.isFinite(Number(value)) ? `${(Number(value) * 100).toFixed(2)}%` : "—"; }
  function compactMoney(value) { return `${(numeric(value) / 10000).toFixed(1)}万`; }
  function formatTime(value) { const date = value ? new Date(value) : null; return date && !Number.isNaN(date.valueOf()) ? date.toLocaleString("zh-CN", { hour12: false }) : (value || "—"); }
  function shortTime(value) { const date = value ? new Date(value) : null; return date && !Number.isNaN(date.valueOf()) ? `${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")} ${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}` : (value || "—"); }
  function escapeHtml(value) { return String(value ?? "").replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]); }
})();
