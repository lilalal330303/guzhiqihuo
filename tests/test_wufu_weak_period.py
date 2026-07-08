import pandas as pd

from quant_lab.strategies.wufu_etf_rotation import (
    WufuEtfRotationConfig,
    generate_a_share_weak_states,
    generate_a_share_weak_states_joinquant_style,
    generate_wufu_targets,
)


def test_generate_a_share_weak_states_enters_and_exits_like_joinquant_logic():
    dates = pd.date_range("2024-01-01", periods=15, freq="D")
    rows = []
    for symbol in ["000300", "399101", "399006", "000510"]:
        closes = [10, 10, 10, 10, 10, 9, 9, 9, 12, 12, 12, 12, 12, 12, 12]
        for trade_date, close in zip(dates, closes, strict=True):
            rows.append({"symbol": symbol, "trade_date": trade_date, "close": close})

    states = generate_a_share_weak_states(
        pd.DataFrame(rows),
        ma_lookback=5,
        max_weak_days=20,
    )

    assert bool(states.loc[states["trade_date"] == dates[5], "is_weak"].iloc[0]) is True
    assert bool(states.loc[states["trade_date"] == dates[8], "is_weak"].iloc[0]) is False


def test_generate_a_share_weak_states_joinquant_style_can_lag_signal_price():
    dates = pd.date_range("2024-01-01", periods=12, freq="D")
    rows = []
    for symbol in ["000300", "399101", "399006", "000510"]:
        closes = [10.0] * 10 + [5.0, 5.0]
        for trade_date, close in zip(dates, closes, strict=True):
            rows.append({"symbol": symbol, "trade_date": trade_date, "close": close})

    no_lag = generate_a_share_weak_states_joinquant_style(pd.DataFrame(rows), signal_lag_days=0)
    lagged = generate_a_share_weak_states_joinquant_style(pd.DataFrame(rows), signal_lag_days=1)

    assert bool(no_lag.loc[no_lag["trade_date"] == dates[10], "is_weak"].iloc[0]) is True
    assert bool(lagged.loc[lagged["trade_date"] == dates[10], "is_weak"].iloc[0]) is False
    assert bool(lagged.loc[lagged["trade_date"] == dates[11], "is_weak"].iloc[0]) is True


def test_generate_wufu_targets_uses_global_pool_during_weak_period():
    dates = pd.date_range("2024-01-01", periods=35, freq="D")
    prices = pd.concat(
        [
            _bars("GLB", dates, [10.0 * (1.005**i) for i in range(35)]),
            _bars("CHN", dates, [10.0 * (1.02**i) for i in range(35)]),
        ],
        ignore_index=True,
    )
    weak_states = pd.DataFrame({"trade_date": dates, "is_weak": [True] * len(dates)})

    targets = generate_wufu_targets(
        prices,
        config=WufuEtfRotationConfig(
            etf_pool=["GLB", "CHN"],
            global_etf_pool=["GLB"],
            defensive_etf=None,
            max_score_threshold=100.0,
            enable_r2_filter=True,
            enable_ma_filter=True,
            enable_volume_check=False,
            enable_loss_filter=False,
        ),
        weak_states=weak_states,
    )

    ready = targets.dropna(subset=["target_symbol"])
    assert not ready.empty
    assert set(ready["target_symbol"]) == {"GLB"}


def _bars(symbol: str, dates: pd.DatetimeIndex, closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": symbol,
            "trade_date": dates,
            "open": closes,
            "high": [value * 1.01 for value in closes],
            "low": [value * 0.99 for value in closes],
            "close": closes,
            "volume": [1000.0] * len(closes),
            "amount": [value * 1000.0 for value in closes],
        }
    )
