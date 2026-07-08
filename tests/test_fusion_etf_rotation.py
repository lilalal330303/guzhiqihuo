import json
from pathlib import Path

import pandas as pd
from pandas.testing import assert_series_equal

from quant_lab.strategies.wufu_etf_rotation import (
    DEFAULT_QIXING_ETF_POOL,
    FusionEtfRotationConfig,
    QixingEnhancementConfig,
    WufuEtfRotationConfig,
    generate_fusion_etf_targets,
    generate_wufu_targets,
)


def test_joinquant_fusion_export_is_single_strategy_clean():
    export_path = Path("reports/jq_fusion_etf_rotation_v1.py")
    assert export_path.exists()

    content = export_path.read_text(encoding="utf-8")
    forbidden_tokens = [
        "portfolio_value_proportion",
        "sub_account",
        "stock_strategy",
        "strategy_holdings",
        "qixing_etf_sell_trade",
        "qixing_etf_buy_trade",
        "run_weekly(strategy_1",
        "qixing_sell",
        "qixing_buy",
        "sell_qixing",
        "buy_qixing",
        "small-cap",
        "small_cap",
        "blue-chip",
        "blue_chip",
    ]
    for token in forbidden_tokens:
        assert token not in content
    for token in [
        "QIXING_ETF_POOL",
        "QIXING_ENHANCEMENT_ENABLED",
        "select_target",
        "order_target_value",
    ]:
        assert token in content


def test_default_qixing_pool_matches_task_1_plan_boundaries():
    assert DEFAULT_QIXING_ETF_POOL[0] == "518880"
    assert DEFAULT_QIXING_ETF_POOL[-1] == "511220"
    assert len(DEFAULT_QIXING_ETF_POOL) == 38
    assert "588000" not in DEFAULT_QIXING_ETF_POOL


def test_fusion_matches_wufu_when_qixing_disabled():
    dates = pd.date_range("2024-01-01", periods=35, freq="D")
    prices = pd.concat(
        [
            _bars("AAA", dates, [10.0 * (1.01**i) for i in range(35)], 1000.0),
            _bars("BBB", dates, [10.0 * (1.005**i) for i in range(35)], 1000.0),
        ],
        ignore_index=True,
    )
    wufu_config = WufuEtfRotationConfig(
        etf_pool=["AAA", "BBB"],
        lookback_days=25,
        holdings_num=1,
        max_score_threshold=20.0,
        enable_volume_check=False,
        enable_loss_filter=False,
    )

    wufu_targets = generate_wufu_targets(prices, config=wufu_config)
    fusion_targets = generate_fusion_etf_targets(
        prices,
        config=FusionEtfRotationConfig(
            wufu=wufu_config,
            qixing=QixingEnhancementConfig(enabled=False),
        ),
    )

    assert_series_equal(
        fusion_targets["target_symbol"],
        wufu_targets["target_symbol"],
        check_names=False,
    )


def test_fusion_deduplicates_wufu_and_qixing_symbols():
    dates = pd.date_range("2024-01-01", periods=35, freq="D")
    prices = pd.concat(
        [
            _bars("AAA", dates, [10.0 * (1.01**i) for i in range(35)], 1000.0),
            _bars("BBB", dates, [10.0 * (1.009**i) for i in range(35)], 1000.0),
            _bars("CCC", dates, [10.0 * (1.008**i) for i in range(35)], 1000.0),
        ],
        ignore_index=True,
    )
    config = FusionEtfRotationConfig(
        wufu=WufuEtfRotationConfig(
            etf_pool=["AAA", "BBB"],
            lookback_days=25,
            holdings_num=1,
            max_score_threshold=20.0,
            score_threshold_ratio=0.0,
            enable_volume_check=False,
            enable_loss_filter=False,
        ),
        qixing=QixingEnhancementConfig(enabled=True, pool=["BBB", "CCC", "CCC"]),
    )

    targets = generate_fusion_etf_targets(prices, config=config)

    first_ready = targets.dropna(subset=["target_symbol"]).iloc[0]
    candidates = json.loads(first_ready["candidates_json"])
    symbols = [candidate["symbol"] for candidate in candidates]
    assert symbols.count("BBB") == 1
    assert symbols.count("CCC") == 1
    for candidate in candidates:
        assert "fusion_score" in candidate
        assert "qixing_bonus" in candidate
        assert "sources" in candidate


def test_qixing_preferred_pool_bonus_promotes_close_candidate():
    dates = pd.date_range("2024-01-01", periods=35, freq="D")
    prices = pd.concat(
        [
            _bars("WUFU", dates, [10.0 * (1.01**i) for i in range(35)], 1000.0),
            _bars("QIX", dates, [10.0 * (1.0099**i) for i in range(35)], 1000.0),
        ],
        ignore_index=True,
    )
    config = FusionEtfRotationConfig(
        wufu=WufuEtfRotationConfig(
            etf_pool=["WUFU"],
            lookback_days=25,
            holdings_num=1,
            max_score_threshold=20.0,
            score_threshold_ratio=0.0,
            enable_volume_check=False,
            enable_loss_filter=False,
        ),
        qixing=QixingEnhancementConfig(
            enabled=True,
            pool=["QIX"],
            preferred_pool_bonus=0.5,
        ),
    )

    targets = generate_fusion_etf_targets(prices, config=config)

    first_ready = targets.dropna(subset=["target_symbol"]).iloc[0]
    candidates = json.loads(first_ready["candidates_json"])
    assert first_ready["target_symbol"] == "QIX"
    assert candidates[0]["symbol"] == "QIX"
    assert candidates[0]["qixing_bonus"] == 0.5
    assert candidates[0]["fusion_score"] > candidates[1]["fusion_score"]


def test_weak_market_applies_global_pool_before_qixing_enhancement():
    dates = pd.date_range("2024-01-01", periods=35, freq="D")
    prices = pd.concat(
        [
            _bars("GLOBAL", dates, [10.0 * (1.005**i) for i in range(35)], 1000.0),
            _bars("QIX_ONLY", dates, [10.0 * (1.03**i) for i in range(35)], 1000.0),
        ],
        ignore_index=True,
    )
    weak_states = pd.DataFrame({"trade_date": dates, "is_weak": [True] * len(dates)})
    config = FusionEtfRotationConfig(
        wufu=WufuEtfRotationConfig(
            etf_pool=["GLOBAL"],
            global_etf_pool=["GLOBAL"],
            lookback_days=25,
            holdings_num=1,
            max_score_threshold=2000.0,
            enable_volume_check=False,
            enable_loss_filter=False,
        ),
        qixing=QixingEnhancementConfig(
            enabled=True,
            pool=["QIX_ONLY"],
            preferred_pool_bonus=10_000.0,
        ),
    )

    targets = generate_fusion_etf_targets(prices, config=config, weak_states=weak_states)

    first_ready = targets.dropna(subset=["target_symbol"]).iloc[0]
    candidates = json.loads(first_ready["candidates_json"])
    assert first_ready["is_weak"]
    assert first_ready["target_symbol"] == "GLOBAL"
    assert [candidate["symbol"] for candidate in candidates] == ["GLOBAL"]


def test_fusion_falls_back_to_defensive_etf_when_no_candidate_passes():
    dates = pd.date_range("2024-01-01", periods=35, freq="D")
    prices = pd.concat(
        [
            _bars("RISK", dates, [10.0 * (1.01**i) for i in range(35)], 1000.0),
            _bars("DEF", dates, [10.0] * 35, 1000.0),
        ],
        ignore_index=True,
    )
    config = FusionEtfRotationConfig(
        wufu=WufuEtfRotationConfig(
            etf_pool=["RISK"],
            defensive_etf="DEF",
            lookback_days=25,
            max_score_threshold=0.0,
            enable_volume_check=False,
            enable_loss_filter=False,
        ),
        qixing=QixingEnhancementConfig(enabled=True, pool=[]),
    )

    targets = generate_fusion_etf_targets(prices, config=config)

    first_ready = targets.dropna(subset=["target_symbol"]).iloc[0]
    assert first_ready["target_symbol"] == "DEF"
    assert first_ready["rank"] == 999
    assert json.loads(first_ready["candidates_json"]) == []


def test_dual_slot_fusion_emits_wufu_and_qixing_targets_with_weights():
    dates = pd.date_range("2024-01-01", periods=35, freq="D")
    prices = pd.concat(
        [
            _bars("WUFU", dates, [10.0 * (1.010**i) for i in range(35)], 1000.0),
            _bars("QIX", dates, [10.0 * (1.009**i) for i in range(35)], 1000.0),
            _bars("DEF", dates, [10.0] * 35, 1000.0),
        ],
        ignore_index=True,
    )
    config = FusionEtfRotationConfig(
        wufu=WufuEtfRotationConfig(
            etf_pool=["WUFU"],
            defensive_etf="DEF",
            lookback_days=25,
            max_score_threshold=20.0,
            enable_volume_check=False,
            enable_loss_filter=False,
        ),
        qixing=QixingEnhancementConfig(
            enabled=True,
            pool=["QIX"],
            independent_slot_enabled=True,
            wufu_slot_weight=0.5,
            qixing_slot_weight=0.5,
        ),
    )

    targets = generate_fusion_etf_targets(prices, config=config)

    first_ready = targets[targets["wufu_target_symbol"] == "WUFU"].iloc[0]
    assert first_ready["target_symbol"] == "WUFU"
    assert first_ready["wufu_target_symbol"] == "WUFU"
    assert first_ready["qixing_target_symbol"] == "QIX"
    assert json.loads(first_ready["target_symbols_json"]) == ["WUFU", "QIX"]
    assert json.loads(first_ready["target_weights_json"]) == {"WUFU": 0.5, "QIX": 0.5}


def test_dual_slot_fusion_merges_duplicate_targets_into_one_full_weight():
    dates = pd.date_range("2024-01-01", periods=35, freq="D")
    prices = pd.concat(
        [
            _bars("BOTH", dates, [10.0 * (1.010**i) for i in range(35)], 1000.0),
            _bars("DEF", dates, [10.0] * 35, 1000.0),
        ],
        ignore_index=True,
    )
    config = FusionEtfRotationConfig(
        wufu=WufuEtfRotationConfig(
            etf_pool=["BOTH"],
            defensive_etf="DEF",
            lookback_days=25,
            max_score_threshold=20.0,
            enable_volume_check=False,
            enable_loss_filter=False,
        ),
        qixing=QixingEnhancementConfig(
            enabled=True,
            pool=["BOTH"],
            independent_slot_enabled=True,
            wufu_slot_weight=0.5,
            qixing_slot_weight=0.5,
        ),
    )

    targets = generate_fusion_etf_targets(prices, config=config)

    first_ready = targets[targets["wufu_target_symbol"] == "BOTH"].iloc[0]
    assert first_ready["wufu_target_symbol"] == "BOTH"
    assert first_ready["qixing_target_symbol"] == "BOTH"
    assert json.loads(first_ready["target_symbols_json"]) == ["BOTH"]
    assert json.loads(first_ready["target_weights_json"]) == {"BOTH": 1.0}


def test_joinquant_dual_slot_export_is_single_owner_clean():
    export_path = Path("reports/jq_fusion_etf_rotation_v2_dual_slot.py")
    assert export_path.exists()

    content = export_path.read_text(encoding="utf-8")
    forbidden_tokens = [
        "portfolio_value_proportion",
        "sub_account",
        "stock_strategy",
        "strategy_holdings",
        "qixing_etf_sell_trade",
        "qixing_etf_buy_trade",
        "run_weekly(strategy_1",
        "sell_qixing",
        "buy_qixing",
        "small-cap",
        "small_cap",
        "blue-chip",
        "blue_chip",
    ]
    for token in forbidden_tokens:
        assert token not in content
    for token in [
        "DUAL_SLOT_ENABLED",
        "WUFU_SLOT_WEIGHT",
        "QIXING_SLOT_WEIGHT",
        "select_dual_slot_targets",
        "g.target_weights",
        "WUFU_QIXING_FUSION_V2_DUAL_SLOT",
    ]:
        assert token in content
    assert "sum(weights.values())" not in content


def _bars(symbol: str, dates: pd.DatetimeIndex, closes: list[float], volume: float) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": symbol,
            "trade_date": dates,
            "open": closes,
            "high": [value * 1.01 for value in closes],
            "low": [value * 0.99 for value in closes],
            "close": closes,
            "volume": [volume] * len(closes),
            "amount": [value * volume for value in closes],
        }
    )
