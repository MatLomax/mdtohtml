"""Bundled KaTeX ``<head>`` stylesheet for pre-rendered math.

Reads the self-contained KaTeX stylesheet (CSS with fonts inlined as base64
data URIs) from the package's ``katex/`` directory and assembles the ``<head>``
snippet a document needs. Math is typeset at convert time by
``katex_render.render_math``, so the output carries static KaTeX markup and
this snippet ships only the CSS/fonts that style it -- no JavaScript engine and
no init script.
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


@lru_cache(maxsize=1)
def katex_css_head_assets() -> str:
    """Return the ``<head>`` snippet that styles pre-rendered math.

    Bundles only the inlined KaTeX stylesheet (fonts embedded as base64 data
    URIs) -- no engine and no init script -- since math is typeset at convert
    time by ``katex_render.render_math`` and the output already carries static
    KaTeX markup. Cached after first read.
    """
    css = (_katex_dir() / "katex.min.css").read_text(encoding="utf-8")

    # Carry KaTeX's licenses into every document that inlines its assets. The
    # KaTeX code is MIT and its fonts are SIL OFL 1.1; both licenses require
    # their notices to travel with all copies. Full texts ship in the bundled
    # ``katex/`` license files; keep this line in sync with them.
    notice = (
        "<!-- KaTeX code: MIT License, "
        "Copyright (c) 2013-2020 Khan Academy and other contributors. "
        "KaTeX fonts: SIL Open Font License 1.1. "
        "See the bundled katex/ license files | https://katex.org -->"
    )
    return f"{notice}<style>{css}</style>"
