# Security Policy

## Supported versions

mdtohtml is pre-1.0; only the latest released version receives security fixes.

## Reporting a vulnerability

Please report security issues privately rather than in a public issue.

- Preferred: use GitHub's private vulnerability reporting on this repository — the **Security** tab, then **Report a vulnerability**.
- If that is unavailable, open a GitHub issue that only states you have a security report and asks for a private channel; do not include details in the public issue.

Where possible include steps to reproduce and the Markdown input plus the resulting HTML. Fixes are prioritized by severity.

## Scope

mdtohtml converts untrusted Markdown into self-contained HTML, so the primary security boundary is HTML sanitization. Generated output is cleaned with [nh3](https://github.com/messense/nh3) against an explicit tag and attribute allowlist, and values interpolated outside that pass (the document title, table-of-contents links, and section ids) are HTML-escaped. Markdown input that yields executable or otherwise unsanitized markup in the output is in scope.
