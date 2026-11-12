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

## Pull requests

1. Branch from `main`.
2. Make the change, with its tests.
3. Run `just check && just test`.
4. Open a pull request against `main`. It is merged by squashing, and its title and
   description become the commit: say what changed and how you know it works.

`main` takes changes only through pull requests, and only once the `ok` check has
passed on a branch that is up to date. On a pull request from a fork, CI runs after a
maintainer has read the change and approved the run, and again after each update.

## Reporting issues

Open an issue with what you expected, what happened, the steps or the board file that
show it, and the versions involved (Python, KiCad, Freerouting). For a security problem,
see [`SECURITY.md`](SECURITY.md) instead.

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
