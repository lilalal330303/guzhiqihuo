# 铁矿石 CTA V1.5 结构化日志设计

## 目标

在不改变 V1.5 信号、参数、仓位计算、换月和下单逻辑的前提下，增加能够与聚宽 `transaction.csv`、`position.csv` 以及 `log.zip` 对账的结构化日志。

## 范围

- 以 `reports/jq_iron_ore_cta_v1_5_post2024.py` 为基础输出一个可直接粘贴到聚宽的完整脚本。
- 只增加日志辅助函数、日志调用和日志开关，不调整策略参数与交易决策。
- 不写本地文件，不依赖自定义库，不使用 Python 3.7 以上特性，避免聚宽加载兼容性问题。

## 日志格式

日志统一使用单行键值格式，前缀为 `JQ_AUDIT|<事件>|`，字段使用稳定的英文键名，方便从 GBK 日志中解析。

### DAILY

每日 `trade_open` 至少记录：

- `date`, `regime`, `raw_signal`, `target_direction`
- `target_contract`, `current_contract`, `current_direction`, `current_amount`
- `close`, `ma_fast`, `ma_slow`, `slope`, `efficiency`, `vol_ratio`, `realized_vol`, `atr`
- `trend_multiplier`, `regime_multiplier`, `drawdown_multiplier`, `risk_multiplier`
- `total_value`, `available_cash`, `high_water`, `drawdown`
- `decision`, `reason`

即使数据不足、没有主力合约或处于冷却期，也记录一条 `DAILY`，以便区分“无信号”“无合约”“风控拒绝”和“持仓管理”。

### ORDER

开仓和平仓委托后记录：

- `date`, `signal_date`, `action`, `code`, `direction`
- `requested`, `filled`, `remaining`, `status`
- `price`, `avg_cost`, `commission`, `realized_pnl`
- `position_before`, `position_after`, `total_value_after`, `available_cash_after`

聚宽订单对象缺失的字段使用空值，不让日志逻辑影响下单；字段读取通过安全属性访问完成。

### POSITION

每次委托后记录当前实际持仓和资金快照：

- `date`, `code`, `direction`, `amount`, `avg_cost`, `price`
- `total_value`, `cash`, `available_cash`, `margin`

## 日志控制

- `AUDIT_LOG_ENABLED = True`：控制结构化审计日志总开关。
- `AUDIT_LOG_LEVEL = "full"`：`full` 记录 DAILY、ORDER、POSITION；`order` 只记录订单和持仓；`off` 关闭新增日志。
- 原有策略提示日志保留。
- 结构化字段中的数字统一转为有限小数，避免 `nan`、对象 repr 或超长日志污染解析。

## 兼容性与安全边界

- 兼容聚宽策略脚本的全局 `log.info` / `log.warn` 环境。
- 不引入 `from __future__ import annotations`，不导入项目内模块。
- 对订单状态、成交数量、成交价格、手续费、持仓字段采用 `getattr` 安全读取。
- 日志失败不得阻断策略：格式化和字段转换遇到异常时降级为简短日志。
- 不在日志中输出账号凭证或无关对象的完整 repr。

## 验证

- 脚本通过 Python 语法编译检查。
- 现有 V1.5 关键函数和参数保持不变。
- 使用轻量 mock 验证：数据不足、空仓、开仓、平仓、部分成交、完全成交、冷却期均能生成结构化日志且不抛异常。
- 对最终脚本做关键字扫描，确认不包含项目内 `reports.*` 导入或未来注解导入。
