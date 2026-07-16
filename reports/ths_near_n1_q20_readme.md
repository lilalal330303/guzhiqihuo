# near_n1_q20 同花顺 SuperMind 运行说明

脚本：`C:/Users/16052/Documents/量化研究/reports/ths_near_n1_q20.py`

当前脚本版本：`ths_v2_data_shape_fix`。该版本修复了 SuperMind 批量 `get_price` 返回 MultiIndex/字典形态时 T-1 行情被解析为空的问题，并加入 `POOL_STAGE`、`POOL_EMPTY`、`THS_ORDER_SKIP` 和 `PRICE_FALLBACK_T1` 诊断日志。

在当前 SuperMind 策略编辑器中：

1. 将脚本全部复制到策略编辑器，覆盖旧代码。
2. 回测区间设置为 `2020-01-01` 至页面可选的最近交易日。
3. 初始资金设置为 `1000000`，频率选择“分钟”，账户选择股票。
4. 点击“编译运行”。
5. 回测完成后导出策略收益、最大回撤、Sharpe、交易日志；重点保留 `NEAR_SIGNAL`、`QUALITY_FALLBACK`、`THS_ORDER`、`THS_ORDER_FAIL` 行。

如果再次出现无交易，先看日志：

- `POOL_EMPTY reason=no_index_components`：同花顺没有返回 399101 成分股；
- `POOL_EMPTY reason=no_previous_close`：批量日行情返回格式或代码格式仍不匹配；
- `THS_ORDER_SKIP reason=no_current_price`：目标已生成，但盘中价格接口为空；
- `QUALITY_FALLBACK` / `CAP_FALLBACK`：因子接口缺失，只是降级选股，不代表完整复刻。

## 结果口径

- 若日志出现 `QUALITY_FALLBACK`，这是同花顺缺少财务因子接口导致的兼容降级版，选股等价于“市值临界 + 中性质量”，不称为完整 `near_n1_q20` 复刻。
- 若日志没有 `CAP_FALLBACK`，说明平台提供了市值因子；若同时没有 `QUALITY_FALLBACK`，才可进行较严格的因子口径对比。
- 本地参考版本的共同区间结果来自 `reports/small_cap_fixed11_log6_p0p1/local_vs_jq_comparison.json`，不能替代同花顺平台实跑结果。
