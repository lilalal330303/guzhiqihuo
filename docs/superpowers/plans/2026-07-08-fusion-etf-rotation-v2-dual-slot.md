# 五福 + 七星 ETF 轮动 V2 双槽位实施记录

> 状态：已完成。本轮目标是恢复原版中真正贡献收益的“双信号、双资金腿”结构，同时保留当前版本的单策略、单订单管理和无归属冲突约束。

## 目标

输出一份新的聚宽回测脚本：

- `reports/jq_fusion_etf_rotation_v2_dual_slot.py`

V2 不恢复旧脚本中的多策略账户、未标记持仓、独立七星买卖调度，而是把五福和七星变成统一策略内部的两个目标槽位。

## 核心设计

- 五福槽位：默认权重 `50%`，沿用五福 V12C 主逻辑。
- 七星槽位：默认权重 `50%`，使用七星 ETF 池独立排序。
- 如果两个槽位选中同一只 ETF，自动合并为 `100%` 权重。
- 如果七星槽位无目标，则回落到五福目标。
- 所有卖出、买入、拆单、止损、日志都仍通过同一套执行路径处理。

## 本轮优化点

1. 恢复双信号收益来源  
   原版表现更好的主要原因是实际形成了五福腿和七星腿。V2 用 `target_weights` 明确表达这两个槽位，避免原版的归属混乱。

2. 弱市切换两日确认  
   当前 V1 容易在指数短期转弱时过早缩池。V2 增加 `WEAK_CONFIRM_DAYS = 2`，连续确认后才切换弱市状态。

3. 放宽硬止损  
   V1 的 `3%` 盘中硬止损对高波动 ETF 偏紧。V2 将 `FIXED_STOP_LOSS_THRESHOLD` 从 `0.97` 调整为 `0.94`。

4. 统一七星盈利保护  
   V2 增加七星高水位回撤保护，但放在统一风控函数内，不再新增七星独立调度。

5. 日志可对账  
   `WUFU_SIGNAL` 和 `WUFU_DAILY_COMPACT` 增加 `weights` 和 `slots` 字段，便于后续对比聚宽日志。

## 涉及文件

- `src/quant_lab/strategies/wufu_etf_rotation.py`
- `tests/test_fusion_etf_rotation.py`
- `reports/jq_fusion_etf_rotation_v2_dual_slot.py`

## 验证结果

已执行：

```powershell
python -m pytest tests/test_fusion_etf_rotation.py -q
python -m pytest tests/test_wufu_etf_rotation.py tests/test_fusion_etf_rotation.py -q
python -m py_compile reports/jq_fusion_etf_rotation_v2_dual_slot.py
python -m pytest -q
```

结果：

- 融合测试通过。
- 五福与融合聚焦测试通过。
- V2 聚宽脚本语法检查通过。
- 全量测试通过。
- V2 脚本未发现 `portfolio_value_proportion`、`sub_account`、`stock_strategy`、`strategy_holdings`、七星独立买卖函数等归属冲突关键词。

## 回测观察重点

在聚宽回测日志中重点看：

- `WUFU_QIXING_FUSION_V2_DUAL_SLOT`
- `WUFU_SIGNAL ... weights=... slots=...`
- `WUFU_DAILY_COMPACT ... weights=... positions=...`
- `WUFU_QIXING_PROFIT_PROTECT`
- `WUFU_WEAK_DETAIL ... pending_count=... confirm_days=2`

如果 V2 接近原版收益，应看到多数强趋势阶段存在两个不同目标，且目标权重约为 `0.5/0.5`；如果两个槽位选中同一 ETF，则目标权重会合并为 `1.0`。
