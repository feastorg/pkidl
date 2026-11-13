# Changelog

All notable changes to pkidl are documented here, in
[Keep a Changelog](https://keepachangelog.com) format: what someone using the library,
or building on it, would notice. Nothing has been released yet, so every entry is under
Unreleased. History before this file was reconstructed from the git log.

## [Unreleased]

### Added

- A build routes a board with its pours known to the router, and checks the result.
  `pkidl.routing.poured` routes with each pour carrying its net and free to be crossed,
  then asks `pkidl.fill.cut_off` whether tracks across a pour have left pads of its
  net on a piece apart from the rest. Where none are, that routing stands, with no
  track where the pour joins a net. Where some are, `Routed.cut` says which pads, on
  which layer, fenced in by which nets' tracks, and the board is routed again with
  that net carried by tracks, as it was before. `pkidl.fill.fills` is a board's pours
  as the pieces they fill in. A build of a board whose pour is cut takes two runs of
  the router. `fills`, `prefill` and `cut_off` take the outline as its corners or as
  the area inside it, cut-outs as holes, and keep the clearance given for `""` from
  what is on no net. `pkidl.footprint.pad_at(footprint, pad)` is where a pad is. (#43)
- Where KiCad is installed (`$KICAD_CLI`, default `kicad-cli`), it is KiCad that says
  what a build's pours leave unconnected, from its own fill of the proposed routing
  (`pkidl.kicad.unconnected`), with any pad it joins by fewer spokes than it asks,
  and pkidl's model answers only where it is not.
  `Routed.judge` says which, and `scripts/corpus.py build` prints it. (#43)
- `decouple(part, caps, within=)` and `Board.decouple()`: a statement that capacitors
  decouple a part. Each is across ground and one of the part's supplies, and is placed
  with its pad on that supply near one of the part's pins on it, one capacitor to a
  pin, in the order named and the order of the pin numbers. A part's capacitors are
  said in one statement. A capacitor with no pin left, or not across ground and a net
  the part is on, is a problem and is not placed. (#7)
- `Board.ground("GND")` declares which nets are ground, and `Net.is_ground` reads it.
  A ground is a rail as well. `decouple` needs it said. (#7)
- Parts are kept inside the board's outline as it is drawn, and clear of its mounting
  holes. `Board.edge()` is the area the outline encloses, rounded corners and cut-outs
  included (`pkidl.edge`); `Board.hole(footprint, at)` puts a mounting hole on the
  board, `Board.from_inputs()` does so for each one in `mechanical.json`, and
  `Board.fixed` lists them. `Board.solve()` reports a part outside the outline or over
  a hole, has a part placed `near=` something look only where it is clear of both, and
  spreads a row over the longest stretch of its edge that holes and the outline leave
  clear, saying how long that is. An outline that does not close, or that encloses two
  areas apart from each other, is the board's one problem, and nothing is placed. (#4)
- `place(part, centre=True)`: the middle of the part's outline at the middle of the
  board. `place(part, near=, within=, toward=Edge.TOP)`: on the side of what it is near
  that is toward an edge, its whole outline beyond that part's outline. `side=` is
  still the face of the board. `toward=` is said once for what a part is near, and
  `Board.solve()` names the side when a part has no place on it. (#23)
- `row(parts, along=Edge.BOTTOM, pitch="even")` and `Board.row()`: a statement that
  parts go in a row along an edge, in the order named, from the left or from the top
  down. Each lies against the edge as `place(against=)` has it, `inset=` likewise. With
  an even pitch the gaps are equal, between the parts and from each end of the edge to
  the part nearest it; with a length, the parts' middles are that far apart about the
  middle of the edge. The parts of a row are turned the same way, the way that makes
  the row's connections shortest, but for one `facing=` an edge. `Board.solve()`
  reports a row longer than its edge and places none of it; a part is in one row along
  an edge, and a second is a conflict. (#22)
- `Board.annotate(part, pins={"B": 1, "E": 2, "C": 3})` names a part's pins, and
  `Part.pin("B")` and `Part.pins("B", "C")` find them by name: the same pins their
  numbers find, so a statement about one says the same thing either way. Only the part
  named has the names, where an area is every part's with that footprint: a footprint
  does not say which pad of a transistor is its base. A name is a word and is said once;
  a second pin for it, a pin the part has not got, and a name that is all digits are
  refused, with nothing of what was said kept. `Part.pin()` with a name
  the part has not got says the names it has. (#21)
- `Board.build(outdir)` and `pkidl.build`: a board's KiCad files, from what its board
  file said. The build solves the statements, puts each part where the solution has
  it, draws each area kept clear as a rule area on the faces it holds on, routes the
  board if the board file said `route()`, and writes `<name>.kicad_pcb` and, for a
  board with `rules`, `<name>.kicad_pro`. It gives a `Built`: the files, the
  `Solution` and what the router proposed. A board whose statements conflict or do
  not hold, with a part nothing places, or with `route()` and no `rules`, is not
  built: `BuildError.problems` says each, and nothing is written. A router that
  leaves connections unmade does not stop the build. The `Board` is left as it was.
  (#17)
- `Board.rules(track=, clearance=, edge=)` and `Board.route()`: statements, in
  `pkidl.intent` as `rules()` and `route()`. The rules are the board's track width,
  clearance and clearance from its edge (0.5 mm unless given), each said once. The
  build writes them into the project and gives them to the router. `Board.route()`
  asks for routing by `pkidl.route.Freerouting`, or by the router `build(router=)`
  is given. (#17)
- `Board.name`: the name a board's files are written under. `Board.from_inputs()`
  sets it to the name of the directory the inputs are in; `build(name=)` gives
  another. (#17)
- `corpus/t2/fan_controller_fan_controller/board.py`: the second corpus board file,
  49 parts with its four fan channels placed by one function, shown in
  `docs/design/board-files.md` as committed. `just corpus` builds and scores it, and
  `just test` solves and routes it, which takes the tests from half a minute to two.
- `corpus/t0/esp12-breakout_ESP12Breakout/board.py`: the first corpus board file, the
  one `docs/design/board-files.md` shows. `python scripts/corpus.py build DIR` builds
  every corpus `board.py`, and `just corpus` has KiCad refill and check what was
  built and scores it in a row under its reference: the parts placed, whether the
  netlist is the circuit's, and the same DRC counts and measures. A board file that
  does not build fails `just corpus` once the scorecard is printed. (#17)
- `pkidl.routing`: a board routed in stages, by a router behind one interface. A `Job`
  is what a board asks of a router: its footprints, outline, net classes, the copper
  already there, and what to keep out of. A `Router` has one method, `route(job, outdir,
  name, stage)`, and hands back a `Run`: the wires and vias it proposes, and how many
  connections it says it left unmade (`unrouted`, `None` where it does not say).
  `staged()` routes the nets of every class but the first alone and not necked, then
  the rest around that copper, then, on a board with planes, what is left, which may
  cross a signal net's pour. It gives a `Routed`: the wires, the vias and each stage's
  `Run`. Nothing is on a board until `lay()` puts it there. (#16)
- `pkidl.route.Freerouting`: the first `Router`. It leaves each stage's `.dsn`, `.ses`
  and `freerouting.log` in the directory it is given, and reads `Run.unrouted` from
  the log's last auto-routing line, as Freerouting 2.5.0 writes it. (#16)
- `pkidl.annotations`: what a footprint does not say about its part, held as named
  areas. An annotation is a TOML file written against two of the part's pads, not the
  footprint's origin. `fit()` turns it through right angles until those two pads are
  where the footprint has them, and refuses a footprint where they are not. Annotations
  ship in `pkidl/parts` and are found by the footprint's name, whichever library it is
  in; `Board.from_inputs()` fits them. The first is the ESP-12E's antenna: the box its
  footprint marks "No Copper", not checked against a datasheet. (#14)
- `Part.area(name)` gives one of a part's areas. `Board.annotate(part, name=(corner,
  corner))` gives the areas of a part that ships with none, in its footprint's
  coordinates. An area is said once: a different box for a name already there is
  refused. (#14)
- `keepout(area, copper=True, both_sides=True)` and `Board.keepout()`: a statement that
  an area of a part is kept clear. It says nothing of where the part goes, so keepouts
  never conflict. `Board.solve()` keeps every other part out of the area, on the part's
  face or on both, and `Solution.keepouts` says where each area is. A part given a
  place inside one is reported and stays where it was put. `keepout` is exported from
  `pkidl`. (#14)
- `Board.solve()` and `pkidl.placement`: where each part goes, worked out from what the
  board's statements say. It gives a `Solution`: a `Pose` for each part placed
  (`poses`), the parts nothing places (`free`), what was said that does not hold, with
  the statements that said it (`problems`), and what it decided where nothing said
  (`chosen`). It moves nothing on the board and drops no statement to make the others
  fit. Parts are turned in right angles only, the board is taken as the box around its
  outline, and the same statements give the same placement whatever order they were
  added in. (#13)
- `place()` takes `side=`: `Side.BACK` or `"back"` puts a part on the back of the board.
  (#13)
- `pkidl.intent`: `place()` and `align()` make statements about where parts go. A part
  is placed `against=` an `Edge` with an `inset=`, `between=` two parts, `facing=` an
  edge, or `near=` a pin or part `within=` a distance; aligned parts sit a whole number
  of `grid=` steps apart. A statement is an immutable value that records the line of
  the board file that made it, and making one moves nothing. (#12)
- `Board.place()`, `Board.align()` and `Board.add()` add statements to a board and give
  them back; `Board.statements()` lists them, for one part with `about=`. The order
  they are added in means nothing, and a statement added twice is kept once. (#12)
- `Board.conflicts()`: each aspect of a part that two statements give differently, with
  the line each was written on. Neither wins. (#12)
- `pkidl.units`: `mm`, `mil` and `inch`, so a length is written with its unit, as
  `1.27 * mm` or `"50mil"`. A `Length` is a whole number of nanometres. A bare number
  has no unit and is refused. (#12)
- `pkidl.circuit`: a board's parts, pins and nets as objects (`Part`, `Pin`, `Net`),
  reached through the board with `board["U1"]`, `board.parts()`, `board.net()` and
  `board.nets()`. `board.parts()` takes references, runs such as `"R1..R5"`, and the
  selectors `on_net()` and `where()`; with nothing asked for it gives every part. (#11)
- `Board.rails()` declares the supplies and grounds, the nets `Part.signal_net` leaves
  out. `Board.name_nets()` gives nets the schematic left anonymous a name to use in the
  board file: the net is found by either name, and its `name` stays the circuit's. (#11)
- `Board.from_inputs(where)`: a board from a directory holding `circuit.json`,
  `mechanical.json` and `footprints/`. The outline is drawn and the mounting holes are
  placed where `mechanical.json` puts them; the parts are loaded and not placed. A
  missing footprint file, or a part connected on a pad its footprint lacks, is reported
  by name. (#10)
- `Board.outline(items)`: the board edge from lines, arcs, rectangles, circles and
  polygons, as `mechanical.json` lists them. (#10)
- `pkidl.footprint.place()` takes a parsed footprint as well as a footprint file or its
  text, and `Placement.uid` derives a footprint's UUIDs from a key other than its
  reference. (#10)
- `Board` is exported from `pkidl`, with `Edge`, `Side`, `place`, `align`, `mm`, `mil`,
  `inch`, `on_net` and `where`. (#10, #11, #12, #13)
- `pkidl.footprint.library_form(placed)`: the library footprint a placed one was placed
  from, with nothing of its placement left. (#9)
- `pkidl.footprint.footprint_path(name)`: where a footprint library keeps a footprint,
  `<library>.pretty/<footprint>.kicad_mod`. (#9, #10)
- `pkidl.importer`: reads the inputs a board is designed from out of an existing
  `.kicad_pcb`. `circuit(board)` gives the parts, their values, footprints and pad nets;
  `mechanical(board)` gives the outline and the mounting holes; `footprints(board)`
  gives the library footprint behind each footprint name. Nothing else of the board's
  layout is read. (#7, #9)
- `corpus/`: public boards under permissive licences, in tiers of difficulty. Each has
  its reference board, its `LICENSE`, and the inputs a board file reads: `circuit.json`,
  `mechanical.json` and `footprints/`. `corpus/manifest.json` records each board's tier,
  licence, source and file hashes. (#7, #9)
- `just corpus` has KiCad refill and check each corpus reference and prints the
  scorecard. `python scripts/corpus.py extract` rewrites the corpus inputs from the
  references. (#7, #9)
- `docs/design/board-files.md`: a board file for one corpus board of each tier, written
  before the library could build them, with what each asks of pkidl. It fixes the API
  style: a board is added to with statements that are immutable and solved together
  whatever their order, there is no `remove()`, and a variant is a function that builds
  a board. `docs/roadmap.md` says where pkidl stands and what comes next. (#8)
- `docs/charter.md`: what pkidl is and is not, its layers, its design principles and the
  order of work. `docs/survey/` holds the prior-art survey behind it. (#4, #5)
- `pkidl.sexpr`: reads and writes KiCad's s-expression files (`parse`, `dumps`, `find`,
  `find_all`). Numbers are kept as the file wrote them, a tree written and read back is
  the same tree, and the same tree always gives the same bytes. (#2)
- `pkidl.footprint.place()`: a library footprint placed on a board the way KiCad stores
  it, from a `Placement`: its position, rotation and side, its pad nets and its link to
  the schematic. `board_only`, `in_bom` and `solid_pads` set what the library footprint
  does not. (#2)
- `pkidl.board.Board`: assembles a board file in the format KiCad 10 saves
  (`version 20260206`) from `footprint()`, `track()`, `via()`, `zone()`, `rule_area()`,
  `text()` and `outline_rounded_rect()`, and writes it with `write()`. Zones are
  written with their outline only, for KiCad to fill. Every UUID is derived from what
  the item is, so the same board is written as the same bytes. (#2)
- `Board.pour()`: a net poured over the whole board, or around its pads on the parts
  given with `around=`, so the pour follows the placement. (#2)
- `pkidl.project`: `write_project()` writes a `.kicad_pro` with its net classes, rules
  and severities stated, not left to KiCad's defaults. `PARITY_ERRORS` and
  `SILK_ERRORS` are severities that make schematic parity findings and silkscreen over
  copper errors. `width_rules()` and `write_rules()` write a `.kicad_dru` that holds
  each net class to a minimum track width. (#2)
- `pkidl.dsn`: `write_dsn()` writes a Specctra DSN file for an autorouter from the
  board, and `read_ses()` reads the routes back. `only=` leaves every other net out of
  the network to route, `fixed=` writes routes already made as protected wiring,
  `class_clearances=` writes the clearance between two net classes, `areas=` are
  written as keepouts and `planes=` as planes. A footprint's copper polygons are
  written as keepouts, and a pad's copper is written at its offset from its drill. (#2)
- `pkidl.route.freerouting()`: runs Freerouting on a DSN file, with one router thread
  and one optimizer thread. `$FREEROUTING` overrides the command. A command that is not
  found, exits with an error or writes no session file raises `RouterError`. (#2)
- `pkidl.fill.prefill()`: each pour's fill worked out before routing, to give to
  `write_dsn(planes=...)`. It leaves the board's zones as they are. (#2)
- `pkidl.stitch.stitch_points()`: grid points where a stitching via on a net fits: clear
  of every pad, of other nets' tracks and vias, of the areas given with `avoid=` and of
  the board edge, and where its model of the net's pour reaches the via on both
  layers. (#2)
- `pkidl.silk`: `place_references()` moves each footprint's reference to a spot clear of
  pads, other silkscreen and the board edge, or to the fab layer when there is none.
  `nearest_clear_spot()` finds a clear place for a board text. (#2)
- `pkidl.measure`: `regions()` counts each net's pour regions on a board KiCad has
  filled. `python -m pkidl.measure BOARD [NET ...] [NET=REGIONS ...]` prints them and
  exits 1 when a net named with `=` has another count. (#2)
- pkidl depends on shapely, which `pkidl.fill` and `pkidl.measure` use. (#2)
- `spike/`: the earlier spike and its history. Its boards are written with pkidl, and it
  stays a separate project. (#2)

### Changed

- A pour that does not say its `clearance` or its `thermal_gap` has both from the
  board's `rules(clearance=)` when the board is built, where it had 0.4 and 0.5 mm
  whatever the rules. The thermal gap is not widened past 0.5 mm by rules that ask
  more clearance. A pour that says either keeps what it says, a zone drawn with
  `Board.zone` is as drawn, and so is a pour on a board with no rules. (#42)
- A footprint with no courtyard and no fabrication drawing has its body on the silk,
  and a part's outline takes that in. Such a part was taken as the box around its
  pads: a fan header's housing hung off the board's edge, and other parts were placed
  inside it. Which side of such a part is longer can change with it, and so which way
  it lies against an edge or in a row: a two-pin header whose housing is deeper than
  its pins are apart now lies with its pins across the edge. A connector whose silk
  overhangs the board's edge is reported as off the board. (#33)
- A pad is no nearer the board's edge than the board's `rules(edge=)`. A part
  `against=` an edge with no `inset=` is as far in as keeps its copper that far from
  it, and `Board.solve()` says so in its choices; an `inset=` that puts a pad nearer
  is a problem naming the pad; and a part placed `near=` something looks only where
  its copper is clear of the edge. On a board with no rules a part against an edge is
  on it, as before. (#33)
- Pads of two parts on different nets are kept as far apart as the board's rules say
  (`rules(clearance=)`). Two parts could touch, and their pads with them: on the fan
  controller a capacitor's pad was 0.036 mm from a pin of the processor. `Board.solve()`
  reports a pair that is closer, naming the two pads, and a part placed `near=`
  something looks only where its pads are clear. Pads on one net, and parts on a board
  with no rules, may still touch. (#31)
- A `Problem` lists a statement once in `statements` where it listed it once for each
  part it placed, as an overlap of two parts of one row did. What it prints is the
  same. (#7)
- A board with rounded corners or mounting holes can now have problems where it had
  none: a part in a rounded corner, or over a hole, was placed without a word. A row
  along an edge with holes near it is narrower than it was. (#4)
- pkidl is licensed under Apache-2.0, where it was MIT. `spike/` is GPL-3.0-or-later.
  (#3)
- The library, its tests and their fixtures moved from `spike/` to the repository root,
  as a project of its own: Python 3.13 or later, depending on shapely only, with tests
  that need no KiCad, SKiDL or router. `spike/` uses pkidl's public API as an outside
  project would. (#6)
- `pkidl.importer.mechanical()` records each mounting hole's rotation and side (`rot`,
  `back`), and `Board.from_inputs()` places the hole with them. (#10)
- The call that draws a rule area from an outline is `Board.rule_area()`. It was
  `Board.keepout()`, which is now the statement about a part's area. (#14)
- `Board.solve()` places the parts given a place before the parts that look for one
  (`near=`), then by reference, so a part that looks sees every area kept clear. (#14)
- `place(between=, against=)` with an edge: the edge says how far the part is from it,
  and `between=` where it is along it. The two were reported as two places. (#14)
- The tests that run Freerouting are skipped where it is not installed. The rest
  still need no KiCad, SKiDL or router. (#16)

### Fixed

- `pkidl.fill.cut_off`, pkidl's model of what a pour joins, cuts the fill away round
  each pad of the net that has a thermal relief, as KiCad does: a pad in the only way
  through a wall parts the pour, and the model took it as whole. A pad is joined to
  every piece of pour its spokes reach, two spokes in all. A pad's own `(clearance 0)`
  is its footprint's, and a piece of pour that touches only a pad that joins no pour is
  not kept. A build asks KiCad where KiCad is installed; this is what answers where it
  is not.
- A pad that shares its number with another in its footprint, as a shield's or a tab's
  pads do, is where it is. `pkidl.fill`, `pkidl.measure`, `pkidl.silk`, `pkidl.stitch`
  and `Board.pour(around=)` took each to be where the first of that number is: a pour
  was filled over the others, and a stitch or a label was placed by the wrong pad. A
  pad whose copper is off its hole, by its drill's offset, is where its copper is in
  `pkidl.fill`. (#43)
- A router is kept off an unplated hole as far as KiCad asks, and off the whole of its
  pad. `pkidl.dsn.write_dsn` wrote such a hole as a keepout of its drill's width: a
  track could cross the ring of a pad wider than its hole, and came within the
  router's own clearance of a hole where KiCad asks 0.25 mm. `write_dsn` takes
  `hole_clearance=` and a `Job` has it, 0.25 mm unless said. A slotted hole, which
  `write_dsn` raised on, is kept out of by its longer side. (#40)
- A built board has no track narrower than its `rules(track=)`. The build let the
  router neck tracks into pins, below the width it then gave KiCad as the least
  allowed. A build routes with neck-down off, and `staged` necks in its later stages
  only where the job's `neck_down` says a track may: it necked there whatever the job
  said. A `Job` has `fan_out`, and a build routes with it off as well: Freerouting's
  fan-out stage narrows its stubs whatever the neck-down setting is. (#32)
- `pkidl.footprint.place()` flips a text's mirror flag when a footprint goes to the
  back. A text the library already mirrored was left mirrored. (#9)
- `pkidl.importer.mechanical()` reads each drill of a hole where it is. Drills were
  found by pad number, so every drill of a hole with unnumbered pads read as the first
  one's position. (#10)
