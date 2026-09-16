"""Core conversion library for mdtohtml.

Converts Obsidian-compatible Markdown to styled, self-contained HTML with
themeable CSS. Math is pre-rendered to static KaTeX markup at convert time and
styled by the bundled KaTeX CSS/fonts; ```mermaid``` fences are pre-rendered to
inline SVG. Neither ships a JavaScript engine or makes a network request, and a
document without math or diagrams carries none of their bytes.

No HTTP, no CLI, no file writing. Callers decide what to do with the output.
"""

from __future__ import annotations

import html as _html
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

import markdown
import nh3

from . import frontmatter, katex_assets, katex_render, mermaid_render

# ── Path Constants ──

THEMES_DIR = Path(__file__).resolve().parent / "themes"


def default_themes_dir() -> Path:
    """Resolve the themes directory to use when none is given explicitly.

    A non-frozen run (plain Python) uses the package-relative ``THEMES_DIR``.

    A PyInstaller-frozen binary always uses a ``themes/`` directory placed
    alongside the executable; no theme CSS is bundled inside the frozen
    binary, so a user can add or replace a theme by dropping a ``.css``
    file there without rebuilding.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "themes"

    return THEMES_DIR

# ── HTML Template ──

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>{title}</title>
    <style>{css}</style>
{head_extra}</head>
<body>
{body}
</body>
</html>
"""


# ── Obsidian Callout Preprocessor ──

_CALLOUT_TYPES = {
    "note",
    "abstract",
    "info",
    "todo",
    "tip",
    "success",
    "question",
    "warning",
    "important",
    "failure",
    "danger",
    "bug",
    "example",
    "quote",
    "keypoint",
}

# Matches the opening line of an Obsidian callout: > [!type] Optional Title
_CALLOUT_RE = re.compile(
    r"^>\s*\[!(" + "|".join(_CALLOUT_TYPES) + r")\]\s*(.*)?$",
    re.IGNORECASE,
)


def preprocess_obsidian_callouts(
    md_text: str,
    *,
    ignore_callouts: set[str] | None = None,
) -> str:
    """Convert Obsidian callout syntax to Python-Markdown admonition syntax.

    Converts:
        > [!note] Optional Title
        > Content line 1
        > Content line 2

    To:
        !!! note "Optional Title"
            Content line 1
            Content line 2

    When *ignore_callouts* is provided, callout blocks whose type is in
    the set are removed from the output entirely.

    Fenced and inline code are protected so a callout example inside a code
    block is never rewritten to admonition syntax.
    """
    protected, placeholders = _protect_code(md_text)
    lines = protected.split("\n")
    result: list[str] = []
    i = 0

    while i < len(lines):
        match = _CALLOUT_RE.match(lines[i])
        if match:
            callout_type = match.group(1).lower()
            title = (match.group(2) or "").strip()

            # Check if this callout type should be ignored
            if ignore_callouts and callout_type in ignore_callouts:
                # Skip the opening line and all continuation lines
                i += 1
                while i < len(lines) and lines[i].startswith(">"):
                    i += 1
                continue

            # Build admonition opening line
            if title:
                result.append(f'!!! {callout_type} "{title}"')
            else:
                result.append(f"!!! {callout_type}")

            i += 1

            # Consume continuation lines starting with >
            while i < len(lines):
                line = lines[i]
                # A line starting with > continues the callout
                if line.startswith(">"):
                    # Strip the leading > and optional single space
                    content = line[1:]
                    if content.startswith(" "):
                        content = content[1:]
                    # Indent content by 4 spaces for the admonition
                    if content.strip():
                        result.append("    " + content)
                    else:
                        # Empty continuation line (just ">")
                        result.append("")
                    i += 1
                else:
                    break
        else:
            result.append(lines[i])
            i += 1

    return _restore_code("\n".join(result), placeholders)


# ── Code Block Protection (shared by callout, wikilink, and title extraction) ──


# An inline code span: an opening run of N backticks closed by the next run of
# exactly N backticks (CommonMark). A span may therefore contain shorter runs,
# e.g. ``code with ` tick``.
_INLINE_CODE_RE = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)")

# A fenced-code opening line: at least three backticks or tildes (up to three
# leading spaces), with an optional info string on the same line.
_FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def _protect_code(text: str, *, inline: bool = True) -> tuple[str, list[str]]:
    """Replace code spans/blocks with NUL-delimited placeholders.

    Fenced blocks (opened by ``` or ~~~ and closed by a fence of the same
    character at least as long as the opener) and, when *inline* is true,
    inline code spans are lifted out so later line/link rewriting never
    touches code. Returns the protected text plus the list of originals for
    :func:`_restore_code`.
    """
    placeholders: list[str] = []

    lines = text.split("\n")
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        m = _FENCE_OPEN_RE.match(lines[i])
        if m:
            fence_char = m.group(1)[0]
            fence_len = len(m.group(1))
            close_re = re.compile(
                r"^ {0,3}" + re.escape(fence_char) + r"{" + str(fence_len) + r",} *$"
            )
            block = [lines[i]]
            i += 1
            while i < n:
                block.append(lines[i])
                closed = close_re.match(lines[i])
                i += 1
                if closed:
                    break
            placeholders.append("\n".join(block))
            out.append(f"\x00CODEPH{len(placeholders) - 1}\x00")
        else:
            out.append(lines[i])
            i += 1
    protected = "\n".join(out)

    if inline:
        def _sub(mm: re.Match[str]) -> str:
            placeholders.append(mm.group(0))
            return f"\x00CODEPH{len(placeholders) - 1}\x00"

        protected = _INLINE_CODE_RE.sub(_sub, protected)

    return protected, placeholders


def _restore_code(text: str, placeholders: list[str]) -> str:
    """Restore originals lifted out by :func:`_protect_code` into their slots."""
    for i, original in enumerate(placeholders):
        text = text.replace(f"\x00CODEPH{i}\x00", original)
    return text


# ── Wikilink Preprocessing ──


# Matches Obsidian wikilinks: [[Page]] or [[Page|display text]]
# Also handles headings: [[Page#heading]] or [[Page#heading|text]]
_WIKILINK_RE = re.compile(r"\[\[([^\]|]+?)(?:\|([^\]]+?))?\]\]")


def preprocess_wikilinks(md_text: str) -> str:
    """Convert Obsidian ``[[wikilink]]`` syntax to standard Markdown links.

    Converts:
        ``[[Some Page]]``          → ``[Some Page](Some Page.html)``
        ``[[Some Page|text]]``     → ``[text](Some Page.html)``
        ``[[Some Page#heading]]``  → ``[Some Page > heading](Some Page.html#heading)``
        ``[[Page#heading|text]]``  → ``[text](Page.html#heading)``

    Links resolve to the ``.html`` sibling produced for each source page.

    Code blocks (fenced and inline) are protected from rewriting.
    """
    protected, placeholders = _protect_code(md_text)

    def _replace_wikilink(m: re.Match[str]) -> str:
        target = m.group(1).strip()
        display = (m.group(2) or "").strip()

        # Split target into page and optional heading fragment
        if "#" in target:
            page, heading = target.split("#", 1)
            page = page.strip()
            heading = heading.strip()
        else:
            page = target
            heading = ""

        # Build the link URL: page.html or page.html#heading
        if page:
            url = f"{page}.html"
            if heading:
                url += f"#{heading}"
        else:
            # [[#heading]] — same-document anchor
            url = f"#{heading}"

        # Build display text
        if not display:
            if page and heading:
                display = f"{page} > {heading}"
            elif page:
                display = page
            else:
                display = heading

        return f"[{display}]({url})"

    rewritten = _WIKILINK_RE.sub(_replace_wikilink, protected)

    return _restore_code(rewritten, placeholders)


# ── Inline Chip Preprocessing ──


# The categorical palette keys a ``:key[label]`` chip may use. Kept in sync with
# the ``.pchip.<key>`` rules the report theme ships; a key outside this set is
# left as literal text so ordinary prose containing a colon is never rewritten.
_CHIP_KEYS = {
    "blue",
    "green",
    "amber",
    "purple",
    "teal",
    "pink",
    "lime",
    "gold",
    "slate",
    "red",
    "gray",
}

# Matches an inline chip: ``:key[label]`` where key is one of the palette keys.
# The leading ``(?<![\w:])`` requires the ``:`` to start a fresh token, so a key
# glued to a preceding word (``code:red[1]``) or a stray ``::`` is left alone.
# The label runs up to the first ``]``; it flows on through markdown and nh3, so
# any markup inside a label is sanitised by the existing pass, not trusted here.
_CHIP_RE = re.compile(
    r"(?<![\w:]):(" + "|".join(sorted(_CHIP_KEYS)) + r")\[([^\]]*)\]"
)

# The bare-text variant: ``:key{label}`` (curly braces) renders the label as
# coloured, bold text with no pill -- ``<span class="ptext key">``. Same palette
# keys and the same leading-token guard as the chip; the two never collide since
# one takes ``[...]`` and the other ``{...}``.
_PTEXT_RE = re.compile(
    r"(?<![\w:]):(" + "|".join(sorted(_CHIP_KEYS)) + r")\{([^}]*)\}"
)


def preprocess_chips(md_text: str) -> str:
    """Convert inline ``:key[label]``/``:key{label}`` syntax to coloured spans.

    Converts, only when *key* is one of the categorical palette keys::

        :blue[North]  →  <span class="pchip blue">North</span>   (a pill)
        :blue{North}  →  <span class="ptext blue">North</span>   (bare bold text)

    A key outside the palette (``:other[x]``) and any other colon usage are left
    untouched. The label passes through markdown conversion and nh3 sanitisation
    normally -- ``span``/``class`` are already allowed and any hostile markup in
    the label is neutralised by that sanitiser, so no special escaping is needed
    here.

    Fenced and inline code are protected so a ``:blue[...]`` example inside code
    is never rewritten.
    """
    protected, placeholders = _protect_code(md_text)

    def _replace_chip(m: re.Match[str]) -> str:
        key = m.group(1)
        label = m.group(2)
        return f'<span class="pchip {key}">{label}</span>'

    def _replace_ptext(m: re.Match[str]) -> str:
        key = m.group(1)
        label = m.group(2)
        return f'<span class="ptext {key}">{label}</span>'

    rewritten = _CHIP_RE.sub(_replace_chip, protected)
    rewritten = _PTEXT_RE.sub(_replace_ptext, rewritten)

    return _restore_code(rewritten, placeholders)


# ── Section Kicker Preprocessing ──


# A section kicker: a line ``^ Label`` sitting immediately above a heading. It
# renders as a small mono-uppercase label over the heading (``.sec-label``). The
# leading ``^`` at column 0 is never Markdown, so it needs no escaping to claim.
_SEC_KICKER_RE = re.compile(r"^\^ (.+)$")

# An ATX heading line (``#`` to ``######`` then a space). Setext headings
# (text underlined by ``===``/``---``) are deliberately not matched: a ``---``
# underline is ambiguous with a thematic break and a ``-`` list, so the kicker
# attaches only to the unambiguous ATX form.
_HEADING_RE = re.compile(r"^#{1,6} ")


def preprocess_section_kickers(md_text: str) -> str:
    """Convert ``^ Label`` kicker lines above a heading to a ``.sec-label``.

    Converts, only when the very next line is an ATX heading::

        ^ The symptom
        ## What it reports

    to a ``<p class="sec-label">The symptom</p>`` block emitted just above the
    heading (an adjacent-sibling CSS rule tucks the heading against it). A ``^``
    line that is not immediately above a heading -- or whose label is empty once
    trimmed -- is left untouched, so ordinary prose that happens to start with a
    caret is never rewritten.

    Keep a kicker to a short plain label: it is emitted as HTML-escaped text, so
    it can never inject markup, but this pass runs after the chip and wikilink
    passes, so any ``:key[..]`` / ``[[..]]`` / Markdown syntax placed inside a
    kicker is not meaningfully rendered (it is escaped as literal text). Fenced
    and inline code are protected so a ``^ ...`` example inside code is never
    rewritten.
    """
    protected, placeholders = _protect_code(md_text)
    lines = protected.split("\n")
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        m = _SEC_KICKER_RE.match(lines[i])
        label = _html.escape(m.group(1).strip(), quote=False) if m else ""
        if label and i + 1 < n and _HEADING_RE.match(lines[i + 1]):
            out.append(f'<p class="sec-label">{label}</p>')
            # A blank line so Python-Markdown treats the ``<p>`` as its own raw
            # HTML block rather than folding it into an adjacent paragraph.
            out.append("")
        else:
            out.append(lines[i])
        i += 1
    return _restore_code("\n".join(out), placeholders)


# ── Caption Preprocessing ──


# A caption marker: a line ``~ text`` renders as a small mono/faint caption
# (``.caption``), typically placed right below a diagram or code block. A single
# leading ``~`` followed by a space is never Markdown (``~~del~~`` needs two, a
# ``~sub~`` has no space, a ``~~~`` fence needs three), so it claims the line
# cleanly.
_CAPTION_RE = re.compile(r"^~ (.+)$")


def preprocess_captions(md_text: str) -> str:
    """Convert ``~ text`` marker lines to a ``.caption`` paragraph.

    Converts::

        ~ Green is the working path; rust is the stranded one

    to ``<p class="caption">Green is the working path; ...</p>``. It is a general
    standalone marker -- most useful directly under a diagram or code card, but
    it fires on any ``~ ...`` line outside code; a line whose caption is empty
    once trimmed is left untouched.

    Keep a caption to short plain text: it is emitted as HTML-escaped text, so it
    can never inject markup, but this pass runs after the chip and wikilink
    passes, so ``:key[..]`` / ``[[..]]`` / Markdown syntax inside a caption is not
    meaningfully rendered (escaped as literal text). Fenced and inline code are
    protected so a ``~ ...`` example inside code is never rewritten.
    """
    protected, placeholders = _protect_code(md_text)
    lines = protected.split("\n")
    out: list[str] = []
    for line in lines:
        m = _CAPTION_RE.match(line)
        caption = _html.escape(m.group(1).strip(), quote=False) if m else ""
        if caption:
            out.append(f'<p class="caption">{caption}</p>')
            # A blank line so Python-Markdown treats the ``<p>`` as its own raw
            # HTML block rather than folding it into an adjacent paragraph.
            out.append("")
        else:
            out.append(line)
    return _restore_code("\n".join(out), placeholders)


# ── Footer Preprocessing ──


# The opening / closing lines of a ``::: footer`` container. Only ``::: footer``
# opens one; any other ``::: xxx`` is left literal. ``:::`` alone closes it.
_FOOTER_OPEN = "::: footer"
_FOOTER_CLOSE = ":::"


def preprocess_footer(md_text: str) -> str:
    """Convert a ``::: footer`` container to a ``<footer>`` region.

    Converts::

        ::: footer
        Traced from **converter.py**.

        - report.css
        - converter.py
        :::

    to a ``<footer class="doc-footer" markdown="1">`` block whose inner Markdown
    is processed by the ``md_in_html`` extension (so emphasis, links, and lists
    work) and then sanitised by the normal ``nh3.clean`` pass -- the footer body
    is ordinary author content, so it needs no special escaping. An unclosed
    container runs to the end of the document. Fenced and inline code are
    protected so a ``::: footer`` example inside code is never rewritten.
    """
    protected, placeholders = _protect_code(md_text)
    lines = protected.split("\n")
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        if lines[i].strip() == _FOOTER_OPEN:
            i += 1
            inner: list[str] = []
            while i < n and lines[i].strip() != _FOOTER_CLOSE:
                inner.append(lines[i])
                i += 1
            if i < n:  # consume the closing ``:::``
                i += 1
            out.append('<footer class="doc-footer" markdown="1">')
            out.append("")
            out.extend(inner)
            out.append("")
            out.append("</footer>")
        else:
            out.append(lines[i])
            i += 1
    return _restore_code("\n".join(out), placeholders)


# ── Keyed Table Preprocessing ──


# A ``{.keyed}`` opt-in line, on its own, marking the table that follows as having
# an accent key column (its first column styled like the scaffold's ``td.ends``).
# Markdown ``attr_list`` cannot attach a class to a table, so this line is the
# opt-in. It is kept as literal text and merely separated into its own paragraph;
# :func:`_wrap_tables` keys the table only when a real ``<table>`` actually
# follows, so a ``{.keyed}`` that is not above a genuine table stays visible as
# literal text rather than being silently consumed.
_KEYED_MARKER_RE = re.compile(r"^\{\.keyed\}[ \t]*$")


def preprocess_keyed_tables(md_text: str) -> str:
    """Separate a ``{.keyed}`` opt-in line into its own paragraph.

    A ``{.keyed}`` line directly above a table would otherwise be lazy-merged
    into the table by Markdown (any text touching a table breaks it), so a blank
    line is inserted after it. The line itself is left intact -- it converts to a
    ``<p>{.keyed}</p>`` paragraph that :func:`_wrap_tables` turns into the
    ``keyed`` class when (and only when) a ``<table>`` immediately follows;
    otherwise it renders as the literal text ``{.keyed}``. A ``{.keyed}`` inside
    code is protected, and one nested in a blockquote/list (not at column 0) is
    left untouched -- keyed tables are a top-level affordance.
    """
    protected, placeholders = _protect_code(md_text)
    lines = protected.split("\n")
    out: list[str] = []
    n = len(lines)
    for i, line in enumerate(lines):
        out.append(line)
        if _KEYED_MARKER_RE.match(line) and i + 1 < n and lines[i + 1].strip():
            # A blank line so the following table isn't merged into this line.
            out.append("")
    return _restore_code("\n".join(out), placeholders)


# ── Math Delimiter Rewriting ──

# pymdownx.arithmatex generic mode wraps each expression in an
# ``arithmatex``-classed element. Depending on version the expression sits in
# a ``<script type="math/tex">`` tag or in ``\(...\)`` / ``\[...\]`` markup.

# Matches arithmatex inline math: <span class="arithmatex">...\(EXPR\)...</span>
_INLINE_MATH_RE = re.compile(
    r'<span\s+class="arithmatex">\s*(?:<span[^>]*>.*?</span>)?\s*'
    r"(?:"
    r'<script\s+type="math/tex">(.*?)</script>'
    r"|"
    r"\\\\?\((.*?)\\\\?\)"
    r")\s*</span>",
    re.DOTALL,
)

# Matches arithmatex display math: <div class="arithmatex">...\[EXPR\]...</div>
_DISPLAY_MATH_RE = re.compile(
    r'<div\s+class="arithmatex">\s*(?:<div[^>]*>.*?</div>)?\s*'
    r"(?:"
    r'<script\s+type="math/tex;\s*mode=display">(.*?)</script>'
    r"|"
    r"\\\\?\[(.*?)\\\\?\]"
    r")\s*</div>",
    re.DOTALL,
)


def _prerender_math(html: str) -> str:
    """Replace pymdownx.arithmatex output with static, pre-rendered KaTeX markup.

    Each inline and display expression is typeset at convert time by
    ``katex_render.render_math`` and spliced back in place of the arithmatex
    element, so the document ships finished KaTeX HTML with no JavaScript
    engine. arithmatex HTML-escapes the expression it emits, so each is
    unescaped to raw LaTeX before rendering (KaTeX consumes LaTeX directly).
    """
    # (start, end, replacement) tuples, applied end-to-start so positions hold.
    replacements: list[tuple[int, int, str]] = []

    for m in _INLINE_MATH_RE.finditer(html):
        expr = m.group(1) if m.group(1) is not None else m.group(2)
        if expr is None:
            continue
        markup = katex_render.render_math(_html.unescape(expr.strip()), display=False)
        replacements.append((m.start(), m.end(), markup))

    for m in _DISPLAY_MATH_RE.finditer(html):
        expr = m.group(1) if m.group(1) is not None else m.group(2)
        if expr is None:
            continue
        markup = katex_render.render_math(_html.unescape(expr.strip()), display=True)
        replacements.append((m.start(), m.end(), markup))

    if not replacements:
        return html

    replacements.sort(key=lambda x: x[0], reverse=True)
    for start, end, replacement in replacements:
        html = html[:start] + replacement + html[end:]

    return html


# ── Table Scroll Wrapping ──


# A whole ``<table>...</table>``, optionally preceded by the ``<p>{.keyed}</p>``
# paragraph a ``{.keyed}`` opt-in line converts to. Non-greedy: Markdown tables
# never nest, so each match is one complete table. Only real Markdown tables are
# matched -- KaTeX emits MathML ``<mtable>`` (not HTML ``<table>``) and mermaid is
# still a placeholder at this point. A ``<p>{.keyed}</p>`` not immediately before a
# ``<table>`` is left untouched, so it renders as the literal text ``{.keyed}``.
_TABLE_WRAP_RE = re.compile(
    r'(<p>\{\.keyed\}</p>\s*)?(<table\b[^>]*>.*?</table>)', re.S
)


def _wrap_tables(html: str) -> str:
    """Wrap each ``<table>`` in a ``<div class="tbl-scroll">`` scroll container.

    The ``tables`` extension emits a bare ``<table>`` with no wrapper. A table
    wider than the content column would otherwise overflow the page (the card's
    corner-clipping ``overflow`` on the table itself hid the overflow). Wrapping
    each table lets the report theme put the card framing (border, radius,
    shadow) and ``overflow-x: auto`` on the wrapper, so a wide table keeps its
    column widths and scrolls horizontally within the card. The wrapper ``div``
    and its class survive ``nh3.clean``.

    A table immediately preceded by a ``<p>{.keyed}</p>`` paragraph (from a
    ``{.keyed}`` opt-in line) gets the extra ``keyed`` class so the theme styles
    its first column as an accent key, and that paragraph is consumed. A
    ``{.keyed}`` paragraph with no table after it is left in place -- it renders
    as literal text, never silently dropped.
    """
    def _wrap(m: re.Match[str]) -> str:
        cls = "tbl-scroll keyed" if m.group(1) else "tbl-scroll"
        return f'<div class="{cls}">{m.group(2)}</div>'

    return _TABLE_WRAP_RE.sub(_wrap, html)


# ── Code Sheet Header ──


# The ``<span class="filename">`` that ``pymdownx.highlight`` emits for a fenced
# block's ``title=`` attribute (``` ```{.python title="..."} ```). The match is
# anchored to the opening ``<div class="highlight">`` so only a highlighter-emitted
# filename (the first child of a code block) is rewritten, never a stray
# ``.filename`` span an author wrote in prose. The non-greedy body match is safe
# because an escaped ``</span>`` inside a title reads ``&lt;/span&gt;``.
_FILENAME_RE = re.compile(
    r'(<div class="highlight">)<span class="filename">(.*?)</span>', re.S
)


def _style_code_headers(html: str) -> str:
    """Turn a code block's ``title=`` filename into a titled ``.sheet-head`` bar.

    A fenced block written ``` ```{.python title="Before the fix | MainWnd.cs"} ```
    highlights normally and carries a ``<span class="filename">`` header inside its
    ``<div class="highlight">``. This rewrites that span into the same header
    treatment the diagram card uses: a ``left | right`` title splits (on the first
    ``|``) into a left-aligned label and a right-aligned meta note; a plain title
    is a single left label. The report theme joins the header and the code into
    one card.

    The captured title text is re-emitted as-is (the highlighter has already
    HTML-escaped it, so no double-escaping). This pass runs BEFORE ``nh3.clean``,
    which is the sanitisation backstop: even a title that somehow carried live
    markup is neutralised downstream, so re-emitting verbatim is safe.
    """
    def _replace(m: re.Match[str]) -> str:
        content = m.group(2)
        left, sep, right = content.partition("|")
        left, right = left.strip(), right.strip()
        if sep and left and right:
            head = (
                '<div class="sheet-head">'
                f'<span class="t">{left}</span>'
                f'<span class="r">{right}</span>'
                "</div>"
            )
        else:
            single = left or right or content.strip()
            head = f'<div class="sheet-head"><span class="t">{single}</span></div>'
        return m.group(1) + head

    return _FILENAME_RE.sub(_replace, html)


# Pygments wraps each highlighted line in ``<span class="hll">…code…\n</span>``
# with the line-terminating newline INSIDE the span. When the report theme makes
# ``.hll`` an ``inline-block`` (so the band covers a horizontally-scrolled wide
# line), two consecutive highlighted lines become adjacent inline-blocks with no
# line break between them and pile onto one row. Moving the newline OUT to after
# ``</span>`` restores a real break between bands while keeping the inline-block.
_HLL_NEWLINE_RE = re.compile(r'(<span class="hll">.*?)\n</span>', re.S)


def _fix_hll_line_breaks(html: str) -> str:
    """Move each ``.hll`` line's terminating newline outside its span.

    So consecutive highlighted lines each render as their own full-width band on
    their own line instead of collapsing onto one row. A highlighted line's inner
    token spans never carry a ``\\n`` immediately before their ``</span>``, so the
    match only ever lands on the ``hll`` wrapper's own close.
    """
    return _HLL_NEWLINE_RE.sub(r"\1</span>\n", html)


# ── Core Functions ──


def extract_title(md_text: str) -> str:
    """Extract the H1 title from markdown text. Returns 'Untitled' if none.

    Fenced code blocks are lifted out first so a ``# comment`` line inside a
    code fence is never mistaken for the document heading.
    """
    protected, _ = _protect_code(md_text, inline=False)
    match = re.search(r"^#\s+(.+)$", protected, re.MULTILINE)
    return match.group(1).strip() if match else "Untitled"


# Markdown extensions and their configuration
_MD_EXTENSIONS = [
    "tables",
    "pymdownx.betterem",
    "pymdownx.tilde",
    "pymdownx.mark",
    # Typographic dashes only: ``--`` -> en-dash, ``---`` -> em-dash. Quotes and
    # ellipses are left as typed (configured off below).
    "smarty",
    "pymdownx.tasklist",
    "pymdownx.highlight",
    "pymdownx.superfences",
    "pymdownx.arithmatex",
    "footnotes",
    "admonition",
    # Processes Markdown inside a ``markdown="1"`` raw-HTML block -- used for the
    # ``<footer>`` a ``::: footer`` container emits.
    "md_in_html",
    "toc",
]

_MD_EXTENSION_CONFIGS = {
    "pymdownx.arithmatex": {
        "generic": True,
    },
    "pymdownx.tasklist": {
        "custom_checkbox": True,
    },
    "pymdownx.highlight": {
        "guess_lang": False,
    },
    "pymdownx.superfences": {
        # Route ```mermaid fences to the diagram pre-renderer; every other
        # fence keeps the default highlighter.
        "custom_fences": [mermaid_render.superfences_config()],
    },
    "toc": {
        "marker": "",
    },
    "smarty": {
        # Dashes only -- leave quotes/ellipses as the author typed them.
        "smart_quotes": False,
        "smart_ellipses": False,
        "smart_angled_quotes": False,
    },
}

# Tags and attributes allowed through nh3 sanitisation.
# These cover output from all markdown extensions: admonition divs, highlight
# spans, math delimiter spans, task list inputs, footnote links, etc.

_NH3_ALLOWED_TAGS = {
    "div",
    "span",
    "p",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "ul",
    "ol",
    "li",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "a",
    "strong",
    "em",
    "del",
    "mark",
    "code",
    "pre",
    "blockquote",
    "hr",
    "img",
    "br",
    "input",
    "sup",
    "sub",
    "figure",
    "figcaption",
    "footer",
    "details",
    "summary",
    "dl",
    "dt",
    "dd",
    "section",
    "abbr",
    "math",
    "semantics",
    "mrow",
    "mi",
    "mo",
    "mn",
    "msup",
    "msub",
    "msubsup",
    "mfrac",
    "msqrt",
    "mroot",
    "mover",
    "munder",
    "munderover",
    "mstyle",
    "mtable",
    "mtr",
    "mtd",
    "mspace",
    "mtext",
    "annotation",
    "svg",
    "path",
    "line",
    "rect",
    "circle",
}

_NH3_ALLOWED_ATTRIBUTES: dict[str, set[str]] = {
    "*": {"class", "id"},
    "a": {"href", "title"},
    "img": {"src", "alt", "title", "width", "height"},
    "input": {"type", "checked", "disabled"},
    "td": {"align", "colspan", "rowspan"},
    "th": {"align", "colspan", "rowspan"},
    "ol": {"start", "type"},
    "li": {"value"},
    # KaTeX positions its HTML spans with inline ``style`` and marks its
    # duplicated MathML tree ``aria-hidden``.
    "span": {"style", "aria-hidden"},
    # KaTeX HTML and MathML attributes. ``svg``/``path`` also cover the inline
    # SVG KaTeX draws for radicals and stretchy delimiters.
    "svg": {"xmlns", "viewBox", "width", "height", "fill", "preserveAspectRatio"},
    "path": {"d", "fill", "stroke", "stroke-width"},
    "math": {"xmlns", "display"},
    "annotation": {"encoding"},
    "mo": {"stretchy", "fence"},
    "mi": {"mathvariant"},
    "mstyle": {"scriptlevel", "displaystyle"},
    "mspace": {"width"},
    "mover": {"accent"},
    "munder": {"accentunder"},
    "mtable": {"rowspacing", "columnalign", "columnspacing"},
}

# The CSS properties KaTeX sets via inline ``style``. Passed to nh3 as
# ``filter_style_properties`` so any other declaration (a ``background:url(...)``
# or ``behavior:`` payload) is dropped while KaTeX's own layout survives.
#
# ``position`` is deliberately excluded. KaTeX's HTML only ever sets it to
# ``relative`` on its ``op-symbol`` spans, which the bundled stylesheet already
# positions via the ``.katex .op-symbol`` rule, so the inline copy is redundant
# and dropping it leaves rendering intact (the ``top`` offset still applies).
# Excluding the property means nh3 strips every ``position`` declaration by its
# normalised name -- so a viewport-pinning ``position: fixed`` / ``sticky``
# overlay injected through the math source cannot survive, and neither can an
# escape-obfuscated spelling (``position:\66 ixed``) that a value-level check on
# the pre-normalised string would miss.
_KATEX_STYLE_PROPS = {
    "height",
    "top",
    "margin-right",
    "margin-left",
    "vertical-align",
    "border-bottom-width",
    "padding-left",
    "min-width",
    "width",
}

# URL schemes nh3 lets through. nh3's scheme gate is global (it cannot vary by
# tag), so ``data:`` is added to the default allowlist here and then narrowed
# by :func:`_nh3_attribute_filter` to image sources only -- otherwise a
# ``data:text/html`` payload on a link would pass too.
_NH3_URL_SCHEMES = set(nh3.ALLOWED_URL_SCHEMES) | {"data"}


def _strip_url_noise(value: str) -> str:
    """Normalise a URL for scheme classification.

    Browsers ignore ASCII whitespace and C0 control characters when resolving a
    URL's scheme (``da\\tta:`` reads as ``data:``, leading spaces are dropped),
    and nh3 classifies schemes the same way. Removing every character up to and
    including ``0x20`` and lowercasing yields a form at least as aggressive, so
    an obfuscated scheme cannot slip past the classification below.
    """
    return "".join(ch for ch in value if ord(ch) > 0x20).lower()


def _nh3_attribute_filter(tag: str, attr: str, value: str) -> str | None:
    """Permit a ``data:`` URI only as an image source, drop it everywhere else.

    A ``data:`` URI keeps an embedded image self-contained (no network fetch),
    but the same scheme on a link (``data:text/html`` → script execution on
    navigation) is an XSS vector. nh3 has already validated the scheme against
    :data:`_NH3_URL_SCHEMES` before this runs, so the only ``data:`` values seen
    here are ones a browser would honour; this narrows them to ``img src`` with
    an ``image/`` MIME type. Every other attribute passes unchanged.

    An SVG loaded through ``<img>`` runs with scripting disabled, so a
    ``data:image/svg+xml`` source cannot execute its own markup.
    """
    normalised = _strip_url_noise(value)
    if normalised.startswith("data:"):
        if tag == "img" and attr == "src" and normalised.startswith("data:image/"):
            return value
        return None
    return value


def md_to_html(
    md_text: str,
    *,
    ignore_callouts: set[str] | None = None,
    dark: bool = False,
    adaptive: bool = False,
) -> str:
    """Convert markdown text to an HTML body fragment.

    Full pipeline:
    1. Obsidian callout preprocessing
    1a. Wikilink preprocessing (``[[Page]]`` → ``[Page](Page.html)``)
    1b. Chip preprocessing (``:key[label]`` → ``<span class="pchip key">``)
    2. Markdown conversion with all extensions (```mermaid``` fences render to
       inline SVG, held aside behind a placeholder)
    3. Math pre-rendering (arithmatex → static KaTeX markup)
    4. nh3 HTML sanitisation
    5. Restore the rendered mermaid SVG in place of its placeholder, after
       sanitisation, since the trusted SVG carries a load-bearing ``<style>``
       block nh3 would otherwise strip.

    When *ignore_callouts* is provided, callout blocks whose type is in the
    set are removed from the output entirely. When *dark* is true, mermaid
    diagrams render with the dark theme. When *adaptive* is true, the theme
    adapts to ``prefers-color-scheme`` and structural diagrams' author classDef
    colours are given a dark-mode variant.
    """
    # Step 0: Drop literal NUL bytes so they cannot collide with the
    # NUL-delimited code placeholder sentinels used throughout the pipeline.
    md_text = md_text.replace("\x00", "")

    mermaid_render.begin_conversion(dark=dark, adaptive=adaptive)
    try:
        # Step 1: Preprocess Obsidian callouts
        md_text = preprocess_obsidian_callouts(
            md_text, ignore_callouts=ignore_callouts
        )

        # Step 1a: Convert Obsidian wikilinks to standard Markdown links
        md_text = preprocess_wikilinks(md_text)

        # Step 1b: Convert inline ``:key[label]`` chips to coloured spans
        md_text = preprocess_chips(md_text)

        # Step 1c: Convert ``^ Label`` kicker lines above a heading to section
        # labels (``.sec-label``).
        md_text = preprocess_section_kickers(md_text)

        # Step 1d: Convert ``~ text`` marker lines to captions (``.caption``).
        md_text = preprocess_captions(md_text)

        # Step 1e: Mark a ``{.keyed}`` table for an accent key column.
        md_text = preprocess_keyed_tables(md_text)

        # Step 1f: Convert a ``::: footer`` container to a ``<footer>`` region.
        md_text = preprocess_footer(md_text)

        # Step 2: Convert markdown to HTML
        md_converter = markdown.Markdown(
            extensions=_MD_EXTENSIONS,
            extension_configs=_MD_EXTENSION_CONFIGS,
            output_format="html",
        )
        html = md_converter.convert(md_text)

        # Step 3: Pre-render math into static KaTeX markup
        html = _prerender_math(html)

        # Step 3a: Wrap each table in a horizontal-scroll container so a wide
        # table scrolls within the card instead of overflowing the page.
        html = _wrap_tables(html)

        # Step 3b: Turn a code block's ``title=`` filename into a titled card
        # header (``.sheet-head``).
        html = _style_code_headers(html)

        # Step 3c: Move each highlighted line's terminating newline outside its
        # ``.hll`` span so consecutive banded lines break onto separate rows.
        html = _fix_hll_line_breaks(html)

        # Step 4: Sanitise with nh3
        html = nh3.clean(
            html,
            tags=_NH3_ALLOWED_TAGS,
            attributes=_NH3_ALLOWED_ATTRIBUTES,
            url_schemes=_NH3_URL_SCHEMES,
            attribute_filter=_nh3_attribute_filter,
            filter_style_properties=_KATEX_STYLE_PROPS,
        )

        # Step 5: Restore trusted mermaid SVG behind the sanitiser
        html = mermaid_render.restore_mermaid(html)
    finally:
        mermaid_render.end_conversion()

    return html


def load_theme_css(theme_name: str, themes_dir: Path | None = None) -> str:
    """Load a theme CSS file by name.

    Raises ValueError if the theme is not found.
    Raises FileNotFoundError if the themes directory doesn't exist.
    """
    if themes_dir is None:
        themes_dir = THEMES_DIR

    if not themes_dir.is_dir():
        raise FileNotFoundError(f"Themes directory not found: {themes_dir}")

    css_path = themes_dir / f"{theme_name}.css"
    if not css_path.is_file():
        available = list_themes(themes_dir)
        raise ValueError(
            f"Theme '{theme_name}' not found. "
            f"Available themes: {', '.join(available) if available else '(none)'}"
        )

    return css_path.read_text(encoding="utf-8")


def list_themes(themes_dir: Path | None = None) -> list[str]:
    """Return a sorted list of available theme names."""
    if themes_dir is None:
        themes_dir = THEMES_DIR

    if not themes_dir.is_dir():
        return []

    return sorted(p.stem for p in themes_dir.glob("*.css") if p.is_file())


# ── Table of Contents ──


class _HeadingExtractor(HTMLParser):
    """Extract headings (with ``id``) and their section kicker from an HTML body.

    Each heading's TOC label is the section kicker -- the ``<p class="sec-label">``
    a ``^ Label`` line sets directly above the heading -- falling back to the
    heading's own text when the section carries no kicker. A kicker's ``<p>`` sits
    immediately before its heading, so a captured kicker is carried to the next
    heading and dropped if any other block appears in between.
    """

    _HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6")

    def __init__(self, max_depth: int = 3) -> None:
        super().__init__()
        self.headings: list[tuple[int, str, str]] = []  # (level, id, label)
        self._current: tuple[int, str] | None = None
        self._current_kicker: str | None = None
        self._text_parts: list[str] = []
        self.max_depth = max_depth
        self._in_kicker = False
        self._kicker_parts: list[str] = []
        self._pending_kicker: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = dict(attrs)
        if tag == "p" and "sec-label" in (attr_dict.get("class") or "").split():
            # Capture the kicker text to carry forward to the next heading.
            self._in_kicker = True
            self._kicker_parts = []
            return
        if tag in self._HEADINGS:
            # The heading consumes any pending kicker regardless of its depth or
            # whether it has an id, so a kicker never leaks past the heading it
            # labels onto a later one.
            kicker = self._pending_kicker
            self._pending_kicker = None
            level = int(tag[1])
            if level <= self.max_depth:
                heading_id = attr_dict.get("id")
                if heading_id:
                    self._current = (level, heading_id)
                    self._current_kicker = kicker
                    self._text_parts = []
            return
        if not self._in_kicker:
            # Any other block breaks the kicker's adjacency to a heading.
            self._pending_kicker = None

    def handle_endtag(self, tag: str) -> None:
        if self._in_kicker and tag == "p":
            self._in_kicker = False
            self._pending_kicker = "".join(self._kicker_parts).strip() or None
            return
        if self._current and tag in self._HEADINGS:
            level, heading_id = self._current
            text = "".join(self._text_parts).strip()
            # The kicker is a valid label in its own right, so a heading with a
            # kicker still lists even when its own text is empty.
            label = self._current_kicker or text
            if label:
                self.headings.append((level, heading_id, label))
            self._current = None
            self._current_kicker = None
            self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_kicker:
            self._kicker_parts.append(data)
        elif self._current is not None:
            self._text_parts.append(data)


def _extract_headings(
    html_body: str, max_depth: int = 3,
) -> list[tuple[int, str, str]]:
    """Return ``[(level, id, label), ...]`` for headings in *html_body*.

    ``label`` is the heading's section kicker when it has one, else its own text.
    """
    parser = _HeadingExtractor(max_depth)
    parser.feed(html_body)
    return parser.headings


def _build_toc_nav(html_body: str, max_depth: int = 3) -> str:
    """Build a ``<nav id="toc">`` sidebar from headings in *html_body*.

    Returns an empty string when no headings are found.
    """
    headings = _extract_headings(html_body, max_depth)
    if not headings:
        return ""

    parts: list[str] = [
        '<nav id="toc" aria-label="Table of Contents">',
        '<div class="toc-head">'
        '<div class="toc-title">Table of Contents</div>'
        '<button type="button" class="toc-toggle" aria-expanded="true"'
        ' aria-controls="toc-list"'
        ' aria-label="Collapse table of contents"></button>'
        "</div>",
    ]
    # ``open_levels`` is a stack holding the heading level of each currently
    # open ``<ul>``. Nesting advances at most one step per heading regardless
    # of the numeric gap between heading levels, so ``<ul>``/``<li>`` opens and
    # closes stay exactly paired even across non-contiguous jumps (e.g. h1->h3
    # or a document that starts at h2).
    open_levels: list[int] = []

    for level, hid, text in headings:
        if not open_levels:
            # The outermost list is the disclosure region the toggle controls
            # (referenced by the button's ``aria-controls``); nested lists are
            # plain ``<ul>``.
            parts.append('<ul id="toc-list">')
            open_levels.append(level)
        elif level > open_levels[-1]:
            # One step deeper: nest a new list inside the current open item.
            parts.append("<ul>")
            open_levels.append(level)
        else:
            # Same level or shallower: close the current item, then unwind any
            # deeper lists until the stack top is at (or below) this level.
            parts.append("</li>")
            while len(open_levels) > 1 and level < open_levels[-1]:
                parts.append("</ul></li>")
                open_levels.pop()
            open_levels[-1] = level

        safe_hid = _html.escape(hid, quote=True)
        safe_text = _html.escape(text)
        parts.append(f'<li><a href="#{safe_hid}">{safe_text}</a>')

    # Close the last open item and every remaining list.
    parts.append("</li>")
    while open_levels:
        parts.append("</ul>")
        open_levels.pop()
        if open_levels:
            parts.append("</li>")

    parts.append("</nav>")
    return "\n".join(parts)


# Scrollspy for the ``--toc`` sidebar: marks the heading currently in view and
# keeps that link visible WITHIN the sidebar.
#
# It deliberately does not use ``scrollIntoView``. That call scrolls every
# scrollable ancestor, including the document, so on a theme whose ``toc``
# section is missing or leaves ``#toc`` in the document flow it scrolls the PAGE
# to the link — which fires another scroll event, which re-runs this, forever.
# The result is an unbreakable flicker that makes the page unreadable, and
# themes are user-authorable, so "every theme sets ``#toc { position: fixed }``"
# is not an assumption this can safely make. Mutating ``toc.scrollTop`` instead
# can only ever move the sidebar, and is a no-op when the sidebar does not scroll.
TOC_JS = """\
(function(){
var toc=document.getElementById('toc');
if(!toc)return;
var links=Array.from(toc.querySelectorAll('a[href^=\"#\"]'));
var entries=links.map(function(a){
var id=decodeURIComponent(a.getAttribute('href').slice(1));
var h=document.getElementById(id);
// Cache each heading's scroll-margin-top: the line a TOC jump parks it on
// (e.g. above a section kicker), which is also where the scrollspy should
// consider it reached.
return{link:a,heading:h,margin:h?parseFloat(getComputedStyle(h).scrollMarginTop)||0:0};
}).filter(function(e){return e.heading;});
if(!entries.length)return;
var raf;
function update(){
raf=null;
var active=null,i;
var de=document.documentElement;
var scrollable=de.scrollHeight-window.innerHeight>1;
// On a genuinely scrollable page a short final section can't reach the trigger
// line, so pin the last entry once fully scrolled. The scrollable guard stops a
// page that already fits the viewport from wrongly pinning the last entry.
if(scrollable&&window.innerHeight+window.scrollY>=de.scrollHeight-2){
active=entries[entries.length-1].link;
}else{
// getBoundingClientRect is viewport-relative, so the active heading is found
// correctly whatever offsetParent a theme's layout gives the headings.
for(i=0;i<entries.length;i++){
// A heading is reached once its top hits its own landing line (its
// scroll-margin-top) plus a small buffer, so a kicker-led section lights up
// the moment it parks at the top rather than only after its heading does.
if(entries[i].heading.getBoundingClientRect().top<=entries[i].margin+20)active=entries[i].link;
}
// Before the first heading crosses the line, light the first entry.
if(!active)active=entries[0].link;
}
links.forEach(function(l){l.classList.remove('active');l.removeAttribute('aria-current');});
if(!active)return;
active.classList.add('active');
active.setAttribute('aria-current','location');
if(toc.scrollHeight<=toc.clientHeight)return;
var tr=toc.getBoundingClientRect(),ar=active.getBoundingClientRect();
if(ar.top<tr.top)toc.scrollTop-=tr.top-ar.top;
else if(ar.bottom>tr.bottom)toc.scrollTop+=ar.bottom-tr.bottom;
}
function schedule(){if(!raf)raf=requestAnimationFrame(update);}
window.addEventListener('scroll',schedule,{passive:true});
window.addEventListener('resize',schedule,{passive:true});
update();
})();
// Collapse/expand toggle: the button flips the sidebar between the full list and
// a slim rail. State is not persisted -- each page load starts expanded -- so a
// shared HTML file always opens showing its contents.
(function(){
var toc=document.getElementById('toc');
if(!toc)return;
var btn=toc.querySelector('.toc-toggle');
if(!btn)return;
btn.addEventListener('click',function(){
var collapsed=toc.classList.toggle('collapsed');
btn.setAttribute('aria-expanded',collapsed?'false':'true');
btn.setAttribute('aria-label',collapsed?'Expand table of contents':'Collapse table of contents');
});
})();
"""


# ── Rendering ──


# Extensions used to render inline markdown inside hero fields (lede, slot
# heading/body). Kept to the inline-formatting subset -- emphasis, strike,
# highlight -- so a hero line reads like body prose; block constructs are not
# expected in a one-line field. Core markdown (links, inline code) is always on.
_INLINE_MD_EXTENSIONS = [
    "pymdownx.betterem",
    "pymdownx.tilde",
    "pymdownx.mark",
    "smarty",
]
_INLINE_MD_CONFIGS = {
    "smarty": {
        "smart_quotes": False,
        "smart_ellipses": False,
        "smart_angled_quotes": False,
    },
}


def _render_inline(text: str) -> str:
    """Render a one-line hero field's inline markdown to sanitised HTML.

    The field is converted with the inline-formatting extensions, unwrapped
    from the single ``<p>`` markdown adds, and run through the same nh3 pass as
    the body -- so author markup (a link, ``code``, ``**bold**``) works while
    any hostile markup is neutralised. It is therefore safe to splice into the
    trusted hero structure built by :func:`_render_hero`.
    """
    md = markdown.Markdown(
        extensions=_INLINE_MD_EXTENSIONS,
        extension_configs=_INLINE_MD_CONFIGS,
        output_format="html",
    )
    rendered = md.convert(text).strip()
    if (
        rendered.startswith("<p>")
        and rendered.endswith("</p>")
        and rendered.count("<p>") == 1
    ):
        rendered = rendered[3:-4]
    return nh3.clean(
        rendered,
        tags=_NH3_ALLOWED_TAGS,
        attributes=_NH3_ALLOWED_ATTRIBUTES,
        url_schemes=_NH3_URL_SCHEMES,
        attribute_filter=_nh3_attribute_filter,
        filter_style_properties=_KATEX_STYLE_PROPS,
    )


def _render_hero(fm: frontmatter.FrontMatter) -> str:
    """Build the report hero ``<header>`` from parsed front matter.

    Emits the eyebrow kicker, the title ``<h1>``, the lede, and a ``.stages``
    grid of ``.stage-card`` slot boxes -- each an optional block, so a hero can
    be just a title or a full three-card rail. Eyebrow and slot labels are plain
    mono kickers (HTML-escaped); the lede and slot heading/body carry inline
    markdown via :func:`_render_inline`. Styled by the ``report`` theme; other
    themes leave the structure unstyled, as with chips.
    """
    parts = ['<header class="report-hero">']
    if fm.eyebrow:
        parts.append(f'<p class="eyebrow">{_html.escape(fm.eyebrow)}</p>')
    if fm.title:
        parts.append(f"<h1>{_html.escape(fm.title)}</h1>")
    if fm.lede:
        parts.append(f'<p class="lede">{_render_inline(fm.lede)}</p>')
    cards: list[str] = []
    for slot in fm.slots:
        # An empty slot (no label/heading/body) contributes no card, so a stray
        # ``slot:`` line never renders an empty box in the rail.
        if not (slot.label or slot.heading or slot.body):
            continue
        card = ['<div class="stage-card">']
        if slot.label:
            card.append(f'<span class="n">{_html.escape(slot.label)}</span>')
        if slot.heading:
            card.append(f"<h3>{_render_inline(slot.heading)}</h3>")
        if slot.body:
            card.append(f"<p>{_render_inline(slot.body)}</p>")
        card.append("</div>")
        cards.append("".join(card))
    if cards:
        parts.append(f'<div class="stages">{"".join(cards)}</div>')
    parts.append("</header>")
    return "\n".join(parts)


def _head_extra_for(body: str) -> str:
    """Return the ``<head>`` snippet needed by *body*.

    The KaTeX stylesheet (with its base64 fonts) is injected only when the body
    carries KaTeX markup, which needs that stylesheet to display. KaTeX wraps
    every expression in a ``class="katex"`` root, so that attribute is the
    sentinel -- present both for math this converter pre-rendered and for KaTeX
    markup an author wrote as raw HTML (which equally needs the CSS). A document
    that merely mentions "katex" in prose or inline code has its ``<``/``>``
    escaped, so the attribute never forms and it ships zero KaTeX bytes. No
    script is injected: math is already typeset in the markup.
    """
    has_math = 'class="katex' in body
    return katex_assets.katex_css_head_assets() if has_math else ""


def render_html(
    md_text: str,
    css: str,
    title: str | None = None,
    *,
    ignore_callouts: set[str] | None = None,
    toc: bool = False,
    dark: bool = False,
    adaptive: bool = False,
) -> str:
    """Convert markdown to a full HTML document string.

    A leading ``---`` front-matter block is split off first: it supplies the
    report hero (eyebrow / title / lede / slot cards) and the document
    ``<title>``, and is removed from the markdown before conversion. A document
    without such a block is unaffected.

    When *toc* is True, a fixed table-of-contents sidebar is prepended to
    the body and scroll-tracking JavaScript is appended. When *dark* is true,
    mermaid diagrams render with the dark theme.
    """
    fm, body_md = frontmatter.parse_frontmatter(md_text)

    if title is None:
        title = (fm.title if fm and fm.title else "") or extract_title(body_md)

    body = md_to_html(
        body_md,
        ignore_callouts=ignore_callouts,
        dark=dark,
        adaptive=adaptive,
    )

    head_extra = _head_extra_for(body)

    hero = _render_hero(fm) if fm and fm.has_hero else ""

    # The hero lives inside <main> (the content column beside the sidebar) when
    # a TOC is present, and at the top of the body otherwise. Its <h1> carries
    # no id, so it never enters the TOC built from the body headings.
    toc_nav = _build_toc_nav(body) if toc else ""
    if toc_nav:
        body = f"{toc_nav}\n<main>\n{hero}{body}\n</main>\n<script>\n{TOC_JS}</script>"
    elif hero:
        body = f"{hero}\n{body}"

    # Escape the title: it is interpolated raw into <title>, bypassing nh3.
    safe_title = _html.escape(title, quote=True)

    return HTML_TEMPLATE.format(
        title=safe_title, css=css, body=body, head_extra=head_extra
    )


# ── High-Level API ──


def convert(
    md_text: str,
    theme_name: str,
    themes_dir: Path | None = None,
    *,
    ignore_callouts: set[str] | None = None,
    toc: bool = False,
) -> str:
    """Convert markdown text to a full HTML document using a named theme.

    When *ignore_callouts* is provided, callout blocks whose type is in
    the set are removed from the output entirely.

    When *toc* is True, a table-of-contents sidebar is included in the output.

    The ``dark`` theme renders mermaid diagrams with matching light-on-dark
    colours; every other theme uses the default diagram palette.

    Raises ValueError for invalid inputs.
    """
    if not md_text or not md_text.strip():
        raise ValueError("Markdown text must not be empty.")

    css = load_theme_css(theme_name, themes_dir)

    return render_html(
        md_text,
        css,
        ignore_callouts=ignore_callouts,
        toc=toc,
        dark=theme_name.lower() == "dark",
        adaptive=theme_name.lower() == "report",
    )
