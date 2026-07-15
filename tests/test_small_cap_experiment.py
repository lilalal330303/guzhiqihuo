import pandas as pd

from quant_lab.research.small_cap_experiment import (
    SmallCapExperimentConfig,
    build_joinquant_v3_targets,
    run_small_cap_experiment,
)
from quant_lab.strategies.small_cap import SmallCapParams


def test_defaults_match_approved_research_scope():
    config = SmallCapExperimentConfig()
    assert config.start_date == "2020-01-01"
    assert config.initial_cash == 1_000_000.0
    assert config.benchmark == "159919"
    assert config.strict is True


def test_experiment_reports_required_and_extended_metrics():
    bars = pd.DataFrame({
        "symbol": ["000001"] * 3,
        "trade_date": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]),
        "open": [10.0, 10.0, 11.0], "close": [10.0, 11.0, 12.0],
        "high_limit": [11.0, 11.0, 12.1], "low_limit": [9.0, 9.0, 9.9],
        "paused": [False, False, False],
    })
    targets = pd.DataFrame({"signal_date": pd.to_datetime(["2024-01-02"]),
                            "symbol": ["000001"], "target_weight": [1.0]})
    result = run_small_cap_experiment(bars, targets, SmallCapExperimentConfig(initial_cash=10_000.0))
    required = {"total_return", "annualized_return", "max_drawdown", "trade_count", "win_rate",
                "volatility", "sharpe", "turnover"}
    assert required <= set(result.metrics)
    assert result.config.initial_cash == 10_000.0


def _make_strict_inputs(symbols: list[str]) -> dict[str, pd.DataFrame]:
    signal_date = pd.Timestamp("2024-01-09")
    query_date = pd.Timestamp("2024-01-08")
    count = len(symbols)
    snapshots = pd.DataFrame({
        "signal_date": [signal_date] * count, "query_date": [query_date] * count,
        "symbol": symbols, "market_cap_100m": range(11, 11 + count),
        "operating_revenue": [2e8] * count, "net_profit": [3e6] * count,
        "roe_pct": [1.0] * count, "roa_pct": [1.0] * count,
        "close": [10.0] * count, "paused": [False] * count, "is_st": [False] * count,
        "name": ["测试"] * count, "board": ["main"] * count,
        "listing_days": [500] * count,
    })
    inputs = {
        "snapshots": snapshots,
        "audit_opinions": pd.DataFrame(), "profit_forecasts": pd.DataFrame(),
        "income_publications": pd.DataFrame(), "share_pledges": pd.DataFrame(),
        "dividend_events": pd.DataFrame(),
        "index_prices": pd.DataFrame({
            "trade_date": pd.date_range("2023-12-25", periods=11, freq="B"),
            "close": [1000.0] * 11,
        }),
        "crowding": pd.DataFrame({
            "trade_date": [query_date], "concentration": [0.44], "observed_symbols": [5000]
        }),
    }
    return inputs


def test_strict_target_builder_uses_query_date_crowding_and_dynamic_stock_count():
    query_date = pd.Timestamp("2024-01-08")
    inputs = _make_strict_inputs(["A", "B", "C"])

    targets, diagnostics, _ = build_joinquant_v3_targets(
        inputs, SmallCapParams(stock_num=5), enable_dynamic_stock_num=True
    )

    assert targets["symbol"].tolist() == ["A", "B", "C"]
    assert targets["target_weight"].sum() == 0.5
    assert diagnostics.loc[0, "crowding_query_date"] == query_date
