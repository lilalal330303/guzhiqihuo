from __future__ import annotations

from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from quant_lab.data.repository import DuckDBRepository
from quant_lab.research.experiment import run_ma_cross_experiment


def main() -> None:
    st.set_page_config(page_title="Quant Research Workbench", layout="wide")
    st.title("Quant Research Workbench")

    with st.sidebar:
        symbol = st.text_input("股票代码", value="000001", max_chars=6)
        start_date = st.date_input("开始日期", value=date(2022, 1, 1))
        end_date = st.date_input("结束日期", value=date.today())
        short_window = st.number_input("短均线", min_value=2, max_value=120, value=20, step=1)
        long_window = st.number_input("长均线", min_value=3, max_value=250, value=60, step=1)
        refresh_data = st.checkbox("刷新 akshare 数据", value=True)
        run_clicked = st.button("运行回测", type="primary")

    if not run_clicked:
        st.info("设置参数后点击运行回测。")
        return

    repo = DuckDBRepository()
    try:
        result = run_ma_cross_experiment(
            repo=repo,
            symbol=symbol.strip(),
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            short_window=int(short_window),
            long_window=int(long_window),
            refresh_data=refresh_data,
        )
    except Exception as exc:
        st.error(f"运行失败：{exc}")
        return

    st.caption(f"Run ID: {result.run_id}")
    metric_cols = st.columns(5)
    metrics = result.metrics
    metric_cols[0].metric("总收益", _fmt_pct(metrics["total_return"]))
    metric_cols[1].metric("年化收益", _fmt_pct(metrics["annualized_return"]))
    metric_cols[2].metric("最大回撤", _fmt_pct(metrics["max_drawdown"]))
    metric_cols[3].metric("交易次数", str(metrics["trade_count"]))
    metric_cols[4].metric("胜率", _fmt_pct(metrics["win_rate"]))

    st.plotly_chart(_price_figure(result.signals, result.trades), use_container_width=True)
    st.plotly_chart(_equity_figure(result.equity_curve), use_container_width=True)

    left, right = st.columns(2)
    with left:
        st.subheader("交易记录")
        st.dataframe(result.trades, use_container_width=True, hide_index=True)
    with right:
        st.subheader("最近信号")
        signal_cols = ["trade_date", "close", "short_ma", "long_ma", "signal", "position", "trade_signal"]
        st.dataframe(result.signals[signal_cols].tail(30), use_container_width=True, hide_index=True)


def _price_figure(signals: pd.DataFrame, trades: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=signals["trade_date"],
            open=signals["open"],
            high=signals["high"],
            low=signals["low"],
            close=signals["close"],
            name="K线",
        )
    )
    fig.add_trace(go.Scatter(x=signals["trade_date"], y=signals["short_ma"], mode="lines", name="短均线"))
    fig.add_trace(go.Scatter(x=signals["trade_date"], y=signals["long_ma"], mode="lines", name="长均线"))

    if not trades.empty:
        fig.add_trace(
            go.Scatter(
                x=trades["entry_date"],
                y=trades["entry_price"],
                mode="markers",
                marker={"symbol": "triangle-up", "size": 11, "color": "#0f9d58"},
                name="买入",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=trades["exit_date"],
                y=trades["exit_price"],
                mode="markers",
                marker={"symbol": "triangle-down", "size": 11, "color": "#d93025"},
                name="卖出",
            )
        )

    fig.update_layout(title="价格与均线信号", xaxis_rangeslider_visible=False, height=520)
    return fig


def _equity_figure(equity_curve: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=equity_curve["trade_date"],
            y=equity_curve["equity"],
            mode="lines",
            name="策略净值",
        )
    )
    fig.update_layout(title="策略权益曲线", height=360)
    return fig


def _fmt_pct(value: float | int) -> str:
    return f"{float(value) * 100:.2f}%"


if __name__ == "__main__":
    main()
