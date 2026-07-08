# Wufu V12-C Ultra Compact + Capacity Split Iteration

## 输出脚本

- 同花顺：`reports/ths_wufu_fast_v12c_ultra_split.py`
- 聚宽：`reports/jq_wufu_fixed_pool_v12c_ultra_split.py`

## 本轮目标

1. Ultra Compact 日志版：保留 `WUFU_DAILY_COMPACT` 全周期日终主线，弱市、信号、执行日志只在状态切换、目标变化或诊断日期输出。
2. 分批成交容量版：检测到买入计划超过当分钟 25% 成交量容量时，不一次性打满，改为未来 5 个分钟逐步把目标仓位爬到最终值。
3. 验收口径：下一轮以同花顺 compact 全周期覆盖为先，再检查弱市 99%+、目标 98%+、止损差异小于 5%，最后再看收益表现。

## 关键实现

- 新增参数：
  - `ULTRA_COMPACT_LOGS = True`
  - `CAPACITY_SPLIT_ENABLED = True`
  - `CAPACITY_PARTICIPATION_RATE = 0.25`
  - `CAPACITY_SPLIT_MINUTES = 5`
- 新增日志：
  - `WUFU_SPLIT_START`：记录触发容量分批的标的、计划股数、当分钟成交量、25% 容量和拆分次数。
  - `WUFU_SPLIT_STEP`：记录每分钟分批目标值、100 份取整后的下单值、价格和份额。
- 执行层保持：
  - 0.2% 现金缓冲。
  - ETF 100 份向下取整。
  - 先卖后买。
  - 下单失败只记录，不追单。

## 下一轮日志验收建议

同花顺回测时优先确认：

1. `WUFU_DAILY_COMPACT` 覆盖是否从 2020-01 到 2026-07 全周期完整。
2. `WUFU_WEAK_SOURCE` 是否只在弱市切换点输出；若仍缺年段，问题在平台日志截断，不在策略状态机。
3. `WUFU_SPLIT_START` 出现的日期是否集中在原先 25% 容量限制日。
4. `WUFU_SPLIT_STEP` 是否连续 5 分钟完成；若同花顺仍部分成交，需要用成交明细核对平台的分钟容量限制是否按“每分钟成交量”或“全天成交量”计算。
5. 用 `WUFU_DAILY_COMPACT` 对账弱市、目标、止损，再单独看收益差异。

## 静态校验

已用工作区 Python 对两份脚本完成 `py_compile` 静态校验。
