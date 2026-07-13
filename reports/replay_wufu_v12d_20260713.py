"""Replay V12D on 2026-07-13 after the stop/rebalance orchestration fix."""
from pathlib import Path
import shutil

from quant_lab.data.repository import DuckDBRepository
from quant_lab.research.paper_trading import run_paper_range


DATABASE = Path("data/market.duckdb")
BACKUP = Path("data/market.duckdb.before_v12d_20260713_rebalance_fix_20260714_0028.bak")


def main() -> int:
    if not BACKUP.exists():
        shutil.copy2(DATABASE, BACKUP)
    repo = DuckDBRepository(DATABASE)
    print(repo.rewind_paper_account("wufu_v12d", "wufu_v12d", "2026-07-13 13:10"))
    results = run_paper_range(
        repo, "2026-07-13 13:10", "2026-07-13 14:56", account_ids=["wufu_v12d"],
    )
    failed = [result for result in results if result.status == "failed"]
    if failed:
        raise RuntimeError(f"replay failed: {failed}")
    print(f"replayed {len(results)} audited minutes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
