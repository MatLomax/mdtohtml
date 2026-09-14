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


# ── SVG Rendering ──


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
    try:
        diagram = mermaidx.render(source, theme=theme, config=_MERMAID_CONFIG)
        svg = diagram.svg()
    except Exception as exc:  # noqa: BLE001 - any renderer failure degrades
        return _degrade_fragment(source, exc)

    if "<svg" not in svg:
        return _degrade_fragment(source, RuntimeError("renderer produced no SVG"))

    # Wrap the diagram in a framing div so themes can border/scroll it and it is
    # distinguishable from the inline ``<svg>`` KaTeX draws for radicals. The
    # wrapper is trusted, post-``nh3.clean`` output alongside the SVG it holds.
    return f'<div class="mermaid-diagram">{svg}</div>'


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
