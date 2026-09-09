"""Tests for the mdtohtml converter module."""

from __future__ import annotations

from pathlib import Path

import pytest

from mdtohtml.converter import (
    TOC_JS,
    _build_toc_nav,
    _extract_headings,
    convert,
    extract_title,
    list_themes,
    load_theme_css,
    md_to_html,
    preprocess_obsidian_callouts,
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
# Math handling (client-side KaTeX)
# ═══════════════════════════════════════════════════════════════════════


class TestMath:
    """Math renders client-side via bundled KaTeX; math-free docs ship none."""

    def test_math_free_has_no_katex_assets(self, tmp_themes_dir: Path) -> None:
        content = convert("# Plain\n\nNo math here at all.\n", "test-theme",
                          tmp_themes_dir)
        # No auto-render init, no math delimiter spans, no inlined KaTeX fonts.
        assert "renderMathInElement" not in content
        assert "katex-inline" not in content
        assert 'katex-display">' not in content
        assert "data:font/woff2;base64" not in content

    def test_math_injects_katex_and_delimiters(self, tmp_themes_dir: Path) -> None:
        md = "Euler: $e^{i\\pi} + 1 = 0$\n\n$$x = \\frac{-b}{2a}$$\n"
        content = convert(md, "test-theme", tmp_themes_dir)
        # KaTeX auto-render init present, and the bundle was injected.
        assert "renderMathInElement" in content
        assert "data:font/woff2;base64" in content
        # Inline delimiter span with the expression text.
        assert '<span class="katex-inline">\\(e^{i\\pi} + 1 = 0\\)</span>' in content
        # Display delimiter span with the expression text.
        assert '<span class="katex-display">\\[x = \\frac{-b}{2a}\\]</span>' in content

    def test_math_escapes_html_specials(self, tmp_themes_dir: Path) -> None:
        content = convert("Compare $a < b > c$.", "test-theme", tmp_themes_dir)
        # The delimiter span survives sanitisation with entities, escaped once.
        assert '<span class="katex-inline">\\(a &lt; b &gt; c\\)</span>' in content
        assert "&amp;lt;" not in content  # not double-escaped

    def test_math_delimiters_survive_sanitisation(self) -> None:
        html = md_to_html("Inline $x^2$ math.")
        assert '<span class="katex-inline">' in html
        assert "\\(x^2\\)" in html

    def test_katex_class_mention_does_not_inject(self, tmp_themes_dir: Path) -> None:
        # A math-free doc that merely names the KaTeX classes -- in prose and in
        # inline code -- must ship zero KaTeX bytes. The bare class name appears
        # in the body as text/`<code>` but never as the `class="..">\(` markup
        # `_math_to_delimiters` emits, so injection must not trigger.
        md = "Style the `katex-inline` and katex-display classes in your CSS.\n"
        content = convert(md, "test-theme", tmp_themes_dir)
        assert "katex-inline" in content  # the word is legitimately present
        assert "renderMathInElement" not in content
        assert "data:font/woff2;base64" not in content


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
        assert nav.count("<ul>") >= 3
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
const toc={scrollHeight:10,clientHeight:100,scrollTop:0,querySelectorAll:()=>anchors,getBoundingClientRect(){return {top:0,bottom:100};}};
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
        return (
            nav.count("<ul>") == nav.count("</ul>")
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


