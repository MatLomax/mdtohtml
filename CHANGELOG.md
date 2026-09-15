# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- A leading `---` front-matter block drives a report hero: an `eyebrow` kicker,
  the `title` (which also sets the document `<title>`), a `lede`, and up to a
  handful of `slot:` cards (`label | heading | body`), rendered as a header band
  with a slot-card rail and styled by the `report` theme. Documents without a
  front-matter block are unaffected.
- `mermaid` fenced code blocks are pre-rendered to inline SVG at convert time,
  so diagrams need no runtime JavaScript and no network call. A diagram that
  fails to parse degrades to its source shown as a code block with a note.
- A bundled example report (`examples/report.md` and its self-contained
  `examples/report.html`) exercising every supported component under the `report`
  theme: the front-matter hero, callouts, tables with chips, task lists, math,
  and titled mermaid diagrams.
- The `report` theme's table-of-contents sidebar has a collapse/expand toggle:
  the button in the sidebar header collapses it to a slim rail (the content
  column reclaims the width) and expands it again. The state is not persisted, so
  a shared HTML file always opens with its contents showing.
- A `title:` in a mermaid diagram's front matter is lifted out of the diagram
  canvas into a styled header bar on the `report` theme's diagram card, and a
  `left | right` title splits into a left-aligned label and a right-aligned meta
  note. Mermaid no longer draws its own in-canvas caption for the title.
- The `report` theme recolours pre-rendered mermaid diagrams to its own palette
  and adapts them to dark mode: structural diagrams (flowchart, sequence, state,
  class, ER) follow the theme, while categorical diagrams (pie, gantt) keep their
  own hues and darken in dark mode.
- Coloured chips gain a dark-mode palette under the `report` theme, each key
  drawn from its matching callout colour, so pills stay legible and on-theme
  when the reader's `prefers-color-scheme` is dark.
- The SIL Open Font License 1.1 covering the bundled KaTeX fonts now ships in
  the bundle (`mdtohtml/katex/OFL.txt`) alongside KaTeX's MIT `LICENSE`.
- Code fences accept a `hl_lines` attribute (e.g. ```` ```python hl_lines="2" ````)
  to emphasise specific lines; under the `report` theme a flagged line is banded
  with an accent tint and an inset accent rule down its left edge, so the line
  under discussion stands out from the rest of the listing.
- A section kicker: a `^ Label` line immediately above a heading renders as a
  small mono-uppercase accent label leading the section (`.sec-label` under the
  `report` theme), with the heading tucked against it. A caret line that is not
  directly above a heading, or one inside a code block, is left as literal text.
- A caption: a `~ text` marker line renders as a small mono, faint caption
  (`.caption` under the `report` theme), tucked under the block above it -- most
  useful directly below a diagram or code block. A `~ ...` line inside a code
  block, or an empty one, is left as literal text; `~~strikethrough~~` is
  unaffected.
- Tables are wrapped in a horizontal-scroll container (`.tbl-scroll`). Under the
  `report` theme the card framing and scrolling now live on the wrapper and
  cells stay on one line, so a table wider than the content column keeps its
  column widths and scrolls within the card instead of squishing its values onto
  multiple lines.
- A code fence can carry a titled header via its `title=` attribute (e.g.
  ```` ```{.python title="Before the fix | converter.py"} ````): under the
  `report` theme the title renders as a header bar on the code card -- a
  `left | right` title splits into a left label and a right-aligned meta note --
  mirroring the diagram card's header, with the header and code joined into one
  card. Syntax highlighting is preserved and a fence without a title is
  unchanged.
- A top-level table can opt in to an accent key column with a `{.keyed}` line
  directly above it: under the `report` theme the table's first body column
  renders as a mono accent row-key. A `{.keyed}` line not above a real table, or
  one inside a code block, is left as literal text. Coloured status cells remain
  expressible with chips (`:green[done]` / `:red[blocked]`).

### Changed

- Math is now pre-rendered to static KaTeX markup at convert time. The output
  carries the KaTeX stylesheet and fonts but no JavaScript engine; math-free
  documents still ship zero KaTeX bytes.
- Under the `report` theme's dark mode, callouts render as tinted cards that
  follow the colour scheme rather than any callout keeping a fixed light-red
  ground, and every callout title meets WCAG AA contrast in both light and dark.
- The `report` theme's warning callout uses an amber accent (matching the
  important callout) instead of sharing the red of failure and danger, so a
  warning is no longer visually identical to a danger.
- Callouts in the `report` theme carry the same drop shadow as its table, code,
  and diagram cards, so they lift off the page and stand out (dropped in print,
  matching the other cards).
- The `report` theme's table header row centres its uppercase label text, so the
  space above the header text matches the space below it instead of the text
  floating high in the cell.
- Task-list checkboxes in the `report` theme are larger and a ticked box now
  shows a check knocked out in the page colour on the accent fill, so completed
  items are easier to spot.
- The `report` theme's table-of-contents sidebar header sits with balanced
  spacing: the gap above the "Table of Contents" label now matches the gap below
  it, so the header no longer reads as top-heavy.
- Under the `report` theme's dark mode, `==highlighted==` text (`<mark>`) uses the
  accent gold as a solid highlighter with dark ink, so highlights stand out
  instead of fading into a dim tint.

### Removed

- Client-side KaTeX rendering: the in-browser engine, the `auto-render`
  extension, and the auto-render init script no longer ship in the output.

## [0.1.0] - 2026-09-09

Initial release.

### Added

- Markdown-to-HTML conversion with Obsidian-compatible extensions: callouts,
  wikilinks (resolved to `.html` siblings), task lists, tables, footnotes,
  syntax highlighting, `~~del~~`, `==mark==`, and an optional
  table-of-contents sidebar.
- Themeable output via drop-in CSS files (`default`, `dark`, `print` shipped
  in the release zip's `themes/` folder), resolved at runtime with no
  rebuild required to add a theme.
- Client-side KaTeX math rendering, injected only when a document actually
  contains math so math-free output ships zero KaTeX bytes.
- Single self-contained PyInstaller binary for Linux and Windows, with CI
  building, smoke-testing, and packaging release zips for both platforms.

[Unreleased]: https://github.com/MatLomax/mdtohtml/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/MatLomax/mdtohtml/releases/tag/v0.1.0
