"""Server-side Mermaid diagram rendering for mdtohtml.

Pre-renders ```mermaid``` fenced code blocks to static, inline SVG at convert
time so the published HTML carries zero runtime JavaScript and makes no network
request. Rendering runs fully in-process via ``mermaidx`` (embedded QuickJS +
mermaid.js + resvg + bundled font metrics); no Node, browser, or network is
involved.

The rendered SVG is trusted renderer output, not arbitrary user HTML: mermaid.js
runs with ``securityLevel="strict"`` and native ``<text>`` labels
(``htmlLabels=False``), so an author's diagram source is the only user input and
every label is escaped into ``<text>``/``<tspan>`` content. The SVG carries a
load-bearing ``<style>`` blob that must survive into the final document intact,
so it is injected AFTER the main ``nh3.clean`` pass via a placeholder registry
(see :func:`format_mermaid_fence` / :func:`restore_mermaid`), mirroring the
code-block protection in :mod:`mdtohtml.converter`.

On any render failure the block degrades gracefully to the original source
re-emitted as a fenced code block plus a visible note; rendering never raises to
the caller.
"""

from __future__ import annotations

import html as _html
import re
import secrets
import threading

import mermaidx

# ── Mermaid Configuration ──

# Forwarded to mermaid.js ``initialize``. ``strict`` security sanitises every
# label into escaped text; ``htmlLabels: false`` keeps mermaid emitting native
# ``<text>`` labels so no ``<foreignObject>``/HTML leaks into the SVG.
_MERMAID_CONFIG = {
    "securityLevel": "strict",
    "flowchart": {"htmlLabels": False},
}

# Theme names passed to ``mermaidx.render``. Both themes emit a transparent SVG
# canvas (mermaid paints no opaque full-canvas rect), so the diagram sits on the
# page background; the dark theme only swaps text/line colours to light tones so
# it reads on a dark page.
_THEME_DARK = "dark"
_THEME_LIGHT = "default"

# ``aria-roledescription`` values (set by mermaid on the SVG root) for the
# diagram families the report theme styles explicitly. Structural diagrams are
# recoloured to the theme palette; categorical pie/gantt keep their own hues and
# are darkened in dark mode. Any other family gets neither class, so an untested
# diagram type keeps mermaid's own colours rather than being mis-recoloured.
_STRUCTURAL_ROLES = frozenset({
    "flowchart-v2",
    "flowchart",
    "sequence",
    "stateDiagram",
    "stateDiagram-v2",
    "class",
    "classDiagram",
    "er",
})
_CATEGORICAL_ROLES = frozenset({"pie", "gantt"})


# ── Frontmatter Title → Card Header ──

# A leading mermaid YAML frontmatter block: ``---`` on its own line, YAML body,
# then a closing ``---`` line, then the diagram. Mermaid draws a ``title:`` field
# as a small caption inside the SVG; this theme instead lifts the title out into
# a styled ``.mermaid-header`` bar on the card, so the title line is extracted and
# removed before the source reaches mermaid.
_FRONTMATTER_RE = re.compile(r"\A\s*---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n(.*)\Z", re.S)

# A top-level ``title:`` line within the frontmatter body. Anchored at column 0
# so a ``title:`` nested under another key (e.g. inside a ``config:`` mapping) is
# left alone -- mermaid's caption title is always a top-level key. Value is
# everything after the colon; quotes are stripped separately.
_TITLE_LINE_RE = re.compile(r"\Atitle[ \t]*:[ \t]*(.*?)[ \t]*\Z")


def _extract_mermaid_title(source: str) -> tuple[str | None, str]:
    """Split a mermaid ``title:`` frontmatter field off the diagram *source*.

    Returns ``(title, source_without_title)``. When the source carries a leading
    YAML frontmatter block with a ``title:`` line, the title (dequoted) is
    returned and that line is removed from the source so mermaid does not also
    draw its own in-canvas caption; any other frontmatter keys are preserved, and
    the frontmatter block is dropped entirely when title was its only key. When
    there is no frontmatter or no title, ``(None, source)`` is returned unchanged.
    """
    m = _FRONTMATTER_RE.match(source)
    if not m:
        return None, source

    yaml_body, diagram = m.group(1), m.group(2)
    title: str | None = None
    kept: list[str] = []
    for line in yaml_body.split("\n"):
        tm = _TITLE_LINE_RE.match(line)
        if tm is not None and title is None:
            raw = tm.group(1).strip()
            if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("\"", "'"):
                raw = raw[1:-1]
            raw = raw.strip()
            if raw:
                title = raw
                continue  # drop the title line from the frontmatter
        kept.append(line)

    if title is None:
        return None, source

    remaining = "\n".join(kept).strip()
    if remaining:
        new_source = f"---\n{remaining}\n---\n{diagram}"
    else:
        new_source = diagram
    return title, new_source


def _header_html(title: str) -> str:
    """Build the ``.mermaid-header`` bar for a diagram *title*.

    A ``left | right`` title splits on the first ``|`` into a left-aligned label
    and a right-aligned meta note; a plain title renders as a single left label.
    The title is author-controlled diagram source injected as trusted output
    (post-``nh3.clean``), so each part is HTML-escaped here.
    """
    left, sep, right = title.partition("|")
    left, right = left.strip(), right.strip()
    if sep and left and right:
        return (
            '<div class="mermaid-header">'
            f'<span class="mh-left">{_html.escape(left, quote=False)}</span>'
            f'<span class="mh-right">{_html.escape(right, quote=False)}</span>'
            "</div>"
        )
    # A missing side (a leading or trailing ``|``) collapses to a single label,
    # so a stray pipe never renders an empty span.
    single = left or right
    return (
        '<div class="mermaid-header">'
        f'<span class="mh-left">{_html.escape(single, quote=False)}</span>'
        "</div>"
    )


# ── SVG Rendering ──


# A ``fill``/``stroke`` declaration whose value is a hex colour, carrying
# ``!important``. Matches ``fill:`` / ``stroke:`` but not ``stroke-width`` or
# ``stroke-dasharray`` (the colon does not sit right after ``stroke``), and only
# hex values, so ``transparent`` / ``none`` / ``url(...)`` fills are left alone.
_HEX_COLOUR_IMPORTANT = re.compile(
    r"(?<![\w-])(fill|stroke)(\s*:\s*#[0-9A-Fa-f]{3,8})\s*!\s*important"
)


def _soften_structural_colours(svg: str) -> str:
    """Drop ``!important`` from mermaid's baked hex ``fill``/``stroke`` colours.

    mermaid emits its palette in an id-scoped ``<style>`` block, and pins some
    colours with ``!important`` -- e.g. ``#gd4 .composition{stroke:#333!important}``
    for class-diagram relation markers and ``#gd5 .marker{stroke:#333!important}``
    for ER crow's-feet. An id selector outranks the theme's class-scoped
    ``.mermaid-structural`` overrides, so on a dark card those markers would keep
    mermaid's grey and be near-invisible. Removing ``!important`` from mermaid's
    *hex-coloured* ``fill``/``stroke`` declarations lets the theme's ``!important``
    overrides win regardless of specificity, while ``fill:transparent`` /
    ``fill:none`` keep theirs -- so hollow arrowheads (aggregation, extension, ER)
    stay hollow. Non-colour properties (``stroke-width``, ``stroke-dasharray``)
    are untouched. Applied only to structural diagrams, which the theme fully
    recolours; categorical/other diagrams keep every ``!important`` so their own
    data-carrying palette is preserved.
    """
    return re.sub(
        r"<style>(.*?)</style>",
        lambda m: "<style>" + _HEX_COLOUR_IMPORTANT.sub(r"\1\2", m.group(1)) + "</style>",
        svg,
        flags=re.S,
    )


def _diagram_class(svg: str) -> str:
    """Return the extra wrapper class for *svg*, keyed on its diagram family.

    Reads the SVG root's ``aria-roledescription`` and maps it to
    ``mermaid-structural`` (recoloured to the theme palette) or
    ``mermaid-categorical`` (pie/gantt: own hues, darkened in dark mode). Any
    other or missing role returns ``""`` so the diagram keeps mermaid's own
    colours untouched.
    """
    match = re.search(r'aria-roledescription="([^"]*)"', svg)
    role = match.group(1) if match else ""
    if role in _STRUCTURAL_ROLES:
        return " mermaid-structural"
    if role in _CATEGORICAL_ROLES:
        return " mermaid-categorical"
    return ""


def render_mermaid(source: str, *, dark: bool = False) -> str:
    """Render Mermaid *source* to embed-ready inline HTML.

    On success returns the inline ``<svg>...</svg>`` produced by mermaid.js (with
    its load-bearing ``<style>`` blob intact) wrapped in a
    ``<div class="mermaid-diagram">`` frame themes can style. On ANY render error
    returns a graceful-degrade fragment: the original source re-emitted as a
    fenced code block plus a visible note. This function never raises to the
    caller.

    Args:
        source: The raw Mermaid diagram source (the fenced block body).
        dark: When true, render with the ``dark`` mermaid theme (light text for a
            dark page); otherwise the ``default`` theme. Both yield a transparent
            canvas.

    Returns:
        A trusted HTML fragment ready to embed in the document body.
    """
    theme = _THEME_DARK if dark else _THEME_LIGHT
    # Lift a ``title:`` frontmatter field into a card header, rendering the source
    # without it so mermaid does not also draw its own in-canvas caption. On a
    # render failure the ORIGINAL source (frontmatter intact) is shown so the
    # author sees exactly what they wrote.
    title, render_source = _extract_mermaid_title(source)
    try:
        diagram = mermaidx.render(render_source, theme=theme, config=_MERMAID_CONFIG)
        svg = diagram.svg()
    except Exception as exc:  # noqa: BLE001 - any renderer failure degrades
        return _degrade_fragment(source, exc)

    if "<svg" not in svg:
        return _degrade_fragment(source, RuntimeError("renderer produced no SVG"))

    # Wrap the diagram in a framing div so themes can border/scroll it and it is
    # distinguishable from the inline ``<svg>`` KaTeX draws for radicals. A
    # family class (structural/categorical) lets the theme recolour or darken it.
    # The wrapper is trusted, post-``nh3.clean`` output alongside the SVG it holds.
    cls = _diagram_class(svg)
    if cls == " mermaid-structural":
        # Let the theme's recolour reach mermaid's id-scoped ``!important`` markers.
        svg = _soften_structural_colours(svg)
    header = _header_html(title) if title else ""
    return f'<div class="mermaid-diagram{cls}">{header}{svg}</div>'


def _degrade_fragment(source: str, error: BaseException) -> str:
    """Build the graceful-degrade fragment for a diagram that failed to render.

    The original *source* is HTML-escaped and re-emitted as a fenced code block
    so the document stays valid and the author can see what did not render. The
    fragment is injected as trusted output (post-``nh3.clean``), so it escapes
    the source itself rather than relying on the sanitiser.
    """
    escaped = _html.escape(source, quote=False)
    reason = _html.escape(str(error), quote=False)
    return (
        '<div class="mermaid-error">\n'
        '<p class="mermaid-error-note">Mermaid diagram could not be rendered.</p>\n'
        f'<pre><code class="language-mermaid">{escaped}</code></pre>\n'
        f"<!-- mermaid render error: {reason} -->\n"
        "</div>"
    )


# ── Per-Conversion Placeholder Registry ──

# A superfences ``format`` callback cannot receive per-conversion state (the dark
# flag) or reach back into the pipeline, and its returned SVG would be stripped
# by the main ``nh3.clean`` pass (nh3 drops ``<style>`` element content and would
# reject much of the SVG). So each conversion keeps thread-local state: the dark
# flag plus a registry mapping a collision-proof placeholder id to the rendered
# HTML. The formatter stashes the HTML and returns an empty ``<div>`` anchored by
# that id; the converter swaps each placeholder for its HTML AFTER sanitisation.
#
# Thread-local isolation makes concurrent conversions on different threads safe;
# a fresh nonce per conversion means stale entries from an earlier conversion on
# the same thread can never be mistaken for the current one.

_state = threading.local()


def _ctx() -> threading.local:
    """Return the current thread's conversion context, initialising if needed."""
    if not getattr(_state, "ready", False):
        begin_conversion(dark=False)
    return _state


def begin_conversion(*, dark: bool) -> None:
    """Start a fresh Mermaid rendering context for one document conversion.

    Resets the placeholder registry, records the *dark* flag for the formatter,
    and generates a per-conversion nonce so placeholder ids are unique to this
    conversion. Called once by the converter before markdown conversion runs.
    """
    _state.dark = dark
    _state.registry = {}
    _state.nonce = secrets.token_hex(8)
    _state.counter = 0
    _state.ready = True


def end_conversion() -> None:
    """Clear the current thread's Mermaid context after a conversion completes."""
    _state.dark = False
    _state.registry = {}
    _state.nonce = ""
    _state.counter = 0
    _state.ready = False


# The placeholder is an empty block-level ``<div>`` carrying only the id nonce.
# It starts with a block tag so Python-Markdown does not wrap it in ``<p>`` (a
# ``<pre>``/``<div>`` degrade fragment would be invalid inside ``<p>``), and its
# ``div``/``id`` survive ``nh3.clean``. The id is matched back out by regex, so
# nh3 attribute reordering/normalisation does not matter.
_PLACEHOLDER_ID = "mermaid-ph-{nonce}-{index}"


def _placeholder_html(placeholder_id: str) -> str:
    """Return the empty anchor ``<div>`` emitted in place of a diagram."""
    return f'<div class="mermaid-placeholder" id="{placeholder_id}"></div>'


def format_mermaid_fence(
    source: str,
    language: str,
    class_name: str,
    options: dict,
    md: object,
    **kwargs: object,
) -> str:
    """Superfences ``custom_fences`` ``format`` callback for ```mermaid``` blocks.

    Matches the callback signature invoked by ``pymdownx.superfences``
    (``format(source, language, class_name, options, md, **kwargs)``). Renders
    the diagram with the current conversion's dark flag, stashes the resulting
    HTML in the thread-local registry, and returns an empty placeholder ``<div>``
    that survives sanitisation and is swapped for the HTML by
    :func:`restore_mermaid` after the main ``nh3.clean`` pass.
    """
    ctx = _ctx()
    placeholder_id = _PLACEHOLDER_ID.format(nonce=ctx.nonce, index=ctx.counter)
    ctx.counter += 1
    ctx.registry[placeholder_id] = render_mermaid(source, dark=ctx.dark)
    return _placeholder_html(placeholder_id)


def restore_mermaid(html: str) -> str:
    """Swap Mermaid placeholder ``<div>``s for their rendered HTML.

    Called by the converter AFTER ``nh3.clean`` so the trusted SVG (and its
    ``<style>`` blob) bypasses sanitisation. Each placeholder is located by its
    id, tolerating any attribute reordering nh3 may have applied and any ``<p>``
    the serialiser may have wrapped it in. Returns *html* unchanged when the
    current context registered no diagrams.
    """
    ctx = _ctx()
    if not ctx.registry:
        return html

    for placeholder_id, fragment in ctx.registry.items():
        # Match the placeholder div by its unique id, optionally wrapped in a
        # lone <p>...</p> the raw-HTML serialiser may have added.
        pattern = re.compile(
            r"(?:<p>\s*)?"
            r'<div\b[^>]*\bid="' + re.escape(placeholder_id) + r'"[^>]*>\s*</div>'
            r"(?:\s*</p>)?"
        )
        html = pattern.sub(lambda _m, f=fragment: f, html, count=1)

    return html


# ── Superfences Registration Helper ──


def superfences_config() -> dict:
    """Return the ``custom_fences`` entry registering the ```mermaid``` fence.

    Merge this into the ``pymdownx.superfences`` extension configuration so a
    ```mermaid``` block routes to :func:`format_mermaid_fence` instead of the
    default highlighter.
    """
    return {
        "name": "mermaid",
        "class": "mermaid",
        "format": format_mermaid_fence,
    }
