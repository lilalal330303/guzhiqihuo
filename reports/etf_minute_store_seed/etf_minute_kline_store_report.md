# ETF 分钟 K 线库搭建报告

## 本轮结果

- 候选标的数：5
- 新增分钟行数：1200
- 本轮成功补数标的：5
- 本轮失败标的：0

## 数据源优先级

1. Pandadata `get_stock_min`：适合作为长周期 1 分钟历史库主源，需要账号权限。
2. mootdx 通达信服务器：免 key，适合近期分钟增量和盘后验证，历史长度有限。
3. AkShare/东方财富：免 key 兜底，通常只适合近期数据，易受网络和限流影响。

## 输出文件

- `etf_minute_fetch_results.csv`
- `etf_minute_coverage.csv`
