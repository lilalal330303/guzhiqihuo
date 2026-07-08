# Wufu V12-D Compact Capacity Iteration

## 输出脚本

- 同花顺：`reports/ths_wufu_fast_v12d_compact_capacity.py`
- 聚宽：`reports/jq_wufu_fixed_pool_v12d_compact_capacity.py`

## 本轮目标

V12-C 已经证明弱市与目标同步基本达标，但同花顺在 `2025-03-24 13:15:00` 仍触发日志条数上限。本轮 V12-D 优先解决“日志全周期覆盖”，同时把分批成交和止损差异做成可审计口径。

## 核心改动

1. 日志极简化
   - `WUFU_EXECUTE` 不再每天输出，仅诊断日输出。
   - `WUFU_ORDER_PLAN` 不再常规输出，仅诊断日输出。
   - `WUFU_PENDING_BUY` 只在仍有等待买入或诊断日输出。
   - `WUFU_MORNING_COMPACT` 只在弱市状态变化或诊断日输出。
   - 聚宽 `WUFU_POSITION` 只在诊断日输出，日常以 `WUFU_DAILY_COMPACT` 为准。

2. 分批成交日志升级
   - 保留 `WUFU_SPLIT_START`。
   - 删除每分钟 `WUFU_SPLIT_STEP` 常规日志。
   - 新增 `WUFU_SPLIT_DONE`，记录最终计划金额、实际持仓市值和缺口比例。
   - 分批目标加入 `CAPACITY_STEP_BUFFER = 0.98`，减少贴边触发资金不足或取整失败。

3. 止损审计增强
   - 同花顺和聚宽 `WUFU_STOP_LOSS` 均增加 `position_value` 与 `source` 字段。
   - 聚宽保留 `closeable` 字段，同花顺以平台可取字段为准。

4. 聚宽 pool 字段修复
   - 聚宽 `WUFU_DAILY_COMPACT` 的 pool 从不存在的 `filtered_etf_list` 改为 `len(g.merged_etf_pool)`。

## 下一轮验收

1. 同花顺 `WUFU_DAILY_COMPACT` 是否覆盖到 2026-07。
2. 弱市匹配率是否仍为 99%+。
3. 目标匹配率是否仍为 98%+。
4. 共同周期止损差异是否下降到 5%以内。
5. `WUFU_SPLIT_DONE` 的 `gap_pct` 是否多数小于 2%。
6. 若仍触发同花顺日志省略，继续删除非必要日志：`WUFU_SIGNAL` 可只输出目标变化，`WUFU_WEAK_SOURCE` 可只输出变化点。

## 静态校验

已用工作区 Python 对两份脚本完成 `py_compile` 静态校验。
