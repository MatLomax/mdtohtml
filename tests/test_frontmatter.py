"""Tests for front-matter parsing and the report hero it drives."""

from __future__ import annotations

from mdtohtml.converter import load_theme_css, render_html
from mdtohtml.frontmatter import Slot, parse_frontmatter

REPORT_CSS = load_theme_css("report")


# ═══════════════════════════════════════════════════════════════════════
# parse_frontmatter
# ═══════════════════════════════════════════════════════════════════════


class TestParseFrontmatter:
    def test_no_leading_fence_returns_unchanged(self):
        text = "# Title\n\nBody."
        fm, body = parse_frontmatter(text)
        assert fm is None
        assert body == text

    def test_unterminated_fence_is_not_frontmatter(self):
        # A leading '---' with no closing '---' is a thematic break, not FM.
        text = "---\ntitle: X\n\nBody without a closing fence."
        fm, body = parse_frontmatter(text)
        assert fm is None
        assert body == text

    def test_full_block_parsed_and_stripped(self):
        text = (
            "---\n"
            "eyebrow: House style\n"
            "title: Release Report\n"
            "lede: One intro line.\n"
            "---\n"
            "\n"
            "## First section\n"
        )
        fm, body = parse_frontmatter(text)
        assert fm is not None
        assert fm.eyebrow == "House style"
        assert fm.title == "Release Report"
        assert fm.lede == "One intro line."
        assert fm.slots == []
        assert body == "## First section\n"

    def test_slots_accumulate_and_split_on_pipe(self):
        text = (
            "---\n"
            "slot: Shipped | Everything green | 178 tests pass.\n"
            "slot: In review | Report theme | Auto light/dark.\n"
            "---\n"
            "body\n"
        )
        fm, _ = parse_frontmatter(text)
        assert fm.slots == [
            Slot("Shipped", "Everything green", "178 tests pass."),
            Slot("In review", "Report theme", "Auto light/dark."),
        ]

    def test_slot_with_fewer_fields(self):
        fm, _ = parse_frontmatter("---\nslot: Only a label\n---\nx\n")
        assert fm.slots == [Slot("Only a label", "", "")]

    def test_slot_extra_pipes_fold_into_body(self):
        fm, _ = parse_frontmatter("---\nslot: L | H | a | b | c\n---\nx\n")
        assert fm.slots == [Slot("L", "H", "a | b | c")]

    def test_colon_in_value_is_preserved(self):
        fm, _ = parse_frontmatter("---\nlede: The meeting is at 10:30 sharp.\n---\nx\n")
        assert fm.lede == "The meeting is at 10:30 sharp."

    def test_unknown_keys_ignored(self):
        fm, _ = parse_frontmatter("---\nauthor: Someone\ntitle: T\n---\nx\n")
        assert fm.title == "T"
        assert fm.eyebrow == ""

    def test_has_hero_flags(self):
        fm, _ = parse_frontmatter("---\ntitle: T\n---\nx\n")
        assert fm.has_hero is True

    def test_block_without_recognised_key_is_not_frontmatter(self):
        # No recognised hero key -> not captured, so nothing is deleted.
        text = "---\nauthor: nobody\n---\nx\n"
        fm, body = parse_frontmatter(text)
        assert fm is None
        assert body == text

    def test_body_leading_blank_lines_stripped(self):
        fm, body = parse_frontmatter("---\ntitle: T\n---\n\n\nfirst line\n")
        assert body == "first line\n"

    def test_leading_thematic_break_section_not_captured(self):
        # A '---' break, a heading, prose, then another '---' must NOT be eaten.
        text = "---\n# My Chapter\n\nImportant intro paragraph.\n\n---\n\nMore body.\n"
        fm, body = parse_frontmatter(text)
        assert fm is None
        assert body == text

    def test_colon_prose_between_breaks_not_captured(self):
        # A lone 'Note:' line looks like key:value but has no recognised key.
        text = "---\nNote: this is prose, not front matter.\n---\nbody\n"
        fm, body = parse_frontmatter(text)
        assert fm is None
        assert body == text

    def test_indented_fence_is_not_frontmatter(self):
        # An indented '---' is a thematic break, never a front-matter fence.
        text = "  ---\ntitle: X\n  ---\nbody\n"
        fm, body = parse_frontmatter(text)
        assert fm is None
        assert body == text

    def test_empty_slot_has_no_hero_content(self):
        # A bare 'slot:' carries nothing, so on its own it is not a hero.
        fm, _ = parse_frontmatter("---\nslot:\n---\nx\n")
        assert fm is not None
        assert fm.slots == [Slot("", "", "")]
        assert fm.has_hero is False

    def test_crlf_body_has_no_leading_carriage_return(self):
        # A CRLF document must not leave a stray '\r' at the head of the body.
        fm, body = parse_frontmatter("---\r\ntitle: T\r\n---\r\n\r\n## Body\r\n")
        assert fm is not None and fm.title == "T"
        assert not body.startswith("\r")
        assert body.startswith("## Body")


# ═══════════════════════════════════════════════════════════════════════
# render_html — hero integration
# ═══════════════════════════════════════════════════════════════════════


class TestHeroRendering:
    def _render(self, md: str, **kw) -> str:
        return render_html(md, REPORT_CSS, **kw)

    def test_full_hero_structure(self):
        md = (
            "---\n"
            "eyebrow: Component reference\n"
            "title: Release Report\n"
            "lede: One **bold** intro.\n"
            "slot: Shipped | All green | 178 tests pass.\n"
            "slot: Review | Theme | Auto light/dark.\n"
            "slot: Deferred | Windows | Needs a runner.\n"
            "---\n"
            "\n"
            "## Section one\n\nProse.\n"
        )
        # Assert against the body only -- the report CSS comment mentions the
        # literal ``<header class="report-hero">``, so a whole-document search
        # would pass even if the hero were never rendered (a false green).
        body = self._render(md).split("</head>", 1)[1]
        assert '<header class="report-hero">' in body
        assert '<p class="eyebrow">Component reference</p>' in body
        assert "<h1>Release Report</h1>" in body
        assert '<p class="lede">One <strong>bold</strong> intro.</p>' in body
        assert '<div class="stages">' in body
        assert body.count('<div class="stage-card">') == 3
        assert '<span class="n">Shipped</span>' in body
        assert "<h3>All green</h3>" in body
        assert "<p>178 tests pass.</p>" in body

    def test_title_sourced_from_frontmatter(self):
        md = "---\ntitle: FM Title\n---\n\n## Body only h2\n"
        html = self._render(md)
        assert "<title>FM Title</title>" in html

    def test_explicit_title_arg_wins_over_frontmatter(self):
        md = "---\ntitle: FM Title\n---\n\n## Body\n"
        html = self._render(md, title="Explicit")
        assert "<title>Explicit</title>" in html

    def test_no_frontmatter_has_no_hero(self):
        md = "# Ordinary\n\nIntro paragraph.\n"
        html = self._render(md)
        # Search the body only -- the report CSS comment mentions the hero markup.
        body = html.split("</head>", 1)[1]
        assert "report-hero" not in body
        assert "<title>Ordinary</title>" in html

    def test_hero_lives_inside_main_with_toc(self):
        md = (
            "---\ntitle: T\n---\n\n"
            "## Alpha\n\ntext\n\n## Beta\n\ntext\n"
        )
        html = self._render(md, toc=True)
        body = html.split("</head>", 1)[1]
        main_start = body.index("<main>")
        hero_pos = body.index('class="report-hero"')
        toc_pos = body.index('id="toc"')
        assert toc_pos < main_start < hero_pos

    def test_hero_h1_absent_from_toc(self):
        md = "---\ntitle: Hero Title\n---\n\n## Real Section\n\ntext\n"
        html = self._render(md, toc=True)
        toc_block = html[html.index('id="toc"') : html.index("</nav>")]
        assert "Hero Title" not in toc_block
        assert "Real Section" in toc_block

    def test_partial_hero_title_only(self):
        md = "---\ntitle: Just A Title\n---\n\n## S\n\nx\n"
        body = self._render(md).split("</head>", 1)[1]
        assert '<header class="report-hero">' in body
        assert "<h1>Just A Title</h1>" in body
        assert 'class="eyebrow"' not in body
        assert 'class="stages"' not in body

    def test_empty_slot_renders_no_card(self):
        # An empty 'slot:' beside a title must not emit an empty stage card.
        md = "---\ntitle: T\nslot:\n---\n\n## S\n\nx\n"
        body = self._render(md).split("</head>", 1)[1]
        assert "<h1>T</h1>" in body
        assert 'class="stages"' not in body
        assert 'class="stage-card"' not in body


# ═══════════════════════════════════════════════════════════════════════
# render_html — hero field sanitisation (XSS probes)
# ═══════════════════════════════════════════════════════════════════════


class TestHeroSanitisation:
    def _render(self, md: str) -> str:
        return render_html(md, REPORT_CSS)

    def test_eyebrow_escaped(self):
        html = self._render("---\neyebrow: <script>alert(1)</script>\n---\nx\n")
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_title_escaped_in_hero_and_head(self):
        html = self._render("---\ntitle: <img src=x onerror=alert(1)>\n---\nx\n")
        assert "<img src=x onerror" not in html
        # Escaped both in the <title> and in the hero <h1>.
        assert html.count("&lt;img") >= 2

    def test_lede_markup_neutralised_but_formatting_kept(self):
        html = self._render(
            "---\nlede: safe **bold** <script>evil()</script>\n---\nx\n"
        )
        assert "<strong>bold</strong>" in html
        assert "<script>evil()</script>" not in html

    def test_slot_body_onclick_stripped(self):
        html = self._render(
            "---\nslot: L | H | <a href=\"#\" onclick=\"steal()\">click</a>\n---\nx\n"
        )
        assert "onclick" not in html
        assert ">click</a>" in html

    def test_slot_label_escaped(self):
        html = self._render("---\nslot: <b>x</b> | H | body\n---\nx\n")
        assert '<span class="n">&lt;b&gt;x&lt;/b&gt;</span>' in html

    def test_lede_style_overlay_properties_stripped(self):
        # An injected position:fixed overlay (clickjacking) must be stripped
        # from the hero exactly as the body path strips it -- the hero's nh3
        # pass shares the KaTeX style-property allowlist.
        md = (
            "---\n"
            'lede: <span style="position:fixed;top:0;left:0;width:100vw;'
            'height:100vh;background:#000;z-index:9999">GOTCHA</span>\n'
            "---\nbody\n"
        )
        body = self._render(md).split("</head>", 1)[1]
        assert "position" not in body
        assert "z-index" not in body
        assert "background" not in body
        # The label text itself survives; only the dangerous style is gone.
        assert ">GOTCHA</span>" in body
