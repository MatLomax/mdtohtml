#!/usr/bin/env python3
"""Regenerate the self-contained KaTeX asset bundle.

Reads a KaTeX ``dist`` directory and writes into ``mdtohtml/katex/``. The
directory defaults to ``node_modules/katex/dist`` (run ``npm install katex``
first) and can be overridden as the first argv, e.g.::

    python scripts/build_katex_assets.py path/to/katex/dist

It writes:

- ``katex.min.css`` with every ``@font-face`` ``src`` rewritten to a single
  base64 ``data:font/woff2;base64,...`` URI (woff2 only; ttf/woff dropped),
  so the stylesheet needs no external font files.
- ``katex.min.js`` and ``auto-render.min.js`` copied verbatim.

Idempotent: re-running overwrites the outputs with the same result.
"""

from __future__ import annotations

import base64
import re
import shutil
import sys
from pathlib import Path

_DEFAULT_DIST = Path("node_modules/katex/dist")
_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "mdtohtml" / "katex"

# Matches a single @font-face { ... } block (minified, no nested braces).
_FONT_FACE_RE = re.compile(r"@font-face\{[^}]*\}")
# Matches the src: ...; declaration inside a font-face block.
_SRC_RE = re.compile(r"src:[^;}]*")
# Matches url(...) format("woff2") pairs, pulling out the woff2 path.
_WOFF2_URL_RE = re.compile(r'url\(([^)]*\.woff2)\)\s*format\("woff2"\)')


def _inline_font_face(block: str, dist: Path) -> str:
    """Rewrite one @font-face block's src to a single base64 woff2 data URI."""

    def _replace_src(src_match: re.Match[str]) -> str:
        src = src_match.group(0)
        woff2 = _WOFF2_URL_RE.search(src)
        if not woff2:
            # No woff2 source found; leave the src untouched.
            return src
        rel = woff2.group(1).strip().strip("'\"")
        font_path = (dist / rel).resolve()
        data = base64.b64encode(font_path.read_bytes()).decode("ascii")
        return f'src:url(data:font/woff2;base64,{data}) format("woff2")'

    return _SRC_RE.sub(_replace_src, block)


def build(dist: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    css = (dist / "katex.min.css").read_text(encoding="utf-8")
    css = _FONT_FACE_RE.sub(lambda m: _inline_font_face(m.group(0), dist), css)
    (output_dir / "katex.min.css").write_text(css, encoding="utf-8")

    shutil.copyfile(dist / "katex.min.js", output_dir / "katex.min.js")
    shutil.copyfile(
        dist / "contrib" / "auto-render.min.js",
        output_dir / "auto-render.min.js",
    )

    # Ship KaTeX's MIT license alongside the vendored assets so the bundle
    # carries its required copyright notice. It lives at the package root
    # (the parent of dist/).
    license_src = dist.parent / "LICENSE"
    if license_src.is_file():
        shutil.copyfile(license_src, output_dir / "LICENSE")
    else:
        print(f"WARNING: KaTeX LICENSE not found at {license_src}; not updated.")

    print(f"Wrote KaTeX bundle to {output_dir}")


def main(argv: list[str]) -> None:
    dist = Path(argv[0]) if argv else _DEFAULT_DIST
    if not dist.is_dir():
        raise SystemExit(f"KaTeX dist directory not found: {dist}")
    build(dist, _OUTPUT_DIR)


if __name__ == "__main__":
    main(sys.argv[1:])
