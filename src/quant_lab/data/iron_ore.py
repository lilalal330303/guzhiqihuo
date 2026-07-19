from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pandas as pd


IRON_ORE_CODE_RE = re.compile(r"^I\d{4}\.XDCE$", re.IGNORECASE)
EXPORT_FILES = {
    "main_daily": "iron_ore_main_daily.csv",
    "contract_daily": "iron_ore_contract_daily.csv",
    "contracts": "iron_ore_contracts.csv",
    "universe_daily": "iron_ore_universe_daily.csv",
}
BAR_COLUMNS = [
    "symbol",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "open_interest",
]


@dataclass(frozen=True)
class IronOreImportResult:
    db_path: str
    row_counts: dict[str, int]
    quality: dict[str, object]


class IronOreDataStore:
    """DuckDB storage and validation boundary for the iron ore export bundle."""

    def __init__(self, db_path: str | Path = "data/market.duckdb") -> None:
        self.db_path = Path(db_path)

    def _connect(self) -> duckdb.DuckDBPyConnection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        return duckdb.connect(str(self.db_path))

    def initialize(self) -> None:
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS iron_ore_main_daily (
                    symbol VARCHAR NOT NULL,
                    trade_date DATE NOT NULL,
                    open DOUBLE NOT NULL,
                    high DOUBLE NOT NULL,
                    low DOUBLE NOT NULL,
                    close DOUBLE NOT NULL,
                    volume DOUBLE NOT NULL,
                    amount DOUBLE NOT NULL,
                    open_interest DOUBLE NOT NULL,
                    source VARCHAR NOT NULL,
                    fetched_at TIMESTAMP NOT NULL,
                    PRIMARY KEY (symbol, trade_date)
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS iron_ore_contract_daily (
                    symbol VARCHAR NOT NULL,
                    trade_date DATE NOT NULL,
                    open DOUBLE NOT NULL,
                    high DOUBLE NOT NULL,
                    low DOUBLE NOT NULL,
                    close DOUBLE NOT NULL,
                    volume DOUBLE NOT NULL,
                    amount DOUBLE NOT NULL,
                    open_interest DOUBLE NOT NULL,
                    source VARCHAR NOT NULL,
                    fetched_at TIMESTAMP NOT NULL,
                    PRIMARY KEY (symbol, trade_date)
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS iron_ore_contracts (
                    symbol VARCHAR PRIMARY KEY,
                    list_date DATE NOT NULL,
                    end_date DATE NOT NULL,
                    source VARCHAR NOT NULL,
                    fetched_at TIMESTAMP NOT NULL
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS iron_ore_universe_daily (
                    asof_date DATE NOT NULL,
                    symbol VARCHAR NOT NULL,
                    list_date DATE NOT NULL,
                    end_date DATE NOT NULL,
                    source VARCHAR NOT NULL,
                    fetched_at TIMESTAMP NOT NULL,
                    PRIMARY KEY (asof_date, symbol)
                )
                """
            )

    def import_bundle(
        self,
        export_dir: str | Path,
        source: str = "joinquant_research",
    ) -> IronOreImportResult:
        """Validate and idempotently import one JoinQuant research export."""
        root = Path(export_dir)
        if not root.is_dir():
            raise FileNotFoundError(f"export directory does not exist: {root}")
        manifest_path = root / "manifest.json"
        manifest: dict[str, object] = {}
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            source = str(manifest.get("source") or source)

        main = self._normalize_bars(
            self._read_required_csv(root / EXPORT_FILES["main_daily"], "main_daily"),
            dataset="main_daily",
            require_main=True,
        )
        contract_daily = self._normalize_bars(
            self._read_required_csv(root / EXPORT_FILES["contract_daily"], "contract_daily"),
            dataset="contract_daily",
            require_main=False,
        )
        contracts = self._normalize_contracts(
            self._read_required_csv(root / EXPORT_FILES["contracts"], "contracts")
        )
        universe = self._normalize_universe(
            self._read_required_csv(root / EXPORT_FILES["universe_daily"], "universe_daily")
        )
        if not set(contract_daily["symbol"]).issubset(set(contracts["symbol"])):
            missing = sorted(set(contract_daily["symbol"]).difference(contracts["symbol"]))
            raise ValueError(f"contract_daily contains symbols missing from contracts: {missing[:5]}")

        now = datetime.now(UTC)
        self.initialize()
        with self._connect() as con:
            self._upsert_bars(con, "iron_ore_main_daily", main, source, now)
            self._upsert_bars(con, "iron_ore_contract_daily", contract_daily, source, now)
            self._upsert_contracts(con, contracts, source, now)
            self._upsert_universe(con, universe, source, now)

        counts = {
            "main_daily": int(len(main)),
            "contract_daily": int(len(contract_daily)),
            "contracts": int(len(contracts)),
            "universe_daily": int(len(universe)),
        }
        quality = self.quality_report()
        quality["manifest"] = manifest
        return IronOreImportResult(str(self.db_path), counts, quality)

    @staticmethod
    def _read_required_csv(path: Path, dataset: str) -> pd.DataFrame:
        if not path.exists():
            raise FileNotFoundError(f"missing {dataset} export file: {path}")
        return pd.read_csv(path)

    @staticmethod
    def _normalize_bars(
        frame: pd.DataFrame,
        dataset: str,
        require_main: bool,
    ) -> pd.DataFrame:
        required = {"symbol", "trade_date", "open", "high", "low", "close"}
        missing = sorted(required.difference(frame.columns))
        if missing:
            raise ValueError(f"{dataset} missing required columns: {missing}")
        rows = frame.copy()
        if require_main and set(rows["symbol"].astype(str).str.upper()) != {"I8888.XDCE"}:
            raise ValueError("main_daily must contain only I8888.XDCE")
        if not require_main:
            codes = rows["symbol"].astype(str).str.upper()
            if not codes.map(lambda value: bool(IRON_ORE_CODE_RE.fullmatch(value))).all():
                raise ValueError(f"{dataset} contains an invalid contract code")
            rows["symbol"] = codes
        else:
            rows["symbol"] = rows["symbol"].astype(str).str.upper()
        rows["trade_date"] = pd.to_datetime(rows["trade_date"], errors="coerce").dt.date
        if rows["trade_date"].isna().any():
            raise ValueError(f"{dataset} contains invalid trade_date values")
        if rows.duplicated(["symbol", "trade_date"]).any():
            raise ValueError(f"duplicate primary keys in {dataset}")
        for column in ["open", "high", "low", "close", "volume", "amount", "open_interest"]:
            if column not in rows.columns:
                rows[column] = 0.0
            rows[column] = pd.to_numeric(rows[column], errors="coerce")
        if rows[["open", "high", "low", "close"]].isna().any().any():
            raise ValueError(f"{dataset} has null OHLC values")
        if (rows[["open", "high", "low", "close"]] <= 0).any().any():
            raise ValueError(f"{dataset} has non-positive OHLC values")
        rows[["volume", "amount", "open_interest"]] = rows[
            ["volume", "amount", "open_interest"]
        ].fillna(0.0)
        return rows[BAR_COLUMNS].sort_values(["symbol", "trade_date"]).reset_index(drop=True)

    @staticmethod
    def _normalize_contracts(frame: pd.DataFrame) -> pd.DataFrame:
        required = {"symbol", "list_date", "end_date"}
        missing = sorted(required.difference(frame.columns))
        if missing:
            raise ValueError(f"contracts missing required columns: {missing}")
        rows = frame.loc[:, ["symbol", "list_date", "end_date"]].copy()
        rows["symbol"] = rows["symbol"].astype(str).str.upper()
        if not rows["symbol"].map(lambda value: bool(IRON_ORE_CODE_RE.fullmatch(value))).all():
            raise ValueError("contracts contains an invalid contract code")
        rows["list_date"] = pd.to_datetime(rows["list_date"], errors="coerce").dt.date
        rows["end_date"] = pd.to_datetime(rows["end_date"], errors="coerce").dt.date
        if rows[["list_date", "end_date"]].isna().any().any():
            raise ValueError("contracts contains invalid dates")
        if (rows["list_date"] >= rows["end_date"]).any():
            raise ValueError("contracts requires list_date < end_date")
        if rows["symbol"].duplicated().any():
            raise ValueError("duplicate primary keys in contracts")
        return rows.sort_values("symbol").reset_index(drop=True)

    @staticmethod
    def _normalize_universe(frame: pd.DataFrame) -> pd.DataFrame:
        required = {"asof_date", "symbol", "list_date", "end_date"}
        missing = sorted(required.difference(frame.columns))
        if missing:
            raise ValueError(f"universe_daily missing required columns: {missing}")
        rows = frame.loc[:, ["asof_date", "symbol", "list_date", "end_date"]].copy()
        rows["symbol"] = rows["symbol"].astype(str).str.upper()
        if not rows["symbol"].map(lambda value: bool(IRON_ORE_CODE_RE.fullmatch(value))).all():
            raise ValueError("universe_daily contains an invalid contract code")
        for column in ["asof_date", "list_date", "end_date"]:
            rows[column] = pd.to_datetime(rows[column], errors="coerce").dt.date
        if rows[["asof_date", "list_date", "end_date"]].isna().any().any():
            raise ValueError("universe_daily contains invalid dates")
        if (rows["list_date"] >= rows["end_date"]).any():
            raise ValueError("universe_daily requires list_date < end_date")
        if rows.duplicated(["asof_date", "symbol"]).any():
            raise ValueError("duplicate primary keys in universe_daily")
        return rows.sort_values(["asof_date", "symbol"]).reset_index(drop=True)

    @staticmethod
    def _upsert_bars(con, table: str, rows: pd.DataFrame, source: str, fetched_at: datetime) -> None:
        payload = rows.copy()
        payload["source"] = source
        payload["fetched_at"] = fetched_at
        con.register("iron_ore_bar_rows", payload)
        con.execute(
            f"""
            INSERT OR REPLACE INTO {table}
            SELECT symbol, trade_date, open, high, low, close, volume, amount,
                   open_interest, source, fetched_at
            FROM iron_ore_bar_rows
            """
        )
        con.unregister("iron_ore_bar_rows")

    @staticmethod
    def _upsert_contracts(con, rows: pd.DataFrame, source: str, fetched_at: datetime) -> None:
        payload = rows.copy()
        payload["source"] = source
        payload["fetched_at"] = fetched_at
        con.register("iron_ore_contract_rows", payload)
        con.execute(
            """
            INSERT OR REPLACE INTO iron_ore_contracts
            SELECT symbol, list_date, end_date, source, fetched_at
            FROM iron_ore_contract_rows
            """
        )
        con.unregister("iron_ore_contract_rows")

    @staticmethod
    def _upsert_universe(con, rows: pd.DataFrame, source: str, fetched_at: datetime) -> None:
        payload = rows.copy()
        payload["source"] = source
        payload["fetched_at"] = fetched_at
        con.register("iron_ore_universe_rows", payload)
        con.execute(
            """
            INSERT OR REPLACE INTO iron_ore_universe_daily
            SELECT asof_date, symbol, list_date, end_date, source, fetched_at
            FROM iron_ore_universe_rows
            """
        )
        con.unregister("iron_ore_universe_rows")

    def load_main_daily(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        return self._load_bars("iron_ore_main_daily", start_date, end_date)

    def load_contract_daily(
        self,
        symbols: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        self.initialize()
        clauses = []
        params: list[object] = []
        if symbols:
            placeholders = ", ".join("?" for _ in symbols)
            clauses.append(f"symbol IN ({placeholders})")
            params.extend(symbols)
        if start_date:
            clauses.append("trade_date >= ?")
            params.append(start_date)
        if end_date:
            clauses.append("trade_date <= ?")
            params.append(end_date)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as con:
            return con.execute(
                "SELECT symbol, trade_date, open, high, low, close, volume, amount, open_interest, source, fetched_at "
                f"FROM iron_ore_contract_daily{where} ORDER BY symbol, trade_date",
                params,
            ).df()

    def load_contracts(self) -> pd.DataFrame:
        self.initialize()
        with self._connect() as con:
            return con.execute(
                "SELECT symbol, list_date, end_date, source, fetched_at FROM iron_ore_contracts ORDER BY symbol"
            ).df()

    def load_universe(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        self.initialize()
        clauses = []
        params: list[object] = []
        if start_date:
            clauses.append("asof_date >= ?")
            params.append(start_date)
        if end_date:
            clauses.append("asof_date <= ?")
            params.append(end_date)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as con:
            return con.execute(
                "SELECT asof_date, symbol, list_date, end_date, source, fetched_at "
                f"FROM iron_ore_universe_daily{where} ORDER BY asof_date, symbol",
                params,
            ).df()

    def _load_bars(
        self,
        table: str,
        start_date: str | None,
        end_date: str | None,
    ) -> pd.DataFrame:
        self.initialize()
        clauses = []
        params: list[object] = []
        if start_date:
            clauses.append("trade_date >= ?")
            params.append(start_date)
        if end_date:
            clauses.append("trade_date <= ?")
            params.append(end_date)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as con:
            return con.execute(
                "SELECT symbol, trade_date, open, high, low, close, volume, amount, open_interest, source, fetched_at "
                f"FROM {table}{where} ORDER BY trade_date",
                params,
            ).df()

    def quality_report(self) -> dict[str, object]:
        self.initialize()
        with self._connect() as con:
            main = con.execute(
                """
                SELECT COUNT(*) AS row_count, MIN(trade_date) AS min_date,
                       MAX(trade_date) AS max_date,
                       COUNT(DISTINCT trade_date) AS distinct_dates,
                       SUM(CASE WHEN open <= 0 OR high <= 0 OR low <= 0 OR close <= 0 THEN 1 ELSE 0 END) AS invalid_ohlc
                FROM iron_ore_main_daily
                """
            ).fetchone()
            contract = con.execute(
                """
                SELECT COUNT(*) AS row_count, COUNT(DISTINCT symbol) AS symbol_count,
                       COUNT(DISTINCT CAST(trade_date AS VARCHAR) || '|' || symbol) AS distinct_keys,
                       SUM(CASE WHEN open <= 0 OR high <= 0 OR low <= 0 OR close <= 0 THEN 1 ELSE 0 END) AS invalid_ohlc
                FROM iron_ore_contract_daily
                """
            ).fetchone()
            universe = con.execute(
                "SELECT COUNT(*), COUNT(DISTINCT asof_date), COUNT(DISTINCT symbol) FROM iron_ore_universe_daily"
            ).fetchone()
            contract_count = con.execute("SELECT COUNT(*) FROM iron_ore_contracts").fetchone()[0]
        main_rows = int(main[0] or 0)
        contract_rows = int(contract[0] or 0)
        return {
            "main_daily_rows": main_rows,
            "main_daily_min_date": None if main[1] is None else str(main[1]),
            "main_daily_max_date": None if main[2] is None else str(main[2]),
            "main_daily_duplicate_keys": main_rows - int(main[3] or 0),
            "main_daily_invalid_ohlc": int(main[4] or 0),
            "contract_daily_rows": contract_rows,
            "contract_count": int(contract_count or 0),
            "contract_daily_duplicate_keys": contract_rows - int(contract[2] or 0),
            "contract_daily_invalid_ohlc": int(contract[3] or 0),
            "universe_daily_rows": int(universe[0] or 0),
            "universe_asof_dates": int(universe[1] or 0),
            "universe_symbol_count": int(universe[2] or 0),
        }
