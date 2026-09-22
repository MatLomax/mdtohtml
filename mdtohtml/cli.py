"""CLI wrapper for the mdtohtml converter.

Output modes
------------
No -o flag     Write converted HTML to **stdout** (single file only).
               Multiple input files without -o is an error.

-o FILE.html   Write to a specific file (single input only).  Multiple
               inputs with a file output is an error.

-o DIR/        Write to a directory (created if needed).  Each input
               produces ``{stem}.html``.

Output is always HTML; there is no format flag.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import NoReturn

from . import __version__
from .converter import convert, default_themes_dir, list_themes

_HTML_EXTENSIONS = {".html"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert Markdown files to styled HTML.",
        epilog=(
            "With no -o flag, output is written to stdout (single file only). "
            "Use -o to specify an output file or directory."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"mdtohtml {__version__}",
    )
    parser.add_argument(
        "files",
        nargs="+",
        metavar="FILE",
        help="One or more .md files to convert",
    )
    # No eager ``choices=``: that would force theme discovery at parser-build
    # time, which must not happen before ``--version``/``-h`` are handled or
    # before the themes directory has even been resolved. The value is
    # validated against the resolved themes directory after parsing.
    parser.add_argument(
        "--theme",
        default="default",
        help="Theme name (default: default)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help=(
            "Output file or directory.  A path ending in .html is treated "
            "as a file; anything else is treated as a directory.  Omit to "
            "write to stdout (single file only)."
        ),
    )
    parser.add_argument(
        "--ignore",
        default=None,
        help=(
            "Comma-separated list of callout types to exclude "
            'from output (e.g. --ignore="info,tip").'
        ),
    )
    parser.add_argument(
        "--toc",
        action="store_true",
        help="Include a table-of-contents sidebar.",
    )
    parser.add_argument(
        "--themes-dir",
        type=Path,
        default=None,
        help="Directory of theme .css files (default: the resolved themes directory).",
    )
    return parser


def _error(msg: str) -> NoReturn:
    """Print an error message to stderr and exit."""
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(1)


def _log(msg: str) -> None:
    """Print informational output to stderr (never pollutes stdout)."""
    print(msg, file=sys.stderr)


def _offer_theme_download() -> bool:
    """When no themes are present, offer to download them; True if now installed.

    Only meaningful for a frozen release binary using its default themes
    location: a dev/pip install ships its themes with the package, and a custom
    --themes-dir is the user's own to populate (handled by the caller, which
    only calls this for the default location). On an interactive terminal this
    prompts and, on yes, fetches the matching themes asset via the updater. When
    non-interactive it prints the exact command to run and declines, so it never
    blocks a script or downloads without consent.
    """
    from .updater import UpdateError, ensure_themes, is_frozen

    if not is_frozen():
        return False
    if not (sys.stdin.isatty() and sys.stderr.isatty()):
        _log("No themes found. Run `mdtohtml update --themes` to download them.")
        return False
    # Prompt on stderr, not via input()'s stdout prompt: stdout is the HTML data
    # channel (a bare `mdtohtml x.md` writes the document there).
    print("No themes found. Download them for this release now? [y/N] ", file=sys.stderr, end="", flush=True)
    try:
        answer = input()
    except EOFError:
        return False
    if answer.strip().lower() not in {"y", "yes"}:
        return False
    try:
        ensure_themes()
    except UpdateError as exc:
        _log(f"Could not download themes: {exc}")
        return False
    _log("Themes installed.")
    return True


def _is_file_output(path: Path) -> bool:
    """Return True if *path* looks like a file rather than a directory."""
    return path.suffix.lower() in _HTML_EXTENSIONS


def _write_content(content: str, dest: Path) -> None:
    """Write HTML conversion output to *dest*."""
    dest.write_text(content, encoding="utf-8")


def _write_stdout(content: str) -> None:
    """Write HTML conversion output to stdout."""
    sys.stdout.write(content)


# ── Main ──


def main() -> None:
    argv = sys.argv[1:]

    # `mdtohtml update ...` is a subcommand, dispatched before the converter
    # parser so it needs no themes/ and never collides with a Markdown input
    # (a real input must end in .md).
    if argv and argv[0] == "update":
        from .updater import main as update_main

        sys.exit(update_main(argv[1:]))

    # Build and parse first, with no themes involved: ``--version`` and ``-h``
    # resolve here and exit, so neither needs a themes/ directory present.
    parser = build_parser()
    args = parser.parse_args(argv)

    themes_dir = args.themes_dir if args.themes_dir is not None else default_themes_dir()
    available = list_themes(themes_dir)
    if not available:
        # Only the default location is auto-fillable; a custom --themes-dir is
        # the user's to populate. Downloading writes to the default themes dir,
        # so re-resolve it before re-checking.
        if args.themes_dir is None and _offer_theme_download():
            themes_dir = default_themes_dir()
            available = list_themes(themes_dir)
    if not available:
        _error(
            "No themes found. Keep the themes/ folder next to the "
            "executable, or pass --themes-dir."
        )
    if args.theme not in available:
        _error(
            f"Unknown theme '{args.theme}'. Available themes: "
            f"{', '.join(available)}."
        )

    theme: str = args.theme
    output: Path | None = args.output

    # --- Parse --ignore into a set of callout types ---
    ignore_callouts: set[str] | None = None
    if args.ignore:
        ignore_callouts = {t.strip().lower() for t in args.ignore.split(",")}
        ignore_callouts.discard("")

    toc: bool = args.toc

    # --- Validate input files ---
    input_paths: list[Path] = []
    for name in args.files:
        p = Path(name)
        if not p.exists():
            _error(f"File not found: {p}")
        if p.suffix.lower() != ".md":
            _error(f"Not a Markdown file: {p}")
        input_paths.append(p)

    multi = len(input_paths) > 1

    # --- Determine output mode ---
    # Three modes: stdout, single-file, directory.
    write_to_stdout = output is None
    write_to_file = output is not None and _is_file_output(output)
    write_to_dir = output is not None and not _is_file_output(output)

    # Validate combinations
    if write_to_stdout and multi:
        _error("Multiple input files require -o (stdout only supports a single file).")

    if write_to_file and multi:
        _error(
            "Multiple input files require a directory output (-o DIR/), "
            "not a single file."
        )

    if write_to_dir:
        if output.exists() and not output.is_dir():
            _error(
                f"Output path exists and is a file, not a directory: {output}"
            )
        output.mkdir(parents=True, exist_ok=True)

    if write_to_file:
        if output.exists() and output.is_dir():
            _error(
                f"Output path exists and is a directory, not a file: {output}"
            )
        output.parent.mkdir(parents=True, exist_ok=True)

    # --- Convert ---
    if write_to_stdout:
        # Single file -> stdout
        md_text = input_paths[0].read_text(encoding="utf-8")
        try:
            content = convert(
                md_text, theme, themes_dir,
                ignore_callouts=ignore_callouts,
                toc=toc,
            )
        except ValueError as exc:
            _error(str(exc))
        except Exception as exc:
            _error(f"Conversion failed for {input_paths[0].name}: {exc}")
        _write_stdout(content)
        return

    if write_to_file:
        # Single file -> specific output file
        md_text = input_paths[0].read_text(encoding="utf-8")
        try:
            content = convert(
                md_text, theme, themes_dir,
                ignore_callouts=ignore_callouts,
                toc=toc,
            )
        except ValueError as exc:
            _error(str(exc))
        except Exception as exc:
            _error(f"Conversion failed for {input_paths[0].name}: {exc}")
        _write_content(content, output)
        _log(f"  {input_paths[0].name}  ->  {output}")
        return

    # --- Directory mode ---
    assert write_to_dir and output is not None

    _log(f"Theme:   {theme}")
    _log(f"Output:  {output}/")
    _log("")

    # In directory/batch mode a single bad file must not abort the whole run:
    # warn, skip it, keep converting the rest, and exit nonzero at the end.
    failures = 0

    for p in input_paths:
        md_text = p.read_text(encoding="utf-8")

        try:
            content = convert(
                md_text, theme, themes_dir,
                ignore_callouts=ignore_callouts,
                toc=toc,
            )
        except Exception as exc:
            _log(f"  WARNING: skipped {p.name}: {exc}")
            failures += 1
            continue

        out_name = f"{p.stem}.html"
        _write_content(content, output / out_name)
        _log(f"  {p.name}  ->  {out_name}")

    _log("")
    if failures:
        _log(f"Done with {failures} failed file(s).")
        sys.exit(1)
    _log("Done.")


if __name__ == "__main__":
    main()
