# Strategy 024 Showcase Page Design

## Goal

Create a standalone GitHub Pages strategy archive for the fixed stable version of “大容量低回撤价值投资”. The page should communicate the strategy’s thesis, exact parameters, long-horizon backtest snapshot, execution safeguards, and reproducible script entry without changing the existing research homepage or live strategy logic.

## Design direction

- Dark navy research-terminal hero with a light evidence body.
- First viewport: stable-version badge, strategy thesis, validation range, and six headline metrics.
- Evidence-first information hierarchy: metrics → thesis → factor formula → execution parameters → backtest table → operating boundaries.
- No external dependencies; use system typography and CSS-native visual elements so GitHub Pages renders offline and remains fast.
- Responsive layout with two-column desktop sections and single-column mobile fallback.

## Content contract

- Use the user-provided long-period JoinQuant snapshot: 2014-01-01 to 2026-07-19, initial capital ¥1,000,000.
- Preserve the original four-factor and MinMax formula: `MinMax(ROIC) + MinMax(Gross Margin) - MinMax(Price/Sales) - MinMax(Variance120)`.
- Describe the stable version as 40-stock quarterly rebalance with top-50 execution buffer and preflight/order audit protections.
- Show historical-return caveats and do not imply a performance guarantee.
- Link the exact stable Python script as a downloadable file.

## Files

- `docs/strategy-024.html`: standalone strategy archive page.
- `docs/strategy-024.css`: page styling and responsive layout.
- `docs/strategy-024-stable.py`: copy of the user-provided stable JoinQuant script.
