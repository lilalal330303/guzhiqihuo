# Wufu V3 执行方案

## 目标

本轮不再同时追求“全市场动态池”和“平台一致性”。先把两个平台压到同一个固定池高速口径上，专门修弱市边界和执行规则。

## 输出脚本

- 同花顺：`reports/同花顺_聚宽五福ETF同步快速V3.py`
- 聚宽：`reports/聚宽_五福ETF同步固定池验证V3.py`

## V3 默认设置

同花顺：

- `USE_DYNAMIC_POOL = False`
- `USE_FULL_MARKET_THRESHOLD = False`
- `FAST_SCORE_HISTORY_CACHE = True`
- `CACHE_LOG_ENABLED = False`
- `WEAK_DETAIL_LOG_ENABLED = True`

聚宽：

- `USE_DYNAMIC_POOL = False`
- `USE_FULL_MARKET_THRESHOLD = False`
- `DETAIL_LOG_ENABLED = False`
- `WEAK_DETAIL_LOG_ENABLED = True`

含义：

1. 两个平台都只跑固定 ETF 池。
2. 成交额阈值也按固定池计算，避免同花顺拿不到全市场 ETF 元数据导致阈值不可比。
3. 同花顺 13:10 评分阶段增加日线历史批量缓存，减少逐标的重复行情读取。
4. 弱市明细只在上一轮不一致高发日期打印，不全周期刷明细。

## 为什么这样做

上一轮同花顺 vs 聚宽目标匹配率已经达到 `90.28%`。其中：

- 弱市一致日目标匹配率：`97.95%`
- 弱市不一致日目标匹配率：`22.50%`

所以 V3 的第一优先级是弱市状态机，而不是继续扩大动态池。固定池口径更快，也更容易定位差异。

## 同花顺速度优化点

1. 关闭动态池，避免早盘动态池清洗和额外行情检查。
2. 固定池阈值，避免尝试全市场 ETF 元数据。
3. 每日成交额缓存继续保留。
4. 新增每日评分历史缓存：13:10 先批量拉候选池历史，逐标的评分只读缓存。
5. 默认关闭缓存日志和评分明细日志。

## 回测后看什么

跑完两个平台分钟级回测后，继续用日志对比器：

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m quant_lab.research.platform_log_compare `
  --ths-log "C:\Users\16052\Desktop\outlog.txt" `
  --jq-log "reports\jq_minute_log_current\log.txt" `
  --output-prefix "reports\ths_jq_fast_v3"
```

重点指标：

1. `target_match_rate` 是否高于 `95%`。
2. `weak_match_rate` 是否高于 `95%`。
3. 弱市不一致日期是否明显减少。
4. 同花顺回测耗时是否明显下降。
5. 两边订单警告是否仍然大量存在。

## 下一步

若 V3 固定池目标匹配高于 `95%`：

1. 修执行层：100 份取整、碎股平仓、资金不足处理。
2. 再开 `USE_FULL_MARKET_THRESHOLD=True`，单独校准阈值。
3. 最后再开 `USE_DYNAMIC_POOL=True`，恢复全市场动态池。

若 V3 固定池目标仍低于 `95%`：

1. 只看 `WUFU_WEAK_DETAIL` 中打印的边界日。
2. 检查指数最后日期、close、MA10、above/below。
3. 不要先改动态池，否则问题会重新混在一起。
