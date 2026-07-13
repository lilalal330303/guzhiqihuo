"""Print the verified V12D July 13 execution chain."""
import pandas as pd

from quant_lab.data.repository import DuckDBRepository


repo = DuckDBRepository("data/market.duckdb")
intent = repo.load_paper_intent("wufu_v12d", "wufu_v12d", "2026-07-13")
print("INTENT", intent["target_weights"] if intent else None)
for label, frame in (
    ("ORDERS", repo.load_paper_orders("wufu_v12d")),
    ("FILLS", repo.load_paper_fills("wufu_v12d")),
):
    rows = frame[pd.to_datetime(frame["timestamp"]).dt.strftime("%Y-%m-%d") == "2026-07-13"]
    print(label)
    print(rows.to_string(index=False))
print("LATEST POSITIONS")
print(repo.load_paper_positions("wufu_v12d").tail(5).to_string(index=False))
print("LATEST EQUITY")
print(repo.load_paper_equity("wufu_v12d").tail(1).to_string(index=False))
