import importlib.util
import math
from pathlib import Path
from types import SimpleNamespace


SCRIPT = Path(__file__).parents[1] / "reports" / "jq_iron_ore_cta_v1_5_post2024.py"


def load_script():
    spec = importlib.util.spec_from_file_location("iron_ore_v15_jq_logs", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_audit_line_is_stable_and_sanitizes_values():
    module = load_script()
    line = module._audit_line(
        "DAILY",
        {"z": 2, "reason": "flat|range", "bad": float("nan"), "a": 1.25},
    )
    assert line == "JQ_AUDIT|DAILY|a=1.250000|bad=|reason=flat/range|z=2"


def test_audit_emit_respects_level_and_never_requires_joinquant():
    module = load_script()

    class CaptureLog:
        def __init__(self):
            self.lines = []

        def info(self, *args, **kwargs):
            self.lines.append(args[0] if len(args) == 1 else args[0] % args[1:])

    capture = CaptureLog()
    module.log = capture
    old_enabled = module.AUDIT_LOG_ENABLED
    old_level = module.AUDIT_LOG_LEVEL
    try:
        module.AUDIT_LOG_ENABLED = True
        module.AUDIT_LOG_LEVEL = "order"
        module._audit_emit("ORDER", {"filled": 3}, level="order")
        module._audit_emit("DAILY", {"date": "2024-01-02"}, level="full")
        assert capture.lines == ["JQ_AUDIT|ORDER|filled=3"]
        module.AUDIT_LOG_LEVEL = "off"
        module._audit_emit("ORDER", {"filled": 4}, level="order")
        assert capture.lines == ["JQ_AUDIT|ORDER|filled=3"]
    finally:
        module.AUDIT_LOG_ENABLED = old_enabled
        module.AUDIT_LOG_LEVEL = old_level


def test_order_audit_fields_use_safe_attributes_and_normalize_numbers():
    module = load_script()

    class FakeOrder:
        amount = 10
        filled = 7
        price = 812.5
        avg_cost = 813.0
        commission = 1.25
        status = "partial"
        pnl = 9.5

    fields = module._order_audit_fields(FakeOrder())
    assert fields["requested"] == 10
    assert fields["filled"] == 7
    assert fields["remaining"] == 3
    assert fields["price"] == 812.5
    assert fields["avg_cost"] == 813.0
    assert fields["commission"] == 1.25
    assert fields["realized_pnl"] == 9.5
    assert fields["status"] == "partial"


def test_order_audit_fields_accept_none_order():
    module = load_script()
    fields = module._order_audit_fields(None)
    assert fields["requested"] == 0
    assert fields["filled"] == 0
    assert fields["remaining"] == 0
    assert fields["status"] == ""


def test_daily_audit_contains_regime_signal_risk_and_decision_fields():
    module = load_script()
    captured = []
    module._audit_emit = lambda event, fields, level="full": captured.append(
        (event, fields, level)
    )
    module.g = SimpleNamespace(
        params=module.POST_PARAMS.copy(),
        high_water_value=1_100_000.0,
        drawdown_multiplier=0.8,
        cooldown=1,
    )
    context = SimpleNamespace(
        portfolio=SimpleNamespace(
            total_value=1_000_000.0,
            available_cash=500_000.0,
            cash=500_000.0,
        )
    )
    snapshot = {
        "params": module.POST_PARAMS.copy(),
        "close": 820.0,
        "ma_fast": 815.0,
        "ma_slow": 810.0,
        "slow_slope": 0.004,
        "efficiency_ratio": 0.4,
        "volatility_ratio": 1.2,
        "realized_vol": 0.3,
        "atr": 18.0,
        "regime_multiplier": 0.9,
        "trend_multiplier": 1.0,
    }

    module._emit_daily_audit(
        context,
        "2024-01-02",
        snapshot,
        "I2405.XDCE",
        "",
        0,
        0,
        -1,
        -1,
        "open",
        "entry_submitted",
    )

    assert len(captured) == 1
    event, fields, level = captured[0]
    assert event == "DAILY"
    assert level == "full"
    assert fields["regime"] == "post_2024"
    assert fields["raw_signal"] == -1
    assert fields["target_direction"] == -1
    assert math.isclose(fields["risk_multiplier"], 0.72)
    assert fields["decision"] == "open"
    assert fields["reason"] == "entry_submitted"


def test_order_audit_emits_order_and_actual_position_snapshot():
    module = load_script()
    captured = []
    module._audit_emit = lambda event, fields, level="full": captured.append(
        (event, fields, level)
    )

    position = SimpleNamespace(
        long_amount=7,
        short_amount=0,
        avg_cost=812.5,
        price=813.0,
    )
    portfolio = SimpleNamespace(
        positions={"I2405.XDCE": position},
        total_value=1_010_000.0,
        available_cash=450_000.0,
        cash=450_000.0,
        margin=150_000.0,
    )
    context = SimpleNamespace(
        previous_date="2024-01-02",
        portfolio=portfolio,
    )
    order = SimpleNamespace(
        amount=10,
        filled=7,
        price=813.0,
        avg_cost=813.0,
        commission=2.5,
        status="partial",
        pnl=0.0,
    )

    module._emit_order_audit(context, order, "open", "I2405.XDCE", 1, 0)

    assert [row[0] for row in captured] == ["ORDER", "POSITION"]
    order_fields = captured[0][1]
    assert captured[0][2] == "order"
    assert order_fields["requested"] == 10
    assert order_fields["filled"] == 7
    assert order_fields["remaining"] == 3
    assert order_fields["position_before"] == 0
    assert order_fields["position_after"] == 7
    position_fields = captured[1][1]
    assert position_fields["code"] == "I2405.XDCE"
    assert position_fields["direction"] == 1
    assert position_fields["amount"] == 7
    assert position_fields["position_amount"] == 7


def test_trade_open_emits_one_daily_record_for_neutral_signal():
    module = load_script()
    captured = []
    module._audit_emit = lambda event, fields, level="full": captured.append(
        (event, fields, level)
    )
    module.g = SimpleNamespace(
        params=module.POST_PARAMS.copy(),
        tradecode="",
        pending_contract=None,
        cooldown=0,
        high_water_value=1_000_000.0,
        drawdown_multiplier=1.0,
        trend_multiplier=1.0,
        regime_multiplier=1.0,
        risk_multiplier=1.0,
    )
    context = SimpleNamespace(
        previous_date="2024-01-02",
        portfolio=SimpleNamespace(
            positions={},
            total_value=1_000_000.0,
            available_cash=1_000_000.0,
            cash=1_000_000.0,
        ),
    )
    snapshot = {
        "params": module.POST_PARAMS.copy(),
        "signal": 0,
        "close": 820.0,
        "ma_fast": 815.0,
        "ma_slow": 810.0,
        "slow_slope": 0.0,
        "efficiency_ratio": 0.1,
        "volatility_ratio": 1.0,
        "realized_vol": 0.3,
        "atr": 18.0,
        "regime_multiplier": 0.0,
        "trend_multiplier": 1.0,
    }
    module.get_signal_snapshot = lambda signal_date: snapshot
    module.get_target_contract = lambda signal_date: "I2405.XDCE"
    module.get_actual_position = lambda ctx: ("", 0, 0)

    module.trade_open(context)

    daily = [row for row in captured if row[0] == "DAILY"]
    assert len(daily) == 1
    assert daily[0][1]["decision"] == "flat"
    assert daily[0][1]["reason"] == "neutral_signal"
    assert daily[0][1]["raw_signal"] == 0


