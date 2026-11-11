# AGENTS.md

Instructions for agents working in this repository.

## Project

pkidl is a Python library for designing PCBs in code: a DSL for a board's layout and
intent, and a generator that writes KiCad files. Read `docs/charter.md` first; it says
what pkidl is, its four layers, its design principles and the order of work.
`docs/survey/` holds the prior-art survey behind them.

## Layout

```
src/pkidl/       # the library. Imports nothing from spike/.
tests/           # its tests; tests/fixtures/ holds public boards, each with its licence
docs/            # charter and survey
spike/           # the BREAD boards written with pkidl: a separate project, its own
                 # pyproject, justfile, AGENTS.md and GPL-3.0-or-later licence
```

## Commands

```sh
just setup        # install dependencies
just check        # fmt-check + lint + typecheck (CI-equivalent)
just test         # pkidl's tests
```

`spike/` has its own: run `just --list` there. Its boards need KiCad, SKiDL and
Freerouting; pkidl's own tests need none of them.

## Conventions

- Run `just check && just test` before every commit; in `spike/` too when it changes.
- Conventional Commits: `type(scope): description`.
- A change a user of the library would notice adds its entry to `CHANGELOG.md`, under
  Unreleased, in the same PR.
- **A board is written from its circuit and its mechanical requirements, never from a
  reference board's layout.** Reference and corpus boards are compared against, not
  copied from: no extracting or transcribing their copper, positions or vias into a
  board file. Values a designer would type in from requirements (an outline, a fixed
  connector, a hole) are fine. A corpus board's `footprints/` is its parts' packages as
  a footprint library holds them, read from the reference with nothing of where a part
  sits (`corpus/README.md`): an input, like the circuit.
- A change to pkidl is judged across every board and test, not by the one it was made
  for.
- `src/pkidl` never imports from `spike/`; `spike/` uses pkidl's public API as an
  outside project would.
- pkidl is Apache-2.0; `spike/` is GPL-3.0-or-later. A fixture from another project
  keeps its own `LICENSE` beside it; commit only permissively licensed boards.
