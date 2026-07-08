from __future__ import annotations

import pandas as pd

from quant_lab.strategies.wufu_etf_rotation import generate_a_share_weak_states


def build_weak_state_boundary_diagnostics(
    jq_weak: pd.DataFrame,
    index_prices: pd.DataFrame,
    ma_lookback: int = 10,
    max_weak_days: int = 20,
    index_symbols: tuple[str, ...] = ("000300", "399101", "399006", "000510"),
) -> pd.DataFrame:
    required_jq = {"trade_date", "jq_weak"}
    missing_jq = required_jq.difference(jq_weak.columns)
    if missing_jq:
        raise ValueError(f"jq_weak missing required columns: {sorted(missing_jq)}")
    required_prices = {"symbol", "trade_date", "close"}
    missing_prices = required_prices.difference(index_prices.columns)
    if missing_prices:
        raise ValueError(f"index_prices missing required columns: {sorted(missing_prices)}")

    local = generate_a_share_weak_states(
        index_prices,
        ma_lookback=ma_lookback,
        max_weak_days=max_weak_days,
        index_symbols=index_symbols,
    )
    jq = jq_weak.copy()
    jq["trade_date"] = pd.to_datetime(jq["trade_date"])
    jq["jq_weak"] = jq["jq_weak"].astype(bool)
    merged = jq.merge(local, on="trade_date", how="left").rename(columns={"is_weak": "local_weak"})
    merged["local_weak"] = merged["local_weak"].fillna(False).astype(bool)
    merged["match"] = merged["jq_weak"] == merged["local_weak"]

    context = _index_ma_context(index_prices, merged["trade_date"].tolist(), ma_lookback, index_symbols)
    return merged.merge(context, on="trade_date", how="left")


def _index_ma_context(
    index_prices: pd.DataFrame,
    trade_dates: list[pd.Timestamp],
    ma_lookback: int,
    index_symbols: tuple[str, ...],
) -> pd.DataFrame:
    rows = index_prices.copy()
    rows["trade_date"] = pd.to_datetime(rows["trade_date"])
    rows = rows.sort_values(["symbol", "trade_date"])
    output: list[dict[str, object]] = []
    for trade_date in trade_dates:
        item: dict[str, object] = {"trade_date": trade_date}
        for symbol in index_symbols:
            history = rows[(rows["symbol"] == symbol) & (rows["trade_date"] <= trade_date)]
            if history.empty:
                item[f"{symbol}_close"] = None
                item[f"{symbol}_ma{ma_lookback}"] = None
                item[f"{symbol}_relation"] = "missing"
                continue
            close = float(history.iloc[-1]["close"])
            ma_value = None
            relation = "insufficient"
            if len(history) >= ma_lookback:
                ma_value = float(history["close"].astype(float).iloc[-ma_lookback:].mean())
                if close > ma_value:
                    relation = "above"
                elif close < ma_value:
                    relation = "below"
                else:
                    relation = "equal"
            item[f"{symbol}_close"] = close
            item[f"{symbol}_ma{ma_lookback}"] = ma_value
            item[f"{symbol}_relation"] = relation
        output.append(item)
    return pd.DataFrame(output)
