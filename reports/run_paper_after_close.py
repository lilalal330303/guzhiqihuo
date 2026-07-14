"""Export the local paper-trading operating snapshot at the 15:05 after-close checkpoint."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from quant_lab.data.repository import DuckDBRepository
from quant_lab.research.paper_after_close import already_completed, complete_paper_trade_day
from quant_lab.research.paper_trading_site_export import export_site_snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Allow a manual export before 15:05")
    parser.add_argument("--trade-date", help="Trade date to complete (default: current Shanghai date)")
    parser.add_argument("--output", type=Path, default=ROOT / "docs" / "paper-trading" / "data" / "snapshot.json")
    args = parser.parse_args()
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    if not args.force and (now.weekday() >= 5 or (now.hour, now.minute) < (15, 5)):
        print(f"跳过：当前不是交易日15:05后的盘后快照窗口（{now:%Y-%m-%d %H:%M}）")
        return 0
    trade_date = args.trade_date or now.strftime("%Y-%m-%d")
    status_path = ROOT / "reports" / "paper_after_close_status.json"
    try:
        prior = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {}
    except (OSError, ValueError):
        prior = {}
    if not args.force and already_completed(prior, trade_date):
        print(f"盘后模拟盘已完成，跳过重复运行：{trade_date}")
        return 0
    try:
        repo = DuckDBRepository(ROOT / "data" / "market.duckdb")
        result = complete_paper_trade_day(repo, trade_date)
        output = export_site_snapshot(repo, args.output)
        status = {"status": "completed", **result, "completed_at": now.isoformat(), "snapshot": str(output)}
        status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"盘后模拟盘已完成：{result}；快照：{output}")
        return 0
    except Exception as exc:
        status_path.write_text(json.dumps({
            "status": "failed", "trade_date": trade_date, "failed_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
            "error": str(exc),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"盘后模拟盘失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
