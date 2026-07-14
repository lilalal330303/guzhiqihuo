from pathlib import Path
import threading
from urllib.request import urlopen

from reports.serve_paper_trading_site import create_server


ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "docs" / "paper-trading"
PAGES = ("index.html", "strategy.html", "positions.html", "orders.html", "logs.html")


def _read(name: str) -> str:
    return (SITE / name).read_text(encoding="utf-8")


def test_all_pages_load_shared_static_site_resources():
    for page in PAGES:
        content = _read(page)
        assert 'href="styles.css?v=20260714-5"' in content
        assert 'src="app.js?v=20260714-5"' in content
        assert "viewport-fit=cover" in content


def test_static_site_fetches_a_dynamic_snapshot_without_fixed_account_ids():
    source = _read("app.js")
    assert 'fetch("data/snapshot.json")' in source
    assert "v7k_wufu_qixing" not in source
    assert "wufu_v12d" not in source
    for page in PAGES:
        assert "v7k_wufu_qixing" not in _read(page)
        assert "wufu_v12d" not in _read(page)


def test_strategy_route_reads_an_account_query_parameter_and_links_to_dynamic_details():
    source = _read("app.js")
    assert "URLSearchParams" in source
    assert 'get("id")' in source
    assert "strategy.html?id=" in source


def test_chart_draws_svg_axes_and_supports_pointer_tooltips():
    source = _read("app.js")
    assert "function renderEquityChart" in source
    assert "createElementNS" in source
    assert "pointermove" in source
    assert "tooltip" in source
    assert "axis" in source


def test_global_views_keep_a_strategy_scope_from_the_route():
    source = _read("app.js")
    for page in ("positions", "orders", "logs"):
        assert f'page === "{page}"' in source
    assert "selectedAccountFromRoute" in source
    assert "当前策略" in source


def test_order_rows_expose_expandable_audit_detail_and_accessible_focus_styles():
    source = _read("app.js")
    styles = _read("styles.css")
    assert "<details" in source
    assert ":focus-visible" in styles
    assert "@media" in styles


def test_local_site_server_serves_the_snapshot_over_http():
    server = create_server(port=0, open_browser=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        address, port = server.server_address
        with urlopen(f"http://{address}:{port}/paper-trading/data/snapshot.json") as response:
            assert response.status == 200
            assert response.headers.get_content_type() == "application/json"
            assert response.headers["Cache-Control"] == "no-store, no-cache, must-revalidate"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_chart_keeps_each_equity_value_paired_with_its_original_timestamp():
    source = _read("app.js")
    assert "const pointsData = curve" in source
    assert "pointsData[index].row.timestamp" in source
    assert "pointsData[nearest].row.timestamp" in source


def test_static_site_error_guidance_explains_how_to_start_the_local_server():
    source = _read("app.js")
    assert "serve_paper_trading_site.py" in source
    assert "http://127.0.0.1:8765/paper-trading/" in source


def test_static_site_surfaces_data_as_of_and_keeps_the_strategy_rail_fixed():
    source = _read("app.js")
    styles = _read("styles.css")
    assert "market_data_as_of" in source
    assert "position:sticky" in styles
    assert "overflow-wrap:anywhere" in styles


def test_static_site_uses_chinese_display_fields_and_explains_rejected_orders():
    source = _read("app.js")
    assert "display_name" in source
    assert "status_display" in source
    assert "已拒绝（未执行）" in source
    assert "未执行：" in source


def test_static_site_has_intraday_daily_and_five_day_equity_period_controls():
    source = _read("app.js")
    assert 'data-period="intraday"' in source
    assert 'data-period="daily"' in source
    assert 'data-period="five-day"' in source
    assert "filterEquityCurve" in source


def test_static_site_keeps_global_pages_strategy_scoped_by_default():
    source = _read("app.js")
    assert "selectedAccountFromRoute" in source
    assert "策略账户" in source
    assert "当前策略" in source
    assert "profit_loss" in source


def test_static_site_hides_rejected_orders_and_low_value_intent_missing_events():
    source = _read("app.js")
    assert "visibleOrders" in source
    assert "visibleTimeline" in source
    assert 'status).toLowerCase() !== "rejected"' in source
    assert '!== "intent_missing"' in source


def test_position_view_supports_daily_history_and_per_symbol_profit_columns():
    source = _read("app.js")
    assert "position_history" in source
    assert "history-date" in source
    for field in ("持仓变化", "平均成本", "已实现盈亏", "浮动盈亏", "单品种总盈亏"):
        assert field in source


def test_daily_equity_uses_columns_and_five_day_equity_stitches_intraday_curves():
    source = _read("app.js")
    assert "renderDailyEquityBars" in source
    assert "renderFiveDayIntradayChart" in source
    assert "filterLastFiveTradingDays" in source
    assert "daily_equity_bars" in source
    assert 'class: "daily-bar"' in source


def test_orders_fills_activity_and_logs_have_trade_date_filters():
    source = _read("app.js")
    for identifier in ("order-date", "activity-date", "log-date"):
        assert identifier in source
    assert "filterByTradeDate" in source
    assert "wireDateFilter" in source


def test_five_day_chart_uses_concatenated_intraday_points_and_day_separators():
    source = _read("app.js")
    styles = _read("styles.css")
    assert "fiveDayCurve" in source
    assert "日内权益拼接" in source
    assert "day-separator" in source
    assert ".day-separator" in styles


def test_account_card_money_metrics_drop_decimal_places_and_schedule_is_visible():
    source = _read("app.js")
    assert "function wholeMoney" in source
    assert '["账户权益", wholeMoney(m.equity)]' in source
    assert '["可用现金", wholeMoney(m.cash)]' in source
    assert '["持仓市值", wholeMoney(m.position_market_value)]' in source
    assert "snapshot_schedule" in source
    assert "15:05" in source


def test_all_named_account_money_metrics_use_integer_yuan():
    source = _read("app.js")
    assert "account-value\">${wholeMoney" in source
    for expression in (
        '["账户权益", wholeMoney(m.equity)]',
        '["可用现金", wholeMoney(m.cash)]',
        '["持仓市值", wholeMoney(m.position_market_value)]',
    ):
        assert expression in source


def test_equity_chart_axes_use_an_adaptive_padded_domain():
    source = _read("app.js")
    assert "function paddedDomain" in source
    assert "paddedDomain(values)" in source
    assert "const floorValue = 0" not in source
    assert "const min = 0" not in source


def test_intraday_equity_only_uses_the_latest_trading_day():
    source = _read("app.js")
    assert "function filterLatestTradingDay" in source
    assert "const intradayCurve = filterLatestTradingDay(curve)" in source
    assert "renderEquityChart(chart, intradayCurve" in source


def test_dark_theme_is_default_and_light_theme_can_be_toggled():
    source = _read("app.js")
    styles = _read("styles.css")
    assert '|| "dark"' in source
    assert "paper-theme" in source
    assert "theme-toggle" in source
    assert "wireThemeToggle" in source
    assert '[data-theme="light"]' in styles


def test_strategy_summary_does_not_show_initial_cash():
    source = _read("app.js")
    assert "initial_cash)]" not in source


def test_selected_strategy_tabs_keep_a_luminous_panel_and_ui_has_motion_feedback():
    styles = _read("styles.css")
    assert '.tab[aria-selected="true"]' in styles
    assert "box-shadow" in styles
    assert ".audit-filter" in styles
    assert "@keyframes viewIn" in styles


def test_mobile_shell_uses_compact_context_bottom_navigation_and_safe_areas():
    source = _read("app.js")
    styles = _read("styles.css")
    assert "mobile-context" in source
    assert "mobile-nav" in source
    assert "mobile-nav-link" in source
    assert "aria-current" in source
    assert "env(safe-area-inset-bottom)" in styles
    assert "scroll-snap-type:x mandatory" in styles
    assert ".mobile-context" in styles


def test_mobile_content_preserves_touch_targets_charts_and_wide_table_access():
    source = _read("app.js")
    styles = _read("styles.css")
    assert "mobile-scroll-hint" in source
    assert "overflow-x:clip" in styles
    assert "min-height:44px" in styles
    assert "-webkit-overflow-scrolling:touch" in styles
    assert "font-size:clamp(18px,6vw,25px)" in styles


def test_command_center_defaults_dark_and_exposes_truthful_terminal_status():
    source = _read("app.js")
    assert 'savedTheme || "dark"' in source
    assert "command-status" in source
    assert "command-module" in source
    assert "行情快照" in source
    assert "实时行情" not in source


def test_command_center_css_defines_hud_tokens_and_reduced_motion():
    styles = _read("styles.css")
    for token in ("--hud-glow", "--hud-grid", "--hud-surface", "--hud-edge", "--hud-scan"):
        assert token in styles
    assert ".command-status" in styles
    assert ".hud-corner" in styles
    assert "prefers-reduced-motion:reduce" in styles
