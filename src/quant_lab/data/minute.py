from __future__ import annotations

from collections.abc import Iterable
import os
from pathlib import Path
import shlex

import pandas as pd


DEFAULT_TDX_SERVERS: tuple[tuple[str, int], ...] = (
    ("218.75.126.9", 7709),
    ("180.153.18.170", 7709),
    ("119.147.212.81", 7709),
)


def fetch_etf_minute_bars_mootdx(
    symbol: str,
    *,
    pages: int = 1,
    page_size: int = 240,
    servers: Iterable[tuple[str, int]] = DEFAULT_TDX_SERVERS,
    timeout: int = 5,
) -> pd.DataFrame:
    """Fetch recent ETF 1-minute bars from mootdx and normalize columns.

    mootdx returns recent paged minute bars. In current tests it exposes real
    `vol` and `amount`, but the free server history is limited and should not
    be treated as full-cycle 2020+ coverage.
    """
    if pages <= 0:
        raise ValueError("pages must be positive")
    if page_size <= 0:
        raise ValueError("page_size must be positive")

    raw_symbol = _strip_exchange_suffix(symbol)
    output_symbol = _with_exchange_suffix(symbol)
    last_error: Exception | None = None

    for host, port in servers:
        try:
            raw = _fetch_mootdx_pages(raw_symbol, pages, page_size, host, port, timeout)
            bars = _normalize_mootdx_minute_bars(raw, output_symbol)
            if not bars.empty:
                return bars
        except Exception as exc:  # pragma: no cover - exercised in integration tests
            last_error = exc

    if last_error is not None:
        raise RuntimeError(f"mootdx minute fetch failed for {symbol}") from last_error
    raise ValueError(f"mootdx returned no minute rows for {symbol}")


def fetch_etf_minute_bars_pandadata(
    symbol: str,
    start_date: str,
    end_date: str,
    *,
    time_zone: tuple[str, str] | None = None,
    env_file: str | Path | None = None,
) -> pd.DataFrame:
    """Fetch ETF 1-minute bars from Pandadata and normalize columns.

    Pandadata requires `panda_data.init_token()` before API calls. Credentials
    are read from environment variables or `~/.pandadata/pandadata.env`:
    `DEFAULT_USERNAME`, `DEFAULT_PASSWORD`, and `JAVA_SERVICE_BASE_URL`.
    """
    panda_data = _init_pandadata(env_file)
    fields = ["symbol", "date", "minute", "datetime", "open", "high", "low", "close", "amount", "volume"]
    kwargs = {
        "symbol": _with_exchange_suffix(symbol),
        "start_date": start_date.replace("-", ""),
        "end_date": end_date.replace("-", ""),
        "fields": fields,
        "frequency": "1m",
    }
    if time_zone is not None:
        kwargs["time_zone"] = time_zone

    raw = panda_data.get_stock_min(**kwargs)
    return _normalize_pandadata_minute_bars(raw, _with_exchange_suffix(symbol))


def fetch_etf_minute_bars_akshare(
    symbol: str,
    start_date: str,
    end_date: str,
    *,
    period: str = "1",
    adjust: str = "",
) -> pd.DataFrame:
    """Fetch recent ETF minute bars from AkShare/Eastmoney and normalize columns.

    Eastmoney's public minute endpoint is useful as a no-key fallback, but it is
    short-horizon and can be blocked by network/proxy policy. Treat this source
    as incremental validation data, not a licensed full-history archive.
    """
    try:
        import akshare as ak  # noqa: PLC0415
    except ModuleNotFoundError as exc:
        raise RuntimeError("akshare is not installed. Install akshare first.") from exc

    raw = ak.fund_etf_hist_min_em(
        symbol=_strip_exchange_suffix(symbol),
        start_date=_to_akshare_datetime(start_date, "09:30:00"),
        end_date=_to_akshare_datetime(end_date, "15:00:00"),
        period=period,
        adjust=adjust,
    )
    return _normalize_akshare_minute_bars(raw, _with_exchange_suffix(symbol))


def _init_pandadata(env_file: str | Path | None = None):
    try:
        import panda_data  # noqa: PLC0415
    except ModuleNotFoundError as exc:
        raise RuntimeError("panda_data is not installed. Install pandadata runtime first.") from exc

    _load_pandadata_env(Path(env_file) if env_file else Path.home() / ".pandadata" / "pandadata.env")
    username = os.getenv("DEFAULT_USERNAME", "")
    password = os.getenv("DEFAULT_PASSWORD", "")
    base_url = os.getenv("JAVA_SERVICE_BASE_URL", "http://pandadata.pandaaiquant.com")
    if not username or not password:
        raise RuntimeError(
            "Pandadata credentials are missing. Set DEFAULT_USERNAME and DEFAULT_PASSWORD, "
            "or create ~/.pandadata/pandadata.env."
        )

    panda_data.init_token(username=username, password=password, base_url=base_url)
    return panda_data


def _load_pandadata_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_env_assignment(line)
        if parsed is None:
            continue
        key, value = parsed
        os.environ.setdefault(key, value)


def _parse_env_assignment(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    try:
        parts = shlex.split(stripped, posix=True)
    except ValueError:
        return None
    if not parts:
        return None
    if parts[0] == "export":
        parts = parts[1:]
    if not parts or "=" not in parts[0]:
        return None
    key, value = parts[0].split("=", 1)
    return (key, value) if key else None


def _fetch_mootdx_pages(
    symbol: str,
    pages: int,
    page_size: int,
    host: str,
    port: int,
    timeout: int,
) -> pd.DataFrame:
    from mootdx.quotes import Quotes

    client = Quotes.factory(
        market="std",
        server=(host, port),
        timeout=timeout,
        heartbeat=False,
        auto_retry=False,
        raise_exception=True,
    )
    frames: list[pd.DataFrame] = []
    try:
        for page in range(pages):
            chunk = client.bars(symbol=symbol, frequency=8, start=page * page_size, offset=page_size)
            if chunk is None or chunk.empty:
                break
            frames.append(chunk)
    finally:
        close = getattr(client, "close", None)
        if close is not None:
            close()

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _normalize_mootdx_minute_bars(raw: pd.DataFrame, symbol: str) -> pd.DataFrame:
    required = {"datetime", "open", "high", "low", "close", "amount"}
    missing = required.difference(raw.columns)
    if missing:
        raise ValueError(f"mootdx minute response missing columns: {sorted(missing)}")

    volume_col = "volume" if "volume" in raw.columns else "vol"
    if volume_col not in raw.columns:
        raise ValueError("mootdx minute response missing volume/vol column")

    bars = raw.copy()
    dt = pd.to_datetime(bars["datetime"])
    normalized = pd.DataFrame(
        {
            "symbol": symbol,
            "trade_date": dt.dt.strftime("%Y-%m-%d"),
            "minute": dt.dt.strftime("%H%M").astype(int),
            "datetime": dt.dt.strftime("%Y-%m-%d %H:%M:%S"),
            "open": pd.to_numeric(bars["open"], errors="coerce"),
            "high": pd.to_numeric(bars["high"], errors="coerce"),
            "low": pd.to_numeric(bars["low"], errors="coerce"),
            "close": pd.to_numeric(bars["close"], errors="coerce"),
            "volume": pd.to_numeric(bars[volume_col], errors="coerce"),
            "amount": pd.to_numeric(bars["amount"], errors="coerce"),
        }
    )
    return (
        normalized.dropna(subset=["open", "high", "low", "close", "volume", "amount"])
        .drop_duplicates(subset=["symbol", "datetime"])
        .sort_values(["symbol", "datetime"])
        .reset_index(drop=True)
    )


def _normalize_pandadata_minute_bars(raw: pd.DataFrame, symbol: str) -> pd.DataFrame:
    required = {"datetime", "amount", "volume"}
    missing = required.difference(raw.columns)
    if missing:
        raise ValueError(f"Pandadata minute response missing columns: {sorted(missing)}")

    bars = raw.copy()
    if "symbol" not in bars.columns:
        bars["symbol"] = symbol
    if "date" not in bars.columns:
        bars["date"] = pd.to_datetime(bars["datetime"]).dt.strftime("%Y%m%d")
    if "minute" not in bars.columns:
        bars["minute"] = pd.to_datetime(bars["datetime"]).dt.strftime("%H%M").astype(int)
    else:
        bars["minute"] = bars["minute"].map(_to_hhmm)

    dt = pd.to_datetime(bars["datetime"])
    normalized = pd.DataFrame(
        {
            "symbol": bars["symbol"].astype(str).str.upper(),
            "trade_date": pd.to_datetime(bars["date"].astype(str)).dt.strftime("%Y-%m-%d"),
            "minute": pd.to_numeric(bars["minute"], errors="coerce").astype("Int64"),
            "datetime": dt.dt.strftime("%Y-%m-%d %H:%M:%S"),
            "open": _numeric_or_nan(bars, "open"),
            "high": _numeric_or_nan(bars, "high"),
            "low": _numeric_or_nan(bars, "low"),
            "close": _numeric_or_nan(bars, "close"),
            "volume": pd.to_numeric(bars["volume"], errors="coerce"),
            "amount": pd.to_numeric(bars["amount"], errors="coerce"),
        }
    )
    price_cols = ["open", "high", "low", "close"]
    for col in price_cols:
        normalized[col] = normalized[col].fillna(0.0)
    return (
        normalized.dropna(subset=["minute", "volume", "amount"])
        .assign(minute=lambda frame: frame["minute"].astype(int))
        .drop_duplicates(subset=["symbol", "datetime"])
        .sort_values(["symbol", "datetime"])
        .reset_index(drop=True)
    )


def _normalize_akshare_minute_bars(raw: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame(
            columns=["symbol", "trade_date", "minute", "datetime", "open", "high", "low", "close", "volume", "amount"]
        )

    column_map = {
        "时间": "datetime",
        "开盘": "open",
        "最高": "high",
        "最低": "low",
        "收盘": "close",
        "成交量": "volume",
        "成交额": "amount",
    }
    bars = raw.rename(columns=column_map).copy()
    required = {"datetime", "open", "high", "low", "close", "volume", "amount"}
    missing = required.difference(bars.columns)
    if missing:
        raise ValueError(f"AkShare ETF minute response missing columns: {sorted(missing)}")

    dt = pd.to_datetime(bars["datetime"])
    normalized = pd.DataFrame(
        {
            "symbol": symbol,
            "trade_date": dt.dt.strftime("%Y-%m-%d"),
            "minute": dt.dt.strftime("%H%M").astype(int),
            "datetime": dt.dt.strftime("%Y-%m-%d %H:%M:%S"),
            "open": pd.to_numeric(bars["open"], errors="coerce"),
            "high": pd.to_numeric(bars["high"], errors="coerce"),
            "low": pd.to_numeric(bars["low"], errors="coerce"),
            "close": pd.to_numeric(bars["close"], errors="coerce"),
            "volume": pd.to_numeric(bars["volume"], errors="coerce"),
            "amount": pd.to_numeric(bars["amount"], errors="coerce"),
        }
    )
    return (
        normalized.dropna(subset=["open", "high", "low", "close", "volume", "amount"])
        .drop_duplicates(subset=["symbol", "datetime"])
        .sort_values(["symbol", "datetime"])
        .reset_index(drop=True)
    )


def _numeric_or_nan(frame: pd.DataFrame, column: str) -> pd.Series:
    if column in frame.columns:
        return pd.to_numeric(frame[column], errors="coerce")
    return pd.Series([float("nan")] * len(frame), index=frame.index)


def _to_hhmm(value: object) -> int | None:
    if pd.isna(value):
        return None
    text = str(value).strip().replace(":", "")
    if "." in text:
        text = text.split(".", 1)[0]
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 6:
        return int(digits[:4])
    if len(digits) >= 4:
        return int(digits[:4])
    return None


def _strip_exchange_suffix(symbol: str) -> str:
    return symbol.split(".")[0]


def _with_exchange_suffix(symbol: str) -> str:
    if "." in symbol:
        return symbol.upper()
    market = "SH" if symbol.startswith(("5", "6", "9")) else "SZ"
    return f"{symbol}.{market}"


def _to_akshare_datetime(date_text: str, fallback_time: str) -> str:
    text = str(date_text).strip()
    if " " in text:
        return text
    return f"{pd.to_datetime(text).strftime('%Y-%m-%d')} {fallback_time}"
