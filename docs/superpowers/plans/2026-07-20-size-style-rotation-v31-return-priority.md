# 大小盘反复横跳 V3.1 收益优先型实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变 V3.0 原始复制模式默认行为的前提下，交付一个可在聚宽直接运行的 V3.1 参数实验脚本，用单变量实验识别收益来源并筛选收益保持型参数。

**Architecture:** V3.1 作为独立、可复制到聚宽的单文件脚本，不依赖本地 `quant_lab` 模块；V3.0 原始复制脚本保持不变，V3.1 仅在顶部增加参数入口，并通过小型纯函数实现参数切换、分支持仓数、组合权重和诊断日志。所有默认值与 V3.0 一致，实验通过修改顶部常量完成。

**Tech Stack:** JoinQuant Python 3、`jqdata`、NumPy、Pandas、pytest、AST 静态检查。

## Global Constraints

- 默认运行模式必须是 `ORIGINAL_REPLICA`，基线默认参数必须为 `STYLE_WINDOW=20`、`STYLE_THRESHOLD=1.2`、`STOCK_NUM=5`。
- 基准必须保持 `000985.XSHG`，默认调仓仍为每月第一个交易日 `09:30`。
- 默认滑点必须为 `FixedSlippage(0)`，原始佣金和印花税设置不得改变。
- 默认选股、日期语义、涨跌停处理、候选失败保护和交易调度不得改变。
- 不得重新加入趋势确认、波动率归一化、`risk_off`、滞后确认、候选缓冲、市场保护、winsorization 或强制保留旧持仓。
- 不得使用 `pivot_table(sort=...)`；必须兼容当前聚宽 Pandas 环境。
- 每个实验只改变一个主要变量；只有通过阶段性门槛的变量才进入组合实验。
- 不修改 `reports/joinquant_size_style_rotation_v30_original_replica.py`；该文件是不可变的原始基线。
- 现有工作区中与本策略无关的未提交修改和未跟踪文件必须保持原样。

---

## 文件地图

| 文件 | 职责 |
|---|---|
| `reports/joinquant_size_style_rotation_v30_original_replica.py` | V3.0 不可变基线，只读参考 |
| `reports/joinquant_size_style_rotation_v31_return_priority.py` | 新建的独立聚宽 V3.1 参数实验脚本 |
| `reports/joinquant_size_style_rotation_v31_return_priority_readme.md` | V3.1 复制、参数、实验顺序和回测记录说明 |
| `reports/joinquant_size_style_rotation_v31_experiment_log_template.md` | 单变量实验记录模板和验收表 |
| `tests/test_joinquant_size_style_rotation_v31_return_priority.py` | V3.1 纯函数、默认行为和源代码约束测试 |

## Task 1: 建立 V3.1 失败测试和默认契约

**Files:**
- Create: `tests/test_joinquant_size_style_rotation_v31_return_priority.py`
- Read only: `reports/joinquant_size_style_rotation_v30_original_replica.py`
- Read only: `docs/superpowers/specs/2026-07-20-size-style-rotation-v31-return-priority-design.md`

**Interfaces:**
- Consumes: V3.0 的模块加载方式、`jqdata` stub、`select_style_branch` 语义。
- Produces: 后续脚本必须提供的常量和函数契约：`STYLE_WINDOW`、`STYLE_THRESHOLD`、`STOCK_NUM`、`USE_BRANCH_STOCK_NUM`、`SMALL_STOCK_NUM`、`BIG_STOCK_NUM`、`POSITION_WEIGHT_MODE`、`SLIPPAGE_VALUE`、`REBALANCE_TIME`、`target_stock_num(branch)`、`allocation_weights(context, securities)`。

- [ ] **Step 1: 创建可加载 JoinQuant 脚本的测试夹具**

复制 V3.0 测试中的 `jqdata` stub 加载方式，但测试目标改为 V3.1：

```python
SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "reports"
    / "joinquant_size_style_rotation_v31_return_priority.py"
)

@pytest.fixture
def module():
    missing = object()
    previous = sys.modules.get("jqdata", missing)
    sys.modules["jqdata"] = types.ModuleType("jqdata")
    name = "joinquant_size_style_rotation_v31_return_priority_test"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[name] = loaded
    try:
        spec.loader.exec_module(loaded)
        yield loaded
    finally:
        sys.modules.pop(name, None)
        if previous is missing:
            sys.modules.pop("jqdata", None)
        else:
            sys.modules["jqdata"] = previous
```

- [ ] **Step 2: 写默认参数契约测试**

```python
def test_v31_defaults_preserve_v30_baseline(module):
    assert module.RUN_MODE == "ORIGINAL_REPLICA"
    assert module.STYLE_WINDOW == 20
    assert module.STYLE_THRESHOLD == 1.2
    assert module.STOCK_NUM == 5
    assert module.USE_BRANCH_STOCK_NUM is False
    assert module.SMALL_STOCK_NUM == 5
    assert module.BIG_STOCK_NUM == 5
    assert module.POSITION_WEIGHT_MODE == "EQUAL"
    assert module.SLIPPAGE_VALUE == 0
    assert module.REBALANCE_TIME == "09:30"
```

- [ ] **Step 3: 写风格阈值和持仓数量边界测试**

```python
def test_threshold_is_a_single_parameter(module):
    assert module.select_style_branch(30.0, 20.0, 1.5) == "SMALL"
    assert module.select_style_branch(30.0, 20.0, 1.4) == "BIG"

def test_common_stock_num_is_the_default_for_both_branches(module):
    module.USE_BRANCH_STOCK_NUM = False
    module.STOCK_NUM = 8
    assert module.target_stock_num("SMALL") == 8
    assert module.target_stock_num("BIG") == 8

def test_branch_stock_num_is_opt_in(module):
    module.USE_BRANCH_STOCK_NUM = True
    module.SMALL_STOCK_NUM = 8
    module.BIG_STOCK_NUM = 3
    assert module.target_stock_num("SMALL") == 8
    assert module.target_stock_num("BIG") == 3
```

同时验证窗口参数会传入行情接口：

```python
def test_style_window_controls_price_count(module):
    calls = {}
    module.get_price = lambda *args, **kwargs: calls.update(kwargs) or pd.DataFrame(
        {"close": [10.0]}, index=pd.to_datetime(["2020-01-01"])
    )
    module.STYLE_WINDOW = 40
    module._style_prices(["A"], date(2020, 1, 1))
    assert calls["count"] == 40
```

- [ ] **Step 4: 写等权和轻度市值权重的纯函数测试**

```python
def test_equal_weights_are_deterministic(module):
    module.POSITION_WEIGHT_MODE = "EQUAL"
    assert module.allocation_weights(None, ["A", "B"]) == {
        "A": 0.5,
        "B": 0.5,
    }

def test_market_cap_light_weights_are_normalized(module):
    module.POSITION_WEIGHT_MODE = "MARKET_CAP_LIGHT"
    module.get_market_caps = lambda _context, securities: {
        "A": 100.0,
        "B": 400.0,
    }
    weights = module.allocation_weights(None, ["A", "B"])
    assert sum(weights.values()) == pytest.approx(1.0)
    assert weights["B"] > weights["A"]
```

- [ ] **Step 5: 写源代码禁用路径测试**

断言 V3.1 源代码不含 `risk_off`、`candidate_buffer`、`winsorize`、`market_guard`、`hysteresis`、`pivot_table(sort=`，且仍包含 `FixedSlippage(0)`、`count=20` 默认值和每月 `09:30` 调度。

- [ ] **Step 6: 运行测试，确认当前必然失败**

Run:

```text
pytest tests/test_joinquant_size_style_rotation_v31_return_priority.py -q
```

Expected: FAIL because the V3.1 script and its parameter interfaces do not exist yet。此失败只验证测试先行，不修改 V3.0。

- [ ] **Step 7: Commit**

```text
git add tests/test_joinquant_size_style_rotation_v31_return_priority.py
git commit -m "test: define size-style rotation v3.1 contract"
```

## Task 2: 创建独立 V3.1 脚本并参数化风格信号

**Files:**
- Create: `reports/joinquant_size_style_rotation_v31_return_priority.py`
- Test: `tests/test_joinquant_size_style_rotation_v31_return_priority.py`
- Read only: `reports/joinquant_size_style_rotation_v30_original_replica.py`

**Interfaces:**
- Consumes: Task 1 的常量和函数契约。
- Produces: 可直接复制到聚宽的完整独立脚本；默认运行行为与 V3.0 一致。

- [ ] **Step 1: 复制 V3.0 为 V3.1 独立脚本**

复制完整脚本后，只对 V3.1 文件做修改；不得在聚宽脚本中通过本地 import 依赖 V3.0。保留 V3.0 的 JoinQuant 兼容适配器、日期适配器、过滤器、订单封装和涨停保护逻辑。

- [ ] **Step 2: 在脚本顶部加入唯一参数入口**

在指数常量之后加入以下配置，默认值必须保持不变：

```python
STYLE_WINDOW = 20
STYLE_THRESHOLD = 1.2
STOCK_NUM = 5
USE_BRANCH_STOCK_NUM = False
SMALL_STOCK_NUM = 5
BIG_STOCK_NUM = 5
POSITION_WEIGHT_MODE = "EQUAL"
SLIPPAGE_VALUE = 0
REBALANCE_TIME = "09:30"
EXPERIMENT_ID = "V31_BASE"
```

- [ ] **Step 3: 实现分支持仓数接口并保持默认等价**

加入：

```python
def target_stock_num(branch):
    if USE_BRANCH_STOCK_NUM:
        if branch == "SMALL":
            return int(SMALL_STOCK_NUM)
        if branch == "BIG":
            return int(BIG_STOCK_NUM)
    return int(STOCK_NUM)
```

将 `SMALL(context)` 和 `BIG(context)` 改为接收可选 `stock_num`，未传入时使用 `g.stock_num`；将 `select_target_list(context, branch)` 改为传入 `target_stock_num(branch)`。默认 `USE_BRANCH_STOCK_NUM=False` 时，所有默认查询、切片和目标数量必须仍为 5。

- [ ] **Step 4: 参数化风格窗口和阈值**

将 `_style_prices` 的 `count=20` 改为 `count=STYLE_WINDOW`，并将 `weekly_adjustment` 中的：

```python
branch = select_style_branch(mean_2000, mean_500, 1.2)
```

改为：

```python
branch = select_style_branch(
    mean_2000,
    mean_500,
    STYLE_THRESHOLD,
)
```

同时保留默认 `STYLE_WINDOW=20` 和 `STYLE_THRESHOLD=1.2`。

- [ ] **Step 5: 参数化滑点和调仓时间**

将初始化中的：

```python
set_slippage(FixedSlippage(0))
run_monthly(weekly_adjustment, 1, time="09:30")
```

改为：

```python
set_slippage(FixedSlippage(SLIPPAGE_VALUE))
run_monthly(weekly_adjustment, 1, time=REBALANCE_TIME)
```

默认配置必须仍然得到零滑点和 `09:30` 调仓。

- [ ] **Step 6: 增加启动和月度诊断日志**

在 `initialize` 中记录：

```python
log.info(
    "V31 params experiment=%s window=%s threshold=%s stock_num=%s "
    "branch_stock_num=%s small_num=%s big_num=%s weight_mode=%s "
    "slippage=%s rebalance_time=%s",
    EXPERIMENT_ID,
    STYLE_WINDOW,
    STYLE_THRESHOLD,
    STOCK_NUM,
    USE_BRANCH_STOCK_NUM,
    SMALL_STOCK_NUM,
    BIG_STOCK_NUM,
    POSITION_WEIGHT_MODE,
    SLIPPAGE_VALUE,
    REBALANCE_TIME,
)
```

月度日志继续记录分支、两个均值、目标列表、调仓前后持仓、卖出列表和买入列表；新增 `style_window`、`style_threshold` 和 `experiment_id` 字段。

- [ ] **Step 7: 运行 V3.1 单元测试和语法检查**

Run:

```text
pytest tests/test_joinquant_size_style_rotation_v31_return_priority.py -q
python -m py_compile reports/joinquant_size_style_rotation_v31_return_priority.py
```

Expected: all V3.1 tests pass，`py_compile` 无输出且退出码为 0。

- [ ] **Step 8: Commit**

```text
git add reports/joinquant_size_style_rotation_v31_return_priority.py tests/test_joinquant_size_style_rotation_v31_return_priority.py
git commit -m "feat: add parameterized size-style rotation v3.1"
```

## Task 3: 完成组合权重实验接口

**Files:**
- Modify: `reports/joinquant_size_style_rotation_v31_return_priority.py`
- Modify: `tests/test_joinquant_size_style_rotation_v31_return_priority.py`

**Interfaces:**
- Consumes: Task 2 的 `POSITION_WEIGHT_MODE` 和原始 `weekly_adjustment` 买入流程。
- Produces: `get_market_caps(context, securities)` 和 `allocation_weights(context, securities)`；默认 `EQUAL` 不调用额外基本面查询。

- [ ] **Step 1: 写权重接口失败测试**

补充以下测试：

```python
def test_equal_mode_does_not_query_market_caps(module):
    module.POSITION_WEIGHT_MODE = "EQUAL"
    module.get_market_caps = lambda *_args: pytest.fail("not needed")
    assert module.allocation_weights(None, ["A", "B", "C"]) == {
        "A": pytest.approx(1 / 3),
        "B": pytest.approx(1 / 3),
        "C": pytest.approx(1 / 3),
    }

def test_empty_weight_input_returns_empty_mapping(module):
    assert module.allocation_weights(None, []) == {}
```

- [ ] **Step 2: 实现市值读取适配器**

实现：

```python
def get_market_caps(context, securities):
    if not securities:
        return {}
    cap_query = query(valuation.code, valuation.market_cap).filter(
        valuation.code.in_(securities)
    )
    try:
        frame = get_fundamentals(
            cap_query,
            date=fundamental_date(context),
        )
    except Exception as exc:
        log.warn("market-cap weights unavailable: %s" % exc)
        return {}
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return {}
    result = {}
    for _, row in frame.iterrows():
        code = row.get("code")
        cap = pd.to_numeric(row.get("market_cap"), errors="coerce")
        if code in securities and pd.notna(cap) and float(cap) > 0:
            result[code] = float(cap)
    return result
```

- [ ] **Step 3: 实现权重归一化**

实现：

```python
def allocation_weights(context, securities):
    securities = list(dict.fromkeys(securities or []))
    if not securities:
        return {}
    if POSITION_WEIGHT_MODE == "EQUAL":
        weight = 1.0 / len(securities)
        return {security: weight for security in securities}
    if POSITION_WEIGHT_MODE != "MARKET_CAP_LIGHT":
        log.warn("unknown weight mode %s; fallback to equal" % POSITION_WEIGHT_MODE)
        weight = 1.0 / len(securities)
        return {security: weight for security in securities}
    caps = get_market_caps(context, securities)
    if len(caps) != len(securities):
        weight = 1.0 / len(securities)
        return {security: weight for security in securities}
    scores = {security: np.sqrt(caps[security]) for security in securities}
    total = sum(scores.values())
    if not np.isfinite(total) or total <= 0:
        weight = 1.0 / len(securities)
        return {security: weight for security in securities}
    return {security: scores[security] / total for security in securities}
```

- [ ] **Step 4: 接入买入分配但保持默认等权**

在卖出完成并得到 `buy_list` 后，使用：

```python
_, slot_count = buy_allocation(
    len(context.portfolio.positions),
    target_num,
    cash,
)
eligible_buy_list = list(buy_list[:max(slot_count, 0)])
weights = allocation_weights(context, eligible_buy_list)
allocations = {
    stock: cash * weights[stock]
    for stock in eligible_buy_list
    if stock in weights
}
```

买入循环从 `allocations.get(stock, 0.0)` 取目标金额；空金额不下单，并继续以 `slot_count` 和实时持仓数量限制订单数。`POSITION_WEIGHT_MODE="EQUAL"` 时，结果必须与当前“可用现金除以可买槽位数”一致。保留 `buy_allocation` 纯函数用于默认行为测试和诊断。

- [ ] **Step 5: 运行权重测试和全局静态约束测试**

Run:

```text
pytest tests/test_joinquant_size_style_rotation_v31_return_priority.py -q
python -m py_compile reports/joinquant_size_style_rotation_v31_return_priority.py
```

Expected: all tests pass；默认模式不发起市值查询，源代码没有历史失败路径。

- [ ] **Step 6: Commit**

```text
git add reports/joinquant_size_style_rotation_v31_return_priority.py tests/test_joinquant_size_style_rotation_v31_return_priority.py
git commit -m "feat: add optional light market-cap weighting"
```

## Task 4: 编写 V3.1 使用说明和实验记录模板

**Files:**
- Create: `reports/joinquant_size_style_rotation_v31_return_priority_readme.md`
- Create: `reports/joinquant_size_style_rotation_v31_experiment_log_template.md`

**Interfaces:**
- Consumes: Task 2 和 Task 3 的确切参数名、默认值和日志字段。
- Produces: 用户可以直接复制脚本、逐项修改参数并记录聚宽结果的文档。

- [ ] **Step 1: 写使用说明的默认配置表**

文档必须明确列出：

```text
RUN_MODE = ORIGINAL_REPLICA
STYLE_WINDOW = 20
STYLE_THRESHOLD = 1.2
STOCK_NUM = 5
USE_BRANCH_STOCK_NUM = False
SMALL_STOCK_NUM = 5
BIG_STOCK_NUM = 5
POSITION_WEIGHT_MODE = EQUAL
SLIPPAGE_VALUE = 0
REBALANCE_TIME = 09:30
```

同时说明 V3.1 是研究回测脚本，不将 `ORIGINAL_REPLICA` 的数据口径等同于实盘无未来函数证明。

- [ ] **Step 2: 写实验顺序**

文档按以下顺序提供可复制配置：

1. 基线：`20 / 1.2 / 5 / EQUAL / 0 / 09:30`；
2. S1：只改变 `STYLE_THRESHOLD` 为 `1.10、1.15、1.25、1.30`；
3. S2：只改变 `STYLE_WINDOW` 为 `10、40、60`；
4. P1：只改变 `STOCK_NUM` 为 `3、8、10`；
5. P2：启用 `USE_BRANCH_STOCK_NUM=True`，只测试 SMALL/BIG 组合；
6. W1：只改变 `POSITION_WEIGHT_MODE="MARKET_CAP_LIGHT"`；
7. X1：只改变 `SLIPPAGE_VALUE` 或 `REBALANCE_TIME`。

每次运行前恢复其他参数为默认值或已通过门槛的值。

- [ ] **Step 3: 写验收表和失败回退规则**

文档必须包含：总收益、年化收益、最大回撤、夏普、胜率、交易次数、换手、空仓月份以及 2020—2021、2022—2023、2024—2026 三个分段的字段。明确候选方案门槛：年化约不低于 40%、总收益约不低于 750%、最大回撤不超过 35%、夏普不低于 1.40。

- [ ] **Step 4: 建立实验记录模板**

模板至少包含以下表头：

```text
实验编号 | 父版本 | 唯一变更参数 | 参数值 | 全样本收益 | 年化收益 |
最大回撤 | 夏普 | 交易次数 | 换手 | 2020-21 | 2022-23 | 2024-26 |
空仓月份 | 目标列表差异 | 是否通过 | 下一步动作 | 备注
```

- [ ] **Step 5: Commit**

```text
git add reports/joinquant_size_style_rotation_v31_return_priority_readme.md reports/joinquant_size_style_rotation_v31_experiment_log_template.md
git commit -m "docs: add size-style rotation v3.1 experiment guide"
```

## Task 5: 本地验证和聚宽基线复核

**Files:**
- Test: `tests/test_joinquant_size_style_rotation_v31_return_priority.py`
- Validate: `reports/joinquant_size_style_rotation_v31_return_priority.py`
- Record template: `reports/joinquant_size_style_rotation_v31_experiment_log_template.md`

**Interfaces:**
- Consumes: 完整 V3.1 脚本、测试、README 和实验模板。
- Produces: 本地静态验证结果，以及用户在聚宽中可复核的基线运行顺序；不凭空生成云回测收益。

- [ ] **Step 1: 运行聚焦测试**

Run:

```text
pytest tests/test_joinquant_size_style_rotation_v31_return_priority.py -q
```

Expected: all V3.1 tests pass。

- [ ] **Step 2: 运行语法检查**

Run:

```text
python -m py_compile reports/joinquant_size_style_rotation_v31_return_priority.py
```

Expected: exit code 0；脚本可被 Python 3 解析。

- [ ] **Step 3: 运行源代码约束检查**

Run:

```text
rg -n "risk_off|candidate_buffer|winsorize|market_guard|hysteresis|pivot_table\(sort=" reports/joinquant_size_style_rotation_v31_return_priority.py
```

Expected: no output。

- [ ] **Step 4: 在聚宽先运行默认基线**

将 V3.1 脚本复制到聚宽 Python3 策略编辑器，使用截图对应的日期、初始资金、基准和分钟频率，保持：

```text
EXPERIMENT_ID = "V31_BASE"
STYLE_WINDOW = 20
STYLE_THRESHOLD = 1.2
STOCK_NUM = 5
USE_BRANCH_STOCK_NUM = False
POSITION_WEIGHT_MODE = "EQUAL"
SLIPPAGE_VALUE = 0
REBALANCE_TIME = "09:30"
```

先确认日志存在持续的风格信号、目标列表和调仓订单；若再次出现连续“style signal unavailable”或无交易，停止参数实验并回到工程排查。

- [ ] **Step 5: 记录基线而不宣称复现收益**

将聚宽实际结果填入模板，至少记录总收益、年化收益、最大回撤、夏普、交易次数、换手、空仓月份和三个分段结果。只有指标和交易行为与原始基线处于同一数量级，才允许进入 S1。

- [ ] **Step 6: 保留云回测记录边界**

聚宽云回测的实际收益和订单日志由用户在平台运行后填入已提交的模板；本地执行阶段不伪造云端指标，也不把未修改的模板重复提交。若用户提供了实际结果，再单独新增基线复核报告并只提交该策略文件。

## Task 6: 执行单变量实验并生成最终参数建议

**Files:**
- Modify: `reports/joinquant_size_style_rotation_v31_experiment_log_template.md`
- Modify: `reports/joinquant_size_style_rotation_v31_return_priority_readme.md`
- Create after actual cloud results are available: `reports/joinquant_size_style_rotation_v31_experiment_report.md`

**Interfaces:**
- Consumes: 聚宽默认基线和各实验实际回测结果。
- Produces: 通过/淘汰路径、最终默认参数建议和明确的回退版本。

- [ ] **Step 1: 完成 S1 风格阈值实验**

每次只修改 `STYLE_THRESHOLD`，保持窗口 20、持仓 5、等权、零滑点、09:30。记录完整样本和三个分段指标。将未达到门槛的阈值标记为淘汰，不进行二次组合。

- [ ] **Step 2: 完成 S2 风格窗口实验**

以默认阈值 1.2 或 S1 通过的唯一阈值为父版本，每次只修改 `STYLE_WINDOW`。窗口必须至少满足跨两个分段不崩溃，才进入 P1。

- [ ] **Step 3: 完成 P1/P2 持仓数量实验**

先测试共用 `STOCK_NUM`，再在共用参数通过后测试 `USE_BRANCH_STOCK_NUM=True` 的 SMALL/BIG 组合。不得同时修改风格窗口和持仓数量。

- [ ] **Step 4: 完成 W1 权重实验**

固定通过的风格和持仓参数，仅比较 `EQUAL` 与 `MARKET_CAP_LIGHT`。如果市值查询不可用，日志必须明确回退为等权；不能把数据缺失当作权重策略收益。

- [ ] **Step 5: 完成 X1 成本和时间敏感性实验**

固定信号和组合结构，分别测试滑点与调仓时间。该阶段只判断收益对现实执行条件的敏感性，不用乐观成本提升排名。

- [ ] **Step 6: 形成最终参数建议**

只选择满足门槛且至少两个分段有效的候选。最终脚本默认值必须明确写入 README，并保留 `V31_BASE` 作为一键回退配置。

- [ ] **Step 7: 运行最终验证**

Run:

```text
pytest tests/test_joinquant_size_style_rotation_v31_return_priority.py -q
python -m py_compile reports/joinquant_size_style_rotation_v31_return_priority.py
```

Expected: all tests pass；最终脚本默认配置仍通过 V3.1 基线契约，且历史失败路径静态检查无输出。

- [ ] **Step 8: Commit 最终实验记录**

```text
git add reports/joinquant_size_style_rotation_v31_experiment_log_template.md reports/joinquant_size_style_rotation_v31_return_priority_readme.md
git add reports/joinquant_size_style_rotation_v31_experiment_report.md
git commit -m "docs: record size-style rotation v3.1 experiment results"
```

只有在 `reports/joinquant_size_style_rotation_v31_experiment_report.md` 已由实际聚宽结果生成后，才执行第二条 `git add`；没有云端结果时只提交前两份文档。

## 完成定义

只有以下条件全部满足，V3.1 才算完成：

1. V3.0 原始基线文件未被修改；
2. V3.1 可独立复制到聚宽运行；
3. 默认参数与原始基线一致；
4. 本地聚焦测试和 `py_compile` 通过；
5. 聚宽默认运行有持续信号、候选列表和订单；
6. 实验记录包含全样本和三个时间分段；
7. 最终参数没有依赖已经淘汰的趋势确认、risk-off、候选缓冲或其他失败路径；
8. README 明确最终参数和 V3.0/V3.1 回退方式。
