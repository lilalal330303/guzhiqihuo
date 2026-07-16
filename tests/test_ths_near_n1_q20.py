from pathlib import Path


SCRIPT = Path("reports/ths_near_n1_q20.py")


def test_ths_script_has_native_entrypoints_and_no_joinquant_imports():
    source = SCRIPT.read_text(encoding="utf-8")
    for marker in (
        "def init(context):",
        "def handle_bar(context, bar_dict):",
        "def before_trading(context):",
        "def after_trading(context):",
    ):
        assert marker in source
    assert "from jqdata import" not in source
    assert "from jqfactor import" not in source


def test_ths_script_has_near_n1_q20_and_audit_markers():
    source = SCRIPT.read_text(encoding="utf-8")
    for marker in (
        "near_n1_q20",
        "NEAR_SIGNAL",
        "THS_ORDER",
        "QUALITY_FALLBACK",
        "closeable_amount",
    ):
        assert marker in source


def test_near_n1_q20_prefers_quality_inside_n_plus_one():
    from reports.ths_near_n1_q20 import select_from_ranked

    ranked = ["A.SH", "B.SH", "C.SH", "D.SH", "E.SH", "F.SH"]
    quality = {code: 0.1 for code in ranked}
    quality["F.SH"] = 1.0
    assert select_from_ranked(ranked, quality, 5) == ranked[:5]


def test_quality_fallback_is_neutral():
    from reports.ths_near_n1_q20 import quality_rank_score

    assert quality_rank_score({}) == 0.5


def test_sell_amount_is_capped_by_closeable_amount():
    from reports.ths_near_n1_q20 import sellable_amount

    position = type("P", (), {"total_amount": 1000, "closeable_amount": 300})()
    assert sellable_amount(position) == 300


def test_order_value_uses_round_lot():
    from reports.ths_near_n1_q20 import round_lot_value

    assert round_lot_value(10.01, 10000, 100) == 9009.0
