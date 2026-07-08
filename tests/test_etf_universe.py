import pandas as pd

from quant_lab.data.etf_universe import build_etf_universe_snapshots


def test_build_etf_universe_snapshots_marks_active_from_price_coverage():
    metadata = pd.DataFrame(
        {
            "symbol": ["510300", "159915", "588000"],
            "name": ["沪深300ETF", "创业板ETF", "科创ETF"],
        }
    )
    prices = pd.DataFrame(
        {
            "symbol": ["510300", "510300", "159915"],
            "trade_date": pd.to_datetime(["2024-01-02", "2024-01-04", "2024-01-03"]),
        }
    )
    trade_dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])

    snapshots = build_etf_universe_snapshots(metadata, trade_dates, prices)

    active = snapshots[snapshots["is_active"]].groupby("trade_date")["symbol"].apply(list).to_dict()
    assert active[pd.Timestamp("2024-01-02")] == ["510300"]
    assert active[pd.Timestamp("2024-01-03")] == ["510300", "159915"]
    assert active[pd.Timestamp("2024-01-04")] == ["510300"]
