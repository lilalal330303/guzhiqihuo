# Stable Strategy Archive Motion and Cleanup Design

## Goal

Refresh the public stable-strategy archive without changing strategy data, tab behavior, or the research claims. The update removes source-attribution copy and the user-facing `024` label, then adds restrained technology-oriented motion that remains suitable for GitHub Pages, Tencent CloudBase static hosting, and mobile browsers.

## Content and naming rules

- Remove the footer's visible “资料来源” block from every strategy view.
- Remove the visible `024` prefix from the value-strategy badge, footer name, metadata, and explanatory closing copy.
- Keep the internal strategy key `value` unchanged so the four-tab data model remains stable.
- Keep the investment disclaimer, strategy metrics, parameter tables, and switching behavior unchanged.

## Motion system

- Use CSS keyframes and small native-JS state hooks only; no external libraries or remote assets.
- Add a slow background grid drift and radial glow pulse to the hero.
- Animate section/cards into view with opacity and translate transitions.
- Add a brief metric rise/highlight when the selected strategy changes.
- Add hover/focus glow to tabs and key cards without changing layout dimensions.
- Respect `prefers-reduced-motion: reduce` by disabling continuous motion and shortening transitions.
- Preserve readable contrast, keyboard focus, and responsive single-column behavior.

## Validation and publishing

- Static checks must confirm that the removed source text and visible `024` labels are absent while the four strategy keys remain.
- Use a browser preview to verify the hero, tabs, mobile-safe layout, and motion state after switching strategies.
- Commit the intended HTML/CSS/spec changes on the showcase branch, push to GitHub Pages, then redeploy the same three-file package to the Tencent CloudBase static site.
- Verify the GitHub and CloudBase roots return HTTP 200 and that the CloudBase root has no extra redirect.

## Out of scope

- No changes to strategy formulas, performance numbers, or research logic.
- No new external CDN dependency, video background, canvas particle system, or autoplay audio.
