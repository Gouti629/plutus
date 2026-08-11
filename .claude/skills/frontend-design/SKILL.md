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

`--surface-1` is deliberately translucent (`rgba(...)`, not a flat hex) in
both themes - it's the "glass" layer: matte, near-neutral black/grey
(`--surface-2`) underneath, with blue pulled out specifically into
translucent panels, borders, and washes rather than tinting the neutrals
themselves. Concretely: dark `--surface-2` is matte near-black with almost no
hue bias (not navy); `--surface-1`, `--border`, `--row-hover`,
`--row-selected`, and `--shadow-sm`'s ambient glow all carry the blue tint
instead, at low opacity (`rgba(110-150, 150-170, 200-255, 0.06-0.55)` range).
Any element using `--surface-1` should also get
`backdrop-filter: blur(var(--glass-blur))` (+ `-webkit-` prefix) so it reads
as glass, not just a flat translucent color - see `header`, `.list-pane`,
`section.block`, `.back-btn`. Keep this split (neutral matte ground, blue
glass panels) rather than reintroducing a blue-tinted neutral - that was
tried and explicitly rejected in favor of this.

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

Three-role type system, all IBM Plex (loaded via Google Fonts in
`index.html`'s `<head>` - this project is a real deployed site, not a
CSP-locked artifact, so webfonts are fine here). Each role is a token, not a
hardcoded family name:

- `--font-sans` (IBM Plex Sans): UI chrome - headers, labels, buttons,
  badges, filter tiles, section titles.
- `--font-serif` (IBM Plex Serif): the actual content being reviewed - the
  claim narrative (`.submitted-text`) and the agent's reasoning
  (`.reasoning`). This is a deliberate split: sans is "the system," serif is
  "the document." Keep new prose/narrative content in serif, not sans.
- `--font-mono` (IBM Plex Mono): identifiers and data - claim IDs, every
  `.field-value` (policy numbers, dates, money - rendered mono uniformly for
  a ledger/case-file feel), evidence source paths, tool-call JSON.

Don't introduce a fourth family or fall back to generic `system-ui` for new
UI text - reuse one of the three roles above.

Scale in use: `21px`/600 weight for the page h1 and detail headers (h1 uses
sans, detail `<h2>` claim-id headers use mono), `15px`/1.6-1.65 line-height
for serif body text, `13-14px` sans/mono for field text, `11-12px` sans for
muted labels and captions (`text-transform: uppercase` +
`letter-spacing: 0.03-0.04em`, matching `section.block h3`).

## The brand mark

`.brand` in the header pairs a small inline SVG (`.mark`) with the "Prism"
wordmark. The mark is a literal visual pun on the product name: one line in
`--accent` enters a triangle, three lines exit colored
`--status-good`/`--status-warning`/`--status-critical` - light splitting into
the same outcome colors used everywhere else in the UI. It's the one
deliberately "designed" flourish in an otherwise restrained, utilitarian
tool - don't add a second one; keep everything else quiet by comparison.

## Filter tiles (`.list-filters` / `.filter-tile`)

The claim-count summary and the decision filter are the same component, not
two - each `.filter-tile` shows a live count (`.filter-count`, mono,
`tabular-nums`) and toggles `aria-pressed`. `DECISION_FILTERS` in app.js is
the source of truth for which decisions get a tile; a `--tile-color` custom
property per `.filter-tile--*` modifier drives both the pressed-state
background (`color-mix`) and the count color. If you add a new filterable
dimension, follow this pattern rather than adding a separate, silent count
display.

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
