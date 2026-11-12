# Security Policy

## Reporting a vulnerability

If you discover a security vulnerability, please report it responsibly.

**Do not open a public issue.**

Instead, use GitHub's private reporting: on the repository's
[Security tab](https://github.com/feastorg/pkidl/security), choose
**Report a vulnerability**. The report is visible only to the maintainers.

Include:

- Description of the vulnerability
- Steps to reproduce
- Impact assessment
- Suggested fix (if any)

## Response timeline

- **Acknowledgment**: within 48 hours
- **Initial assessment**: within 7 days
- **Fix or mitigation**: best effort, targeting 30 days for critical issues

## Supported versions

Nothing is released yet. Fixes land on `main`.

| Version | Supported |
| ------- | --------- |
| `main`  | Yes       |

## Scope

This policy covers the code in this repository. pkidl reads KiCad files and board
files, which are Python and run as written: a board file from someone else is code to
read before it is run. The library starts one other program, the router named in
`$FREEROUTING`; the `justfile` recipes start KiCad through `$KICAD_CLI`.

Dependencies are locked in `uv.lock` and updated by Dependabot.
