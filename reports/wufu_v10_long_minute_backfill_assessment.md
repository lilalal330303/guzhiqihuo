# 五福 ETF V10 长周期分钟补库与复评报告

## 执行结论

本轮已把本地分钟补库器升级为“源预检 + 按月分批 + 断点增量 + 中文 HTML 报告”的长期补库流程，但当前机器没有 Pandadata 凭据，且 `jqdatasdk`、`tushare` SDK 尚未安装或配置账号，因此无法真正拉取 2020-2026 全池历史分钟线。

本轮没有新增长周期分钟数据。V10 复跑后仍是“真实分钟优先、缺口日期日线代理兜底”的结果。

## 数据源状态

- Pandadata：SDK 已安装，但缺少 `DEFAULT_USERNAME` / `DEFAULT_PASSWORD`，也没有 `~/.pandadata/pandadata.env`，预检失败。
- JQData：`jqdatasdk` 未安装，未配置账号。
- Tushare Pro：`tushare` 未安装，未配置 token。
- mootdx：可用，但只能覆盖近期通达信分钟数据，不适合作为 2020 起全历史主源。
- AkShare/东方财富：可作为近期兜底，但受网络和接口限制，不适合作为全历史主源。

## 本地分钟库现状

- `prices_minute` 总行数：38,400
- 覆盖标的数：6
- 覆盖日期：2026-05-29 至 2026-07-07
- V10 回测区间命中分钟行数：36,960
- V10 回测区间命中分钟日期：2026-05-29 至 2026-07-06

## Pandadata 预检结果

运行范围：2020-01-02 至 2026-07-06  
样本标的：511880、510300、159967  
结果：新增 0 行，3 个标的均因源不可用跳过。

阻断原因：

`Pandadata credentials are missing. Set DEFAULT_USERNAME and DEFAULT_PASSWORD, or create ~/.pandadata/pandadata.env.`

输出文件：

- `reports/etf_minute_store_long_pandadata_probe/etf_minute_kline_store_report.html`
- `reports/etf_minute_store_long_pandadata_probe/etf_minute_fetch_results.csv`
- `reports/etf_minute_store_long_pandadata_probe/etf_minute_coverage.csv`

## V10 复评结果

方法：`real_minute_with_daily_proxy_fallback`

| 指标 | 基准：真实 13:11 买入 | V10：真实分钟择时 | 差异 |
|---|---:|---:|---:|
| 最终权益 | 6,120,732.57 | 33,171,533.35 | 27,050,800.78 |
| 总收益 | 512.07% | 3217.15% | 2705.08% |
| 年化收益 | 32.10% | 71.27% | 39.17% |
| 最大回撤 | -29.93% | -24.91% | 5.02% |
| 交易数 | 1509 | 1521 | 12 |
| 止损次数 | 0 | 29 | 29 |

交易模式：

- 买入模式：`force_proxy` 395、`trend_proxy` 364、`force_real` 2
- 卖出/止损执行：`daily_close` 729、`stop_proxy` 29、`minute` 2

## 判断

当前 V10 的漂亮收益仍不能当作“完整真实分钟回测结论”。原因是 2020-2026 的大部分交易仍走日线代理，真实分钟只命中最近少量交易。它只能说明真实分钟执行链路已经打通，不能说明日内择时模块在全历史分钟数据上已经被验证。

## 下一步

1. 配置 Pandadata 账号后，直接复用现有补库脚本按月补全历史分钟。
2. 如果使用 JQData，需要安装并登录 `jqdatasdk`，再增加一个本地落库适配器。
3. 如果使用 Tushare Pro，需要安装 `tushare` 并配置 token，同时确认分钟权限和积分满足历史分钟数据调用。
4. 长周期分钟补齐后，重新跑 `reports/run_wufu_v10_intraday_timing_backtest.py`，重点看 `entry_mode_breakdown` 中 `trend_real/force_real` 占比是否超过 95%，以及 `execution_mode_breakdown` 中 `minute/stop_real` 是否替代代理模式。
