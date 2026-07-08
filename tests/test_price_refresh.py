import pandas as pd

from quant_lab.data.price_refresh import build_incremental_price_fetch_plan


def test_incremental_price_fetch_plan_skips_complete_symbol():
    coverage = pd.DataFrame(
        {
            "symbol": ["AAA"],
            "min_trade_date": ["2024-01-01"],
            "max_trade_date": ["2024-01-05"],
            "row_count": [5],
        }
    )

    plan = build_incremental_price_fetch_plan(["AAA"], coverage, "2024-01-01", "2024-01-05")

    assert plan.empty


def test_incremental_price_fetch_plan_adds_missing_suffix_only():
    coverage = pd.DataFrame(
        {
            "symbol": ["AAA"],
            "min_trade_date": ["2024-01-01"],
            "max_trade_date": ["2024-01-03"],
            "row_count": [3],
        }
    )

    plan = build_incremental_price_fetch_plan(["AAA"], coverage, "2024-01-01", "2024-01-05")

    assert plan[["symbol", "start_date", "end_date", "reason"]].astype(str).to_dict("records") == [
        {
            "symbol": "AAA",
            "start_date": "2024-01-04",
            "end_date": "2024-01-05",
            "reason": "missing_suffix",
        }
    ]


def test_incremental_price_fetch_plan_does_not_fetch_before_first_active_date():
    coverage = pd.DataFrame(
        {
            "symbol": ["AAA"],
            "min_trade_date": ["2024-03-01"],
            "max_trade_date": ["2024-03-05"],
            "row_count": [3],
        }
    )
    first_active = pd.DataFrame({"symbol": ["AAA"], "first_active_date": ["2024-03-01"]})

    plan = build_incremental_price_fetch_plan(
        ["AAA"],
        coverage,
        "2024-01-01",
        "2024-03-05",
        first_active_dates=first_active,
    )

    assert plan.empty


def test_incremental_price_fetch_plan_counts_expected_rows_from_first_active_date():
    coverage = pd.DataFrame(
        {
            "symbol": ["AAA"],
            "min_trade_date": ["2024-03-01"],
            "max_trade_date": ["2024-03-03"],
            "row_count": [3],
        }
    )
    first_active = pd.DataFrame({"symbol": ["AAA"], "first_active_date": ["2024-03-01"]})
    calendar = pd.date_range("2024-01-01", "2024-03-03", freq="D")

    plan = build_incremental_price_fetch_plan(
        ["AAA"],
        coverage,
        "2024-01-01",
        "2024-03-03",
        calendar_dates=calendar,
        first_active_dates=first_active,
    )

    assert plan.empty
