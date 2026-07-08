from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
REPORTS = ROOT / "reports"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(REPORTS) not in sys.path:
    sys.path.insert(0, str(REPORTS))

import run_wufu_v8_local_execution_backtest as exec_bt  # noqa: E402
from quant_lab.data.repository import DuckDBRepository  # noqa: E402
from quant_lab.strategies.wufu_etf_rotation import (  # noqa: E402
    WufuEtfRotationConfig,
    generate_a_share_weak_states_joinquant_style,
    generate_wufu_targets,
)


START_DATE = "2020-01-02"
END_DATE = "2026-07-06"
WARMUP_START_DATE = "2019-09-01"
PREFIX = REPORTS / "wufu_v8b_validation"


def main() -> None:
    repo = DuckDBRepository(ROOT / "data" / "market.duckdb")
    config = WufuEtfRotationConfig()
    symbols = list(dict.fromkeys(config.etf_pool + config.global_etf_pool + [config.defensive_etf]))
    prices = repo.load_prices_for_symbols(symbols, WARMUP_START_DATE, END_DATE)
    prices, excluded = exec_bt.exclude_symbols_with_price_jumps(prices, max_abs_daily_return=0.25)

    index_prices = repo.load_prices_for_symbols(["000300", "399101", "399006", "000510"], WARMUP_START_DATE, END_DATE)
    auto_weak = generate_a_share_weak_states_joinquant_style(
        index_prices,
        ma_lookback=config.weak_period_ma_lookback,
        max_weak_days=config.max_weak_days,
        signal_lag_days=0,
    )
    replay_targets = pd.read_csv(REPORTS / "wufu_platform_sync_v6_targets.csv", dtype={"target_symbol": str})
    replay_weak = replay_targets[["trade_date", "is_weak"]].copy()
    replay_weak["trade_date"] = pd.to_datetime(replay_weak["trade_date"])

    target_sets: dict[str, pd.DataFrame] = {
        "v6_targets": replay_targets,
        "v8_auto_weak_warmup": _target_window(generate_wufu_targets(prices, config=config, weak_states=auto_weak)),
        "v8_replay_weak_warmup": _target_window(generate_wufu_targets(prices, config=config, weak_states=replay_weak)),
    }

    results: dict[str, object] = {
        "start_date": START_DATE,
        "end_date": END_DATE,
        "warmup_start_date": WARMUP_START_DATE,
        "excluded_symbols": excluded,
        "rows": {
            "prices": int(len(prices)),
            "symbols": int(prices["symbol"].nunique()),
            "index_prices": int(len(index_prices)),
            "auto_weak": int(len(auto_weak)),
            "replay_weak": int(len(replay_weak)),
        },
        "variants": {},
        "comparisons": {},
    }

    for name, targets in target_sets.items():
        targets = _target_window(targets)
        targets.to_csv(PREFIX.with_name(f"{PREFIX.name}_{name}_targets.csv"), index=False, encoding="utf-8-sig")
        backtest = exec_bt.run_execution_backtest(prices, targets)
        backtest["equity"].to_csv(PREFIX.with_name(f"{PREFIX.name}_{name}_equity.csv"), index=False, encoding="utf-8-sig")
        backtest["trades"].to_csv(PREFIX.with_name(f"{PREFIX.name}_{name}_trades.csv"), index=False, encoding="utf-8-sig")
        results["variants"][name] = {
            "target_rows": int(len(targets)),
            "weak_days": int(targets["is_weak"].sum()) if "is_weak" in targets else None,
            "metrics": backtest["metrics"],
        }

    results["comparisons"]["auto_vs_v6"] = compare_targets(target_sets["v8_auto_weak_warmup"], target_sets["v6_targets"])
    results["comparisons"]["replay_vs_v6"] = compare_targets(target_sets["v8_replay_weak_warmup"], target_sets["v6_targets"])
    results["comparisons"]["auto_vs_replay"] = compare_targets(target_sets["v8_auto_weak_warmup"], target_sets["v8_replay_weak_warmup"])

    PREFIX.with_name(f"{PREFIX.name}_summary.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))


def _target_window(targets: pd.DataFrame) -> pd.DataFrame:
    rows = targets.copy()
    rows["trade_date"] = pd.to_datetime(rows["trade_date"])
    rows["target_symbol"] = rows["target_symbol"].astype(str).str.zfill(6)
    rows = rows[rows["trade_date"].between(pd.Timestamp(START_DATE), pd.Timestamp(END_DATE))]
    return rows.reset_index(drop=True)


def compare_targets(left: pd.DataFrame, right: pd.DataFrame) -> dict[str, object]:
    l = _target_window(left)[["trade_date", "target_symbol", "is_weak"]].rename(
        columns={"target_symbol": "left_target", "is_weak": "left_weak"}
    )
    r = _target_window(right)[["trade_date", "target_symbol", "is_weak"]].rename(
        columns={"target_symbol": "right_target", "is_weak": "right_weak"}
    )
    rows = l.merge(r, on="trade_date", how="inner")
    target_match = rows["left_target"] == rows["right_target"]
    weak_match = rows["left_weak"].astype(bool) == rows["right_weak"].astype(bool)
    mismatch = rows.loc[~target_match, "trade_date"].dt.strftime("%Y-%m-%d").head(40).tolist()
    return {
        "days": int(len(rows)),
        "target_match_days": int(target_match.sum()),
        "target_match_rate": float(target_match.mean()) if len(rows) else None,
        "weak_match_days": int(weak_match.sum()),
        "weak_match_rate": float(weak_match.mean()) if len(rows) else None,
        "target_mismatch_dates_sample": mismatch,
    }


if __name__ == "__main__":
    main()
