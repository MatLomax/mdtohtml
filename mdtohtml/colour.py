"""Small, dependency-free colour maths for theme-adaptive rendering.

Provides hex/RGB/HSL conversion, WCAG relative-luminance contrast, and a
hue-preserving :func:`dark_variant` used to retune baked diagram colours for a
dark page. The goal throughout is to keep a colour's *hue* (its semantic
identity -- "this node is the green/good one") while moving lightness and
saturation into a band that reads on a dark background, then validate the result
against WCAG contrast so retuned text stays legible on its retuned fill.
"""

from __future__ import annotations

import colorsys


def _clamp(value: float, low: float, high: float) -> float:
    """Clamp *value* into the inclusive ``[low, high]`` range."""
    return max(low, min(high, value))


def parse_hex(value: str) -> tuple[int, int, int] | None:
    """Parse a ``#rgb`` or ``#rrggbb`` string to an ``(r, g, b)`` 0-255 tuple.

    Returns ``None`` for anything that is not a 3- or 6-digit hex colour (an
    ``#rgba``/``#rrggbbaa`` value, a named colour, ``none``/``transparent``, or
    a malformed string), so callers can leave non-hex values untouched.
    """
    if not value or value[0] != "#":
        return None
    body = value[1:]
    if len(body) == 3:
        body = "".join(ch * 2 for ch in body)
    if len(body) != 6:
        return None
    try:
        return int(body[0:2], 16), int(body[2:4], 16), int(body[4:6], 16)
    except ValueError:
        return None


def to_hex(rgb: tuple[int, int, int]) -> str:
    """Format an ``(r, g, b)`` 0-255 tuple as a ``#rrggbb`` string."""
    r, g, b = (int(round(_clamp(c, 0, 255))) for c in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def _rgb_to_hsl(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    """Convert an ``(r, g, b)`` 0-255 tuple to ``(h, s, l)`` floats in 0..1."""
    r, g, b = (c / 255 for c in rgb)
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    return h, s, l


def _hsl_to_rgb(h: float, s: float, l: float) -> tuple[int, int, int]:
    """Convert ``(h, s, l)`` floats in 0..1 to an ``(r, g, b)`` 0-255 tuple."""
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return int(round(r * 255)), int(round(g * 255)), int(round(b * 255))


def _linear(channel: float) -> float:
    """Linearise one 0-255 sRGB channel for luminance (WCAG 2.x formula)."""
    c = channel / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    """Return the WCAG relative luminance (0..1) of an ``(r, g, b)`` colour."""
    r, g, b = rgb
    return 0.2126 * _linear(r) + 0.7152 * _linear(g) + 0.0722 * _linear(b)


def contrast_ratio(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    """Return the WCAG contrast ratio (1..21) between two ``(r, g, b)`` colours."""
    la, lb = relative_luminance(a), relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


# Roles a baked diagram colour can play, driving how it is retuned for dark mode.
ROLE_FILL = "fill"  # a node/shape surface -> becomes a dark tile
ROLE_STROKE = "stroke"  # a border/edge -> stays a visible mid-light line
ROLE_TEXT = "text"  # a label ink -> becomes a light, legible tone


def dark_variant(value: str, role: str) -> str:
    """Return a dark-mode-friendly variant of hex *value* for its *role*.

    The hue is preserved; only lightness and saturation move, so a green node
    stays green and a red one stays red. A ``fill`` (surface) is pulled down into
    a dark tile band, a ``text`` (label ink) is lifted into a light band so it
    reads on that tile, and a ``stroke`` (border) lands in a visible mid-light
    band. A non-hex value (``none``/``transparent``/``url(...)``) is returned
    unchanged so hollow shapes stay hollow. WCAG pairing is applied separately by
    the caller once each classDef's fill/text variants are known.
    """
    rgb = parse_hex(value)
    if rgb is None:
        return value
    h, s, l = _rgb_to_hsl(rgb)
    if role == ROLE_TEXT:
        # Label ink: ensure it is light, keeping some hue so it reads as coloured.
        new_l = max(l, 0.82)
        new_s = _clamp(s, 0.0, 0.85)
    elif role == ROLE_STROKE:
        # Border: a visible mid-light line whichever way the original leaned.
        new_l = _clamp(l if l >= 0.5 else 1.0 - l * 0.5, 0.52, 0.78)
        new_s = _clamp(s, 0.12, 0.9)
    else:  # ROLE_FILL
        # Surface: a dark tile, lighter originals sitting a touch darker so the
        # set keeps some spread; saturation eased so tiles are tinted, not neon.
        new_l = _clamp(0.17 + (1.0 - l) * 0.12, 0.15, 0.30)
        new_s = _clamp(s * 0.7 + 0.05, 0.08, 0.5)
    return to_hex(_hsl_to_rgb(h, new_s, new_l))


def lighten_to_contrast(
    value: str, background: str, target: float, *, ceiling: float = 0.96
) -> str:
    """Lighten hex *value* until it clears *target* contrast on *background*.

    Raises the colour's lightness in small steps (hue and saturation held) until
    the WCAG contrast ratio against *background* reaches *target* or the
    lightness hits *ceiling*. Returns *value* unchanged when it is not hex or
    already clears the target.
    """
    fg = parse_hex(value)
    bg = parse_hex(background)
    if fg is None or bg is None or contrast_ratio(fg, bg) >= target:
        return value
    h, s, l = _rgb_to_hsl(fg)
    while l < ceiling:
        l = min(ceiling, l + 0.04)
        candidate = _hsl_to_rgb(h, s, l)
        if contrast_ratio(candidate, bg) >= target:
            return to_hex(candidate)
    return to_hex(_hsl_to_rgb(h, s, ceiling))
