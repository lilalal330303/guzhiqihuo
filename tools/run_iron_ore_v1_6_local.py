import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from quant_lab.backtest.iron_ore_cta import IronOreBacktestConfig, run_iron_ore_v16_backtest
from quant_lab.data.iron_ore import IronOreDataStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Run local daily iron ore CTA V1.6 backtest.")
    parser.add_argument("--db", default="data/market.duckdb", help="DuckDB path.")
    parser.add_argument("--start", default="2018-01-01", help="Backtest start date.")
    parser.add_argument("--end", default="2026-07-18", help="Backtest end date.")
    parser.add_argument("--initial-cash", type=float, default=1_000_000.0)
    parser.add_argument("--output-dir", default="reports/iron_ore_v1_6_local_backtest")
    args = parser.parse_args()

    store = IronOreDataStore(args.db)
    main_daily = store.load_main_daily()
    contract_daily = store.load_contract_daily()
    contracts = store.load_contracts()
    universe = store.load_universe()
    result = run_iron_ore_v16_backtest(
        main_daily,
        contract_daily,
        contracts,
        universe,
        IronOreBacktestConfig(
            start_date=args.start,
            end_date=args.end,
            initial_cash=args.initial_cash,
        ),
    )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    result.signals.to_csv(output_dir / "signals.csv", index=False)
    result.trades.to_csv(output_dir / "trades.csv", index=False)
    result.equity_curve.to_csv(output_dir / "equity_curve.csv", index=False)
    (output_dir / "metrics.json").write_text(
        json.dumps(result.metrics, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(json.dumps({
        "output_dir": str(output_dir),
        "metrics": result.metrics,
        "signal_rows": len(result.signals),
        "trade_rows": len(result.trades),
    }, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
