"""Export the local paper-trading operating snapshot at the 15:30 after-close checkpoint."""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from quant_lab.data.repository import DuckDBRepository
from quant_lab.research.paper_trading_site_export import export_site_snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Allow a manual export before 15:30")
    parser.add_argument("--output", type=Path, default=ROOT / "docs" / "paper-trading" / "data" / "snapshot.json")
    args = parser.parse_args()
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    if not args.force and (now.weekday() >= 5 or (now.hour, now.minute) < (15, 30)):
        print(f"跳过：当前不是交易日15:30后的盘后快照窗口（{now:%Y-%m-%d %H:%M}）")
        return 0
    output = export_site_snapshot(DuckDBRepository(ROOT / "data" / "market.duckdb"), args.output)
    print(f"盘后快照已导出：{output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
