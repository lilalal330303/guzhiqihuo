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


def test_previous_close_map_handles_supermind_multiindex_batch(monkeypatch):
    import reports.ths_near_n1_q20 as strategy

    now = __import__("datetime").datetime(2025, 7, 17, 9, 31)

    def fake_datetime():
        return now

    frame = __import__("pandas").DataFrame(
        {"close": [10.0, 10.5, 20.0, 20.5]},
        index=__import__("pandas").MultiIndex.from_tuples(
            [
                ("000001.SZ", "2025-07-16"),
                ("000001.SZ", "2025-07-17"),
                ("000002.SZ", "2025-07-16"),
                ("000002.SZ", "2025-07-17"),
            ],
            names=["code", "time"],
        ),
    )

    monkeypatch.setattr(strategy, "get_datetime", fake_datetime, raising=False)
    monkeypatch.setattr(strategy, "get_price", lambda *args, **kwargs: frame, raising=False)

    assert strategy._previous_close_map(["000001.SZ", "000002.SZ"], type("C", (), {})()) == {
        "000001.SZ": 10.0,
        "000002.SZ": 20.0,
    }


def test_previous_close_map_handles_supermind_dict_get_price(monkeypatch):
    import reports.ths_near_n1_q20 as strategy

    now = __import__("datetime").datetime(2025, 7, 17, 9, 31)
    frame = {
        "000001.SZ": __import__("pandas").DataFrame(
            {"close": [10.0, 10.5]},
            index=__import__("pandas").to_datetime(["2025-07-16", "2025-07-17"]),
        ),
        "000002.SZ": __import__("pandas").DataFrame(
            {"close": [20.0, 20.5]},
            index=__import__("pandas").to_datetime(["2025-07-16", "2025-07-17"]),
        ),
    }
    calls = []

    def fake_datetime():
        return now

    def fake_get_price(*args, **kwargs):
        calls.append((args, kwargs))
        if kwargs.get("is_panel") is False or kwargs.get("is_panel") == 0:
            return frame
        raise TypeError("SuperMind requires is_panel")

    monkeypatch.setattr(strategy, "get_datetime", fake_datetime, raising=False)
    monkeypatch.setattr(strategy, "get_price", fake_get_price, raising=False)

    assert strategy._previous_close_map(["000001.SZ", "000002.SZ"], type("C", (), {})()) == {
        "000001.SZ": 10.0,
        "000002.SZ": 20.0,
    }
    assert any(call[1].get("is_panel") in (False, 0) for call in calls)


def test_before_trading_precomputes_signal(monkeypatch):
    import reports.ths_near_n1_q20 as strategy

    now = __import__("datetime").datetime(2025, 7, 17, 9, 0)
    context = type("C", (), {})()
    calls = []

    monkeypatch.setattr(strategy, "get_datetime", lambda: now, raising=False)
    monkeypatch.setattr(
        strategy,
        "select_near_n1_q20",
        lambda ctx: calls.append(ctx) or ["000001.SZ"],
    )

    strategy.before_trading(context)

    assert calls == [context]
    assert context.ths_last_signal == ["000001.SZ"]
    assert context.ths_signal_date == "2025-07-17"
