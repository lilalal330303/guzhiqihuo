# 五福 ETF V9 弱市同步迭代说明

## 本轮目标

V8 日志显示同花顺 A500 日线不可用，但脚本仍用前三个指数运行自动弱市，导致弱市匹配率降到 89.84%，目标匹配率降到 90.60%。V9 的目标是先恢复同步主线：四个弱市指数缺一不可，A500 缺失时强制回退到统一弱市日历/回放弱市。

## 已完成改动

### 同花顺 V9

脚本：`reports/ths_wufu_fast_v9_weak_calendar_fallback.py`

改动：

1. `WEAK_MIN_VALID_INDEXES` 从 3 改为 4。
2. 四个指数中任意一个日线不足，立即触发 `WUFU_WEAK_FALLBACK`。
3. 新增弱市日历版本：`joinquant_v4_ranges_20200102_20260706_v9`。
4. 新增统一日志：
   - `WUFU_WEAK_SOURCE date=... mode=fallback|auto weak=... valid=... min_valid=4 version=... source=...`
   - `WUFU_A500_SOURCE date=... resolved=... status=missing|ok ...`
5. 保留 V8 执行层规则：0.2% 现金缓冲、成本预留、100 份向下取整、`estimated_cost / residual_cash / round_lot`。

预期：

- 如果同花顺仍取不到 A500，则每天应看到 `mode=fallback`。
- 弱市匹配率应从 V8 的 89.84% 回到接近 V7 的 100%。
- 目标匹配率应从 V8 的 90.60% 回到 V7 附近，目标约 98%。

### 聚宽 V9

脚本：`reports/jq_wufu_fixed_pool_v9_weak_calendar_fallback.py`

改动：

1. 初始化版本升级为 `WUFU_JQ_FIXED_POOL_V9`。
2. 新增相同的弱市日历版本字段。
3. 新增统一日志：
   - `WUFU_WEAK_SOURCE date=... mode=auto weak=... valid=... min_valid=4 version=... source=index`
4. 保留 V8 执行层规则。

## 验收重点

下一轮平台日志重点看：

1. 同花顺是否出现 `WUFU_WEAK_SOURCE mode=fallback`。
2. 同花顺 `WUFU_A500_SOURCE` 是否仍为 `status=missing`。
3. 弱市匹配率是否恢复到 95% 以上。
4. 目标匹配率是否恢复到 95% 以上。
5. `order_fail` 是否继续为 0。

## 输出文件

- 同花顺 V9：`reports/ths_wufu_fast_v9_weak_calendar_fallback.py`
- 同花顺 V9 中文副本：`reports/同花顺_聚宽五福ETF同步快速V9_弱市日历兜底.py`
- 聚宽 V9：`reports/jq_wufu_fixed_pool_v9_weak_calendar_fallback.py`
- 聚宽 V9 中文副本：`reports/聚宽_五福ETF同步固定池V9_弱市来源日志.py`

