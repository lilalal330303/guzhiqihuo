"""Write the current local paper-trading audit snapshot for the static site."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from quant_lab.data.repository import DuckDBRepository
from quant_lab.research.paper_trading_site_export import export_site_snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "docs" / "paper-trading" / "data" / "snapshot.json",
        help="Destination JSON file (default: docs/paper-trading/data/snapshot.json)",
    )
    args = parser.parse_args()
    output = export_site_snapshot(DuckDBRepository(ROOT / "data" / "market.duckdb"), args.output)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
