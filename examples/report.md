---
eyebrow: mdtohtml · component reference
title: Release Readiness Report
lede: A single self-contained page exercising every component `mdtohtml` supports --- typography, callouts, tables, task lists, footnotes, wikilinks, syntax highlighting, coloured chips, pre-rendered math, pre-rendered mermaid diagrams, section kickers, captions, titled code and diagram cards, and a document footer. This line is the report **lede**.
slot: Shipped | Server-side rendering | Math and diagrams are pre-rendered at convert time and carry no runtime engine; the only script is the optional table-of-contents sidebar.
slot: Themed | Report theme | Warm, AA-accessible, and auto light/dark via `prefers-color-scheme`.
slot: Portable | Single file | Every asset inlines into one self-contained HTML document.
---

^ Legend
## Status legend

Status legend: :green[shipped] :blue[in review] :amber[at risk]
:red[blocked] :slate[deferred] :purple[spike] :teal[docs] :pink[design]
:lime[qa] :gold[release] :gray[backlog]

A section can lead with a `^ Label` kicker --- the small mono line above this and
the other headings on this page.

^ Formatting
## Text and inline formatting

Ordinary prose with **bold**, *italic*, `inline code`, ~~struck-through~~
text, and ==highlighted== phrases. A colon that is not a palette key stays
literal: the meeting is at `10:30`, and a ratio like `3:1` is untouched. An
inline chip mid-sentence reads :blue[in review] without disturbing the flow.
The same palette also colours bare text: `:green{yes}` renders :green{yes} and
`:red{no}` renders :red{no} as bold coloured words with no pill.

> A blockquote for a pulled-out remark. It is distinct from a callout and
> renders as a plain quotation.

Here is a footnote reference[^1], resolved at the foot of the page. And an
Obsidian wikilink to a sibling page: [[Architecture Overview]], one with
custom text [[Architecture Overview|the design doc]], and one to a heading
[[Architecture Overview#Data Flow]].

---

^ Callouts
## Callout cards

> [!note] Note
> The `report` theme renders Obsidian callouts as tinted cards with a mono
> uppercase title.

> [!tip] Tip
> Callouts accept full markdown inside, including `code`, **emphasis**, and
> lists.

> [!warning] Warning
> The warning callout uses an amber accent --- distinct from the red danger
> family --- with an AA-safe title in both light and dark colour schemes.

> [!danger] Danger
> The danger and failure family keeps the red accent, for destructive or
> irreversible actions.

> [!keypoint]
> A `keypoint` callout is a plain elevated card with no title --- for the one
> takeaway of a section. It can hold a pull quote:
>
> > Every other callout tints and labels itself; the keypoint stays quiet.

^ Lists
## Lists and tasks

Unordered:

- First item
- Second item, with a nested list
    - Nested one
    - Nested two
- Third item

Ordered:

1. Prepare the build
2. Run the full gate
3. Ship the release

Task list:

- [x] Pre-render math server-side
- [x] Pre-render mermaid diagrams
- [x] Aggregate third-party notices
- [ ] Tag the release

^ Data
## A data table with chips

A `{.keyed}` line above a table styles its first column as an accent key. Tables
also stay on one line and scroll horizontally within their card when they are
wider than the page.

{.keyed}
| Component | Owner | Status | Notes |
|-----------|-------|--------|-------|
| Math (KaTeX SSR) | core | :green[shipped] | No JS engine in output |
| Mermaid diagrams | core | :green[shipped] | Inline SVG, `securityLevel: strict` |
| Report theme | ui | :blue[in review] | Auto light/dark |
| Matrix / legend fences | ui | :slate[deferred] | Out of this cut |
| Windows binary | build | :amber[at risk] | Needs a Windows runner |

^ Code
## Syntax-highlighted code

A fence can carry a `title=` for a header card (a `left | right` title splits
across it) and `hl_lines` to band the line under discussion:

```{.python title="mdtohtml.converter | build()" hl_lines="5"}
from mdtohtml.converter import convert

def build(md: str) -> str:
    """Convert markdown to a self-contained HTML document."""
    return convert(md, theme_name="report", toc=True)
```
~ The single entry point callers use; the banded line does the conversion.

^ Math
## Mathematics

Inline math flows in a sentence: the mass-energy relation is $E = mc^2$, and
Euler's identity is $e^{i\pi} + 1 = 0$.

Display math is centred on its own line:

$$
\int_0^\infty \frac{x^{s-1}}{e^{x} - 1}\,dx = \Gamma(s)\,\zeta(s)
$$

A matrix and a fraction:

$$
A = \begin{pmatrix} a & b \\ c & d \end{pmatrix}
\qquad
\frac{\partial}{\partial t}\,\Psi = \hat{H}\,\Psi
$$

^ Diagrams
## Diagrams

A flowchart. Its `title:` front-matter field is lifted out of the canvas into
the card's header bar, and a `left | right` title splits across it:

```mermaid
---
title: Conversion pipeline | mdtohtml
---
graph TD
  A[Author writes markdown] --> B{Has math or diagrams?}
  B -->|yes| C[Pre-render at convert time]
  B -->|no| D[Plain conversion]
  C --> E[Sanitise + assemble]
  D --> E
  E --> F[Self-contained HTML]
```
~ A tilde-marker line renders a caption under the card, like this one.

A sequence diagram:

```mermaid
sequenceDiagram
  participant U as User
  participant C as CLI
  participant R as Renderer
  U->>C: mdtohtml notes.md --theme report
  C->>R: convert(markdown)
  R-->>C: HTML document
  C-->>U: notes.html
```

A state diagram:

```mermaid
stateDiagram-v2
  [*] --> Draft
  Draft --> Review
  Review --> Shipped
  Review --> Draft
  Shipped --> [*]
```

A pie chart (categorical - keeps its own hues, darker in dark mode):

```mermaid
pie title Test coverage by area
  "Converter" : 45
  "Rendering" : 30
  "CLI" : 15
  "Themes" : 10
```

A gantt chart (categorical):

```mermaid
gantt
  title Release plan
  dateFormat YYYY-MM-DD
  section Build
  Math + mermaid   :done, a1, 2026-09-01, 7d
  Report theme     :done, a2, after a1, 5d
  section Ship
  Tag release      :a3, after a2, 3d
```

^ Notes
## Notes

Everything above renders to one portable HTML file with no network calls. Math
and diagrams carry no runtime engine; the only JavaScript is the optional
table-of-contents sidebar (its scroll-spy and collapse toggle).

::: footer
Generated by **mdtohtml** with the `report` theme. A `::: footer` container ends
the page; a list inside it gets chevron bullets. Source components:

- converter.py
- themes/report.css
- mermaid_render.py
:::

[^1]: Footnotes are collected here and linked back to their references.
