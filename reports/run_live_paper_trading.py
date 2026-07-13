"""Run one live-paper minute using stored bars, mootdx, then Tencent fallback."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from quant_lab.data.repository import DuckDBRepository
from quant_lab.research.live_paper_trading import advance_live_paper_trading


def _tencent_fallback(symbol: str, now: pd.Timestamp) -> pd.DataFrame:
    """Provider seam reserved for the Tencent live quote adapter."""
    return pd.DataFrame()


def main() -> int:
    parser = argparse.ArgumentParser(description="Advance ETF paper trading from live minute bars.")
    parser.add_argument("--now", help="Timestamp to process (default: current local time).")
    parser.add_argument("--once", action="store_true", help="Run a single minute and exit.")
    args = parser.parse_args()
    now = pd.Timestamp(args.now) if args.now else pd.Timestamp.now()
    results = advance_live_paper_trading(DuckDBRepository(), now, _tencent_fallback)
    print(pd.DataFrame([item.__dict__ for item in results]).to_string(index=False) if results else "no eligible trading minute")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
