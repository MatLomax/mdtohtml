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


def _pre_resolve_themes_dir(argv: list[str]) -> Path:
    """Resolve the themes directory to build ``--theme`` choices against.

    argparse evaluates a ``choices=`` list when the parser is built, before
    the real parse of ``argv`` runs, so a user-supplied ``--themes-dir`` has
    to be pulled out of *argv* ahead of building the full parser.
    """
    # allow_abbrev=False: otherwise argparse's prefix matching lets a bare
    # "--theme VALUE" on the real CLI be misread here as an abbreviation of
    # "--themes-dir VALUE", since this pre-parser knows only the latter.
    pre = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    pre.add_argument("--themes-dir", type=Path, default=None)
    known, _ = pre.parse_known_args(argv)
    return known.themes_dir if known.themes_dir is not None else default_themes_dir()


def build_parser(themes_dir: Path) -> argparse.ArgumentParser:
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
    parser.add_argument(
        "--theme",
        default="default",
        choices=list_themes(themes_dir),
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
            "Comma-separated list of Obsidian callout types to exclude "
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
    themes_dir = _pre_resolve_themes_dir(argv)

    if not list_themes(themes_dir):
        _error(
            "No themes found. Keep the themes/ folder next to the "
            "executable, or pass --themes-dir."
        )

    parser = build_parser(themes_dir)
    args = parser.parse_args(argv)

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
