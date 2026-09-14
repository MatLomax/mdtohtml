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
- ``katex.min.js`` copied verbatim (the engine mdtohtml runs at convert time
  to pre-render math server-side).
- ``LICENSE`` - KaTeX's MIT license, covering the bundled *code*.
- ``OFL.txt`` - the SIL Open Font License 1.1 plus the fonts' copyright,
  covering the ``KaTeX_*`` woff2 fonts base64-embedded in ``katex.min.css``
  (the fonts are OFL, not MIT, so their license must travel with the bundle).

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

# SIL Open Font License 1.1 text plus the KaTeX fonts' copyright, written to
# ``OFL.txt`` when the KaTeX package does not ship a font-license file of its
# own. This mirrors mdtohtml/katex/OFL.txt so the two never drift.
_OFL_FONT_LICENSE = """Copyright (c) 2009-2010 Design Science, Inc.
Copyright (c) 2014-2018 Khan Academy

This Font Software is licensed under the SIL Open Font License, Version 1.1.
This license is copied below, and is also available with a FAQ at:
https://openfontlicense.org


-----------------------------------------------------------
SIL OPEN FONT LICENSE Version 1.1 - 26 February 2007
-----------------------------------------------------------

PREAMBLE
The goals of the Open Font License (OFL) are to stimulate worldwide
development of collaborative font projects, to support the font creation
efforts of academic and linguistic communities, and to provide a free and
open framework in which fonts may be shared and improved in partnership
with others.

The OFL allows the licensed fonts to be used, studied, modified and
redistributed freely as long as they are not sold by themselves. The
fonts, including any derivative works, can be bundled, embedded,
redistributed and/or sold with any software provided that any reserved
names are not used by derivative works. The fonts and derivatives,
however, cannot be released under any other type of license. The
requirement for fonts to remain under this license does not apply
to any document created using the fonts or their derivatives.

DEFINITIONS
"Font Software" refers to the set of files released by the Copyright
Holder(s) under this license and clearly marked as such. This may
include source files, build scripts and documentation.

"Reserved Font Name" refers to any names specified as such after the
copyright statement(s).

"Original Version" refers to the collection of Font Software components as
distributed by the Copyright Holder(s).

"Modified Version" refers to any derivative made by adding to, deleting,
or substituting -- in part or in whole -- any of the components of the
Original Version, by changing formats or by porting the Font Software to a
new environment.

"Author" refers to any designer, engineer, programmer, technical
writer or other person who contributed to the Font Software.

PERMISSION & CONDITIONS
Permission is hereby granted, free of charge, to any person obtaining
a copy of the Font Software, to use, study, copy, merge, embed, modify,
redistribute, and sell modified and unmodified copies of the Font
Software, subject to the following conditions:

1) Neither the Font Software nor any of its individual components,
in Original or Modified Versions, may be sold by itself.

2) Original or Modified Versions of the Font Software may be bundled,
redistributed and/or sold with any software, provided that each copy
contains the above copyright notice and this license. These can be
included either as stand-alone text files, human-readable headers or
in the appropriate machine-readable metadata fields within text or
binary files as long as those fields can be easily viewed by the user.

3) No Modified Version of the Font Software may use the Reserved Font
Name(s) unless explicit written permission is granted by the corresponding
Copyright Holder. This restriction only applies to the primary font name as
presented to the users.

4) The name(s) of the Copyright Holder(s) or the Author(s) of the Font
Software shall not be used to promote, endorse or advertise any
Modified Version, except to acknowledge the contribution(s) of the
Copyright Holder(s) and the Author(s) or with their explicit written
permission.

5) The Font Software, modified or unmodified, in part or in whole,
must be distributed entirely under this license, and must not be
distributed under any other license. The requirement for fonts to
remain under this license does not apply to any document created
using the Font Software.

TERMINATION
This license becomes null and void if any of the above conditions are
not met.

DISCLAIMER
THE FONT SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO ANY WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT
OF COPYRIGHT, PATENT, TRADEMARK, OR OTHER RIGHT. IN NO EVENT SHALL THE
COPYRIGHT HOLDER BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
INCLUDING ANY GENERAL, SPECIAL, INDIRECT, INCIDENTAL, OR CONSEQUENTIAL
DAMAGES, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF THE USE OR INABILITY TO USE THE FONT SOFTWARE OR FROM
OTHER DEALINGS IN THE FONT SOFTWARE.
"""


def _find_font_license(dist: Path) -> Path | None:
    """Return a font-license file shipped by the KaTeX package, if any.

    The npm package currently ships only its MIT ``LICENSE``; the SIL OFL that
    covers the fonts is not included. Prefer an upstream file if a future
    release adds one (so the two never drift) and fall back to the embedded
    ``_OFL_FONT_LICENSE`` text otherwise.
    """
    pkg = dist.parent
    for candidate in (
        pkg / "OFL.txt",
        pkg / "OFL",
        pkg / "LICENSE-OFL",
        dist / "fonts" / "OFL.txt",
        pkg / "src" / "fonts" / "OFL.txt",
    ):
        if candidate.is_file():
            return candidate
    return None


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

    # Ship KaTeX's MIT license alongside the vendored assets so the bundle
    # carries its required copyright notice. It lives at the package root
    # (the parent of dist/).
    license_src = dist.parent / "LICENSE"
    if license_src.is_file():
        shutil.copyfile(license_src, output_dir / "LICENSE")
    else:
        print(f"WARNING: KaTeX LICENSE not found at {license_src}; not updated.")

    # Ship the SIL Open Font License for the fonts. The KaTeX_* woff2 fonts
    # base64-embedded in katex.min.css are licensed under the SIL OFL 1.1 (not
    # the MIT license that covers the code), so the OFL text and the fonts'
    # copyright must travel with the bundle. The npm package ships no font
    # license file, so copy an upstream one if present and otherwise write the
    # embedded text.
    ofl_src = _find_font_license(dist)
    if ofl_src is not None:
        shutil.copyfile(ofl_src, output_dir / "OFL.txt")
    else:
        (output_dir / "OFL.txt").write_text(_OFL_FONT_LICENSE, encoding="utf-8")

    print(f"Wrote KaTeX bundle to {output_dir}")


def main(argv: list[str]) -> None:
    dist = Path(argv[0]) if argv else _DEFAULT_DIST
    if not dist.is_dir():
        raise SystemExit(f"KaTeX dist directory not found: {dist}")
    build(dist, _OUTPUT_DIR)


if __name__ == "__main__":
    main(sys.argv[1:])
