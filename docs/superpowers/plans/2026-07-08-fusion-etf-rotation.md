# 五福 + 七星 ETF 轮动融合实施计划

> 状态：已完成。本文件记录本轮优化的执行路径、约束、产物和验证结果，便于后续继续迭代。

## 目标

以五福 ETF V12C 为基准，把七星 ETF 的有效部分融合为增强模块，产出一套单策略、单目标、单持仓、单下单路径的 ETF 轮动方案，并导出可在聚宽运行的干净脚本。

## 总体架构

本地研究工作台保留核心策略逻辑，位置：

- `src/quant_lab/strategies/wufu_etf_rotation.py`

聚宽脚本作为平台适配层，位置：

- `reports/jq_fusion_etf_rotation_v1.py`

测试用于保护关键行为，位置：

- `tests/test_fusion_etf_rotation.py`

设计说明文档，位置：

- `docs/superpowers/specs/2026-07-08-fusion-etf-rotation-design.md`

## 全局约束

- 基准脚本使用 `reports/jq_wufu_fixed_pool_v12c_ultra_split.py`。
- 保留五福 V12C 的核心行为作为基准。
- 七星不再作为独立策略运行，只作为候选池和评分增强。
- 删除小市值、白马股、多策略账户等无用逻辑。
- 不引入策略 ID、虚拟子账户、持仓归属映射或并行下单调度。
- 本轮不改 Streamlit 界面。
- 本地回测仍遵守 T 日信号、T+1 执行。

## 任务 1：建立本地融合 API

状态：已完成。

改动文件：

- `src/quant_lab/strategies/wufu_etf_rotation.py`
- `tests/test_fusion_etf_rotation.py`

新增接口：

- `DEFAULT_QIXING_ETF_POOL`
- `QixingEnhancementConfig`
- `FusionEtfRotationConfig`
- `generate_fusion_etf_targets()`

完成内容：

- 增加七星默认 ETF 池。
- 增加七星增强配置。
- 增加融合策略配置。
- 增加融合目标生成函数。
- 关闭七星增强时，直接委托给原五福目标生成逻辑，确保基准兼容。
- 开启七星增强时，将七星池去重并入同一候选池。

验证点：

- 七星关闭时，融合输出与五福输出一致。
- 五福和七星重复标的只出现一次。
- 候选记录包含统一的 `fusion_score`。

## 任务 2：实现七星增强语义

状态：已完成。

改动文件：

- `src/quant_lab/strategies/wufu_etf_rotation.py`
- `tests/test_fusion_etf_rotation.py`

完成内容：

- 支持七星偏好池加分。
- 支持基于 `fusion_score` 的统一排序。
- 弱市状态下先使用五福弱市池，再进入融合排序。
- 无候选通过时回落到防御 ETF。
- 候选 JSON 中记录来源、动量分、融合分、七星加分等字段。

验证点：

- 当七星候选和五福候选分数接近时，七星加分可以推动其胜出。
- 弱市中七星不能绕过五福弱市约束。
- 候选全部不合格时，目标回落到防御 ETF。

## 任务 3：导出干净聚宽脚本

状态：已完成。

新增文件：

- `reports/jq_fusion_etf_rotation_v1.py`

基准来源：

- `reports/jq_wufu_fixed_pool_v12c_ultra_split.py`

完成内容：

- 保留五福 V12C 的早盘准备、信号计算、统一执行、待买趋势检查、强制买入、容量拆单、分钟止损、每日重置。
- 新增 `QIXING_ETF_POOL`。
- 新增 `QIXING_ENHANCEMENT_ENABLED`。
- 新增 `QIXING_PREFERRED_POOL_BONUS`。
- 非弱市时将七星 ETF 池去重并入五福候选池。
- `score_symbol()` 输出 `qixing_bonus` 和 `fusion_score`。
- `select_target()` 使用 `fusion_score` 统一排序。

明确删除或避免：

- 小市值策略。
- 白马股策略。
- 七星独立卖出和买入回调。
- 多策略资金比例。
- 虚拟子账户。
- `stock_strategy` 或类似持仓归属逻辑。

## 任务 4：验证

状态：已完成。

已执行验证：

```powershell
python -m py_compile reports/jq_wufu_fixed_pool_v12c_ultra_split.py
python -m py_compile reports/jq_fusion_etf_rotation_v1.py
python -m pytest tests/test_fusion_etf_rotation.py::test_joinquant_fusion_export_is_single_strategy_clean -q
python -m pytest tests/test_wufu_etf_rotation.py tests/test_fusion_etf_rotation.py -q
python -m pytest -q
```

结果：

- 聚宽基准脚本语法检查通过。
- 聚宽融合脚本语法检查通过。
- 融合脚本清洁度测试通过。
- 五福和融合策略聚焦测试通过。
- 全量测试通过。

## Git 记录

本轮工作已提交到本地 Git：

```text
a89e0a5 feat: add fused wufu qixing etf rotation
```

本次中文文档调整应作为后续单独提交。

## 后续可迭代方向

- 对七星增强参数做分段回测，确认加分是否真正改善收益/回撤。
- 增加溢价率、成交额异常、短周期动量等更细的七星过滤项。
- 将聚宽脚本和本地模块的关键排序结果做逐日对账。
- 在 Streamlit 工作台中增加融合策略的研究入口。
