"""Shared fixtures for mdtohtml tests."""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

warnings.filterwarnings("ignore")


@pytest.fixture()
def tmp_themes_dir(tmp_path: Path) -> Path:
    """Create a temporary themes directory with a test CSS file.

    The test theme (``test-theme``) contains section markers matching the
    project convention and a second theme so ``list_themes`` returns >1 entry.
    """
    themes = tmp_path / "themes"
    themes.mkdir()

    test_css = (
        "/* @section: base */\n"
        "body { font-family: sans-serif; color: #333; }\n"
        "\n"
        "/* @section: headings */\n"
        "h1 { font-size: 24px; }\n"
        "h2 { font-size: 20px; }\n"
        "\n"
        "/* @section: paragraph */\n"
        "p { line-height: 1.6; }\n"
        "\n"
        "/* @section: screen */\n"
        "@media screen { body { max-width: 800px; } }\n"
    )
    (themes / "test-theme.css").write_text(test_css, encoding="utf-8")

    (themes / "another.css").write_text(
        "/* @section: base */\nbody { color: red; }\n",
        encoding="utf-8",
    )

    return themes


@pytest.fixture()
def sample_markdown() -> str:
    """A short markdown document with an H1 title."""
    return "# Hello World\n\nThis is a **test** document.\n"


@pytest.fixture()
def sample_markdown_no_title() -> str:
    """Markdown without an H1 heading."""
    return "Some paragraph text without a title.\n"
