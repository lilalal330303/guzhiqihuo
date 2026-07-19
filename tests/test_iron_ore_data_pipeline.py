import json
import zipfile

import pandas as pd
import pytest

from reports.jq_research_export_iron_ore_v1_6 import (
    _normalize_price_frame,
    package_export_bundle,
)
from quant_lab.data.iron_ore import IronOreDataStore


def _write_bundle(root, duplicate_contract_row=False):
    dates = pd.date_range("2024-01-01", periods=3, freq="B")
    main = pd.DataFrame(
        {
            "symbol": "I8888.XDCE",
            "trade_date": dates,
            "open": [100.0, 99.0, 98.0],
            "high": [101.0, 100.0, 99.0],
            "low": [99.0, 98.0, 97.0],
            "close": [99.5, 98.5, 97.5],
            "volume": [10, 11, 12],
            "amount": [1000, 1100, 1200],
            "open_interest": [20, 21, 22],
        }
    )
    contract = main.copy()
    contract["symbol"] = "I2405.XDCE"
    metadata = pd.DataFrame(
        {
            "symbol": ["I2405.XDCE"],
            "list_date": ["2023-01-01"],
            "end_date": ["2025-05-10"],
        }
    )
    universe = pd.DataFrame(
        {
            "asof_date": dates,
            "symbol": "I2405.XDCE",
            "list_date": "2023-01-01",
            "end_date": "2025-05-10",
        }
    )
    if duplicate_contract_row:
        contract = pd.concat([contract, contract.iloc[[0]]], ignore_index=True)
    main.to_csv(root / "iron_ore_main_daily.csv", index=False)
    contract.to_csv(root / "iron_ore_contract_daily.csv", index=False)
    metadata.to_csv(root / "iron_ore_contracts.csv", index=False)
    universe.to_csv(root / "iron_ore_universe_daily.csv", index=False)
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "dataset": "iron_ore_v1_6",
                "start_date": "2024-01-01",
                "end_date": "2024-01-03",
                "source": "joinquant_research",
            }
        ),
        encoding="utf-8",
    )


def test_import_bundle_creates_idempotent_iron_ore_tables(tmp_path):
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    _write_bundle(export_dir)
    store = IronOreDataStore(tmp_path / "market.duckdb")

    first = store.import_bundle(export_dir)
    second = store.import_bundle(export_dir)

    assert first.row_counts["main_daily"] == 3
    assert first.row_counts["contract_daily"] == 3
    assert second.row_counts == first.row_counts
    assert len(store.load_main_daily()) == 3
    assert len(store.load_contract_daily()) == 3
    report = store.quality_report()
    assert report["main_daily_duplicate_keys"] == 0
    assert report["contract_daily_duplicate_keys"] == 0
    assert report["contract_count"] == 1


def test_import_bundle_accepts_the_single_download_zip(tmp_path):
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    _write_bundle(export_dir)
    zip_path = package_export_bundle(export_dir, tmp_path / "iron_ore_v1_6_export.zip")

    store = IronOreDataStore(tmp_path / "market.duckdb")
    result = store.import_bundle(zip_path)

    assert result.row_counts["main_daily"] == 3
    with zipfile.ZipFile(zip_path) as archive:
        assert sorted(archive.namelist()) == sorted(
            [
                "iron_ore_main_daily.csv",
                "iron_ore_contract_daily.csv",
                "iron_ore_contracts.csv",
                "iron_ore_universe_daily.csv",
                "manifest.json",
            ]
        )


def test_import_bundle_rejects_duplicate_contract_primary_keys(tmp_path):
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    _write_bundle(export_dir, duplicate_contract_row=True)
    store = IronOreDataStore(tmp_path / "market.duckdb")

    with pytest.raises(ValueError, match="duplicate.*contract_daily"):
        store.import_bundle(export_dir)


def test_import_bundle_rejects_non_iron_ore_contract_code(tmp_path):
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    _write_bundle(export_dir)
    bad_metadata = pd.DataFrame(
        {
            "symbol": ["IC2405.CCFX"],
            "list_date": ["2023-01-01"],
            "end_date": ["2025-05-10"],
        }
    )
    bad_metadata.to_csv(export_dir / "iron_ore_contracts.csv", index=False)
    store = IronOreDataStore(tmp_path / "market.duckdb")

    with pytest.raises(ValueError, match="contract code"):
        store.import_bundle(export_dir)


def test_research_export_normalizes_joinquant_money_to_local_amount():
    raw = pd.DataFrame(
        {
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
            "volume": [1000.0],
            "money": [100500.0],
            "open_interest": [500.0],
        },
        index=pd.to_datetime(["2024-01-02"]),
    )
    normalized = _normalize_price_frame(raw, "I8888.XDCE")
    assert normalized.loc[0, "amount"] == 100500.0
    assert "money" not in normalized.columns
