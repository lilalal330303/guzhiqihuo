# 固收+稳定策略档案接入 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `joinquant_fixed_plus_stable_current.py` 以“固收+策略”接入现有稳定策略档案库，并通过 GitHub Actions 自动部署到腾讯云静态托管。

**Architecture:** 保持现有单页档案库的策略注册表架构，在 `strategy-024.html` 中新增 `fixedplus` 配置对象和切换标签；复制稳定版聚宽脚本为归档资产，但不修改其交易逻辑。发布沿用仓库现有的 CloudBase Actions 工作流。

**Tech Stack:** 静态 HTML/CSS/JavaScript、JoinQuant Python3 脚本、Git、GitHub Actions、CloudBase CLI 静态托管。

## Global Constraints

- 只接入 `joinquant_fixed_plus_stable_current.py`，不接入 selected/aggressive 路线。
- 不修改固收+交易逻辑、参数和执行函数。
- 页面不新增下载入口。
- 不把目标波动率、配置比例等参数冒充为收益回测结果；无收益快照处明确写“待补录”。
- 公开页面必须继续支持已有四个策略，并新增 `#fixedplus`。

---

### Task 1: 建立归档展示数据与资产

**Files:**
- Create: `fixed-plus-stable.py`
- Modify: `strategy-024.html`
- Modify: `strategy-024.css`
- Modify: `index.html`

**Interfaces:**
- `strategy-024.html` 继续通过 `strategies.fixedplus` 提供页面字段、指标、参数、证据和运行注意事项。
- `fixed-plus-stable.py` 是根目录中的原始稳定版脚本副本，内容与研究目录源文件一致。

- [ ] **Step 1: 复制并核对稳定版脚本**

  将 `C:\Users\16052\Documents\量化研究\joinquant_fixed_plus_stable_current.py` 复制为档案库根目录 `fixed-plus-stable.py`，并用 SHA-256 比对两个文件完全一致。

- [ ] **Step 2: 新增 fixedplus 主题色与第五个标签**

  在 `strategy-024.css` 增加 `body[data-theme="fixedplus"]` 的蓝青色变量；在 `strategy-024.html` 增加：

  ```html
  <button class="strategy-tab" type="button" role="tab" aria-selected="false" data-strategy="fixedplus">固收+策略</button>
  ```

  并把“STABLE STRATEGY ARCHIVE / 四套成熟版本”改为“五套成熟版本”，meta description 同步增加“固收+策略”。

- [ ] **Step 3: 注册 fixedplus 策略对象**

  在 `smallcap` 对象之后、注册表结束前新增 `fixedplus`，使用以下可由脚本直接核对的事实：

  ```javascript
  fixedplus: {
    name: "固收+策略",
    shortName: "固收+策略",
    theme: "fixedplus",
    status: "稳定版 · stable-v1.0 参数锁定",
    version: "Stable · V1.0",
    title: "固收+<br><em>稳健配置</em>",
    lead: "以 511010.XSHG 债券核心为底仓，叠加现金管理、黄金、红利与海外资产卫星仓位；通过风险资产逆波动分配、组合波动率上限和现金缓冲，把收益弹性与回撤边界写进执行层。",
    period: "稳定版 V1.0",
    benchmark: "511010.XSHG",
    evidenceScope: "脚本参数归档 · 收益快照待补录",
    heroReturn: "6.00<sup>% 目标波动</sup>",
    heroNote: "稳定版参数锁定 · 目标年化波动率 6%",
    chartStart: "债券核心",
    chartEnd: "风险卫星",
    chartLeft: "60% 511010",
    chartRight: "35% 风险资产",
    snapshotNote: "本档案先固定可复核的策略结构和执行边界；当前仓库未附固收+独立长周期收益快照，因此不填入未经核验的收益、回撤或夏普数据。",
    metrics: [
      ["债券核心", "60%"],
      ["现金管理", "5%"],
      ["风险资产卫星", "35%"],
      ["目标年化波动", "6%"],
      ["再平衡周期", "20 交易日"],
      ["现金缓冲", "2%"]
    ],
    extraMetrics: "风险资产按近 60 日波动率倒数分配；最低上市 60 日；100 份整手；停牌、涨跌停和现金不足时跳过或约束交易。",
    methodTitle: "债券打底，风险预算决定卫星仓位",
    methodIntro: "固收+稳定版不追求复杂择时，而是先锁定债券核心和现金管理底座，再在黄金、红利和海外资产之间分配风险资产预算。每次调仓前先检查历史波动率与组合实现波动率，超出目标时把风险资产权重转入现金管理 ETF。",
    principles: [
      ["01", "核心底仓", "511010.XSHG 配置 60%，511990.XSHG 配置 5%，形成债券与现金管理底座。"],
      ["02", "风险预算", "518880、510880、513100 组成风险卫星，按近 60 日波动率倒数分配风险预算。"],
      ["03", "波动率护栏", "组合实现年化波动率超过 6% 时缩减风险资产，并保留 2% 现金缓冲。"]
    ],
    flow: [
      ["01", "建立目标权重", "读取稳定版五资产配置并清理、归一化有效权重。"],
      ["02", "风险资产预算", "读取近 60 个交易日历史价格，按波动率倒数重新分配风险资产预算。"],
      ["03", "组合波动检查", "计算组合实现波动率，超出 6% 时把风险资产部分转入现金管理 ETF。"],
      ["04", "执行再平衡", "每 20 个交易日先卖后买，检查停牌、涨跌停、整手和可用现金。"]
    ],
    engineTitle: "固定配置 + 逆波动风险预算",
    engineIntro: "信号引擎只承担风险预算和执行约束，不用未经验证的择时、趋势或残差动量模块覆盖稳定版原始结构。",
    factors: [
      ["60%", "债券核心", "511010.XSHG 作为基准与稳定底仓，目标权重 60%。"],
      ["5%", "现金管理", "511990.XSHG 作为现金代理，兼顾现金缓冲与超额风险转移。"],
      ["1/σ", "风险预算", "黄金、红利、海外风险资产按近 60 日年化波动率倒数分配卫星预算。"],
      ["6%", "波动护栏", "组合实现波动率超过目标时，风险资产按比例缩放并转入现金代理。"]
    ],
    formula: "Target = normalize(fixed core + inverse-vol risk budget + volatility cap + 2% cash buffer)",
    parameterIntro: "这些参数是稳定版的可复现边界，展示的是脚本事实而不是收益承诺。",
    parameters: [
      ["版本", "stable-v1.0 · 固收+当前稳定版"],
      ["基准", "<code>511010.XSHG</code>"],
      ["目标权重", "511010 60% · 511990 5% · 518880 10% · 510880 12.5% · 513100 12.5%"],
      ["风险预算窗口", "60 个交易日"],
      ["目标年化波动", "6%"],
      ["再平衡周期", "20 个交易日"],
      ["调仓阈值", "目标权重偏离超过 15%"],
      ["现金缓冲", "2%"],
      ["最低上市时间", "60 个自然日"],
      ["整手约束", "100 份"],
      ["手续费", "基金开平仓佣金 0.02%，最低 5 元"],
      ["执行顺序", "先卖后买 · 扣除现金缓冲后买入"]
    ],
    evidenceIntro: "目前可核验的证据是脚本版本、资产配置、风险预算和执行护栏；收益快照需在聚宽完成统一区间回测后再补入，避免把配置目标误读为历史表现。",
    evidence: [
      ["稳定版本", "stable-v1.0", "策略定位", "固收+稳定版"],
      ["债券核心", "65% 合计", "风险卫星", "35% 初始配置"],
      ["风险预算", "60 日逆波动", "波动护栏", "6% 年化目标"],
      ["调仓周期", "20 交易日", "调仓阈值", "15% 偏离"],
      ["现金缓冲", "2%", "整手约束", "100 份"],
      ["收益快照", "待补录", "证据口径", "脚本参数可复核"]
    ],
    calloutTitle: "先把边界固定，再补回测证据",
    calloutText: "固收+策略的核心价值在于风险预算和执行边界。下一次回测应使用统一区间、基准、手续费和初始资金，并单独记录收益、波动、最大回撤与现金占用。",
    bars: [["债券/现金核心", "65%", "65%", ""], ["风险资产卫星", "35%", "35%", "benchmark"], ["目标波动率", "60%", "6%", "risk"]],
    notes: [
      ["适合：追求稳健波动边界", "底仓、现金缓冲和波动率护栏适合希望控制组合波动、又保留有限风险资产弹性的研究账户。", ""],
      ["适合：按统一口径做回测", "正式使用前应补录聚宽长周期回测，并核对 ETF 上市时间、成交可得性、滑点和现金占用。", ""],
      ["不适合：把目标波动当收益保证", "6% 是风险目标，不是收益承诺；资产净值仍会受到利率、权益、黄金、海外市场和执行价格影响。", "warn"]
    ],
    closingTitle: "稳健不是静止，而是把风险写进每一次调仓。",
    closingText: "固收+策略固定为 stable-v1.0 参数档案。后续如需迭代，应先补齐统一回测证据，再一次只验证一个风险预算或执行变量。",
    footerName: "固收+策略 · stable-v1.0"
  }
  ```

- [ ] **Step 4: 更新入口页**

  在 `index.html` 的稳定策略卡片文案中增加“固收+策略”，将“四套成熟策略”改为“五套成熟策略”。

### Task 2: 页面与脚本验证

**Files:**
- Test: `strategy-024.html`, `fixed-plus-stable.py`, `index.html`

- [ ] **Step 1: 验证静态引用与标签**

  检查 `#fixedplus`、`strategies.fixedplus`、`body[data-theme="fixedplus"]`、`stable-v1.0` 和 `fixed-plus-stable.py` 均存在；检查已有 `value/wufu/fuxing/smallcap` 仍存在。

- [ ] **Step 2: 验证脚本归档完整性**

  运行 SHA-256 比对，预期源文件与归档文件哈希相同；运行 `python -m py_compile fixed-plus-stable.py` 不能直接成功，因为脚本依赖聚宽 `jqdata`，因此使用 AST 解析验证语法，不导入 `jqdata`。

- [ ] **Step 3: 运行项目测试与差异检查**

  在主工作区运行 `python -m pytest tests/test_joinquant_fixed_plus_exports.py -q`；在档案库工作树运行 `git diff --check`。

### Task 3: Git 与 CloudBase 发布

**Files:**
- Modify: `.github/workflows/deploy-cloudbase.yml`（仅在验证发现需要时修改；默认不改）

- [ ] **Step 1: 检查发布范围并提交**

  只暂存本次新增/修改的档案文件、脚本副本、设计/计划文档；不暂存 `.superpowers/` 或主工作区未关联变更。提交信息使用 `feat: add fixed-plus stable strategy archive`。

- [ ] **Step 2: 推送 main**

  推送到 `origin/main`，记录提交 SHA。

- [ ] **Step 3: 验证 Actions**

  等待 `Deploy stable strategy archive to CloudBase` 的最新运行与本次提交 SHA 对齐，并确认 `deploy` 作业、`Log in to CloudBase`、`Deploy static site to hosting root` 均成功。

- [ ] **Step 4: 验证公开站点**

  检查根地址和 `strategy-024.html#fixedplus` 返回 HTTP 200，并确认公开 HTML 中包含“固收+策略”“stable-v1.0”“风险预算”。
