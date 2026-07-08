from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import timedelta

import pandas as pd

from quant_lab.backtest.metrics import calculate_metrics
from quant_lab.backtest.rotation import run_single_slot_rotation_backtest
from quant_lab.data.ingest import fetch_etf_daily, fetch_index_daily
from quant_lab.data.repository import DuckDBRepository
from quant_lab.strategies.wufu_etf_rotation import (
    WufuEtfRotationConfig,
    build_dynamic_etf_pool,
    calculate_joinquant_liquidity_thresholds,
    dynamic_pool_snapshots,
    generate_a_share_weak_states,
    generate_a_share_weak_states_joinquant_style,
    generate_wufu_targets,
)


@dataclass(frozen=True)
class WufuEtfRotationExperimentResult:
    run_id: str
    prices: pd.DataFrame
    targets: pd.DataFrame
    equity_curve: pd.DataFrame
    trades: pd.DataFrame
    metrics: dict[str, float | int]
    fetched_symbols: list[str]
    skipped_symbols: dict[str, str]
    data_quality_excluded_symbols: list[str]


def run_wufu_etf_rotation_experiment(
    repo: DuckDBRepository,
    start_date: str,
    end_date: str,
    config: WufuEtfRotationConfig | None = None,
    refresh_data: bool = True,
    hypothesis: str = "五福 ETF 基础版：在 ETF 池内选择加权对数动量得分最高且通过过滤的品种，次日执行。",
    next_research_note: str = "下一步可补充动态行业池、弱市判定、盘中成交量投影、溢价率和分钟止损。",
    max_abs_daily_return: float = 0.25,
    weak_states: pd.DataFrame | None = None,
    use_local_weak_states: bool = False,
    etf_metadata: pd.DataFrame | None = None,
    dynamic_liquidity_threshold: float | None = None,
    dynamic_liquidity_thresholds: pd.DataFrame | None = None,
    commission_rate: float = 0.0001,
    slippage_rate: float = 0.0001,
    min_commission: float = 5.0,
    etf_adjust: str = "qfq",
    target_cache_key: str | None = None,
    use_target_cache: bool = True,
    use_dynamic_snapshot_cache: bool = True,
    weak_state_signal_lag_days: int = 0,
    apply_liquidity_filter: bool = False,
) -> WufuEtfRotationExperimentResult:
    config = config or WufuEtfRotationConfig()
    repo.initialize()
    symbols = _configured_symbols(config, etf_metadata=etf_metadata)
    warmup_start_date = _warmup_start_date(start_date, config)
    fetched_symbols: list[str] = []
    skipped_symbols: dict[str, str] = {}

    if refresh_data:
        for symbol in symbols:
            try:
                fetched = fetch_etf_daily(symbol=symbol, start_date=warmup_start_date, end_date=end_date, adjust=etf_adjust)
                repo.upsert_prices(fetched, source=f"akshare-etf-{etf_adjust}-fallback-may-be-unadjusted")
                fetched_symbols.append(symbol)
            except Exception as exc:  # noqa: BLE001 - keep batch fetch resilient for research runs.
                skipped_symbols[symbol] = str(exc)
        if use_local_weak_states:
            for index_symbol in ["000300", "399101", "399006", "000510"]:
                try:
                    fetched_index = fetch_index_daily(index_symbol, warmup_start_date, end_date)
                    repo.upsert_prices(fetched_index, source="akshare-index-sina")
                except Exception as exc:  # noqa: BLE001
                    skipped_symbols[f"index:{index_symbol}"] = str(exc)

    prices = repo.load_prices_for_symbols(symbols=symbols, start_date=warmup_start_date, end_date=end_date)
    if prices.empty:
        raise ValueError(f"no stored ETF prices from {start_date} to {end_date}")
    prices, data_quality_excluded_symbols = _exclude_symbols_with_price_jumps(prices, max_abs_daily_return)
    if prices.empty:
        raise ValueError("all ETF prices were excluded by data quality checks")

    dynamic_pool: list[str] = []
    dynamic_snapshots = pd.DataFrame()
    if etf_metadata is not None and (dynamic_liquidity_threshold is not None or dynamic_liquidity_thresholds is not None):
        if dynamic_liquidity_thresholds is None:
            dynamic_liquidity_thresholds = calculate_joinquant_liquidity_thresholds(prices)
        latest_threshold = _latest_liquidity_threshold(dynamic_liquidity_thresholds, end_date)
        threshold_source = dynamic_liquidity_thresholds if dynamic_liquidity_threshold is None else dynamic_liquidity_threshold
        dynamic_pool = build_dynamic_etf_pool(etf_metadata, prices, end_date=end_date, liquidity_threshold=latest_threshold)
        if use_dynamic_snapshot_cache:
            dynamic_snapshots = repo.load_dynamic_pool_snapshots(warmup_start_date, end_date)
        if not _covers_trade_dates(dynamic_snapshots, prices):
            dynamic_snapshots = dynamic_pool_snapshots(
                etf_metadata,
                prices,
                liquidity_threshold=threshold_source,
            )
            repo.replace_dynamic_pool_snapshots(dynamic_snapshots, source="local-etf-metadata-daily-snapshot")
        config = WufuEtfRotationConfig(**(asdict(config) | {"dynamic_etf_pool": dynamic_pool}))

    if use_local_weak_states and weak_states is None:
        index_prices = repo.load_prices_for_symbols(["000300", "399101", "399006", "000510"], warmup_start_date, end_date)
        if weak_state_signal_lag_days:
            weak_states = generate_a_share_weak_states_joinquant_style(
                index_prices,
                ma_lookback=config.weak_period_ma_lookback,
                max_weak_days=config.max_weak_days,
                signal_lag_days=weak_state_signal_lag_days,
            )
        else:
            weak_states = generate_a_share_weak_states(
                index_prices,
                ma_lookback=config.weak_period_ma_lookback,
                max_weak_days=config.max_weak_days,
            )

    targets = pd.DataFrame()
    target_cache_hit = False
    if target_cache_key and use_target_cache:
        targets = repo.load_wufu_target_cache(target_cache_key, start_date, end_date)
        if not _covers_target_dates(targets, prices, start_date, end_date):
            targets = pd.DataFrame()
        else:
            target_cache_hit = True
    if targets.empty:
        targets = generate_wufu_targets(
            prices,
            config=config,
            weak_states=weak_states,
            dynamic_snapshots=dynamic_snapshots,
            liquidity_thresholds=dynamic_liquidity_thresholds if apply_liquidity_filter else None,
        )
        targets = targets[pd.to_datetime(targets["trade_date"]) >= pd.Timestamp(start_date)].reset_index(drop=True)
        if target_cache_key:
            cache_rows = targets.copy()
            cache_rows["cache_key"] = target_cache_key
            repo.save_wufu_target_cache(cache_rows[["cache_key", "trade_date", "target_symbol", "is_weak", "candidates_json"]])
    else:
        targets = targets.drop(columns=["cache_key", "created_at"], errors="ignore")
    backtest_prices = prices[pd.to_datetime(prices["trade_date"]) >= pd.Timestamp(start_date)].reset_index(drop=True)
    backtest = run_single_slot_rotation_backtest(
        prices=backtest_prices,
        targets=targets,
        commission_rate=commission_rate,
        slippage_rate=slippage_rate,
        min_commission=min_commission,
    )
    metrics = calculate_metrics(backtest.equity_curve, backtest.trades)
    params = asdict(config) | {
        "fetched_symbols": fetched_symbols,
        "skipped_symbols": skipped_symbols,
        "warmup_start_date": warmup_start_date,
        "max_abs_daily_return": max_abs_daily_return,
        "data_quality_excluded_symbols": data_quality_excluded_symbols,
        "weak_state_source": "provided" if weak_states is not None and not use_local_weak_states else ("local-index" if use_local_weak_states else "disabled"),
        "weak_state_signal_lag_days": weak_state_signal_lag_days,
        "dynamic_etf_pool": dynamic_pool,
        "dynamic_liquidity_threshold": dynamic_liquidity_threshold if dynamic_liquidity_threshold is not None else "joinquant_daily_formula",
        "dynamic_liquidity_threshold_latest": _latest_liquidity_threshold(dynamic_liquidity_thresholds, end_date)
        if dynamic_liquidity_thresholds is not None
        else dynamic_liquidity_threshold,
        "commission_rate": commission_rate,
        "slippage_rate": slippage_rate,
        "min_commission": min_commission,
        "etf_adjust": etf_adjust,
        "target_cache_key": target_cache_key,
        "target_cache_hit": target_cache_hit,
        "apply_liquidity_filter": apply_liquidity_filter,
        "dynamic_snapshot_rows": int(len(dynamic_snapshots)),
        "dynamic_snapshot_dates": int(pd.to_datetime(dynamic_snapshots["trade_date"]).nunique()) if not dynamic_snapshots.empty else 0,
    }
    run_id = repo.save_wufu_rotation_run(
        start_date=start_date,
        end_date=end_date,
        hypothesis=hypothesis,
        params=params,
        metrics=metrics,
        trades=backtest.trades,
        next_research_note=next_research_note,
    )

    return WufuEtfRotationExperimentResult(
        run_id=run_id,
        prices=prices,
        targets=targets,
        equity_curve=backtest.equity_curve,
        trades=backtest.trades,
        metrics=metrics,
        fetched_symbols=fetched_symbols,
        skipped_symbols=skipped_symbols,
        data_quality_excluded_symbols=data_quality_excluded_symbols,
    )


def _configured_symbols(config: WufuEtfRotationConfig, etf_metadata: pd.DataFrame | None = None) -> list[str]:
    symbols = list(dict.fromkeys(config.etf_pool))
    symbols.extend(symbol for symbol in config.dynamic_etf_pool if symbol not in symbols)
    if etf_metadata is not None and "symbol" in etf_metadata.columns:
        symbols.extend(symbol for symbol in etf_metadata["symbol"].astype(str).tolist() if symbol not in symbols)
    if config.defensive_etf and config.defensive_etf not in symbols:
        symbols.append(config.defensive_etf)
    return symbols


def _covers_trade_dates(candidate: pd.DataFrame, prices: pd.DataFrame) -> bool:
    if candidate.empty:
        return False
    candidate_dates = set(pd.to_datetime(candidate["trade_date"]).dt.normalize())
    price_dates = set(pd.to_datetime(prices["trade_date"]).dt.normalize())
    return price_dates.issubset(candidate_dates)


def _covers_target_dates(candidate: pd.DataFrame, prices: pd.DataFrame, start_date: str, end_date: str) -> bool:
    if candidate.empty:
        return False
    candidate_dates = set(pd.to_datetime(candidate["trade_date"]).dt.normalize())
    price_rows = prices.copy()
    price_rows["trade_date"] = pd.to_datetime(price_rows["trade_date"]).dt.normalize()
    mask = price_rows["trade_date"].between(pd.Timestamp(start_date), pd.Timestamp(end_date))
    expected_dates = set(price_rows.loc[mask, "trade_date"].drop_duplicates())
    return bool(expected_dates) and expected_dates.issubset(candidate_dates)


def _warmup_start_date(start_date: str, config: WufuEtfRotationConfig) -> str:
    warmup_bars = max(config.lookback_days, config.volume_lookback, config.ma_lookback) + 30
    warmup_calendar_days = warmup_bars * 3
    return (pd.Timestamp(start_date).date() - timedelta(days=warmup_calendar_days)).isoformat()


def _exclude_symbols_with_price_jumps(
    prices: pd.DataFrame,
    max_abs_daily_return: float,
) -> tuple[pd.DataFrame, list[str]]:
    if max_abs_daily_return <= 0:
        return prices, []
    rows = prices.sort_values(["symbol", "trade_date"]).copy()
    rows["daily_return"] = rows.groupby("symbol")["close"].pct_change()
    broken = sorted(rows.loc[rows["daily_return"].abs() > max_abs_daily_return, "symbol"].unique().tolist())
    if not broken:
        return prices, []
    return prices[~prices["symbol"].isin(broken)].reset_index(drop=True), broken


def _latest_liquidity_threshold(thresholds: pd.DataFrame | None, end_date: str) -> float:
    if thresholds is None or thresholds.empty:
        return 10_000_000.0
    rows = thresholds.copy()
    rows["trade_date"] = pd.to_datetime(rows["trade_date"])
    rows = rows[rows["trade_date"] <= pd.Timestamp(end_date)]
    if rows.empty:
        return 10_000_000.0
    return float(rows.sort_values("trade_date").iloc[-1]["liquidity_threshold"])
