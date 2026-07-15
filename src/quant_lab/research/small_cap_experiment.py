from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from quant_lab.backtest.metrics import calculate_metrics
from quant_lab.backtest.portfolio import (
    CostModel,
    DailyRiskConfig,
    PortfolioBacktestResult,
    run_portfolio_backtest,
)
from quant_lab.data.repository import DuckDBRepository
from quant_lab.strategies.small_cap import (
    SmallCapParams,
    crowding_position_ratio,
    select_joinquant_v3,
)


@dataclass(frozen=True)
class SmallCapExperimentConfig:
    start_date: str = "2020-01-01"
    end_date: str = date.today().isoformat()
    initial_cash: float = 1_000_000.0
    benchmark: str = "159919"
    strict: bool = True
    hypothesis: str = "小市值因子在严格时点数据和可交易约束下具有超额收益"
    next_research_note: str = "比较严格版与降级版，并进行参数敏感性和风控消融。"


@dataclass(frozen=True)
class SmallCapExperimentResult:
    config: SmallCapExperimentConfig
    backtest: PortfolioBacktestResult
    metrics: dict[str, float | int]
    annual_returns: pd.DataFrame


def _validate_dynamic_stock_counts(counts: tuple[int, int, int, int]) -> None:
    if (
        not isinstance(counts, tuple)
        or len(counts) != 4
        or any(
            isinstance(count, (bool, np.bool_))
            or not isinstance(count, (int, np.integer))
            or count <= 0
            for count in counts
        )
    ):
        raise ValueError("counts must contain exactly four positive integers")


def dynamic_stock_num(
    index_diff: float,
    counts: tuple[int, int, int, int] = (3, 4, 5, 6),
) -> int:
    """Map the 399101-to-MA10 difference to a profile holding count."""
    _validate_dynamic_stock_counts(counts)
    if not np.isfinite(index_diff):
        raise ValueError("index_diff must be finite")
    if index_diff >= 200:
        return counts[0]
    if index_diff >= -200:
        return counts[1]
    if index_diff >= -500:
        return counts[2]
    return counts[3]


def build_joinquant_v3_targets(
    inputs: dict[str, pd.DataFrame],
    params: SmallCapParams,
    *,
    enable_audit: bool = True,
    enable_dividend: bool = True,
    enable_crowding: bool = True,
    enable_dynamic_stock_num: bool = True,
    fix_known_source_bugs: bool = False,
    audit_mode: str = "hard",
    quality_penalty: float = 0.10,
    dynamic_stock_counts: tuple[int, int, int, int] = (3, 4, 5, 6),
    profile_name: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Build Tuesday v3 targets from JoinQuant point-in-time exports.

    This function is intentionally independent of DuckDB.  It is therefore
    deterministic, fixture-testable and reusable by baseline, sensitivity and
    ablation orchestration.
    """
    _validate_dynamic_stock_counts(dynamic_stock_counts)
    if profile_name is not None and (
        not isinstance(profile_name, str) or not profile_name.strip()
    ):
        raise ValueError("profile_name must be a non-empty string or None")
    snapshots = inputs["snapshots"].copy()
    if snapshots.empty:
        raise ValueError("strict JoinQuant snapshots are empty")
    for column in ["signal_date", "query_date"]:
        snapshots[column] = pd.to_datetime(snapshots[column])
    index_prices = inputs.get("index_prices", pd.DataFrame()).copy()
    if not index_prices.empty:
        index_prices["trade_date"] = pd.to_datetime(index_prices["trade_date"])
        index_prices = index_prices.sort_values("trade_date")
        index_prices["ma10"] = index_prices["close"].rolling(10).mean()
    crowding = inputs.get("crowding", pd.DataFrame()).copy()
    if not crowding.empty:
        crowding["trade_date"] = pd.to_datetime(crowding["trade_date"])
        crowding = crowding.set_index("trade_date")
    target_rows: list[dict[str, object]] = []
    diagnostic_rows: list[dict[str, object]] = []
    rejection_frames: list[pd.DataFrame] = []
    events = {
        key: inputs.get(key, pd.DataFrame()).copy()
        for key in [
            "audit_opinions", "profit_forecasts", "income_publications",
            "share_pledges", "dividend_events",
        ]
    }
    indexed_events: dict[str, pd.DataFrame] = {}
    for key, frame in events.items():
        if not frame.empty:
            frame["symbol"] = frame["symbol"].astype(str)
            indexed_events[key] = frame.set_index("symbol", drop=False).sort_index()
        else:
            indexed_events[key] = frame
    for signal_date, group in snapshots.groupby("signal_date", sort=True):
        query_date = pd.Timestamp(group["query_date"].iloc[0])
        stock_num = params.stock_num
        index_diff = np.nan
        if enable_dynamic_stock_num:
            exact = index_prices.loc[index_prices["trade_date"].eq(query_date)] if not index_prices.empty else pd.DataFrame()
            if exact.empty or pd.isna(exact.iloc[-1].get("ma10")):
                raise ValueError(f"missing exact 399101 MA10 input for query date {query_date.date()}")
            index_diff = float(exact.iloc[-1]["close"] - exact.iloc[-1]["ma10"])
            stock_num = dynamic_stock_num(index_diff, dynamic_stock_counts)
        run_params = SmallCapParams(**{**params.__dict__, "stock_num": stock_num})
        likely = group.loc[
            group["market_cap_100m"].between(run_params.market_cap_min / 1e8, run_params.market_cap_max / 1e8)
            & group["operating_revenue"].gt(run_params.revenue_min)
            & group["net_profit"].gt(run_params.net_profit_min)
            & group["roe_pct"].gt(0)
            & group["roa_pct"].gt(0)
        ].sort_values(["market_cap_100m", "symbol"]).head(stock_num * 5)
        event_symbols = likely["symbol"].astype(str).tolist()
        dated_events: dict[str, pd.DataFrame] = {}
        for key, frame in indexed_events.items():
            if frame.empty:
                dated_events[key] = frame
                continue
            available = frame.index.intersection(event_symbols)
            subset = frame.loc[available].copy() if len(available) else frame.iloc[0:0].copy()
            date_column = "pub_date" if "pub_date" in subset else "implementation_pub_date"
            if date_column in subset:
                subset = subset.loc[pd.to_datetime(subset[date_column]).le(query_date)]
            dated_events[key] = subset
        selection = select_joinquant_v3(
            group,
            signal_date=signal_date,
            query_date=query_date,
            params=run_params,
            audit_opinions=dated_events["audit_opinions"],
            profit_forecasts=dated_events["profit_forecasts"],
            income_publications=dated_events["income_publications"],
            share_pledges=dated_events["share_pledges"],
            dividend_events=dated_events["dividend_events"],
            enable_audit=enable_audit,
            enable_dividend=enable_dividend,
            fix_known_source_bugs=fix_known_source_bugs,
            audit_mode=audit_mode,
            quality_penalty=quality_penalty,
        )
        if not selection.rejected.empty:
            rejected = selection.rejected.copy()
            rejected["signal_date"] = signal_date
            rejection_frames.append(rejected)
        concentration = np.nan
        position_ratio = 1.0
        observed_symbols = np.nan
        if enable_crowding:
            if crowding.empty or query_date not in crowding.index:
                raise ValueError(f"missing exact crowding input for query date {query_date.date()}")
            crowd_row = crowding.loc[query_date]
            if isinstance(crowd_row, pd.DataFrame):
                crowd_row = crowd_row.iloc[-1]
            concentration = float(crowd_row["concentration"])
            observed_symbols = float(crowd_row.get("observed_symbols", np.nan))
            position_ratio = crowding_position_ratio(concentration, run_params)
        selected = selection.selected
        if selected and position_ratio > 0:
            weight = position_ratio / len(selected)
            for symbol in selected:
                target_row = {
                    "signal_date": signal_date,
                    "symbol": symbol,
                    "target_weight": weight,
                }
                if profile_name is not None:
                    target_row.update({"stock_num": stock_num, "profile_name": profile_name})
                target_rows.append(target_row)
        else:
            # The source switches to 511880 during its empty/maximum-crowding
            # states.  The daily engine will apply its stock-like fill model;
            # this fee-model difference is disclosed in the report.
            target_row = {"signal_date": signal_date, "symbol": "511880", "target_weight": 1.0}
            if profile_name is not None:
                target_row.update({"stock_num": stock_num, "profile_name": profile_name})
            target_rows.append(target_row)
        diagnostic_row = {
            "signal_date": signal_date,
            "query_date": query_date,
            "stock_num": stock_num,
            "index_diff": index_diff,
            "crowding_query_date": query_date,
            "crowding": concentration,
            "crowding_observed_symbols": observed_symbols,
            "position_ratio": position_ratio,
            "selected_count": len(selected),
            "selected_symbols": ",".join(selected),
        }
        if profile_name is not None:
            diagnostic_row["profile_name"] = profile_name
        diagnostic_rows.append(diagnostic_row)
    target_columns = ["signal_date", "symbol", "target_weight"]
    if profile_name is not None:
        target_columns.extend(["stock_num", "profile_name"])
    targets = pd.DataFrame(target_rows, columns=target_columns)
    diagnostics = pd.DataFrame(diagnostic_rows)
    rejections = pd.concat(rejection_frames, ignore_index=True) if rejection_frames else pd.DataFrame(
        columns=["symbol", "rule", "evidence_date", "signal_date"]
    )
    return targets, diagnostics, rejections


def run_small_cap_experiment(
    bars: pd.DataFrame,
    targets: pd.DataFrame,
    config: SmallCapExperimentConfig | None = None,
    *,
    risk: DailyRiskConfig | None = None,
    market_daily: pd.DataFrame | None = None,
    index_bars: pd.DataFrame | None = None,
    crowding_daily: pd.DataFrame | None = None,
    exposure_budget_daily: pd.DataFrame | None = None,
    buy_new_only: bool = False,
    costs: CostModel | None = None,
) -> SmallCapExperimentResult:
    config = config or SmallCapExperimentConfig()
    backtest = run_portfolio_backtest(
        bars, targets, initial_cash=config.initial_cash, risk=risk,
        market_daily=market_daily, index_bars=index_bars, crowding_daily=crowding_daily,
        exposure_budget_daily=exposure_budget_daily,
        buy_new_only=buy_new_only,
        costs=costs,
    )
    trades = backtest.trades.copy()
    if "return_pct" not in trades:
        trades["return_pct"] = 0.0
    metrics = calculate_metrics(backtest.equity_curve, trades)
    returns = backtest.equity_curve["equity"].pct_change().dropna()
    volatility = float(returns.std(ddof=0) * np.sqrt(252)) if len(returns) else 0.0
    sharpe = float(returns.mean() / returns.std(ddof=0) * np.sqrt(252)) if len(returns) and returns.std(ddof=0) else 0.0
    turnover = float(trades["amount"].abs().sum() / config.initial_cash) if not trades.empty else 0.0
    metrics.update({"volatility": volatility, "sharpe": sharpe, "turnover": turnover})
    curve = backtest.equity_curve.copy()
    curve["year"] = pd.to_datetime(curve["trade_date"]).dt.year
    annual = curve.groupby("year")["equity"].agg(["first", "last"]).reset_index()
    annual["return"] = annual["last"] / annual["first"] - 1.0
    return SmallCapExperimentResult(config, backtest, metrics, annual[["year", "return"]])


def run_degraded_small_cap_experiment(
    repo: DuckDBRepository,
    config: SmallCapExperimentConfig,
    params: SmallCapParams | None = None,
    apply_status_filters: bool = True,
) -> tuple[SmallCapExperimentResult, pd.DataFrame]:
    """Run the explicitly degraded daily proxy over the same requested interval.

    It uses only locally observed trade status, listing history, price and
    float-cap proxy (volume / turnover × close).  It does *not* substitute this
    proxy for total market cap or silently omit the original financial/event
    rules; callers must label results as degraded.
    """
    if config.strict:
        raise ValueError("strict mode requires point-in-time total market cap and financial/event facts")
    params = params or SmallCapParams()
    candidates = repo.load_degraded_small_cap_candidates(
        config.start_date, config.end_date, params.market_cap_min, params.market_cap_max,
        params.price_max, params.listing_days_min, params.stock_num, apply_status_filters,
    )
    if candidates.empty:
        raise ValueError("no degraded candidates; turnover data may be incomplete")
    counts = candidates.groupby("signal_date")["symbol"].transform("count")
    targets = candidates.loc[:, ["signal_date", "symbol"]].copy()
    targets["target_weight"] = 1.0 / counts
    symbols = sorted(targets["symbol"].unique().tolist())
    bars = repo.load_execution_bars(symbols, config.start_date, config.end_date)
    return run_small_cap_experiment(bars, targets, config), candidates
