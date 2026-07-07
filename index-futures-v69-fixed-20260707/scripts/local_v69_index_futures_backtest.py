from __future__ import annotations

import html
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from backtest_a_share_index_futures_v18 import CONTRACTS
from backtest_multi_product_v22 import MARGIN_RATES, RISK_POINTS


ROOT = Path(__file__).resolve().parent
SRC = ROOT / "multi_product_v62_single_module_backtests" / "v62_single_module_trades.csv"
BASELINE = ROOT / "multi_product_v60_rebuild_environment_layer" / "sealed_v51_baseline" / "multi_cycle_summary.csv"
OUT = ROOT / "multi_product_v69_lock_allowed_priority_optimized"
OUT.mkdir(parents=True, exist_ok=True)

OPEN_FEE_RATE = 0.000023
CLOSE_Y_FEE_RATE = 0.000023
CLOSE_T_FEE_RATE = 0.00023
INITIAL_CASH = 1_000_000.0
MAX_ACTIVE_LOTS = 4
MAX_LOCK_PAIRS_PER_PRODUCT = 4
LOCK_CARRY_DAYS = 5
MIN_AVAILABLE_RATIO = 0.05

ALLOWED_MODULES = {"TREND_PULLBACK", "OPENING_RANGE_BREAKOUT"}
MODULE_ZH = {
    "TREND_PULLBACK": "趋势回踩",
    "OPENING_RANGE_BREAKOUT": "开盘区间突破",
}
MODULE_PRIORITY = {"TREND_PULLBACK": 3, "OPENING_RANGE_BREAKOUT": 2}


@dataclass
class Position:
    trade_id: int
    row: dict
    entry_fee: float
    entry_type: str
    qty: int = 1


def fee(price: float, product: str, rate: float) -> float:
    return float(price) * CONTRACTS[product]["multiplier"] * rate


def margin(price: float, product: str) -> float:
    return float(price) * CONTRACTS[product]["multiplier"] * MARGIN_RATES[product]


def money(x: float) -> str:
    return f"{x:,.0f}"


def pct(x: float) -> str:
    return f"{x:.2f}%"


def load_candidates() -> pd.DataFrame:
    trades = pd.read_csv(SRC)
    trades = trades[trades["module"].isin(ALLOWED_MODULES)].copy()
    trades["entry_time"] = pd.to_datetime(trades["entry_time"])
    trades["exit_time"] = pd.to_datetime(trades["exit_time"])
    trades["entry_date"] = trades["entry_time"].dt.date
    trades["exit_date"] = trades["exit_time"].dt.date
    trades["module_zh"] = trades["module"].map(MODULE_ZH).fillna(trades["module_zh"])
    trades["priority"] = trades["module"].map(MODULE_PRIORITY).fillna(1)
    trades["expected_margin"] = trades.apply(lambda r: margin(float(r["entry_price"]), str(r["product"])), axis=1)
    trades["expected_profit_cash"] = trades["target_points"].astype(float) * trades["product"].map(lambda p: CONTRACTS[p]["multiplier"])
    trades["efficiency"] = trades["expected_profit_cash"] / trades["expected_margin"].replace(0, pd.NA)
    trades = trades.sort_values(["entry_time", "priority", "efficiency"], ascending=[True, False, False]).reset_index(drop=True)
    trades["candidate_id"] = range(len(trades))
    return trades


def release_expired_locks(inventory: dict[str, list[dict]], now_date, price_hint: dict[str, float]) -> list[dict]:
    events = []
    for product, locks in inventory.items():
        kept = []
        for lock in locks:
            age = (pd.Timestamp(now_date) - pd.Timestamp(lock["date"])).days
            if age > LOCK_CARRY_DAYS:
                px = price_hint.get(product, lock["price"])
                release_fee = 2.0 * fee(px, product, CLOSE_Y_FEE_RATE)
                events.append(
                    {
                        "datetime": pd.Timestamp(now_date),
                        "date": now_date,
                        "product": product,
                        "event": "释放过期锁仓",
                        "fee": round(release_fee, 2),
                        "lock_date": lock["date"],
                    }
                )
            else:
                kept.append(lock)
        inventory[product] = kept
    return events


def available_after(active: list[Position], cash: float, row: pd.Series) -> float:
    used_margin = sum(margin(float(p.row["entry_price"]), str(p.row["product"])) for p in active)
    new_margin = margin(float(row["entry_price"]), str(row["product"]))
    return cash - used_margin - new_margin


def has_conflict(active: list[Position], row: pd.Series) -> tuple[bool, str]:
    product = str(row["product"])
    direction = str(row["direction"])
    if any(str(p.row["product"]) == product for p in active):
        return True, "同品种已有敞口"
    same_direction = sum(1 for p in active if str(p.row["direction"]) == direction)
    if same_direction >= 2:
        return True, "组合已有2手同向敞口"
    return False, ""


def has_future_signal(candidates: pd.DataFrame, idx: int, product: str, date) -> bool:
    future = candidates.iloc[idx + 1 :]
    if future.empty:
        return False
    return bool(((future["product"] == product) & (future["entry_date"] > date)).any())


def lock_side_for_entry(direction: str) -> str:
    return "short" if direction == "long" else "long"


def lock_side_for_exit(direction: str) -> str:
    return "short" if direction == "long" else "long"


def choose_entry_fee(row: pd.Series, inventory: dict[str, list[dict]]) -> tuple[float, str, int]:
    product = str(row["product"])
    entry_date = row["entry_date"]
    wanted_side = lock_side_for_entry(str(row["direction"]))
    locks = inventory.setdefault(product, [])
    today_same_side = any(lock.get("side") == wanted_side and lock["date"] == entry_date for lock in locks)
    if today_same_side:
        return fee(float(row["entry_price"]), product, OPEN_FEE_RATE), "新开仓：平昨被同品种今仓阻挡", 0
    usable_idx = next(
        (
            i
            for i, lock in enumerate(locks)
            if lock["date"] < entry_date and lock.get("side") == wanted_side
        ),
        None,
    )
    if usable_idx is None:
        return fee(float(row["entry_price"]), product, OPEN_FEE_RATE), "新开仓", 0
    locks.pop(usable_idx)
    return fee(float(row["entry_price"]), product, CLOSE_Y_FEE_RATE), "复用昨日对锁筹码", 1


def close_position(pos: Position, now, inventory: dict[str, list[dict]], candidates: pd.DataFrame, idx_hint: int) -> dict:
    row = pos.row
    product = str(row["product"])
    exit_price = float(row["exit_price"])
    exit_date = pd.Timestamp(row["exit_time"]).date()
    locks = inventory.setdefault(product, [])
    is_reused_chip = pos.entry_type.startswith("复用")
    can_lock = (
        not is_reused_chip
        and len(locks) < MAX_LOCK_PAIRS_PER_PRODUCT
        and has_future_signal(candidates, idx_hint, product, exit_date)
    )
    if is_reused_chip:
        exit_fee = fee(exit_price, product, CLOSE_Y_FEE_RATE)
        exit_type = "复用旧筹码后直接平昨"
        avoided = 0
        direct = 0
        old_chip_close_yesterday = 1
    elif can_lock:
        exit_fee = fee(exit_price, product, OPEN_FEE_RATE)
        locks.append({"date": exit_date, "price": exit_price, "side": lock_side_for_exit(str(row["direction"]))})
        exit_type = "退出对锁，规避平今"
        avoided = 1
        direct = 0
        old_chip_close_yesterday = 0
    else:
        exit_fee = fee(exit_price, product, CLOSE_T_FEE_RATE)
        exit_type = "锁仓额度不足或末段，直接平今"
        avoided = 0
        direct = 1
        old_chip_close_yesterday = 0
    total_fee = pos.entry_fee + exit_fee
    gross = float(row["gross_pnl"])
    return {
        "trade_id": pos.trade_id,
        "candidate_id": row["candidate_id"],
        "stage": row["stage"],
        "product": product,
        "module": row["module"],
        "module_zh": row["module_zh"],
        "direction": row["direction"],
        "entry_time": row["entry_time"],
        "exit_time": row["exit_time"],
        "entry_price": row["entry_price"],
        "exit_price": row["exit_price"],
        "state": row["state"],
        "state_zh": row["state_zh"],
        "environment": row["environment"],
        "environment_zh": row["environment_zh"],
        "exit_reason": row["exit_reason"],
        "points": row["points"],
        "gross_pnl": round(gross, 2),
        "fee": round(total_fee, 2),
        "net_pnl": round(gross - total_fee, 2),
        "entry_type": pos.entry_type,
        "exit_type": exit_type,
        "avoid_close_today": avoided,
        "chip_reused": 1 if is_reused_chip else 0,
        "forced_direct_close": direct,
        "old_chip_close_yesterday": old_chip_close_yesterday,
        "lock_pairs_after": len(locks),
    }


def run_combo(candidates: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    active: list[Position] = []
    inventory: dict[str, list[dict]] = {}
    closed_rows = []
    rejected_rows = []
    event_rows = []
    equity_rows = []
    cash = INITIAL_CASH
    trade_id = 0
    last_release_date = None

    for idx, row in candidates.iterrows():
        now = row["entry_time"]
        now_date = row["entry_date"]
        if last_release_date != now_date:
            price_hint = {str(r["product"]): float(r["entry_price"]) for _, r in candidates[candidates["entry_date"] == now_date].iterrows()}
            releases = release_expired_locks(inventory, now_date, price_hint)
            for event in releases:
                cash -= float(event["fee"])
                event_rows.append(event)
            last_release_date = now_date

        still_active = []
        for pos in active:
            if pd.Timestamp(pos.row["exit_time"]) <= now:
                closed = close_position(pos, now, inventory, candidates, idx)
                cash += float(closed["net_pnl"])
                closed_rows.append(closed)
            else:
                still_active.append(pos)
        active = still_active

        conflict, reason = has_conflict(active, row)
        if conflict:
            rejected_rows.append({"candidate_id": row["candidate_id"], "stage": row["stage"], "product": row["product"], "entry_time": row["entry_time"], "module": row["module"], "reason": reason})
            continue
        if len(active) >= MAX_ACTIVE_LOTS:
            rejected_rows.append({"candidate_id": row["candidate_id"], "stage": row["stage"], "product": row["product"], "entry_time": row["entry_time"], "module": row["module"], "reason": "组合敞口达到4手"})
            continue
        available = available_after(active, cash, row)
        if available < INITIAL_CASH * MIN_AVAILABLE_RATIO:
            rejected_rows.append({"candidate_id": row["candidate_id"], "stage": row["stage"], "product": row["product"], "entry_time": row["entry_time"], "module": row["module"], "reason": "可用资金低于5%阈值"})
            continue
        entry_fee, entry_type, reused = choose_entry_fee(row, inventory)
        cash -= entry_fee
        trade_id += 1
        active.append(Position(trade_id=trade_id, row=row.to_dict(), entry_fee=entry_fee, entry_type=entry_type))
        equity_rows.append(
            {
                "datetime": now,
                "stage": row["stage"],
                "cash_after_fee": round(cash, 2),
                "active_lots": len(active),
                "locked_pairs": sum(len(v) for v in inventory.values()),
                "available_cash_est": round(available, 2),
                "opened_product": row["product"],
                "opened_module": row["module"],
                "chip_reused": reused,
            }
        )

    for pos in active:
        closed = close_position(pos, pos.row["exit_time"], inventory, candidates, len(candidates) - 1)
        cash += float(closed["net_pnl"])
        closed_rows.append(closed)

    for product, locks in inventory.items():
        if not locks:
            continue
        last_px = float(candidates[candidates["product"] == product]["exit_price"].iloc[-1])
        for lock in locks:
            release_fee = 2.0 * fee(last_px, product, CLOSE_Y_FEE_RATE)
            cash -= release_fee
            event_rows.append(
                {
                    "datetime": candidates["exit_time"].max(),
                    "date": candidates["exit_date"].max(),
                    "product": product,
                    "event": "回测结束释放剩余锁仓",
                    "fee": round(release_fee, 2),
                    "lock_date": lock["date"],
                }
            )

    trades = pd.DataFrame(closed_rows).sort_values(["exit_time", "entry_time"]).reset_index(drop=True)
    rejected = pd.DataFrame(rejected_rows)
    events = pd.DataFrame(event_rows)
    equity = pd.DataFrame(equity_rows)
    if not trades.empty and not events.empty:
        # Put final release fees into total accounting without changing individual trade win/loss.
        release_by_stage = events.assign(stage=events["date"].astype(str).map(lambda _: "")).copy()
    return trades, rejected, events, equity


def summarize(candidates: pd.DataFrame, trades: pd.DataFrame, events: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    release_fee = float(events["fee"].sum()) if not events.empty else 0.0
    stage_release = pd.DataFrame(columns=["stage", "release_fee"])
    if not events.empty:
        stage_map = candidates[["stage", "exit_date"]].drop_duplicates().copy()
        stage_map["date"] = stage_map["exit_date"].astype(str)
        ev = events.copy()
        ev["date"] = ev["date"].astype(str)
        ev = ev.merge(stage_map[["stage", "date"]], on="date", how="left")
        stage_release = ev.groupby("stage", dropna=False)["fee"].sum().reset_index(name="release_fee")

    module = (
        trades.groupby(["module", "module_zh"], sort=False)
        .agg(
            trades=("net_pnl", "size"),
            net_pnl=("net_pnl", "sum"),
            gross_pnl=("gross_pnl", "sum"),
            fee=("fee", "sum"),
            win_rate=("net_pnl", lambda s: (s > 0).mean() * 100),
            avoided_close_today=("avoid_close_today", "sum"),
            chip_reused=("chip_reused", "sum"),
            direct_close=("forced_direct_close", "sum"),
            old_chip_close_yesterday=("old_chip_close_yesterday", "sum"),
        )
        .reset_index()
    )
    stage = (
        trades.groupby("stage", sort=False)
        .agg(
            trades=("net_pnl", "size"),
            net_pnl=("net_pnl", "sum"),
            gross_pnl=("gross_pnl", "sum"),
            fee=("fee", "sum"),
            win_rate=("net_pnl", lambda s: (s > 0).mean() * 100),
            avoided_close_today=("avoid_close_today", "sum"),
            chip_reused=("chip_reused", "sum"),
            direct_close=("forced_direct_close", "sum"),
            old_chip_close_yesterday=("old_chip_close_yesterday", "sum"),
        )
        .reset_index()
    )
    stage = stage.merge(stage_release, on="stage", how="left")
    stage["release_fee"] = stage["release_fee"].fillna(0.0)
    stage["net_after_release"] = stage["net_pnl"] - stage["release_fee"]

    total = pd.DataFrame(
        [
            {
                "version": "V65 旧筹码平昨退出",
                "candidate_signals": len(candidates),
                "closed_trades": len(trades),
                "net_profit": float(trades["net_pnl"].sum()) - release_fee if not trades.empty else -release_fee,
                "gross_pnl": float(trades["gross_pnl"].sum()) if not trades.empty else 0.0,
                "trade_fee": float(trades["fee"].sum()) if not trades.empty else 0.0,
                "release_fee": release_fee,
                "total_fee": (float(trades["fee"].sum()) if not trades.empty else 0.0) + release_fee,
                "win_rate_pct": float((trades["net_pnl"] > 0).mean() * 100) if not trades.empty else 0.0,
                "avoided_close_today": int(trades["avoid_close_today"].sum()) if not trades.empty else 0,
                "chip_reused": int(trades["chip_reused"].sum()) if not trades.empty else 0,
                "direct_close": int(trades["forced_direct_close"].sum()) if not trades.empty else 0,
                "old_chip_close_yesterday": int(trades["old_chip_close_yesterday"].sum()) if not trades.empty else 0,
            }
        ]
    )
    return total, module, stage


def read_baseline() -> pd.DataFrame:
    if not BASELINE.exists():
        return pd.DataFrame()
    base = pd.read_csv(BASELINE)
    return base[["stage", "net_profit", "closed_trades", "win_rate_pct", "total_fee", "max_drawdown_pct"]].rename(
        columns={
            "net_profit": "baseline_net",
            "closed_trades": "baseline_trades",
            "win_rate_pct": "baseline_win_rate",
            "total_fee": "baseline_fee",
            "max_drawdown_pct": "baseline_dd",
        }
    )


def table_html(df: pd.DataFrame, cols: list[str], money_cols: set[str] | None = None, pct_cols: set[str] | None = None) -> str:
    money_cols = money_cols or set()
    pct_cols = pct_cols or set()
    head = "".join(f"<th>{html.escape(c)}</th>" for c in cols)
    rows = []
    for _, row in df[cols].iterrows():
        cells = []
        for col in cols:
            value = row[col]
            if pd.notna(value):
                if col in money_cols:
                    value = money(float(value))
                elif col in pct_cols:
                    value = pct(float(value))
                elif isinstance(value, float):
                    value = f"{value:.2f}"
            cells.append(f"<td>{html.escape(str(value))}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return "<table><thead><tr>" + head + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"


def build_report(total: pd.DataFrame, module: pd.DataFrame, stage: pd.DataFrame, rejected: pd.DataFrame) -> None:
    base = read_baseline()
    stage_compare = stage.merge(base, on="stage", how="left")
    if "baseline_net" in stage_compare:
        stage_compare["net_diff_vs_v51"] = stage_compare["net_after_release"] - stage_compare["baseline_net"]
    else:
        stage_compare["net_diff_vs_v51"] = pd.NA
    total_net = float(total["net_profit"].iloc[0])
    rejected_summary = (
        rejected.groupby("reason").size().reset_index(name="count").sort_values("count", ascending=False)
        if not rejected.empty
        else pd.DataFrame(columns=["reason", "count"])
    )
    doc = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<title>V65 旧筹码平昨退出回测</title>
<style>
body{{margin:0;background:#f5f7fb;color:#172033;font-family:"Microsoft YaHei",Arial,sans-serif}}
.wrap{{max-width:1540px;margin:0 auto;padding:28px 30px 46px}}
.hero{{background:#172033;color:white;border-radius:8px;padding:26px 30px}}
h1{{margin:0 0 8px;font-size:34px}} h2{{margin:28px 0 12px;font-size:22px}}
p{{line-height:1.75;color:#435066}} table{{width:100%;border-collapse:collapse;background:#fff;border:1px solid #d9e1ea}}
th{{background:#26364f;color:#fff;text-align:left;padding:10px;white-space:nowrap}} td{{padding:9px 10px;border-top:1px solid #e6ebf2;white-space:nowrap}}
tr:nth-child(even) td{{background:#f8fafd}} .cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:18px 0}}
.card{{background:white;border:1px solid #d9e1ea;border-radius:8px;padding:15px}} .k{{font-size:13px;color:#607085}} .v{{font-size:22px;font-weight:700;margin-top:6px}}
.note{{background:#fff;border-left:5px solid #3267d6;padding:14px 16px;margin:16px 0;color:#334155}}
</style>
</head>
<body><div class="wrap">
<section class="hero"><h1>V65 旧筹码平昨退出回测</h1><div>只交易趋势回踩和开盘区间突破；新开仓退出可对锁，复用昨日对锁筹码形成的敞口退出时直接平昨。</div></section>
<div class="cards">
<div class="card"><div class="k">十段净收益</div><div class="v">{money(total_net)}</div></div>
<div class="card"><div class="k">成交笔数</div><div class="v">{int(total['closed_trades'].iloc[0]):,}</div></div>
<div class="card"><div class="k">总手续费</div><div class="v">{money(float(total['total_fee'].iloc[0]))}</div></div>
<div class="card"><div class="k">真实胜率</div><div class="v">{pct(float(total['win_rate_pct'].iloc[0]))}</div></div>
</div>
<div class="note">该版本专门修正V64的滚动续锁：旧对锁筹码可以平单边作为开仓筹码，但这笔敞口退出时不再继续对锁，而是按平昨直接结算。</div>
<h2>总览</h2>
{table_html(total, ["version","candidate_signals","closed_trades","net_profit","gross_pnl","trade_fee","release_fee","total_fee","win_rate_pct","avoided_close_today","chip_reused","old_chip_close_yesterday","direct_close"], {"net_profit","gross_pnl","trade_fee","release_fee","total_fee"}, {"win_rate_pct"})}
<h2>模块贡献</h2>
{table_html(module.sort_values("net_pnl", ascending=False), ["module_zh","trades","net_pnl","gross_pnl","fee","win_rate","avoided_close_today","chip_reused","old_chip_close_yesterday","direct_close"], {"net_pnl","gross_pnl","fee"}, {"win_rate"})}
<h2>十段表现与V51基准对比</h2>
{table_html(stage_compare.sort_values("stage"), ["stage","trades","net_after_release","gross_pnl","fee","release_fee","win_rate","avoided_close_today","chip_reused","old_chip_close_yesterday","baseline_net","net_diff_vs_v51","baseline_trades","baseline_fee","baseline_dd"], {"net_after_release","gross_pnl","fee","release_fee","baseline_net","net_diff_vs_v51","baseline_fee"}, {"win_rate","baseline_dd"})}
<h2>被过滤候选</h2>
{table_html(rejected_summary, ["reason","count"])}
<h2>下一步</h2>
<p>如果V65手续费继续下降且净收益保持，下一步再进入信号侧降频；如果净收益明显下降，说明滚动续锁本身贡献了可用筹码，需要限制而不是完全关闭。</p>
</div></body></html>"""
    (OUT / "v65_chip_exit_close_yesterday_report.html").write_text(doc, encoding="utf-8")


def main() -> None:
    candidates = load_candidates()
    trades, rejected, events, equity = run_combo(candidates)
    total, module, stage = summarize(candidates, trades, events)
    candidates.to_csv(OUT / "v65_candidates.csv", index=False, encoding="utf-8-sig")
    trades.to_csv(OUT / "v65_combo_trades.csv", index=False, encoding="utf-8-sig")
    rejected.to_csv(OUT / "v65_rejected_candidates.csv", index=False, encoding="utf-8-sig")
    events.to_csv(OUT / "v65_lock_events.csv", index=False, encoding="utf-8-sig")
    equity.to_csv(OUT / "v65_equity_events.csv", index=False, encoding="utf-8-sig")
    total.to_csv(OUT / "v65_summary.csv", index=False, encoding="utf-8-sig")
    module.to_csv(OUT / "v65_module_summary.csv", index=False, encoding="utf-8-sig")
    stage.to_csv(OUT / "v65_stage_summary.csv", index=False, encoding="utf-8-sig")
    build_report(total, module, stage, rejected)
    print(OUT / "v65_chip_exit_close_yesterday_report.html")


if __name__ == "__main__":
    main()
