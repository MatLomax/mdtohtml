"""Server-side KaTeX math rendering via an in-process JavaScript engine.

Pre-renders LaTeX math to static KaTeX HTML markup at convert time using
``katex.renderToString`` inside a QuickJS context, so the emitted document
carries typeset markup (styled by the bundled KaTeX CSS/fonts) and no
JavaScript engine. There is no network access and no DOM: KaTeX runs
DOM-free inside QuickJS.

The bundled ``katex.min.js`` is loaded exactly once into a cached context on
first render and reused across every subsequent expression, since context
construction plus the engine ``eval`` is the dominant one-time cost while a
warm render is sub-millisecond.
"""

from __future__ import annotations

import html as _html
import json

import quickjs

from . import katex_assets

# ── Engine Singleton ──

# The one live QuickJS context with ``katex.min.js`` evaluated into it, built
# lazily by ``_get_context`` and reused for every render. mdtohtml is a
# single-threaded CLI that converts documents sequentially, so a plain cached
# singleton is correct here; no locking is warranted.
_context: quickjs.Context | None = None


def _get_context() -> quickjs.Context:
    """Return the shared QuickJS context, building it on first use.

    Constructs the context and evaluates the bundled ``katex.min.js`` exactly
    once, then hands back the same context on every later call. The bundle is
    resolved through ``katex_assets._katex_dir`` so it loads both from a plain
    package run and from a PyInstaller-frozen binary.
    """
    global _context
    if _context is None:
        ctx = quickjs.Context()
        src = (katex_assets._katex_dir() / "katex.min.js").read_text(
            encoding="utf-8"
        )
        ctx.eval(src)
        _context = ctx
    return _context


# ── Rendering ──


def render_math(expr: str, *, display: bool = False) -> str:
    """Render a LaTeX expression to static KaTeX HTML markup.

    Args:
        expr: Raw LaTeX source (unescaped -- KaTeX consumes LaTeX directly).
        display: When True, render in display mode (block, centered) rather
            than inline mode.

    Returns:
        The KaTeX HTML markup as a real ``str``. The engine is invoked with
        ``throwOnError`` disabled, so a malformed expression yields visible
        ``katex-error`` markup instead of raising. If the engine itself fails
        for any reason, the expression degrades to a visible ``katex-error``
        span carrying the escaped source rather than crashing the document.
    """
    opts = {"displayMode": display, "throwOnError": False}
    # Embed both arguments as JS literals via json.dumps: Python bool/None map
    # to JS true/false/null, and JSON encoding escapes the LaTeX string fully.
    # ``.slice(0)`` flattens the QuickJS rope object that renderToString returns
    # (which the binding cannot otherwise convert) into a real string.
    js = "(katex.renderToString(%s,%s)).slice(0)" % (
        json.dumps(expr),
        json.dumps(opts),
    )
    try:
        return _get_context().eval(js)
    except Exception:
        return _error_markup(expr)


def _error_markup(expr: str) -> str:
    """Return visible error markup for an expression the engine could not run.

    Mirrors KaTeX's own ``katex-error`` styling so an engine-level failure is
    surfaced in the document exactly like a parse error would be, carrying the
    HTML-escaped source so nothing breaks out of the surrounding markup. The
    source is coerced to ``str`` first so this fallback cannot itself raise,
    honouring the guarantee that a single expression never crashes the document.
    """
    safe = _html.escape(str(expr))
    return f'<span class="katex-error" title="Math render error">{safe}</span>'
