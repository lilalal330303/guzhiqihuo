# ETF 分钟 K 线库搭建报告

## 本轮结果

- 候选标的数：3
- 新增分钟行数：0
- 本轮成功补数标的：0
- 本轮失败或源不可用标的：3
- 请求区间：2020-01-02 至 2026-07-06
- 分批天数：31
- 配置数据源：['pandadata']
- 可用数据源：[]

## 数据源预检

- pandadata: 不可用，RuntimeError: Pandadata credentials are missing. Set DEFAULT_USERNAME and DEFAULT_PASSWORD, or create ~/.pandadata/pandadata.env.

## 数据源优先级

1. Pandadata `get_stock_min`：适合作为长周期 1 分钟历史库主源，需要账号权限。
2. JQData / Tushare Pro / 米筐 / Wind / Choice / iFinD：适合授权长周期分钟数据，可作为 Pandadata 的替代主源。
3. mootdx：免 key，适合近期分钟增量和盘后验证，历史长度有限。
4. AkShare/东方财富：免 key 兜底，通常只适合近期数据，易受网络和限流影响。

## 输出文件

- `etf_minute_fetch_results.csv`
- `etf_minute_coverage.csv`
