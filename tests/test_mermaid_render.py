"""Tests for server-side Mermaid rendering (:mod:`mdtohtml.mermaid_render`)."""

from __future__ import annotations

import re

import markdown
import nh3
import pytest

from mdtohtml.mermaid_render import (
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
