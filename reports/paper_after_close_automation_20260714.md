# 模拟盘盘后自动更新交付报告（2026-07-14）

## 当日结果

- 交易日：2026-07-14
- 联合策略标的：129个
- 新增分钟行情：30,960条
- 新增日线：129条（由真实分钟OHLCV聚合）
- 策略审计窗口：13:01—14:56，共232个账户分钟事件
- 福星ETF权益：944,181.12元；现金259.72元；当前2个持仓
- 五福ETF权益：944,404.66元；现金22.06元；当前1个持仓
- 页面行情实际截至：2026-07-14 14:56

## 根因与修复

旧任务只在15:30导出已有快照，不下载行情、不推进策略，因此无法让模拟盘随实盘更新。新流水线按以下顺序运行：

1. 从通达信下载当日129个联合标的完整一分钟行情。
2. 在写库前验证每个冻结策略标的的13:01—14:56所需分钟完整性。
3. 写入分钟行情，并从真实分钟OHLCV聚合当日日线供下一交易日暖机。
4. 按V7K、V12D冻结适配器推进模拟账户，不修改核心策略和参数。
5. 导出本地页面审计快照及机器可读运行状态。

## 自动任务

- Windows任务：`QuantLab_PaperTrading_AfterClose_1530`
- 触发：每天15:30、15:45、16:00
- 成功后同交易日后续触发自动跳过；失败时后续触发自动重试。
- 电脑休眠或错过触发后，恢复时自动补运行并允许唤醒电脑。
- 周末自动跳过。
- Git发布任务：`QuantLab_PaperTrading_Publish_1605`，每天16:05和16:20仅同步模拟盘快照到master及GitHub Pages main分支。

## 交付文件

- 流水线：`src/quant_lab/research/paper_after_close.py`
- 任务入口：`reports/run_paper_after_close.py`
- 状态：`reports/paper_after_close_status.json`
- 页面快照：`docs/paper-trading/data/snapshot.json`
- 测试：`tests/test_paper_after_close.py`
- Git发布入口：`reports/publish_paper_snapshot.ps1`
