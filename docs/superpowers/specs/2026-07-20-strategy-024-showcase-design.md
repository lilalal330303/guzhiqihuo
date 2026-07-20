# Stable Strategy Archive Page Design

## Goal

Create a standalone GitHub Pages strategy archive for four fixed strategy versions: “大容量低回撤价值投资”, “五福etf”, “福星etf”, and “小市值策略”. The page should communicate each strategy’s thesis, parameters, backtest evidence, and operating boundaries through the same visual template without changing any strategy logic.

## Design direction

- Dark navy research-terminal hero with a light evidence body.
- First viewport: stable-version badge, strategy selector, strategy thesis, validation range, and six headline metrics.
- Evidence-first information hierarchy: metrics → thesis → factor formula → execution parameters → backtest table → operating boundaries.
- Use one data-driven page and a four-option tab switcher so every strategy has the same sections and visual vocabulary.
- No external dependencies; use system typography and CSS-native visual elements so GitHub Pages renders offline and remains fast.
- Responsive layout with two-column desktop sections and single-column mobile fallback.

## Content contract

- Use the user-provided long-period JoinQuant snapshot: 2014-01-01 to 2026-07-19, initial capital ¥1,000,000.
- Preserve the original four-factor and MinMax formula: `MinMax(ROIC) + MinMax(Gross Margin) - MinMax(Price/Sales) - MinMax(Variance120)`.
- Describe the stable version as 40-stock quarterly rebalance with top-50 execution buffer and preflight/order audit protections.
- Show historical-return caveats and do not imply a performance guarantee.
- Do not provide a download button or script link on the public page. Strategy code may remain in the repository as research history, but the page is an explanatory archive only.
- Use only metrics available in the local research records. When a strategy’s evidence is a historical baseline or platform log, label the evidence scope instead of presenting it as a fresh run.

## Files

- `strategy-024.html`: stable strategy archive and tab switcher.
- `strategy-024.css`: shared styling and responsive layout.
- `strategy-024-stable.py`: retained as repository research history, with no public page link.
