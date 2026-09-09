# Contributing

## Setup

```bash
git clone https://github.com/MatLomax/mdtohtml.git
cd mdtohtml
python -m venv .venv
.venv/bin/pip install -e '.[build]'
```

## Running tests

```bash
.venv/bin/python -m pytest -q
```

All 125 tests should pass before you open a PR.

## Coding notes

- The HTML pipeline stays `weasyprint`-free. This project only ever produces
  HTML — no PDF path, no headless browser, no server. Don't reintroduce a
  PDF/rendering dependency.
- `mdtohtml/converter.py` has no CLI or file-I/O concerns; it's a pure
  markdown-text-in, HTML-string-out library. Keep argument parsing and file
  handling in `mdtohtml/cli.py`.
- Theme CSS lives on disk under `mdtohtml/themes/` and is never baked into the
  PyInstaller binary — only the KaTeX assets are. Keep that split.

## Regenerating KaTeX assets

The vendored bundle under `mdtohtml/katex/` is checked in and rarely needs touching.
To regenerate it (e.g. to bump the KaTeX version), edit the `katex` version
in `package.json`, then:

```bash
npm install
python scripts/build_katex_assets.py
```

npm/Node.js is only ever used to fetch the `katex` package for this one
script; it is not a build or runtime dependency of `mdtohtml` itself.

## Pull requests

- Keep changes focused; unrelated cleanups belong in a separate PR.
- Add or update tests for any behavior change.
- Update `README.md`/`CHANGELOG.md` when user-facing behavior changes.
- Make sure `pytest` is green before requesting review.
