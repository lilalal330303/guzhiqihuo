from __future__ import annotations

import argparse
from pathlib import Path

from quant_lab.research.etf_minute_kline_store import (
    MinuteStoreConfig,
    build_etf_minute_kline_store,
    write_minute_store_report,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build local ETF 1-minute K-line store.")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--symbols", default="", help="Comma separated ETF codes. Empty means select by daily liquidity.")
    parser.add_argument("--top-n", type=int, default=100)
    parser.add_argument("--sources", default="pandadata,mootdx,akshare")
    parser.add_argument("--db-path", default="data/market.duckdb")
    parser.add_argument("--output-dir", default="reports/etf_minute_store")
    parser.add_argument("--mootdx-pages", type=int, default=8)
    parser.add_argument("--mootdx-page-size", type=int, default=800)
    parser.add_argument("--batch-days", type=int, default=31)
    parser.add_argument("--no-preflight", action="store_true")
    args = parser.parse_args()

    symbols = tuple(item.strip() for item in args.symbols.split(",") if item.strip())
    sources = tuple(item.strip() for item in args.sources.split(",") if item.strip())
    config = MinuteStoreConfig(
        start_date=args.start_date,
        end_date=args.end_date,
        symbols=symbols,
        top_n=args.top_n,
        sources=sources,
        db_path=Path(args.db_path),
        mootdx_pages=args.mootdx_pages,
        mootdx_page_size=args.mootdx_page_size,
        batch_days=args.batch_days,
        preflight=not args.no_preflight,
    )
    result = build_etf_minute_kline_store(config)
    paths = write_minute_store_report(result, args.output_dir)
    coverage = result["coverage"]
    rows = int(coverage["row_count"].sum()) if not coverage.empty else 0
    print(f"symbols={len(result['symbols'])}")
    print(f"coverage_rows={rows}")
    print(f"report={paths['report']}")


if __name__ == "__main__":
    main()
