"""Self-contained Markdown-to-HTML converter with client-side KaTeX."""

from __future__ import annotations

from .converter import convert

__version__ = "0.1.0"

__all__ = ["__version__", "convert"]
