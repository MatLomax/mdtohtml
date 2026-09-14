"""Tests for the server-side KaTeX renderer and its CSS head assets."""

from __future__ import annotations

from mdtohtml import katex_assets, katex_render


# ── render_math: rendering modes ──


def test_inline_render_contains_katex_class_not_display() -> None:
    """An inline render carries ``class="katex"`` and no ``katex-display``."""
    out = katex_render.render_math("c=\\pm\\sqrt{a^2+b^2}")
    assert 'class="katex"' in out
    assert "katex-display" not in out


def test_display_render_contains_katex_display() -> None:
    """A display render carries the ``katex-display`` block marker."""
    out = katex_render.render_math("c=\\pm\\sqrt{a^2+b^2}", display=True)
    assert "katex-display" in out


# ── render_math: robustness ──


def test_malformed_expression_yields_error_markup_without_raising() -> None:
    """A malformed expression degrades to visible ``katex-error`` markup."""
    out = katex_render.render_math("\\frac{")
    assert "katex-error" in out


def test_unicode_expression_renders() -> None:
    """An expression producing non-ASCII output renders to real markup."""
    out = katex_render.render_math("\\alpha+\\beta \\ge \\sum_{i=1}^{n} x_i")
    assert 'class="katex"' in out
    assert any(ord(ch) > 127 for ch in out)


def test_return_value_is_flattened_str() -> None:
    """The return is a genuine ``str`` (the QuickJS rope was flattened)."""
    out = katex_render.render_math("x^2")
    assert type(out) is str


# ── render_math: singleton reuse ──


def test_singleton_context_reused_across_calls() -> None:
    """The engine context is built once and reused for later renders."""
    katex_render.render_math("x^2")
    first = katex_render._context
    assert first is not None
    katex_render.render_math("y^2")
    assert katex_render._context is first


# ── katex_css_head_assets ──


def test_css_head_assets_has_style_and_no_script() -> None:
    """The CSS head snippet is a ``<style>`` block carrying no ``<script>``."""
    head = katex_assets.katex_css_head_assets()
    assert "<style>" in head
    assert "</style>" in head
    assert "<script" not in head


def test_css_head_assets_credits_both_licenses() -> None:
    """The head notice credits both the MIT code and the SIL OFL fonts."""
    head = katex_assets.katex_css_head_assets()
    assert "MIT" in head
    assert "SIL Open Font License" in head
