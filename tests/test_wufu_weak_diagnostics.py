import pandas as pd

from quant_lab.research.wufu_weak_diagnostics import build_weak_state_boundary_diagnostics


def test_build_weak_state_boundary_diagnostics_outputs_index_ma_context():
    dates = pd.date_range("2024-01-01", periods=12)
    index_prices = pd.concat(
        [
            pd.DataFrame({"symbol": symbol, "trade_date": dates, "close": range(1, 13)})
            for symbol in ["000300", "399101", "399006", "000510"]
        ],
        ignore_index=True,
    )
    jq_weak = pd.DataFrame({"trade_date": [dates[-1]], "jq_weak": [True]})

    diagnostics = build_weak_state_boundary_diagnostics(
        jq_weak=jq_weak,
        index_prices=index_prices,
        ma_lookback=10,
        max_weak_days=20,
    )

    assert diagnostics["match"].tolist() == [False]
    assert diagnostics["000300_close"].tolist() == [12.0]
    assert diagnostics["000300_ma10"].tolist() == [7.5]
    assert diagnostics["000300_relation"].tolist() == ["above"]
