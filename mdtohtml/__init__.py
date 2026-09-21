"""Self-contained Markdown-to-HTML converter with client-side KaTeX."""

from __future__ import annotations

from .converter import convert

# The version comes from the git tag via setuptools_scm, written to the
# generated _version.py at build time. Prefer that; fall back to the installed
# package metadata (a wheel/sdist install with no _version.py); fall back last
# to a sentinel for a raw source checkout that was never built.
try:
    from ._version import __version__
except ImportError:  # pragma: no cover - exercised only in unbuilt trees
    from importlib.metadata import PackageNotFoundError, version

    try:
        __version__ = version("mdtohtml")
    except PackageNotFoundError:
        __version__ = "0.0.0+unknown"

__all__ = ["__version__", "convert"]
