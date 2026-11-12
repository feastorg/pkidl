# Contributing

pkidl is early and its design is still being settled, so an issue that says what you
want to do is the best first step for anything larger than a fix.

## Working on it

```sh
just setup        # install dependencies
just check        # format check, lint and type-check: what CI runs
just test         # pkidl's tests
```

Run `just check && just test` before every commit. pkidl's own tests need no KiCad or
SKiDL. The ones that run Freerouting are skipped where it is not installed, and run in
CI. `spike/` is a separate project with its own `justfile`; its boards need KiCad 10,
SKiDL and Freerouting.

## Conventions

- Commits follow [Conventional Commits](https://www.conventionalcommits.org):
  `type(scope): description`.
- A change a user of the library would notice adds its entry to `CHANGELOG.md`, under
  Unreleased, in the same pull request.
- A change to pkidl is judged across every board and test, not by the one it was made
  for (`corpus/README.md`).
- **A board is written from its circuit and its mechanical requirements, never from a
  reference board's layout.** Reference and corpus boards are compared against, not
  copied from: no extracting or transcribing their copper, positions or vias into a
  board file.
- `src/pkidl` never imports from `spike/`.

## Licences

pkidl is Apache-2.0 and `spike/` is GPL-3.0-or-later; a contribution is made under the
licence of the part it changes. A board from another project keeps its own `LICENSE`
beside it, and only permissively licensed boards are committed.

`AGENTS.md` holds the same rules for coding agents.
