# Board files, written first

Step 4 of the charter: the pkidl files we would want to write for corpus boards, before
pkidl can run them. They are the API design; reviewing them is reviewing the language.
Each is written from the board's circuit (`circuit.json`), mechanical requirements
(`mechanical.json`), its parts' footprints (`footprints/`) and what its purpose implies,
never from the reference layout.

Status: a sketch for review. Names and signatures are proposals.

## T0: `esp12-breakout_ESP12Breakout`

**What the board is, from its circuit:** an ESP-12E Wi-Fi module (U1); five 10k
resistors strapping its boot pins (R1, R2 pull RST and EN up; R3, R4 pull GPIO0 and
GPIO2 up; R5 pulls GPIO15 down); two 8-pin headers (P1, P2) carrying every module pin
out. A breakout: the headers are what plugs into a breadboard. Board 26.67 x 34.93 mm,
no mounting holes.

```python
"""ESP-12E breakout: the module, its boot straps, and two headers that sit in a
breadboard."""

from pkidl import Board, Edge, inch, mm

board = Board.from_inputs(__file__)  # the circuit, outline, holes and footprints beside it
board.rails("VCC", "GND")

u1, p1, p2 = board.parts("U1", "P1", "P2")
straps = board.parts("R1..R5")

# The headers plug into a breadboard: one down each long edge, their rows 0.9 inch
# apart on the 1.05 inch board, an exact number of 0.1-inch grid steps.
board.place(p1, against=Edge.LEFT, inset=0.075 * inch)
board.place(p2, against=Edge.RIGHT, inset=0.075 * inch)
board.align(p1, p2, grid=0.1 * inch)

# The module between them, its antenna end on the top edge with no copper under it.
board.place(u1, between=(p1, p2), against=Edge.TOP, facing=Edge.TOP)
board.keepout(u1.area("antenna"), copper=True, both_sides=True)

# Each strap sits by the module pin it biases, on the back: the module and the headers
# fill the front.
for r in straps:
    board.place(r, near=u1.pin_on(r.signal_net), within=3 * mm, side="back")

board.rules(track=0.25 * mm, clearance=0.2 * mm)
board.pour("GND", layer="B.Cu")
board.route()
```

Under thirty lines, blank ones counted; no coordinates except the outline's (from
`mechanical.json`) and the two insets.

**What it needs from pkidl:**

| Line | Feature | Exists today |
|---|---|---|
| `Board.from_inputs` | load `circuit.json` + `mechanical.json`; footprints by name from `footprints/` | yes: the outline drawn, the holes placed, the parts loaded and waiting for placement; takes the directory or a file in it (`__file__`) |
| `board.parts("R1..R5")` | typed part handles, range selectors | yes (`pkidl.circuit`): references, runs, `on_net(...)`, `where(value=...)` |
| `place(against=Edge.LEFT, inset=)` | placement relative to the outline | yes (`pkidl.placement`): `board.solve()` works out a pose for each part, and `board.build()` puts it there |
| `align(p1, p2, grid=)` | grid alignment across parts | yes: checked, and reported when it does not hold |
| `place(between=, against=, facing=)` | relative placement, orientation by intent | yes |
| `u1.area("antenna")` | named regions on a footprint | yes (`pkidl.annotations`): shipped for the ESP-12E, or said in the board file with `board.annotate` |
| `keepout(area, copper=True)` | an area kept clear | yes: placement keeps other parts out of it and says where it is, the build draws it as a rule area on each face it holds on, and the router is told to keep out of it |
| `u1.pin_on(net)`, `r.signal_net` | pins and nets as objects; "the net that isn't a rail" | yes, with `board.rails(...)` declared first |
| `place(near=, within=)` | proximity placement | yes: the nearest clear place, looked for in 0.1 mm steps |
| `3 * mm`, `0.1 * inch` | lengths with their unit | yes (`pkidl.units`); the calls that draw copper directly still take millimetres as numbers |
| `board.rules(...)` | design rules from intent | yes: a statement, said once; the build writes them into the project and routes to them |
| `board.pour("GND", layer=)` | whole-layer pour | yes (`Board.pour`) |
| `board.route()` | staged routing | yes: a statement; the build has a router (`pkidl.route.Freerouting` unless given another) route the board in stages (`pkidl.routing`) |
| the build and the scorecard | KiCad files, refill, DRC, measures | yes: `board.build(dir)` writes the board and its project; `just corpus` builds each `board.py`, has KiCad refill and check it, and scores it under its reference |

**Design questions it raises:**

1. **Where a footprint's meaning lives.** "Antenna, keep copper out" is not in KiCad's
   ESP-12E footprint. Options: a small pkidl annotation per footprint (`antenna` region,
   `tab`, `pin 1 side`), shipped for common parts and declared in the board file
   otherwise; or the keepout written in the board file in footprint coordinates. The
   first scales; the second is honest about what is known.
2. **`r.signal_net`.** "The net that isn't VCC or GND" reads well, but depends on knowing
   which nets are rails. Declared (`board.rails("VCC", "GND")`), or inferred from net
   names and fan-out? Declaring is predictable; inferring is shorter.
3. **How much placement is solved, and how much stated.** Here every part is placed by a
   relation. The solver has to report when relations conflict or leave a part free
   (charter: results, not booleans). For larger boards: are unplaced parts an error, or
   left to an autoplacer?
4. **Mutation vs values.** `board.place(...)` changes the board object. Explicit, not
   ambient; but should placement return a value instead (`board = board.place(...)`)?
   Mutation on an explicit object reads like SKiDL and stays simple; the model underneath
   records each call either way.
5. **Units.** `0.25 * mm` against `"0.25mm"`: both, with typed quantities underneath?

**Decided (2026-11-11):** footprint meaning lives in pkidl part annotations (shipped for
common parts, declarable in a board file); rails are declared (`board.rails(...)`); the
API style is the working choice below, to be confirmed by the comparison that follows.

**As built:** `board.rails(...)` and `board.name_nets(...)` give back the nets they were
given, not the board, and a named net keeps the circuit's name in the KiCad files, so
the netlist still matches. Rails are declared before `signal_net` is read: a rail
declared afterwards is refused, since the answer already given would no longer hold.
A pin is found by number (`fan.pin(4)`), or by a name the board file gave it
(`driver.pin("B")`, below), since no corpus reference carries pin names.

**As built, statements** (`pkidl.intent`): `place(...)` and `align(...)` make a
statement and move nothing; `board.place`, `board.align` and `board.add` add it to a
board and give it back. A statement is a value: two that say the same thing are equal
wherever they were written, and saying one twice says it once. Each records the line of
the board file that made it, the line inside a block function when a block made it.
`board.statements(about=part)` reads back what has been said, and `statement.data()` is
the same plain data however it was written (`{"place": "P1", "against": "left",
"inset": 1905000}`).

What one statement alone can say about a part is said once: its inset from an edge, the
edge it faces, its distance from a pin. Two statements that give one of these
differently are a conflict, reported with both lines and neither winning: `P1: inset
from the left edge is 1.905 mm (board.py:33) and 2.54 mm (board.py:40)`. An inset left
out and an inset given are also two answers. Against the left edge and against the top
edge is a corner, not a conflict. `board.conflicts()` finds these before anything is
solved, in an order that does not depend on the order the statements were added. Whether
the statements can all hold on the board at once (a part between two others and against
an edge, parts on a grid) is geometry, and is the placement solver's to report.

**As built, placement** (`pkidl.placement`): `board.solve()` reads the statements and
gives a `Solution`: a pose for each part it could place (`poses`), the parts nothing
places (`free`), each statement it could not make hold with the line that made it
(`problems`), and what it settled where the board file left it open (`chosen`). It
moves nothing, and never drops a statement to make the others fit; putting the poses on
the board is the build's.

- `against=` an edge: the part lies along it, its longer side to the edge. `inset=` is
  from the edge to the centres of the part's pads nearest it, which is what a header's
  row spacing is measured between; with no inset the part's outline touches the edge.
  Along the edge it is centred. Two edges are a corner.
- `facing=` an edge: the side that is up in the library footprint is turned to it.
- `between=` two parts: its centre is midway between theirs, across and along. With
  `against=` an edge as well, the edge says how far the part is from it and
  `between=` where it is along it.
- `near=` a pin or part, `within=`: the nearest place that is on the board and clear of
  every other part, a pad of the part within the distance of a pad of what it is near,
  centre to centre.
- `side="back"`: the face it is on. Parts on one face may touch and not overlap; a part
  with holes takes both faces.
- `align`: the parts' first pins are a whole number of grid steps apart. Checked, not
  moved to.
- `keepout` of an area of a part: no other part's outline reaches into it, on the
  part's face or on both.

Which way round a part is, where nothing says, is the way that makes its connections
shortest, and is reported: `P1: turned 90 degrees, of 90, 270, for the shortest
connections`.

Question 3, in part: a part nothing places is named in `free`, and a statement that
cannot hold is a problem with its line. Neither is settled silently. Whether a build
refuses a board that has either is the build's to decide.

The T0 file above was first sketched with the headers 1.27 mm in and the straps on the
front. Solved on the board's inputs, neither holds, and both are reported
(`test_what_does_not_fit_on_the_t0_board_is_said`):

```
P1 does not fit on the board: it reaches 0.48 mm past the left edge
align(P1, P2, grid=2.54 mm) does not hold: P1 and P2 are 24.13 mm apart across the board, 9.5 steps
R1 has no place within 3 mm of U1.1 that is on the front of the board and clear of the other parts
```

The board is 1.05 inch wide, so rows 0.9 inch apart are 0.075 inch in from each edge;
and with the module between the headers, 0.48 mm of the front is left between its pads
and each header's courtyard, so the straps go on the back, under the pins they bias.
With those two values every part is placed
(`test_what_the_t0_board_file_says_about_placement_places_every_part`).

**As built, annotations** (`pkidl.annotations`): what a footprint does not say about
its part, here that one end of the module is its antenna, is a part annotation: a
TOML file for each footprint in `src/pkidl/parts/`, found by the footprint's name
whichever library it is in.

```toml
footprint = "ESP-12E"

[pads]
1 = [0, 0]
22 = [16, 0]

[areas]
antenna = [[0, -8.4], [16, -2.6]]
```

It is written against two of the part's pads and not a footprint's origin, since
libraries draw one package about different origins and turned different ways. It is
fitted to the footprint a board has by those two pads, moved and turned through right
angles. A footprint whose pads are not that far apart is some other part under the
name: its annotation is not used, and `u1.area("antenna")` says why not.
`Board.from_inputs` fits what ships to the board's footprints. A part with nothing
shipped gets its areas in the board file, in its footprint's coordinates:
`board.annotate(u1, antenna=((0 * mm, -8.4 * mm), (16 * mm, -2.6 * mm)))`. An area is
said once; a different box for one that is there is refused.

`u1.area("antenna")` is the area as an object, and `board.keepout(area, copper=True,
both_sides=True)` a statement like `place`. A keepout claims nothing about a part, so
two never conflict. `Solution.keepouts` says where each area is on the board and on
which faces: on T0, the width of the module between its two rows of pads, from the top
edge down 5.8 mm, on both. The call that draws a rule area from an outline is now
`board.rule_area(...)`.

The antenna's box is the one the T0 board's footprint draws on its courtyard layer and
labels "No Copper"; a test holds the two together
(`test_the_esp12e_annotation_is_the_box_its_footprint_marks_no_copper`). It has not
been checked against a datasheet.

**As built, pin names:** a board file names a part's pins, each name with the pin's
number, and then finds a pin by its name:

```python
for q in board.parts("Q2..Q5"):
    board.annotate(q, pins={"B": 1, "E": 2, "C": 3})
```

The names are the part's, not its footprint's, where an area is every part's with that
footprint: the fan controller's drivers are `lib_pcb:SOT-23` with value `Q_NPN_BEC`,
and a SOT-23 with another transistor in it has its base on another pad. `q.pin("B")` is
the pin `q.pin(1)` is, so a statement made by either says the same thing and its data
names the pin by number (`"near": "Q2.1"`). A name is said once, as an area is: a
second pin for it is refused, and so is a name that is all digits, which would be taken
for a pin's.
No annotation that ships names pins yet: one could, for a footprint that does fix them,
as the ESP-12E's does.

**`between=` and an edge**, left open by placement, is settled: `between=` alone centres
the module along the board as well as across it, 4.79 mm from the top edge, and with
`against=Edge.TOP` as well it gives way along the board to the edge. A part that
looks for a place (`near=`) looks once every part given a place has one, so it keeps
out of their areas whatever its reference.

Open after this:

- **An annotation that ships holds areas only**, each a box, and a footprint drawn as
  the mirror image of the annotation is not fitted.
- **An area of a part that itself looks for its place** (`near=`) is not kept out of
  by parts placed before it. What is in it is reported (`R1 is in U1's antenna area,
  which is kept clear of copper`), not moved.
- **`side=`.** Here it is the face of the board. The fan channel below writes
  `side=Edge.TOP` for which side of the fan the LED sits; one of the two needs another
  word.
- **The narrow variant below** moves the straps to the back; on this board they are
  there already, and the spacing is the whole difference.
- **A placement that goes round.** A part is turned to bring its pads nearer what they
  connect to, and that can leave a part placed `near=` it with no place; without that
  part it turns back. It is reported (`the placement does not settle: each pass moves a
  part`), not resolved.
- **Limits of this solver:** the board is taken as the box around its outline, and
  mounting holes are not kept clear of; `near=` is solved alone, not with `against=` or
  `between=` beside it; parts turn in right angles.

**As built, routing** (`pkidl.routing`): a router is an engine behind one interface.
It is given a `Job` (the placed footprints, the outline, the net classes, what copper
is there already, the areas to keep out of, the pours, and how to route: `neck_down`,
`cross_planes`, `quick`) and hands back a `Run`: wires, vias, and how many connections
it says it left unmade. `pkidl.route.Freerouting` is the first; it writes the job as a
DSN file, runs Freerouting on it and reads the session and the log.

`staged(router, job, outdir, name)` routes a board in up to three runs: the nets of
every class but Default first and alone, with neck-down off; everything left around
those; and, on a board with pours, a last run for what the corridors between the pours
left unconnected, which may cross a signal net's pour and never a power one. It gives
back a `Routed`: the tracks and vias proposed, each once, and each stage's run. Nothing
is on the board until `lay(board, routed)` puts it there. What a router says of its
own work is reported and not trusted: KiCad's DRC judges the board.

The stages are the ones `spike/` routed its boards in, moved; its boards are built
through them. The flags a stage sets are Freerouting's reasons (a router that may neck
narrows a wide track along whole runs; against planes its optimizer and fan-out cost
minutes for nothing), said in terms another router could answer.

Open after this:

- **A `Run` says a number**, not which connections are unmade. The charter's "routed,
  partly routed, infeasible or not found" needs the nets named, which Freerouting's
  log does not give and its REST API does.
- **Stages come from net classes**: a class other than Default is routed first. A
  board file has no words yet for which nets those are.

**As built, the build** (`pkidl.build`): `board.rules(track=, clearance=, edge=)` and
`board.route()` are statements like the rest: each is said once, and a second `rules`
that gives a width differently is a conflict with both lines. `board.build(dir)` solves
what was said, puts each part where the solution has it, draws each kept area as a rule
area on the faces it holds on, has the router route the board if the board file said
`route()`, and writes `<name>.kicad_pcb` and `<name>.kicad_pro` into `dir`, the name
being the directory the inputs came from unless `name=` gives another. It gives back a
`Built`: the two files, the solution, and what the router proposed.

A board is not built from statements that conflict or do not hold, with a part nothing
places, or with `route()` and no `rules`: `BuildError` says each, with its line, and
nothing is written. A router that leaves connections unmade does not stop the build:
its number is in the result, and KiCad's DRC judges the board. The `Board` is not
changed by building it, so it can be built again.

The T0 board file above is `corpus/t0/esp12-breakout_ESP12Breakout/board.py`, and a
test holds the two to the same text. Built, refilled and checked by KiCad 10.0.6, then
scored (`scripts/corpus.py build`, `kicad-cli pcb drc --refill-zones --save-board
--severity-all`, `scripts/corpus.py score`: the steps of `just corpus`, 2026-11-11):

```
tier board                           parts nets  err warn uncon  vias  track mm
t0   esp12-breakout_ESP12Breakout        8   22    8   22     0    10     200.9
       built from its board.py           8 same    8   13     0     2     138.3
```

The eight errors on each are the same eight: `malformed_courtyard`, all on U1, whose
footprint is the reference's own. The built board's 13 warnings are all
`silk_over_copper`.

Open after this:

- **Reference text is where the footprint has it**, which on this board is over pads:
  the 13 warnings. `pkidl.silk` moves references clear, and the build does not call it.
- **The pour is not a statement.** `board.pour("GND", layer=)` draws a zone when it is
  called, as `Board.pour` always has. The router is not told of it and routes GND as
  track; KiCad fills the pour around what was routed.
- **Every net is in one class**, with the board's one track width and clearance.
  Classes, and so the stages, wait for words that say which nets carry power.
- **The build does not run KiCad.** Refill and DRC are `just corpus`'s, on the files
  the build wrote.

Question 5, units: both. A length is `1.27 * mm`, `50 * mil`, `0.1 * inch`, or the text
`"1.27mm"`, `"50mil"`, `"0.1in"`, and is kept as a whole number of nanometres, as KiCad
stores it, so the three are one value. A bare number is refused rather than taken for
millimetres. `align(..., grid=)` means the parts are a whole number of grid steps from
each other, across and along; it does not put them on a grid fixed to the board, which
has no physical meaning for a board that plugs into a breadboard.

## API style: a board you add to, made of statements

`board.place(...)` records an intent; nothing moves until the build solves them all
together. The working choice:

- **The board is added to** (`board.place(...)`, `board.add(...)`), and each call
  returns the statement it added, an immutable value that can be named, inspected or
  removed.
- **Order never matters.** Statements are solved together; two that contradict each
  other are a reported conflict naming both source lines, never "last one wins".
- **Blocks and variants are functions that return statements**; `board.copy()` makes a
  variant explicitly.

The alternative is pure values: every call returns a new board (`board =
board.place(...)`), as in build123d's algebra mode. Both are written out below on two
boards, to compare.

### T2: `fan_controller_fan_controller`

A PIC24 (U1) driving four PC fans: each fan channel is a 4-pin fan header, an NPN
low-side driver with its base resistor, a pull-up on the tach line, a status LED with
its resistor, and a 12 V decoupling capacitor. A fifth channel reads a fan's PWM input
(P1, Q1, R14). A 7805 (U2) makes 5 V; a rotary encoder (SW1) and a programming header
(P2). Board 60 x 37 mm with four 3.3 mm holes.

**Added to, with a block function:**

```python
from pkidl import Board, Edge, mm, place, row

board = Board.from_inputs("corpus/t2/fan_controller_fan_controller")
board.rails("+12V", "+5V", "GND")

def fan_channel(fan, driver, base_r, tach_r, led, led_r, cap):
    """A fan header with its driver, tach pull-up and status LED close behind it."""
    return [
        place(driver, near=fan.pin(4), within=4 * mm),
        place(base_r, near=driver.pin("B"), within=2 * mm),
        place(tach_r, near=fan.pin(3), within=3 * mm),
        place(cap, near=fan.pin(2), within=2 * mm),
        place(led, near=fan, side=Edge.TOP, within=5 * mm),
        place(led_r, near=led, within=2 * mm),
    ]

fans = board.parts("P3", "P4", "P5", "P6")
board.add(row(fans, along=Edge.BOTTOM, pitch="even"))      # headers along one edge
for fan, q, rb, rt, d, rd, c in zip(
        fans, board.parts("Q2..Q5"), board.parts("R15..R18"), board.parts("R10..R13"),
        board.parts("D1..D4"), board.parts("R7", "R8", "R9", "R19"), board.parts("C3..C6")):
    board.add(*fan_channel(fan, q, rb, rt, d, rd, c))

board.place(board["U1"], centre=True)
board.place(board["U2"], against=Edge.LEFT)                # regulator by the 12 V input
board.place(board["SW1"], against=Edge.TOP)
board.place(board["P2"], against=Edge.RIGHT)
board.decouple(board["U1"], board.parts("C2", "C8", "C9"))  # caps on its supply pins
board.pour("GND", layer="B.Cu")
board.route()
```

**Pure values:**

```python
board = Board.from_inputs("corpus/t2/fan_controller_fan_controller").rails("+12V", "+5V", "GND")

def fan_channel(board, fan, driver, base_r, tach_r, led, led_r, cap):
    return (board
            .place(driver, near=fan.pin(4), within=4 * mm)
            .place(base_r, near=driver.pin("B"), within=2 * mm)
            .place(tach_r, near=fan.pin(3), within=3 * mm)
            .place(cap, near=fan.pin(2), within=2 * mm)
            .place(led, near=fan, side=Edge.TOP, within=5 * mm)
            .place(led_r, near=led, within=2 * mm))

fans = board.parts("P3", "P4", "P5", "P6")
board = board.row(fans, along=Edge.BOTTOM, pitch="even")
for fan, q, rb, rt, d, rd, c in zip(...):                  # as above
    board = fan_channel(board, fan, q, rb, rt, d, rd, c)
board = (board.place(board["U1"], centre=True)
              .place(board["U2"], against=Edge.LEFT)
              .place(board["SW1"], against=Edge.TOP)
              .place(board["P2"], against=Edge.RIGHT)
              .decouple(board["U1"], board.parts("C2", "C8", "C9"))
              .pour("GND", layer="B.Cu")
              .route())
```

### T0 variant: the ESP-12E breakout, narrow

The same breakout with its headers 0.6 inch apart instead of across the full board width,
for narrow breadboards, and the straps moved to the back.

**Added to:**

```python
def breakout(board, spacing):
    u1, p1, p2 = board.parts("U1", "P1", "P2")
    return [
        place(p1, against=Edge.LEFT, inset=1.27 * mm),
        place(p2, right_of=p1, distance=spacing),
        align(p1, p2, grid=0.1 * inch),
        place(u1, between=(p1, p2), facing=Edge.TOP),
        keepout(u1.area("antenna"), copper=True, both_sides=True),
    ]

wide = Board.from_inputs(ESP12)
wide.rails("VCC", "GND")
wide.add(*breakout(wide, spacing=0.9 * inch))
narrow = wide.copy()                                   # explicit copy for the variant
narrow.remove(*narrow.statements(about="P2"))          # or build it from breakout(..., 0.6)
narrow.add(place(narrow["P2"], right_of=narrow["P1"], distance=0.6 * inch))
narrow.add(*[place(r, side="back") for r in narrow.parts("R1..R5")])
```

**Pure values:**

```python
base = Board.from_inputs(ESP12).rails("VCC", "GND")
wide = breakout(base, spacing=0.9 * inch)              # breakout returns a new board
narrow = breakout(base, spacing=0.6 * inch).place(base.parts("R1..R5"), side="back")
```

### What the comparison shows

| | Added to | Pure values |
|---|---|---|
| Everyday statements | one per line, as Python reads | chained or reassigned; `board =` everywhere |
| Blocks | a function returning statements; reusable on any board | a function taking and returning a board; also reusable |
| Variants | `copy()` plus edits, or rebuild from the block function: two ways, the first clumsy | natural: build each from the shared base |
| The silent mistake | none: a call always lands | `board.place(...)` without `board =` does nothing, no error |
| Removing or overriding a statement | possible (`remove`), but invites order-dependence | not needed: build what you want |

**Reading:** for the everyday board (fan_controller), adding reads better and has no
silent failure. For variants, pure values are cleaner, and the added-to version's
`copy()`/`remove()` path is the weak point: it is where order-dependence creeps back in.

**Proposal:** keep the board added to, drop `remove()`, and make variants the pure way:
a variant is a function that builds a board from a base and parameters, never a copy
edited afterwards. `copy()` stays only as an explicit snapshot. That takes the strength
of each and closes both weak points (the silent no-op, and edit-after-copy).

**Decided (2026-11-11):** the proposal above. A board is added to with statements
(`board.place(...)`, `board.add(...)`), each an immutable value, solved together
regardless of order, contradictions reported as conflicts; there is no `remove()`;
variants are functions that build a board from a base and parameters; `copy()` is only
an explicit snapshot.

## T1: `OpenMPPT_OpenMPPT`

**From its circuit:** a BQ24650 (U101) solar MPPT charger driving a synchronous buck.
Solar in on an XT30 (J103), through a blocking diode (D101, a 10 A dual Schottky) to the
input rail; two paralleled high-side FETs (Q101, Q103) and two low-side (Q102, Q104)
around the switch node; a 3.3 uH inductor (L101); two paralleled 10 mOhm sense
resistors (R110, R113) whose ends U101 reads on pins 9 and 10; the battery rail out on
a second XT30 (J104). Bulk and ceramic capacitors on both rails. About 10 A (the diode's
and connectors' rating). Board 74.8 x 47 mm, no holes.

```python
from pkidl import A, Board, Edge, mm

board = Board.from_inputs("corpus/t1/OpenMPPT_OpenMPPT")
vin, sw, vbat = board.name_nets({"Net-(C106-Pad1)": "VIN", "Net-(C105-Pad1)": "SW",
                                 "Net-(C109-Pad1)": "VBAT"})  # fmt: skip
board.rails("VIN", "VBAT", "GND")

j_in, j_bat = board.parts("J103", "J104")
board.place(j_in, against=Edge.LEFT)                   # solar in one end
board.place(j_bat, against=Edge.RIGHT)                 # battery out the other

# The power path, with the current each stretch carries. pkidl sizes the copper for it
# and checks the narrowest neck on the filled board.
board.path(j_in, "D101", vin, current=10 * A)
board.path(vin, ["Q101", "Q103"], sw, ["Q102", "Q104"], "GND", current=10 * A)
board.path(sw, "L101", ["R110", "R113"], vbat, j_bat, current=10 * A)

# The switching loop: input ceramic, high side, low side, back to its ground. As small
# as it can be; the switch node no bigger than the parts it joins.
board.loop("C115", ["Q101", "Q103"], ["Q102", "Q104"], area="min")
board.limit(sw, area="min")

# Kelvin sense: U101 reads the resistors' own pads, as a pair, away from the power copper.
board.kelvin(["R110", "R113"], to=board["U101"].pins(9, 10))

# The FETs shed heat into copper under them, through vias to the other side.
for q in board.parts("Q101..Q104"):
    board.heatsink(q)                                  # sized from its part annotation

board.place(board["U101"], near=["Q101", "Q102"], within=10 * mm)
board.decouple(board["U101"])                          # the caps on its pins, by its pins
board.route()
```

**Needs, beyond T0/T2:** naming nets the schematic left anonymous; `path(..., current=)`
sizing copper and checking it on the result (the gap the survey found nobody fills);
`loop(area="min")` and `limit(net, area=)` as placement and pour objectives; `kelvin`;
`heatsink` from part annotations (thermal pad, via pattern); `decouple` choosing which
capacitors go to which pins from the circuit.

**Questions:** how `loop(area="min")` is checked (the loop's enclosed area on the
result is measurable; is a threshold stated or only minimised?); whether `path` with a
list of parallel parts means "share the current" (it should, and the check counts each
branch).

## T3: `usb2serial-CH340G_USB2TTL-CH340G`

**From its circuit:** a CH340G USB-to-serial chip (U2) with its 12 MHz resonator (X1)
and load capacitors; a micro-USB connector (P1) whose D+ and D- go to U2; a 3.3 V
regulator (U1); a 3-pin header choosing the I/O voltage (P2); a 6-pin serial header
(P3); power, TX and RX LEDs. Board 18 x 25 mm, two layers.

```python
from pkidl import Board, Edge, mm, ohm

board = Board.from_inputs("corpus/t3/usb2serial-CH340G_USB2TTL-CH340G")
board.rails("+5V", "+3.3V", "VCC", "GND")
board.stackup("2L-1.6mm-1oz")                          # impedance needs the stackup
dp, dm = board.name_nets({"Net-(P1-Pad3)": "USB_DP", "Net-(P1-Pad2)": "USB_DM"})

board.place(board["P1"], against=Edge.BOTTOM, overhang=0.6 * mm)  # plug reachable
board.place(board["P3"], against=Edge.TOP)
board.place(board["U2"], near=board["P1"], within=8 * mm)

board.diff_pair(dp, dm, impedance=90 * ohm, skew=0.1 * mm, reference="GND")
board.place(board["X1"], near=board["U2"].pins(7, 8), within=3 * mm)
board.keepout(below=board["X1"], signals=True)         # no tracks under the resonator
board.decouple(board["U2"])
board.pour("GND", layer="B.Cu")                        # the pair's reference plane
board.route()
```

**Needs:** a stackup and impedance-driven width and gap; `diff_pair` with skew and a
reference plane that must be unbroken under it (checked); `overhang`; keepouts relative
to a part.

**Question:** on two layers, a 90 Ohm pair over a 1.6 mm board is wide; pkidl should say
so ("the pair needs 1.9 mm width at this stackup") rather than silently route it narrow.
That is a diagnostic in intent terms, not a DRC error.

## T4: `icehat_icehat`

**From its circuit:** a Lattice iCE40-family FPGA (U401, value `ice5lp4k_sg48`, QFN-48
with exposed pad) on a
Raspberry Pi HAT: the Pi's 40-pin header (J2), three PMOD connectors (P401, P403, P404)
with 3-pin voltage selectors, 3.3 V and 1.2 V regulators (U301, U302), LEDs and test
points. Board 65 x 30 mm, four layers, four holes.

```python
from pkidl import Board, Edge, mm, row
from pkidl.std import rpi_hat                          # a published mechanical standard

board = Board.from_inputs("corpus/t4/icehat_icehat", template=rpi_hat(variant="mini"))
board.rails("+5V", "+3V3", "+1V2", "GND")
board.stackup("4L-1.6mm", layers=["F.Cu", "GND", "PWR", "B.Cu"])
board.plane("GND", layer=2)
board.plane({"+3V3": ..., "+1V2": ...}, layer=3)       # split power plane, by region

board.fix(board["J2"], at=rpi_hat.header)              # the standard places the header
pmods = board.parts("P401", "P403", "P404")
board.add(row(pmods, along=Edge.RIGHT))                # PMODs on the open edge
for pmod, sel in zip(pmods, board.parts("P402", "P405", "P406")):
    board.place(sel, near=pmod, within=4 * mm)

board.place(board["U401"], centre=True)
board.fanout(board["U401"], via="0.3/0.15mm")          # escape the QFN to inner layers
board.decouple(board["U401"])
board.route(layers=["F.Cu", "B.Cu"])                   # signals outside, planes inside
```

**Needs:** mechanical templates for published standards (Pi HAT, Arduino shield, PMOD,
Eurocard), with a `variant`; a stackup with named roles; planes and split planes by
region; QFN fanout with via types; routing restricted to layers.

**Question:** is a standard (`rpi_hat`) part of pkidl, or a separate package of
templates others contribute to? The first is quicker; the second scales.

## What the five boards ask for, together

| Feature | T0 | T2 | T1 | T3 | T4 |
|---|---|---|---|---|---|
| Load circuit + mechanical; part handles; selectors | x | x | x | x | x |
| Placement relative to edges, parts, pins; rows; grids | x | x | x | x | x |
| Rails declared; nets named | x | x | x | x | x |
| Part annotations (antenna, thermal pad, keep-clear) | x | | x | x | x |
| Decoupling from the circuit | | x | x | x | x |
| Blocks as functions | | x | | | x |
| Copper for current, checked on the result | | | x | | |
| Loops and areas as objectives | | | x | | |
| Kelvin and differential pairs; impedance from a stackup | | | x | x | |
| Stackup, planes, fanout, layer-restricted routing | | | | x | x |
| Mechanical standards as templates | | | | | x |

The first four rows are needed by every board and are where implementation starts.
