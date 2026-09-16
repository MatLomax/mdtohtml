"""Tests for server-side Mermaid rendering (:mod:`mdtohtml.mermaid_render`)."""

from __future__ import annotations

import colorsys
import re

import markdown
import nh3
import pytest

from mdtohtml import colour
from mdtohtml.mermaid_render import (
    _extract_mermaid_title,
    _header_html,
    begin_conversion,
    end_conversion,
    format_mermaid_fence,
    render_mermaid,
    restore_mermaid,
    superfences_config,
)

# ── Sample diagram sources ──

FLOWCHART = "graph TD; A-->B; B-->C{decision}; C-->|yes|D; C-->|no|A"
SEQUENCE = (
    "sequenceDiagram\n"
    "    Alice->>John: Hello John, how are you?\n"
    "    John-->>Alice: Great!"
)
CLASS = (
    "classDiagram\n"
    "    Animal <|-- Duck\n"
    "    Animal : +int age\n"
    "    Animal: +isMammal()"
)
# Valid syntax, but the label text contains injection markers.
HOSTILE = (
    'graph TD\n'
    '  A["img onerror=alert(1) and <b>bold</b>"] --> B["plain & ampersand"]\n'
    '  B --> C["&lt;script&gt;alert(1)&lt;/script&gt;"]'
)
MALFORMED = "graph TD; A-->; -->< this is not valid mermaid <<<"


# ── Helpers ──


def _on_attributes(svg: str) -> list[str]:
    """Return any ``on*`` event-handler names that appear as element attributes.

    A literal ``onerror=`` in visible label *text* is not an attribute, so this
    scans only inside start tags.
    """
    hits: list[str] = []
    for tag in re.finditer(r"<[a-zA-Z][^>]*>", svg):
        hits.extend(re.findall(r"\s(on[a-z]+)\s*=", tag.group(0)))
    return hits


# ═══════════════════════════════════════════════════════════════════════
# render_mermaid — success paths
# ═══════════════════════════════════════════════════════════════════════


class TestRenderSuccess:
    def test_flowchart_renders_svg(self) -> None:
        out = render_mermaid(FLOWCHART)
        assert "<svg" in out
        assert "</svg>" in out
        # Load-bearing style blob is present.
        assert "<style" in out

    @pytest.mark.parametrize("source", [FLOWCHART, SEQUENCE, CLASS])
    def test_output_is_free_of_active_content(self, source: str) -> None:
        out = render_mermaid(source)
        low = out.lower()
        assert "<script" not in low
        assert "<foreignobject" not in low
        assert "javascript:" not in low
        assert _on_attributes(out) == []

    def test_style_blob_is_scoped_to_svg_id(self) -> None:
        # Correct appearance depends on the #gdN-scoped style block shipping.
        out = render_mermaid(FLOWCHART)
        svg_id = re.search(r'<svg[^>]*\bid="([^"]+)"', out).group(1)
        assert f"#{svg_id}" in out

    def test_rendered_svg_is_wrapped_in_frame_div(self) -> None:
        # A successful diagram is framed so themes can border/scroll it and it
        # is distinguishable from KaTeX's inline SVGs. The wrapper also carries a
        # diagram-family class the theme keys its recolouring off.
        out = render_mermaid(FLOWCHART)
        assert out.startswith('<div class="mermaid-diagram')
        assert out.endswith("</div>")
        assert "<svg" in out

    def test_flowchart_wrapper_is_tagged_structural(self) -> None:
        out = render_mermaid(FLOWCHART)
        assert 'class="mermaid-diagram mermaid-structural"' in out

    def test_pie_wrapper_is_tagged_categorical(self) -> None:
        out = render_mermaid('pie title P\n  "A" : 5\n  "B" : 3\n')
        assert 'class="mermaid-diagram mermaid-categorical"' in out

    def test_unknown_family_gets_no_extra_class(self) -> None:
        # A diagram family the theme does not special-case keeps mermaid's own
        # colours: the wrapper carries only the base frame class.
        out = render_mermaid("journey\n  title J\n  section S\n  Task: 5: Me\n")
        if "mermaid-error" not in out:  # only if the renderer supports it
            assert 'class="mermaid-diagram"' in out
            assert "mermaid-structural" not in out
            assert "mermaid-categorical" not in out

    def test_degrade_path_is_not_wrapped_in_frame_div(self) -> None:
        # The failure fragment keeps its own ``mermaid-error`` wrapper.
        out = render_mermaid(MALFORMED)
        assert 'class="mermaid-diagram"' not in out
        assert "mermaid-error" in out


# ═══════════════════════════════════════════════════════════════════════
# render_mermaid — theming
# ═══════════════════════════════════════════════════════════════════════


class TestTheming:
    def test_dark_and_light_differ(self) -> None:
        light = render_mermaid(FLOWCHART, dark=False)
        dark = render_mermaid(FLOWCHART, dark=True)
        assert light != dark

    def test_no_opaque_full_canvas_background(self) -> None:
        # Both themes must leave the canvas transparent so the diagram sits on
        # the page background.
        for dark in (False, True):
            out = render_mermaid(FLOWCHART, dark=dark)
            full_canvas = [
                r
                for r in re.findall(r"<rect[^>]*>", out)
                if re.search(r'width="100%"|height="100%"', r)
            ]
            assert full_canvas == []


def _hex_colour_important(svg: str) -> int:
    """Count ``fill``/``stroke`` hex-colour ``!important`` decls in the style blob."""
    style = re.search(r"<style>(.*?)</style>", svg, re.S)
    body = style.group(1) if style else ""
    return len(
        re.findall(
            r"(?<![\w-])(?:fill|stroke)\s*:\s*#[0-9A-Fa-f]{3,8}\s*!important", body
        )
    )


class TestStructuralColourSoftening:
    # mermaid pins some structural colours ``!important`` and id-scoped (e.g.
    # ``#gd4 .composition``), which would outrank the theme's class-scoped
    # recolour and leave relation markers grey/invisible on a dark card. The
    # renderer strips ``!important`` from mermaid's hex ``fill``/``stroke`` for
    # STRUCTURAL diagrams only, so the theme override wins by cascade order.

    RELATIONS = "classDiagram\n A <|-- B\n A *-- C\n A o-- D\n A ..> E"
    ER = "erDiagram\n CUSTOMER ||--o{ ORDER : places"

    def test_structural_hex_colours_are_softened(self) -> None:
        # Class + ER diagrams carry mermaid's id-scoped hex ``!important`` markers.
        assert _hex_colour_important(render_mermaid(self.RELATIONS)) == 0
        assert _hex_colour_important(render_mermaid(self.ER)) == 0

    def test_hollow_arrowheads_keep_their_important(self) -> None:
        # ``fill:transparent`` (aggregation/extension) and ``fill:none`` (ER
        # marker) keep ``!important`` so the theme cannot solidify hollow heads.
        style = re.search(
            r"<style>(.*?)</style>", render_mermaid(self.RELATIONS), re.S
        ).group(1)
        assert re.search(r"fill\s*:\s*transparent\s*!important", style)
        er_style = re.search(
            r"<style>(.*?)</style>", render_mermaid(self.ER), re.S
        ).group(1)
        assert re.search(r"fill\s*:\s*none\s*!important", er_style)

    def test_categorical_palette_is_not_softened(self) -> None:
        # A gantt chart's data-carrying hues stay ``!important`` -- softening is
        # scoped to structural diagrams, so the categorical palette is preserved.
        gantt = "gantt\n title G\n section S\n T:a,2020-01-01,3d"
        assert _hex_colour_important(render_mermaid(gantt)) > 0


# ═══════════════════════════════════════════════════════════════════════
# render_mermaid — dark-mode classDef retune
# ═══════════════════════════════════════════════════════════════════════


CLASSDEF = (
    "graph TD\n"
    "  A[Start] --> B[Good]\n"
    "  A --> C[Bad]\n"
    "  classDef good fill:#dcecda,stroke:#2e7d32,color:#1b5e20\n"
    "  classDef bad fill:#f8d7da,stroke:#c62828,color:#7f1d1d\n"
    "  class B good\n"
    "  class C bad\n"
)


def _var_defs(block: str) -> dict[str, str]:
    """Parse ``--mN:#hex;`` custom-property definitions out of a ``#id{...}`` block."""
    return dict(re.findall(r"(--m\d+):(#[0-9a-fA-F]{6})", block))


def _dark_defs(svg: str) -> dict[str, str]:
    """Return the ``--mN -> #hex`` map from a diagram's dark-mode media block."""
    svg_id = re.search(r'<svg id="([^"]+)"', svg).group(1)
    _light, dark = re.findall(r"#" + re.escape(svg_id) + r"\{(--m0[^}]*)\}", svg)
    return _var_defs(dark)


class TestClassDefDarkRetune:
    # An author's ``classDef fill:#dcecda`` bakes in as an inline ``!important``
    # colour no stylesheet can override, so on a dark page a pale fill keeps its
    # light tone. The adaptive retune routes each classDef colour through a
    # per-diagram custom property: the author's colour in light, a hue-preserving
    # dark-friendly, WCAG-checked tone under ``prefers-color-scheme: dark``.

    def test_no_classdef_diagram_gets_no_injection(self) -> None:
        # With no author classDef colours there is nothing to retune, so the
        # adaptive pass adds no variables and no media query.
        out = render_mermaid(FLOWCHART, adaptive=True)
        assert "var(--m" not in out
        assert "prefers-color-scheme" not in out

    def test_non_adaptive_leaves_classdef_colours_literal(self) -> None:
        out = render_mermaid(CLASSDEF, adaptive=False)
        assert "#dcecda" in out  # author colour stays a literal hex
        assert "var(--m" not in out
        assert "prefers-color-scheme" not in out

    def test_adaptive_routes_colours_through_variables(self) -> None:
        out = render_mermaid(CLASSDEF, adaptive=True)
        # Node fills and label inks now reference custom properties, not literals.
        assert re.search(r'style="fill:var\(--m\d+\) !important', out)
        assert "@media (prefers-color-scheme:dark)" in out

    def test_light_values_are_the_author_colours(self) -> None:
        out = render_mermaid(CLASSDEF, adaptive=True)
        svg_id = re.search(r'<svg id="([^"]+)"', out).group(1)
        light_block = re.search(
            r"#" + re.escape(svg_id) + r"\{(--m0[^}]*)\}", out
        ).group(1)
        light = set(_var_defs(light_block).values())
        # Every author colour appears verbatim as a light value (light unchanged).
        for author in ("#dcecda", "#2e7d32", "#1b5e20", "#f8d7da", "#c62828", "#7f1d1d"):
            assert author in light

    def test_dark_labels_meet_aa_on_their_tiles(self) -> None:
        out = render_mermaid(CLASSDEF, adaptive=True)
        svg_id = re.search(r'<svg id="([^"]+)"', out).group(1)
        light_block, dark_block = re.findall(
            r"#" + re.escape(svg_id) + r"\{(--m0[^}]*)\}", out
        )
        light, dark = _var_defs(light_block), _var_defs(dark_block)
        var_of = {hexval: name for name, hexval in light.items()}
        for fill, text in (("#dcecda", "#1b5e20"), ("#f8d7da", "#7f1d1d")):
            fill_dark = colour.parse_hex(dark[var_of[fill]])
            text_dark = colour.parse_hex(dark[var_of[text]])
            assert colour.contrast_ratio(text_dark, fill_dark) >= 4.5

    def test_dark_fill_preserves_hue(self) -> None:
        out = render_mermaid(CLASSDEF, adaptive=True)
        svg_id = re.search(r'<svg id="([^"]+)"', out).group(1)
        light_block, dark_block = re.findall(
            r"#" + re.escape(svg_id) + r"\{(--m0[^}]*)\}", out
        )
        light, dark = _var_defs(light_block), _var_defs(dark_block)
        for name, author in light.items():
            lh = colorsys.rgb_to_hls(*(c / 255 for c in colour.parse_hex(author)))[0]
            dh = colorsys.rgb_to_hls(*(c / 255 for c in colour.parse_hex(dark[name])))[0]
            assert dh == pytest.approx(lh, abs=0.02)

    def test_multiple_classdef_diagrams_scope_independently(self) -> None:
        # Two classDef diagrams in one page get distinct root ids, so their
        # per-diagram variable definitions never collide.
        begin_conversion(dark=False, adaptive=True)
        try:
            format_mermaid_fence(CLASSDEF, "mermaid", "mermaid", {}, None)
            format_mermaid_fence(CLASSDEF, "mermaid", "mermaid", {}, None)
            from mdtohtml.mermaid_render import _ctx

            svgs = list(_ctx().registry.values())
        finally:
            end_conversion()
        ids = [re.search(r'<svg id="([^"]+)"', s).group(1) for s in svgs]
        assert ids[0] != ids[1]
        for i, svg in enumerate(svgs):
            # Each diagram scopes its own definitions to its own id only.
            assert svg.count("@media (prefers-color-scheme:dark)") == 1
            assert ("#" + ids[1 - i] + "{--m") not in svg

    def test_fill_equal_text_colour_still_meets_aa(self) -> None:
        # A colour used as BOTH fill and text must get independent tile and ink
        # variants -- one shared variable would put the label on an identically
        # coloured tile (contrast 1.0), the exact failure this guards.
        src = (
            "graph TD\n  A[x] --> B[y]\n"
            "  classDef mono fill:#808080,stroke:#808080,color:#808080\n"
            "  class A mono\n  class B mono\n"
        )
        out = render_mermaid(src, adaptive=True)
        dark = _dark_defs(out)
        fill_var = re.search(r'<rect[^>]*style="fill:var\((--m\d+)\)', out).group(1)
        text_var = re.search(r'<text[^>]*style="fill:var\((--m\d+)\)', out).group(1)
        assert fill_var != text_var
        assert (
            colour.contrast_ratio(
                colour.parse_hex(dark[fill_var]), colour.parse_hex(dark[text_var])
            )
            >= 4.5
        )

    def test_cross_role_colour_reuse_keeps_every_label_aa(self) -> None:
        # One colour as ink in class A and fill in class B must not let A's WCAG
        # lift corrupt B's tile: each class keeps an AA-legible label.
        src = (
            "graph TD\n  A[x] --> B[y]\n"
            "  classDef good fill:#aaddaa,stroke:#2e7d32,color:#336633\n"
            "  classDef bad fill:#336633,stroke:#c62828,color:#eeeeee\n"
            "  class A good\n  class B bad\n"
        )
        out = render_mermaid(src, adaptive=True)
        dark = _dark_defs(out)
        nodes = re.findall(
            r'<g class="node[^"]*\b(?:good|bad)\b[^"]*".*?</g>', out, re.S
        )
        assert len(nodes) == 2
        for block in nodes:
            fill_var = re.search(r'<rect[^>]*style="fill:var\((--m\d+)\)', block).group(1)
            text_var = re.search(r'<text[^>]*style="fill:var\((--m\d+)\)', block).group(1)
            assert (
                colour.contrast_ratio(
                    colour.parse_hex(dark[fill_var]), colour.parse_hex(dark[text_var])
                )
                >= 4.5
            )


# ═══════════════════════════════════════════════════════════════════════
# render_mermaid — hostile labels
# ═══════════════════════════════════════════════════════════════════════


class TestHostileLabel:
    def test_hostile_label_produces_no_active_content(self) -> None:
        out = render_mermaid(HOSTILE)
        low = out.lower()
        assert "<svg" in low  # it renders rather than degrading
        assert "<script" not in low
        assert "<foreignobject" not in low
        assert "javascript:" not in low
        assert _on_attributes(out) == []
        # No raw <b> element leaked in from the label.
        assert not re.search(r"<b[\s>]", low)

    def test_hostile_label_is_escaped_into_text(self) -> None:
        # The script-looking label survives only as escaped, inert text.
        out = render_mermaid(HOSTILE)
        assert "&lt;script&gt;" in out
        assert "<script" not in out.lower()


# ═══════════════════════════════════════════════════════════════════════
# render_mermaid — graceful degrade
# ═══════════════════════════════════════════════════════════════════════


class TestDegrade:
    def test_malformed_does_not_raise(self) -> None:
        # Must never raise to the caller.
        out = render_mermaid(MALFORMED)
        assert isinstance(out, str)

    def test_malformed_degrades_to_code_block_and_note(self) -> None:
        out = render_mermaid(MALFORMED)
        assert "<svg" not in out
        assert "mermaid-error" in out
        assert "<pre>" in out
        assert "<code" in out
        assert "could not be rendered" in out.lower()

    def test_degrade_preserves_escaped_source(self) -> None:
        out = render_mermaid(MALFORMED)
        # The original source is preserved with its angle brackets escaped.
        assert "&lt;" in out
        assert "-->&lt;" in out or "&lt;&lt;&lt;" in out


# ═══════════════════════════════════════════════════════════════════════
# Fence formatter + placeholder registry + restore (integration surface)
# ═══════════════════════════════════════════════════════════════════════


def _convert_with_mermaid(doc: str, *, dark: bool) -> str:
    """Mimic the converter wiring: superfences + nh3 + post-nh3 restore."""
    begin_conversion(dark=dark)
    try:
        md = markdown.Markdown(
            extensions=["pymdownx.superfences"],
            extension_configs={
                "pymdownx.superfences": {"custom_fences": [superfences_config()]}
            },
            output_format="html",
        )
        html = md.convert(doc)
        # The main sanitiser: SVG-agnostic allow-list (but class/id allowed on
        # any element, matching the converter's ``"*": {"class", "id"}``), so it
        # WOULD strip the SVG if it were present — proving the placeholder
        # survives and restore runs after it.
        html = nh3.clean(
            html,
            tags={"p", "div", "code", "pre"},
            attributes={"*": {"class", "id"}},
        )
        html = restore_mermaid(html)
    finally:
        end_conversion()
    return html


class TestFenceIntegration:
    def test_formatter_returns_placeholder_not_svg(self) -> None:
        begin_conversion(dark=False)
        try:
            token = format_mermaid_fence(FLOWCHART, "mermaid", "mermaid", {}, None)
            assert "<svg" not in token
            assert 'class="mermaid-placeholder"' in token
        finally:
            end_conversion()

    def test_placeholder_survives_nh3_and_restores_svg(self) -> None:
        doc = f"Intro.\n\n```mermaid\n{FLOWCHART}\n```\n\nOutro."
        html = _convert_with_mermaid(doc, dark=False)
        assert "<svg" in html
        assert "<style" in html  # load-bearing blob survived
        assert "mermaid-placeholder" not in html  # placeholder was consumed
        assert "Intro." in html and "Outro." in html

    def test_multiple_diagrams_in_one_document(self) -> None:
        doc = (
            f"```mermaid\n{FLOWCHART}\n```\n\n"
            f"```mermaid\n{SEQUENCE}\n```\n\n"
            f"```mermaid\n{CLASS}\n```\n"
        )
        html = _convert_with_mermaid(doc, dark=False)
        assert html.count("<svg") == 3
        assert "mermaid-placeholder" not in html
        # Each diagram carries a distinct svg id so their style blobs never clash.
        ids = re.findall(r'<svg[^>]*\bid="([^"]+)"', html)
        assert len(ids) == len(set(ids)) == 3

    def test_dark_flag_threads_to_formatter(self) -> None:
        doc = f"```mermaid\n{FLOWCHART}\n```\n"
        light = _convert_with_mermaid(doc, dark=False)
        dark = _convert_with_mermaid(doc, dark=True)
        assert light != dark

    def test_malformed_fence_degrades_within_document(self) -> None:
        doc = f"```mermaid\n{MALFORMED}\n```\n"
        html = _convert_with_mermaid(doc, dark=False)
        assert "<svg" not in html
        assert "mermaid-error" in html
        assert "could not be rendered" in html.lower()


# ═══════════════════════════════════════════════════════════════════════
# Frontmatter title → card header
# ═══════════════════════════════════════════════════════════════════════


class TestFrontmatterTitle:
    def test_extract_title_only_strips_frontmatter(self) -> None:
        title, src = _extract_mermaid_title(
            "---\ntitle: My Flow\n---\nflowchart TD\n A-->B\n"
        )
        assert title == "My Flow"
        assert src == "flowchart TD\n A-->B\n"

    def test_extract_preserves_other_frontmatter_keys(self) -> None:
        title, src = _extract_mermaid_title(
            "---\nconfig:\n  theme: base\ntitle: Kept\n---\nflowchart TD\n A-->B\n"
        )
        assert title == "Kept"
        assert src.startswith("---\n")
        assert "config:" in src and "theme: base" in src
        assert "title:" not in src
        assert src.rstrip().endswith("A-->B")

    def test_extract_dequotes_title(self) -> None:
        for raw in ('"Hello: World"', "'Hello: World'"):
            title, _ = _extract_mermaid_title(
                f'---\ntitle: {raw}\n---\nflowchart TD\n A-->B\n'
            )
            assert title == "Hello: World"

    def test_no_frontmatter_is_unchanged(self) -> None:
        src_in = "flowchart TD\n A-->B\n"
        title, src = _extract_mermaid_title(src_in)
        assert title is None
        assert src == src_in

    def test_frontmatter_without_title_is_unchanged(self) -> None:
        src_in = "---\nconfig:\n  theme: base\n---\nflowchart TD\n A-->B\n"
        title, src = _extract_mermaid_title(src_in)
        assert title is None
        assert src == src_in

    def test_header_single_title(self) -> None:
        html = _header_html("Just A Title")
        assert '<div class="mermaid-header">' in html
        assert '<span class="mh-left">Just A Title</span>' in html
        assert "mh-right" not in html

    def test_header_split_title_left_right(self) -> None:
        html = _header_html("Overview | v2.1")
        assert '<span class="mh-left">Overview</span>' in html
        assert '<span class="mh-right">v2.1</span>' in html

    def test_header_escapes_html(self) -> None:
        html = _header_html("<script> | <b>x</b>")
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
        assert "&lt;b&gt;x&lt;/b&gt;" in html

    def test_render_lifts_title_into_header_not_canvas(self) -> None:
        out = render_mermaid("---\ntitle: My Flow Title\n---\nflowchart TD\n A-->B\n")
        assert '<div class="mermaid-header">' in out
        assert out.index("mermaid-header") < out.index("<svg")
        # The title appears once (in the header), never as an in-canvas <text>
        # caption (mermaid's ``.flowchartTitleText`` CSS rule may still be present
        # in the style blob, but no <text> element carries the title).
        assert out.count("My Flow Title") == 1
        assert not re.search(r"<text[^>]*>[^<]*My Flow Title", out)

    def test_render_without_title_has_no_header(self) -> None:
        out = render_mermaid("flowchart TD\n A-->B\n")
        assert "mermaid-header" not in out
        assert "<svg" in out

    def test_degrade_shows_original_source_with_frontmatter(self) -> None:
        out = render_mermaid("---\ntitle: Broken\n---\n" + MALFORMED)
        assert "mermaid-error" in out
        # The degrade shows the ORIGINAL source, title line intact for the author.
        assert "title: Broken" in out

    def test_nested_title_is_not_lifted(self) -> None:
        # A ``title:`` indented under another key is not mermaid's caption title,
        # so it is left in place (matched only at column 0).
        src_in = "---\nconfig:\n  title: Nested\n---\nflowchart TD\n A-->B\n"
        title, src = _extract_mermaid_title(src_in)
        assert title is None
        assert src == src_in

    def test_similar_top_level_keys_do_not_match(self) -> None:
        for key in ("subtitle", "x-title"):
            src_in = f"---\n{key}: v\n---\nflowchart TD\n A-->B\n"
            title, src = _extract_mermaid_title(src_in)
            assert title is None
            assert src == src_in

    def test_crlf_frontmatter(self) -> None:
        title, src = _extract_mermaid_title(
            "---\r\ntitle: CRLF\r\n---\r\nflowchart TD\r\n A-->B\r\n"
        )
        assert title == "CRLF"
        assert "title:" not in src

    def test_header_leading_pipe_collapses_to_single(self) -> None:
        assert _header_html("| Right") == (
            '<div class="mermaid-header"><span class="mh-left">Right</span></div>'
        )

    def test_header_trailing_pipe_collapses_to_single(self) -> None:
        assert _header_html("Left |") == (
            '<div class="mermaid-header"><span class="mh-left">Left</span></div>'
        )

    def test_header_splits_on_first_pipe_only(self) -> None:
        html = _header_html("a | b | c")
        assert '<span class="mh-left">a</span>' in html
        assert '<span class="mh-right">b | c</span>' in html

    def test_titled_diagram_header_survives_full_pipeline(self) -> None:
        doc = "```mermaid\n---\ntitle: Pipe Test | v9\n---\nflowchart TD\n A-->B\n```\n"
        html = _convert_with_mermaid(doc, dark=False)
        assert '<div class="mermaid-header">' in html
        assert '<span class="mh-left">Pipe Test</span>' in html
        assert '<span class="mh-right">v9</span>' in html
        assert "<svg" in html
