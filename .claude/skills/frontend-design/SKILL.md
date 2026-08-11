---
name: frontend-design
description: Design system and conventions for Prism, the FNOL dashboard (dashboard/index.html, styles.css, app.js). Use when adding or modifying any dashboard UI - new views, components, layout, or styling - so changes stay consistent with the existing look instead of introducing ad-hoc styles or a build step.
paths: dashboard/**
---

Prism is a plain HTML/CSS/JS trace viewer - no framework, no build step, no
component library. Keep it that way unless the user explicitly asks to add
one; the "no build step" property is a deliberate project choice (see
README.md), not an oversight.

## Token system (dashboard/styles.css)

All color comes from CSS custom properties defined on `:root`, never literal
hex values in component rules. Categories, by name (check the current `:root`
block for exact values before using them):

- Surfaces: `--surface-1` (raised/card), `--surface-2` (page background)
- Text: `--text-primary`, `--text-secondary`, `--text-muted`
- Structure: `--gridline`, `--border`
- Interaction: `--row-hover`, `--row-selected`, `--accent`
- Semantic status (separate from `--accent`, never reuse the accent hue for
  status): `--status-good`, `--status-warning`, `--status-serious`,
  `--status-critical` - these map to decision outcomes (auto-approve /
  request-info / flag) and confidence/severity, not arbitrary UI color.

Every new color decision must be a token, not a one-off value, and must have
a reason to pick a *new* token vs. reusing an existing one.

## Theming - three states, not two

The page can render with no explicit theme stamp (system default, split only
by `prefers-color-scheme`), `data-theme="light"`, or `data-theme="dark"` on
`:root`. Follow the existing three-block pattern in styles.css exactly when
adding tokens:

1. Bare `:root { ... }` - the complete light palette.
2. `@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { ... } }` - dark overrides, guarded so an explicit light choice still wins.
3. `:root[data-theme="dark"] { ... }` - same dark values again, so a manual toggle wins over the media query.

Never give a color its only definition inside a media query or `[data-theme]`
block - it must exist on bare `:root` first. `body`'s background must come
from a token (`--surface-2`), never left transparent.

## Layout conventions

- Desktop: `.layout` is a flex row - `.list-pane` (fixed width, 400px,
  min 280px) + `.detail-pane` (flex: 1). Both scroll independently.
- Mobile (`@media (max-width: 768px)`): panes become full-screen, absolutely
  positioned, and slide via `transform: translateX(...)` toggled by a
  `showing-detail` class on `<body>`, with a `.back-btn` (hidden on desktop)
  to return to the list. Preserve this pattern for any new mobile-specific
  behavior rather than introducing a second responsive strategy.
- Card-like sections use `section.block`: `var(--surface-1)` background,
  1px `var(--border)`, `10px` radius, `16px 20px` padding.
- Pills/badges use `border-radius: 999px`; cards/sections use `8-10px`.

## Typography

`system-ui, -apple-system, "Segoe UI", sans-serif` - no webfonts, no
`@font-face`. Scale in use: `18px`/600 weight for the page h1, `20px` for
detail headers, `13-14px` for body/field text, `11-12px` for muted labels and
captions (often with `text-transform: uppercase` + `letter-spacing: 0.03-0.04em`
for section labels, matching `section.block h3`).

## JS conventions (app.js)

Plain DOM manipulation through the `el(tag, attrs, ...children)` helper
already defined at the top of the file - use it for new elements rather than
`innerHTML` string-building, to keep escaping safe and the style consistent.
Data flows in via `loadTraces()` (tries `/api/claims`, falls back to the
`FNOL_TRACES` global from `data.js`) - any new view should read from the same
trace objects already loaded, not fetch something new, unless the user asks
for a new data source.

## Before adding something new

Check whether an existing token, class, or pattern already covers it (badge
colors for status, `.field-grid` for label/value pairs, `<details>`-based
`.tool-call` for collapsible raw data) before introducing a new one - this
dashboard intentionally stays small and repetitive rather than accumulating
one-off component variants.
