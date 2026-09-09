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

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

# ``__file__`` is not defined when a .spec is exec'd, so derive the project
# root from the current working directory (PyInstaller runs from there).
_ROOT = Path.cwd()

# Python-Markdown and pymdownx load their extensions dynamically by dotted
# string name (e.g. "pymdownx.arithmatex"), so the static analyzer never sees
# these imports. Collect every submodule of both packages as hidden imports so
# all extensions the converter names are present in the frozen binary.
hiddenimports = collect_submodules("markdown") + collect_submodules("pymdownx")

datas = [
    (str(_ROOT / "mdtohtml" / "katex"), "katex"),
]

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
    binaries=[],
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
    # Strip symbol tables to shrink the binary (effective on Linux/macOS).
    strip=True,
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
