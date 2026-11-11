# Roadmap

Where pkidl stands, and the next milestones. The charter (`docs/charter.md`) says why;
the board files (`docs/design/board-files.md`) say what the language should look like.

## Done (2026-11-11)

- Charter and prior-art survey (`docs/charter.md`, `docs/survey/`).
- Library at the root, Apache-2.0; the BREAD boards in `spike/` as an outside user,
  GPL-3.0-or-later; kidl-spike's history carried in, kidl-spike archived.
- Corpus: 15 public boards in five tiers with `circuit.json` and `mechanical.json`
  (`pkidl.importer`) and a reference scorecard (`just corpus`, the Corpus workflow).
- Board files written first for one board per tier; API style decided: a board added
  to with immutable, order-independent statements, no `remove()`, variants as functions.

## Milestone 1: the T0 board end to end

**Done when** `corpus/t0/esp12-breakout_ESP12Breakout/board.py`, as written in the board
files, builds a board that `just corpus` scores: the netlist matches `circuit.json`, 0
unconnected, DRC errors no more than the reference's own, every part placed by a stated
relation, and the board file under 30 lines.

In order; each a PR with its tests:

1. **Footprints for corpus boards.** The corpus uses 84 footprint libraries, mostly
   KiCad 5 names and project-specific ones that KiCad 10 doesn't ship. Proposal: the
   importer also writes each footprint's definition, normalised to library form (origin,
   no rotation, front side), into `corpus/<board>/footprints/`. A footprint is the part's
   package, an input like a library, not layout. **Needs your decision:** it reads the
   reference board for more than the circuit and the outline.
2. **`Board.from_inputs`**: a board from `circuit.json`, `mechanical.json` and those
   footprints; the outline from `mechanical.json`.
3. **Parts, pins and nets as objects**: `board["U1"]`, `board.parts("R1..R5")`,
   `u1.pin_on(net)`, `r.signal_net`, `board.rails(...)`, `board.name_nets(...)`; typed
   selectors with string shorthand.
4. **The intent model**: statements as immutable values recording their source line;
   `board.place`/`board.add` return them; solved together at build; conflicts reported
   with both lines.
5. **Placement v1**: against an edge with inset, between parts, near a pin within a
   distance, grid alignment, facing; parts left free or over-constrained reported.
6. **Part annotations**: the format, and the ESP-12E's antenna area; `keepout(area)`.
7. **Routing in pkidl**: the staged routing in `spike/` (power, signals, crossings,
   planes) moved behind a router interface, Freerouting the first backend.
8. **Build and score**: `board.build(dir)` writes the KiCad files; `just corpus` builds
   every `board.py` and scores it beside its reference.

## Milestone 2: T2, blocks

fan_controller: blocks as functions, rows, decoupling from the circuit. Then the other
T0 and T2 boards.

## Milestone 3: T1, copper for current

OpenMPPT: `path(..., current=)` sizing copper and checking the narrowest neck on the
filled board, loops and areas as objectives, Kelvin sense, heatsinking. This is where
DCMT's copied copper in `spike/` gets replaced by intent.

## Later

T3 (stackup, impedance, differential pairs), T4 (planes, fanout, mechanical standards as
templates), and `spike/`'s boards rewritten in the language.

## Open items

- **KiCad 10 never finishes refilling three corpus references** (OpenMPPT,
  bldc-gimbal-1d, a123 BCM); `just corpus` gives up after 600 s. Cause unknown; worth a
  minimal reproduction before any upstream report.
- **pre-commit is not installed in this clone**: installing a hook repo for the first
  time is a hand step (workstation-configs #609). CI runs the same checks.
- **Whether agents should edit the intent model's data form or the Python**: tested once
  milestone 1's model exists (charter, open questions).
