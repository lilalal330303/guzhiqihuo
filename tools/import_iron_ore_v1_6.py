import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from quant_lab.data.iron_ore import IronOreDataStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Import a JoinQuant iron ore V1.6 export directory or ZIP into DuckDB.")
    parser.add_argument("--input", "--input-dir", dest="input_path", required=True, help="Export directory or .zip file.")
    parser.add_argument("--db", default="data/market.duckdb", help="DuckDB path.")
    parser.add_argument("--source", default="joinquant_research", help="Source label stored in DuckDB.")
    args = parser.parse_args()

    result = IronOreDataStore(args.db).import_bundle(args.input_path, source=args.source)
    print(json.dumps({
        "db_path": result.db_path,
        "row_counts": result.row_counts,
        "quality": result.quality,
    }, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
