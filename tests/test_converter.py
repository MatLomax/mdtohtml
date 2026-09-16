"""Tests for the mdtohtml converter module."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from mdtohtml.converter import (
    TOC_JS,
    _build_toc_nav,
    _extract_headings,
    _style_code_headers,
    _wrap_tables,
    convert,
    extract_title,
    list_themes,
    load_theme_css,
    md_to_html,
    preprocess_captions,
    preprocess_chips,
    preprocess_footer,
    preprocess_keyed_tables,
    preprocess_obsidian_callouts,
    preprocess_section_kickers,
    preprocess_wikilinks,
    render_html,
)


# ═══════════════════════════════════════════════════════════════════════
# extract_title
# ═══════════════════════════════════════════════════════════════════════


class TestExtractTitle:
    def test_extract_title_with_h1(self) -> None:
        md = "# My Document\n\nSome body text."
        assert extract_title(md) == "My Document"

    def test_extract_title_without_h1(self) -> None:
        md = "## Sub-heading only\n\nBody text."
        assert extract_title(md) == "Untitled"

    def test_extract_title_empty(self) -> None:
        assert extract_title("") == "Untitled"

    def test_extract_title_picks_first_h1(self) -> None:
        md = "# First\n\n# Second\n"
        assert extract_title(md) == "First"


# ═══════════════════════════════════════════════════════════════════════
# md_to_html
# ═══════════════════════════════════════════════════════════════════════


class TestMdToHtml:
    def test_md_to_html_basic(self) -> None:
        html = md_to_html("Hello world")
        assert "<p>" in html
        assert "Hello world" in html

    def test_md_to_html_headings(self) -> None:
        html = md_to_html("# Big\n\n## Small\n")
        assert "<h1" in html
        assert "<h2" in html
        assert "Big" in html
        assert "Small" in html

    def test_md_to_html_unordered_list(self) -> None:
        html = md_to_html("- one\n- two\n")
        assert "<ul>" in html
        assert "<li>" in html
        assert "one" in html

    def test_md_to_html_ordered_list(self) -> None:
        html = md_to_html("1. first\n2. second\n")
        assert "<ol>" in html
        assert "first" in html

    def test_md_to_html_tables(self) -> None:
        table_md = "| A | B |\n|---|---|\n| 1 | 2 |\n"
        html = md_to_html(table_md)
        assert "<table" in html
        assert "<th" in html or "<td" in html

    def test_md_to_html_strikethrough(self) -> None:
        html = md_to_html("~~deleted~~")
        assert "<del>" in html
        assert "deleted" in html

    def test_md_to_html_highlight(self) -> None:
        html = md_to_html("==highlighted==")
        assert "<mark>" in html
        assert "highlighted" in html

    def test_md_to_html_task_list(self) -> None:
        md = "- [ ] unchecked\n- [x] checked\n"
        html = md_to_html(md)
        assert "<input" in html
        assert "unchecked" in html
        assert "checked" in html

    def test_md_to_html_footnotes(self) -> None:
        md = "Text with note[^1].\n\n[^1]: The footnote.\n"
        html = md_to_html(md)
        assert "fn" in html.lower() or "footnote" in html.lower()

    def test_md_to_html_important_callout(self) -> None:
        html = md_to_html("> [!important] Read First\n> High-priority details.\n")
        assert "admonition important" in html
        assert "Read First" in html
        assert "High-priority details." in html


# ═══════════════════════════════════════════════════════════════════════
# preprocess_obsidian_callouts
# ═══════════════════════════════════════════════════════════════════════


class TestPreprocessObsidianCallouts:
    def test_preprocess_obsidian_callouts_basic(self) -> None:
        md = "> [!note]\n> Some content.\n"
        result = preprocess_obsidian_callouts(md)
        assert "!!! note" in result
        assert "Some content." in result

    def test_preprocess_obsidian_callouts_with_title(self) -> None:
        md = "> [!warning] Watch Out\n> Be careful.\n"
        result = preprocess_obsidian_callouts(md)
        assert '!!! warning "Watch Out"' in result
        assert "Be careful." in result

    def test_preprocess_obsidian_callouts_multiline(self) -> None:
        md = "> [!tip] Helpful\n> Line one.\n> Line two.\n"
        result = preprocess_obsidian_callouts(md)
        assert '!!! tip "Helpful"' in result
        assert "Line one." in result
        assert "Line two." in result

    def test_non_callout_blockquote_unchanged(self) -> None:
        md = "> Normal blockquote\n"
        result = preprocess_obsidian_callouts(md)
        assert result.strip() == md.strip()

    def test_ignore_single_callout_type(self) -> None:
        md = "> [!info] Details\n> Some info content.\n"
        result = preprocess_obsidian_callouts(md, ignore_callouts={"info"})
        assert "info" not in result
        assert "Some info content." not in result

    def test_ignore_multiple_callout_types(self) -> None:
        md = (
            "> [!info] I1\n> Info.\n\n"
            "> [!tip] T1\n> Tip.\n\n"
            "> [!warning] W1\n> Warning.\n"
        )
        result = preprocess_obsidian_callouts(md, ignore_callouts={"info", "tip"})
        assert "Info." not in result
        assert "Tip." not in result
        assert '!!! warning "W1"' in result
        assert "Warning." in result

    def test_ignore_none_converts_all(self) -> None:
        md = "> [!info] Details\n> Content.\n"
        result = preprocess_obsidian_callouts(md, ignore_callouts=None)
        assert '!!! info "Details"' in result
        assert "Content." in result

    def test_ignore_case_insensitive_in_source(self) -> None:
        md = "> [!INFO] Details\n> Content.\n"
        result = preprocess_obsidian_callouts(md, ignore_callouts={"info"})
        assert "Content." not in result


class TestMdToHtmlIgnoreCallouts:
    def test_ignore_removes_callout_from_html(self) -> None:
        md = "# Hello\n\n> [!info] Details\n> Info content.\n\nParagraph.\n"
        html = md_to_html(md, ignore_callouts={"info"})
        assert "Info content." not in html
        assert "Paragraph." in html

    def test_ignore_preserves_other_callout_in_html(self) -> None:
        md = (
            "> [!info] Details\n> Info content.\n\n"
            "> [!warning] Watch Out\n> Warning content.\n"
        )
        html = md_to_html(md, ignore_callouts={"info"})
        assert "Info content." not in html
        assert "Warning content." in html
        assert "admonition warning" in html


# ═══════════════════════════════════════════════════════════════════════
# preprocess_wikilinks
# ═══════════════════════════════════════════════════════════════════════


class TestPreprocessWikilinks:
    def test_basic_wikilink(self) -> None:
        result = preprocess_wikilinks("See [[Some Page]] for details.")
        assert result == "See [Some Page](Some Page.html) for details."

    def test_wikilink_with_display_text(self) -> None:
        result = preprocess_wikilinks("See [[Some Page|click here]] now.")
        assert result == "See [click here](Some Page.html) now."

    def test_wikilink_with_heading(self) -> None:
        result = preprocess_wikilinks("See [[Some Page#section]].")
        assert result == "See [Some Page > section](Some Page.html#section)."

    def test_wikilink_with_heading_and_display(self) -> None:
        result = preprocess_wikilinks("[[Page#heading|custom text]]")
        assert result == "[custom text](Page.html#heading)"

    def test_same_document_heading(self) -> None:
        result = preprocess_wikilinks("See [[#my heading]].")
        assert result == "See [my heading](#my heading)."

    def test_wikilink_in_folder(self) -> None:
        result = preprocess_wikilinks("[[folder/Page]]")
        assert result == "[folder/Page](folder/Page.html)"

    def test_multiple_wikilinks(self) -> None:
        md = "See [[Page A]] and [[Page B|B link]]."
        result = preprocess_wikilinks(md)
        assert "[Page A](Page A.html)" in result
        assert "[B link](Page B.html)" in result

    def test_wikilink_in_fenced_code_unchanged(self) -> None:
        md = "```\n[[Some Page]]\n```"
        result = preprocess_wikilinks(md)
        assert "[[Some Page]]" in result

    def test_wikilink_in_inline_code_unchanged(self) -> None:
        md = "Use `[[Some Page]]` syntax."
        result = preprocess_wikilinks(md)
        assert "[[Some Page]]" in result

    def test_no_wikilinks_unchanged(self) -> None:
        md = "Just a normal paragraph."
        result = preprocess_wikilinks(md)
        assert result == md

    def test_empty_string(self) -> None:
        assert preprocess_wikilinks("") == ""


class TestMdToHtmlWikilinks:
    def test_wikilink_becomes_html_link(self) -> None:
        html = md_to_html("See [[Some Page]] for details.")
        assert "<a" in html
        assert "Some Page" in html
        assert "Some Page.html" in html

    def test_wikilink_display_text_preserved(self) -> None:
        html = md_to_html("[[Some Page|click here]]")
        assert "click here" in html
        assert "<a" in html


# ═══════════════════════════════════════════════════════════════════════
# load_theme_css / list_themes
# ═══════════════════════════════════════════════════════════════════════


class TestThemeLoading:
    def test_load_theme_css_valid(self, tmp_themes_dir: Path) -> None:
        css = load_theme_css("test-theme", tmp_themes_dir)
        assert "body" in css
        assert "font-family" in css

    def test_load_theme_css_invalid(self, tmp_themes_dir: Path) -> None:
        with pytest.raises(ValueError, match="not found"):
            load_theme_css("nonexistent", tmp_themes_dir)

    def test_list_themes(self, tmp_themes_dir: Path) -> None:
        themes = list_themes(tmp_themes_dir)
        assert isinstance(themes, list)
        assert themes == sorted(themes), "themes should be sorted"
        assert "test-theme" in themes
        assert "another" in themes

    def test_list_themes_empty_dir(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty-themes"
        empty.mkdir()
        assert list_themes(empty) == []

    def test_list_themes_missing_dir(self, tmp_path: Path) -> None:
        missing = tmp_path / "nope"
        assert list_themes(missing) == []

    def test_shipped_themes_available(self) -> None:
        """The default themes packaged with the project are discoverable."""
        themes = list_themes()
        assert "default" in themes
        assert "dark" in themes
        assert "print" in themes


# ═══════════════════════════════════════════════════════════════════════
# render_html
# ═══════════════════════════════════════════════════════════════════════


class TestRendering:
    _CSS = "body { font-family: sans-serif; }"
    _MD = "# Title\n\nParagraph text.\n"

    def test_render_html(self) -> None:
        html = render_html(self._MD, self._CSS)
        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert "</html>" in html
        assert "Title" in html

    def test_render_html_contains_css(self) -> None:
        html = render_html(self._MD, self._CSS)
        assert "<style>" in html
        assert "font-family" in html

    def test_render_html_title_override(self) -> None:
        html = render_html(self._MD, self._CSS, title="Custom")
        assert "<title>Custom</title>" in html


# ═══════════════════════════════════════════════════════════════════════
# convert (high-level HTML API)
# ═══════════════════════════════════════════════════════════════════════


class TestConvert:
    def test_convert_html(self, tmp_themes_dir: Path) -> None:
        content = convert("# Doc\n\nBody.\n", "test-theme", tmp_themes_dir)
        assert isinstance(content, str)
        assert "<!DOCTYPE html>" in content
        assert "Doc" in content

    def test_convert_invalid_theme(self, tmp_themes_dir: Path) -> None:
        with pytest.raises(ValueError, match="not found"):
            convert("# Doc\n", "nope", tmp_themes_dir)

    def test_convert_empty_markdown(self, tmp_themes_dir: Path) -> None:
        with pytest.raises(ValueError, match="empty"):
            convert("", "test-theme", tmp_themes_dir)

    def test_convert_whitespace_only(self, tmp_themes_dir: Path) -> None:
        with pytest.raises(ValueError, match="empty"):
            convert("   \n\n  ", "test-theme", tmp_themes_dir)


# ═══════════════════════════════════════════════════════════════════════
# Math handling (server-side pre-rendered KaTeX)
# ═══════════════════════════════════════════════════════════════════════


class TestMath:
    """Math is typeset to static KaTeX markup at convert time.

    The output ships KaTeX CSS/fonts but no JavaScript engine, and a math-free
    document carries none of the KaTeX bytes.
    """

    def test_math_free_has_no_katex_assets(self, tmp_themes_dir: Path) -> None:
        content = convert("# Plain\n\nNo math here at all.\n", "test-theme",
                          tmp_themes_dir)
        # No KaTeX markup, no inlined KaTeX fonts, and no math-rendering script.
        assert 'class="katex' not in content
        assert "data:font/woff2;base64" not in content
        assert "renderMathInElement" not in content

    def test_math_pre_renders_to_static_markup(self, tmp_themes_dir: Path) -> None:
        md = "Euler: $e^{i\\pi} + 1 = 0$\n\n$$x = \\frac{-b}{2a}$$\n"
        content = convert(md, "test-theme", tmp_themes_dir)
        # The KaTeX stylesheet (with base64 fonts) is injected, and the math is
        # already typeset in the markup: an inline root and a display block.
        assert "data:font/woff2;base64" in content
        assert 'class="katex"' in content
        assert "katex-display" in content

    def test_math_ships_no_js_engine(self, tmp_themes_dir: Path) -> None:
        # A math document with no TOC carries zero script: math is pre-rendered,
        # so neither the KaTeX engine nor an auto-render init is in the output.
        content = convert("Inline $x^2$ only.\n", "test-theme", tmp_themes_dir)
        assert "<script" not in content
        assert "renderMathInElement" not in content

    def test_math_error_degrades_visibly(self) -> None:
        # A malformed expression yields visible katex-error markup rather than
        # raising and aborting the whole document.
        html = md_to_html("Broken $\\frac{$ expression.")
        assert "katex-error" in html

    def test_math_handles_html_specials(self, tmp_themes_dir: Path) -> None:
        # ``<`` / ``>`` inside math are LaTeX relations; the expression renders
        # to KaTeX markup without leaking a raw angle bracket into the document.
        content = convert("Compare $a < b > c$.", "test-theme", tmp_themes_dir)
        assert 'class="katex"' in content

    def test_katex_class_mention_does_not_inject(self, tmp_themes_dir: Path) -> None:
        # A math-free doc that merely names the KaTeX classes -- in prose and in
        # inline code -- must ship zero KaTeX bytes. The bare class name appears
        # in the body as text/`<code>` but never as KaTeX's own ``class="katex"``
        # root, so the stylesheet injection must not trigger.
        md = "Style the `katex-inline` and katex-display classes in your CSS.\n"
        content = convert(md, "test-theme", tmp_themes_dir)
        assert "katex-inline" in content  # the word is legitimately present
        assert 'class="katex"' not in content
        assert "data:font/woff2;base64" not in content

    def test_inline_style_cannot_pin_to_viewport(self) -> None:
        # Allowing inline ``style`` for KaTeX must not let raw HTML in the
        # source pin an element to the viewport for a clickjacking overlay.
        # ``position`` is not an allowed style property, so every spelling --
        # plain, escaped value, and escaped property name -- is stripped, while
        # the layout properties KaTeX needs (here ``top``) may remain inert.
        for payload in (
            '<span style="position:fixed;top:0;width:100%;height:100%">x</span>',
            r'<span style="position:\66 ixed;top:0;width:100%">x</span>',
            r'<span style="po\73 ition:fixed">x</span>',
            '<span style="position:sticky;top:0">x</span>',
            '<span style="position:absolute;top:0;width:100%;height:100%">x</span>',
        ):
            out = md_to_html(payload)
            assert "position" not in out
            assert "fixed" not in out.lower()
            assert "sticky" not in out.lower()
            assert "absolute" not in out.lower()

    def test_math_keeps_operator_vertical_offset(self) -> None:
        # Dropping the redundant inline ``position`` must not cost KaTeX its
        # large-operator vertical offset: the ``top`` declaration still ships
        # and the ``.op-symbol`` class positions the element via the stylesheet.
        html = md_to_html("$\\sum_{i=1}^{n} i$")
        assert 'class="katex"' in html
        assert "top:" in html


# ═══════════════════════════════════════════════════════════════════════
# Mermaid diagrams (server-side pre-rendered SVG)
# ═══════════════════════════════════════════════════════════════════════


class TestMermaid:
    """```mermaid``` fences pre-render to inline SVG that survives sanitisation."""

    def test_fence_renders_to_inline_svg(self) -> None:
        html = md_to_html("```mermaid\ngraph TD; A-->B; B-->C\n```\n")
        assert "<svg" in html
        # The placeholder used to bypass the sanitiser is fully resolved.
        assert "mermaid-placeholder" not in html

    def test_rendered_svg_carries_no_script(self) -> None:
        html = md_to_html("```mermaid\ngraph TD; A-->B\n```\n")
        assert "<script" not in html
        assert "foreignobject" not in html.lower()

    def test_style_blob_survives_sanitisation(self) -> None:
        # The diagram's load-bearing <style> block is trusted renderer output
        # injected after nh3, so it reaches the document intact.
        html = md_to_html("```mermaid\ngraph TD; A-->B\n```\n")
        assert "<style" in html

    def test_multiple_diagrams_in_one_document(self) -> None:
        md = (
            "```mermaid\ngraph TD; A-->B\n```\n\n"
            "```mermaid\nsequenceDiagram\n    Alice->>John: Hi\n```\n"
        )
        html = md_to_html(md)
        assert html.count("<svg") == 2
        assert "mermaid-placeholder" not in html

    def test_bad_diagram_degrades_without_crashing(self) -> None:
        html = md_to_html("```mermaid\n$$ not a valid diagram !!!\n```\n")
        assert "mermaid-error" in html
        assert "<svg" not in html

    def test_diagram_free_doc_has_no_mermaid_artifacts(self) -> None:
        html = md_to_html("# Title\n\nJust prose, no diagrams.\n")
        assert "mermaid" not in html
        assert "<svg" not in html

    def test_dark_theme_differs_from_default(self) -> None:
        src = "```mermaid\ngraph TD; A-->B\n```\n"
        assert md_to_html(src, dark=True) != md_to_html(src, dark=False)

    def test_code_fence_of_other_language_is_not_rendered(self) -> None:
        # A plain code fence must stay a code block, not route to the renderer.
        html = md_to_html("```python\nprint('graph TD; A-->B')\n```\n")
        assert "<svg" not in html
        assert "<code" in html

    _CLASSDEF_DOC = (
        "# Doc\n\n"
        "```mermaid\n"
        "graph TD\n"
        "  A[Start] --> B[Good]\n"
        "  classDef good fill:#dcecda,stroke:#2e7d32,color:#1b5e20\n"
        "  class B good\n"
        "```\n"
    )

    def test_report_theme_retunes_classdef_for_dark(self) -> None:
        # The auto light/dark report theme routes classDef colours through
        # per-diagram variables with a dark-mode media query.
        out = convert(self._CLASSDEF_DOC, "report")
        assert "fill:var(--m" in out
        assert "@media (prefers-color-scheme:dark)" in out

    def test_default_theme_leaves_classdef_literal(self) -> None:
        # A single-scheme theme must not retune -- dark tiles on a light page
        # would be wrong -- so the author colour stays a literal hex.
        out = convert(self._CLASSDEF_DOC, "default")
        assert "fill:var(--m" not in out
        assert "#dcecda" in out


# ═══════════════════════════════════════════════════════════════════════
# Table of Contents
# ═══════════════════════════════════════════════════════════════════════


class TestToc:
    """Tests for the table-of-contents feature."""

    # ── Heading ID generation ──

    def test_heading_ids_generated(self) -> None:
        html = md_to_html("# Hello World\n\n## Sub Heading\n")
        assert 'id="hello-world"' in html
        assert 'id="sub-heading"' in html

    def test_heading_ids_survive_sanitisation(self) -> None:
        html = md_to_html("# Test Heading\n")
        assert '<h1 id="test-heading">Test Heading</h1>' in html

    # ── Heading extraction ──

    def test_extract_headings_basic(self) -> None:
        body = '<h1 id="intro">Introduction</h1><h2 id="setup">Setup</h2>'
        headings = _extract_headings(body)
        assert headings == [(1, "intro", "Introduction"), (2, "setup", "Setup")]

    def test_extract_headings_max_depth(self) -> None:
        body = (
            '<h1 id="a">A</h1>'
            '<h2 id="b">B</h2>'
            '<h3 id="c">C</h3>'
            '<h4 id="d">D</h4>'
        )
        headings = _extract_headings(body, max_depth=2)
        assert len(headings) == 2
        assert headings[0] == (1, "a", "A")
        assert headings[1] == (2, "b", "B")

    def test_extract_headings_no_id(self) -> None:
        body = '<h1>No ID</h1><h2 id="has-id">Has ID</h2>'
        headings = _extract_headings(body)
        assert len(headings) == 1
        assert headings[0] == (2, "has-id", "Has ID")

    def test_extract_headings_strips_inner_tags(self) -> None:
        body = '<h2 id="api"><code>API</code> Reference</h2>'
        headings = _extract_headings(body)
        assert headings == [(2, "api", "API Reference")]

    # ── TOC nav building ──

    def test_build_toc_nav_basic(self) -> None:
        body = '<h1 id="intro">Intro</h1><h2 id="setup">Setup</h2>'
        nav = _build_toc_nav(body)
        assert '<nav id="toc"' in nav
        assert 'href="#intro"' in nav
        assert 'href="#setup"' in nav
        assert "Intro" in nav
        assert "Setup" in nav
        assert "toc-title" in nav

    def test_build_toc_nav_empty(self) -> None:
        assert _build_toc_nav("<p>No headings here</p>") == ""

    def test_build_toc_nav_nesting(self) -> None:
        body = (
            '<h1 id="a">A</h1>'
            '<h2 id="b">B</h2>'
            '<h3 id="c">C</h3>'
            '<h1 id="d">D</h1>'
        )
        nav = _build_toc_nav(body)
        # Count open-tag prefixes so the outer ``<ul id="toc-list">`` is included.
        assert nav.count("<ul") >= 3
        assert nav.count("</ul>") >= 3

    # ── render_html with toc ──

    def test_render_html_toc(self, tmp_themes_dir: Path) -> None:
        css = (tmp_themes_dir / "test-theme.css").read_text()
        md = "# Heading One\n\n## Heading Two\n\nParagraph.\n"
        result = render_html(md, css, toc=True)
        assert '<nav id="toc"' in result
        assert "<main>" in result
        assert "<script>" in result
        assert 'href="#heading-one"' in result
        assert 'href="#heading-two"' in result

    def test_render_html_no_toc_by_default(self, tmp_themes_dir: Path) -> None:
        css = (tmp_themes_dir / "test-theme.css").read_text()
        md = "# Heading One\n\nParagraph.\n"
        result = render_html(md, css)
        assert "<nav" not in result
        assert "<main>" not in result

    def test_render_html_toc_no_headings(self, tmp_themes_dir: Path) -> None:
        css = (tmp_themes_dir / "test-theme.css").read_text()
        md = "Just a paragraph.\n"
        result = render_html(md, css, toc=True)
        assert "<nav" not in result
        assert "<main>" not in result

    def test_convert_html_toc(self, tmp_themes_dir: Path) -> None:
        content = convert(
            "# Heading\n\nText.\n", "test-theme", tmp_themes_dir, toc=True,
        )
        assert '<nav id="toc"' in content

    # ── Scrollspy safety ──

    def test_toc_scrollspy_never_scrolls_the_document(self) -> None:
        """``scrollIntoView`` walks every scrollable ancestor, the document
        included. Moving ``toc.scrollTop`` is the only form that cannot."""
        assert "scrollIntoView" not in TOC_JS
        assert "toc.scrollTop" in TOC_JS

    def test_toc_scrollspy_is_offsetparent_immune(self) -> None:
        """Active-heading detection uses viewport-relative rects, not
        ``offsetTop`` (which a theme's positioned layout would skew)."""
        assert "getBoundingClientRect" in TOC_JS
        assert "offsetTop" not in TOC_JS

    # ── Collapse/expand toggle ──

    def test_build_toc_nav_has_collapse_toggle(self) -> None:
        nav = _build_toc_nav('<h1 id="a">A</h1><h2 id="b">B</h2>')
        assert 'class="toc-head"' in nav
        assert 'class="toc-toggle"' in nav
        assert 'type="button"' in nav
        # Default (each load) is expanded.
        assert 'aria-expanded="true"' in nav
        # The disclosure button names the region it controls, which carries the id.
        assert 'aria-controls="toc-list"' in nav
        assert '<ul id="toc-list">' in nav

    def test_toc_js_wires_the_collapse_toggle(self) -> None:
        assert "toc-toggle" in TOC_JS
        assert "classList.toggle('collapsed')" in TOC_JS
        # The scrollspy IIFE is still present alongside the toggle.
        assert "getBoundingClientRect" in TOC_JS

    def test_toc_scrollspy_pins_last_entry_at_page_bottom(self) -> None:
        """A short final section can't reach the trigger line, so the last
        entry is pinned once the page is fully scrolled."""
        assert "innerHeight" in TOC_JS
        assert "scrollHeight" in TOC_JS

    def test_toc_scrollspy_marks_active_for_assistive_tech(self) -> None:
        """The active link is exposed via ``aria-current``, not class only."""
        assert "aria-current" in TOC_JS

    def test_toc_scrollspy_recomputes_on_resize(self) -> None:
        assert "'resize'" in TOC_JS

    def test_toc_scrollspy_active_selection_executes_correctly(
        self, tmp_path: Path,
    ) -> None:
        """Run the real TOC_JS against a stubbed DOM (via node) and assert the
        active entry for the layouts the string checks above cannot see:
        first-entry on load, mid-scroll advance, last-entry pinned at the
        bottom of a scrollable page, and first-entry on a short page that
        already fits the viewport (the bottom-pin must not fire there)."""
        import json
        import shutil
        import subprocess

        node = shutil.which("node")
        if node is None:
            pytest.skip("node not available")

        (tmp_path / "toc.js").write_text(TOC_JS, encoding="utf-8")
        harness = r"""
const fs=require('fs');
const js=fs.readFileSync(process.argv[2],'utf8');
function link(){const o={cls:new Set(),attrs:{}};o.classList={add(c){o.cls.add(c);},remove(c){o.cls.delete(c);}};o.setAttribute=(k,v)=>{o.attrs[k]=v;};o.removeAttribute=(k)=>{delete o.attrs[k];};o.getBoundingClientRect=()=>({top:0,bottom:10});return o;}
let headTops=[0,0,0],scrollHeight=2000,innerHeight=500,scrollY=0;
const links=[link(),link(),link()];
const headings=[0,1,2].map(i=>({getBoundingClientRect(){return {top:headTops[i]};}}));
const anchors=links.map((l,i)=>({getAttribute(){return '#h'+i;},classList:l.classList,setAttribute:l.setAttribute,removeAttribute:l.removeAttribute,getBoundingClientRect(){return {top:0,bottom:10};}}));
const toggleBtn={addEventListener(){},setAttribute(){}};
const toc={scrollHeight:10,clientHeight:100,scrollTop:0,querySelectorAll:()=>anchors,querySelector:()=>toggleBtn,classList:{toggle(){return true;}},getBoundingClientRect(){return {top:0,bottom:100};}};
let sh=null;
global.requestAnimationFrame=fn=>fn();
global.document={getElementById(id){if(id==='toc')return toc;const m=/^h(\d)$/.exec(id);return m?headings[+m[1]]:null;},documentElement:{get scrollHeight(){return scrollHeight;}}};
global.window={get innerHeight(){return innerHeight;},get scrollY(){return scrollY;},addEventListener(ev,fn){if(ev==='scroll')sh=fn;},requestAnimationFrame:global.requestAnimationFrame};
const run=()=>sh&&sh();
const active=()=>{for(let i=0;i<links.length;i++)if(links[i].cls.has('active'))return i;return -1;};
const out={};
headTops=[100,600,1200];scrollHeight=2000;innerHeight=500;scrollY=0;eval(js);out.longTop=active();
headTops=[-400,-5,600];run();out.mid=active();
headTops=[-900,-800,300];scrollY=1500;run();out.bottom=active();
headTops=[5,40,90];scrollHeight=400;innerHeight=800;scrollY=0;run();out.shortFits=active();
process.stdout.write(JSON.stringify(out));
"""
        (tmp_path / "harness.js").write_text(harness, encoding="utf-8")
        proc = subprocess.run(
            [node, str(tmp_path / "harness.js"), str(tmp_path / "toc.js")],
            capture_output=True, text=True, timeout=30,
        )
        assert proc.returncode == 0, proc.stderr
        result = json.loads(proc.stdout)
        assert result["longTop"] == 0     # first entry lit on load
        assert result["mid"] == 1         # advances as headings pass the line
        assert result["bottom"] == 2      # last entry pinned at page bottom
        assert result["shortFits"] == 0   # short page: first, not last

    def test_toc_js_toggle_collapses_and_expands(self, tmp_path: Path) -> None:
        """Run the real toggle IIFE (via node): clicking flips the 'collapsed'
        class and the button's aria-expanded/aria-label, and clicking again
        restores it -- with no persistence call."""
        import json
        import shutil
        import subprocess

        node = shutil.which("node")
        if node is None:
            pytest.skip("node not available")

        assert "localStorage" not in TOC_JS  # state is intentionally not persisted

        (tmp_path / "toc.js").write_text(TOC_JS, encoding="utf-8")
        harness = r"""
const fs=require('fs');
const js=fs.readFileSync(process.argv[2],'utf8');
let clickHandler=null;
const cls=new Set();
const btn={attrs:{},addEventListener(ev,fn){if(ev==='click')clickHandler=fn;},setAttribute(k,v){btn.attrs[k]=v;}};
const toc={classList:{toggle(c){if(cls.has(c)){cls.delete(c);return false;}cls.add(c);return true;}},querySelector:()=>btn,querySelectorAll:()=>[],getBoundingClientRect(){return{top:0,bottom:0};},scrollHeight:0,clientHeight:0};
global.requestAnimationFrame=fn=>fn();
global.document={getElementById(id){return id==='toc'?toc:null;},documentElement:{scrollHeight:0}};
global.window={innerHeight:0,scrollY:0,addEventListener(){},requestAnimationFrame:global.requestAnimationFrame};
eval(js);
const out={hasHandler:!!clickHandler};
clickHandler();out.first={collapsed:cls.has('collapsed'),aria:btn.attrs['aria-expanded'],label:btn.attrs['aria-label']};
clickHandler();out.second={collapsed:cls.has('collapsed'),aria:btn.attrs['aria-expanded'],label:btn.attrs['aria-label']};
process.stdout.write(JSON.stringify(out));
"""
        (tmp_path / "harness.js").write_text(harness, encoding="utf-8")
        proc = subprocess.run(
            [node, str(tmp_path / "harness.js"), str(tmp_path / "toc.js")],
            capture_output=True, text=True, timeout=30,
        )
        assert proc.returncode == 0, proc.stderr
        r = json.loads(proc.stdout)
        assert r["hasHandler"] is True
        assert r["first"] == {
            "collapsed": True, "aria": "false", "label": "Expand table of contents",
        }
        assert r["second"] == {
            "collapsed": False, "aria": "true", "label": "Collapse table of contents",
        }


# ═══════════════════════════════════════════════════════════════════════
# Security regressions (S1-S4)
# ═══════════════════════════════════════════════════════════════════════


class TestSecurityFixes:
    _CSS = "body { color: #000; }"

    def test_s1_render_html_escapes_malicious_title(self) -> None:
        """An H1 that breaks out of <title> must be HTML-escaped, not raw."""
        md = "# </title><script>alert(1)</script>\n\nBody.\n"
        out = render_html(md, self._CSS)
        head = out.split("</head>", 1)[0]
        assert "<script>alert(1)</script>" not in head
        assert "&lt;/title&gt;&lt;script&gt;alert(1)" in head

    def test_s2_toc_nav_escapes_malicious_heading(
        self, tmp_themes_dir: Path,
    ) -> None:
        """A backticked-script heading must not re-inject live markup into the
        TOC nav (spliced in after nh3 has already run)."""
        md = "# `<script>alert(2)</script>`\n\nText.\n"
        out = convert(md, "test-theme", tmp_themes_dir, toc=True)
        nav = out.split("<main>", 1)[0]
        assert "<script>alert(2)</script>" not in nav
        assert "&lt;script&gt;alert(2)" in nav

    def test_s3_inline_style_attribute_stripped(self) -> None:
        """An untrusted inline style must be removed by nh3 (clickjacking)."""
        md = (
            '<div style="position:fixed;top:0;left:0;'
            'width:100vw;height:100vh">overlay</div>\n'
        )
        html = md_to_html(md)
        assert "style=" not in html
        assert "overlay" in html

    def test_s3_class_and_id_still_allowed(self) -> None:
        """Removing style must not strip the class/id extensions rely on."""
        html = md_to_html("# Heading\n")
        assert 'id="heading"' in html

    def test_s4_nul_byte_stripped_no_content_confusion(self) -> None:
        """A literal NUL in input must not collide with placeholder sentinels."""
        md = "# Title\n\nSee `\x00realcode\x00` and body text.\n"
        html = md_to_html(md)
        assert "\x00" not in html
        assert "realcode" in html


# ═══════════════════════════════════════════════════════════════════════
# TOC nesting balance (L1)
# ═══════════════════════════════════════════════════════════════════════


class TestTocNestingBalance:
    @staticmethod
    def _balanced(nav: str) -> bool:
        # Count open-tag prefixes so the outer ``<ul id="toc-list">`` is balanced
        # against its ``</ul>`` alongside the plain nested ``<ul>``s.
        return (
            nav.count("<ul") == nav.count("</ul>")
            and nav.count("<li>") == nav.count("</li>")
        )

    def test_l1_h1_to_h3_jump(self) -> None:
        body = '<h1 id="a">A</h1><h3 id="b">B</h3>'
        assert self._balanced(_build_toc_nav(body))

    def test_l1_start_at_h2(self) -> None:
        body = '<h2 id="a">A</h2>'
        assert self._balanced(_build_toc_nav(body))

    def test_l1_h3_to_h1_drop(self) -> None:
        body = '<h3 id="a">A</h3><h1 id="b">B</h1>'
        assert self._balanced(_build_toc_nav(body))

    def test_l1_h1_h3_h1(self) -> None:
        body = '<h1 id="a">A</h1><h3 id="b">B</h3><h1 id="c">C</h1>'
        assert self._balanced(_build_toc_nav(body))


# ═══════════════════════════════════════════════════════════════════════
# Code-protection robustness (R1, R3, R4, R5, R6)
# ═══════════════════════════════════════════════════════════════════════


class TestCodeProtectionRobustness:
    def test_r1_callout_inside_fence_survives(self) -> None:
        """A '> [!note]' example inside a fence must not become an admonition."""
        md = "```\n> [!note] Example\n> body line\n```\n"
        html = md_to_html(md)
        assert "[!note] Example" in html
        assert "admonition" not in html

    def test_r3_multi_backtick_inline_with_tick(self) -> None:
        """A double-backtick span containing a lone backtick protects its
        wikilink from rewriting."""
        md = "Use ``code with ` tick and [[WL]]`` here."
        result = preprocess_wikilinks(md)
        assert "[[WL]]" in result
        assert result == md

    def test_r4_tilde_fence_protected(self) -> None:
        """A ~~~ fence must protect its wikilinks from rewriting."""
        md = "~~~\n[[link]]\n~~~\n"
        assert "[[link]]" in preprocess_wikilinks(md)

    def test_r5_longer_closing_fence_protected(self) -> None:
        """A block opened with ``` and closed with a longer ```` is protected."""
        md = "```\n[[Inside]]\n````\n[[Outside]]\n"
        result = preprocess_wikilinks(md)
        assert "[[Inside]]" in result  # protected inside the fence
        assert "[Outside](Outside.html)" in result  # the outside wikilink

    def test_r6_title_ignores_fenced_hash_comment(self) -> None:
        """A '# comment' inside a fence must not win as the document title."""
        md = "```bash\n# not the title\necho hi\n```\n\n# Real Title\n\nbody\n"
        assert extract_title(md) == "Real Title"


# ═══════════════════════════════════════════════════════════════════════
# Inline chips (:key[label])
# ═══════════════════════════════════════════════════════════════════════


class TestPreprocessChips:
    def test_palette_key_becomes_chip_span(self) -> None:
        result = preprocess_chips(":blue[North]")
        assert result == '<span class="pchip blue">North</span>'

    def test_non_palette_key_left_literal(self) -> None:
        assert preprocess_chips(":other[x]") == ":other[x]"

    def test_ordinary_colon_text_untouched(self) -> None:
        md = "Ratio 3:1 and time 10:30 stay as-is."
        assert preprocess_chips(md) == md

    def test_key_glued_to_preceding_word_left_literal(self) -> None:
        # A palette key must start a fresh token; glued to a word (or another
        # colon) it is ordinary prose, not a chip.
        for md in ("code:red[1]", "a:blue[x]", "path::green[y]"):
            assert preprocess_chips(md) == md

    def test_multiple_chips(self) -> None:
        result = preprocess_chips(":blue[North] and :green[South]")
        assert result == (
            '<span class="pchip blue">North</span> and '
            '<span class="pchip green">South</span>'
        )

    def test_chip_in_inline_code_untouched(self) -> None:
        md = "Use `:blue[North]` to tag a row."
        result = preprocess_chips(md)
        assert ":blue[North]" in result
        assert "pchip" not in result

    def test_palette_key_brace_becomes_ptext_span(self) -> None:
        assert (
            preprocess_chips(":blue{North}")
            == '<span class="ptext blue">North</span>'
        )

    def test_non_palette_key_brace_left_literal(self) -> None:
        assert preprocess_chips(":other{x}") == ":other{x}"
        assert preprocess_chips("plain {curly}") == "plain {curly}"

    def test_chip_and_ptext_coexist(self) -> None:
        result = preprocess_chips(":green[pill] and :green{bare}")
        assert '<span class="pchip green">pill</span>' in result
        assert '<span class="ptext green">bare</span>' in result

    def test_ptext_in_inline_code_untouched(self) -> None:
        result = preprocess_chips("Use `:blue{North}` bare.")
        assert ":blue{North}" in result
        assert "ptext" not in result

    def test_chip_in_fenced_code_untouched(self) -> None:
        md = "```\n:blue[North]\n```"
        result = preprocess_chips(md)
        assert ":blue[North]" in result
        assert "pchip" not in result

    def test_all_eleven_palette_keys(self) -> None:
        keys = [
            "blue", "green", "amber", "purple", "teal", "pink",
            "lime", "gold", "slate", "red", "gray",
        ]
        for key in keys:
            result = preprocess_chips(f":{key}[label]")
            assert result == f'<span class="pchip {key}">label</span>'


class TestSmartDashes:
    """``--`` -> en-dash, ``---`` -> em-dash; quotes/ellipses left as typed."""

    def test_double_dash_becomes_en_dash(self) -> None:
        assert "–" in md_to_html("spans 1 -- 2")

    def test_triple_dash_becomes_em_dash(self) -> None:
        assert "—" in md_to_html("a break --- here")

    def test_dashes_in_code_untouched(self) -> None:
        out = md_to_html("`a -- b`")
        assert "a -- b" in out
        assert "–" not in out and "—" not in out

    def test_quotes_and_ellipses_not_smartened(self) -> None:
        out = md_to_html('say "hi" and wait ...')
        assert '"hi"' in out
        assert "..." in out
        assert "“" not in out and "…" not in out

    def test_hero_field_gets_smart_dashes(self) -> None:
        out = convert(
            "---\ntitle: T\nlede: a --- b\n---\n\n# Doc\n\nBody.\n", "report"
        )
        assert "—" in out


class TestMdToHtmlChips:
    def test_chip_renders_to_span_in_html(self) -> None:
        html = md_to_html(":blue[North]")
        assert '<span class="pchip blue">North</span>' in html

    def test_hostile_chip_label_is_sanitised(self) -> None:
        # A chip label carrying an XSS payload flows through nh3 like any other
        # markup: the event handler is stripped, leaving inert output.
        html = md_to_html(":blue[<img src=x onerror=alert(1)>]")
        assert "onerror" not in html
        assert "alert(1)" not in html
        # The chip wrapper itself is intact; only the payload is neutralised.
        assert 'class="pchip blue"' in html


# ═══════════════════════════════════════════════════════════════════════
# Document footer (::: footer -> <footer>)
# ═══════════════════════════════════════════════════════════════════════


class TestPreprocessFooter:
    def test_footer_container_becomes_footer_block(self) -> None:
        result = preprocess_footer("::: footer\nTraced from X.\n:::")
        assert '<footer class="doc-footer" markdown="1">' in result
        assert "</footer>" in result
        assert "Traced from X." in result

    def test_unclosed_footer_runs_to_end(self) -> None:
        result = preprocess_footer("::: footer\nlast line, no close")
        assert '<footer class="doc-footer" markdown="1">' in result
        assert "</footer>" in result

    def test_other_container_is_not_a_footer(self) -> None:
        md = "::: note\nhi\n:::"
        assert preprocess_footer(md) == md

    def test_footer_inside_code_is_untouched(self) -> None:
        md = "```\n::: footer\nx\n:::\n```"
        assert preprocess_footer(md) == md


class TestMdToHtmlFooter:
    def test_footer_renders_and_processes_inner_markdown(self) -> None:
        out = md_to_html("::: footer\nTraced from **converter.py**.\n\n- a\n- b\n:::")
        # The <footer> survives nh3 (the allowlist addition) -- this assertion
        # would fail if ``footer`` were still stripped.
        assert "<footer" in out
        assert "</footer>" in out
        # Inner markdown was processed by md_in_html.
        assert "<strong>converter.py</strong>" in out
        assert "<ul>" in out
        # md_in_html consumes the marker attribute.
        assert "markdown=" not in out

    def test_no_footer_without_marker(self) -> None:
        assert "<footer" not in md_to_html("Just body text.")

    def test_hostile_footer_content_is_sanitised(self) -> None:
        out = md_to_html("::: footer\n<img src=x onerror=alert(1)>\n:::")
        assert "onerror" not in out
        assert "<footer" in out


class TestReportThemeFooter:
    def test_report_css_styles_footer_and_file_bullets(self) -> None:
        css = load_theme_css("report")
        assert "footer.doc-footer" in css
        # The file list gets chevron bullets -- the light typographic chevron
        # (U+203A), not a heavy ASCII ``>``.
        assert "footer.doc-footer li::before" in css
        m = re.search(r"footer\.doc-footer li::before \{([^}]*)\}", css)
        assert m is not None
        assert 'content: "›"' in m.group(1)
        assert 'content: ">"' not in m.group(1)


# ═══════════════════════════════════════════════════════════════════════
# Code sheet header (title= -> .sheet-head)
# ═══════════════════════════════════════════════════════════════════════


class TestStyleCodeHeaders:
    _PRE = '<div class="highlight"><span class="filename">{}</span><pre></pre></div>'

    def test_pipe_title_splits_into_left_and_right(self) -> None:
        out = _style_code_headers(self._PRE.format("Before | file.py"))
        assert (
            '<div class="highlight"><div class="sheet-head">'
            '<span class="t">Before</span>'
            '<span class="r">file.py</span>'
            "</div>"
        ) in out

    def test_plain_title_is_single_label(self) -> None:
        out = _style_code_headers(self._PRE.format("config.py"))
        assert (
            '<div class="highlight"><div class="sheet-head">'
            '<span class="t">config.py</span></div>'
        ) in out

    def test_no_filename_is_untouched(self) -> None:
        html = '<div class="highlight"><pre><code>x</code></pre></div>'
        assert _style_code_headers(html) == html

    def test_prose_filename_span_is_not_transformed(self) -> None:
        # The match is anchored to the opening highlight div, so a stray
        # ``.filename`` span in prose is left alone (no orphan header).
        html = '<p>see <span class="filename">notes.txt</span></p>'
        assert _style_code_headers(html) == html

    def test_already_escaped_content_is_not_double_escaped(self) -> None:
        # pymdownx escapes the title; the pass must re-emit it verbatim.
        out = _style_code_headers(self._PRE.format("a &lt;b&gt;"))
        assert "a &lt;b&gt;" in out
        assert "&amp;lt;" not in out


class TestMdToHtmlCodeSheet:
    def test_titled_fence_renders_header_and_preserves_highlight(self) -> None:
        out = md_to_html('```{.python title="Before | converter.py"}\nx = 1\n```')
        assert '<div class="sheet-head">' in out
        assert '<span class="t">Before</span>' in out
        assert '<span class="r">converter.py</span>' in out
        # Syntax highlighting survives (the delegate highlighter ran).
        assert 'class="highlight"' in out
        assert 'class="mi"' in out
        assert "filename" not in out

    def test_plain_fence_has_no_sheet_head(self) -> None:
        out = md_to_html("```python\nx = 1\n```")
        assert "sheet-head" not in out
        assert 'class="highlight"' in out

    def test_hostile_title_is_escaped(self) -> None:
        out = md_to_html('```{.python title="<img src=x onerror=alert(1)>"}\nx=1\n```')
        assert "<img" not in out
        assert '<span class="t">&lt;img src=x onerror=alert(1)&gt;</span>' in out


class TestReportThemeCodeSheet:
    def test_report_css_styles_the_sheet_head(self) -> None:
        css = load_theme_css("report")
        assert ".sheet-head" in css
        assert ".sheet-head .t" in css
        assert ".sheet-head .r" in css
        # The header joins the code into one card via :has().
        assert ".highlight:has(.sheet-head)" in css


# ═══════════════════════════════════════════════════════════════════════
# Table scroll wrapper (.tbl-scroll)
# ═══════════════════════════════════════════════════════════════════════


class TestWrapTables:
    def test_wrap_tables_wraps_a_table(self) -> None:
        wrapped = _wrap_tables("<table><tr><td>1</td></tr></table>")
        assert wrapped == (
            '<div class="tbl-scroll"><table><tr><td>1</td></tr></table></div>'
        )

    def test_no_table_is_untouched(self) -> None:
        assert _wrap_tables("<p>no table here</p>") == "<p>no table here</p>"

    def test_two_tables_wrapped_separately_not_nested(self) -> None:
        wrapped = _wrap_tables("<table><tr><td>1</td></tr></table>"
                               "<table><tr><td>2</td></tr></table>")
        assert wrapped.count('<div class="tbl-scroll">') == 2
        assert '<div class="tbl-scroll"><div class="tbl-scroll"' not in wrapped

    def test_keyed_paragraph_adds_keyed_class_and_is_consumed(self) -> None:
        wrapped = _wrap_tables(
            "<p>{.keyed}</p><table><tr><td>1</td></tr></table>"
        )
        assert wrapped == (
            '<div class="tbl-scroll keyed"><table><tr><td>1</td></tr></table></div>'
        )

    def test_keyed_paragraph_without_table_is_left_literal(self) -> None:
        # A ``{.keyed}`` paragraph not before a table is left in place (renders as
        # literal text), never dropped.
        html = "<p>{.keyed}</p><p>no table</p>"
        assert _wrap_tables(html) == html


class TestPreprocessKeyedTables:
    def test_marker_before_table_is_separated_and_kept(self) -> None:
        # The line is kept literal, with a blank line inserted so the table below
        # is not lazy-merged into it.
        result = preprocess_keyed_tables("{.keyed}\n| A | B |\n|---|---|\n| 1 | 2 |")
        assert result.startswith("{.keyed}\n\n| A | B |")

    def test_already_separated_marker_is_unchanged(self) -> None:
        md = "{.keyed}\n\nJust a paragraph."
        assert preprocess_keyed_tables(md) == md

    def test_marker_inside_code_is_untouched(self) -> None:
        md = "```\n{.keyed}\n| A |\n```"
        assert preprocess_keyed_tables(md) == md


class TestMdToHtmlKeyedTable:
    def test_keyed_table_wrapper_has_keyed_class(self) -> None:
        out = md_to_html("{.keyed}\n| K | V |\n|---|---|\n| a | b |")
        assert 'class="tbl-scroll keyed">' in out

    def test_keyed_above_pipeless_table_form(self) -> None:
        # Header + delimiter without edge pipes still keys end-to-end.
        out = md_to_html("{.keyed}\nK | V\n---|---\na | b")
        assert 'class="tbl-scroll keyed">' in out

    def test_keyed_above_malformed_table_stays_literal(self) -> None:
        # A near-table Markdown does not actually build leaves ``{.keyed}`` as
        # literal text (never silently dropped) and applies no keyed class.
        out = md_to_html("{.keyed}\n| A | B | C |\n|---|---|\n| 1 | 2 | 3 |")
        assert "<p>{.keyed}</p>" in out
        assert "tbl-scroll keyed" not in out

    def test_chips_work_in_table_cells(self) -> None:
        # Status cells are covered by chips (the accent key column is the new bit).
        out = md_to_html("| Task | Status |\n|------|--------|\n| Build | :green[done] |")
        assert '<span class="pchip green">done</span>' in out

    def test_report_css_styles_keyed_key_column(self) -> None:
        css = load_theme_css("report")
        assert ".tbl-scroll.keyed tbody td:first-child" in css


class TestMdToHtmlTableScroll:
    def test_table_is_wrapped_in_scroll_container(self) -> None:
        out = md_to_html("| A | B |\n|---|---|\n| 1 | 2 |")
        assert re.search(r'<div class="tbl-scroll">\s*<table', out)
        assert out.count("tbl-scroll") == 1
        assert out.find("</table>") < out.find("</div>")

    def test_katex_mtable_is_not_wrapped(self) -> None:
        # KaTeX emits MathML ``<mtable>``, not HTML ``<table>`` -- it must not be
        # caught by the table-wrap pass.
        out = md_to_html(r"$$\begin{pmatrix} a & b \\ c & d \end{pmatrix}$$")
        assert "tbl-scroll" not in out


class TestReportThemeTableScroll:
    def test_card_framing_lives_on_the_wrapper(self) -> None:
        css = load_theme_css("report")
        scroll = css[css.index(".tbl-scroll {"):]
        scroll = scroll[: scroll.index("}")]
        assert "overflow-x: auto" in scroll
        assert "border: 1px solid var(--line)" in scroll
        assert "box-shadow: var(--shadow)" in scroll

    def test_cells_wrap_to_fit(self) -> None:
        css = load_theme_css("report")
        # Cells wrap so a table sizes to the content column instead of forcing a
        # horizontal scroll (matching the reference); no nowrap on th/td.
        th_td = re.search(r"\nth, td \{([^}]*)\}", css).group(1)
        assert "white-space: nowrap" not in th_td
        assert "padding: 10px 14px" in th_td

    def test_print_suppresses_wrapper_shadow(self) -> None:
        css = load_theme_css("report")
        print_block = css[css.index("@media print"):]
        # The shadow now lives on the wrapper, so print suppresses .tbl-scroll.
        assert ".tbl-scroll" in print_block

    def test_print_reflows_wide_tables_instead_of_clipping(self) -> None:
        # Paper has no scrollbar, so on print the wrapper stops clipping, letting
        # a wide table reflow to fit instead of losing columns (cells wrap).
        css = load_theme_css("report")
        print_block = css[css.index("@media print"):]
        assert "overflow-x: visible" in print_block


# ═══════════════════════════════════════════════════════════════════════
# Captions (~ text -> .caption)
# ═══════════════════════════════════════════════════════════════════════


class TestPreprocessCaptions:
    def test_marker_becomes_caption(self) -> None:
        result = preprocess_captions("~ Green is the working path")
        assert result == '<p class="caption">Green is the working path</p>\n'

    def test_strikethrough_is_not_a_caption(self) -> None:
        # ``~~del~~`` (two tildes) and ``~sub~`` are the tilde extension; only a
        # single ``~ `` (tilde + space) at line start is a caption marker.
        assert preprocess_captions("~~struck~~") == "~~struck~~"

    def test_marker_inside_code_fence_untouched(self) -> None:
        md = "```\n~ inside code\n```"
        assert preprocess_captions(md) == md

    def test_empty_caption_stays_literal(self) -> None:
        assert preprocess_captions("~   \n") == "~   \n"

    def test_caption_is_html_escaped(self) -> None:
        result = preprocess_captions("~ a <b> & c")
        assert "a &lt;b&gt; &amp; c" in result
        assert "<b>" not in result


class TestMdToHtmlCaptions:
    def test_caption_after_code_block_renders_in_order(self) -> None:
        out = md_to_html("```python\nx = 1\n```\n~ The build step")
        assert 'class="caption"' in out
        assert out.find('class="highlight"') < out.find('class="caption"')

    def test_caption_after_mermaid_renders(self) -> None:
        out = md_to_html("```mermaid\ngraph TD; A-->B\n```\n~ The pipeline")
        assert 'class="caption"' in out
        assert out.find("mermaid-diagram") < out.find('class="caption"')

    def test_hostile_caption_is_escaped(self) -> None:
        out = md_to_html("~ <img src=x onerror=alert(1)>")
        assert "<img" not in out
        assert "&lt;img src=x onerror=alert(1)&gt;" in out
        assert 'class="caption"' in out


class TestReportThemeCaption:
    def test_report_css_styles_caption(self) -> None:
        css = load_theme_css("report")
        assert ".caption" in css


# ═══════════════════════════════════════════════════════════════════════
# Section kickers (^ Label above a heading -> .sec-label)
# ═══════════════════════════════════════════════════════════════════════


class TestPreprocessSectionKickers:
    def test_kicker_above_heading_becomes_sec_label(self) -> None:
        result = preprocess_section_kickers("^ The symptom\n## What it reports")
        assert '<p class="sec-label">The symptom</p>' in result
        # The heading survives right after the emitted label.
        assert "## What it reports" in result

    def test_caret_not_above_heading_stays_literal(self) -> None:
        md = "^ just a caret line\n\nnot a heading"
        assert preprocess_section_kickers(md) == md

    def test_caret_inside_code_fence_untouched(self) -> None:
        md = "```\n^ inside code\n## also code\n```"
        assert preprocess_section_kickers(md) == md

    def test_whitespace_only_label_stays_literal(self) -> None:
        # An empty label after trimming would emit a blank ``.sec-label``; the
        # guard leaves the caret line literal instead.
        md = "^   \n## Heading"
        assert preprocess_section_kickers(md) == md
        assert "sec-label" not in md_to_html(md)

    def test_label_is_html_escaped(self) -> None:
        result = preprocess_section_kickers("^ a <b> & c\n## H")
        assert "a &lt;b&gt; &amp; c" in result
        assert "<b>" not in result


class TestMdToHtmlSectionKickers:
    def test_kicker_renders_adjacent_to_heading(self) -> None:
        out = md_to_html("^ The symptom\n## What it reports")
        # Adjacent DOM siblings (only whitespace between) so ``.sec-label + h2``
        # applies. Levels h1-h6 are all supported.
        assert re.search(
            r'<p class="sec-label">The symptom</p>\s*<h2', out
        )

    def test_hostile_kicker_label_is_escaped(self) -> None:
        # The label is HTML-escaped at emit time (the hero eyebrow/slot model),
        # so a hostile payload becomes inert text: no live element forms, and
        # the escaped source is what renders.
        out = md_to_html("^ <img src=x onerror=alert(1)>\n## Heading")
        assert "<img" not in out
        assert "&lt;img src=x onerror=alert(1)&gt;" in out
        assert 'class="sec-label"' in out


class TestReportThemeSectionKicker:
    def test_report_css_styles_sec_label(self) -> None:
        css = load_theme_css("report")
        assert ".sec-label" in css
        # The following heading is tucked against the kicker.
        assert ".sec-label + h2" in css
        # The body kicker is muted (--ink-faint), NOT the gold accent -- the
        # accent eyebrow is reserved for the hero.
        m = re.search(r"\n\.sec-label \{([^}]*)\}", css)
        assert m is not None
        assert "color: var(--ink-faint)" in m.group(1)
        assert "var(--accent)" not in m.group(1)
        # It matches the hero eyebrow's size and font -- only the colour differs.
        eb = re.search(r"\n\.eyebrow \{([^}]*)\}", css)
        assert eb is not None
        for prop in (
            "font-size: 12px",
            "letter-spacing: 0.18em",
            "font-family: var(--mono)",
            "text-transform: uppercase",
        ):
            assert prop in m.group(1)
            assert prop in eb.group(1)
        # Neither declares an explicit weight -- both rely on the normal (400)
        # default, so re-adding font-weight: 700 to the kicker would diverge.
        assert "font-weight" not in m.group(1)
        assert "font-weight" not in eb.group(1)


# ═══════════════════════════════════════════════════════════════════════
# Report theme
# ═══════════════════════════════════════════════════════════════════════


class TestReportTheme:
    """The shipped ``report`` drop-in theme and its chip/palette surface."""

    def test_report_theme_is_discoverable(self) -> None:
        assert "report" in list_themes()

    def test_report_css_carries_chip_and_palette_rules(self) -> None:
        css = load_theme_css("report")
        assert ".pchip" in css
        # Every one of the eleven palette keys has a chip rule.
        for key in (
            "blue", "green", "amber", "purple", "teal", "pink",
            "lime", "gold", "slate", "red", "gray",
        ):
            assert f".pchip.{key}" in css
        # A representative palette fill value from report_template's PALETTE.
        assert "#d7e6f2" in css

    def test_report_css_frames_mermaid_not_bare_svg(self) -> None:
        css = load_theme_css("report")
        assert ".mermaid-diagram" in css
        # A bare ``svg {`` rule would corrupt KaTeX's inline radicals.
        assert "\nsvg {" not in css
        assert "\nsvg{" not in css

    def test_report_css_gives_diagram_header_a_filled_bar(self) -> None:
        css = load_theme_css("report")
        m = re.search(r"\n\.mermaid-header \{([^}]*)\}", css)
        assert m is not None
        body = m.group(1)
        # A filled warm bar, not a bare underline.
        assert "linear-gradient(180deg, #fefefe, #f7f3ea)" in body
        # Pulled full-bleed to the card edges (card padding is 16px 14px) so the
        # fill spans the whole width -- the negative margin is what makes it a
        # bar rather than an inset strip.
        assert "margin: -16px -14px 14px" in body
        # Top corners nest inside the card's 12px radius.
        assert "border-radius: 11px 11px 0 0" in body
        # In dark the adapted diagram (and code) headers switch to the cool
        # panel bar token, since those cards ride on var(--panel).
        assert re.search(
            r"@media \(prefers-color-scheme: dark\) \{\s*"
            r"\.sheet-head,\s*"
            r"\.mermaid-structural \.mermaid-header,\s*"
            r"\.mermaid-categorical \.mermaid-header \{\s*"
            r"background: var\(--line-soft\);",
            css,
        ) is not None

    def test_convert_with_report_theme_succeeds(self) -> None:
        out = convert("# Doc\n\nBody with :teal[tag].\n", "report")
        assert "<!DOCTYPE html>" in out
        assert '<span class="pchip teal">tag</span>' in out

    def test_math_and_mermaid_render_under_report_theme(self) -> None:
        doc = (
            "# Title\n\nInline $x^2$ here.\n\n"
            "```mermaid\ngraph TD; A-->B\n```\n"
        )
        out = convert(doc, "report")
        assert 'class="katex"' in out
        # A flowchart is tagged structural so the report theme can recolour it.
        assert 'class="mermaid-diagram mermaid-structural"' in out

    def test_report_css_gives_body_lists_chevron_bullets(self) -> None:
        css = load_theme_css("report")
        # The disc is removed so only the chevron marker shows (no double bullet).
        assert re.search(r"\nul \{[^}]*list-style: none", css) is not None
        # Body unordered lists use the accent chevron as their marker. Anchored to
        # a line start so it lands on the general rule, not the nested one.
        m = re.search(
            r"\nul > li:not\(\.task-list-item\)::before \{([^}]*)\}", css
        )
        assert m is not None
        assert 'content: "›"' in m.group(1)
        assert "color: var(--accent)" in m.group(1)
        # Nested levels (a ul inside any list) step back to a transparent shade.
        m2 = re.search(
            r":is\(ol, ul\) ul > li:not\(\.task-list-item\)::before \{([^}]*)\}",
            css,
        )
        assert m2 is not None
        assert "opacity" in m2.group(1)
        # Task-list items are excluded (their own checkbox marker); the TOC opts
        # out; ordered lists keep their numbers (never matched by ``ul > li``).
        assert re.search(r"#toc li::before \{[^}]*content: none", css) is not None

    def test_report_css_matches_reference_type_and_spacing(self) -> None:
        css = load_theme_css("report")
        # Content column widened to the reference width; the old 860px is gone.
        assert "max-width: 1020px" in css
        assert "860px" not in css
        # Section spacing uses non-collapsing padding-top so a section gap adds to
        # the previous block's margin (matching the reference's section padding).
        sec = re.search(r"\n\.sec-label \{([^}]*)\}", css).group(1)
        assert "padding-top: 48px" in sec
        h2 = re.search(r"\nh2 \{([^}]*)\}", css).group(1)
        assert "padding-top: 48px" in h2
        # A heading right after a kicker owns no extra top gap (kicker owns it).
        tuck = re.search(r"\.sec-label \+ h1,.*?\{([^}]*)\}", css, re.S).group(1)
        assert "padding-top: 0" in tuck
        # Code header padding matches the reference (11px).
        sheet = re.search(r"\n\.sheet-head \{([^}]*)\}", css).group(1)
        assert "padding: 11px 16px" in sheet
        # The header LEFT label keeps its source case; the right meta stays upper.
        left_t = re.search(r"\.sheet-head \.t \{([^}]*)\}", css).group(1)
        assert "text-transform: none" in left_t
        left_mh = re.search(r"\.mermaid-header \.mh-left \{([^}]*)\}", css).group(1)
        assert "text-transform: none" in left_mh

    def test_report_css_numbers_ordered_lists_with_accent_counter(self) -> None:
        css = load_theme_css("report")
        # Ordered lists render a mono accent counter, not the default marker.
        assert re.search(r"\nol \{[^}]*list-style: none", css) is not None
        m = re.search(r"\nol > li::before \{([^}]*)\}", css)
        assert m is not None
        assert "counter(ol-item)" in m.group(1)
        assert "color: var(--accent)" in m.group(1)
        assert "font-family: var(--mono)" in m.group(1)
        # Footnotes keep their plain decimal marker (the container class is the
        # singular ``footnote``), excluded from the accent counter.
        assert re.search(
            r"\.footnote li::before \{[^}]*content: none", css
        ) is not None
        assert re.search(
            r"\.footnote ol \{[^}]*list-style: decimal", css
        ) is not None

    def test_report_css_styles_footnote_block_with_singular_class(self) -> None:
        css = load_theme_css("report")
        # The rendered container is the singular ``footnote``; the dead plural
        # ``.footnotes`` selectors must not linger (they never matched).
        assert re.search(r"\.footnotes\b", css) is None
        m = re.search(r"\n\.footnote \{([^}]*)\}", css)
        assert m is not None
        assert "border-top:" in m.group(1)
        assert "font-size: 13px" in m.group(1)

    def test_report_css_note_callout_is_amber(self) -> None:
        css = load_theme_css("report")
        # The note callout uses the amber accent (like warning), not the blue it
        # had before -- matching the reference.
        note = re.search(r"\.admonition\.note \{([^}]*)\}", css).group(1)
        assert "#c07a33" in note
        assert "#3f6f96" not in note
        title = re.search(
            r"\.admonition\.note \.admonition-title \{([^}]*)\}", css
        ).group(1)
        assert "#8a5210" in title
        # Dark mode note title is amber too, not the old blue.
        assert ".admonition.note .admonition-title { color: #fbbf24; }" in css

    def test_report_css_styles_bare_coloured_text(self) -> None:
        css = load_theme_css("report")
        base = re.search(r"\n\.ptext \{([^}]*)\}", css).group(1)
        assert "font-weight: 700" in base
        # A representative palette colour, light and (brighter) dark.
        assert ".ptext.green { color: #4b7a45; }" in css
        assert ".ptext.green { color: #86efac; }" in css
        assert ".ptext.red { color: #b0432c; }" in css

    def test_report_css_callout_inline_code_uses_family_colour(self) -> None:
        css = load_theme_css("report")
        # Inline code in a note callout takes the amber family tint (less
        # transparent than the callout's own 0.12 background).
        m = re.search(r"\.admonition\.note code[^{]*\{([^}]*)\}", css)
        assert m is not None
        assert "rgba(192, 122, 51, 0.25)" in m.group(1)
        # A code BLOCK inside a callout keeps its own frame (only inline tinted).
        assert re.search(r"\.admonition pre code \{[^}]*background: none", css)

    def test_report_css_card_header_font_matches_reference(self) -> None:
        css = load_theme_css("report")
        for sel in (r"\.mermaid-header \.mh-left", r"\.sheet-head \.t"):
            assert "font-size: 12px" in re.search(
                sel + r" \{([^}]*)\}", css
            ).group(1)
        for sel in (r"\.mermaid-header \.mh-right", r"\.sheet-head \.r"):
            assert "font-size: 11px" in re.search(
                sel + r" \{([^}]*)\}", css
            ).group(1)

    def test_keypoint_callout_becomes_admonition(self) -> None:
        out = md_to_html("> [!keypoint]\n> The one takeaway.")
        assert 'class="admonition keypoint"' in out

    def test_report_css_styles_keypoint_card(self) -> None:
        css = load_theme_css("report")
        kp = re.search(r"\.admonition\.keypoint \{([^}]*)\}", css).group(1)
        # An elevated white card with an accent-line border (not a tinted rule).
        assert "border: 1px solid var(--accent-line)" in kp
        assert "background: var(--panel)" in kp
        # No title on a keypoint.
        assert re.search(
            r"\.admonition\.keypoint \.admonition-title \{[^}]*display: none", css
        )
        # Its pull-quote is an amber-barred block.
        bq = re.search(
            r"\.admonition\.keypoint blockquote \{([^}]*)\}", css
        ).group(1)
        assert "border-left: 3px solid var(--accent)" in bq
        assert "background: var(--accent-soft)" in bq

    def test_report_css_centres_the_task_checkmark(self) -> None:
        css = load_theme_css("report")
        # A ticked box's checkmark is centre-anchored, not pinned to a fixed
        # low-left offset (which left it visibly off-centre).
        m = re.search(
            r"\[checked\] \+ \.task-list-indicator::after \{([^}]*)\}", css
        )
        assert m is not None
        body = m.group(1)
        # Centre-anchored: left/top 50% put the tick's origin at the box centre,
        # and the negative margins (half the tick's own box, with a 1px optical
        # lift) pull it back so it sits true -- both halves are load-bearing.
        assert "left: 50%" in body
        assert "top: 50%" in body
        assert "margin-left: -3px" in body
        assert "margin-top: -6px" in body


# ═══════════════════════════════════════════════════════════════════════
# Code line emphasis (hl_lines -> .hll)
# ═══════════════════════════════════════════════════════════════════════


class TestCodeLineHighlight:
    """``hl_lines`` marks one line of a code block; the report theme bands it."""

    def test_hl_lines_emits_hll_class(self) -> None:
        # The parser already wraps the flagged line in ``.hll``; nh3 keeps the
        # class (``*: {class}``). This is the hook the report theme styles.
        html = md_to_html('```python hl_lines="2"\nx = 1\ny = 2\nz = 3\n```')
        assert 'class="hll"' in html
        # Syntax highlighting is preserved alongside the banded line.
        assert 'class="highlight"' in html

    def test_plain_fence_has_no_hll(self) -> None:
        html = md_to_html("```python\nx = 1\n```")
        assert "hll" not in html

    def test_adjacent_hl_lines_break_onto_separate_rows(self) -> None:
        html = md_to_html('```python\na = 1\nb = 2\nc = 3\n```'.replace(
            "```python", '```python hl_lines="2 3"'
        ))
        assert html.count('class="hll"') == 2
        # Each band's terminating newline is moved OUTSIDE its span, so two
        # consecutive bands are separated by a real line break (not glued
        # together, which piled them onto one row). This pattern -- one hll span
        # closing, a newline, then the next hll span -- only holds with the fix.
        assert re.search(
            r'<span class="hll">.*?</span>\n<span class="hll">', html, re.S
        )
        assert '</span><span class="hll">' not in html
        assert '\n</span>' not in html

    def test_report_css_bands_the_highlighted_line(self) -> None:
        css = load_theme_css("report")
        assert ".highlight .hll" in css
        # The band is an accent tint with an inset accent rule. inline-block +
        # min-width:100% keeps it covering the whole line even once ``pre`` is
        # scrolled horizontally (a plain block box stops at the static width).
        marker = css[css.index(".highlight .hll"):]
        marker = marker[: marker.index("}")]
        assert "display: inline-block" in marker
        assert "min-width: 100%" in marker
        assert "var(--accent-soft)" in marker
        assert "inset 3px 0 var(--accent)" in marker

    def test_report_css_hll_prints_with_a_border_cue(self) -> None:
        # Browsers drop background + box-shadow when "print background graphics"
        # is off (the default), so the band falls back to a real left border in
        # the print block -- borders always print, keeping the line marked.
        css = load_theme_css("report")
        print_block = css[css.index("@media print"):]
        assert ".highlight .hll" in print_block
        hll_print = print_block[print_block.index(".highlight .hll"):]
        hll_print = hll_print[: hll_print.index("}")]
        assert "border-left: 3px solid" in hll_print


