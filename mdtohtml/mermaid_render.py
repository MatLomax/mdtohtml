"""Server-side Mermaid diagram rendering for mdtohtml.

Pre-renders ```mermaid``` fenced code blocks to static, inline SVG at convert
time so the published HTML carries zero runtime JavaScript and makes no network
request. Rendering runs fully in-process via ``mermaidx`` (embedded QuickJS +
mermaid.js + resvg + bundled font metrics); no Node, browser, or network is
involved.

The rendered SVG is trusted renderer output, not arbitrary user HTML: mermaid.js
runs with ``securityLevel="strict"`` and native ``<text>`` labels
(``htmlLabels=False``), so an author's diagram source is the only user input and
every label is escaped into ``<text>``/``<tspan>`` content. The SVG carries a
load-bearing ``<style>`` blob that must survive into the final document intact,
so it is injected AFTER the main ``nh3.clean`` pass via a placeholder registry
(see :func:`format_mermaid_fence` / :func:`restore_mermaid`), mirroring the
code-block protection in :mod:`mdtohtml.converter`.

On any render failure the block degrades gracefully to the original source
re-emitted as a fenced code block plus a visible note; rendering never raises to
the caller.
"""

from __future__ import annotations

import html as _html
import re
import secrets
import threading

import mermaidx

from . import colour

# ── Mermaid Configuration ──

# Forwarded to mermaid.js ``initialize``. ``strict`` security sanitises every
# label into escaped text; ``htmlLabels: false`` keeps mermaid emitting native
# ``<text>`` labels so no ``<foreignObject>``/HTML leaks into the SVG. The label
# size is set here, below mermaid's 16px default, rather than by scaling the
# rendered SVG, so mermaid lays every box out around the smaller text.
# Sequence, gantt and pie diagrams size their text independently of this
# setting (the bundled mermaid ignores even sequence's own font-size options),
# so they keep mermaid's sizes.
_MERMAID_FONT_SIZE = "14px"
_MERMAID_CONFIG = {
    "securityLevel": "strict",
    "flowchart": {"htmlLabels": False},
    "themeVariables": {"fontSize": _MERMAID_FONT_SIZE},
}

# Theme names passed to ``mermaidx.render``. Both themes emit a transparent SVG
# canvas (mermaid paints no opaque full-canvas rect), so the diagram sits on the
# page background; the dark theme only swaps text/line colours to light tones so
# it reads on a dark page.
_THEME_DARK = "dark"
_THEME_LIGHT = "default"

# ``aria-roledescription`` values (set by mermaid on the SVG root) for the
# diagram families the report theme styles explicitly. Structural diagrams are
# recoloured to the theme palette; categorical pie/gantt keep their own hues and
# are darkened in dark mode. Any other family gets neither class, so an untested
# diagram type keeps mermaid's own colours rather than being mis-recoloured.
_STRUCTURAL_ROLES = frozenset({
    "flowchart-v2",
    "flowchart",
    "sequence",
    "stateDiagram",
    "stateDiagram-v2",
    "class",
    "classDiagram",
    "er",
})
_CATEGORICAL_ROLES = frozenset({"pie", "gantt"})


# ── Frontmatter Title → Card Header ──

# A leading mermaid YAML frontmatter block: ``---`` on its own line, YAML body,
# then a closing ``---`` line, then the diagram. Mermaid draws a ``title:`` field
# as a small caption inside the SVG; this theme instead lifts the title out into
# a styled ``.mermaid-header`` bar on the card, so the title line is extracted and
# removed before the source reaches mermaid.
_FRONTMATTER_RE = re.compile(r"\A\s*---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n(.*)\Z", re.S)

# A top-level ``title:`` line within the frontmatter body. Anchored at column 0
# so a ``title:`` nested under another key (e.g. inside a ``config:`` mapping) is
# left alone -- mermaid's caption title is always a top-level key. Value is
# everything after the colon; quotes are stripped separately.
_TITLE_LINE_RE = re.compile(r"\Atitle[ \t]*:[ \t]*(.*?)[ \t]*\Z")


def _extract_mermaid_title(source: str) -> tuple[str | None, str]:
    """Split a mermaid ``title:`` frontmatter field off the diagram *source*.

    Returns ``(title, source_without_title)``. When the source carries a leading
    YAML frontmatter block with a ``title:`` line, the title (dequoted) is
    returned and that line is removed from the source so mermaid does not also
    draw its own in-canvas caption; any other frontmatter keys are preserved, and
    the frontmatter block is dropped entirely when title was its only key. When
    there is no frontmatter or no title, ``(None, source)`` is returned unchanged.
    """
    m = _FRONTMATTER_RE.match(source)
    if not m:
        return None, source

    yaml_body, diagram = m.group(1), m.group(2)
    title: str | None = None
    kept: list[str] = []
    for line in yaml_body.split("\n"):
        tm = _TITLE_LINE_RE.match(line)
        if tm is not None and title is None:
            raw = tm.group(1).strip()
            if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("\"", "'"):
                raw = raw[1:-1]
            raw = raw.strip()
            if raw:
                title = raw
                continue  # drop the title line from the frontmatter
        kept.append(line)

    if title is None:
        return None, source

    remaining = "\n".join(kept).strip()
    if remaining:
        new_source = f"---\n{remaining}\n---\n{diagram}"
    else:
        new_source = diagram
    return title, new_source


def _header_html(title: str) -> str:
    """Build the ``.mermaid-header`` bar for a diagram *title*.

    A ``left | right`` title splits on the first ``|`` into a left-aligned label
    and a right-aligned meta note; a plain title renders as a single left label.
    The title is author-controlled diagram source injected as trusted output
    (post-``nh3.clean``), so each part is HTML-escaped here.
    """
    left, sep, right = title.partition("|")
    left, right = left.strip(), right.strip()
    if sep and left and right:
        return (
            '<div class="mermaid-header">'
            f'<span class="mh-left">{_html.escape(left, quote=False)}</span>'
            f'<span class="mh-right">{_html.escape(right, quote=False)}</span>'
            "</div>"
        )
    # A missing side (a leading or trailing ``|``) collapses to a single label,
    # so a stray pipe never renders an empty span.
    single = left or right
    return (
        '<div class="mermaid-header">'
        f'<span class="mh-left">{_html.escape(single, quote=False)}</span>'
        "</div>"
    )


# ── SVG Rendering ──


# A ``fill``/``stroke`` declaration whose value is a hex colour, carrying
# ``!important``. Matches ``fill:`` / ``stroke:`` but not ``stroke-width`` or
# ``stroke-dasharray`` (the colon does not sit right after ``stroke``), and only
# hex values, so ``transparent`` / ``none`` / ``url(...)`` fills are left alone.
_HEX_COLOUR_IMPORTANT = re.compile(
    r"(?<![\w-])(fill|stroke)(\s*:\s*#[0-9A-Fa-f]{3,8})\s*!\s*important"
)


def _soften_structural_colours(svg: str) -> str:
    """Drop ``!important`` from mermaid's baked hex ``fill``/``stroke`` colours.

    mermaid emits its palette in an id-scoped ``<style>`` block, and pins some
    colours with ``!important`` -- e.g. ``#gd4 .composition{stroke:#333!important}``
    for class-diagram relation markers and ``#gd5 .marker{stroke:#333!important}``
    for ER crow's-feet. An id selector outranks the theme's class-scoped
    ``.mermaid-structural`` overrides, so on a dark card those markers would keep
    mermaid's grey and be near-invisible. Removing ``!important`` from mermaid's
    *hex-coloured* ``fill``/``stroke`` declarations lets the theme's ``!important``
    overrides win regardless of specificity, while ``fill:transparent`` /
    ``fill:none`` keep theirs -- so hollow arrowheads (aggregation, extension, ER)
    stay hollow. Non-colour properties (``stroke-width``, ``stroke-dasharray``)
    are untouched. Applied only to structural diagrams, which the theme fully
    recolours; categorical/other diagrams keep every ``!important`` so their own
    data-carrying palette is preserved.
    """
    return re.sub(
        r"<style>(.*?)</style>",
        lambda m: "<style>" + _HEX_COLOUR_IMPORTANT.sub(r"\1\2", m.group(1)) + "</style>",
        svg,
        flags=re.S,
    )


# The SVG root id (``gd1``, ``gd2``, ...) mermaid stamps per diagram. It is
# unique within a page, so custom-property definitions scoped to it never leak
# between diagrams.
_SVG_ID_RE = re.compile(r'<svg[^>]*\bid="([^"]+)"')

# A ``classDef`` shape rule in mermaid's ``<style>`` block, e.g.
# ``#gd1 .good rect{fill:#dcecda!important;stroke:#2e7d32!important;color:#1b5e20!important;}``.
# The ``!important`` marks it as an author classDef (mermaid's own defaults are
# not ``!important``), so this signature isolates author colours from the base
# palette. Five identical rules (rect/polygon/ellipse/circle/path) exist per
# class; they dedupe naturally into the same colour sets.
_CLASSDEF_SHAPE_TMPL = (
    r"#{id}\s+\.[\w-]+\s+(?:rect|polygon|ellipse|circle|path)\s*\{{([^}}]*)\}}"
)
_CLASSDEF_TSPAN_TMPL = r"#{id}\s+\.[\w-]+\s+tspan\s*\{{([^}}]*)\}}"
_DECL_FILL_RE = re.compile(r"(?<![\w-])fill\s*:\s*(#[0-9A-Fa-f]{3,8})")
_DECL_STROKE_RE = re.compile(r"(?<![\w-])stroke\s*:\s*(#[0-9A-Fa-f]{3,8})")
_DECL_COLOR_RE = re.compile(r"(?<![\w-])color\s*:\s*(#[0-9A-Fa-f]{3,8})")

# Minimum WCAG contrast a retuned label must keep against its retuned node fill.
_LABEL_CONTRAST_AA = 4.5


# Node shapes a classDef fill/stroke lands on, and label elements a classDef
# text colour lands on. The element decides an ambiguous ``fill`` declaration's
# role: on a shape it is a surface (fill), on a label it is ink (text).
_SHAPE_ELEMS = ("rect", "polygon", "ellipse", "circle", "path")
_LABEL_ELEMS = ("text", "tspan", "g")
_INLINE_STYLE_TMPL = r'(<(?:{elems})\b[^>]*?\bstyle=")([^"]*)(")'


def _retune_classdef_for_dark(svg: str) -> str:
    """Give a diagram's ``classDef`` colours a dark-mode variant, hue preserved.

    An author's ``classDef fill:#dcecda`` bakes into the SVG as an inline
    ``!important`` colour that no theme stylesheet can override, so on a dark page
    a pale ``fill`` keeps its light tone while the theme lightens the label -- pale
    text on a pale tile, unreadable. This routes each classDef colour through a
    per-diagram CSS custom property whose light value is the author's own colour
    (so light mode is byte-for-byte unchanged) and whose ``@media (prefers-color-
    scheme: dark)`` value is a retuned tone: the *same hue*, with lightness and
    saturation moved into a dark-friendly band -- fills become dark tiles, labels
    light ink, borders visible mid-tones -- then WCAG-checked so each label clears
    AA against its tile.

    Variables are keyed by ``(role, colour)``, not colour alone, so a single
    colour used as both a fill and a label (or as a fill in one class and ink in
    another) gets an independent tile and ink variant -- otherwise they would
    collapse to one value and the contrast guarantee would break. Replacement is
    scoped to classDef ``<style>`` rules and node/label elements (never a blanket
    value swap), so a colour an author happens to share with a mermaid marker is
    left alone. The properties are scoped to the SVG's unique root id, so diagrams
    never bleed into one another. A diagram with no classDef colours is returned
    unchanged.
    """
    id_match = _SVG_ID_RE.search(svg)
    style_match = re.search(r"<style>(.*?)</style>", svg, re.S)
    if not id_match or not style_match:
        return svg
    svg_id = id_match.group(1)
    style = style_match.group(1)

    shape_re = re.compile(_CLASSDEF_SHAPE_TMPL.format(id=re.escape(svg_id)))
    tspan_re = re.compile(_CLASSDEF_TSPAN_TMPL.format(id=re.escape(svg_id)))

    # (role, hex) keys collected from the authoritative classDef <style> rules.
    keys: set[tuple[str, str]] = set()
    # (fill_hex, text_hex) pairs per classDef, for the WCAG label-on-tile check.
    pairs: list[tuple[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()

    for match in shape_re.finditer(style):
        body = match.group(1)
        if "!important" not in body:  # skip mermaid's own (non-classDef) defaults
            continue
        f = _DECL_FILL_RE.search(body)
        s = _DECL_STROKE_RE.search(body)
        t = _DECL_COLOR_RE.search(body)
        fh = f.group(1).lower() if f else None
        sh = s.group(1).lower() if s else None
        th = t.group(1).lower() if t else None
        if fh:
            keys.add((colour.ROLE_FILL, fh))
        if sh:
            keys.add((colour.ROLE_STROKE, sh))
        if th:
            keys.add((colour.ROLE_TEXT, th))
        if fh and th and (fh, th) not in seen_pairs:
            seen_pairs.add((fh, th))
            pairs.append((fh, th))
    for match in tspan_re.finditer(style):
        body = match.group(1)
        if "!important" not in body:
            continue
        t = _DECL_FILL_RE.search(body)
        if t:
            keys.add((colour.ROLE_TEXT, t.group(1).lower()))

    if not keys:
        return svg

    dark = {key: colour.dark_variant(key[1], key[0]) for key in keys}

    # Keep each label legible on its own tile; if the same ink pairs with several
    # tiles, take the lightest lift any of them demands.
    for fill_hex, text_hex in pairs:
        fk = (colour.ROLE_FILL, fill_hex)
        tk = (colour.ROLE_TEXT, text_hex)
        if fk not in dark or tk not in dark:
            continue
        lifted = colour.lighten_to_contrast(dark[tk], dark[fk], _LABEL_CONTRAST_AA)
        cur = colour.parse_hex(dark[tk])
        new = colour.parse_hex(lifted)
        if new and cur and colour.relative_luminance(new) > colour.relative_luminance(cur):
            dark[tk] = lifted

    ordered = sorted(keys)
    varname = {key: f"--m{i}" for i, key in enumerate(ordered)}
    # Light value is the author's own colour (light mode unchanged); dark value is
    # the retuned tone. A colour shared across roles yields several variables that
    # all carry the same light value but diverge in dark.
    light_defs = "".join(f"{varname[k]}:{k[1]};" for k in ordered)
    dark_defs = "".join(f"{varname[k]}:{dark[k]};" for k in ordered)
    inject = (
        f"#{svg_id}{{{light_defs}}}"
        f"@media (prefers-color-scheme:dark){{#{svg_id}{{{dark_defs}}}}}"
    )

    def _sub_decls(body: str, fill_role: str) -> str:
        """Rewrite classDef colour declarations in *body* to ``var()`` refs.

        ``color``/``stroke`` carry their role in the property name; an ambiguous
        ``fill`` takes *fill_role* (a surface on a shape, ink on a label).
        """

        def repl(role: str, prop: str, m: "re.Match[str]") -> str:
            key = (role, m.group(1).lower())
            return f"{prop}:var({varname[key]})" if key in varname else m.group(0)

        body = _DECL_COLOR_RE.sub(lambda m: repl(colour.ROLE_TEXT, "color", m), body)
        body = _DECL_STROKE_RE.sub(
            lambda m: repl(colour.ROLE_STROKE, "stroke", m), body
        )
        body = _DECL_FILL_RE.sub(lambda m: repl(fill_role, "fill", m), body)
        return body

    def _rewrite_rule(fill_role: str, m: "re.Match[str]") -> str:
        rule_body = m.group(1)
        if "!important" not in rule_body:  # only author classDef rules
            return m.group(0)
        return m.group(0).replace(rule_body, _sub_decls(rule_body, fill_role), 1)

    # Rewrite the <style> block's classDef rules (shape fills, tspan ink).
    style = shape_re.sub(lambda m: _rewrite_rule(colour.ROLE_FILL, m), style)
    style = tspan_re.sub(lambda m: _rewrite_rule(colour.ROLE_TEXT, m), style)
    svg = svg.replace(
        style_match.group(0), "<style>" + inject + style + "</style>", 1
    )

    # Rewrite inline styles, letting the element decide an ambiguous ``fill``.
    shape_inline = re.compile(_INLINE_STYLE_TMPL.format(elems="|".join(_SHAPE_ELEMS)))
    label_inline = re.compile(_INLINE_STYLE_TMPL.format(elems="|".join(_LABEL_ELEMS)))
    svg = shape_inline.sub(
        lambda m: m.group(1) + _sub_decls(m.group(2), colour.ROLE_FILL) + m.group(3),
        svg,
    )
    svg = label_inline.sub(
        lambda m: m.group(1) + _sub_decls(m.group(2), colour.ROLE_TEXT) + m.group(3),
        svg,
    )
    return svg


# A ``classDef`` statement: ``classDef name[,name...] styles``, at the start of
# a line or after a ``;`` statement separator. Each name the author defines is
# reported on the diagram wrapper so a theme's built-in semantic class of the
# same name (``success``, ``danger``, ...) steps aside.
_CLASSDEF_STMT_RE = re.compile(r"(?:^|;)[ \t]*classDef[ \t]+([\w,-]+)", re.M)

# The semantic class names themes colour (see the themes' ``mermaid-semantic``
# section).
SEMANTIC_CLASSES = ("success", "warning", "danger", "info", "accent", "muted")


def _own_classes(source: str) -> list[str]:
    """Return the class names the diagram *source* defines with ``classDef``.

    Sorted and de-duplicated so the wrapper attribute is stable. ``default`` is
    mermaid's restyle-every-node hook, not a class an author puts on a node, so
    it is kept like any other name (a theme simply never keys on it).
    """
    names: set[str] = set()
    for match in _CLASSDEF_STMT_RE.finditer(source):
        names.update(n for n in match.group(1).split(",") if n)
    return sorted(names)


def _narrow_default_classdef(svg: str, own: list[str]) -> str:
    """Keep an author ``classDef default`` off semantic-classed elements.

    Mermaid tags every node ``default`` and emits ``classDef default`` as
    id-scoped rules (``#gd1 .default rect{...}``) that outrank any theme rule, so
    a ``:::success`` node would keep the default look while taking the theme's
    semantic label colour. In mermaid an explicitly assigned class beats
    ``default``; this restores that for the semantic classes the author has not
    redefined, by narrowing each ``.default`` selector with
    ``:not(.success,...)``. Returns *svg* unchanged when there is nothing to do.
    """
    semantic = [name for name in SEMANTIC_CLASSES if name not in own]
    if "default" not in own or not semantic:
        return svg
    narrowed = ".default:not(" + ",".join("." + n for n in semantic) + ")"

    def _style(m: "re.Match[str]") -> str:
        body = re.sub(r"(#[\w-]+\s+)\.default(?![\w-])", r"\1" + narrowed, m.group(1))
        return "<style>" + body + "</style>"

    return re.sub(r"<style>(.*?)</style>", _style, svg, flags=re.S)


# A ``style <id> ...`` statement: a per-element style the author set by hand,
# which keeps priority over the theme's semantic colours.
_STYLE_STMT_RE = re.compile(r"(?:^|;)[ \t]*style[ \t]+([\w-]+)", re.M)

# A full ``classDef name[,name...] decls`` statement: the names and the
# declarations mermaid applies (and, for ``default``, inlines on every element).
_CLASSDEF_FULL_RE = re.compile(r"(?:^|;)[ \t]*classDef[ \t]+([\w,-]+)[ \t]+([^;\n]+)", re.M)

# The opening tag of a node/cluster group carrying classes and an id, and the
# element name inside that id: ``gd1-flowchart-A-0`` / ``gd2-state-Idle-1`` /
# ``gd3-classId-Foo-0`` for nodes, ``gd1-S1`` for a subgraph.
_GROUP_OPEN_RE = re.compile(r'<g class="([^"]*)"([^>]*?)\bid="([^"]*)"([^>]*)>')
_ELEMENT_ID_RE = re.compile(r"^gd\d+-(?:(?:flowchart|state|classId)-(.+)-\d+|(.+))$")
_GROUP_KINDS = frozenset({"node", "cluster", "statediagram-cluster"})
_STYLED_TAG_RE = re.compile(r'<(\w+)([^>]*?)(\s+style=")([^"]*)(")')

# Class a semantic-classed element gets when a ``style`` statement targets it;
# the themes' semantic rules skip it, so the hand-set style stands entirely.
OWN_STYLE_CLASS = "own-style"


def _group_end(svg: str, start: int) -> int:
    """Return the index just past the ``</g>`` closing the ``<g>`` at *start*."""
    depth = 0
    for m in re.finditer(r"<g\b|</g>", svg[start:]):
        depth += 1 if m.group(0) == "<g" else -1
        if depth == 0:
            return start + m.end()
    return len(svg)


def _classdef_props(source: str) -> dict[str, set[str]]:
    """Map each ``classDef`` name in *source* to the CSS properties it sets."""
    props: dict[str, set[str]] = {}
    for names, decls in _CLASSDEF_FULL_RE.findall(source):
        keys = {d.partition(":")[0].strip().lower() for d in decls.split(",") if ":" in d}
        for name in filter(None, names.split(",")):
            props.setdefault(name, set()).update(keys)
    return props


def _drop_default_decls(tag: str, style: str, default: set[str], kept_props: set[str]) -> str:
    """Remove the declarations ``classDef default`` supplied from an inline *style*.

    Mermaid merges every class on an element property by property into one
    inline ``!important`` style, a later class replacing the default's value. So
    such a declaration came from the default exactly when the default sets that
    property and none of the element's other classes (*kept_props*) does. On
    label ``<text>`` the inline ``fill`` is mermaid's rendering of ``color``.
    """
    kept = []
    for decl in style.split(";"):
        prop = decl.partition(":")[0].strip().lower()
        if not prop:
            continue
        if "!important" not in decl:
            # Mermaid's own inline styling (e.g. a label background's
            # ``stroke: none``), not a class it inlined.
            kept.append(decl.strip())
            continue
        source_prop = "color" if tag == "text" and prop == "fill" else prop
        if source_prop in default and source_prop not in kept_props:
            continue
        kept.append(decl.strip())
    return ";".join(kept)


def _resolve_semantic_groups(svg: str, source: str, own: list[str]) -> str:
    """Settle author styling against the themes' semantic colours, per element.

    For each node/subgraph/composite state carrying a semantic class the author
    has not redefined with ``classDef``:

    * one a ``style`` statement targets gets the :data:`OWN_STYLE_CLASS`, so the
      theme leaves it entirely to the hand-set style;
    * otherwise, if the author has a ``classDef default``, the default's inlined
      declarations are removed from it -- mermaid inlines ``classDef default``
      on every element as ``!important`` styles no stylesheet can beat, while in
      mermaid an explicitly assigned class wins over ``default``. A property any
      other class on the element sets is kept (see :func:`_drop_default_decls`).

    The element's name is read exactly from its id, so ``style A`` never matches
    a node ``AB-A``. Runs on the raw render, before any colour rewriting.
    """
    semantic = {name for name in SEMANTIC_CLASSES if name not in own}
    if not semantic:
        return svg
    styled = set(_STYLE_STMT_RE.findall(source))
    classdefs = _classdef_props(source)
    default = classdefs.get("default", set())
    if not styled and not default:
        return svg

    out: list[str] = []
    pos = 0
    for m in _GROUP_OPEN_RE.finditer(svg):
        if m.start() < pos:
            continue  # inside a group already rewritten
        classes = m.group(1).split()
        if not (_GROUP_KINDS.intersection(classes) and semantic.intersection(classes)):
            continue
        ident = _ELEMENT_ID_RE.match(m.group(3))
        name = (ident.group(1) or ident.group(2)) if ident else None
        if name in styled:
            out.append(svg[pos : m.start()])
            out.append(
                f'<g class="{m.group(1).rstrip()} {OWN_STYLE_CLASS}"'
                f'{m.group(2)}id="{m.group(3)}"{m.group(4)}>'
            )
            pos = m.end()
        elif default:
            kept_props: set[str] = set()
            for cls in classes:
                if cls != "default":
                    kept_props |= classdefs.get(cls, set())

            def _restyle(sm: "re.Match[str]") -> str:
                kept = _drop_default_decls(sm.group(1), sm.group(4), default, kept_props)
                attr = f"{sm.group(3)}{kept}{sm.group(5)}" if kept else ""
                return f"<{sm.group(1)}{sm.group(2)}{attr}"

            end = _group_end(svg, m.start())
            out.append(svg[pos : m.start()])
            out.append(_STYLED_TAG_RE.sub(_restyle, svg[m.start() : end]))
            pos = end
    out.append(svg[pos:])
    return "".join(out)


def _diagram_class(svg: str) -> str:
    """Return the extra wrapper class for *svg*, keyed on its diagram family.

    Reads the SVG root's ``aria-roledescription`` and maps it to
    ``mermaid-structural`` (recoloured to the theme palette) or
    ``mermaid-categorical`` (pie/gantt: own hues, darkened in dark mode). Any
    other or missing role returns ``""`` so the diagram keeps mermaid's own
    colours untouched.
    """
    match = re.search(r'aria-roledescription="([^"]*)"', svg)
    role = match.group(1) if match else ""
    if role in _STRUCTURAL_ROLES:
        return " mermaid-structural"
    if role in _CATEGORICAL_ROLES:
        return " mermaid-categorical"
    return ""


def render_mermaid(source: str, *, dark: bool = False, adaptive: bool = False) -> str:
    """Render Mermaid *source* to embed-ready inline HTML.

    On success returns the inline ``<svg>...</svg>`` produced by mermaid.js (with
    its load-bearing ``<style>`` blob intact) wrapped in a
    ``<div class="mermaid-diagram">`` frame themes can style. On ANY render error
    returns a graceful-degrade fragment: the original source re-emitted as a
    fenced code block plus a visible note. This function never raises to the
    caller.

    Args:
        source: The raw Mermaid diagram source (the fenced block body).
        dark: When true, render with the ``dark`` mermaid theme (light text for a
            dark page); otherwise the ``default`` theme. Both yield a transparent
            canvas.
        adaptive: When true, the target theme adapts to ``prefers-color-scheme``,
            so a structural diagram's author ``classDef`` colours are given a
            hue-preserving dark-mode variant (see
            :func:`_retune_classdef_for_dark`). Only meaningful for a
            light-rendered, auto light/dark theme (the ``report`` theme).

    Returns:
        A trusted HTML fragment ready to embed in the document body.
    """
    theme = _THEME_DARK if dark else _THEME_LIGHT
    # Lift a ``title:`` frontmatter field into a card header, rendering the source
    # without it so mermaid does not also draw its own in-canvas caption. On a
    # render failure the ORIGINAL source (frontmatter intact) is shown so the
    # author sees exactly what they wrote.
    title, render_source = _extract_mermaid_title(source)
    try:
        diagram = mermaidx.render(render_source, theme=theme, config=_MERMAID_CONFIG)
        svg = diagram.svg()
    except Exception as exc:  # noqa: BLE001 - any renderer failure degrades
        return _degrade_fragment(source, exc)

    if "<svg" not in svg:
        return _degrade_fragment(source, RuntimeError("renderer produced no SVG"))

    # Wrap the diagram in a framing div so themes can border/scroll it and it is
    # distinguishable from the inline ``<svg>`` KaTeX draws for radicals. A
    # family class (structural/categorical) lets the theme recolour or darken it.
    # The wrapper is trusted, post-``nh3.clean`` output alongside the SVG it holds.
    cls = _diagram_class(svg)
    # Author ``classDef`` names, so a theme's semantic colours of the same name
    # defer to the author's own definition; then settle ``style`` statements and
    # ``classDef default`` against the semantic classes, on the raw colours.
    own = _own_classes(render_source)
    svg = _resolve_semantic_groups(svg, render_source, own)
    if cls == " mermaid-structural":
        # On an auto light/dark theme, give author classDef colours a dark-mode
        # variant before softening so the retune reads the ``!important`` markers.
        if adaptive:
            svg = _retune_classdef_for_dark(svg)
        # Let the theme's recolour reach mermaid's id-scoped ``!important`` markers.
        svg = _soften_structural_colours(svg)
    header = _header_html(title) if title else ""
    svg = _narrow_default_classdef(svg, own)
    own_attr = f' data-own-classes="{_html.escape(" ".join(own))}"' if own else ""
    return f'<div class="mermaid-diagram{cls}"{own_attr}>{header}{svg}</div>'


def _degrade_fragment(source: str, error: BaseException) -> str:
    """Build the graceful-degrade fragment for a diagram that failed to render.

    The original *source* is HTML-escaped and re-emitted as a fenced code block
    so the document stays valid and the author can see what did not render. The
    fragment is injected as trusted output (post-``nh3.clean``), so it escapes
    the source itself rather than relying on the sanitiser.
    """
    escaped = _html.escape(source, quote=False)
    reason = _html.escape(str(error), quote=False)
    return (
        '<div class="mermaid-error">\n'
        '<p class="mermaid-error-note">Mermaid diagram could not be rendered.</p>\n'
        f'<pre><code class="language-mermaid">{escaped}</code></pre>\n'
        f"<!-- mermaid render error: {reason} -->\n"
        "</div>"
    )


# ── Per-Conversion Placeholder Registry ──

# A superfences ``format`` callback cannot receive per-conversion state (the dark
# flag) or reach back into the pipeline, and its returned SVG would be stripped
# by the main ``nh3.clean`` pass (nh3 drops ``<style>`` element content and would
# reject much of the SVG). So each conversion keeps thread-local state: the dark
# flag plus a registry mapping a collision-proof placeholder id to the rendered
# HTML. The formatter stashes the HTML and returns an empty ``<div>`` anchored by
# that id; the converter swaps each placeholder for its HTML AFTER sanitisation.
#
# Thread-local isolation makes concurrent conversions on different threads safe;
# a fresh nonce per conversion means stale entries from an earlier conversion on
# the same thread can never be mistaken for the current one.

_state = threading.local()


def _ctx() -> threading.local:
    """Return the current thread's conversion context, initialising if needed."""
    if not getattr(_state, "ready", False):
        begin_conversion(dark=False)
    return _state


def begin_conversion(*, dark: bool, adaptive: bool = False) -> None:
    """Start a fresh Mermaid rendering context for one document conversion.

    Resets the placeholder registry, records the *dark* and *adaptive* flags for
    the formatter, and generates a per-conversion nonce so placeholder ids are
    unique to this conversion. ``adaptive`` is set for an auto light/dark theme
    (the ``report`` theme), enabling the classDef dark-mode retune. Called once by
    the converter before markdown conversion runs.
    """
    _state.dark = dark
    _state.adaptive = adaptive
    _state.registry = {}
    _state.nonce = secrets.token_hex(8)
    _state.counter = 0
    _state.ready = True


def end_conversion() -> None:
    """Clear the current thread's Mermaid context after a conversion completes."""
    _state.dark = False
    _state.adaptive = False
    _state.registry = {}
    _state.nonce = ""
    _state.counter = 0
    _state.ready = False


# The placeholder is an empty block-level ``<div>`` carrying only the id nonce.
# It starts with a block tag so Python-Markdown does not wrap it in ``<p>`` (a
# ``<pre>``/``<div>`` degrade fragment would be invalid inside ``<p>``), and its
# ``div``/``id`` survive ``nh3.clean``. The id is matched back out by regex, so
# nh3 attribute reordering/normalisation does not matter.
_PLACEHOLDER_ID = "mermaid-ph-{nonce}-{index}"


def _placeholder_html(placeholder_id: str) -> str:
    """Return the empty anchor ``<div>`` emitted in place of a diagram."""
    return f'<div class="mermaid-placeholder" id="{placeholder_id}"></div>'


def format_mermaid_fence(
    source: str,
    language: str,
    class_name: str,
    options: dict,
    md: object,
    **kwargs: object,
) -> str:
    """Superfences ``custom_fences`` ``format`` callback for ```mermaid``` blocks.

    Matches the callback signature invoked by ``pymdownx.superfences``
    (``format(source, language, class_name, options, md, **kwargs)``). Renders
    the diagram with the current conversion's dark flag, stashes the resulting
    HTML in the thread-local registry, and returns an empty placeholder ``<div>``
    that survives sanitisation and is swapped for the HTML by
    :func:`restore_mermaid` after the main ``nh3.clean`` pass.
    """
    ctx = _ctx()
    placeholder_id = _PLACEHOLDER_ID.format(nonce=ctx.nonce, index=ctx.counter)
    ctx.counter += 1
    ctx.registry[placeholder_id] = render_mermaid(
        source, dark=ctx.dark, adaptive=getattr(ctx, "adaptive", False)
    )
    return _placeholder_html(placeholder_id)


def restore_mermaid(html: str) -> str:
    """Swap Mermaid placeholder ``<div>``s for their rendered HTML.

    Called by the converter AFTER ``nh3.clean`` so the trusted SVG (and its
    ``<style>`` blob) bypasses sanitisation. Each placeholder is located by its
    id, tolerating any attribute reordering nh3 may have applied and any ``<p>``
    the serialiser may have wrapped it in. Returns *html* unchanged when the
    current context registered no diagrams.
    """
    ctx = _ctx()
    if not ctx.registry:
        return html

    for placeholder_id, fragment in ctx.registry.items():
        # Match the placeholder div by its unique id, optionally wrapped in a
        # lone <p>...</p> the raw-HTML serialiser may have added.
        pattern = re.compile(
            r"(?:<p>\s*)?"
            r'<div\b[^>]*\bid="' + re.escape(placeholder_id) + r'"[^>]*>\s*</div>'
            r"(?:\s*</p>)?"
        )
        html = pattern.sub(lambda _m, f=fragment: f, html, count=1)

    return html


# ── Superfences Registration Helper ──


def superfences_config() -> dict:
    """Return the ``custom_fences`` entry registering the ```mermaid``` fence.

    Merge this into the ``pymdownx.superfences`` extension configuration so a
    ```mermaid``` block routes to :func:`format_mermaid_fence` instead of the
    default highlighter.
    """
    return {
        "name": "mermaid",
        "class": "mermaid",
        "format": format_mermaid_fence,
    }
