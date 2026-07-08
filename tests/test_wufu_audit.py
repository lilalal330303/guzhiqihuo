import pandas as pd

from quant_lab.research.wufu_audit import audit_joinquant_dynamic_pool


def test_audit_joinquant_dynamic_pool_classifies_candidate_not_top():
    jq = pd.DataFrame({"trade_date": ["2024-01-02"], "target_symbol": ["AAA"]})
    local = pd.DataFrame(
        {
            "trade_date": ["2024-01-02"],
            "target_symbol": ["BBB"],
            "candidates_json": ['[{"symbol":"AAA","rank":2,"momentum_score":1.2}]'],
        }
    )
    snapshots = pd.DataFrame(
        {
            "trade_date": ["2024-01-02"],
            "symbol": ["AAA"],
            "rank": [5],
            "industry_key": ["半导"],
            "avg_amount": [100000000.0],
        }
    )

    audit = audit_joinquant_dynamic_pool(jq, local, snapshots)

    assert not bool(audit.iloc[0]["target_match"])
    assert bool(audit.iloc[0]["jq_in_dynamic_pool"])
    assert bool(audit.iloc[0]["jq_in_candidates"])
    assert audit.iloc[0]["reason"] == "in_candidates_not_top"
