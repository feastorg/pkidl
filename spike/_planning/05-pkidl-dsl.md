# pkidl as a board-writing language (2026-11-11)

## Why this note

pkidl is meant to be to the PCB what SKiDL is to the schematic: a developer who has
just written a circuit in SKiDL writes its board in a short, readable Python file of
intent, and pkidl makes the copper. Loaf, RLHT and DCMT are test cases for that. A board
counts when reproducing it made pkidl grow a feature a developer would use; a finished
board on its own proves nothing.

Phase 6 lost that. DCMT's power copper is 460 lines of coordinates extracted from the
original board (`dcmt_copper.py`, `scripts/extract_dcmt_copper.py`), placed with
snapping and per-board patches (`BRIDGE_POUR_X_MAX`, body and GND ties, solid pads). The
board is clean (0 DRC errors, 10.2 mm of +12V) and says nothing about pkidl: no pkidl
user would write that file, and no feature came out of it.

The rule from here: **a board file holds what a developer would write by hand,
designing that board for the first time from its SKiDL circuit.** The originals are
compared against, never copied from.

## Where things stand

| Piece | Where | Developer-facing? |
|---|---|---|
| `Board.track/via/zone/keepout`, absolute mm | `pkidl.board` | No: an s-expression writer |
| Footprint placement from a lib + `(x, y, rot, back)` | `pkidl.footprint` | Partly |
| DSN writer, SES reader, Freerouting runner | `pkidl.dsn`, `pkidl.route` | Internals |
| Pour prefill for the router (planes) | `pkidl.fill` | Internals |
| Stitching, silkscreen placement | `pkidl.stitch`, `pkidl.silk` | Partly |
| Staged routing (power, signals, crossings) | `kidl_spike.boards.slice` | Should be pkidl |
| Blocks placed per channel, at an anchor | `kidl_spike.boards.slice_build` | Should be pkidl |
| Track width from current (IPC-2221), mains rules from IEC 60664-1 | `kidl_spike.boards.block_layout` | Should be pkidl: this is intent |
| Copper geometry copied from the originals: `dcmt_copper.py`; by hand, `BODY_GNDPWR`, `OUT_STRIPS`, the thermal via grid, `HS1_VIAS` | `kidl_spike.boards.*` | No |
| Root part positions to the originals' decimals (`Spot(173.3, 136.132769)`) | `rlht_layout`, `dcmt_layout` | No |

Fixed mechanical interfaces are different: Loaf's connector positions, the Slice
format's outline, holes and bus connector, the Nano's USB over the edge. A developer
is given those as requirements and types them in once. They stay, as specs.

## What the board files should look like

Sketches of the target, to steer the API. Names are not settled.

**Loaf** (a backplane: connectors fixed, a bus straight through):

```python
board = pkidl.Board(circuit, outline=rounded_rect(48.3, 77, 169.5, 127, r=2))
board.fix(spec.interface)                       # J1-J7: the mechanical interface
board.bus(circuit.bus, through=["J2", "J3", "J4", "J5", "J6", "J7"], layer="F.Cu")
board.pour("GND", layer="B.Cu")                 # the whole layer
board.pour("+12V", layer="F.Cu")                # whatever the bus leaves
board.write("build/loaf")
```

**A bridge block** (written once, placed per channel):

```python
@pkidl.block
def bridge(b):                                  # b: one bridge subcircuit's parts
    b.U.place(rotation=0)                       # the block's origin
    b.CB1.near(b.U[1], b.U[2])                  # bootstrap caps at their pins
    b.CB2.near(b.U[10], b.U[11])
    b.R.near(b.U[8]); b.CSNS.near(b.U[8])
    b.CBULK.near(b.U[6], b.U[7])
    b.JOUT.at_edge("right"); b.JVDC.at_edge("right")
    b.pour("VS", around=[b.U[6], b.CBULK, b.CVS], current=MOTOR_AMPS)
    b.pour("OUT1", between=(b.U[2], b.JOUT[1]), current=MOTOR_AMPS)
    b.heatsink(b.U, net="GNDPWR")               # pour under the tab + via field, sized
```

**DCMT** (the Slice format, two bridges, a supply path):

```python
board = pkidl.Board(circuit, outline=SLICE_S)
board.fix(J1=SLICE_S.bus_pin1, A1=SLICE_S.nano)
for ch in ("CH1", "CH2"):
    board.place(bridge, circuit.bridges[ch], slot=SLICE_S.channel(ch))
board.pour("+12V", from_="J1", to=["S1.1", "S2.1"], current=2 * MOTOR_AMPS)  # to each bridge's supply switch
board.pour("GNDPWR", layer="B.Cu")
board.route()                                   # power first, then signals, around pours
board.write("build/dcmt")
```

What these need that pkidl lacks:

1. **Blocks**: a layout written once against a subcircuit, placed per instance.
2. **Relative placement**: `near` pins, at an edge, in a slot, resolved without
   overlap. Absolute positions remain for fixed interfaces.
3. **Intent pours**: `around` parts, `between` pins, a whole layer; sized by
   `current` (IPC-2221 width as the pour's narrowest neck), priorities derived.
4. **Heatsinking**: copper under a part's tab and a via field, sized from its
   footprint, not typed in.
5. **Routing as one call**: staged routing, planes and corridors move from
   `kidl_spike.slice` into pkidl.
6. **Checks with the design**: after `write`, the measures we use by hand (DRC, pour
   regions, the narrowest cross-section of a net between two parts) as an API, so a
   `current=` claim is verified on the filled board.

## Order, each with a board as its test

| Step | pkidl feature | Test board | Measured against the original, not copied |
|---|---|---|---|
| 1 | Pours by intent (`layer`, `around`, `between`) and `Board.measure` | Loaf | DRC 0; pour regions; +12V and GND continuity |
| 2 | Blocks and relative placement | RLHT (relay and thermocouple blocks) | netlist; DRC 0; parts on board, no overlap |
| 3 | `current=`: pour necks sized by IPC-2221, checked on the filled board | DCMT +12V | narrowest +12V cross-section, today 10.2 mm from copied copper |
| 4 | Heatsinking | DCMT bridges | GNDPWR area under each LMD18200; via count |
| 5 | Routing as one call | all five | unrouted 0; DRC 0; route time |

Each step replaces copied or transcribed data in a board with pkidl calls, and the board
must still meet the measures. `dcmt_copper.py`, the extractor and the hand-copied
geometry go when step 4 matches them; until then they are the bar to beat.

## Open questions

- **Where the line sits for root placement:** a developer would place the Nano and the
  buck by hand; to the 0.1 mm, not the original's 6 decimals. I'd round those and keep
  them as hand placement.
- **How much of `kidl_spike.boards` becomes pkidl:** blocks, rules and routing stages
  are general; the Slice format and BREAD's blocks stay in kidl_spike, as users of
  pkidl.
- **Whether the public PCBench boards get board files too:** a hand-written pkidl file
  for one or two small external boards would test the language on circuits we didn't
  design. They have no SKiDL circuit, so this needs their netlists read in.
