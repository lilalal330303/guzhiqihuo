(() => {
  "use strict";

  const page = document.body.dataset.page || "overview";
  const app = document.getElementById("app");
  const currency = new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY", maximumFractionDigits: 2 });
  const wholeCurrency = new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY", maximumFractionDigits: 0 });
  const numeric = (value) => Number.isFinite(Number(value)) ? Number(value) : 0;
  const savedTheme = (() => { try { return localStorage.getItem("paper-theme"); } catch (_) { return null; } })();
  document.documentElement.dataset.theme = savedTheme || "dark";

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
    wireThemeToggle();
    const view = document.getElementById("view");
    if (page === "strategy") renderStrategy(view, account, snapshot);
    else if (page === "positions") renderPositions(view, account, snapshot);
    else if (page === "orders") renderOrders(view, account, snapshot);
    else if (page === "logs") renderLogs(view, account, snapshot);
    else renderOverview(view, accounts, account, snapshot);
    decorateMobileTables(app);
    new MutationObserver(() => decorateMobileTables(app)).observe(view, { childList: true, subtree: true });
  }

  function decorateMobileTables(root) {
    root.querySelectorAll(".table-wrap:not([data-mobile-ready])").forEach((wrapper) => {
      wrapper.dataset.mobileReady = "true";
      wrapper.insertAdjacentHTML("beforebegin", '<div class="mobile-scroll-hint" aria-hidden="true">左右滑动查看完整信息 →</div>');
    });
    root.querySelectorAll(".data-table tbody tr:not(.terminal-row)").forEach((row) => row.classList.add("terminal-row"));
  }

  function selectedAccountFromRoute(accounts) {
    const wanted = new URLSearchParams(window.location.search).get("id");
    return accounts.find((item) => item.id === wanted) || accounts[0];
  }

  function shell(snapshot, accounts, current) {
    const currentId = encodeURIComponent(current.id);
    const navItems = [
      ["index.html", "策略总览", "overview", "⌂"],
      [`positions.html?id=${currentId}`, "持仓", "positions", "▤"],
      [`orders.html?id=${currentId}`, "订单", "orders", "⇄"],
      [`logs.html?id=${currentId}`, "日志", "logs", "≡"],
    ];
    const nav = navItems.map(([href, label, key]) => `<a href="${href}" class="${page === key ? "active" : ""}">${key === "orders" ? "订单与成交" : key === "logs" ? "运行日志" : label}</a>`).join("");
    const mobileNav = navItems.map(([href, label, key, icon]) => `<a class="mobile-nav-link" href="${href}" ${page === key ? 'aria-current="page"' : ""}><span aria-hidden="true">${icon}</span><b>${label}</b></a>`).join("");
    const cards = accounts.map((item) => {
      const metrics = item.metrics || {};
      const active = item.id === current.id ? " active" : "";
      return `<a class="account-link${active}" href="strategy.html?id=${encodeURIComponent(item.id)}"><i class="hud-corner" aria-hidden="true"></i><div class="account-name">${escapeHtml(item.display?.name || item.id)}</div><div class="account-value">${wholeMoney(metrics.equity ?? item.display?.initial_cash)}</div><div class="account-meta">持仓 ${numeric(metrics.position_count)} 个 · 独立账户</div></a>`;
    }).join("");
    const currentName = escapeHtml(current.display?.name || current.id);
    const currentModule = escapeHtml((navItems.find((item) => item[2] === page) || navItems[0])[1]);
    const marketSnapshot = escapeHtml(formatTime(snapshot.market_data_as_of));
    return `<header class="topbar"><div class="brand">量化研究 <small>模拟盘</small></div><div class="command-module"><small>COMMAND MODULE</small><b>${currentModule}</b></div><div class="mobile-context">${currentName}</div><nav class="topnav" aria-label="模拟盘导航">${nav}</nav><div class="command-status"><span class="live-dot"></span><small>行情快照</small><b>${marketSnapshot}</b></div><div class="source">审计快照 · ${escapeHtml(formatTime(snapshot.generated_at))}</div><button class="theme-toggle" type="button" aria-label="切换显示主题"></button></header><nav class="mobile-nav" aria-label="移动端模拟盘导航">${mobileNav}</nav><div class="layout"><aside class="rail"><div class="rail-label">策略账户 / ${accounts.length}</div>${cards}</aside>`;
  }

  function wireThemeToggle() {
    const button = document.querySelector(".theme-toggle");
    if (!button) return;
    const sync = () => {
      const dark = document.documentElement.dataset.theme === "dark";
      button.textContent = dark ? "☀ 亮色" : "☾ 深色";
      button.setAttribute("aria-pressed", String(dark));
      button.title = dark ? "切换为亮色主题" : "切换为深色主题";
    };
    sync();
    button.addEventListener("click", () => {
      const theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = theme;
      try { localStorage.setItem("paper-theme", theme); } catch (_) { /* local file privacy mode */ }
      sync();
    });
  }

  function renderOverview(root, accounts, current, snapshot) {
    root.innerHTML = pageHead("模拟盘策略总览", "账户之间独立核算；点击左侧策略进入其独立详情。", snapshot) +
      `<section class="strategy-summary">${accounts.map(accountCard).join("")}</section>` +
      `<section class="panel"><div class="section-title"><div><h2>${escapeHtml(current.display?.name || current.id)} · 权益走势</h2><p>当前策略</p></div>${periodControls()}</div><div class="chart-wrap" id="equity-chart"></div></section>` +
      `<section class="grid"><section class="panel"><h2>当前策略最近执行活动</h2><div class="timeline">${timelineMarkup(visibleTimeline(current.timeline || []).slice(-8).reverse())}</div></section><section class="panel"><h2>当前持仓</h2>${positionTable(latestPositions(current))}</section></section>`;
    wireChartPeriod(root, current, current.display?.name || current.id);
  }

  function accountCard(account) {
    const m = account.metrics || {};
    return `<a class="strategy-card" href="strategy.html?id=${encodeURIComponent(account.id)}"><div class="eyebrow">独立策略账户</div><h2>${escapeHtml(account.display?.name || account.id)}</h2>${kpis([["账户权益", wholeMoney(m.equity)], ["可用现金", wholeMoney(m.cash)], ["持仓市值", wholeMoney(m.position_market_value)], ["累计收益", percent(m.total_return)]])}</a>`;
  }

  function renderStrategy(root, account, snapshot) {
    const m = account.metrics || {};
    root.innerHTML = pageHead(account.display?.name || account.id, "独立策略视图：总览、持仓、订单和日志均只显示当前策略。", snapshot) +
      kpis([["账户权益", wholeMoney(m.equity)], ["可用现金", wholeMoney(m.cash)], ["持仓市值", wholeMoney(m.position_market_value)], ["累计收益", percent(m.total_return)]]) +
      `<section class="panel"><div class="section-title"><div><h2>权益走势</h2><p>当前策略</p></div>${periodControls()}</div><div class="chart-wrap" id="equity-chart"></div></section>` +
      `<div class="tabs" role="tablist"><button class="tab" role="tab" aria-selected="true" data-tab="positions">持仓</button><button class="tab" role="tab" aria-selected="false" data-tab="orders">订单</button><button class="tab" role="tab" aria-selected="false" data-tab="fills">成交</button><button class="tab" role="tab" aria-selected="false" data-tab="timeline">执行活动</button><button class="tab" role="tab" aria-selected="false" data-tab="logs">运行日志</button></div><section class="panel" id="tab-content"></section>`;
    wireChartPeriod(root, account, account.display?.name || account.id);
    const content = root.querySelector("#tab-content");
    const show = (tab) => {
      content.innerHTML = tab === "positions" ? positionHistoryMarkup(account.position_history || [])
        : tab === "orders" ? datedAuditMarkup("order-date", "订单日期", visibleOrders(account.orders || []), orderTable)
        : tab === "fills" ? datedAuditMarkup("fill-date", "成交日期", account.fills || [], fillTable)
        : tab === "timeline" ? datedAuditMarkup("activity-date", "活动日期", visibleTimeline(account.timeline || []).slice().reverse(), (rows) => `<div class="timeline">${timelineMarkup(rows)}</div>`)
        : datedAuditMarkup("log-date", "日志日期", auditLogRows(account), (rows) => `<div class="timeline">${timelineMarkup(rows)}</div>`);
      if (tab === "positions") wirePositionHistory(content, account.position_history || []);
      else wireDateFilter(content);
    };
    show("positions");
    root.querySelectorAll(".tab").forEach((button) => button.addEventListener("click", () => {
      root.querySelectorAll(".tab").forEach((tab) => tab.setAttribute("aria-selected", String(tab === button)));
      show(button.dataset.tab);
    }));
  }

  function renderPositions(root, account, snapshot) {
    root.innerHTML = scopedHead("历史持仓", account, snapshot, "按交易日查看当日持仓品种变化和单品种盈亏。") + `<section class="panel">${positionHistoryMarkup(account.position_history || [])}</section>`;
    wirePositionHistory(root, account.position_history || []);
  }

  function renderOrders(root, account, snapshot) {
    const orders = visibleOrders(account.orders || []), fills = account.fills || [];
    root.innerHTML = scopedHead("订单与成交", account, snapshot, "按交易日核对有效订单与成交；被拒绝订单仅保留在底层审计库。") + `<section class="panel"><div class="section-title"><div><h2>订单与成交</h2><p>同一日期口径联动展示</p></div></div>${combinedOrderFilterMarkup(orders, fills)}</section>`;
    wireOrderDateFilter(root, orders, fills);
  }

  function renderLogs(root, account, snapshot) {
    root.innerHTML = scopedHead("运行日志", account, snapshot, "执行活动和异常记录仅属于当前策略，可按交易日回溯。") + `<section class="panel">${datedAuditMarkup("log-date", "日志日期", auditLogRows(account), (rows) => `<div class="timeline">${timelineMarkup(rows)}</div>`)}</section>`;
    wireDateFilter(root);
  }

  function scopedHead(title, account, snapshot, description) {
    return pageHead(title, description, snapshot) + `<div class="scope-label">当前策略：<b>${escapeHtml(account.display?.name || account.id)}</b></div>`;
  }

  function pageHead(title, description, snapshot) {
    const asOf = snapshot.market_data_as_of ? formatTime(snapshot.market_data_as_of) : "暂无可用行情时点";
    const schedule = snapshot.snapshot_schedule || { label: "盘后快照", time: "15:05" };
    return `<div class="page-head"><div><div class="eyebrow">本地模拟盘</div><h1>${escapeHtml(title)}</h1><p class="snapshot-note">${escapeHtml(description)}</p></div><div class="snapshot-status"><span class="live-dot"></span><div>行情实际截至：<b>${escapeHtml(asOf)}</b><br>${escapeHtml(schedule.label || "盘后快照")}计划：<b>${escapeHtml(schedule.time || "15:05")}</b><br><small>快照导出：${escapeHtml(formatTime(snapshot.generated_at))}</small></div></div></div>`;
  }

  function kpis(items) { return `<section class="kpis">${items.map(([name, value]) => `<div class="kpi"><i class="hud-corner" aria-hidden="true"></i><span class="hud-label">${name}</span><b>${value}</b></div>`).join("")}</section>`; }
  function periodControls() { return `<div class="period-controls" role="group" aria-label="权益图周期"><button data-period="intraday" class="period active">日内</button><button data-period="daily" class="period">按日</button><button data-period="five-day" class="period">近5日</button></div>`; }

  function wireChartPeriod(root, account, label) {
    const chart = root.querySelector("#equity-chart");
    const curve = account.equity_curve || [];
    const dailyBars = account.daily_equity_bars || [];
    const fiveDayCurve = filterLastFiveTradingDays(curve);
    const intradayCurve = filterLatestTradingDay(curve);
    const draw = (period) => {
      if (period === "daily") renderDailyEquityBars(chart, dailyBars, label);
      else if (period === "five-day") renderFiveDayIntradayChart(chart, fiveDayCurve, label);
      else renderEquityChart(chart, intradayCurve, label, period);
    };
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

  function filterLatestTradingDay(curve) {
    const records = (Array.isArray(curve) ? curve : []).filter((row) => Number.isFinite(Number(row.equity)));
    const dates = [...new Set(records.map(tradeDate).filter(Boolean))].sort();
    const latest = dates[dates.length - 1];
    return latest ? records.filter((row) => tradeDate(row) === latest) : records;
  }

  function filterLastFiveTradingDays(curve) {
    const rows = (Array.isArray(curve) ? curve : []).filter((row) => Number.isFinite(Number(row.equity)) && tradeDate(row));
    const dates = [...new Set(rows.map(tradeDate))].sort().slice(-5);
    return rows.filter((row) => dates.includes(tradeDate(row))).sort((a, b) => String(a.timestamp).localeCompare(String(b.timestamp)));
  }

  function latestPositions(account) {
    const rows = Array.isArray(account.positions) ? account.positions : [];
    const newest = rows.reduce((result, row) => Math.max(result, Date.parse(row.timestamp || "") || 0), 0);
    return rows.filter((row) => (Date.parse(row.timestamp || "") || 0) === newest && numeric(row.quantity) > 0);
  }

  function visibleOrders(rows) {
    return (Array.isArray(rows) ? rows : []).filter((row) => String(row.status).toLowerCase() !== "rejected");
  }

  function visibleTimeline(rows) {
    return (Array.isArray(rows) ? rows : []).filter((row) => [row.event, row.reason, row.message, row.exception_type]
      .every((value) => String(value || "").toLowerCase() !== "intent_missing"));
  }

  function tradeDate(row) { return String(row.timestamp || row.created_at || row.trade_date || "").slice(0, 10); }
  function filterByTradeDate(rows, date) { return (Array.isArray(rows) ? rows : []).filter((row) => tradeDate(row) === date); }
  function auditDates(...groups) { return [...new Set(groups.flat().map(tradeDate).filter(Boolean))].sort().reverse(); }
  function dateOptions(dates) { return dates.map((date, index) => `<option value="${escapeHtml(date)}"${index === 0 ? " selected" : ""}>${escapeHtml(date)}</option>`).join(""); }

  function datedAuditMarkup(id, label, rows, renderer) {
    const dates = auditDates(rows);
    if (!dates.length) return renderer([]);
    return `<div class="audit-filter"><label for="${id}">${escapeHtml(label)}</label><select id="${id}" data-date-filter>${dateOptions(dates)}</select><span>${dates.length} 个交易日可回溯</span></div><div class="dated-audit" data-date-target data-records="${escapeHtml(JSON.stringify(rows))}"></div>`;
  }

  function wireDateFilter(root) {
    root.querySelectorAll("[data-date-filter]").forEach((select) => {
      const target = select.parentElement?.nextElementSibling;
      if (!target) return;
      let rows = [];
      try { rows = JSON.parse(target.dataset.records || "[]"); } catch (_) { rows = []; }
      const kind = select.id.startsWith("order") ? "order" : select.id.startsWith("fill") ? "fill" : "timeline";
      const draw = () => {
        const filtered = filterByTradeDate(rows, select.value);
        target.innerHTML = kind === "order" ? orderTable(filtered) : kind === "fill" ? fillTable(filtered) : `<div class="timeline">${timelineMarkup(filtered)}</div>`;
        target.classList.remove("view-refresh"); void target.offsetWidth; target.classList.add("view-refresh");
      };
      select.addEventListener("change", draw); draw();
    });
  }

  function combinedOrderFilterMarkup(orders, fills) {
    const dates = auditDates(orders, fills);
    if (!dates.length) return empty("暂无订单与成交审计记录。");
    return `<div class="audit-filter"><label for="order-date">交易日期</label><select id="order-date">${dateOptions(dates)}</select><span>订单与成交同步切换</span></div><div id="order-day-content"></div>`;
  }

  function wireOrderDateFilter(root, orders, fills) {
    const select = root.querySelector("#order-date"), target = root.querySelector("#order-day-content");
    if (!select || !target) return;
    const draw = () => {
      target.innerHTML = `<div class="audit-split"><section><h3>有效订单</h3>${orderTable(filterByTradeDate(orders, select.value))}</section><section><h3>成交明细</h3>${fillTable(filterByTradeDate(fills, select.value))}</section></div>`;
      target.classList.remove("view-refresh"); void target.offsetWidth; target.classList.add("view-refresh");
    };
    select.addEventListener("change", draw); draw();
  }

  function auditLogRows(account) {
    return visibleTimeline([...(account.timeline || []), ...(account.exceptions || [])]).sort((a, b) => String(b.timestamp || "").localeCompare(String(a.timestamp || "")));
  }

  function positionHistoryMarkup(history) {
    if (!history.length) return empty("暂无历史持仓快照。");
    const options = history.slice().reverse().map((day, index) => `<option value="${escapeHtml(day.trade_date)}"${index === 0 ? " selected" : ""}>${escapeHtml(day.trade_date)}</option>`).join("");
    return `<div class="history-toolbar"><label for="history-date">持仓日期</label><select id="history-date" class="history-date">${options}</select><span>展示当日最后一个审计快照</span></div><div id="history-table"></div>`;
  }

  function wirePositionHistory(root, history) {
    const select = root.querySelector("#history-date");
    const target = root.querySelector("#history-table");
    if (!select || !target || !history.length) return;
    const draw = () => {
      const day = history.find((item) => item.trade_date === select.value) || history[history.length - 1];
      target.innerHTML = historyPositionTable(day.holdings || [], day);
    };
    select.addEventListener("change", draw);
    draw();
  }

  function historyPositionTable(rows, day) {
    if (!rows.length) return empty("当日无持仓变化记录。");
    return `<div class="history-caption">${escapeHtml(day.trade_date)} · 快照 ${escapeHtml(formatTime(day.timestamp))}</div><div class="table-wrap"><table class="data-table history-table"><thead><tr><th>标的</th><th>动作</th><th>持仓数量</th><th>持仓变化</th><th>收盘价</th><th>市值</th><th>平均成本</th><th>已实现盈亏</th><th>浮动盈亏</th><th>单品种总盈亏</th></tr></thead><tbody>${rows.map((row) => `<tr><td>${symbolCell(row)}</td><td><span class="action action-${escapeHtml(row.action)}">${escapeHtml(row.action)}</span></td><td>${formatQuantity(row.quantity)}</td><td>${signedQuantity(row.quantity_change)}</td><td>${priceCell(row.close)}</td><td>${money(row.market_value)}</td><td>${priceCell(row.average_cost)}</td><td>${pnlValue(row.realized_pnl)}</td><td>${pnlValue(row.unrealized_pnl)}</td><td>${pnlValue(row.total_pnl)}</td></tr>`).join("")}</tbody></table></div>`;
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
    const rows = visibleTimeline([...(account.timeline || []), ...(account.exceptions || [])]).sort((a, b) => String(b.timestamp || "").localeCompare(String(a.timestamp || "")));
    return `<div class="timeline">${timelineMarkup(rows)}</div>`;
  }

  function tableMarkup(rows, columns) {
    if (!rows?.length) return empty("暂无可展示的审计记录。");
    return `<div class="table-wrap"><table class="data-table"><thead><tr>${columns.map((column) => `<th>${labelFor(column)}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${columns.map((column) => `<td>${formatCell(row, column)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  }

  function timelineMarkup(rows) {
    if (!rows?.length) return empty("暂无执行活动或异常记录。");
    return rows.map((row) => `<article class="event terminal-row"><time>${escapeHtml(formatTime(row.timestamp || row.created_at))}</time>${escapeHtml(eventMessage(row))}</article>`).join("");
  }

  function eventMessage(row) {
    if (String(row.status).toLowerCase() === "rejected") return `未执行：${rejectionReason(row)}`;
    const raw = row.message || row.reason || row.event || row.exception_type || row.status_display || row.status;
    return translateAuditText(raw) || "已记录审计事件";
  }
  function rejectionReason(row) {
    const raw = row.reason || row.reject_reason || row.message;
    const reasons = {
      insufficient_cash: "可用资金不足",
      participation_cap: "超过单分钟容量上限",
      capacity_limit: "超过成交容量上限",
      invalid_price: "行情价格无效",
      suspended: "标的停牌",
    };
    return reasons[String(raw || "").toLowerCase()] || raw || "订单未通过执行条件或容量校验，未产生成交。";
  }
  function symbolCell(row) { return `<b>${escapeHtml(row.display_name || row.symbol || "—")}</b><small class="code">${escapeHtml(row.symbol || "")}</small>`; }
  function sideCell(row) { return escapeHtml(row.side_display || ({ buy: "买入", sell: "卖出" }[String(row.side).toLowerCase()] || row.side || "—")); }
  function statusCell(row) { const rejected = String(row.status).toLowerCase() === "rejected"; const label = rejected ? "已拒绝（未执行）" : translateAuditText(row.status_display || row.status) || "—"; return `<span class="status${rejected ? " rejected" : ""}">${escapeHtml(label)}</span>${rejected ? `<small class="status-note">未执行：${escapeHtml(rejectionReason(row))}</small>` : ""}`; }
  function translateAuditText(value) {
    const raw = String(value || "");
    const labels = {
      filled: "已成交", partial: "部分成交", pending: "待执行", submitted: "已提交",
      cancelled: "已撤销", canceled: "已撤销", rejected: "已拒绝（未执行）",
      intent_missing: "当前时点无待执行交易意图", recovered_no_action: "恢复审计：无需执行",
      audit: "已记录审计事件", signal: "已生成策略信号", order: "已生成订单",
    };
    return labels[raw.toLowerCase()] || raw;
  }
  function profitCell(row) { return row.profit_loss === null || row.profit_loss === undefined ? "—" : `<span class="${numeric(row.profit_loss) >= 0 ? "positive" : "negative"}">${money(row.profit_loss)}</span>`; }
  function pnlValue(value) { return value === null || value === undefined ? "—" : `<span class="${numeric(value) >= 0 ? "positive" : "negative"}">${money(value)}</span>`; }
  function priceCell(value) { return Number.isFinite(Number(value)) ? Number(value).toFixed(4) : "—"; }
  function formatQuantity(value) { return Number.isFinite(Number(value)) ? Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 0 }) : "—"; }
  function signedQuantity(value) { const number = Number(value); return Number.isFinite(number) ? `${number > 0 ? "+" : ""}${number.toLocaleString("zh-CN", { maximumFractionDigits: 0 })}` : "—"; }
  function details(row) { return `<details class="audit-detail"><summary>展开</summary>${escapeHtml(JSON.stringify(row, null, 2))}</details>`; }
  function empty(message) { return `<div class="empty">${escapeHtml(message)}</div>`; }

  function renderFiveDayIntradayChart(container, curve, label) {
    renderEquityChart(container, curve, label, "近5日日内权益拼接", true);
  }

  function paddedDomain(values) {
    const clean = values.map(Number).filter(Number.isFinite);
    if (!clean.length) return { min: 0, max: 1, range: 1 };
    const low = Math.min(...clean), high = Math.max(...clean);
    const padding = Math.max((high - low) * .12, Math.abs(high) * .002, 1);
    const min = low - padding, max = high + padding;
    return { min, max, range: Math.max(max - min, 1) };
  }

  function renderEquityChart(container, curve, label, period, showDaySeparators = false) {
    if (!container) return;
    container.innerHTML = "";
    const pointsData = curve.map((row) => ({ row, value: numeric(row.equity) })).filter((point) => Number.isFinite(point.value));
    if (!pointsData.length) { container.innerHTML = empty("暂无权益快照；审计数据写入后将自动显示。"); return; }
    const values = pointsData.map((point) => point.value);
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.classList.add("equity-chart"); svg.setAttribute("viewBox", "0 0 760 300"); svg.setAttribute("role", "img"); svg.setAttribute("aria-label", `${label}${period}权益走势`);
    const left = 74, top = 20, width = 650, height = 220, bottom = top + height;
    const { min, range } = paddedDomain(values);
    const x = (index) => left + (values.length === 1 ? width / 2 : index * width / (values.length - 1));
    const y = (value) => top + height - (value - min) / range * height;
    const add = (name, attrs, text) => { const node = document.createElementNS("http://www.w3.org/2000/svg", name); Object.entries(attrs || {}).forEach(([key, value]) => node.setAttribute(key, value)); if (text !== undefined) node.textContent = text; svg.appendChild(node); return node; };
    add("line", { x1: left, y1: top, x2: left, y2: bottom, class: "axis" }); add("line", { x1: left, y1: bottom, x2: left + width, y2: bottom, class: "axis" });
    for (let index = 0; index < 4; index += 1) { const value = min + range * index / 3; const yy = y(value); add("line", { x1: left, y1: yy, x2: left + width, y2: yy, class: "axis", opacity: ".45" }); add("text", { x: 4, y: yy + 4, class: "axis-label" }, compactMoney(value)); }
    [...new Set([0, Math.floor((values.length - 1) / 2), values.length - 1])].forEach((index) => add("text", { x: x(index), y: bottom + 25, "text-anchor": "middle", class: "axis-label" }, shortTime(pointsData[index].row.timestamp || pointsData[index].row.trade_date)));
    if (showDaySeparators) {
      let previousDay = tradeDate(pointsData[0].row);
      add("text", { x: x(0), y: bottom + 25, "text-anchor": "start", class: "axis-label day-label" }, previousDay.slice(5));
      pointsData.forEach((point, index) => {
        const day = tradeDate(point.row);
        if (day !== previousDay) {
          add("line", { x1: x(index), y1: top, x2: x(index), y2: bottom, class: "day-separator" });
          add("text", { x: x(index) + 3, y: bottom + 25, "text-anchor": "start", class: "axis-label day-label" }, day.slice(5));
          previousDay = day;
        }
      });
    }
    const points = values.map((value, index) => `${x(index)},${y(value)}`).join(" "); add("polygon", { points: `${left},${bottom} ${points} ${left + width},${bottom}`, class: "series-area" }); add("polyline", { points, class: "series" });
    const crosshairX = add("line", { x1: left, y1: top, x2: left, y2: bottom, class: "chart-crosshair-x", opacity: "0" });
    const crosshairY = add("line", { x1: left, y1: top, x2: left + width, y2: top, class: "chart-crosshair-y", opacity: "0" });
    const focus = add("circle", { cx: x(0), cy: y(values[0]), r: 4, class: "point", opacity: "0" }); const tooltip = document.createElement("div"); tooltip.className = "chart-tooltip"; container.append(svg, tooltip);
    svg.addEventListener("pointermove", (event) => { const rect = svg.getBoundingClientRect(); const px = (event.clientX - rect.left) / rect.width * 760; const nearest = Math.max(0, Math.min(values.length - 1, Math.round((px - left) / width * (values.length - 1)))); const focusX = x(nearest), focusY = y(values[nearest]); focus.setAttribute("cx", focusX); focus.setAttribute("cy", focusY); focus.setAttribute("opacity", "1"); crosshairX.setAttribute("x1", focusX); crosshairX.setAttribute("x2", focusX); crosshairX.setAttribute("opacity", ".75"); crosshairY.setAttribute("y1", focusY); crosshairY.setAttribute("y2", focusY); crosshairY.setAttribute("opacity", ".75"); tooltip.style.display = "block"; tooltip.style.left = `${Math.min(container.clientWidth - 150, Math.max(5, event.clientX - rect.left + 10))}px`; tooltip.style.top = `${Math.max(4, event.clientY - rect.top - 44)}px`; tooltip.textContent = `${shortTime(pointsData[nearest].row.timestamp || pointsData[nearest].row.trade_date)} · ${money(values[nearest])}`; });
    svg.addEventListener("pointerleave", () => { tooltip.style.display = "none"; focus.setAttribute("opacity", "0"); crosshairX.setAttribute("opacity", "0"); crosshairY.setAttribute("opacity", "0"); });
  }

  function renderDailyEquityBars(container, bars, label) {
    if (!container) return;
    container.innerHTML = "";
    if (!bars.length) { container.innerHTML = empty("暂无按日权益数据。"); return; }
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.classList.add("equity-chart"); svg.setAttribute("viewBox", "0 0 760 300"); svg.setAttribute("role", "img"); svg.setAttribute("aria-label", `${label}按日权益柱状图`);
    const left = 74, top = 20, width = 650, height = 220, bottom = top + height;
    const values = bars.map((row) => numeric(row.close));
    const { min: floorValue, range } = paddedDomain(values);
    const slot = width / bars.length, barWidth = Math.min(42, slot * .62);
    const y = (value) => top + height - (value - floorValue) / range * height;
    const add = (name, attrs, text) => { const node = document.createElementNS("http://www.w3.org/2000/svg", name); Object.entries(attrs || {}).forEach(([key, value]) => node.setAttribute(key, value)); if (text !== undefined) node.textContent = text; svg.appendChild(node); return node; };
    add("line", { x1: left, y1: top, x2: left, y2: bottom, class: "axis" }); add("line", { x1: left, y1: bottom, x2: left + width, y2: bottom, class: "axis" });
    for (let index = 0; index < 4; index += 1) { const value = floorValue + range * index / 3; const yy = y(value); add("line", { x1: left, y1: yy, x2: left + width, y2: yy, class: "axis", opacity: ".4" }); add("text", { x: 4, y: yy + 4, class: "axis-label" }, compactMoney(value)); }
    bars.forEach((row, index) => { const xx = left + slot * index + (slot - barWidth) / 2; const yy = y(numeric(row.close)); const rect = add("rect", { x: xx, y: yy, width: barWidth, height: Math.max(1, bottom - yy), class: "daily-bar", "data-tone": numeric(row.return) >= 0 ? "up" : "down" }); rect.appendChild(Object.assign(document.createElementNS("http://www.w3.org/2000/svg", "title"), { textContent: `${row.trade_date}  收盘权益 ${money(row.close)}  日涨跌 ${percent(row.return)}` })); add("text", { x: xx + barWidth / 2, y: bottom + 22, "text-anchor": "middle", class: "axis-label" }, String(row.trade_date).slice(5)); });
    container.append(svg);
  }

  function renderEquityCandlesticks(container, bars, label) {
    if (!container) return;
    container.innerHTML = "";
    if (!bars.length) { container.innerHTML = empty("暂无连续5日权益 K 线数据。"); return; }
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.classList.add("equity-chart"); svg.setAttribute("viewBox", "0 0 760 300"); svg.setAttribute("role", "img"); svg.setAttribute("aria-label", `${label}连续5日5分钟权益K线图`);
    const left = 74, top = 20, width = 650, height = 220, bottom = top + height;
    const lows = bars.map((row) => numeric(row.low)), highs = bars.map((row) => numeric(row.high));
    const min = Math.min(...lows), max = Math.max(...highs), padding = Math.max((max - min) * .12, Math.abs(max) * .003, 1), range = max - min + padding * 2;
    const y = (value) => top + height - (value - (min - padding)) / range * height;
    const slot = width / bars.length, bodyWidth = Math.max(2, Math.min(10, slot * .58));
    const add = (name, attrs, text) => { const node = document.createElementNS("http://www.w3.org/2000/svg", name); Object.entries(attrs || {}).forEach(([key, value]) => node.setAttribute(key, value)); if (text !== undefined) node.textContent = text; svg.appendChild(node); return node; };
    add("line", { x1: left, y1: top, x2: left, y2: bottom, class: "axis" }); add("line", { x1: left, y1: bottom, x2: left + width, y2: bottom, class: "axis" });
    for (let index = 0; index < 4; index += 1) { const value = min - padding + range * index / 3; const yy = y(value); add("line", { x1: left, y1: yy, x2: left + width, y2: yy, class: "axis", opacity: ".4" }); add("text", { x: 4, y: yy + 4, class: "axis-label" }, compactMoney(value)); }
    let previousDay = "";
    bars.forEach((row, index) => {
      const center = left + slot * index + slot / 2;
      if (row.trade_date !== previousDay) {
        if (index > 0) add("line", { x1: left + slot * index, y1: top, x2: left + slot * index, y2: bottom, class: "day-separator" });
        add("text", { x: center, y: bottom + 22, "text-anchor": "start", class: "axis-label day-label" }, String(row.trade_date).slice(5));
        previousDay = row.trade_date;
      }
      const up = numeric(row.close) >= numeric(row.open);
      add("line", { x1: center, y1: y(numeric(row.high)), x2: center, y2: y(numeric(row.low)), class: "candle-wick", "data-tone": up ? "up" : "down" });
      const bodyTop = Math.min(y(numeric(row.open)), y(numeric(row.close)));
      const body = add("rect", { x: center - bodyWidth / 2, y: bodyTop, width: bodyWidth, height: Math.max(1.5, Math.abs(y(numeric(row.open)) - y(numeric(row.close)))), class: "candle-body", "data-tone": up ? "up" : "down" });
      body.appendChild(Object.assign(document.createElementNS("http://www.w3.org/2000/svg", "title"), { textContent: `${shortTime(row.timestamp)} · 5分钟  开 ${money(row.open)}  高 ${money(row.high)}  低 ${money(row.low)}  收 ${money(row.close)}` }));
    });
    container.append(svg);
  }

  function formatCell(row, key) { if (key === "symbol_display") return symbolCell(row); if (key === "market_value") return money(row.market_value); if (key === "timestamp") return escapeHtml(formatTime(row.timestamp)); return escapeHtml(String(row[key] ?? "—")); }
  function labelFor(key) { return ({ symbol_display: "标的", quantity: "数量", market_value: "市值", timestamp: "快照时间" })[key] || key; }
  function money(value) { return Number.isFinite(Number(value)) ? currency.format(Number(value)) : "—"; }
  function wholeMoney(value) { return Number.isFinite(Number(value)) ? wholeCurrency.format(Math.trunc(Number(value))) : "—"; }
  function percent(value) { return Number.isFinite(Number(value)) ? `${(Number(value) * 100).toFixed(2)}%` : "—"; }
  function compactMoney(value) { return `${(numeric(value) / 10000).toFixed(1)}万`; }
  function formatTime(value) { const date = value ? new Date(value) : null; return date && !Number.isNaN(date.valueOf()) ? date.toLocaleString("zh-CN", { hour12: false }) : (value || "—"); }
  function shortTime(value) { const date = value ? new Date(value) : null; return date && !Number.isNaN(date.valueOf()) ? `${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")} ${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}` : (value || "—"); }
  function escapeHtml(value) { return String(value ?? "").replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]); }
})();
