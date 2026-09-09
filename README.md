# mdtohtml

A self-contained command-line tool that converts Obsidian-compatible Markdown
into styled, standalone HTML.

[![build](https://github.com/MatLomax/mdtohtml/actions/workflows/build.yml/badge.svg)](https://github.com/MatLomax/mdtohtml/actions/workflows/build.yml)
[![test](https://github.com/MatLomax/mdtohtml/actions/workflows/test.yml/badge.svg)](https://github.com/MatLomax/mdtohtml/actions/workflows/test.yml)

## Features

- **Single self-contained binary.** No server, no API, no network call, and
  no Node.js or Python required at runtime once built.
- **Obsidian-compatible Markdown**: callouts (`> [!note]`), wikilinks
  (`[[Page]]`, resolved to the `.html` sibling of each page), task lists,
  tables, footnotes, syntax highlighting, `~~del~~`, `==mark==`, and an
  optional table-of-contents sidebar.
- **Themeable** via drop-in CSS files — add a theme without rebuilding
  anything.
- **Client-side math.** A bundled KaTeX (fonts inlined as base64 data URIs)
  is injected only when a document actually contains math, so a math-free
  document ships zero KaTeX bytes.
- **Single-file output.** Each converted document is one portable,
  self-contained HTML file.

## Install

**Download a release.** Grab the zip for your platform from the
[Releases](https://github.com/MatLomax/mdtohtml/releases) page and extract
it as-is — the executable and its `themes/` folder must sit side by side:

```
/somewhere/
  mdtohtml
  themes/
    default.css
    dark.css
    print.css
```

Running the bare executable with no `themes/` folder next to it (or an empty
one) fails with a clear error instead of converting anything.

**Or build from source** — see [Building binaries](#building-binaries)
below.

## Usage

```bash
# Convert one file to stdout
mdtohtml notes.md > notes.html

# Convert to a specific file
mdtohtml notes.md -o notes.html

# Convert several files into a directory (one .html per input)
mdtohtml *.md -o out/

# Pick a theme and add a table-of-contents sidebar
mdtohtml notes.md --theme dark --toc -o notes.html

# Drop callouts of a given type
mdtohtml notes.md --ignore "info,tip" -o notes.html

# Point at a themes folder kept elsewhere
mdtohtml notes.md --themes-dir /path/to/themes -o notes.html
```

Run `mdtohtml --help` for the full flag list.

## Themes

Themes are plain CSS files. To add or customize one, drop a `.css` file into
the `themes/` folder next to the binary:

```
/somewhere/
  mdtohtml
  themes/
    default.css
    dark.css
    print.css
    mytheme.css
```

Then `mdtohtml notes.md --theme mytheme -o out.html` uses it — no rebuild
needed. A `--themes-dir` flag can also point at a themes folder kept
elsewhere.

## Math

Math is written as standard LaTeX delimiters (`$inline$` and `$$display$$`)
and typeset client-side by a bundled [KaTeX](https://katex.org/), with fonts
inlined as base64 data URIs. The KaTeX assets are only injected into the
output `<head>` when a document actually contains math, so a document
without math carries zero KaTeX bytes.

KaTeX is MIT-licensed (Copyright (c) 2013-2020 Khan Academy and other
contributors); its license ships in `mdtohtml/katex/LICENSE`.

## How it works

1. Markdown (with Obsidian callouts and wikilinks preprocessed) is converted
   to HTML via `markdown` + `pymdown-extensions`.
2. The output is sanitized with [`nh3`](https://github.com/messense/nh3).
3. The sanitized body is wrapped in an HTML template with the chosen theme's
   CSS inlined, plus the KaTeX assets when the document contains math.

No `weasyprint`, no headless browser, no PDF path — HTML is the only output
format.

## Known limitations

- **Nested callouts** (`> > [!warning]` inside another callout) and lazy
  (unindented) callout continuation lines are not converted; use a single
  level of `> [!type]` blocks.

## Development

```bash
python -m venv .venv
.venv/bin/pip install -e '.[build]'
.venv/bin/python -m pytest -q
```

## Regenerating KaTeX assets

The vendored KaTeX bundle under `mdtohtml/katex/` is checked in, so most contributors
never need to touch this. To regenerate it (e.g. to bump the KaTeX version):

```bash
npm install
python scripts/build_katex_assets.py
```

`npm`/Node.js is used **only** to fetch the `katex` package as a source for
this script — it is not required to build, test, or run `mdtohtml` itself.
The script reads `node_modules/katex/dist`, inlines its fonts as base64 data
URIs into `katex.min.css`, and writes the result into `mdtohtml/katex/`.

## Building binaries

The build produces a single self-contained executable (no Python required to
run it). PyInstaller is the only extra build dependency.

```bash
pip install -e '.[build]'
scripts/build_binary.sh
```

`scripts/build_binary.sh` wipes `build/` and `dist/`, runs PyInstaller against
`mdtohtml.spec` (onefile), and then assembles the release zip that ships to
users: `dist/mdtohtml-linux-x86_64.zip` (or `dist/mdtohtml-windows-x86_64.zip`
on Windows), containing the executable and a `themes/` folder side by side.
Theme CSS is **not** baked into the executable — only KaTeX's rendering
assets are — so the `themes/` folder must travel with the binary.

The Linux binary is dynamically linked against the glibc of the machine that
built it, so it runs on that glibc version or newer. It does not run on musl
systems (e.g. Alpine). To target older distros, build inside a manylinux
container; for musl, build on the target musl system.

Cross-compilation is not possible with PyInstaller, so the Windows binary is
built on Windows. `.github/workflows/build.yml` builds and smoke-tests the
binary on both `ubuntu-latest` and `windows-latest` and uploads the zipped
binary + `themes/` as an artifact for each.

## License

[MIT](LICENSE) (c) Mathieu Lomax
