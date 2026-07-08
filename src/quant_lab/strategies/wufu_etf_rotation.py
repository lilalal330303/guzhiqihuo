from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
import math

import numpy as np
import pandas as pd


DEFAULT_GLOBAL_ETF_POOL = [
    "518880",
    "501018",
    "161226",
    "159985",
    "159980",
    "513310",
    "159518",
    "159509",
    "513100",
    "513520",
    "513500",
    "159502",
    "513400",
    "513030",
    "513290",
    "520830",
    "159529",
]

DEFAULT_CHINA_ETF_POOL = [
    "513090",
    "513120",
    "513180",
    "513330",
    "513750",
    "159892",
    "513190",
    "159605",
    "513630",
    "159323",
    "510900",
    "513920",
    "513970",
    "511380",
    "512050",
    "510500",
    "159915",
    "510300",
    "512100",
    "159949",
    "588080",
    "159967",
    "588220",
    "563300",
    "510760",
    "588200",
    "515880",
    "159981",
    "512880",
    "513350",
    "159326",
    "159516",
    "159206",
    "512480",
    "159363",
    "159870",
    "512400",
    "159755",
    "588170",
    "159992",
    "159995",
    "512890",
    "515220",
    "159566",
    "159819",
    "512800",
    "512690",
    "515050",
    "562500",
    "512170",
    "517520",
    "159869",
    "512070",
    "159611",
    "562800",
    "515120",
    "512010",
    "510880",
    "515790",
    "515980",
    "512660",
    "159928",
    "512710",
    "560860",
    "515030",
    "159766",
    "159218",
    "159852",
    "516160",
    "516150",
    "159227",
    "159583",
    "588790",
    "159865",
    "512980",
    "159851",
    "561360",
    "561980",
    "562590",
    "512200",
    "159732",
    "159667",
    "516510",
    "159840",
    "159998",
    "159825",
    "512670",
    "159883",
    "515210",
    "515400",
    "159256",
    "561330",
    "515170",
    "159638",
    "516520",
    "513360",
    "516190",
]

DEFAULT_QIXING_ETF_POOL = [
    "518880",
    "159980",
    "159985",
    "501018",
    "161226",
    "159981",
    "513100",
    "159509",
    "513290",
    "513500",
    "159529",
    "513400",
    "513520",
    "513030",
    "513080",
    "513310",
    "513730",
    "159792",
    "513130",
    "513050",
    "159920",
    "513690",
    "510300",
    "510500",
    "510050",
    "510210",
    "159915",
    "588080",
    "512100",
    "563360",
    "563300",
    "512890",
    "159967",
    "512040",
    "159201",
    "511380",
    "511010",
    "511220",
]


@dataclass(frozen=True)
class MomentumScore:
    momentum_score: float
    annualized_return: float
    r_squared: float


@dataclass(frozen=True)
class WufuEtfRotationConfig:
    etf_pool: list[str] = field(default_factory=lambda: DEFAULT_GLOBAL_ETF_POOL + DEFAULT_CHINA_ETF_POOL)
    global_etf_pool: list[str] = field(default_factory=lambda: DEFAULT_GLOBAL_ETF_POOL.copy())
    dynamic_etf_pool: list[str] = field(default_factory=list)
    defensive_etf: str | None = "511880"
    holdings_num: int = 1
    lookback_days: int = 25
    min_score_threshold: float = 0.0
    max_score_threshold: float = 5.0
    score_threshold_ratio: float = 0.9
    enable_r2_filter: bool = True
    r2_threshold: float = 0.4
    enable_ma_filter: bool = True
    ma_lookback: int = 10
    ma_threshold: float = 1.0
    enable_volume_check: bool = True
    volume_lookback: int = 5
    volume_threshold: float = 1.8
    enable_loss_filter: bool = True
    loss: float = 0.97
    weak_period_ma_lookback: int = 10
    max_weak_days: int = 20


@dataclass(frozen=True)
class QixingEnhancementConfig:
    enabled: bool = False
    pool: list[str] = field(default_factory=lambda: DEFAULT_QIXING_ETF_POOL.copy())
    preferred_pool_bonus: float = 0.0
    independent_slot_enabled: bool = False
    wufu_slot_weight: float = 0.5
    qixing_slot_weight: float = 0.5
    short_lookback_days: int = 10
    short_momentum_min: float | None = None
    liquidity_lookback_days: int = 20
    liquidity_threshold: float | None = None
    volume_lookback_days: int = 5
    volume_threshold: float | None = None
    premium_threshold: float | None = None


@dataclass(frozen=True)
class FusionEtfRotationConfig:
    wufu: WufuEtfRotationConfig = field(default_factory=WufuEtfRotationConfig)
    qixing: QixingEnhancementConfig = field(default_factory=QixingEnhancementConfig)


FUND_COMPANIES = ['\u56fd\u6d77\u5bcc\u5170\u514b\u6797',
 '\u4ea4\u94f6\u65bd\u7f57\u5fb7',
 '\u5149\u5927\u4fdd\u5fb7\u4fe1',
 '\u5706\u4fe1\u6c38\u4e30',
 '\u5174\u8bc1\u5168\u7403',
 '\u534e\u6da6\u5143\u5927',
 '\u957f\u6c5f\u8bc1\u5238',
 '\u521b\u91d1\u5408\u4fe1',
 '\u6c11\u751f\u52a0\u94f6',
 '\u897f\u90e8\u5229\u5f97',
 '\u4fe1\u8fbe\u6fb3\u4e9a',
 '\u534e\u6cf0\u67cf\u745e',
 '\u4e2d\u4fe1\u4fdd\u8bda',
 '\u519c\u94f6\u6c47\u7406',
 '\u4e2d\u94f6\u8bc1\u5238',
 '\u6d59\u5546\u8bc1\u5238',
 '\u6d66\u94f6\u5b89\u76db',
 '\u4e2d\u4fe1\u5efa\u6295',
 '\u524d\u6d77\u5f00\u6e90',
 '\u6cf0\u8fbe\u5b8f\u5229',
 '\u6c47\u4e30\u664b\u4fe1',
 '\u6052\u751f\u524d\u6d77',
 '\u65b9\u6b63\u5bcc\u90a6',
 '\u4e2d\u94f6\u56fd\u9645',
 '\u666f\u987a\u957f\u57ce',
 '\u56fd\u6295\u745e\u94f6',
 '\u7533\u4e07\u83f1\u4fe1',
 '\u56fd\u8054\u5b89',
 '\u6d77\u5bcc\u901a',
 '\u4e1c\u65b9\u7ea2',
 '\u6c47\u6dfb\u5bcc',
 '\u6613\u65b9\u8fbe',
 '\u534e\u5b89',
 '\u5e7f\u53d1',
 '\u5174\u5168',
 '\u62db\u5546',
 '\u534e\u5b9d',
 '\u957f\u76db',
 '\u56fd\u8054',
 '\u592a\u5e73',
 '\u5efa\u4fe1',
 '\u666f\u987a',
 '\u56fd\u4fe1',
 '\u4e07\u5bb6',
 '\u5609\u5b9e',
 '\u957f\u4fe1',
 '\u6cd3\u5fb7',
 '\u8d22\u901a',
 '\u4e2d\u6b27',
 '\u534e\u590f',
 '\u4e1c\u5434',
 '\u4e2d\u4fe1',
 '\u4e5d\u6cf0',
 '\u5de5\u94f6',
 '\u8bfa\u5fb7',
 '\u91d1\u9e70',
 '\u56fd\u6cf0',
 '\u519c\u94f6',
 '\u4e2d\u94f6',
 '\u4e2d\u91d1',
 '\u4e2d\u5e9a',
 '\u56fd\u91d1',
 '\u4e2d\u52a0',
 '\u5929\u5f18',
 '\u535a\u65f6',
 '\u957f\u5b89',
 '\u4e2d\u90ae',
 '\u5bcc\u56fd',
 '\u5357\u65b9',
 '\u6c38\u8d62',
 '\u6c47\u5b89',
 '\u6cf0\u5eb7',
 '\u8bfa\u5b89',
 '\u534e\u6cf0',
 '\u94f6\u6cb3',
 '\u4e2d\u822a',
 '\u9e4f\u534e',
 '\u4ea4\u94f6',
 '\u6d59\u5546',
 '\u6469\u6839',
 '\u4e1c\u6d77',
 '\u5174\u94f6',
 '\u957f\u57ce',
 '\u9e4f\u626c',
 '\u94f6\u534e',
 '\u4e2d\u878d',
 '\u5e73\u5b89',
 '\u5927\u6210',
 '\u5fb7\u90a6',
 '\u534e\u5546']

NOISE_WORDS = ['\u6307\u6570ETF',
 '\u4e0a\u5e02\u5f00\u653e\u5f0f',
 'LOF\u57fa\u91d1',
 'ETF\u57fa\u91d1',
 'LOF\u8054\u63a5',
 'ETF\u8054\u63a5',
 '1000',
 '\u8054\u63a5\u57fa\u91d1',
 '9999',
 '2000',
 '\u6307\u6570\u57fa\u91d1',
 '6666',
 '8888',
 '\u6307\u6570A',
 '300',
 'G60',
 '100',
 '500',
 '\u6307\u6570C',
 '\u57fa\u672c\u9762',
 'HGS',
 'ETF',
 'LOF',
 'ZZ',
 '\u592e\u4f01',
 '\u5168\u6307',
 '\u573a\u5916',
 'GT',
 '\u91cf\u5316',
 '\u6307\u57fa',
 '\u6e56\u5317',
 'A\u7c7b',
 '\u56fd\u4f01',
 'TK',
 'BS',
 '\u4e0a\u6d77',
 '\u4ea7\u4e1a',
 '\u8054\u63a5',
 'CS',
 'YH',
 '\u56db\u5ddd',
 '\u6307\u6570',
 '\u667a\u80fd',
 '\u7cbe\u9009',
 'E\u7c7b',
 'WJ',
 'TF',
 'FG',
 '\u6c11\u8425',
 '\u6307\u589e',
 'C\u7c7b',
 '\u6d59\u6c5f',
 '\u57fa\u91d1',
 '\u6c11\u4f01',
 'SG',
 '\u677f\u5757',
 '\u573a\u5185',
 '\u589e\u5f3a',
 '30',
 'AH',
 'GF',
 '50',
 'ZS',
 '\u4f4e\u6ce2',
 '\u7b56\u7565',
 '\u4e3b\u9898',
 'DB',
 '\u9f99\u5934',
 'SZ',
 'B',
 '\u9ec4',
 '\u65b0',
 'C',
 '\u5927',
 'E']

SPECIAL_GROUPS = [{'name': '\u9999\u6e2f\u7ec4',
  'keywords': ['HS\u79d1\u6280', '\u6e2f\u80a1\u901a', 'HKC', 'HGS', '\u6052\u751f', '\u6052\u6307', '\u6e2f\u80a1', 'H\u80a1', '\u9999\u6e2f', 'HK', '\u4e2d\u6982', '\u6e2f', 'H'],
  'remove_words': ['\u6e2f\u80a1\u901a', 'HKC', 'HGS', '\u6052\u751f', '\u6052\u6307', '\u6e2f\u80a1', 'H\u80a1', '\u9999\u6e2f', 'HK', '\u4e2d\u6982', 'HS', '\u6e2f', 'H']},
 {'name': '\u79d1\u521b\u7ec4',
  'keywords': ['\u79d1\u521b\u521b\u4e1a', '\u79d1\u521b\u677f', 'K C', '\u79d1\u521b', '\u79d1\u7efc', 'KC', '\u53cc\u521b', '\u521b\u521b'],
  'remove_words': ['\u79d1\u521b\u521b\u4e1a',
                   '\u79d1\u521b\u677f',
                   'K C',
                   'AAA',
                   '\u79d1\u521b',
                   '\u79d1\u7efc',
                   'KC',
                   '\u53cc\u521b',
                   '\u521b\u521b',
                   '\u503a\u5238',
                   '\u503a\u6c47',
                   '\u503a\u6307',
                   '\u503a\u6caa',
                   '\u503a\u6613',
                   '\u503a\u57fa',
                   '\u503a\u5174',
                   '\u503a\u6469',
                   '\u503a']},
 {'name': '\u7f8e\u6307\u7ec4', 'keywords': ['\u7eb3\u65af\u8fbe\u514b', '\u6807\u666e', '\u7eb3\u6307'], 'remove_words': ['\u7eb3\u65af\u8fbe\u514b', '\u6807\u666e', '\u7eb3\u6307']},
 {'name': '\u521b\u4e1a\u7ec4', 'keywords': ['\u521b\u4e1a\u677f', '\u521b\u6210\u957f', '\u521b\u4e1a', '\u521b\u677f'], 'remove_words': ['\u521b\u4e1a\u677f', '\u521b\u6210\u957f', '\u521b\u4e1a', '\u521b\u677f']}]

EXCLUDE_DYNAMIC_KEYWORDS = ['300\u73b0\u91d1\u6d41',
 '800\u73b0\u91d1\u6d41',
 '\u73b0\u91d1800',
 '\u79d1\u521bAAA',
 '500\u73b0\u91d1',
 '800\u73b0\u91d1',
 '\u81ea\u7531\u73b0\u91d1\u6d41',
 '\u73b0\u91d1\u6d41TF',
 '\u73b0\u91d1\u5168\u6307',
 '\u73b0\u91d1\u6307\u6570',
 '1000',
 '\u73b0\u91d1\u81ea\u7531',
 '\u4e2d\u94f6\u73b0\u91d1',
 'A500',
 'MSCI',
 '\u73b0\u91d1\u6d41\u5168',
 '\u73b0\u91d1\u6d41\u57fa',
 '2000',
 '\u57fa\u51c6\u56fd\u503a',
 '\u6caa\u516c\u53f8\u503a',
 '\u73b0\u91d1\u6d41E',
 '\u6df1100',
 'A100',
 '\u5168\u6307\u73b0\u91d1',
 '\u516c\u53f8\u503a',
 '800',
 '300',
 '\u4f01\u4e1a\u503a',
 '\u653f\u91d1\u503a',
 '200',
 '\u4fe1\u7528\u503a',
 '\u5229\u7387\u503a',
 'A50',
 '500',
 '180',
 '\u65b0\u7efc\u503a',
 'ESG',
 '\u73b0\u91d1\u6d41',
 '\u56fd\u5f00\u503a',
 '\u57ce\u6295\u503a',
 '\u7f8e\u5143\u503a',
 '\u53ef\u8f6c\u503a',
 '\u79d1\u521b\u503a',
 '100',
 '\u6caa\u6df1',
 '\u8d27\u5e01',
 '\u56fd\u503a',
 'MS',
 '\u8f6c\u503a',
 '\u79d1\u503a',
 '\u53cc\u503a',
 '\u57ce\u6295',
 '\u6df1\u6210',
 '\u4e2d\u8bc1',
 '\u6df1\u8bc1',
 '\u5feb\u94b1',
 '\u5feb\u7ebf',
 '\u4e0a\u8bc1',
 '30',
 '\u77ed\u878d',
 '50',
 '\u73b0\u91d1',
 '\u5730\u503a',
 '\u503a']

def build_dynamic_etf_pool(
    etf_metadata: pd.DataFrame,
    prices: pd.DataFrame,
    end_date: str,
    liquidity_threshold: float,
    top_n: int = 100,
    lookback_days: int = 3,
) -> list[str]:
    required_meta = {"symbol", "name"}
    missing_meta = required_meta.difference(etf_metadata.columns)
    if missing_meta:
        raise ValueError(f"etf_metadata missing required columns: {sorted(missing_meta)}")
    required_prices = {"symbol", "trade_date", "amount"}
    missing_prices = required_prices.difference(prices.columns)
    if missing_prices:
        raise ValueError(f"prices missing required columns: {sorted(missing_prices)}")

    meta = etf_metadata.copy()
    meta["symbol"] = meta["symbol"].astype(str)
    meta["industry_key"] = meta["name"].map(_dynamic_industry_key)
    meta = meta[meta["industry_key"] != ""]

    price_rows = prices.copy()
    price_rows["trade_date"] = pd.to_datetime(price_rows["trade_date"])
    end_ts = pd.Timestamp(end_date)
    trade_dates = sorted(price_rows.loc[price_rows["trade_date"] <= end_ts, "trade_date"].drop_duplicates())
    selected_dates = trade_dates[-lookback_days:]
    if not selected_dates:
        return []
    recent = price_rows[price_rows["trade_date"].isin(selected_dates)]
    avg_amount = recent.groupby("symbol")["amount"].mean()
    candidates = meta.join(avg_amount.rename("avg_amount"), on="symbol").dropna(subset=["avg_amount"])
    candidates = candidates[candidates["avg_amount"] > liquidity_threshold]
    if candidates.empty:
        return []

    best_per_group = (
        candidates.sort_values("avg_amount", ascending=False)
        .drop_duplicates("industry_key", keep="first")
        .sort_values("avg_amount", ascending=False)
    )
    return best_per_group["symbol"].head(top_n).tolist()


def dynamic_pool_snapshots(
    etf_metadata: pd.DataFrame,
    prices: pd.DataFrame,
    liquidity_threshold: float | pd.DataFrame | dict[pd.Timestamp | str, float],
    top_n: int = 100,
    lookback_days: int = 3,
) -> pd.DataFrame:
    price_rows = prices.copy()
    price_rows["trade_date"] = pd.to_datetime(price_rows["trade_date"])
    price_rows["symbol"] = price_rows["symbol"].astype(str)
    price_rows["amount"] = pd.to_numeric(price_rows["amount"], errors="coerce")
    meta = etf_metadata.copy()
    meta["symbol"] = meta["symbol"].astype(str)
    meta["industry_key"] = meta["name"].map(_dynamic_industry_key)
    meta = meta[meta["industry_key"] != ""]
    if meta.empty or price_rows.empty:
        return pd.DataFrame(columns=["trade_date", "symbol", "rank", "industry_key", "avg_amount"])

    amount_pivot = (
        price_rows.pivot_table(index="trade_date", columns="symbol", values="amount", aggfunc="mean")
        .sort_index()
        .rolling(window=lookback_days, min_periods=1)
        .mean()
    )
    avg_rows = amount_pivot.stack().rename("avg_amount").reset_index()
    thresholds = _liquidity_threshold_by_date(liquidity_threshold)
    avg_rows["liquidity_threshold"] = avg_rows["trade_date"].map(lambda value: _threshold_for_date(thresholds, value))
    candidates = avg_rows.merge(meta[["symbol", "industry_key"]], on="symbol", how="inner")
    candidates = candidates[candidates["avg_amount"] > candidates["liquidity_threshold"]]
    if candidates.empty:
        return pd.DataFrame(columns=["trade_date", "symbol", "rank", "industry_key", "avg_amount"])

    best_per_group = (
        candidates.sort_values(["trade_date", "avg_amount"], ascending=[True, False])
        .drop_duplicates(["trade_date", "industry_key"], keep="first")
        .sort_values(["trade_date", "avg_amount"], ascending=[True, False])
    )
    best_per_group["rank"] = best_per_group.groupby("trade_date").cumcount() + 1
    snapshots = best_per_group[best_per_group["rank"] <= top_n][
        ["trade_date", "symbol", "rank", "industry_key", "avg_amount"]
    ].copy()
    return snapshots.reset_index(drop=True)


def calculate_joinquant_liquidity_thresholds(
    prices: pd.DataFrame,
    trade_dates: list[pd.Timestamp] | pd.Series | None = None,
    lookback_days: int = 3,
    divisor: float = 20000.0,
    fallback: float = 10_000_000.0,
) -> pd.DataFrame:
    """Replicate JoinQuant's global ETF money threshold for each decision date.

    JoinQuant computes the threshold in the morning of day T with all ETF
    turnover from the previous three trading days: mean(daily total money) /
    20000. Local bars therefore use dates strictly before the decision date to
    avoid look-ahead.
    """
    required = {"symbol", "trade_date", "amount"}
    missing = required.difference(prices.columns)
    if missing:
        raise ValueError(f"prices missing required columns: {sorted(missing)}")
    if lookback_days <= 0:
        raise ValueError("lookback_days must be positive")
    if divisor <= 0:
        raise ValueError("divisor must be positive")

    rows = prices.copy()
    rows["trade_date"] = pd.to_datetime(rows["trade_date"]).dt.normalize()
    rows["amount"] = pd.to_numeric(rows["amount"], errors="coerce")
    daily_total = rows.dropna(subset=["amount"]).groupby("trade_date")["amount"].sum().sort_index()
    decision_dates = (
        sorted(pd.to_datetime(pd.Series(trade_dates)).dt.normalize().drop_duplicates())
        if trade_dates is not None
        else sorted(daily_total.index)
    )

    output: list[dict[str, object]] = []
    for trade_date in decision_dates:
        previous_totals = daily_total[daily_total.index < trade_date].tail(lookback_days)
        if len(previous_totals) < lookback_days:
            threshold = fallback
            source = "fallback_insufficient_history"
        else:
            threshold = float(previous_totals.mean() / divisor)
            source = "joinquant_formula"
        output.append(
            {
                "trade_date": trade_date,
                "liquidity_threshold": float(threshold),
                "source": source,
                "lookback_days": int(len(previous_totals)),
                "daily_total_mean": float(previous_totals.mean()) if len(previous_totals) else 0.0,
            }
        )
    return pd.DataFrame(output)


def _liquidity_threshold_by_date(
    liquidity_threshold: float | pd.DataFrame | dict[pd.Timestamp | str, float],
) -> dict[pd.Timestamp, float] | float:
    if isinstance(liquidity_threshold, pd.DataFrame):
        required = {"trade_date", "liquidity_threshold"}
        missing = required.difference(liquidity_threshold.columns)
        if missing:
            raise ValueError(f"liquidity threshold frame missing required columns: {sorted(missing)}")
        rows = liquidity_threshold.copy()
        rows["trade_date"] = pd.to_datetime(rows["trade_date"]).dt.normalize()
        return dict(zip(rows["trade_date"], rows["liquidity_threshold"].astype(float), strict=False))
    if isinstance(liquidity_threshold, dict):
        return {pd.Timestamp(key).normalize(): float(value) for key, value in liquidity_threshold.items()}
    return float(liquidity_threshold)


def _threshold_for_date(thresholds: dict[pd.Timestamp, float] | float, trade_date: pd.Timestamp) -> float:
    if isinstance(thresholds, float):
        return thresholds
    key = pd.Timestamp(trade_date).normalize()
    if key in thresholds:
        return float(thresholds[key])
    previous = [date for date in thresholds if date <= key]
    if not previous:
        return 10_000_000.0
    return float(thresholds[max(previous)])


def _dynamic_pool_snapshot_for_date(
    etf_metadata: pd.DataFrame,
    prices: pd.DataFrame,
    end_date: pd.Timestamp,
    liquidity_threshold: float,
    top_n: int,
    lookback_days: int,
) -> list[dict[str, object]]:
    meta = etf_metadata.copy()
    meta["symbol"] = meta["symbol"].astype(str)
    meta["industry_key"] = meta["name"].map(_dynamic_industry_key)
    meta = meta[meta["industry_key"] != ""]

    trade_dates = sorted(prices.loc[prices["trade_date"] <= end_date, "trade_date"].drop_duplicates())
    selected_dates = trade_dates[-lookback_days:]
    if not selected_dates:
        return []
    recent = prices[prices["trade_date"].isin(selected_dates)]
    avg_amount = recent.groupby("symbol")["amount"].mean()
    candidates = meta.join(avg_amount.rename("avg_amount"), on="symbol").dropna(subset=["avg_amount"])
    candidates = candidates[candidates["avg_amount"] > liquidity_threshold]
    if candidates.empty:
        return []
    best_per_group = (
        candidates.sort_values("avg_amount", ascending=False)
        .drop_duplicates("industry_key", keep="first")
        .sort_values("avg_amount", ascending=False)
        .head(top_n)
    )
    return [
        {
            "trade_date": end_date,
            "symbol": row.symbol,
            "rank": rank,
            "industry_key": row.industry_key,
            "avg_amount": float(row.avg_amount),
        }
        for rank, row in enumerate(best_per_group.itertuples(index=False), start=1)
    ]


def _dynamic_industry_key(name: str) -> str:
    original = str(name)
    matched_group = _matched_special_group(original)
    cleaned = original
    if any(keyword in cleaned for keyword in EXCLUDE_DYNAMIC_KEYWORDS):
        return ""
    for word in FUND_COMPANIES:
        cleaned = cleaned.replace(word, "")
    if matched_group:
        for word in matched_group["remove_words"]:
            cleaned = cleaned.replace(word, "")
    for word in NOISE_WORDS:
        cleaned = cleaned.replace(word, "")
    cleaned = cleaned.strip()
    industry_key = cleaned[:2] if len(cleaned) >= 2 else cleaned
    if not industry_key:
        return ""
    if matched_group:
        return f"{matched_group['name']}_{industry_key}"
    return industry_key


def _matched_special_group(name: str) -> dict[str, object] | None:
    for group in SPECIAL_GROUPS:
        if any(keyword in name for keyword in group["keywords"]):
            return group
    return None


def generate_a_share_weak_states(
    index_prices: pd.DataFrame,
    ma_lookback: int = 10,
    max_weak_days: int = 20,
    index_symbols: tuple[str, ...] = ("000300", "399101", "399006", "000510"),
) -> pd.DataFrame:
    required = {"symbol", "trade_date", "close"}
    missing = required.difference(index_prices.columns)
    if missing:
        raise ValueError(f"index_prices missing required columns: {sorted(missing)}")

    data = index_prices.copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"])
    data = data[data["symbol"].isin(index_symbols)].sort_values(["trade_date", "symbol"])
    if data.empty:
        return pd.DataFrame(columns=["trade_date", "is_weak", "below_count", "above_count", "weak_days_count"])

    is_weak = False
    weak_start_date: pd.Timestamp | None = None
    rows: list[dict[str, object]] = []
    trade_dates = sorted(data["trade_date"].drop_duplicates())
    for trade_date in trade_dates:
        below_count = 0
        above_count = 0
        for symbol in index_symbols:
            history = data[(data["symbol"] == symbol) & (data["trade_date"] <= trade_date)].sort_values("trade_date")
            if len(history) < ma_lookback:
                continue
            closes = history["close"].astype(float)
            current_price = float(closes.iloc[-1])
            ma_value = float(closes.iloc[-ma_lookback:].mean())
            if current_price > ma_value:
                above_count += 1
            elif current_price < ma_value:
                below_count += 1

        weak_condition_met = below_count >= 3
        exit_condition_met = above_count >= 3
        weak_days_count = 0
        if is_weak and weak_start_date is not None:
            weak_days_count = sum(1 for day in trade_dates if weak_start_date <= day <= trade_date)
        max_days_exceeded = weak_days_count >= max_weak_days

        if is_weak:
            if max_days_exceeded or exit_condition_met:
                is_weak = False
                weak_start_date = None
                weak_days_count = 0
            elif weak_condition_met:
                weak_start_date = trade_date
                weak_days_count = 0
        elif weak_condition_met:
            is_weak = True
            weak_start_date = trade_date
            weak_days_count = 0

        rows.append(
            {
                "trade_date": trade_date,
                "is_weak": bool(is_weak),
                "below_count": below_count,
                "above_count": above_count,
                "weak_days_count": weak_days_count,
            }
        )

    return pd.DataFrame(rows)


def generate_a_share_weak_states_joinquant_style(
    index_prices: pd.DataFrame,
    ma_lookback: int = 10,
    max_weak_days: int = 20,
    index_symbols: tuple[str, ...] = ("000300", "399101", "399006", "000510"),
    signal_lag_days: int = 0,
) -> pd.DataFrame:
    required = {"symbol", "trade_date", "close"}
    missing = required.difference(index_prices.columns)
    if missing:
        raise ValueError(f"index_prices missing required columns: {sorted(missing)}")
    if signal_lag_days < 0:
        raise ValueError("signal_lag_days must be non-negative")

    data = index_prices.copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"])
    data = data[data["symbol"].isin(index_symbols)].sort_values(["trade_date", "symbol"])
    if data.empty:
        return pd.DataFrame(columns=["trade_date", "is_weak", "below_count", "above_count", "weak_days_count", "signal_trade_date"])

    is_weak = False
    weak_start_date: pd.Timestamp | None = None
    rows: list[dict[str, object]] = []
    trade_dates = sorted(data["trade_date"].drop_duplicates())
    for position, trade_date in enumerate(trade_dates):
        signal_position = position - signal_lag_days
        signal_trade_date = trade_dates[signal_position] if signal_position >= 0 else None
        below_count = 0
        above_count = 0
        if signal_trade_date is not None:
            for symbol in index_symbols:
                history = data[(data["symbol"] == symbol) & (data["trade_date"] <= signal_trade_date)].sort_values("trade_date")
                if len(history) < ma_lookback:
                    continue
                closes = history["close"].astype(float)
                current_price = float(closes.iloc[-1])
                ma_value = float(closes.iloc[-ma_lookback:].mean())
                if current_price > ma_value:
                    above_count += 1
                elif current_price < ma_value:
                    below_count += 1

        weak_condition_met = below_count >= 3
        exit_condition_met = above_count >= 3
        weak_days_count = 0
        if is_weak and weak_start_date is not None:
            weak_days_count = sum(1 for day in trade_dates if weak_start_date <= day <= trade_date)
        max_days_exceeded = weak_days_count >= max_weak_days

        if is_weak:
            if max_days_exceeded or exit_condition_met:
                is_weak = False
                weak_start_date = None
                weak_days_count = 0
            elif weak_condition_met:
                weak_start_date = trade_date
                weak_days_count = 0
        elif weak_condition_met:
            is_weak = True
            weak_start_date = trade_date
            weak_days_count = 0

        rows.append(
            {
                "trade_date": trade_date,
                "is_weak": bool(is_weak),
                "below_count": below_count,
                "above_count": above_count,
                "weak_days_count": weak_days_count,
                "signal_trade_date": signal_trade_date,
            }
        )
    return pd.DataFrame(rows)


def calculate_momentum_score(price_series: pd.Series | np.ndarray, lookback_days: int) -> MomentumScore | None:
    values = pd.Series(price_series, dtype="float64").dropna().to_numpy()
    if len(values) < lookback_days + 1:
        return None

    recent = values[-(lookback_days + 1) :]
    if np.any(recent <= 0):
        return None

    y = np.log(recent)
    x = np.arange(len(y), dtype="float64")
    weights = np.linspace(1.0, 2.0, len(y))
    regression_weights = weights**2
    weight_sum = regression_weights.sum()
    x_bar = (regression_weights * x).sum() / weight_sum
    y_bar = (regression_weights * y).sum() / weight_sum
    dx = x - x_bar
    dy = y - y_bar
    variance_x = (regression_weights * dx**2).sum()
    if variance_x == 0:
        return MomentumScore(0.0, 0.0, 0.0)

    slope = (regression_weights * dx * dy).sum() / variance_x
    intercept = y_bar - slope * x_bar
    annualized_return = math.exp(slope * 250.0) - 1.0
    y_pred = slope * x + intercept
    ss_res = (weights * (y - y_pred) ** 2).sum()
    ss_tot = (weights * (y - y.mean()) ** 2).sum()
    r_squared = 1.0 - ss_res / ss_tot if ss_tot else 0.0
    return MomentumScore(
        momentum_score=float(annualized_return * r_squared),
        annualized_return=float(annualized_return),
        r_squared=float(r_squared),
    )


def generate_wufu_targets(
    prices: pd.DataFrame,
    config: WufuEtfRotationConfig | None = None,
    weak_states: pd.DataFrame | None = None,
    dynamic_snapshots: pd.DataFrame | None = None,
    liquidity_thresholds: pd.DataFrame | dict[pd.Timestamp | str, float] | float | None = None,
    liquidity_lookback: int = 3,
) -> pd.DataFrame:
    config = config or WufuEtfRotationConfig()
    required = {"symbol", "trade_date", "close", "volume"}
    missing = required.difference(prices.columns)
    if missing:
        raise ValueError(f"prices missing required columns: {sorted(missing)}")
    if config.holdings_num != 1:
        raise ValueError("basic local version supports holdings_num=1")

    data = prices.copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"])
    data = data.sort_values(["symbol", "trade_date"])
    dynamic_by_date = _dynamic_pool_by_date(dynamic_snapshots)
    dynamic_symbols = [symbol for symbols in dynamic_by_date.values() for symbol in symbols]
    allowed = set(config.etf_pool + config.dynamic_etf_pool + dynamic_symbols)
    if config.defensive_etf:
        allowed.add(config.defensive_etf)
    data = data[data["symbol"].isin(allowed)]
    if data.empty:
        raise ValueError("no prices available for configured ETF pool")
    weak_by_date = _weak_state_by_date(weak_states)
    symbol_bars = _symbol_bar_cache(data)
    threshold_by_date = _liquidity_threshold_by_date(liquidity_thresholds) if liquidity_thresholds is not None else None

    rows: list[dict[str, object]] = []
    trade_dates = sorted(data["trade_date"].drop_duplicates())
    for trade_date in trade_dates:
        is_weak = weak_by_date.get(trade_date, False)
        daily_dynamic_pool = dynamic_by_date.get(trade_date, [])
        etf_pool = (
            config.global_etf_pool
            if is_weak
            else list(dict.fromkeys(config.etf_pool + config.dynamic_etf_pool + daily_dynamic_pool))
        )
        if threshold_by_date is not None:
            filtered_pool = _filter_pool_by_liquidity_for_date(
                symbol_bars,
                trade_date,
                etf_pool,
                threshold_by_date,
                liquidity_lookback,
            )
            if filtered_pool:
                etf_pool = filtered_pool
        metrics = _rank_etfs_for_date_cached(symbol_bars, trade_date, config, etf_pool=etf_pool, is_weak=is_weak)
        candidates = _apply_candidate_threshold(metrics, config, is_weak=is_weak)
        target = candidates[0] if candidates else None
        if target is None and config.defensive_etf in symbol_bars:
            target = _defensive_target_cached(symbol_bars, trade_date, config.defensive_etf)

        rows.append(
            {
                "trade_date": trade_date,
                "target_symbol": target["symbol"] if target else None,
                "rank": target["rank"] if target else None,
                "momentum_score": target["momentum_score"] if target else None,
                "annualized_return": target["annualized_return"] if target else None,
                "r_squared": target["r_squared"] if target else None,
                "close": target["close"] if target else None,
                "is_weak": is_weak,
                "candidates_json": json.dumps(_serializable_candidates(candidates[:10]), ensure_ascii=False),
            }
        )

    return pd.DataFrame(rows)


def generate_fusion_etf_targets(
    prices: pd.DataFrame,
    config: FusionEtfRotationConfig | None = None,
    weak_states: pd.DataFrame | None = None,
    dynamic_snapshots: pd.DataFrame | None = None,
    liquidity_thresholds: pd.DataFrame | dict[pd.Timestamp | str, float] | float | None = None,
    liquidity_lookback: int = 3,
) -> pd.DataFrame:
    config = config or FusionEtfRotationConfig()
    if not config.qixing.enabled:
        return generate_wufu_targets(
            prices,
            config=config.wufu,
            weak_states=weak_states,
            dynamic_snapshots=dynamic_snapshots,
            liquidity_thresholds=liquidity_thresholds,
            liquidity_lookback=liquidity_lookback,
        )

    if config.qixing.independent_slot_enabled:
        return _generate_dual_slot_fusion_targets(
            prices=prices,
            config=config,
            weak_states=weak_states,
            dynamic_snapshots=dynamic_snapshots,
            liquidity_thresholds=liquidity_thresholds,
            liquidity_lookback=liquidity_lookback,
        )

    fused_wufu = replace(config.wufu, etf_pool=list(dict.fromkeys(config.wufu.etf_pool + config.qixing.pool)))
    return _generate_fusion_targets_with_bonus(
        prices,
        config=FusionEtfRotationConfig(wufu=fused_wufu, qixing=config.qixing),
        weak_states=weak_states,
        dynamic_snapshots=dynamic_snapshots,
        liquidity_thresholds=liquidity_thresholds,
        liquidity_lookback=liquidity_lookback,
    )


def _generate_dual_slot_fusion_targets(
    prices: pd.DataFrame,
    config: FusionEtfRotationConfig,
    weak_states: pd.DataFrame | None,
    dynamic_snapshots: pd.DataFrame | None,
    liquidity_thresholds: pd.DataFrame | dict[pd.Timestamp | str, float] | float | None,
    liquidity_lookback: int,
) -> pd.DataFrame:
    wufu_config = config.wufu
    qixing_config = config.qixing
    required = {"symbol", "trade_date", "close", "volume"}
    missing = required.difference(prices.columns)
    if missing:
        raise ValueError(f"prices missing required columns: {sorted(missing)}")
    if wufu_config.holdings_num != 1:
        raise ValueError("dual-slot fusion local version supports holdings_num=1")
    if qixing_config.wufu_slot_weight < 0 or qixing_config.qixing_slot_weight < 0:
        raise ValueError("slot weights must be non-negative")
    slot_weight_sum = qixing_config.wufu_slot_weight + qixing_config.qixing_slot_weight
    if slot_weight_sum <= 0:
        raise ValueError("at least one slot weight must be positive")

    data = prices.copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"])
    data = data.sort_values(["symbol", "trade_date"])
    dynamic_by_date = _dynamic_pool_by_date(dynamic_snapshots)
    dynamic_symbols = [symbol for symbols in dynamic_by_date.values() for symbol in symbols]
    allowed = set(
        wufu_config.etf_pool
        + wufu_config.global_etf_pool
        + wufu_config.dynamic_etf_pool
        + dynamic_symbols
        + qixing_config.pool
    )
    if wufu_config.defensive_etf:
        allowed.add(wufu_config.defensive_etf)
    data = data[data["symbol"].isin(allowed)]
    if data.empty:
        raise ValueError("no prices available for configured ETF pool")

    weak_by_date = _weak_state_by_date(weak_states)
    symbol_bars = _symbol_bar_cache(data)
    threshold_by_date = _liquidity_threshold_by_date(liquidity_thresholds) if liquidity_thresholds is not None else None

    rows: list[dict[str, object]] = []
    trade_dates = sorted(data["trade_date"].drop_duplicates())
    for trade_date in trade_dates:
        is_weak = weak_by_date.get(trade_date, False)
        daily_dynamic_pool = dynamic_by_date.get(trade_date, [])
        wufu_pool = (
            wufu_config.global_etf_pool
            if is_weak
            else list(dict.fromkeys(wufu_config.etf_pool + wufu_config.dynamic_etf_pool + daily_dynamic_pool))
        )
        qixing_pool = list(dict.fromkeys(qixing_config.pool))
        if threshold_by_date is not None:
            filtered_wufu_pool = _filter_pool_by_liquidity_for_date(
                symbol_bars,
                trade_date,
                wufu_pool,
                threshold_by_date,
                liquidity_lookback,
            )
            if filtered_wufu_pool:
                wufu_pool = filtered_wufu_pool
            filtered_qixing_pool = _filter_pool_by_liquidity_for_date(
                symbol_bars,
                trade_date,
                qixing_pool,
                threshold_by_date,
                liquidity_lookback,
            )
            if filtered_qixing_pool:
                qixing_pool = filtered_qixing_pool

        wufu_metrics = _rank_etfs_for_date_cached(symbol_bars, trade_date, wufu_config, etf_pool=wufu_pool, is_weak=is_weak)
        qixing_metrics = _rank_etfs_for_date_cached(
            symbol_bars,
            trade_date,
            replace(wufu_config, etf_pool=qixing_pool),
            etf_pool=qixing_pool,
            is_weak=False,
        )
        qixing_metrics = [_with_fusion_score(row, set(qixing_pool), qixing_config) for row in qixing_metrics]
        qixing_metrics.sort(key=lambda row: float(row["fusion_score"]), reverse=True)
        for index, row in enumerate(qixing_metrics, start=1):
            row["rank"] = index

        wufu_target = wufu_metrics[0] if wufu_metrics else None
        qixing_target = qixing_metrics[0] if qixing_metrics else None
        if wufu_target is None and wufu_config.defensive_etf in symbol_bars:
            wufu_target = _defensive_target_cached(symbol_bars, trade_date, wufu_config.defensive_etf)
        if qixing_target is None and wufu_target is not None:
            qixing_target = wufu_target

        target_weights = _combine_slot_weights(
            [
                (wufu_target, qixing_config.wufu_slot_weight),
                (qixing_target, qixing_config.qixing_slot_weight),
            ]
        )
        target_symbols = list(target_weights)
        primary_target = wufu_target or qixing_target
        rows.append(
            {
                "trade_date": trade_date,
                "target_symbol": primary_target["symbol"] if primary_target else None,
                "wufu_target_symbol": wufu_target["symbol"] if wufu_target else None,
                "qixing_target_symbol": qixing_target["symbol"] if qixing_target else None,
                "target_symbols_json": json.dumps(target_symbols, ensure_ascii=False),
                "target_weights_json": json.dumps(target_weights, ensure_ascii=False, sort_keys=True),
                "rank": primary_target["rank"] if primary_target else None,
                "momentum_score": primary_target["momentum_score"] if primary_target else None,
                "fusion_score": primary_target.get("fusion_score") if primary_target else None,
                "qixing_bonus": primary_target.get("qixing_bonus") if primary_target else None,
                "annualized_return": primary_target["annualized_return"] if primary_target else None,
                "r_squared": primary_target["r_squared"] if primary_target else None,
                "close": primary_target["close"] if primary_target else None,
                "is_weak": is_weak,
                "candidates_json": json.dumps(
                    {
                        "wufu": _serializable_candidates(wufu_metrics[:10]),
                        "qixing": _serializable_fusion_candidates(qixing_metrics[:10]),
                    },
                    ensure_ascii=False,
                ),
            }
        )
    return pd.DataFrame(rows)


def _combine_slot_weights(slots: list[tuple[dict[str, object] | None, float]]) -> dict[str, float]:
    weights: dict[str, float] = {}
    for target, weight in slots:
        if target is None or weight <= 0:
            continue
        symbol = str(target["symbol"])
        weights[symbol] = weights.get(symbol, 0.0) + float(weight)
    total = sum(weights.values())
    if total <= 0:
        return {}
    return {symbol: round(weight / total, 10) for symbol, weight in weights.items()}


def _generate_fusion_targets_with_bonus(
    prices: pd.DataFrame,
    config: FusionEtfRotationConfig,
    weak_states: pd.DataFrame | None,
    dynamic_snapshots: pd.DataFrame | None,
    liquidity_thresholds: pd.DataFrame | dict[pd.Timestamp | str, float] | float | None,
    liquidity_lookback: int,
) -> pd.DataFrame:
    wufu_config = config.wufu
    required = {"symbol", "trade_date", "close", "volume"}
    missing = required.difference(prices.columns)
    if missing:
        raise ValueError(f"prices missing required columns: {sorted(missing)}")
    if wufu_config.holdings_num != 1:
        raise ValueError("fusion local version supports holdings_num=1")

    data = prices.copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"])
    data = data.sort_values(["symbol", "trade_date"])
    dynamic_by_date = _dynamic_pool_by_date(dynamic_snapshots)
    dynamic_symbols = [symbol for symbols in dynamic_by_date.values() for symbol in symbols]
    allowed = set(wufu_config.etf_pool + wufu_config.dynamic_etf_pool + dynamic_symbols + config.qixing.pool)
    if wufu_config.defensive_etf:
        allowed.add(wufu_config.defensive_etf)
    data = data[data["symbol"].isin(allowed)]
    if data.empty:
        raise ValueError("no prices available for configured ETF pool")

    weak_by_date = _weak_state_by_date(weak_states)
    symbol_bars = _symbol_bar_cache(data)
    threshold_by_date = _liquidity_threshold_by_date(liquidity_thresholds) if liquidity_thresholds is not None else None
    qixing_pool = set(config.qixing.pool)

    rows: list[dict[str, object]] = []
    trade_dates = sorted(data["trade_date"].drop_duplicates())
    for trade_date in trade_dates:
        is_weak = weak_by_date.get(trade_date, False)
        daily_dynamic_pool = dynamic_by_date.get(trade_date, [])
        etf_pool = (
            wufu_config.global_etf_pool
            if is_weak
            else list(dict.fromkeys(wufu_config.etf_pool + wufu_config.dynamic_etf_pool + daily_dynamic_pool))
        )
        if threshold_by_date is not None:
            filtered_pool = _filter_pool_by_liquidity_for_date(
                symbol_bars,
                trade_date,
                etf_pool,
                threshold_by_date,
                liquidity_lookback,
            )
            if filtered_pool:
                etf_pool = filtered_pool
        metrics = _rank_etfs_for_date_cached(symbol_bars, trade_date, wufu_config, etf_pool=etf_pool, is_weak=is_weak)
        metrics = [_with_fusion_score(row, qixing_pool, config.qixing) for row in metrics]
        metrics.sort(key=lambda row: float(row["fusion_score"]), reverse=True)
        for index, row in enumerate(metrics, start=1):
            row["rank"] = index
        candidates = _apply_fusion_candidate_threshold(metrics, wufu_config, is_weak=is_weak)
        target = candidates[0] if candidates else None
        if target is None and wufu_config.defensive_etf in symbol_bars:
            target = _defensive_target_cached(symbol_bars, trade_date, wufu_config.defensive_etf)

        rows.append(
            {
                "trade_date": trade_date,
                "target_symbol": target["symbol"] if target else None,
                "rank": target["rank"] if target else None,
                "momentum_score": target["momentum_score"] if target else None,
                "fusion_score": target.get("fusion_score") if target else None,
                "qixing_bonus": target.get("qixing_bonus") if target else None,
                "annualized_return": target["annualized_return"] if target else None,
                "r_squared": target["r_squared"] if target else None,
                "close": target["close"] if target else None,
                "is_weak": is_weak,
                "candidates_json": json.dumps(_serializable_fusion_candidates(candidates[:10]), ensure_ascii=False),
            }
        )

    return pd.DataFrame(rows)


def _symbol_bar_cache(data: pd.DataFrame) -> dict[str, dict[str, np.ndarray]]:
    cache: dict[str, dict[str, np.ndarray]] = {}
    for symbol, rows in data.groupby("symbol", sort=False):
        ordered = rows.sort_values("trade_date")
        cache[str(symbol)] = {
            "trade_date": ordered["trade_date"].to_numpy(dtype="datetime64[ns]"),
            "close": ordered["close"].astype(float).to_numpy(),
            "volume": ordered["volume"].astype(float).to_numpy(),
            "amount": ordered["amount"].astype(float).to_numpy()
            if "amount" in ordered.columns
            else (ordered["close"].astype(float) * ordered["volume"].astype(float)).to_numpy(),
        }
    return cache


def _filter_pool_by_liquidity_for_date(
    symbol_bars: dict[str, dict[str, np.ndarray]],
    trade_date: pd.Timestamp,
    etf_pool: list[str],
    thresholds: dict[pd.Timestamp, float] | float,
    lookback: int,
) -> list[str]:
    threshold = _threshold_for_date(thresholds, trade_date)
    trade_date64 = np.datetime64(pd.Timestamp(trade_date), "ns")
    output: list[str] = []
    for symbol in etf_pool:
        bars = symbol_bars.get(symbol)
        if bars is None:
            continue
        end_pos = int(np.searchsorted(bars["trade_date"], trade_date64, side="left"))
        if end_pos < lookback:
            continue
        amount = bars["amount"][end_pos - lookback : end_pos].astype(float)
        if len(amount) < lookback or not np.isfinite(amount).all():
            continue
        if float(amount.mean()) > threshold:
            output.append(symbol)
    return output


def _rank_etfs_for_date_cached(
    symbol_bars: dict[str, dict[str, np.ndarray]],
    trade_date: pd.Timestamp,
    config: WufuEtfRotationConfig,
    etf_pool: list[str],
    is_weak: bool,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    trade_date64 = np.datetime64(pd.Timestamp(trade_date), "ns")
    for symbol in etf_pool:
        bars = symbol_bars.get(symbol)
        if bars is None:
            continue
        end_pos = int(np.searchsorted(bars["trade_date"], trade_date64, side="right"))
        if end_pos < config.lookback_days + 1:
            continue
        closes = pd.Series(bars["close"][:end_pos], dtype="float64")
        volumes = pd.Series(bars["volume"][:end_pos], dtype="float64")
        score = calculate_momentum_score(closes, config.lookback_days)
        if score is None:
            continue

        passed_momentum = config.min_score_threshold <= score.momentum_score <= config.max_score_threshold
        passed_r2 = score.r_squared > config.r2_threshold
        passed_ma = _passes_ma_filter(closes, config)
        passed_volume = _passes_volume_filter(volumes, config)
        passed_loss = _passes_loss_filter(closes, config)
        if not passed_momentum:
            continue
        if config.enable_r2_filter and not is_weak and not passed_r2:
            continue
        if config.enable_ma_filter and is_weak and not passed_ma:
            continue
        if config.enable_volume_check and not passed_volume:
            continue
        if config.enable_loss_filter and not passed_loss:
            continue

        rows.append(
            {
                "symbol": symbol,
                "trade_date": trade_date,
                "rank": 0,
                "momentum_score": score.momentum_score,
                "annualized_return": score.annualized_return,
                "r_squared": score.r_squared,
                "close": float(closes.iloc[-1]),
            }
        )

    rows.sort(key=lambda row: float(row["momentum_score"]), reverse=True)
    for index, row in enumerate(rows, start=1):
        row["rank"] = index
    return rows


def _defensive_target_cached(
    symbol_bars: dict[str, dict[str, np.ndarray]],
    trade_date: pd.Timestamp,
    defensive_etf: str,
) -> dict[str, object] | None:
    bars = symbol_bars.get(defensive_etf)
    if bars is None:
        return None
    end_pos = int(np.searchsorted(bars["trade_date"], np.datetime64(pd.Timestamp(trade_date), "ns"), side="right"))
    if end_pos == 0:
        return None
    return {
        "symbol": defensive_etf,
        "trade_date": trade_date,
        "rank": 999,
        "momentum_score": None,
        "annualized_return": None,
        "r_squared": None,
        "close": float(bars["close"][end_pos - 1]),
    }


def _dynamic_pool_by_date(dynamic_snapshots: pd.DataFrame | None) -> dict[pd.Timestamp, list[str]]:
    if dynamic_snapshots is None or dynamic_snapshots.empty:
        return {}
    required = {"trade_date", "symbol", "rank"}
    missing = required.difference(dynamic_snapshots.columns)
    if missing:
        raise ValueError(f"dynamic_snapshots missing required columns: {sorted(missing)}")
    rows = dynamic_snapshots.copy()
    rows["trade_date"] = pd.to_datetime(rows["trade_date"])
    rows["symbol"] = rows["symbol"].astype(str)
    rows = rows.sort_values(["trade_date", "rank"])
    grouped = rows.groupby("trade_date")["symbol"].apply(list)
    return grouped.to_dict()


def _serializable_candidates(candidates: list[dict[str, object]]) -> list[dict[str, object]]:
    fields = ["symbol", "rank", "momentum_score", "annualized_return", "r_squared", "close"]
    rows: list[dict[str, object]] = []
    for candidate in candidates:
        rows.append({field: candidate.get(field) for field in fields})
    return rows


def _with_fusion_score(
    row: dict[str, object],
    qixing_pool: set[str],
    config: QixingEnhancementConfig,
) -> dict[str, object]:
    output = row.copy()
    in_qixing_pool = str(row["symbol"]) in qixing_pool
    bonus = config.preferred_pool_bonus if in_qixing_pool else 0.0
    output["qixing_bonus"] = float(bonus)
    output["fusion_score"] = float(row["momentum_score"]) + float(bonus)
    output["sources"] = ["wufu", "qixing"] if in_qixing_pool else ["wufu"]
    return output


def _apply_fusion_candidate_threshold(
    ranked: list[dict[str, object]],
    config: WufuEtfRotationConfig,
    is_weak: bool = False,
) -> list[dict[str, object]]:
    top_10 = ranked[:10]
    if len(top_10) < config.holdings_num:
        return top_10

    reference_score = float(top_10[config.holdings_num - 1]["fusion_score"])
    ratio = 1.0 if is_weak else config.score_threshold_ratio
    score_threshold = reference_score * ratio
    return [row for row in top_10 if float(row["fusion_score"]) >= score_threshold]


def _serializable_fusion_candidates(candidates: list[dict[str, object]]) -> list[dict[str, object]]:
    fields = [
        "symbol",
        "rank",
        "momentum_score",
        "fusion_score",
        "qixing_bonus",
        "annualized_return",
        "r_squared",
        "close",
        "sources",
    ]
    rows: list[dict[str, object]] = []
    for candidate in candidates:
        rows.append({field: candidate.get(field) for field in fields})
    return rows


def _rank_etfs_for_date(
    history: pd.DataFrame,
    trade_date: pd.Timestamp,
    config: WufuEtfRotationConfig,
    etf_pool: list[str],
    is_weak: bool,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for symbol in etf_pool:
        symbol_history = history[history["symbol"] == symbol].sort_values("trade_date")
        if len(symbol_history) < config.lookback_days + 1:
            continue

        closes = symbol_history["close"].astype(float)
        score = calculate_momentum_score(closes, config.lookback_days)
        if score is None:
            continue

        current = symbol_history.iloc[-1]
        passed_momentum = config.min_score_threshold <= score.momentum_score <= config.max_score_threshold
        passed_r2 = score.r_squared > config.r2_threshold
        passed_ma = _passes_ma_filter(closes, config)
        passed_volume = _passes_volume_filter(symbol_history["volume"], config)
        passed_loss = _passes_loss_filter(closes, config)
        if not passed_momentum:
            continue
        if config.enable_r2_filter and not is_weak and not passed_r2:
            continue
        if config.enable_ma_filter and is_weak and not passed_ma:
            continue
        if config.enable_volume_check and not passed_volume:
            continue
        if config.enable_loss_filter and not passed_loss:
            continue

        rows.append(
            {
                "symbol": symbol,
                "trade_date": trade_date,
                "rank": 0,
                "momentum_score": score.momentum_score,
                "annualized_return": score.annualized_return,
                "r_squared": score.r_squared,
                "close": float(current["close"]),
            }
        )

    rows.sort(key=lambda row: float(row["momentum_score"]), reverse=True)
    for index, row in enumerate(rows, start=1):
        row["rank"] = index
    return rows


def _apply_candidate_threshold(
    ranked: list[dict[str, object]],
    config: WufuEtfRotationConfig,
    is_weak: bool = False,
) -> list[dict[str, object]]:
    top_10 = ranked[:10]
    if len(top_10) < config.holdings_num:
        return top_10

    reference_score = float(top_10[config.holdings_num - 1]["momentum_score"])
    ratio = 1.0 if is_weak else config.score_threshold_ratio
    score_threshold = reference_score * ratio
    return [row for row in top_10 if float(row["momentum_score"]) >= score_threshold]


def _weak_state_by_date(weak_states: pd.DataFrame | None) -> dict[pd.Timestamp, bool]:
    if weak_states is None or weak_states.empty:
        return {}
    required = {"trade_date", "is_weak"}
    missing = required.difference(weak_states.columns)
    if missing:
        raise ValueError(f"weak_states missing required columns: {sorted(missing)}")
    states = weak_states.copy()
    states["trade_date"] = pd.to_datetime(states["trade_date"])
    return dict(zip(states["trade_date"], states["is_weak"].astype(bool), strict=False))


def _passes_ma_filter(closes: pd.Series, config: WufuEtfRotationConfig) -> bool:
    if len(closes) < config.ma_lookback:
        return False
    ma_value = closes.iloc[-config.ma_lookback :].mean()
    return float(closes.iloc[-1]) > float(ma_value) * config.ma_threshold


def _passes_volume_filter(volumes: pd.Series, config: WufuEtfRotationConfig) -> bool:
    if len(volumes) < config.volume_lookback + 1:
        return False
    current_volume = float(volumes.iloc[-1])
    trailing = volumes.iloc[-(config.volume_lookback + 1) : -1].astype(float)
    if trailing.isna().any() or (trailing <= 0).any():
        return False
    return current_volume / float(trailing.mean()) < config.volume_threshold


def _passes_loss_filter(closes: pd.Series, config: WufuEtfRotationConfig) -> bool:
    if len(closes) < 4:
        return True
    recent = closes.iloc[-4:].astype(float).to_numpy()
    ratios = recent[1:] / recent[:-1]
    return bool(np.min(ratios) >= config.loss)


def _defensive_target(history: pd.DataFrame, trade_date: pd.Timestamp, defensive_etf: str) -> dict[str, object] | None:
    symbol_history = history[history["symbol"] == defensive_etf].sort_values("trade_date")
    if symbol_history.empty:
        return None
    current = symbol_history.iloc[-1]
    return {
        "symbol": defensive_etf,
        "trade_date": trade_date,
        "rank": 999,
        "momentum_score": None,
        "annualized_return": None,
        "r_squared": None,
        "close": float(current["close"]),
    }
