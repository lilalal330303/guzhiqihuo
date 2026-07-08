# 五福 ETF 平台同步 V7 脚本迭代报告

## 本轮目标

在 V6 达到“弱市状态 100% 一致、目标日期 98.48% 一致”的基础上，继续压缩剩余差异，并让下一轮同花顺、聚宽分钟级日志可以更直接定位原因。

## 已完成改动

1. 同花顺 `WUFU_SCORE_DETAIL` 补齐无候选日期格式
   - V6 中同花顺在过滤后没有可打分标的时，输出格式缺少 `weak` 和 `target` 字段。
   - 这会导致解析器漏读专项 24 日中的 `2021-07-21`。
   - V7 已统一为：`date / weak / pool / passed / target / top10`。

2. 两个平台统一输出 `WUFU_ORDER_PLAN`
   - 字段包括：日期、目标代码、账户权益、0.2% 现金缓冲后的可用金额、当前价、100 份向下取整后的份额、实际目标下单金额。
   - 下一轮可以判断执行差异来自价格源、整手取整、资金口径，还是平台成交撮合。

3. 聚宽日终持仓日志防重复
   - `reset_daily_flags` 和 `after_trading_end` 都可以触发持仓记录。
   - V7 增加同日保护，保证每天只输出一条 `WUFU_POSITION`。

4. 初始化版本号升级
   - 同花顺新增 `WUFU_THS_FAST_V7`。
   - 聚宽升级为 `WUFU_JQ_FIXED_POOL_V7`。
   - 后续日志可以直接识别脚本版本，避免 V5/V6/V7 混用。

## 输出脚本

- 同花顺英文路径：`reports/ths_wufu_fast_v7_score_pool_execution.py`
- 同花顺中文副本：`reports/同花顺_聚宽五福ETF同步快速V7_诊断执行.py`
- 聚宽英文路径：`reports/jq_wufu_fixed_pool_v7_score_pool_execution.py`
- 聚宽中文副本：`reports/聚宽_五福ETF同步固定池V7_诊断执行.py`

## 验证结果

已用本地 Python 对两份 V7 脚本做语法检查，通过。

## 下一轮日志验收重点

1. `WUFU_SCORE_DETAIL`
   - 预期同花顺与聚宽专项 24 日都能解析到 24 条。
   - 如果仍有目标不一致，优先看 Top10 的 `score / annualized / r2 / price / today_volume`。

2. `WUFU_ORDER_PLAN`
   - 对比同一天两边的 `price / shares / order_value`。
   - 如果目标一致但收益不同，优先检查这组字段。

3. `WUFU_POSITION`
   - 预期每日一条。
   - 如果两边目标一致但持仓不同，检查卖出失败、买入失败、停牌、整手不足和现金缓冲。

4. 速度优化方向
   - 同花顺脚本继续保持“只在 24 个诊断日输出重日志”。
   - 常规回测不要打开全量逐标的明细，否则分钟级环境会明显变慢。

