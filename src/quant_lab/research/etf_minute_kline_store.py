from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Iterable

import duckdb
import pandas as pd

from quant_lab.data.minute import (
    fetch_etf_minute_bars_akshare,
    fetch_etf_minute_bars_mootdx,
    fetch_etf_minute_bars_pandadata,
)
from quant_lab.data.repository import DuckDBRepository


DEFAULT_DB_PATH = Path("data/market.duckdb")
DEFAULT_SOURCES = ("pandadata", "mootdx", "akshare")


@dataclass(frozen=True)
class MinuteStoreConfig:
    start_date: str
    end_date: str
    symbols: tuple[str, ...] = ()
    top_n: int = 100
    sources: tuple[str, ...] = DEFAULT_SOURCES
    db_path: Path = DEFAULT_DB_PATH
    min_daily_amount: float = 0.0
    mootdx_pages: int = 8
    mootdx_page_size: int = 800
    time_zone: tuple[str, str] | None = None
    batch_days: int = 31
    preflight: bool = True


def build_etf_minute_kline_store(config: MinuteStoreConfig) -> dict[str, object]:
    """Incrementally populate local ETF 1-minute bars into DuckDB."""
    repo = DuckDBRepository(config.db_path)
    repo.initialize()

    symbols = list(config.symbols) or select_etf_symbols_from_daily(
        config.db_path,
        config.start_date,
        config.end_date,
        top_n=config.top_n,
        min_daily_amount=config.min_daily_amount,
    )
    symbols = [_with_exchange_suffix(symbol) for symbol in symbols]
    source_status = (
        check_minute_source_availability(
            config.sources,
            sample_symbol=symbols[0] if symbols else "510300.SH",
            sample_date=config.end_date,
            config=config,
        )
        if config.preflight
        else {source: {"ok": True, "rows": 0, "message": "preflight skipped"} for source in config.sources}
    )
    active_sources = tuple(source for source in config.sources if source_status.get(source, {}).get("ok"))

    existing = repo.load_minute_coverage(symbols, config.start_date, config.end_date)
    existing_ranges = {
        str(row.symbol): (
            pd.to_datetime(row.min_trade_date).strftime("%Y-%m-%d") if pd.notna(row.min_trade_date) else None,
            pd.to_datetime(row.max_trade_date).strftime("%Y-%m-%d") if pd.notna(row.max_trade_date) else None,
        )
        for row in existing.itertuples(index=False)
    }

    results: list[dict[str, object]] = []
    for symbol in symbols:
        if not active_sources:
            results.append(
                {
                    "symbol": symbol,
                    "status": "source_unavailable",
                    "source": "",
                    "start_date": config.start_date,
                    "end_date": config.end_date,
                    "rows": 0,
                    "error": _source_status_message(source_status),
                }
            )
            continue

        fetch_start = _next_fetch_start(existing_ranges.get(symbol), config.start_date)
        if fetch_start > config.end_date:
            results.append({"symbol": symbol, "status": "up_to_date", "rows": 0, "source": "", "error": ""})
            continue

        result = _fetch_one_symbol(symbol, fetch_start, config.end_date, config, active_sources=active_sources)
        if not result["bars"].empty:
            repo.upsert_minute_bars(result["bars"], source=str(result["source"]))
        results.append(
            {
                "symbol": symbol,
                "status": result["status"],
                "source": result["source"],
                "start_date": fetch_start,
                "end_date": config.end_date,
                "rows": int(len(result["bars"])),
                "error": result["error"],
            }
        )

    final_coverage = repo.load_minute_coverage(symbols, config.start_date, config.end_date)
    return {
        "config": {
            "start_date": config.start_date,
            "end_date": config.end_date,
            "top_n": config.top_n,
            "sources": list(config.sources),
            "active_sources": list(active_sources),
            "db_path": str(config.db_path),
            "batch_days": config.batch_days,
        },
        "source_status": source_status,
        "symbols": symbols,
        "results": results,
        "coverage": final_coverage,
    }


def check_minute_source_availability(
    sources: Iterable[str],
    *,
    sample_symbol: str,
    sample_date: str,
    config: MinuteStoreConfig | None = None,
) -> dict[str, dict[str, object]]:
    """Run a small non-secret source preflight before long backfills."""
    cfg = config or MinuteStoreConfig(start_date=sample_date, end_date=sample_date, symbols=(sample_symbol,))
    status: dict[str, dict[str, object]] = {}
    for source in sources:
        try:
            if source == "mootdx":
                probe = fetch_etf_minute_bars_mootdx(sample_symbol, pages=1, page_size=240)
                probe = _filter_range(probe, sample_date, sample_date)
            else:
                probe = _fetch_from_source(source, sample_symbol, sample_date, sample_date, cfg)
            status[source] = {
                "ok": not probe.empty,
                "rows": int(len(probe)),
                "message": "ok" if not probe.empty else "source returned no rows for sample date",
            }
        except Exception as exc:  # pragma: no cover - source and credential dependent
            status[source] = {"ok": False, "rows": 0, "message": f"{type(exc).__name__}: {exc}"}
    return status


def select_etf_symbols_from_daily(
    db_path: str | Path,
    start_date: str,
    end_date: str,
    *,
    top_n: int,
    min_daily_amount: float = 0.0,
) -> list[str]:
    """Select liquid ETFs from local daily bars by average amount."""
    with duckdb.connect(str(db_path)) as con:
        return (
            con.execute(
                """
                SELECT symbol
                FROM prices_daily
                WHERE trade_date BETWEEN ? AND ?
                  AND (symbol LIKE '15%' OR symbol LIKE '51%' OR symbol LIKE '56%' OR symbol LIKE '58%')
                GROUP BY symbol
                HAVING AVG(COALESCE(amount, 0)) >= ?
                ORDER BY AVG(COALESCE(amount, 0)) DESC, COUNT(*) DESC, symbol
                LIMIT ?
                """,
                [start_date, end_date, min_daily_amount, top_n],
            )
            .df()["symbol"]
            .astype(str)
            .tolist()
        )


def write_minute_store_report(result: dict[str, object], output_dir: str | Path) -> dict[str, Path]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    results = pd.DataFrame(result["results"])
    coverage = result["coverage"]
    coverage_frame = coverage if isinstance(coverage, pd.DataFrame) else pd.DataFrame()

    results_path = output_path / "etf_minute_fetch_results.csv"
    coverage_path = output_path / "etf_minute_coverage.csv"
    report_path = output_path / "etf_minute_kline_store_report.md"
    html_path = output_path / "etf_minute_kline_store_report.html"
    results.to_csv(results_path, index=False)
    coverage_frame.to_csv(coverage_path, index=False)

    ok_rows = int(results["rows"].sum()) if not results.empty and "rows" in results else 0
    ok_symbols = int((results.get("rows", pd.Series(dtype=float)) > 0).sum()) if not results.empty else 0
    failed = results[results.get("status", pd.Series(dtype=str)).isin(["failed", "source_unavailable"])] if not results.empty else results
    config = result.get("config", {})
    source_status = result.get("source_status", {})
    source_lines = "\n".join(
        f"- {source}: {'可用' if detail.get('ok') else '不可用'}，{detail.get('message', '')}"
        for source, detail in source_status.items()
    ) or "- 未执行源预检"

    report = f"""# ETF 分钟 K 线库搭建报告

## 本轮结果

- 候选标的数：{len(result["symbols"])}
- 新增分钟行数：{ok_rows}
- 本轮成功补数标的：{ok_symbols}
- 本轮失败或源不可用标的：{len(failed)}
- 请求区间：{config.get('start_date')} 至 {config.get('end_date')}
- 分批天数：{config.get('batch_days')}
- 配置数据源：{config.get('sources')}
- 可用数据源：{config.get('active_sources')}

## 数据源预检

{source_lines}

## 数据源优先级

1. Pandadata `get_stock_min`：适合作为长周期 1 分钟历史库主源，需要账号权限。
2. JQData / Tushare Pro / 米筐 / Wind / Choice / iFinD：适合授权长周期分钟数据，可作为 Pandadata 的替代主源。
3. mootdx：免 key，适合近期分钟增量和盘后验证，历史长度有限。
4. AkShare/东方财富：免 key 兜底，通常只适合近期数据，易受网络和限流影响。

## 输出文件

- `etf_minute_fetch_results.csv`
- `etf_minute_coverage.csv`
"""
    report_path.write_text(report, encoding="utf-8")
    html_path.write_text(_html_report(report), encoding="utf-8")
    return {"results": results_path, "coverage": coverage_path, "report": report_path, "html": html_path}


def _html_report(markdown_text: str) -> str:
    escaped = markdown_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    lines = []
    for line in escaped.splitlines():
        if line.startswith("# "):
            lines.append(f"<h1>{line[2:]}</h1>")
        elif line.startswith("## "):
            lines.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("- "):
            lines.append(f"<p>{line}</p>")
        elif line and line[0].isdigit() and ". " in line[:4]:
            lines.append(f"<p>{line}</p>")
        elif line.strip():
            lines.append(f"<p>{line}</p>")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>ETF 分钟 K 线库搭建报告</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif; line-height: 1.65; margin: 40px; color: #1f2937; }}
    h1 {{ font-size: 28px; }}
    h2 {{ font-size: 20px; margin-top: 28px; }}
    p {{ margin: 8px 0; }}
    code {{ background: #f3f4f6; padding: 2px 5px; border-radius: 4px; }}
  </style>
</head>
<body>
{chr(10).join(lines)}
</body>
</html>
"""


def _fetch_one_symbol(
    symbol: str,
    start_date: str,
    end_date: str,
    config: MinuteStoreConfig,
    *,
    active_sources: Iterable[str] | None = None,
) -> dict[str, object]:
    errors: list[str] = []
    for source in active_sources or config.sources:
        try:
            bars = _fetch_from_source(source, symbol, start_date, end_date, config)
            bars = _filter_range(bars, start_date, end_date)
            if not bars.empty:
                return {"status": "ok", "source": source, "bars": bars, "error": ""}
            errors.append(f"{source}: empty")
        except Exception as exc:  # pragma: no cover - network/source dependent
            errors.append(f"{source}: {type(exc).__name__}: {exc}")
    return {
        "status": "failed",
        "source": "",
        "bars": pd.DataFrame(),
        "error": " | ".join(errors),
    }


def _fetch_from_source(
    source: str,
    symbol: str,
    start_date: str,
    end_date: str,
    config: MinuteStoreConfig,
) -> pd.DataFrame:
    if source == "pandadata":
        return _fetch_pandadata_batches(symbol, start_date, end_date, config)
    if source == "mootdx":
        return fetch_etf_minute_bars_mootdx(
            symbol,
            pages=config.mootdx_pages,
            page_size=config.mootdx_page_size,
        )
    if source == "akshare":
        return fetch_etf_minute_bars_akshare(symbol, start_date, end_date)
    raise ValueError(f"unknown minute source: {source}")


def _fetch_pandadata_batches(symbol: str, start_date: str, end_date: str, config: MinuteStoreConfig) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for batch_start, batch_end in _date_batches(start_date, end_date, config.batch_days):
        chunk = fetch_etf_minute_bars_pandadata(symbol, batch_start, batch_end, time_zone=config.time_zone)
        if not chunk.empty:
            frames.append(chunk)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _date_batches(start_date: str, end_date: str, batch_days: int) -> list[tuple[str, str]]:
    if batch_days <= 0:
        return [(start_date, end_date)]
    start = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)
    batches: list[tuple[str, str]] = []
    cursor = start
    while cursor <= end:
        batch_end = min(cursor + timedelta(days=batch_days - 1), end)
        batches.append((cursor.strftime("%Y-%m-%d"), batch_end.strftime("%Y-%m-%d")))
        cursor = batch_end + timedelta(days=1)
    return batches


def _filter_range(bars: pd.DataFrame, start_date: str, end_date: str) -> pd.DataFrame:
    if bars.empty:
        return bars
    rows = bars.copy()
    rows["trade_date"] = pd.to_datetime(rows["trade_date"]).dt.strftime("%Y-%m-%d")
    return rows[(rows["trade_date"] >= start_date) & (rows["trade_date"] <= end_date)].reset_index(drop=True)


def _next_date(last_date: str | None, fallback: str) -> str:
    if not last_date:
        return fallback
    return (pd.to_datetime(last_date) + timedelta(days=1)).strftime("%Y-%m-%d")


def _next_fetch_start(existing_range: tuple[str | None, str | None] | None, start_date: str) -> str:
    if not existing_range:
        return start_date
    min_date, max_date = existing_range
    if not min_date or min_date > start_date:
        return start_date
    return _next_date(max_date, start_date)


def _with_exchange_suffix(symbol: str) -> str:
    text = str(symbol).upper()
    if "." in text:
        return text
    market = "SH" if text.startswith(("5", "6", "9")) else "SZ"
    return f"{text}.{market}"


def _source_status_message(status: dict[str, dict[str, object]]) -> str:
    return " | ".join(f"{source}: {detail.get('message', '')}" for source, detail in status.items())
