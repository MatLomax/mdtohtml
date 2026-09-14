# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onefile spec for the mdtohtml CLI binary.

Bundles the self-contained KaTeX assets (``katex/`` -> ``katex``) into the
executable. At runtime the code resolves these from ``sys._MEIPASS`` when
frozen (katex_assets._katex_dir). Theme CSS files are NOT bundled: they ship
only in the release zip, in a ``themes/`` directory placed next to the
executable, which the frozen binary reads at runtime
(converter.default_themes_dir). A user can add or replace a theme by
dropping a ``.css`` file into that directory with no rebuild.
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

# ``__file__`` is not defined when a .spec is exec'd, so derive the project
# root from the current working directory (PyInstaller runs from there).
_ROOT = Path.cwd()

# Python-Markdown and pymdownx load their extensions dynamically by dotted
# string name (e.g. "pymdownx.arithmatex"), so the static analyzer never sees
# these imports. Collect every submodule of both packages as hidden imports so
# all extensions the converter names are present in the frozen binary.
hiddenimports = collect_submodules("markdown") + collect_submodules("pymdownx")

# The JS engine behind both server-side KaTeX and mermaid rendering. quickjs-ng
# exposes its native extension as the top-level module ``_quickjs`` (its .so
# sits at the site-packages root), imported by the ``quickjs`` package; name it
# explicitly since the static analyzer never sees it. mermaidx loads its engine
# and resvg lazily, so collect every submodule.
hiddenimports += ["_quickjs"]
hiddenimports += collect_submodules("mermaidx")

datas = [
    (str(_ROOT / "mdtohtml" / "katex"), "katex"),
    # Third-party license aggregate. The frozen binary carries it internally
    # (at the bundle root) exactly as it carries the KaTeX license files inside
    # katex/, so the bundled dependencies' notices travel with the executable
    # even though the release zip ships only the binary and themes/.
    (str(_ROOT / "THIRD-PARTY-LICENSES"), "."),
]
# mermaidx reads assets/mermaid.js, assets/dom_shim.js and assets/fonts/*.ttf
# relative to its package directory; collect_data_files preserves that layout.
datas += collect_data_files("mermaidx")

# Native extension modules invisible to static analysis: the resvg SVG
# rasteriser (a Rust cdylib) and the quickjs-ng engine.
binaries = collect_dynamic_libs("resvg_py")
binaries += collect_dynamic_libs("quickjs")

# Heavy, unused modules. weasyprint is the deliberately-dropped PDF path;
# tkinter and friends are GUI/scientific stacks the converter never imports.
excludes = [
    "weasyprint",
    "tkinter",
    "PIL",
    "numpy",
    "pytest",
    "_pytest",
    "pydoc",
    "doctest",
    "unittest",
]

a = Analysis(
    ["entry.py"],
    pathex=[str(_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="mdtohtml",
    debug=False,
    bootloader_ignore_signals=False,
    # Strip symbol tables to shrink the binary on Linux/macOS. Never strip on
    # Windows: PyInstaller's strip corrupts the bundled ``python3xx.dll`` and
    # the frozen executable then fails to load the Python DLL at runtime.
    strip=sys.platform != "win32",
    # UPX is not used: PyInstaller disables it on Linux/macOS, and it is left
    # off on Windows to avoid antivirus false positives.
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
