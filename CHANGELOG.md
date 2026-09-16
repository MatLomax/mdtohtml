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
- Bundled example report sources under `examples/`: `report.md` is an exhaustive
  component reference under the `report` theme, exercising every combination that
  inlines into one self-contained file and pairing each with the Markdown source
  that produces it. It is grouped into dedicated sections -- front matter, text
  formatting, colouring (chips + bare coloured text), markers (section kickers +
  captions), heading levels `h2` through `h6` with `h2`/`h3` TOC nesting, callouts,
  lists, tables, code, math, and diagrams -- covering all eleven chip colours and
  all eleven bare coloured-text keys, all fifteen callout families (with per-family
  inline-code tints, plus custom and untitled forms) and a keypoint card,
  unordered/ordered/task lists, plain and keyed tables, plain/single-title/split-title
  code cards with a banded `hl_lines` block, inline and display math, and a titled
  mermaid diagram card (showing how to add a diagram and set its header-bar title),
  alongside a document footer -- and `phantom-transit-stock.md` is a realistic
  report including
  `classDef`-coloured diagrams. Each renders to a self-contained HTML sibling with
  `mdtohtml`; the generated `.html` files are regenerated from the sources rather
  than committed.
- The `report` theme's table-of-contents sidebar has a collapse/expand toggle:
  the button in the sidebar header collapses it to a slim rail (the content
  column reclaims the width) and expands it again. The state is not persisted, so
  a shared HTML file always opens with its contents showing.
- A `title:` in a mermaid diagram's front matter is lifted out of the diagram
  canvas into a filled header bar on the `report` theme's diagram card -- a warm
  bar spanning the card's full width in light, adapting to a panel bar in dark --
  and a `left | right` title splits into a left-aligned label and a right-aligned
  meta note. Mermaid no longer draws its own in-canvas caption for the title.
- The `report` theme recolours pre-rendered mermaid diagrams to its own palette
  and adapts them to dark mode: structural diagrams (flowchart, sequence, state,
  class, ER) follow the theme, while categorical diagrams (pie, gantt) keep their
  own hues and darken in dark mode.
- Author `classDef` colours on a structural diagram now adapt to dark mode under
  the `report` theme. Each colour keeps its hue while its lightness and
  saturation move to a dark-friendly tone -- pale fills become dark tiles, dark
  labels become light ink, borders become restrained mid-tones kept dimmer than
  the label ink so the text reads a touch brighter than its node's outline -- and
  every label is WCAG AA-legible against its tile. Light mode keeps the author's
  exact colours, and a diagram with no `classDef` colours is left untouched.
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
  muted mono-uppercase label leading the section (`.sec-label` under the
  `report` theme) -- matching the hero eyebrow's size and font but in a muted
  tone rather than the accent -- with the heading tucked against it. A caret
  line that is not directly above a heading, or one inside a code block, is left
  as literal text.
- A caption: a `~ text` marker line renders as a small mono, faint caption
  (`.caption` under the `report` theme), tucked under the block above it -- most
  useful directly below a diagram or code block. A `~ ...` line inside a code
  block, or an empty one, is left as literal text; `~~strikethrough~~` is
  unaffected.
- Tables are wrapped in a card container (`.tbl-scroll`) that carries the border,
  radius, and shadow. Under the `report` theme table cells wrap to fit, so a
  table sizes to the content column rather than forcing a horizontal scroll; a
  viewport narrower than the table's floor width falls back to scrolling within
  the card.
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
- A `::: footer` ... `:::` container renders a styled document footer: under the
  `report` theme a faint, top-ruled provenance region, with any list inside it
  getting accent `›` chevron bullets. The footer body is ordinary Markdown (emphasis,
  links, lists all work). Documents without the container are unaffected.
- A `> [!keypoint]` callout renders as a plain elevated card -- no coloured rule
  and no title -- for the one takeaway of a section, holding a lead paragraph and
  an optional amber-barred pull quote (a `> >` blockquote inside it). Under the
  `report` theme it is a white panel with an accent-line border and shadow.
- Bare coloured text: `:key{text}` (the eleven palette keys, e.g. `:green{yes}` /
  `:red{no}`) renders the text bold in the palette colour with no pill
  (`<span class="ptext key">`) -- the plain-text companion to the `:key[label]`
  chip. A key outside the palette, or the syntax inside code, is left literal.
- Typographic dashes: `--` becomes an en-dash and `---` becomes an em-dash in
  prose and hero fields. Straight quotes and `...` are left as typed, and code is
  never touched.

### Changed

- Task-list items in the `report` theme now line their text up with unordered and
  ordered list items on one shared left edge, the checkbox sitting in the same
  left gutter as the chevron and number, instead of being indented a step further
  right.
- Blockquote text in the `report` theme's dark mode lifts to the full body ink so
  quotes no longer read too dim against the panel; the border and tinted ground
  still set the quote apart, and light mode is unchanged.
- A table-of-contents link now lands above its section's kicker rather than
  scrolling it off the top: a kicker-preceded heading carries a `scroll-margin-top`,
  and the scrollspy marks a section active once it reaches that same landing line
  (its own `scroll-margin-top` plus the trigger buffer), so a kicker-led section
  lights up as it parks at the top.
- The `report` theme's table-of-contents entries are semibold with a little more
  vertical padding, and the "Table of Contents" header matches the entry type size.
- The table-of-contents sidebar labels each entry with its section kicker (the
  `^ Label` line above the heading) when the section has one, falling back to the
  heading text otherwise; the link still targets the heading. Under the `report`
  theme these top-level entries take the kicker's own type -- a muted mono
  uppercase label -- so the sidebar mirrors the in-page section kickers.
- The `report` theme declares `color-scheme: light dark`, so native scrollbars
  (and any UA controls) follow the reader's `prefers-color-scheme` instead of
  staying light on a dark page. The table-of-contents rail's thin scrollbar is
  pinned to the theme tokens so its thumb darkens with the page, and pre-rendered
  mermaid diagrams no longer hold their scrollbar to light in dark mode.
- The `report` theme's monospace stack adds `JetBrains Mono` (between `SF Mono`
  and `Menlo`), so inline code, code blocks, and card headers pick it up when the
  reader has it installed.
- The `report` theme's card-header labels (diagram and code-sheet bars) now use a
  600 weight and a warm ink (`#4a4335` label, `#9a8f76` meta) in light mode,
  switching to the theme's light-on-dark tokens in dark mode.
- The `report` theme's section kicker (`.sec-label`) tracks a touch tighter
  (`0.16em`) than the hero eyebrow (`0.18em`), and the diagram/code caption
  (`.caption`) is 13px with the body line height, matching the reference.
- The `report` theme's layout is tuned to the report scaffold: a wider content
  column, larger (non-collapsing) spacing above section headings, and code and
  diagram card headers at the reference's type size whose left-hand title keeps
  its source case while the right-hand meta note stays uppercased.
- Inline code inside a callout takes the callout's own colour -- a less
  transparent tint of the family accent, or the house accent for the family-less
  keypoint card -- instead of the neutral grey chip.
- Unordered lists in the `report` theme use an accent `›` chevron as their
  bullet -- the same marker as the document footer, made the house bullet --
  with nested levels stepping back to a more transparent shade. Ordered lists
  render their number as a bare mono accent counter aligned to the chevron's
  gutter, so a single-digit number's left edge lines up under the chevron while a
  wider number extends into the gutter rather than crowding the item text. The
  table-of-contents and footnotes keep their own markers.
- Math is now pre-rendered to static KaTeX markup at convert time. The output
  carries the KaTeX stylesheet and fonts but no JavaScript engine; math-free
  documents still ship zero KaTeX bytes.
- Under the `report` theme's dark mode, callouts render as tinted cards that
  follow the colour scheme rather than any callout keeping a fixed light-red
  ground, and every callout title meets WCAG AA contrast in both light and dark.
- The `report` theme's note callout uses the amber accent -- border, tint, and
  mono title -- rather than blue, matching the reference's default callout.
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
  shows a centred check knocked out in the page colour on the accent fill, so
  completed items are easier to spot.
- The `report` theme's table-of-contents sidebar header sits with balanced
  spacing: the gap above the "Table of Contents" label now matches the gap below
  it, so the header no longer reads as top-heavy.
- Under the `report` theme's dark mode, `==highlighted==` text (`<mark>`) uses the
  accent gold as a solid highlighter with dark ink, so highlights stand out
  instead of fading into a dim tint.

### Fixed

- The `report` theme's card-header tracking (`letter-spacing`) on the diagram and
  code-sheet header bars now resolves against each label's own type size: the
  spacing is set on the label and meta spans (`0.06em` and `0.1em`) instead of the
  bar, so it no longer inherits a too-wide value computed from the bar's larger
  inherited font size.
- A code block highlighting more than one line (`hl_lines="2 3"`) now bands each
  flagged line on its own row instead of collapsing the consecutive lines onto a
  single row.
- Footnotes under the `report` theme now render their intended styling -- a
  faint top-ruled separator (in place of the default horizontal rule) and
  smaller muted text -- rather than falling back to the browser's plain footnote
  block.

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
