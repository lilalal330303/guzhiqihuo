from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

import pandas as pd


DATE_TIME_RE = re.compile(r"(?P<date>\d{4}-\d{2}-\d{2})\s+(?P<time>\d{2}:\d{2}:\d{2})")
SIGNAL_RE = re.compile(r"WUFU_SIGNAL .*?signal_date=(?P<date>\d{4}-\d{2}-\d{2}) target=(?P<target>[^ ]*) top10=(?P<top10>.*)$")
EXECUTE_RE = re.compile(r"WUFU_EXECUTE .*?trade_date=(?P<date>\d{4}-\d{2}-\d{2}) target=(?P<target>.*)$")
MORNING_RE = re.compile(r"morning date=(?P<date>\d{4}-\d{2}-\d{2}) weak=(?P<weak>True|False) threshold=(?P<threshold>[-\d.]+) pool=(?P<pool>\d+)")
JQ_MORNING_RE = re.compile(r"WUFU_MORNING .*?weak=(?P<weak>True|False) threshold=(?P<threshold>[-\d.]+) pool=(?P<pool>\d+)")
SCORE_DETAIL_RE = re.compile(r"WUFU_SCORE_DETAIL date=(?P<date>\d{4}-\d{2}-\d{2}) weak=(?P<weak>True|False) pool=(?P<pool>\d+) passed=(?P<passed>\d+) target=(?P<target>[^ ]+) top10=(?P<top10>.*)$")
THRESHOLD_RE = re.compile(r"WUFU_THRESHOLD_DETAIL date=(?P<date>\d{4}-\d{2}-\d{2}) universe=(?P<universe>\d+) valid=(?P<valid>\d+).*?threshold=(?P<threshold>[-\d.]+) source=(?P<source>\S+)")
POOL_RE = re.compile(r"WUFU_POOL_FILTER date=(?P<date>\d{4}-\d{2}-\d{2}) input=(?P<input>\d+) output=(?P<output>\d+) threshold=(?P<threshold>[-\d.]+) selected=(?P<selected>.*?) rejected_sample=")
ORDER_PLAN_RE = re.compile(r"WUFU_ORDER_PLAN date=(?P<date>\d{4}-\d{2}-\d{2}) code=(?P<code>\S+) account_value=(?P<account_value>[-\d.]+) buffered_value=(?P<buffered_value>[-\d.]+) price=(?P<price>[-\d.]+) shares=(?P<shares>\d+) order_value=(?P<order_value>[-\d.]+)")
POSITION_RE = re.compile(r"WUFU_POSITION date=(?P<date>\d{4}-\d{2}-\d{2}) value=(?P<value>[-\d.]+) positions=(?P<positions>.*)$")
THS_CLOSE_RE = re.compile(r"close value=(?P<value>[-\d.]+) weak=(?P<weak>True|False) pool=(?P<pool>\d+) target=(?P<target>[^ ]*) top10=(?P<top10>.*)$")

DIAGNOSTIC_DATES = {
    "2020-07-17", "2020-12-14", "2021-04-20", "2021-05-26", "2021-05-27",
    "2021-05-28", "2021-05-31", "2021-06-03", "2021-07-01", "2021-07-02",
    "2021-07-21", "2021-08-31", "2021-09-10", "2021-11-30", "2021-12-01",
    "2021-12-09", "2021-12-10", "2022-03-29", "2024-11-25", "2025-07-22",
    "2025-09-04", "2025-09-09", "2025-11-14", "2026-07-02",
}


def symbol6(value: object) -> str:
    return str(value or "").strip()[:6]


def parse_top_codes(raw: str, sep: str = ",") -> list[str]:
    if not isinstance(raw, str) or not raw:
        return []
    return [symbol6(item.split(":")[0]) for item in raw.split(sep) if item.strip()]


def parse_score_items(raw: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    if not isinstance(raw, str) or not raw:
        return rows
    for item in raw.split("|"):
        parts = item.split(":")
        if len(parts) >= 6:
            rows.append(
                {
                    "code": symbol6(parts[0]),
                    "score": float(parts[1]),
                    "annualized": float(parts[2]),
                    "r2": float(parts[3]),
                    "price": float(parts[4]),
                    "today_volume": float(parts[5]),
                }
            )
    return rows


def parse_position_symbol(raw: str) -> str:
    if not raw:
        return ""
    first = raw.split("|")[0]
    return symbol6(first.split(":")[0])


def read_zip_log(path: Path) -> str:
    with zipfile.ZipFile(path) as zf:
        name = zf.namelist()[0]
        return zf.read(name).decode("utf-8", errors="ignore")


def parse_log_text(text: str, platform: str) -> dict[str, pd.DataFrame | dict[str, object]]:
    rows: dict[str, list[dict[str, object]]] = {
        "signals": [],
        "executes": [],
        "morning": [],
        "score_detail": [],
        "threshold_detail": [],
        "pool_filter": [],
        "order_plan": [],
        "position": [],
        "close": [],
        "order_fail": [],
    }
    counts = {
        "line_count": 0,
        "warnings": 0,
        "errors": 0,
        "version_v7": False,
        "version_lines": [],
    }
    for line in text.splitlines():
        counts["line_count"] += 1
        dt = DATE_TIME_RE.search(line)
        log_date = dt.group("date") if dt else None
        log_time = dt.group("time") if dt else None
        if "WARN" in line or "WARNING" in line:
            counts["warnings"] += 1
        if "ERROR" in line or "璁㈠崟濮旀墭澶辫触" in line:
            counts["errors"] += 1
        if "WUFU_THS_FAST_" in line or "WUFU_JQ_FIXED_POOL_" in line:
            counts["version_lines"].append(line.strip())
            if "_V7" in line:
                counts["version_v7"] = True
        if "WUFU_SIGNAL" in line:
            m = SIGNAL_RE.search(line)
            if m:
                rows["signals"].append({"date": m.group("date"), "time": log_time, "target": symbol6(m.group("target")), "top10": parse_top_codes(m.group("top10")), "top10_raw": m.group("top10")})
        if "WUFU_EXECUTE" in line:
            m = EXECUTE_RE.search(line)
            if m:
                rows["executes"].append({"date": m.group("date"), "time": log_time, "target": symbol6(m.group("target"))})
        if "morning date=" in line:
            m = MORNING_RE.search(line)
            if m:
                rows["morning"].append({"date": m.group("date"), "time": log_time, "weak": m.group("weak") == "True", "threshold": float(m.group("threshold")), "pool": int(m.group("pool"))})
        if "WUFU_MORNING" in line:
            m = JQ_MORNING_RE.search(line)
            if m and log_date:
                rows["morning"].append({"date": log_date, "time": log_time, "weak": m.group("weak") == "True", "threshold": float(m.group("threshold")), "pool": int(m.group("pool"))})
        if "WUFU_SCORE_DETAIL" in line:
            m = SCORE_DETAIL_RE.search(line)
            if m:
                rows["score_detail"].append({"date": m.group("date"), "weak": m.group("weak") == "True", "pool": int(m.group("pool")), "passed": int(m.group("passed")), "target": symbol6(m.group("target")), "top10": parse_top_codes(m.group("top10"), "|"), "items": parse_score_items(m.group("top10")), "top10_raw": m.group("top10")})
        if "WUFU_THRESHOLD_DETAIL" in line:
            m = THRESHOLD_RE.search(line)
            if m:
                rows["threshold_detail"].append({"date": m.group("date"), "universe": int(m.group("universe")), "valid": int(m.group("valid")), "threshold": float(m.group("threshold")), "source": m.group("source")})
        if "WUFU_POOL_FILTER" in line:
            m = POOL_RE.search(line)
            if m:
                rows["pool_filter"].append({"date": m.group("date"), "input": int(m.group("input")), "output": int(m.group("output")), "threshold": float(m.group("threshold")), "selected": parse_top_codes(m.group("selected"))})
        if "WUFU_ORDER_PLAN" in line:
            m = ORDER_PLAN_RE.search(line)
            if m:
                rows["order_plan"].append({"date": m.group("date"), "code": symbol6(m.group("code")), "account_value": float(m.group("account_value")), "buffered_value": float(m.group("buffered_value")), "price": float(m.group("price")), "shares": int(m.group("shares")), "order_value": float(m.group("order_value"))})
        if "WUFU_POSITION" in line:
            m = POSITION_RE.search(line)
            if m:
                rows["position"].append({"date": m.group("date"), "time": log_time, "value": float(m.group("value")), "positions": m.group("positions"), "symbol": parse_position_symbol(m.group("positions"))})
        if "close value=" in line:
            m = THS_CLOSE_RE.search(line)
            if m and log_date:
                rows["close"].append({"date": log_date, "time": log_time, "value": float(m.group("value")), "weak": m.group("weak") == "True", "pool": int(m.group("pool")), "target": symbol6(m.group("target"))})
        if "WUFU_ORDER_FAIL" in line or "璁㈠崟濮旀墭澶辫触" in line:
            rows["order_fail"].append({"date": log_date, "time": log_time, "line": line.strip()})
    out: dict[str, pd.DataFrame | dict[str, object]] = {"counts": counts}
    for name, items in rows.items():
        frame = pd.DataFrame(items)
        if not frame.empty and "date" in frame.columns:
            frame["date"] = pd.to_datetime(frame["date"]).dt.date
        out[name] = frame
    return out


def compare(ths: dict[str, object], jq: dict[str, object], prefix: Path) -> dict[str, object]:
    prefix.parent.mkdir(parents=True, exist_ok=True)
    for platform, parsed in (("ths", ths), ("jq", jq)):
        for name, frame in parsed.items():
            if isinstance(frame, pd.DataFrame):
                frame.to_csv(prefix.with_name(f"{prefix.name}_{platform}_{name}.csv"), index=False, encoding="utf-8-sig")

    signal = _merge_target(ths["signals"], jq["signals"], "signal")
    morning = _merge_morning(ths["morning"], jq["morning"])
    score = _merge_score(ths["score_detail"], jq["score_detail"])
    order = _merge_order(ths["order_plan"], jq["order_plan"])
    position = _merge_position(ths["position"], jq["position"])
    pool = _merge_pool(ths["pool_filter"], jq["pool_filter"])
    threshold = _merge_threshold(ths["threshold_detail"], jq["threshold_detail"])

    for name, frame in (("signal_compare", signal), ("morning_compare", morning), ("score_compare", score), ("order_plan_compare", order), ("position_compare", position), ("pool_filter_compare", pool), ("threshold_compare", threshold)):
        frame.to_csv(prefix.with_name(f"{prefix.name}_{name}.csv"), index=False, encoding="utf-8-sig")

    summary = {
        "ths_counts": ths["counts"],
        "jq_counts": jq["counts"],
        "ths_rows": _row_counts(ths),
        "jq_rows": _row_counts(jq),
        "signal": _signal_summary(signal),
        "morning": _morning_summary(morning),
        "score": _score_summary(score, ths["score_detail"], jq["score_detail"]),
        "order_plan": _order_summary(order),
        "position": _position_summary(position),
        "pool_filter": _pool_summary(pool),
        "threshold": _threshold_summary(threshold),
        "ths_equity": _equity_summary(ths["position"]),
        "jq_equity": _equity_summary(jq["position"]),
        "order_fail": {"ths": int(len(ths["order_fail"])), "jq": int(len(jq["order_fail"]))},
    }
    prefix.with_name(f"{prefix.name}_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def _row_counts(parsed: dict[str, object]) -> dict[str, int]:
    return {name: int(len(value)) for name, value in parsed.items() if isinstance(value, pd.DataFrame)}


def _merge_target(ths: pd.DataFrame, jq: pd.DataFrame, name: str) -> pd.DataFrame:
    if ths.empty or jq.empty:
        return pd.DataFrame()
    left = ths[["date", "time", "target", "top10"]].rename(columns={"time": "ths_time", "target": "ths_target", "top10": "ths_top10"})
    right = jq[["date", "time", "target", "top10"]].rename(columns={"time": "jq_time", "target": "jq_target", "top10": "jq_top10"})
    rows = left.merge(right, on="date", how="inner")
    rows[f"{name}_target_match"] = rows["ths_target"] == rows["jq_target"]
    rows["top1_match"] = rows.apply(lambda r: (r["ths_top10"][0] if r["ths_top10"] else None) == (r["jq_top10"][0] if r["jq_top10"] else None), axis=1)
    rows["top10_overlap"] = rows.apply(lambda r: len(set(r["ths_top10"]).intersection(set(r["jq_top10"]))), axis=1)
    return rows


def _merge_morning(ths: pd.DataFrame, jq: pd.DataFrame) -> pd.DataFrame:
    if ths.empty or jq.empty:
        return pd.DataFrame()
    rows = ths.rename(columns={"time": "ths_time", "weak": "ths_weak", "threshold": "ths_threshold", "pool": "ths_pool"}).merge(
        jq.rename(columns={"time": "jq_time", "weak": "jq_weak", "threshold": "jq_threshold", "pool": "jq_pool"}),
        on="date",
        how="inner",
    )
    rows["weak_match"] = rows["ths_weak"] == rows["jq_weak"]
    rows["threshold_ratio"] = rows["ths_threshold"] / rows["jq_threshold"]
    rows["pool_diff"] = rows["ths_pool"] - rows["jq_pool"]
    return rows


def _merge_score(ths: pd.DataFrame, jq: pd.DataFrame) -> pd.DataFrame:
    if ths.empty or jq.empty:
        return pd.DataFrame()
    rows = ths[["date", "weak", "pool", "passed", "target", "top10", "items"]].rename(columns={"weak": "ths_weak", "pool": "ths_pool", "passed": "ths_passed", "target": "ths_target", "top10": "ths_top10", "items": "ths_items"}).merge(
        jq[["date", "weak", "pool", "passed", "target", "top10", "items"]].rename(columns={"weak": "jq_weak", "pool": "jq_pool", "passed": "jq_passed", "target": "jq_target", "top10": "jq_top10", "items": "jq_items"}),
        on="date",
        how="inner",
    )
    rows["target_match"] = rows["ths_target"] == rows["jq_target"]
    rows["top10_overlap"] = rows.apply(lambda r: len(set(r["ths_top10"]).intersection(set(r["jq_top10"]))), axis=1)
    rows["passed_diff"] = rows["ths_passed"] - rows["jq_passed"]
    rows["top1_match"] = rows.apply(lambda r: (r["ths_top10"][0] if r["ths_top10"] else None) == (r["jq_top10"][0] if r["jq_top10"] else None), axis=1)
    return rows


def _merge_order(ths: pd.DataFrame, jq: pd.DataFrame) -> pd.DataFrame:
    if ths.empty or jq.empty:
        return pd.DataFrame()
    rows = ths.rename(columns={c: f"ths_{c}" for c in ths.columns if c != "date"}).merge(
        jq.rename(columns={c: f"jq_{c}" for c in jq.columns if c != "date"}),
        on="date",
        how="inner",
    )
    rows["code_match"] = rows["ths_code"] == rows["jq_code"]
    rows["price_diff"] = rows["ths_price"] - rows["jq_price"]
    rows["shares_diff"] = rows["ths_shares"] - rows["jq_shares"]
    rows["order_value_diff"] = rows["ths_order_value"] - rows["jq_order_value"]
    rows["account_value_ratio"] = rows["ths_account_value"] / rows["jq_account_value"]
    return rows


def _merge_position(ths: pd.DataFrame, jq: pd.DataFrame) -> pd.DataFrame:
    if ths.empty or jq.empty:
        return pd.DataFrame()
    rows = ths.rename(columns={c: f"ths_{c}" for c in ths.columns if c != "date"}).merge(
        jq.rename(columns={c: f"jq_{c}" for c in jq.columns if c != "date"}),
        on="date",
        how="inner",
    )
    rows["symbol_match"] = rows["ths_symbol"] == rows["jq_symbol"]
    rows["value_diff"] = rows["ths_value"] - rows["jq_value"]
    rows["value_ratio"] = rows["ths_value"] / rows["jq_value"]
    return rows


def _merge_pool(ths: pd.DataFrame, jq: pd.DataFrame) -> pd.DataFrame:
    if ths.empty or jq.empty:
        return pd.DataFrame()
    rows = ths.rename(columns={c: f"ths_{c}" for c in ths.columns if c != "date"}).merge(
        jq.rename(columns={c: f"jq_{c}" for c in jq.columns if c != "date"}),
        on="date",
        how="inner",
    )
    rows["output_diff"] = rows["ths_output"] - rows["jq_output"]
    rows["selected_overlap"] = rows.apply(lambda r: len(set(r["ths_selected"]).intersection(set(r["jq_selected"]))), axis=1)
    return rows


def _merge_threshold(ths: pd.DataFrame, jq: pd.DataFrame) -> pd.DataFrame:
    if ths.empty or jq.empty:
        return pd.DataFrame()
    rows = ths.rename(columns={c: f"ths_{c}" for c in ths.columns if c != "date"}).merge(
        jq.rename(columns={c: f"jq_{c}" for c in jq.columns if c != "date"}),
        on="date",
        how="inner",
    )
    rows["threshold_ratio"] = rows["ths_threshold"] / rows["jq_threshold"]
    rows["valid_diff"] = rows["ths_valid"] - rows["jq_valid"]
    return rows


def _signal_summary(frame: pd.DataFrame) -> dict[str, object]:
    if frame.empty:
        return {"days": 0}
    return {
        "days": int(len(frame)),
        "target_match_days": int(frame["signal_target_match"].sum()),
        "target_match_rate": float(frame["signal_target_match"].mean()),
        "top1_match_rate": float(frame["top1_match"].mean()),
        "top10_overlap_mean": float(frame["top10_overlap"].mean()),
        "mismatch_dates": [str(x) for x in frame.loc[~frame["signal_target_match"], "date"].head(40).tolist()],
    }


def _morning_summary(frame: pd.DataFrame) -> dict[str, object]:
    if frame.empty:
        return {"days": 0}
    return {
        "days": int(len(frame)),
        "weak_match_days": int(frame["weak_match"].sum()),
        "weak_match_rate": float(frame["weak_match"].mean()),
        "threshold_ratio_median": float(frame["threshold_ratio"].median()),
        "pool_diff_median": float(frame["pool_diff"].median()),
    }


def _score_summary(frame: pd.DataFrame, ths_score: pd.DataFrame, jq_score: pd.DataFrame) -> dict[str, object]:
    ths_dates = {str(x) for x in ths_score["date"].tolist()} if not ths_score.empty else set()
    jq_dates = {str(x) for x in jq_score["date"].tolist()} if not jq_score.empty else set()
    out = {
        "ths_rows": int(len(ths_score)),
        "jq_rows": int(len(jq_score)),
        "missing_in_ths": sorted(jq_dates - ths_dates),
        "missing_in_jq": sorted(ths_dates - jq_dates),
        "diagnostic_dates_covered_ths": len(DIAGNOSTIC_DATES.intersection(ths_dates)),
        "diagnostic_dates_covered_jq": len(DIAGNOSTIC_DATES.intersection(jq_dates)),
    }
    if not frame.empty:
        out.update(
            {
                "matched_days": int(len(frame)),
                "target_match_rate": float(frame["target_match"].mean()),
                "top1_match_rate": float(frame["top1_match"].mean()),
                "top10_overlap_mean": float(frame["top10_overlap"].mean()),
                "passed_diff_median": float(frame["passed_diff"].median()),
                "mismatch_dates": [str(x) for x in frame.loc[~frame["target_match"], "date"].tolist()],
            }
        )
    return out


def _order_summary(frame: pd.DataFrame) -> dict[str, object]:
    if frame.empty:
        return {"days": 0}
    matched = frame[frame["code_match"]]
    return {
        "days": int(len(frame)),
        "code_match_rate": float(frame["code_match"].mean()),
        "price_abs_diff_max": float(frame["price_diff"].abs().max()),
        "shares_abs_diff_median": float(frame["shares_diff"].abs().median()),
        "shares_abs_diff_p95": float(frame["shares_diff"].abs().quantile(0.95)),
        "order_value_abs_diff_median": float(frame["order_value_diff"].abs().median()),
        "account_value_ratio_median": float(frame["account_value_ratio"].median()),
        "same_code_days": int(len(matched)),
    }


def _position_summary(frame: pd.DataFrame) -> dict[str, object]:
    if frame.empty:
        return {"days": 0}
    return {
        "days": int(len(frame)),
        "symbol_match_rate": float(frame["symbol_match"].mean()),
        "value_ratio_median": float(frame["value_ratio"].median()),
        "value_abs_diff_median": float(frame["value_diff"].abs().median()),
        "final_ths_value": float(frame.sort_values("date")["ths_value"].iloc[-1]),
        "final_jq_value": float(frame.sort_values("date")["jq_value"].iloc[-1]),
        "final_value_ratio": float(frame.sort_values("date")["ths_value"].iloc[-1] / frame.sort_values("date")["jq_value"].iloc[-1]),
    }


def _pool_summary(frame: pd.DataFrame) -> dict[str, object]:
    if frame.empty:
        return {"days": 0}
    return {
        "days": int(len(frame)),
        "output_diff_median": float(frame["output_diff"].median()),
        "output_diff_abs_max": float(frame["output_diff"].abs().max()),
        "selected_overlap_median": float(frame["selected_overlap"].median()),
    }


def _threshold_summary(frame: pd.DataFrame) -> dict[str, object]:
    if frame.empty:
        return {"days": 0}
    return {
        "days": int(len(frame)),
        "threshold_ratio_median": float(frame["threshold_ratio"].median()),
        "threshold_ratio_min": float(frame["threshold_ratio"].min()),
        "threshold_ratio_max": float(frame["threshold_ratio"].max()),
        "valid_diff_median": float(frame["valid_diff"].median()),
    }


def _equity_summary(frame: pd.DataFrame) -> dict[str, object]:
    if frame.empty:
        return {"days": 0}
    rows = frame.sort_values("date")
    equity = rows["value"].astype(float)
    drawdown = equity / equity.cummax() - 1.0
    return {
        "days": int(len(rows)),
        "first_date": str(rows["date"].iloc[0]),
        "last_date": str(rows["date"].iloc[-1]),
        "first_value": float(equity.iloc[0]),
        "final_value": float(equity.iloc[-1]),
        "total_return_from_first_position": float(equity.iloc[-1] / equity.iloc[0] - 1.0),
        "max_drawdown": float(drawdown.min()),
    }


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    ths_text = Path(r"C:\Users\16052\Desktop\outlog.txt").read_text(encoding="utf-8", errors="ignore")
    jq_text = read_zip_log(Path(r"C:\Users\16052\Desktop\log.zip"))
    prefix = root / "reports" / "ths_jq_fast_v7_acceptance"
    summary = compare(parse_log_text(ths_text, "ths"), parse_log_text(jq_text, "jq"), prefix)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
