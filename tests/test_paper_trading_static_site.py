from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "docs" / "paper-trading"
PAGES = ("index.html", "strategy.html", "positions.html", "orders.html", "logs.html")


def _read(name: str) -> str:
    return (SITE / name).read_text(encoding="utf-8")


def test_all_pages_load_shared_static_site_resources():
    for page in PAGES:
        content = _read(page)
        assert 'href="styles.css"' in content
        assert 'src="app.js"' in content


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


def test_global_views_have_native_strategy_filters_and_visible_result_counts():
    source = _read("app.js")
    for page in ("positions", "orders", "logs"):
        assert f'page === "{page}"' in source
    assert "<select" in source
    assert "result-count" in source


def test_order_rows_expose_expandable_audit_detail_and_accessible_focus_styles():
    source = _read("app.js")
    styles = _read("styles.css")
    assert "<details" in source
    assert ":focus-visible" in styles
    assert "@media" in styles
