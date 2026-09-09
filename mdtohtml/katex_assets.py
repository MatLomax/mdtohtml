"""Bundled KaTeX assets for client-side math rendering.

Reads the self-contained KaTeX bundle (CSS with fonts inlined as base64
data URIs, the KaTeX engine, and the auto-render extension) from the
package's ``katex/`` directory and assembles the ``<head>`` snippet that
typesets math in the browser on ``DOMContentLoaded``.
"""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path


def _katex_dir() -> Path:
    """Resolve the bundled ``katex/`` asset directory, frozen-aware.

    A PyInstaller-frozen binary reads the assets added via ``--add-data``,
    which land under ``sys._MEIPASS``. A plain Python run reads the
    package-relative ``katex/`` directory.
    """
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "katex"
    return Path(__file__).resolve().parent / "katex"

# Init script: run KaTeX auto-render over the whole body once the DOM is ready,
# matching the ``\(...\)`` inline and ``\[...\]`` display delimiters that
# ``_math_to_delimiters`` emits.
_INIT_JS = (
    "document.addEventListener(\"DOMContentLoaded\",function(){"
    "renderMathInElement(document.body,{delimiters:["
    '{left:"\\\\(",right:"\\\\)",display:false},'
    '{left:"\\\\[",right:"\\\\]",display:true}'
    "]});});"
)


@lru_cache(maxsize=1)
def katex_head_assets() -> str:
    """Return the ``<head>`` snippet that renders math client-side.

    Bundles the inlined KaTeX stylesheet, the KaTeX engine, the auto-render
    extension, and an init script. Cached after first read.
    """
    katex_dir = _katex_dir()
    css = (katex_dir / "katex.min.css").read_text(encoding="utf-8")
    katex_js = (katex_dir / "katex.min.js").read_text(encoding="utf-8")
    autorender_js = (katex_dir / "auto-render.min.js").read_text(encoding="utf-8")

    # Carry KaTeX's copyright notice into every document that inlines its code
    # (MIT requires the notice to travel with all copies). The full license text
    # ships in the bundled ``katex/LICENSE``; keep this line in sync with it.
    notice = (
        "<!-- KaTeX | MIT License | "
        "Copyright (c) 2013-2020 Khan Academy and other contributors | "
        "https://katex.org -->"
    )
    return (
        f"{notice}"
        f"<style>{css}</style>"
        f"<script>{katex_js}</script>"
        f"<script>{autorender_js}</script>"
        f"<script>{_INIT_JS}</script>"
    )
