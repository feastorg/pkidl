# pkidl charter

## The problem

Nearly every layer of a hardware design can be written as code: firmware, mechanical
CAD (build123d, CadQuery), and the schematic (SKiDL). The PCB layout is the exception.
It is still drawn by hand in a GUI and stored as a large file of absolute coordinates.

The reasoning behind a layout is never written down: why this pour is this wide, why
this part sits by that pin, which return path a signal relies on. A KiCad file holds
only the result. So a layout can't be reviewed or diffed as design, reused on the next
board, regenerated when the circuit changes, or checked in CI against what it was meant
to do, the way code can.

## What pkidl is

**A Python library for designing PCBs in code: a DSL for a board's layout and intent, and
a generator that turns it into KiCad files.** A board file says what the designer
means; pkidl makes the geometry; KiCad and pkidl's own measures check that the result
meets what was said.

It is for anyone who would rather design a board in code than draw it: engineers with
families of boards or variants, teams who want hardware reviewed and tested like
software, and programs that generate designs, LLM-based agents included. A program can
write Python; it cannot sensibly produce a board's coordinates. pkidl gives all of them
the same thing: the board as readable, checkable source.

Four layers, each usable on its own and each built on the one below:

1. **Coverage.** Every board object KiCad has, from Python: footprints, tracks, arcs,
   vias (through, blind, buried, micro), zones with every fill option, rule areas,
   graphics, text, dimensions, the stackup, net classes, custom DRC rules, any layer
   count. *If you can do it in KiCad, you can do it in pkidl.* This is also the escape
   hatch: where intent does not reach yet, you drop a level, never hit a wall.
2. **Intent.** Relations and requirements instead of positions:
   - placement: near a pin, aligned, grouped, on an edge, on a side, in a slot;
   - copper: pour a net here, this path carries 6 A, this pair is 90 ohm differential,
     these traces match in length, clearance follows voltage, this return stays unbroken;
   - mechanical: the outline, holes, connectors fixed where an enclosure needs them;
   - blocks: a layout written once against a subcircuit and placed per instance, as a
     SKiDL subcircuit is written once and called per channel.
3. **Solvers.** Placement, routing (Freerouting today, swappable), pour fill,
   stitching: they turn intent into geometry, and each can be overridden by a lower
   layer.
4. **Verification in the language of intent.** KiCad's DRC, plus a measure of every
   stated intent on the real result: "the +12V pour's narrowest neck is 1.4 mm at U1;
   6 A needs 4.2 mm". This closes the loop for whoever writes the board, a person or a
   program: write intent, build, read diagnostics that name intent, revise.

The bar for the language: **simple boards take a few readable lines, as SKiDL
circuits do, and the ceiling is KiCad's.**

**A generator, first.** The code is the source and KiCad files are build output, as a
STEP file is for build123d or Verilog for a Python HDL. A netlist change is a rebuild;
a tweak lives in code. pkidl reads KiCad files to import corpus boards, mechanical
interfaces and footprints, and to bootstrap a board file; editing existing boards in
place, preserving hand edits, waits for a real user who needs it (decided 2026-11-11).

## Design principles

Adopted from reviewing what code-first PCB tooling converges on, and revised by the
prior-art survey (`docs/survey/`):

- **Logical and physical apart.** The circuit (parts, pins, nets) is input, never
  edited by layout; physical objects refer to it by stable IDs, so two netlists diff.
- **Python to write, one model underneath.** Boards are written in Python, not a new
  language: nothing new to learn, no parser to maintain, and all of Python's loops,
  functions and tests (code generators, LLMs among them, also handle it better than a
  new syntax or JSON). The calls register intent in one typed model that serialises to
  canonical data, for plans, diffs and diagnostics; solving and writing KiCad come
  after. Whether the data form is also worth editing directly, by tools that generate
  boards, is decided in step 4.
- **Explicit objects, no ambient state.** Objects combined by functions and operators,
  as in build123d's algebra mode: no implicit stack (CadQuery), no global default board
  (SKiDL), no builder context such as `with Board():`.
- **Everything queryable.** Any object can be measured and located (OpenSCAD's lesson).
- **Units that can't go wrong:** `"0.2mm"`, `"8mil"`, or typed values; integer
  nanometres inside, as KiCad stores them.
- **Typed selectors, strings as sugar:** select by reference, net and pin
  (`on_net("GND")`, `where(value="100nF")`), with `"C1..C4"` shorthand over them.
- **Engines propose, the core applies.** A placer, router or filler returns a change;
  the core checks it, applies or rejects it, and can show it first, as data.
- **Results, not booleans, from every solver.** Routing reports routed, partly routed,
  infeasible or not found; placement names the parts left free and the intents that
  conflict, never choosing silently; errors name pads, nets and distances in board terms
  and point at the line of the board file that made the object.
- **Determinism.** The same input gives the same bytes. Identity comes from the netlist
  and the intent, never from the order code ran in.
- **Numbers first, then pictures.** A build is judged by layer-4 measures; a render after
  every build is for review by eye, which catches only coarse mistakes.
- **Don't rebuild what exists:** KiCad for DRC, fill and fab output, through files and
  `kicad-cli` (the IPC API needs a running GUI until KiCad 11); existing routers behind
  one interface (Freerouting's REST API for structured results); shapely (or Clipper2)
  for geometry.

## What pkidl is not (yet)

- A schematic tool: the circuit comes from SKiDL, or from a netlist.
- A KiCad replacement: KiCad stays the file format, the viewer and the judge.
- A router: it drives routers and gives them intent; it does not compete with them
  unless the corpus shows it must.
- Tied to BREAD: the BREAD boards are users of pkidl, like any other.

## How success is measured

Never by one board, and never by byte-identity with an original. By a **corpus**: public,
permissively licensed boards, in tiers.

| Tier | Boards | What they force pkidl to have |
|---|---|---|
| T0 | simple two-layer: breakouts, LED drivers | coverage, placement, routing end to end |
| T1 | power two-layer: motor drivers, bucks, BMS | intent pours, current sizing, heatsinking |
| T2 | mixed-signal MCU boards | blocks, decoupling placement, ground strategy |
| T3 | USB and other differential pairs | impedance, pairs, length matching |
| T4 | four layers and up, fine pitch, BGA | stackup, fanout, blind and buried vias |

**What a corpus board's pkidl file may use:** its netlist (the circuit, the input a
SKiDL author has), its mechanical requirements (outline, holes, fixed connectors),
typed in as a person would, and its parts' footprints as a footprint library holds them
(decided 2026-11-11: these boards' libraries are not shipped any more, so each footprint
is read out of the board, without where it sits). **Never its layout geometry:** the
original is only compared against.

**The scorecard, per board,** printed by one harness that builds every board:

- the netlist matches; ERC and DRC errors;
- measured against the original: current capacity of power paths, clearances, pour
  continuity, unrouted connections, via count;
- lines of pkidl in the board file (the elegance measure);
- time to build.

A change to pkidl is judged by the whole scorecard, not by the board it was made for.

## How we work

1. This charter.
2. A prior-art survey, in two halves, so pkidl is built on what is known:
   - **PCB tools:** atopile, JITX, tscircuit, pcbflow, KiCad-Autoplace, KiCad's IPC
     API (whether it runs headless in KiCad 10) and pcbnew scripting, Freerouting and
     other routers. What each does, where each stops, what to borrow; and whether
     anyone already verifies layout intent (current, return paths) on the result.
   - **Design languages:** CadQuery against build123d (chaining against explicit
     objects), OpenSCAD, SKiDL, Python-embedded HDLs (Amaranth, Chisel), atopile's
     own language, UI constraint layout (flexbox, Cassowary), Terraform's plan and
     apply. What made each pleasant or painful to write, read and generate.
3. The corpus and the scorecard harness, before more language code.
4. The language designed by writing it first: pkidl files for 5-8 corpus boards across
   the tiers, as we would want to write them, reviewed as the API design.
5. Implementation, layer by layer, judged by the scorecard.

## Where things live

- **`feastorg/pkidl`**: the library, this charter, the corpus, the harness.
- **`spike/`**: our boards (Loaf, RLHT, DCMT, HBTC, TC4) written in pkidl, as an
  outside user's repository of boards would be: it imports pkidl's public API only.
- **`feastorg/kidl-spike`'s history** is carried into pkidl (#2), not lost.

## Open questions

- Whether the intent model's data form is worth editing directly, by tools that
  generate or revise boards, or only the Python. The survey settled the rest (Python to
  write, one serialisable model underneath); step 4 tests this part: the same revision
  made both ways on two or three corpus boards.

Settled since: a corpus board's circuit enters as `circuit.json`, which `pkidl.importer`
reads from the board; and the corpus commits only boards whose source repository carries
a permissive licence, each with its `LICENSE` (`corpus/README.md`).
