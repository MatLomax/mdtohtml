"""Tests for the small colour-maths module."""

from __future__ import annotations

import colorsys

import pytest

from mdtohtml import colour


def _hue(hex_value: str) -> float:
    r, g, b = colour.parse_hex(hex_value)
    return colorsys.rgb_to_hls(r / 255, g / 255, b / 255)[0]


class TestParseHex:
    def test_six_digit(self) -> None:
        assert colour.parse_hex("#aabbcc") == (170, 187, 204)

    def test_three_digit_expands(self) -> None:
        assert colour.parse_hex("#abc") == (170, 187, 204)

    def test_uppercase(self) -> None:
        assert colour.parse_hex("#AABBCC") == (170, 187, 204)

    @pytest.mark.parametrize(
        "value", ["", "red", "none", "transparent", "#12", "#abcd", "#12345g", "aabbcc"]
    )
    def test_non_hex_returns_none(self, value: str) -> None:
        assert colour.parse_hex(value) is None


class TestToHex:
    def test_roundtrip(self) -> None:
        assert colour.to_hex((170, 187, 204)) == "#aabbcc"

    def test_clamps_out_of_range(self) -> None:
        assert colour.to_hex((-5, 999, 128)) == "#00ff80"


class TestLuminanceAndContrast:
    def test_black_and_white_luminance(self) -> None:
        assert colour.relative_luminance((0, 0, 0)) == pytest.approx(0.0)
        assert colour.relative_luminance((255, 255, 255)) == pytest.approx(1.0)

    def test_white_on_black_is_max_contrast(self) -> None:
        assert colour.contrast_ratio((255, 255, 255), (0, 0, 0)) == pytest.approx(21.0)

    def test_contrast_is_symmetric(self) -> None:
        a, b = (30, 60, 90), (200, 210, 220)
        assert colour.contrast_ratio(a, b) == colour.contrast_ratio(b, a)


class TestDarkVariant:
    def test_light_fill_becomes_darker_tile(self) -> None:
        # A pale surface must drop in luminance so it reads as a dark tile.
        original = colour.parse_hex("#dcecda")
        variant = colour.parse_hex(colour.dark_variant("#dcecda", colour.ROLE_FILL))
        assert colour.relative_luminance(variant) < colour.relative_luminance(original)

    def test_dark_text_becomes_lighter_ink(self) -> None:
        original = colour.parse_hex("#1b5e20")
        variant = colour.parse_hex(colour.dark_variant("#1b5e20", colour.ROLE_TEXT))
        assert colour.relative_luminance(variant) > colour.relative_luminance(original)

    @pytest.mark.parametrize(
        "value,role",
        [
            ("#dcecda", colour.ROLE_FILL),
            ("#1b5e20", colour.ROLE_TEXT),
            ("#2e7d32", colour.ROLE_STROKE),
            ("#c62828", colour.ROLE_STROKE),
        ],
    )
    def test_hue_is_preserved(self, value: str, role: str) -> None:
        # Semantic identity (the hue) must survive the lightness/saturation move.
        assert _hue(colour.dark_variant(value, role)) == pytest.approx(
            _hue(value), abs=0.01
        )

    def test_text_reads_brighter_than_its_border(self) -> None:
        # The label ink must sit brighter than the node's border so the text
        # carries more presence than the outline in dark mode.
        text = colour.parse_hex(colour.dark_variant("#1b5e20", colour.ROLE_TEXT))
        stroke = colour.parse_hex(colour.dark_variant("#2e7d32", colour.ROLE_STROKE))
        assert colour.relative_luminance(text) > colour.relative_luminance(stroke)

    def test_text_brighter_than_border_when_both_start_from_one_colour(self) -> None:
        # Even when the classDef gives text and stroke the same author colour,
        # the retuned ink must out-brighten the retuned border.
        base = "#3d7a3d"
        text = colour.parse_hex(colour.dark_variant(base, colour.ROLE_TEXT))
        stroke = colour.parse_hex(colour.dark_variant(base, colour.ROLE_STROKE))
        assert colour.relative_luminance(text) > colour.relative_luminance(stroke)

    def test_text_brighter_than_border_for_a_low_luminance_ink_hue(self) -> None:
        # A classDef may give ink and border unrelated hues: a deep-blue label
        # (low luminance even when light) against a yellow-green border (high
        # luminance even when mid-dark). HSL lightness would invert here; the
        # luminance bounds must still keep the ink brighter than the border.
        text = colour.parse_hex(colour.dark_variant("#000033", colour.ROLE_TEXT))
        stroke = colour.parse_hex(colour.dark_variant("#333300", colour.ROLE_STROKE))
        assert colour.relative_luminance(text) > colour.relative_luminance(stroke)

    def test_text_brighter_than_border_across_every_hue_pairing(self) -> None:
        # The guarantee is universal: for any independent ink/border author hues,
        # the retuned label out-luminates the retuned border.
        samples = [
            f"#{r:02x}{g:02x}{b:02x}"
            for r in (0, 128, 255)
            for g in (0, 128, 255)
            for b in (0, 128, 255)
        ]
        for ink in samples:
            text_lum = colour.relative_luminance(
                colour.parse_hex(colour.dark_variant(ink, colour.ROLE_TEXT))
            )
            for border in samples:
                stroke_lum = colour.relative_luminance(
                    colour.parse_hex(colour.dark_variant(border, colour.ROLE_STROKE))
                )
                assert text_lum > stroke_lum, (ink, border)

    def test_non_hex_is_unchanged(self) -> None:
        assert colour.dark_variant("none", colour.ROLE_FILL) == "none"
        assert colour.dark_variant("transparent", colour.ROLE_FILL) == "transparent"


class TestLightenToContrast:
    def test_lifts_until_target_met(self) -> None:
        # A mid-dark ink on a dark tile is lifted until it clears AA.
        tile = "#253c22"
        lifted = colour.lighten_to_contrast("#2e7d32", tile, 4.5)
        assert colour.contrast_ratio(
            colour.parse_hex(lifted), colour.parse_hex(tile)
        ) >= 4.5

    def test_already_passing_is_unchanged(self) -> None:
        assert colour.lighten_to_contrast("#ffffff", "#000000", 4.5) == "#ffffff"

    def test_non_hex_is_unchanged(self) -> None:
        assert colour.lighten_to_contrast("none", "#000000", 4.5) == "none"

    def test_hue_preserved_while_lifting(self) -> None:
        lifted = colour.lighten_to_contrast("#2e7d32", "#253c22", 4.5)
        assert _hue(lifted) == pytest.approx(_hue("#2e7d32"), abs=0.01)
