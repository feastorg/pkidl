# Roadmap

Where pkidl stands, and the next milestones. The charter (`docs/charter.md`) says why;
the board files (`docs/design/board-files.md`) say what the language should look like.

This file is orientation: what is done, what was decided, and the order of what is
next. The work itself is in the issues, and each milestone below names its own. What
is open and belongs to no milestone is in the issue list, not here.

## Done (2026-11-11)

- Charter and prior-art survey (`docs/charter.md`, `docs/survey/`).
- Library at the root, Apache-2.0; the BREAD boards in `spike/` as an outside user,
  GPL-3.0-or-later; kidl-spike's history carried in, kidl-spike archived.
- Corpus: 15 public boards in five tiers with `circuit.json` and `mechanical.json`
  (`pkidl.importer`) and a reference scorecard (`just corpus`, the Corpus workflow).
- Board files written first for one board per tier; API style decided: a board added
  to with immutable, order-independent statements, no `remove()`, variants as functions.

## Milestone 1: the T0 board end to end

Done 2026-11-11: the eight steps below are merged, and the T0 board file builds a board
with the circuit's netlist, 0 unconnected, 8 DRC errors beside the reference's 8, all
eight parts placed by a stated relation, in 29 lines (`docs/design/board-files.md`, "As
built, the build", has the scorecard rows and what is open).

**Done when** `corpus/t0/esp12-breakout_ESP12Breakout/board.py`, as written in the board
files, builds a board that `just corpus` scores: the netlist matches `circuit.json`, 0
unconnected, DRC errors no more than the reference's own, every part placed by a stated
relation, and the board file under 30 lines.

In order; each a PR with its tests:

1. **Footprints for corpus boards.** The corpus boards name footprints from KiCad 5
   libraries and project-specific ones that KiCad 10 doesn't ship. The importer writes
   each footprint's definition, put back in library form (origin, no rotation, front
   side, no nets or label positions), into `corpus/<tier>/<board>/footprints/`. A
   footprint is the part's package, an input like a library, not layout (decided
   2026-11-11: this reads the reference for more than the circuit and the outline).
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

fan_controller: blocks as functions, rows, decoupling from the circuit. The other T0
and T2 boards follow it, each with its own board file, and are not part of what done
means here.

**Done when** `corpus/t2/fan_controller_fan_controller/board.py` builds a board that
`just corpus` scores: the netlist matches `circuit.json`, 0 unconnected, DRC errors no
more than the reference's own, every one of its 49 parts placed by a stated relation,
and the four fan channels placed by one block function.

How long the board file is goes in the scorecard and is not a bar to pass. A line
that says which capacitor goes to which pin is worth more than its absence, and a
target on length is a reason to leave it out.

Tracked in #8. Steps 1 to 5 are merged, step 6 is #11 and step 7 is #12.
The router is still given the box around the board and not its outline (#13).

In order; each a PR with its tests:

1. **Pin names, said in the board file.** No corpus reference carries pin names
   (`pinfunction` appears in none of the 15), so `circuit.json` has pad numbers only,
   and the board file selects pins by name (`driver.pin("B")`). A footprint does not
   fix them: the drivers are `lib_pcb:SOT-23` with value `Q_NPN_BEC`, and a SOT-23's
   pin order differs by part. So the board file says them (decided 2026-11-11):
   `board.annotate(q, pins={"B": 1, "E": 2, "C": 3})`. The names are that part's alone,
   where an area said the same way is every part's with the footprint: on
   UProgrammer one SOT-23 footprint holds two MOSFETs and two bipolar transistors.
   Shipped names, for a footprint that does fix them, can follow.
2. **Rows**: `row(parts, along=Edge.BOTTOM, pitch="even")`, a statement a block can
   return.
3. **`centre=True`, and one word for two sides.** `side="back"` is the face of the
   board; the fan channel wrote `side=Edge.TOP` for which side of the fan its LED
   sits. `side=` stays the face, and which side of what a part is near is
   `toward=Edge.TOP` (decided 2026-11-11): a relation the solver has to keep, not only
   a word.
4. **What the solver leaves out that this board has**: its four mounting holes kept
   clear of, and its corners, rounded to a 4 mm radius about those holes, where the
   solver takes the board as the box around its outline. A row then spreads over what
   the holes leave clear of an edge (decided 2026-11-11). `near=` solved with
   `against=` or `between=` beside it is the other limit (#14); no line of the sketch
   needs it yet, so it is built when a board file does.
5. **Decoupling from the circuit**: `board.decouple(u1, caps, within=)` puts each
   capacitor by one of the part's pins on the supply it is across, one capacitor to a
   pin (decided 2026-11-12), with ground declared by `board.ground("GND")` (decided
   2026-11-12). The sketch gives U1 three capacitors on +5V (C2, C8, C9), and U1 has
   two +5V pins (13, 28), with U2's output on the same net: the third has no pin and is
   reported. C12 is the one capacitor alone with a pin of U1 (pin 20), and the sketch
   leaves it out.
6. **The whole board file.** The sketch in the board files places 35 of the 49 parts.
   The fifth channel (P1, Q1, R14), the bulk capacitor (C7) and C1, C10..C12, R1..R6
   are not in it, and a build refuses a board with a part nothing places. It also
   says `route()` with no `rules(...)`, which a build refuses as well, and it names
   its inputs by a path where the T0 board file uses `__file__`.
7. **Build and score**: `board.py` committed, held to the text in the board files, and
   its row in the scorecard under its reference.

## Milestone 2b: a board with the library as it stands

Tracked in #23.

Every step of milestones 1 and 2 changed pkidl for the board it was made for. That is
how the language gets built, and it is not evidence that the language carries over.
The evidence is a board written afterwards with nothing added.

Once fan_controller builds, `corpus/t0/qrp_swr_meter_swr_meter_rev_a/board.py` is
written from its circuit and its mechanical inputs with no change under `src/pkidl`:
21 parts, four mounting holes, and an arc bitten out of each corner. It is a different
board from the two that shaped the library, in a tier the library already claims.

**Done when** that board file is committed as far as it can be written, and what it
could not say is listed: each thing the board needed that pkidl did not have, one line
each, with the statement that would have said it, and each filed as an issue. The
count is the measure, and it goes beside the board's row in the scorecard. Nothing on the list is built in that
PR.

What the count means is decided before it is known. None or one: the next board is
written the same way, from the next tier down the list. More than a few of one kind,
as with relations the solver cannot hold together: that kind is the next milestone,
ahead of copper for current.

## Milestone 3: T1, copper for current

OpenMPPT: `path(..., current=)` sizing copper and checking the narrowest neck on the
filled board, loops and areas as objectives, Kelvin sense, heatsinking. This is where
DCMT's copied copper in `spike/` gets replaced by intent.

Tracked in #10, coarse until milestone 2b's count is in. What is already known to be
in the way: a pour is not a statement and the router is not told of it (#19), a board
file has no words for which nets carry power (#20), a pour is filled across a cut-out
and on outer layers only (#21), and there is no way to write a track by hand from a
pin (#22).

## Later

T3 (stackup, impedance, differential pairs), T4 (planes, fanout, mechanical standards as
templates), and `spike/`'s boards rewritten in the language.

## The placement solver

The solver places one part at a time, each after what it is placed by, and goes round
until nothing moves. It reports what it cannot hold together and does not search for
it. Where it has been seen to stop is #9: `near=` solved alone (#14), a placement that
does not settle (#15), a part against an edge centred on the whole edge (#16), an area
of a part placed `near=` something (#17), and 14 s to solve 49 parts (#18). Milestone
2b says how much that costs on a board it was not built for.

## Open, outside the milestones

In the issue list. The ones a milestone will meet:

- KiCad 10 never finishes refilling three corpus references, OpenMPPT among them (#24).
- A routing run says how many connections it left unmade, not which (#25).
- Whether tools should edit the intent model's data form or the Python: the charter's
  open question (#30).
