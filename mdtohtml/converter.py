"""Core conversion library for mdtohtml.

Converts Obsidian-compatible Markdown to styled, self-contained HTML with
themeable CSS. Math is emitted as plain KaTeX auto-render delimiters and
typeset client-side by a bundled KaTeX; documents without math carry zero
KaTeX bytes.

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

from . import katex_assets

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


def _escape_math(expr: str) -> str:
    """HTML-escape the characters that would otherwise break out of markup.

    arithmatex generic mode already HTML-escapes the expression it emits, so
    the text is first unescaped to the raw LaTeX and then escaped exactly
    once. This is idempotent and stays correct whether the source came from
    the ``\\(...\\)`` markup (pre-escaped) or a ``<script type="math/tex">``
    tag (raw).
    """
    raw = _html.unescape(expr)
    return raw.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _math_to_delimiters(html: str) -> str:
    """Replace pymdownx.arithmatex output with plain KaTeX auto-render markup.

    Each inline expression ``E`` becomes ``<span class="katex-inline">\\(E\\)</span>``
    and each display expression ``E`` becomes
    ``<span class="katex-display">\\[E\\]</span>``. The wrapping ``span`` and the
    literal ``\\(...\\)`` / ``\\[...\\]`` delimiters survive nh3 sanitisation and
    are picked up by KaTeX's ``renderMathInElement`` in the browser.
    """
    # (start, end, replacement) tuples, applied end-to-start so positions hold.
    replacements: list[tuple[int, int, str]] = []

    for m in _INLINE_MATH_RE.finditer(html):
        expr = m.group(1) if m.group(1) is not None else m.group(2)
        if expr is None:
            continue
        esc = _escape_math(expr.strip())
        replacements.append(
            (m.start(), m.end(), f'<span class="katex-inline">\\({esc}\\)</span>')
        )

    for m in _DISPLAY_MATH_RE.finditer(html):
        expr = m.group(1) if m.group(1) is not None else m.group(2)
        if expr is None:
            continue
        esc = _escape_math(expr.strip())
        replacements.append(
            (m.start(), m.end(), f'<span class="katex-display">\\[{esc}\\]</span>')
        )

    if not replacements:
        return html

    replacements.sort(key=lambda x: x[0], reverse=True)
    for start, end, replacement in replacements:
        html = html[:start] + replacement + html[end:]

    return html


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
    "pymdownx.tasklist",
    "pymdownx.highlight",
    "pymdownx.superfences",
    "pymdownx.arithmatex",
    "footnotes",
    "admonition",
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
    "toc": {
        "marker": "",
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
    "mfrac",
    "msqrt",
    "mover",
    "munder",
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
    "svg": {"xmlns", "viewBox", "width", "height", "fill"},
    "path": {"d", "fill", "stroke", "stroke-width"},
    "math": {"xmlns"},
}


def md_to_html(
    md_text: str,
    *,
    ignore_callouts: set[str] | None = None,
) -> str:
    """Convert markdown text to an HTML body fragment.

    Full pipeline:
    1. Obsidian callout preprocessing
    1a. Wikilink preprocessing (``[[Page]]`` → ``[Page](Page.html)``)
    2. Markdown conversion with all extensions
    3. Math delimiter rewriting (arithmatex → KaTeX auto-render delimiters)
    4. nh3 HTML sanitisation

    When *ignore_callouts* is provided, callout blocks whose type is in
    the set are removed from the output entirely.
    """
    # Step 0: Drop literal NUL bytes so they cannot collide with the
    # NUL-delimited code placeholder sentinels used throughout the pipeline.
    md_text = md_text.replace("\x00", "")

    # Step 1: Preprocess Obsidian callouts
    md_text = preprocess_obsidian_callouts(md_text, ignore_callouts=ignore_callouts)

    # Step 1a: Convert Obsidian wikilinks to standard Markdown links
    md_text = preprocess_wikilinks(md_text)

    # Step 2: Convert markdown to HTML
    md_converter = markdown.Markdown(
        extensions=_MD_EXTENSIONS,
        extension_configs=_MD_EXTENSION_CONFIGS,
        output_format="html",
    )
    html = md_converter.convert(md_text)

    # Step 3: Rewrite math into client-side KaTeX auto-render delimiters
    html = _math_to_delimiters(html)

    # Step 4: Sanitise with nh3
    html = nh3.clean(
        html,
        tags=_NH3_ALLOWED_TAGS,
        attributes=_NH3_ALLOWED_ATTRIBUTES,
    )

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
    """Extract headings with ``id`` attributes from an HTML body fragment."""

    def __init__(self, max_depth: int = 3) -> None:
        super().__init__()
        self.headings: list[tuple[int, str, str]] = []  # (level, id, text)
        self._current: tuple[int, str] | None = None
        self._text_parts: list[str] = []
        self.max_depth = max_depth

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag[1])
            if level <= self.max_depth:
                attr_dict = dict(attrs)
                heading_id = attr_dict.get("id")
                if heading_id:
                    self._current = (level, heading_id)
                    self._text_parts = []

    def handle_endtag(self, tag: str) -> None:
        if self._current and tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level, heading_id = self._current
            text = "".join(self._text_parts).strip()
            if text:
                self.headings.append((level, heading_id, text))
            self._current = None
            self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._current is not None:
            self._text_parts.append(data)


def _extract_headings(
    html_body: str, max_depth: int = 3,
) -> list[tuple[int, str, str]]:
    """Return ``[(level, id, text), ...]`` for headings in *html_body*."""
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
        '<div class="toc-title">Table of Contents</div>',
    ]
    # ``open_levels`` is a stack holding the heading level of each currently
    # open ``<ul>``. Nesting advances at most one step per heading regardless
    # of the numeric gap between heading levels, so ``<ul>``/``<li>`` opens and
    # closes stay exactly paired even across non-contiguous jumps (e.g. h1->h3
    # or a document that starts at h2).
    open_levels: list[int] = []

    for level, hid, text in headings:
        if not open_levels:
            parts.append("<ul>")
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
return{link:a,heading:document.getElementById(id)};
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
if(entries[i].heading.getBoundingClientRect().top<=20)active=entries[i].link;
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
"""


# ── Rendering ──


def _head_extra_for(body: str) -> str:
    """Return the ``<head>`` snippet needed by *body*.

    KaTeX assets are injected only when the body carries the math markup
    emitted by ``_math_to_delimiters`` -- the opening span tag immediately
    followed by its delimiter (``\\(`` or ``\\[``). Matching that whole
    sequence, rather than the bare class name, means a document that merely
    mentions ``katex-inline`` in prose or inline code (where any ``<``/``>``
    is escaped) ships zero KaTeX bytes.
    """
    has_math = ('class="katex-inline">\\(' in body) or (
        'class="katex-display">\\[' in body
    )
    return katex_assets.katex_head_assets() if has_math else ""


def render_html(
    md_text: str,
    css: str,
    title: str | None = None,
    *,
    ignore_callouts: set[str] | None = None,
    toc: bool = False,
) -> str:
    """Convert markdown to a full HTML document string.

    When *toc* is True, a fixed table-of-contents sidebar is prepended to
    the body and scroll-tracking JavaScript is appended.
    """
    if title is None:
        title = extract_title(md_text)

    body = md_to_html(
        md_text,
        ignore_callouts=ignore_callouts,
    )

    head_extra = _head_extra_for(body)

    if toc:
        toc_nav = _build_toc_nav(body)
        if toc_nav:
            body = f"{toc_nav}\n<main>\n{body}\n</main>\n<script>\n{TOC_JS}</script>"

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
    )
