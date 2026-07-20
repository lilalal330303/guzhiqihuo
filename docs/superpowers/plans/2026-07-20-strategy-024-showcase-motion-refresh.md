# Stable Strategy Archive Motion Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove source-attribution and user-facing `024` copy from the stable strategy archive, add restrained technology-oriented motion, and publish the same verified files to GitHub Pages and Tencent CloudBase.

**Architecture:** Keep the existing single-page, data-driven strategy switcher. Content cleanup stays in the HTML template and strategy data objects; motion stays in the shared CSS plus one small strategy-change state hook in the existing native JavaScript. No external assets, libraries, or strategy logic changes.

**Tech Stack:** Static HTML, CSS keyframes/transitions, vanilla JavaScript, PowerShell validation, Git, GitHub Pages, Tencent CloudBase static hosting.

## Global Constraints

- Remove the footer's visible “资料来源” block from every strategy view.
- Remove the visible `024` prefix from the value-strategy badge, footer name, metadata, and explanatory closing copy.
- Keep the internal strategy key `value` unchanged so the four-tab data model remains stable.
- Keep strategy metrics, parameter tables, switching behavior, and investment disclaimer unchanged.
- Use CSS keyframes and native JavaScript only; add no external libraries, remote assets, video, canvas particles, or audio.
- Respect `prefers-reduced-motion: reduce`.
- Verify both published roots return HTTP 200 and CloudBase has no extra redirect.

---

### Task 1: Remove source and visible 024 copy

**Files:**
- Modify: `strategy-024.html` template footer and value-strategy data object.

**Interfaces:**
- Consumes: existing `strategies.value`, `sourceText`, `footerName`, `version`, and `closingText` fields.
- Produces: the same four strategy keys and render functions, with no source-attribution output and no user-facing `024` text.

- [ ] **Step 1: Record the current occurrences before editing**

Run:

```powershell
rg -n "资料来源|024" strategy-024.html
```

Expected: matches in the footer template, value metadata, value version, value closing text, and source fields.

- [ ] **Step 2: Update the HTML template/data**

Make these exact content changes:

```html
<!-- Replace the current footer with the disclaimer only. -->
<footer><div class="wrap">历史回测不代表未来表现，不构成投资建议。</div></footer>
```

```javascript
// In strategies.value, use these values and remove sourceText entirely.
version: "Stable",
closingText: "这是价值投资策略的稳定版档案。后续实验应以此版本为基准，单独记录假设、参数、回测区间、交易清单和下一步研究结论。",
footerName: "大容量低回撤价值投资"
```

Delete `sourceText` from all four strategy objects and delete any `sourceText` span from the footer so switching cannot render attribution text for another strategy.

- [ ] **Step 3: Run the content regression check**

Run:

```powershell
$html = Get-Content -Raw strategy-024.html
if ($html -match '资料来源') { throw 'source attribution remains' }
if ($html -match '024') { throw 'visible 024 marker remains' }
if ($html -notmatch 'data-strategy="value"') { throw 'value strategy key changed' }
if ($html -notmatch '五福etf|福星etf|小市值策略') { throw 'strategy tabs were damaged' }
'CONTENT_CHECK=PASS'
```

Expected: `CONTENT_CHECK=PASS`.

- [ ] **Step 4: Commit the content-only change**

```powershell
git add strategy-024.html
git commit -m "content: remove source and legacy value label"
```

---

### Task 2: Add restrained technology motion

**Files:**
- Modify: `strategy-024.css` shared hero, card, tab, metric, and reduced-motion rules.
- Modify: `strategy-024.html` strategy-switch render hook.

**Interfaces:**
- Consumes: existing `document.body.dataset.theme`, `.strategy-tab`, `.metric`, `.card`, and `renderStrategy(key)` flow.
- Produces: `.motion-refresh` state class that is applied for one render cycle and removed after the CSS transition completes.

- [ ] **Step 1: Add CSS motion primitives**

Append the following rules to `strategy-024.css`, adapting only selector names that already exist in the file:

```css
body::before {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: -1;
  opacity: .24;
  background-image: linear-gradient(rgba(125, 180, 255, .055) 1px, transparent 1px),
                    linear-gradient(90deg, rgba(125, 180, 255, .055) 1px, transparent 1px);
  background-size: 42px 42px;
  animation: grid-drift 28s linear infinite;
}

.hero::before,
.hero::after {
  transition: opacity .6s ease, transform .8s ease;
}

.hero::before { animation: halo-breathe 7s ease-in-out infinite; }
.hero::after { animation: halo-breathe 9s ease-in-out -3s infinite reverse; }

.card,
.metric-card,
.evidence-card,
.flow-step {
  transition: transform .35s ease, border-color .35s ease, box-shadow .35s ease, opacity .45s ease;
}

.card:hover,
.metric-card:hover,
.evidence-card:hover,
.flow-step:hover {
  transform: translateY(-3px);
  border-color: rgba(125, 180, 255, .48);
  box-shadow: 0 18px 48px rgba(22, 90, 180, .16), 0 0 0 1px rgba(125, 180, 255, .08);
}

.strategy-tab { transition: color .25s ease, background .25s ease, box-shadow .25s ease, transform .25s ease; }
.strategy-tab:hover,
.strategy-tab:focus-visible { transform: translateY(-1px); box-shadow: 0 0 24px rgba(125, 180, 255, .2); }

.motion-refresh .hero-copy,
.motion-refresh .hero-panel,
.motion-refresh .section-block { animation: content-rise .55s ease both; }
.motion-refresh .hero-panel { animation-delay: .06s; }
.motion-refresh .section-block:nth-of-type(2) { animation-delay: .1s; }
.motion-refresh .section-block:nth-of-type(3) { animation-delay: .16s; }
.motion-refresh .metric-card { animation: metric-rise .48s ease both; }
.motion-refresh .metric-card:nth-child(2) { animation-delay: .04s; }
.motion-refresh .metric-card:nth-child(3) { animation-delay: .08s; }

@keyframes grid-drift { from { background-position: 0 0, 0 0; } to { background-position: 42px 42px, 42px 42px; } }
@keyframes halo-breathe { 0%, 100% { opacity: .42; transform: scale(1); } 50% { opacity: .72; transform: scale(1.06); } }
@keyframes content-rise { from { opacity: .28; transform: translateY(12px); } to { opacity: 1; transform: translateY(0); } }
@keyframes metric-rise { from { opacity: .35; transform: translateY(8px) scale(.985); } to { opacity: 1; transform: translateY(0) scale(1); } }

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: .01ms !important;
    animation-iteration-count: 1 !important;
    scroll-behavior: auto !important;
    transition-duration: .01ms !important;
  }
  body::before { display: none; }
}
```

- [ ] **Step 2: Add the strategy-change state hook**

In `renderStrategy(key)`, immediately after the existing field/render calls and before the function returns, add:

```javascript
document.body.classList.remove("motion-refresh");
void document.body.offsetWidth;
document.body.classList.add("motion-refresh");
window.clearTimeout(window.__motionRefreshTimer);
window.__motionRefreshTimer = window.setTimeout(() => {
  document.body.classList.remove("motion-refresh");
}, 900);
```

This keeps the initial render and each tab switch deterministic while allowing the CSS animation to replay.

- [ ] **Step 3: Run static motion checks**

Run:

```powershell
$css = Get-Content -Raw strategy-024.css
$html = Get-Content -Raw strategy-024.html
foreach ($token in @('grid-drift','halo-breathe','content-rise','metric-rise','prefers-reduced-motion','motion-refresh')) {
  if ($css -notmatch [regex]::Escape($token) -and $html -notmatch [regex]::Escape($token)) { throw "missing motion token: $token" }
}
'MOTION_CHECK=PASS'
```

Expected: `MOTION_CHECK=PASS`.

- [ ] **Step 4: Commit the motion change**

```powershell
git add strategy-024.css strategy-024.html
git commit -m "ui: add restrained strategy archive motion"
```

---

### Task 3: Browser QA and publish both sites

**Files:**
- Verify: `strategy-024.html`, `strategy-024.css`.
- Package: temporary three-file archive containing `index.html`, `strategy-024.html`, and `strategy-024.css`.

**Interfaces:**
- Consumes: the two committed page files and existing logged-in GitHub/Tencent CloudBase sessions.
- Produces: pushed GitHub Pages content and a new successful CloudBase deployment of the same static package.

- [ ] **Step 1: Run local syntax and content checks**

Because the file is HTML, extract its inline script and validate the JavaScript:

```powershell
$html = Get-Content -Raw strategy-024.html
$script = [regex]::Match($html, '<script>([\s\S]*)</script>').Groups[1].Value
Set-Content -Path "$env:TEMP\strategy-024-inline-check.js" -Value $script -Encoding utf8
node --check "$env:TEMP\strategy-024-inline-check.js"
```

Expected: Node exits with code 0 and no syntax errors.

- [ ] **Step 2: Preview the page in a browser**

Open the local page and verify:

```text
1. The hero no longer displays 024.
2. The footer contains only the historical-return disclaimer.
3. Each of 价值投资策略, 五福etf, 福星etf, 小市值策略 switches correctly.
4. Cards and metrics animate once on switching; tab hover/focus is visible.
5. The layout remains readable at narrow width.
```

- [ ] **Step 3: Push the intended branch**

```powershell
$status = git status --short
if ($status) { throw "working tree is not clean: $status" }
git log -3 --oneline
git push origin agent/strategy-024-showcase
```

Expected: push succeeds and the working tree is clean.

- [ ] **Step 4: Verify the GitHub Pages root**

```powershell
$gitUrl = 'https://lilalal330303.github.io/guzhiqihuo/strategy-024.html'
$git = Invoke-WebRequest -Uri $gitUrl -MaximumRedirection 0 -UseBasicParsing
if ($git.StatusCode -ne 200) { throw "GitHub Pages status: $($git.StatusCode)" }
if ($git.Content -match '资料来源|024') { throw 'GitHub page still contains removed copy' }
'GITHUB_CHECK=PASS'
```

Expected: `GITHUB_CHECK=PASS` after Pages propagation.

- [ ] **Step 5: Deploy the identical package to CloudBase**

Create a temporary zip with only:

```text
index.html          # copy of strategy-024.html
strategy-024.html
strategy-024.css
```

Use the logged-in Tencent CloudBase static hosting uploader to deploy a new version under `stable-strategy-archive`, without enabling paid services or changing domain settings.

- [ ] **Step 6: Verify the domestic root**

```powershell
$cloudUrl = 'https://stable-strategy-archive-lilalal-d0g2kr8juc0ebea4f.webapps.tcloudbase.com/'
$cloud = Invoke-WebRequest -Uri $cloudUrl -MaximumRedirection 0 -UseBasicParsing
if ($cloud.StatusCode -ne 200) { throw "CloudBase status: $($cloud.StatusCode)" }
if ($cloud.Content -match '资料来源|024') { throw 'CloudBase page still contains removed copy' }
'CLOUDBASE_CHECK=PASS'
```

Expected: `CLOUDBASE_CHECK=PASS` with the same page content as GitHub Pages and no second redirect.
