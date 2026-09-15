"""Leading front-matter reader for the report hero.

A document may open with a ``---`` fenced block carrying the hero content that
does not belong in the body prose: an eyebrow kicker, the title, a lede, and up
to a handful of "slot" cards. The block is parsed here into :class:`FrontMatter`
and stripped from the markdown before conversion; the converter renders the
hero from it and sources the ``<title>`` from ``title:``.

The format is intentionally tiny and dependency-free -- one ``key: value`` per
line, with ``slot:`` repeatable and pipe-delimited into ``label | heading |
body``. No YAML library is bundled; anything richer than this flat shape is out
of scope. Detection is conservative: only a bare ``---``-fenced block of
``key: value`` lines carrying at least one recognised hero key is treated as
front matter, so a document that merely opens with a thematic break (or has no
block at all) is returned unchanged and renders exactly as before.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_FENCE = "---"

# A ``key: value`` line: a word-like key at column 0 followed by a colon. Used
# to tell a real front-matter block from a leading thematic-break section.
_KEY_LINE = re.compile(r"^[A-Za-z][\w-]*\s*:")

# The keys that make a block worth treating as a hero front matter. At least one
# must be present, so an ordinary ``Note:`` line between two ``---`` rules is not
# mistaken for front matter.
_HERO_KEYS = {"title", "eyebrow", "lede", "slot"}


@dataclass
class Slot:
    """One hero "slot" card: a mono label, a heading, and a body line."""

    label: str = ""
    heading: str = ""
    body: str = ""


@dataclass
class FrontMatter:
    """Parsed hero front matter. Empty fields render nothing."""

    title: str = ""
    eyebrow: str = ""
    lede: str = ""
    slots: list[Slot] = field(default_factory=list)

    @property
    def has_hero(self) -> bool:
        """True when there is any hero content worth emitting a ``<header>`` for.

        An empty ``slot:`` line (no label/heading/body) carries nothing to show,
        so a block of only empty slots does not qualify -- it would otherwise
        emit a bare ``<header>`` with an empty card box.
        """
        return bool(
            self.title
            or self.eyebrow
            or self.lede
            or any(s.label or s.heading or s.body for s in self.slots)
        )


def parse_frontmatter(md_text: str) -> tuple[FrontMatter | None, str]:
    """Split leading ``---`` front matter off *md_text*.

    Returns ``(front_matter, body)``, or ``(None, md_text)`` unchanged when the
    text does not begin with a genuine front-matter block. To qualify, the text
    must open with a bare ``---`` line at column 0 (a trailing ``\\r`` from CRLF
    is tolerated), be closed by another bare ``---`` line, and have between them
    at least one non-blank line where *every* non-blank line is a ``key: value``
    line and at least one key is a recognised hero key. This deliberately does
    NOT capture a leading thematic-break section -- a heading, prose, or a
    ``Note:`` line sitting between two ``---`` rules -- so such a document keeps
    rendering exactly as it did before this feature existed.

    Recognised keys: ``title``, ``eyebrow``, ``lede`` (each a single value),
    and ``slot`` (repeatable; split on ``|`` into label / heading / body, with
    any extra ``|`` folded back into the body). The value is everything after
    the first colon, so a colon inside a value (``10:30``) is preserved.
    Unrecognised ``key: value`` lines are ignored, keeping the format
    forward-compatible.
    """
    lines = md_text.split("\n")
    first = lines[0] if lines else ""
    # The opening fence is a bare ``---`` at column 0; an indented ``---`` (a
    # valid thematic break) is not front matter.
    if first.strip() != _FENCE or first[:1].isspace():
        return None, md_text

    close = next(
        (
            i
            for i in range(1, len(lines))
            if lines[i].strip() == _FENCE and not lines[i][:1].isspace()
        ),
        None,
    )
    if close is None:
        return None, md_text

    content = [ln for ln in lines[1:close] if ln.strip()]
    if not content or not all(_KEY_LINE.match(ln) for ln in content):
        return None, md_text
    if not any(ln.partition(":")[0].strip().lower() in _HERO_KEYS for ln in content):
        return None, md_text

    fm = FrontMatter()
    for line in content:
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if key == "title":
            fm.title = value
        elif key == "eyebrow":
            fm.eyebrow = value
        elif key == "lede":
            fm.lede = value
        elif key == "slot":
            parts = [p.strip() for p in value.split("|")]
            label = parts[0] if parts else ""
            heading = parts[1] if len(parts) > 1 else ""
            # Fold any extra pipes back into the body so a body line may itself
            # contain a "|".
            body = " | ".join(parts[2:]) if len(parts) > 2 else ""
            fm.slots.append(Slot(label=label, heading=heading, body=body))

    # Drop the blank line(s) that typically separate the fence from the body so
    # the body starts cleanly at its first real line. ``\r`` is stripped too so a
    # CRLF document does not leave a stray carriage return at the body head.
    body = "\n".join(lines[close + 1 :]).lstrip("\r\n")
    return fm, body
