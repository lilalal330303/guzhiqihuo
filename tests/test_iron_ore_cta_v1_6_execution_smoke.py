from types import SimpleNamespace

import pytest

import reports.jq_iron_ore_cta_v1_6_all_cycle_short as strategy


def _snapshot(params, regime_multiplier=1.0, signal_multiplier=1.0):
    return {
        "params": params,
        "signal": -1,
        "signal_multiplier": signal_multiplier,
        "close": 500.0,
        "ma_fast": 495.0,
        "ma_slow": 490.0,
        "slow_slope": 0.002,
        "efficiency_ratio": 0.80,
        "direction_consistency": 0.80,
        "volatility_ratio": 1.10,
        "regime_multiplier": regime_multiplier,
        "trend_multiplier": 1.0,
        "atr": 10.0,
        "realized_vol": 0.20,
    }


@pytest.mark.parametrize("params", [strategy.PRE_PARAMS, strategy.POST_PARAMS])
def test_short_entry_is_available_in_both_regimes(monkeypatch, params):
    calls = []
    monkeypatch.setattr(strategy, "get_contract_price", lambda code, date: 500.0)
    monkeypatch.setattr(
        strategy,
        "order_target",
        lambda code, amount, side=None: (
            calls.append((code, amount, side))
            or SimpleNamespace(amount=amount, filled=amount)
        ),
        raising=False,
    )
    strategy.g = SimpleNamespace(
        drawdown_multiplier=1.0,
        regime_multiplier=1.0,
        trend_multiplier=1.0,
        signal_multiplier=1.0,
        risk_multiplier=1.0,
        best_close=None,
        params=params,
    )
    context = SimpleNamespace(
        previous_date="2026-07-17",
        portfolio=SimpleNamespace(
            total_value=1_000_000.0,
            available_cash=1_000_000.0,
        ),
    )

    assert strategy.open_position(
        context,
        "I2609.XDCE",
        -1,
        _snapshot(params),
    )
    assert calls and calls[0][2] == "short"
    assert strategy.g.best_close == 500.0


def test_signal_multiplier_and_regime_gate_can_reduce_or_block_entry(monkeypatch):
    calls = []
    monkeypatch.setattr(strategy, "get_contract_price", lambda code, date: 500.0)
    monkeypatch.setattr(
        strategy,
        "order_target",
        lambda code, amount, side=None: calls.append((code, amount, side)),
        raising=False,
    )
    strategy.g = SimpleNamespace(
        drawdown_multiplier=1.0,
        regime_multiplier=1.0,
        trend_multiplier=1.0,
        signal_multiplier=1.0,
        risk_multiplier=1.0,
        best_close=None,
        params=strategy.POST_PARAMS,
    )
    context = SimpleNamespace(
        previous_date="2026-07-17",
        portfolio=SimpleNamespace(
            total_value=1_000_000.0,
            available_cash=1_000_000.0,
        ),
    )
    assert strategy.open_position(
        context,
        "I2609.XDCE",
        -1,
        _snapshot(strategy.POST_PARAMS, regime_multiplier=0.0),
    ) is False
    assert calls == []
