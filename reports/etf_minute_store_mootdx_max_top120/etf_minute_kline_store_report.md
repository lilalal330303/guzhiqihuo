# ETF 分钟 K 线库搭建报告

## 本轮结果

- 候选标的数：120
- 新增分钟行数：2735760
- 本轮成功补数标的：120
- 本轮失败或源不可用标的：0
- 请求区间：2026-02-06 至 2026-07-07
- 分批天数：31
- 配置数据源：['mootdx', 'akshare']
- 可用数据源：['mootdx']

## 数据源预检

- mootdx: 可用，ok
- akshare: 不可用，ProxyError: HTTPSConnectionPool(host='push2his.eastmoney.com', port=443): Max retries exceeded with url: /api/qt/stock/trends2/get?fields1=f1%2Cf2%2Cf3%2Cf4%2Cf5%2Cf6%2Cf7%2Cf8%2Cf9%2Cf10%2Cf11%2Cf12%2Cf13&fields2=f51%2Cf52%2Cf53%2Cf54%2Cf55%2Cf56%2Cf57%2Cf58&ut=7eea3edcaed734bea9cbfc24409ed989&ndays=5&iscr=0&secid=1.511880 (Caused by ProxyError('Unable to connect to proxy', RemoteDisconnected('Remote end closed connection without response')))

## 数据源优先级

1. Pandadata `get_stock_min`：适合作为长周期 1 分钟历史库主源，需要账号权限。
2. JQData / Tushare Pro / 米筐 / Wind / Choice / iFinD：适合授权长周期分钟数据，可作为 Pandadata 的替代主源。
3. mootdx：免 key，适合近期分钟增量和盘后验证，历史长度有限。
4. AkShare/东方财富：免 key 兜底，通常只适合近期数据，易受网络和限流影响。

## 输出文件

- `etf_minute_fetch_results.csv`
- `etf_minute_coverage.csv`
