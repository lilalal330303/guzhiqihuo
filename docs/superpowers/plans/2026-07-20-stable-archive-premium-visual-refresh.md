# 稳定策略档案库质感化视觉刷新实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (\`- [ ]\`) syntax for tracking.

**Goal:** 在不改变四个策略数据、公式、切换行为和页面文案边界的前提下，重做稳定策略档案库的视觉层，并将同一份通过验收的页面发布到 GitHub Pages 与现有国内 CDN。

**Architecture:** 保持当前单页数据驱动结构。策略内容继续由 strategy-024.html 内的 strategies 对象驱动，视觉系统集中在 strategy-024.css，只通过 CSS 变量、伪元素、现有类名和现有 motion-refresh 状态实现质感、背景与动效，不增加运行时依赖。

**Tech Stack:** 原生 HTML、CSS、JavaScript；GitHub Pages；现有国内静态 CDN；PowerShell 静态检查与本地 HTTP 预览。

## Global Constraints

- 不改变 value、wufu、fuxing、smallcap 四个 data-strategy 键和对应数据对象。
- 不修改策略公式、收益数字、参数、研究结论或免责声明。
- 不增加框架、字体、图标库、远程图片、外部 CDN、canvas 或音频。
- 不恢复资料来源、下载入口、返回研究主页按钮或 024 可见编号。
- 保留锚点导航、键盘 focus、手机单列布局、无 JavaScript 提示和 prefers-reduced-motion 支持。
- 发布前必须验证页面根地址返回 HTTP 200，并使用同一份最终页面同步到两个平台。

---

### Task 1: 建立质感化视觉令牌与背景层

**Files:**
- Modify: strategy-024.css:1-80
- Test: PowerShell 静态检查，不新增测试框架

**Interfaces:**
- Consumes: 现有 body[data-theme] 主题变量和 .hero、.hero::before、.hero::after 结构。
- Produces: 全站可复用的墨蓝/石墨/冰蓝/香槟金令牌、纸张背景、hero 深度层和稳定的 focus ring。

- [ ] **Step 1: 写视觉不变量检查**

    $site = "C:\Users\16052\Documents\量化研究\.worktrees\strategy-024-showcase-publish"
    $css = Get-Content -Raw -Encoding utf8 "$site\strategy-024.css"
    $html = Get-Content -Raw -Encoding utf8 "$site\strategy-024.html"
    if ($css -notmatch "--ink-dark|--gold|--ice|--surface") { throw "visual tokens missing" }
    if ($css -notmatch "prefers-reduced-motion") { throw "reduced motion rule missing" }
    if ($html -notmatch 'data-strategy="value"|data-strategy="wufu"|data-strategy="fuxing"|data-strategy="smallcap"') { throw "strategy tabs missing" }

    Expected: 当前版本在新增令牌前对第一条检查失败；其余两条通过。

- [ ] **Step 2: 仅在 CSS 顶部增加新令牌与主题派生色**

    保留现有 --accent、--accent-soft 主题入口，并增加 --ink-dark、--gold、--ice、--surface、--surface-strong、--hairline、--shadow-deep 等变量；价值主题使用冰蓝作为主色，其他三主题只改变强调色，不改变页面结构。

- [ ] **Step 3: 重做 body、.hero 与伪元素背景**

    将 body 改为冷白纸张背景叠加两处低透明径向光晕；hero 使用石墨墨蓝渐变、细网格、斜向光带和一层低透明噪点模拟。背景装饰必须 pointer-events: none，不遮挡内容。

- [ ] **Step 4: 运行不变量检查**

    if ($css -notmatch "--gold") { throw "gold token missing" }
    if ($css -notmatch "background-image") { throw "background layer missing" }
    Write-Output "visual token and background checks passed"

    Expected: 输出 visual token and background checks passed。

- [ ] **Step 5: Commit**

    git -C "C:\Users\16052\Documents\量化研究\.worktrees\strategy-024-showcase-publish" add -- strategy-024.css
    git -C "C:\Users\16052\Documents\量化研究\.worktrees\strategy-024-showcase-publish" commit -m "style: add premium archive visual system"

### Task 2: 重做首屏、策略切换器与证据卡片

**Files:**
- Modify: strategy-024.css:60-355
- Test: 本地静态页面检查与浏览器预览

**Interfaces:**
- Consumes: strategy-024.html 现有 .nav、.archive-intro、.strategy-switcher、.hero-grid、.hero-card、.metric、.factor、.parameter、.evidence-callout 类名。
- Produces: 可复用的档案标签、玻璃卡片、指标高光、焦点态和主题切换反馈。

- [ ] **Step 1: 先验证 DOM 合同未变**

    $html = Get-Content -Raw -Encoding utf8 "C:\Users\16052\Documents\量化研究\.worktrees\strategy-024-showcase-publish\strategy-024.html"
    foreach ($selector in @("strategy-switcher", "hero-card", "metric-grid", "factor-grid", "parameter-grid", "evidence-body", "notes-grid")) {
      if ($html -notmatch $selector) { throw "DOM contract missing: $selector" }
    }
    Write-Output "DOM contract passed"

    Expected: 输出 DOM contract passed。

- [ ] **Step 2: 重做导航、档案标题与切换器**

    增加更清晰的细边框、内层高光、选中态金属渐变、选中指示条和键盘 :focus-visible。切换器不改变按钮文字与 data-strategy 属性，不改变布局尺寸跳变。

- [ ] **Step 3: 重做 hero 卡与指标卡**

    为 .hero-card 增加深层内阴影、微妙扫描线、右上角数据轨迹装饰；为 .metric 增加统一的数值层级、左侧主题色边线、hover 微抬升和切换时的 metric-rise 动画。动画只使用 transform/opacity/box-shadow。

- [ ] **Step 4: 统一方法、因子、参数、证据和运行边界卡片**

    采用同一套 radius、hairline、surface、shadow 令牌；公式块保留深色代码语义，表格保持清晰网格和可横向滚动，不修改其中内容。

- [ ] **Step 5: 在 prefers-reduced-motion 下验证**

    $css = Get-Content -Raw -Encoding utf8 "C:\Users\16052\Documents\量化研究\.worktrees\strategy-024-showcase-publish\strategy-024.css"
    if ($css -notmatch "\.strategy-tab:focus-visible") { throw "focus-visible missing" }
    if ($css -notmatch "@media \(prefers-reduced-motion: reduce\)") { throw "reduced motion missing" }
    Write-Output "accessibility motion checks passed"

    Expected: 输出 accessibility motion checks passed。

- [ ] **Step 6: Commit**

    git -C "C:\Users\16052\Documents\量化研究\.worktrees\strategy-024-showcase-publish" add -- strategy-024.css
    git -C "C:\Users\16052\Documents\量化研究\.worktrees\strategy-024-showcase-publish" commit -m "style: refine strategy archive surfaces"

### Task 3: 响应式与动效验收

**Files:**
- Modify: strategy-024.css:158-405 only if checks expose a gap
- Test: 本地 HTTP 预览、桌面/手机宽度检查、策略切换检查

**Interfaces:**
- Consumes: Task 1 的视觉令牌与 Task 2 的卡片样式，现有 motion-refresh 类切换逻辑。
- Produces: 无横向溢出、无动效遮挡、四策略切换状态稳定的最终样式。

- [ ] **Step 1: 启动静态预览**

    $site = "C:\Users\16052\Documents\量化研究\.worktrees\strategy-024-showcase-publish"
    python -m http.server 4173 --directory $site

    Expected: 本地页面可通过 http://127.0.0.1:4173/strategy-024.html 打开。

- [ ] **Step 2: 验证四个策略状态**

    在页面中依次点击 价值投资策略、五福etf、福星etf、小市值策略，确认标题、主题色、收益指标、参数区和证据区均更新；确认浏览器 URL 不发生外部跳转。

- [ ] **Step 3: 验证桌面与手机布局**

    在 1440px 和 390px 宽度检查：首屏无裁切，策略切换器可换行，指标卡不溢出，表格可读，页面无水平滚动条。

- [ ] **Step 4: 验证减弱动效模式**

    启用系统 prefers-reduced-motion 后刷新页面，确认背景停止循环、内容不因等待动画而不可见、策略切换仍然可用。

- [ ] **Step 5: 运行最终静态检查**

    $site = "C:\Users\16052\Documents\量化研究\.worktrees\strategy-024-showcase-publish"
    $html = Get-Content -Raw -Encoding utf8 "$site\strategy-024.html"
    $css = Get-Content -Raw -Encoding utf8 "$site\strategy-024.css"
    if ($html -match "资料来源|下载|返回研究主页|024") { throw "removed public copy reintroduced" }
    if ($html -notmatch 'data-strategy="value"' -or $html -notmatch 'data-strategy="wufu"' -or $html -notmatch 'data-strategy="fuxing"' -or $html -notmatch 'data-strategy="smallcap"') { throw "strategy key regression" }
    if ($css -match "https?://|@import") { throw "external CSS dependency added" }
    Write-Output "final archive checks passed"

    Expected: 输出 final archive checks passed。

- [ ] **Step 6: Commit final visual changes**

    git -C "C:\Users\16052\Documents\量化研究\.worktrees\strategy-024-showcase-publish" add -- strategy-024.css strategy-024.html
    git -C "C:\Users\16052\Documents\量化研究\.worktrees\strategy-024-showcase-publish" commit -m "style: polish stable strategy archive"

### Task 4: 发布到 GitHub Pages 与国内 CDN

**Files:**
- Use: strategy-024.html、strategy-024.css、existing repository publishing configuration
- Modify: only the repository branch history and CDN deployed version
- Test: GitHub Pages root and CDN root HTTP 200 checks

**Interfaces:**
- Consumes: Task 3 通过验收的同一份 HTML/CSS 文件和现有两个发布入口。
- Produces: GitHub Pages 与国内 CDN 同步到同一版本，根地址无需二次跳转即可打开。

- [ ] **Step 1: 确认只包含本次页面文件**

    git -C "C:\Users\16052\Documents\量化研究\.worktrees\strategy-024-showcase-publish" status --short
    git -C "C:\Users\16052\Documents\量化研究\.worktrees\strategy-024-showcase-publish" diff --stat origin/main...HEAD

    Expected: 差异只包含本次视觉规格、HTML/CSS 变更；忽略未跟踪的 .superpowers/ 工作目录，不将其加入提交。

- [ ] **Step 2: 推送 GitHub Pages 分支**

    git -C "C:\Users\16052\Documents\量化研究\.worktrees\strategy-024-showcase-publish" push origin agent/strategy-024-showcase

    Expected: 远端分支更新成功，GitHub Pages 使用的主分支同步到最新提交。

- [ ] **Step 3: 使用现有国内 CDN 发布同一份页面包**

    沿用已验证的国内 CDN 站点和登录态，只上传 strategy-024.html、strategy-024.css、index.html 入口及现有必要静态文件；不重新创建站点、不增加跳转页、不改域名。

- [ ] **Step 4: 验证两个入口**

    $gitUrl = "https://lilalal330303.github.io/guzhiqihuo/strategy-024.html"
    $cloudUrl = "https://stable-strategy-archive-lilalal-d0g2kr8juc0ebea4f.webapps.tcloudbase.com/"
    Invoke-WebRequest -UseBasicParsing -Uri $gitUrl -MaximumRedirection 0 | Select-Object StatusCode,Headers
    Invoke-WebRequest -UseBasicParsing -Uri $cloudUrl -MaximumRedirection 0 | Select-Object StatusCode,Headers

    Expected: 两个根地址均返回 HTTP 200；页面 HTML 不出现资料来源、下载入口、返回研究主页和 024。

- [ ] **Step 5: Commit/publish handoff**

    记录最终提交、两个公开入口和发布验证结果；若 CDN 预览地址带临时令牌，则同时说明正式入口与令牌有效期，不把临时令牌写入源码。
