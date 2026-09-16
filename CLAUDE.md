# Project rules

## Commit each unit of work as soon as it is complete

Commit every unit of work the moment it is finished — as its own focused,
single-purpose commit — instead of letting changes for several features pile up
in the working tree. A unit is "finished" when it is implemented, its gates and
the full test suite are green, and it has passed the adversarial review the
machine-level definition of done requires. Commit it then, before starting the
next unit.

- **This rule is standing authorization to commit.** Do not wait for a separate
  "commit" instruction for each unit — committing a completed unit is expected
  here. (This overrides the usual "commit only when explicitly asked".)
- **Pushing is NOT covered.** `git push` still requires an explicit request.
- **Never batch unrelated features into one commit**, and never let the tree
  accumulate several finished features that then have to be split apart after the
  fact — committing as you go is precisely how that is avoided.
- Follow the commit-message style in `.git/COMMIT_STYLE.md`, and stage only the
  paths belonging to the unit being committed.

## Record every change in the CHANGELOG before committing

Every commit that changes behaviour, output, or features (or fixes a bug) must
add or update its entry under `[Unreleased]` in `CHANGELOG.md` **in the same
commit** — do not commit a user-facing change without its changelog line.
Purely internal commits with no user-visible effect — these project rules, the
`CHANGELOG.md` file itself, test-only changes, tooling — are exempt.

## Examples: track the sources, regenerate the outputs, never commit the HTML

The `examples/` folder holds each example's Markdown **source** (`*.md`, tracked)
beside its generated HTML **output** (`*.html`, gitignored via `examples/*.html`
and never committed). The rendered HTML is a build artifact, not source.

- **Regenerate every example after any change that affects its output** — an
  example source, the converter, or a theme — so the local outputs never drift.
  Render in place with the CLI, e.g.
  `mdtohtml examples/<name>.md -o examples/ --theme report --toc`, once per source.
- **Commit only the `.md` sources.** The `.html` siblings stay in `examples/`
  locally (open them to preview) but are regenerated, not tracked.

