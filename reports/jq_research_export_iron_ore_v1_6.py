"""JoinQuant Research exporter for the local iron ore CTA V1.6 dataset.

Run this file in JoinQuant's research environment, not in the strategy editor.
The default export is daily data with a strict point-in-time futures universe.
After the files are downloaded from the research workspace, run the local
import CLI:

    python tools/import_iron_ore_v1_6.py --input-dir iron_ore_v1_6_export
"""

import json
import os
import re

import pandas as pd


SIGNAL_SECURITY = "I8888.XDCE"
IRON_ORE_CODE_RE = re.compile(r"^I\d{4}\.XDCE$", re.IGNORECASE)
REQUIRED_PRICE_FIELDS = ["open", "high", "low", "close"]
QUERY_OPTIONAL_FIELDS = ["volume", "money", "open_interest"]
OUTPUT_OPTIONAL_FIELDS = ["volume", "amount", "open_interest"]
EXPORT_FILES = {
    "main_daily": "iron_ore_main_daily.csv",
    "contract_daily": "iron_ore_contract_daily.csv",
    "contracts": "iron_ore_contracts.csv",
    "universe_daily": "iron_ore_universe_daily.csv",
}


def _format_date(value):
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _normalize_price_frame(raw, symbol):
    if raw is None or raw.empty:
        return pd.DataFrame(
            columns=["symbol", "trade_date"] + REQUIRED_PRICE_FIELDS + OUTPUT_OPTIONAL_FIELDS
        )
    frame = raw.copy()
    if "time" in frame.columns:
        date_column = "time"
    elif "date" in frame.columns:
        date_column = "date"
    else:
        frame = frame.reset_index()
        date_column = next(
            column
            for column in frame.columns
            if str(column).lower() in {"index", "time", "date"}
        )
    frame = frame.rename(columns={date_column: "trade_date"})
    frame["symbol"] = str(symbol).upper()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce")
    for column in REQUIRED_PRICE_FIELDS + QUERY_OPTIONAL_FIELDS:
        if column not in frame.columns:
            frame[column] = 0.0
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if "amount" not in frame.columns:
        frame["amount"] = frame["money"]
    frame = frame[["symbol", "trade_date"] + REQUIRED_PRICE_FIELDS + OUTPUT_OPTIONAL_FIELDS]
    frame = frame.dropna(subset=REQUIRED_PRICE_FIELDS)
    frame = frame.loc[(frame[REQUIRED_PRICE_FIELDS] > 0).all(axis=1)]
    return frame.sort_values("trade_date").drop_duplicates(["symbol", "trade_date"])


def _get_daily_price(symbol, start_date, end_date):
    fields = REQUIRED_PRICE_FIELDS + QUERY_OPTIONAL_FIELDS
    try:
        raw = get_price(
            symbol,
            start_date=_format_date(start_date),
            end_date=_format_date(end_date),
            frequency="daily",
            fields=fields,
            panel=False,
            fq=None,
        )
    except Exception:
        raw = get_price(
            symbol,
            start_date=_format_date(start_date),
            end_date=_format_date(end_date),
            frequency="daily",
            fields=REQUIRED_PRICE_FIELDS,
            panel=False,
            fq=None,
        )
    return _normalize_price_frame(raw, symbol)


def _normalize_futures_metadata(raw, asof_date):
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["asof_date", "symbol", "list_date", "end_date"])
    frame = raw.reset_index().copy()
    code_column = "index" if "index" in frame.columns else frame.columns[0]
    frame = frame.rename(columns={code_column: "symbol"})
    if "list_date" not in frame.columns:
        if "start_date" in frame.columns:
            frame = frame.rename(columns={"start_date": "list_date"})
        else:
            frame["list_date"] = asof_date
    if "end_date" not in frame.columns:
        return pd.DataFrame(columns=["asof_date", "symbol", "list_date", "end_date"])
    frame["symbol"] = frame["symbol"].astype(str).str.upper()
    frame = frame.loc[frame["symbol"].map(lambda value: bool(IRON_ORE_CODE_RE.fullmatch(value)))]
    frame["asof_date"] = pd.Timestamp(asof_date)
    frame["list_date"] = pd.to_datetime(frame["list_date"], errors="coerce")
    frame["end_date"] = pd.to_datetime(frame["end_date"], errors="coerce")
    frame = frame.dropna(subset=["list_date", "end_date"])
    return frame[["asof_date", "symbol", "list_date", "end_date"]].drop_duplicates(
        ["asof_date", "symbol"]
    )


def _download_universe(main_daily, metadata_stride):
    dates = list(pd.to_datetime(main_daily["trade_date"]).drop_duplicates().sort_values())
    if not dates:
        raise ValueError("main daily data is empty")
    stride = max(1, int(metadata_stride))
    selected_dates = dates[::stride]
    if dates[-1] not in selected_dates:
        selected_dates.append(dates[-1])
    snapshots = []
    for asof_date in selected_dates:
        raw = get_all_securities(["futures"], date=_format_date(asof_date))
        normalized = _normalize_futures_metadata(raw, asof_date)
        if not normalized.empty:
            snapshots.append(normalized)
    if not snapshots:
        raise ValueError("no iron ore futures were returned by get_all_securities")
    return pd.concat(snapshots, ignore_index=True).drop_duplicates(
        ["asof_date", "symbol"]
    ).sort_values(["asof_date", "symbol"]).reset_index(drop=True)


def export_iron_ore_v16_bundle(
    start_date="2018-01-01",
    end_date="2026-07-18",
    output_dir="iron_ore_v1_6_export",
    metadata_stride=1,
):
    """Download and write the complete V1.6 daily research bundle."""
    requested_start = pd.Timestamp(start_date).normalize()
    requested_end = pd.Timestamp(end_date).normalize()
    data_start = requested_start - pd.Timedelta(days=180)
    os.makedirs(output_dir, exist_ok=True)

    main_daily = _get_daily_price(SIGNAL_SECURITY, data_start, requested_end)
    if main_daily.empty:
        raise ValueError("I8888.XDCE returned no daily data")
    universe_daily = _download_universe(main_daily, metadata_stride)
    contracts = (
        universe_daily.loc[:, ["symbol", "list_date", "end_date"]]
        .drop_duplicates("symbol")
        .sort_values("symbol")
        .reset_index(drop=True)
    )

    contract_frames = []
    for symbol in contracts["symbol"].tolist():
        bars = _get_daily_price(symbol, data_start, requested_end)
        if not bars.empty:
            contract_frames.append(bars)
    if not contract_frames:
        raise ValueError("no iron ore contract daily bars were returned")
    contract_daily = pd.concat(contract_frames, ignore_index=True)

    datasets = {
        "main_daily": main_daily,
        "contract_daily": contract_daily,
        "contracts": contracts,
        "universe_daily": universe_daily,
    }
    for key, frame in datasets.items():
        frame.to_csv(
            os.path.join(output_dir, EXPORT_FILES[key]),
            index=False,
            encoding="utf-8-sig",
        )
    manifest = {
        "dataset": "iron_ore_v1_6",
        "source": "joinquant_research",
        "signal_security": SIGNAL_SECURITY,
        "requested_start_date": _format_date(requested_start),
        "requested_end_date": _format_date(requested_end),
        "data_start_date": _format_date(data_start),
        "data_end_date": _format_date(requested_end),
        "metadata_stride": int(metadata_stride),
        "required_price_fields": REQUIRED_PRICE_FIELDS,
        "optional_price_fields": QUERY_OPTIONAL_FIELDS,
        "row_counts": {key: int(len(frame)) for key, frame in datasets.items()},
        "contract_count": int(contracts["symbol"].nunique()),
        "universe_asof_count": int(universe_daily["asof_date"].nunique()),
    }
    with open(os.path.join(output_dir, "manifest.json"), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2, default=str)
    return manifest


# In JoinQuant Research, call export_iron_ore_v16_bundle(...) explicitly after
# reviewing the date range and metadata_stride.  The module does not auto-run
# a potentially large download merely because it was pasted or imported.
