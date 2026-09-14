# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `mermaid` fenced code blocks are pre-rendered to inline SVG at convert time,
  so diagrams need no runtime JavaScript and no network call. A diagram that
  fails to parse degrades to its source shown as a code block with a note.
- The SIL Open Font License 1.1 covering the bundled KaTeX fonts now ships in
  the bundle (`mdtohtml/katex/OFL.txt`) alongside KaTeX's MIT `LICENSE`.

### Changed

- Math is now pre-rendered to static KaTeX markup at convert time. The output
  carries the KaTeX stylesheet and fonts but no JavaScript engine; math-free
  documents still ship zero KaTeX bytes.

### Removed

- Client-side KaTeX rendering: the in-browser engine, the `auto-render`
  extension, and the auto-render init script no longer ship in the output.

## [0.1.0] - 2026-09-09

Initial release.

### Added

- Markdown-to-HTML conversion with Obsidian-compatible extensions: callouts,
  wikilinks (resolved to `.html` siblings), task lists, tables, footnotes,
  syntax highlighting, `~~del~~`, `==mark==`, and an optional
  table-of-contents sidebar.
- Themeable output via drop-in CSS files (`default`, `dark`, `print` shipped
  in the release zip's `themes/` folder), resolved at runtime with no
  rebuild required to add a theme.
- Client-side KaTeX math rendering, injected only when a document actually
  contains math so math-free output ships zero KaTeX bytes.
- Single self-contained PyInstaller binary for Linux and Windows, with CI
  building, smoke-testing, and packaging release zips for both platforms.

[Unreleased]: https://github.com/MatLomax/mdtohtml/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/MatLomax/mdtohtml/releases/tag/v0.1.0
