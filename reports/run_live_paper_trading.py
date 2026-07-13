"""Run one live-paper minute using stored bars, mootdx, then Tencent fallback."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from quant_lab.data.repository import DuckDBRepository
from quant_lab.research.live_paper_trading import advance_live_paper_trading


def _tencent_fallback(symbol: str, now: pd.Timestamp) -> pd.DataFrame:
    """Fetch and normalize Tencent's current ETF minute bar for ``now``.

    The execution runner accepts a bar only when its timestamp exactly matches
    the requested minute, so a delayed quote cannot accidentally be used for a
    later simulated fill.  Provider/network failures are intentionally a safe
    empty frame: the runner records ``data_missing`` and does not trade.
    """
    clean = str(symbol).split(".")[0]
    prefix = "sh" if clean.startswith(("5", "6", "9")) else "sz"
    code = f"{prefix}{clean}"
    columns = ["symbol", "trade_date", "minute", "datetime", "open", "high", "low", "close", "volume", "amount"]
    try:
        response = requests.get(
            "https://web.ifzq.gtimg.cn/appstock/app/minute/query",
            params={"code": code},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        rows = ((payload.get("data") or {}).get(code) or {}).get("data") or {}
        rows = rows.get("data") or rows.get("minute") or []
    except (OSError, ValueError, requests.RequestException, AttributeError):
        return pd.DataFrame(columns=columns)

    requested = pd.Timestamp(now).floor("min")
    normalized: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        try:
            timestamp = pd.to_datetime(str(row[0]), format="%Y%m%d%H%M")
            if timestamp != requested:
                continue
            close = float(row[2])
            normalized.append({
                "symbol": symbol,
                "trade_date": timestamp.normalize(),
                "minute": int(timestamp.strftime("%H%M")),
                "datetime": timestamp,
                "open": float(row[1]),
                "high": float(row[3]),
                "low": float(row[4]),
                "close": close,
                "volume": float(row[5]),
                "amount": float(row[6]) if len(row) > 6 else 0.0,
            })
        except (TypeError, ValueError):
            continue
    return pd.DataFrame(normalized, columns=columns)


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
