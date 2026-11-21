# Changelog

All notable changes to pkidl are documented here, in
[Keep a Changelog](https://keepachangelog.com) format: what someone using the library,
or building on it, would notice. Nothing has been released yet, so every entry is under
Unreleased. History before this file was reconstructed from the git log.

## [Unreleased]

### Added

- `corpus/vendors/`: a manifest per vendor that pins every board file in Olimex's,
  SparkFun's and Adafruit's GitHub organisations to a commit and a git blob hash, with
  its product, revision, whether it is the current one, its format and what kind of
  file it is. The boards are not kept in the repository:
  `python scripts/corpus.py fetch` downloads the ones asked for (`--vendor`,
  `--product`, `--current`, `--kicad`) into `build/vendors/`, keeps one only if its
  bytes are the pinned ones, and skips what is already there. Files that are not
  product boards (production panels, backups, drawings, templates, duplicates) are
  marked and left out unless `--all` is given. `corpus/PROVENANCE.md` says how the
  manifests were read and what is not known of them.
- A path's current sets how wide the tracks of its nets are. Every net that is the net
  of a stretch of a `path` is laid, the whole of it, as wide as the current needs to
  warm its tracks by no more than the new `rules(rise=)` allows: `10 * degC` where
  nothing says, with the new unit `degC` for a difference in temperature. The width is
  Brooks and Adam's fit to IPC-2152 for an outer layer, as the source of KiCad's master
  branch has it (`common/track_width_calculations.cpp`, read 2026-11-19; ΔT = 215.3 ·
  I² · W^-1.15 · Th^-1, amps, °C and mils), with the copper as thick as
  `rules(copper=)` says, taken up to the next whole micrometre (`pkidl.paths.needed`):
  1.5 A at 10 °C in 1 oz copper needs 0.562 mm. It is not what KiCad 10.0.8's
  calculator reckons: that is by IPC-2221, and gives 0.5255 mm for the
  same. `needed` refuses a current, a rise or a thickness that is not more than
  nothing, and gives a width for any current however large: nothing says where the
  fit stops holding. A net is never narrower
  than `rules(track=)`; one on several paths takes the largest of their currents, not
  their sum; and the net into parts side by side is given the whole current. The nets
  of a width are a net class named for it (`0.562 mm`): the router is given the classes
  and their nets, `<name>.kicad_pro` has them, and a `<name>.kicad_dru` beside it,
  written only where there is such a class, makes each class's width the least KiCad's
  DRC allows a track of it, as an error, with the reason above each rule (`a path's
  1.5 A needs 0.562 mm to warm by no more than 10 °C in 0.035 mm copper`). The file
  is written whole over whatever is at its path, so a rule of one's own put there is
  lost to the next such build; a build of a board with no wider net leaves that path
  alone, and a file an earlier build left there stays. Each `Reading` has its path's current and
  what that needs (`Reading.needs`), and says `0.5 mm at its narrowest where 1.5 A
  needs 0.562 mm` where the copper on the way is narrower; nothing fails for it. A
  board with no `path`, or none whose current needs more than `rules(track=)`, is
  built byte for byte as before. A board with a wider net is routed differently: its
  tracks are wider; a run that joins what a pour left cut off is told of the classes
  as the first run is, so a track that joins a net of a wider class is laid that
  wide, and the pours stand for it where a track of the widest class can end in
  them, whichever net is joined; and where the board is routed again without its
  pours the wider nets are routed first, alone. The bench supply's 1.5 A paths put
  six nets at 0.562 mm (built 2026-11-20, `poured: 0 unrouted, poured-join: 0
  unrouted`): 112 of its 223 segments of track are that wide, one pad of ground that
  a wider track fences off its pour is joined by 3.371 mm of track and a via, and
  KiCad 10.0.8 finds nothing unconnected and no track under its class's width. The
  way round its limiter is 273 mΩ and drops 410 mV at 1.5 A, where at 0.5 mm it was
  318 mΩ and 476 mV: it is about 312 mm of track, and a width for heat does not shorten
  it. A via is not sized: each class has the one via, and no reading counts one. (#10)
- The way a current goes through the board, said and measured. `board.path(jack, power,
  limit, current=1 * A)`, or `pkidl.path(...)` in a block, is a statement: its stops
  are parts, nets (a `Net` or its name) and lists of parts side by side, and
  `current=` is a current with its unit, the new `A` and `mA`. Each two parts in a row
  are a stretch of one net, the one they share or the one named between them; parts
  that share no net, or several with none named, and a part with no pad on a net named
  beside it are problems of the solve with the line. A build that routes the board
  measures each stretch on it and `Built.routed.paths` has the result: the resistance
  of the net's tracks between the two ends as a network, so tracks in parallel count
  as parallel, the drop at the path's current, and the length and narrowest width of
  the way of least resistance. Copper is taken at 20 °C (1.72e-8 Ω·m) and as thick as
  the new `rules(copper=)` says, 0.035 mm (1 oz) where it says nothing; a via and a
  pad add no resistance, and a track joins one where its middle line is within that
  copper; tracks of one layer join where their ends meet, where one ends within the
  other's copper part way along it, not beside its end, and where they cross, a pad and a via join where their copper
  touches, and copper laid twice is one strip. A measurement never stops a build: one
  that raises is a reading that says so. A pour is
  not measured, nor what it reaches: ends no track joins read `not joined by track`,
  with `GND has a pour, which is not measured` where the net has one, and a stretch
  whose net has a pour as well is given as `at most`. What a part is between its own
  pads is not counted. The measurement reports and changes nothing. (#10, #90)
- Copper, and parts, kept clear of something fixed on the board. `board.keepout(sink,
  copper=True)` takes what `board.fixed(name)` gives where it takes an area of a part:
  no track and no pour in the box round the thing's outline on its face, or on either
  face with `both_sides=True`, and no via. It is a rule area in the board that is
  written and a keepout for the router. Pads are let be, so a pin in a hole of a part
  placed `on=` the thing is still reached from the face that is not kept. A pad on a
  net with its middle inside the box that no track can reach is a problem of the solve
  naming the part: a pad on the surface of a kept face, and any pad when both faces
  are kept. It keeps no part out, which
  a fixed thing does already. `board.apart(parts, sink, 5 * mm)` keeps the outline of
  each part that far from the thing's, whichever face either is on. A part that looks
  for its place (`near=`, `after=`, `before=`, a row beside a part) keeps it, and a
  place that is given and breaks it is a problem (`C101 is 0.6 mm from 530002B02500G at
  (186.055, 149.225), and apart(...) keeps it 5 mm from it`). Of `bodies_apart` and
  every `apart` that speaks of a part and a thing the largest holds, two `apart`
  statements are never a conflict, and a part `on=` a thing it is kept apart from is a
  problem. `Routed.kept_out` lists each track and via the routed board has in an area
  kept clear of copper, a fixed thing's or a part's. A board that says none of this is
  built byte for byte as before. (#82)
- Room between parts by how the board is assembled. `board.rules(track=0.5 * mm,
  clearance=0.3 * mm, assembly="hand")` keeps the copper of pads of different parts
  1.27 mm apart, whatever their nets, and the outlines of parts 0.5 mm from each other
  and from what is fixed on the board. `pads_apart=` and `bodies_apart=` say either
  distance as a length, with the word or without, and win over the word's.
  `assembly="machine"` is nothing more than the clearance, as is a board that says none
  of it, which is placed exactly as before. A part that looks for its place (`near=`,
  `after=`, `before=`, a row beside a part) keeps both distances, and a row beside a
  part with no pitch takes the least pitch that does. A place that is given is not
  moved: where it breaks one it is a problem naming the two pads or the two parts
  (`R1.2 is 0.36 mm from J1.1, and the rules keep the pads of different parts 1.27 mm
  apart`). The parts of a row with a pitch said, and a part `on=` something fixed with
  that thing, are not held to `bodies_apart` with each other. `Solution.chosen` says
  what is kept. Neither distance is written into the project, so KiCad's DRC does not
  check them. (#66)
- A row of parts beside a part. `board.row(resistors, beside=switch, toward=Edge.RIGHT)`
  puts the parts side by side on the side of the part that is toward that edge, in the
  order named, from the top down or from the left. Each stands across the row, its
  length away from the part, and all are turned the same way. `pitch=` is the distance
  between their middles; with none they are as close as keeps their outlines clear and
  their pads the rules' clearance apart. The row is as near the part as is clear, level
  with its middle, and further out or along from there, up to 30 mm, where something
  is in the way; `Solution.chosen` says where it went. One with no place is a single
  problem, and none of it is placed. `row()` takes `along=` an edge or `beside=` a part
  with `toward=`, and refuses both or neither. (#75)
- A part at a point of the board. `place(pot, at=(72 * mm, 76 * mm), facing=Edge.TOP)`
  puts the footprint's origin two lengths across and down from the board's top left
  corner, and `of=pot.pin(1)` puts that pin there instead, whichever way round the part
  is. It is not looked for: off the board, over a hole or on another part it is a
  problem. Two different points for one part are a conflict.
- A part on something fixed on the board. `sink = board.fixed("530002B02500G")` has a
  fixed thing by its footprint or its label, and `place(limit, on=sink, at=(12.7 * mm,
  0 * mm))` puts the part at a point of it, in the thing's own coordinates and turned
  as the thing is. The part may overlap that thing, and nothing else.
- An area of the board, and parts said to be inside it. `left = board.area(Edge.LEFT,
  share=1 / 3)` or `board.area(box=((0 * mm, 0 * mm), (30 * mm, 40 * mm)))` makes one,
  and `board.inside(left, [jack, reg5, c1])` keeps each part's whole outline in it:
  a part placed `near=` something or `after=` a part looks for its place there, and one
  whose place is given outside it is a problem. `pkidl.area` and `pkidl.inside` are
  the same for a block function.
- `place(part, near=pin, within=15 * mm, at_least=5 * mm)`: a least distance beside
  the most, pad to pad, for parts that are not to be packed against what they are near.
- Where along an edge a part goes can be said. `place(jack, against=Edge.LEFT,
  along=1 / 3)` puts the middle of its outline a third of the way along the edge, and
  `along=12 * mm` that distance, from the edge's top end or its left end.
  `place(esp, against=Edge.RIGHT, after=sr2)` puts it further along the edge than
  another part, as near that part as there is a clear place, and `before=` the other
  way; the two together are between two parts. With none of them a part is centred
  along its edge, as before.
- A side of a part has a name, and goes to an edge by it. `board.annotate(jack,
  sides={"socket": Edge.LEFT})` names a side of the footprint as it is drawn, for every
  part with that footprint to ask for, and `place(jack, against=Edge.LEFT, outward="socket")`
  puts that side at the edge, on either face of the board. A side that is not named,
  `outward=` with no `against=`, and a part said to be two ways round are each told.
- `board.annotate(display, oriented=True)` says a part's way round matters, and naming
  a side of a part says it of that part. Of a part so marked the way round is never
  chosen for its wiring, and another part with the same footprint is not marked: where
  no `facing=` or `outward=` says it, `Board.solve()` reports `DIG1's way round matters
  and nothing says it`, and a build refuses the board.
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
- `corpus/t0/nextbusclock_NextBusClockV1/board.py`: the third corpus board file, 26
  through-hole parts, written with the library as it stood to see what it could not
  say (`docs/roadmap.md`, milestone 2b). `just corpus` builds and scores it.
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

- A net in a class is in it alone, whatever its name. `write_project` wrote each
  member's name as its `netclass_patterns` entry, and KiCad reads an entry as a
  pattern: as a regular expression and as a wildcard, taking a net that either
  matches whole. So a member `V+` put a net `V` in its class, `A.B` took `AxB`, `D*`
  took `DATA` and `Net-(U1-Pad3)` took `Net-U1-Pad3` (KiCad 10.0.8, by its DRC); a
  net two classes' patterns matched was in both. Each name is now written as the
  pattern only it matches (`pkidl.project.exactly`): a backslash before each
  character an expression reads as other than itself, a brace as `[{]`, and `*` and
  `?` by their numbers. A name with none of those is written as it was, so a project
  whose members have none is the same file. What is left: a net named as another's
  pattern is written, `V\+` beside `V+`, is taken with it.
- A net keeps its pour where what a run left cut off from it can be joined by a
  track. A build's run with the pours known that made every connection and left pads
  of a poured net cut off is no longer routed again at once with that net carried by
  tracks. Its tracks are kept, and the router is asked for the nets cut off alone
  (`<name>-poured-join.dsn`), told of the pours as they fill round those tracks
  (`pkidl.fill.standing`): where
  a track can end in them (`pkidl.fill.landings`), so that it is not aimed at a
  corner of the pour it does not fit, and less each piece of pour that joins only
  pads cut off, so that no track is ended in one. A part of the pour that only the
  gaps round its own net's pads cut from the rest is no piece of its own, and is in a
  plane with the rest. Of the pads a piece apart joins to each other the router is
  told of one (`pkidl.fill.surplus`, `unnet`), and one track joins them. A pad the pour joins to nothing, one no pour
  reaches though one is drawn over it or one alone on a piece apart
  (`pkidl.fill.unreached`), is taken off the pour, `(zone_connect 0)` in the board
  that is written, and joined by the track alone. The pour of a net that is not
  being joined is a keepout, as much of it as would be its plane: drawn in by half a
  track, and only where a pad of its net is on it. Nets joined in one run are free
  to cross each other's pours. What is laid is checked as the run was, by KiCad where
  it is installed: where the check finds nothing it is the routing, `Routed.joined`
  has a line for each net with the track and vias laid, and `Routed.taken_off` and
  `Routed.unjoined` each pad taken off. KiCad's check names each relief it finds
  starved as well as what it leaves unconnected, on any pad of a poured net, and a
  join it finds one after is not kept, as a first run is not; the model's check of a
  join names only what is cut off. A check that still finds something cut off is
  mended the same way, three times at most. What the router says it left unmade of a
  join is in its run and decides nothing where the check finds nothing. Where nothing
  is laid or the check is not passed, the net gives up its pour as before and nothing
  laid to join it is kept. `Routed.cut` has what every check found, and `scripts/corpus.py build`
  prints each line. A board whose first run leaves nothing cut off is built as it
  was, byte for byte. `pkidl.routing.poured` takes how the pours stand as a sixth
  argument, `refill`, and asks its check with the pads taken off as a third.

- The bench supply's two toggle switches are 12.7 mm between centres, where they were
  10.0 mm.

- The bench supply's board file keeps copper from under the four screws that hold its
  meters, on both faces: an area 6 mm across round each hole, and `keepout` of it.

- The bench supply's board file keeps copper from under its heatsink
  (`keepout(sink, copper=True)`) and says how far its electrolytics and its diodes
  stand from it (`apart`), in place of two areas worked out by hand.

- The next-bus clock's board file is assembled by hand: `assembly="hand"` in its rules.
  No pads of different parts are nearer than 1.3 mm, where they were 0.3 mm.

- The bench supply's board file is written again with what milestone 2d added: both
  LM317s on the heatsink, the panel's parts at points, the sense resistors in two banks
  beside their switch, and `assembly="hand"`. Its test no longer runs with the slow
  ones.

- A placement that goes round is kept at one of the placements it goes round, the one
  with the fewest problems and of those the first, and the choices name the parts:
  `K1 and R1: each is placed by where the others are, and they go round 2 placements`.
  It was a problem, `the placement does not settle: each pass moves a part`, naming
  every part and no statement, whatever else the board had. A placement still moving
  after two dozen passes is that problem still, of the parts that moved and the
  statements about them.
- A build takes a pad starved of its pour off the pour, where a track joins it. A pad
  whose thermal relief reaches too little of its pour, or only an island of it that
  nothing else of the net is on, is an error by KiCad's DRC (`starved_thermal`), and
  the build wrote the board with it and said so in `Routed.left`. Where the pads,
  tracks and vias of the pad's net are one piece without the pour, the pad is now
  written with `(zone_connect 0)`, the pours are filled and checked again, by KiCad
  where it is installed, and that is repeated until a check names no such pad, five
  checks at most. No track, via or connection is changed. `Routed.unjoined` has a line
  for each pad taken off (`C5.1 is taken off the pour of GND on B.Cu, which starved its
  relief: a track joins it to the rest of GND`), and `scripts/corpus.py build` prints
  them and writes them to `built.json`. A starved pad that only the pour joins is left
  as it was and is in `Routed.left`, which is now what the last check found of the
  board written, however it was routed. A pad that says `zone_connect` 0 or 2, itself
  or by its footprint, is not touched. Where KiCad is not installed the model finds
  the starved pads of the board to be written (`pkidl.fill.starved`), which it did not
  report before; it names pads KiCad passes. A board with no pour, or whose pours
  starve no pad, is written byte for byte as before. `Cut.starved` marks what was found
  starved, with its layer, and `pkidl.fill.spare` and `pkidl.fill.unjoin` are the pads
  that can be taken off and the board with them off. (#52)
- A board routed again without its pours is checked as the run with them was, and what
  the check finds is in the result as `Routed.left`: the pours are still drawn round
  the tracks, and can leave a pad on a relief that joins an island of pour, which
  KiCad's DRC rejects. The board is written as before and nothing is changed for what
  is found. `scripts/corpus.py build` prints each as `left on the board as built`.
- A part with no place within the distance said is told how far off the nearest place
  is, to the next 0.1 mm up, and what is most in the way: `R8 has no place within 8 mm
  of ESP1.5 ...: the nearest is 9.1 mm from it, with ESP1, IC1 and the board's edge in
  the way`. The distance is the one that would do with every other part where it is: a
  part that turns once this one is placed can change it. It is looked for three times
  as far as was said, no less than 10 mm and no more than 30, and `there is none within
  30 mm either` where there is none; a part said 30 mm or more is not looked for
  further. The problem's text is longer by that.
- Places off a drawn outline are sifted out with the rest when a place near something
  is looked for. Each place in a notch was tried in full, one at a time, before a part
  with no place toward it was told so.
- `Board.solve()` is faster where parts are placed `near=` something: the next-bus
  clock's 26 parts in 1.8 s where it took 47.5 s, the fan controller's 49 in 0.3 s
  where it took 21.7 s, with the same poses, choices and problems. The places a part
  might go are sifted all at once by where its box would be, nearest first, and only
  those left are looked at one by one. pkidl depends on numpy, which shapely already
  brought.
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

- `pkidl.importer.mechanical()` takes a part of the circuit that is a mounting hole on a
  net, such as a grounded standoff, for a hole as well: its entry has `"part": true` and
  the reference `circuit()` gives it, and the part stays in the circuit with its net. A
  part is one when its pads are each a hole with at most a ring, as a hole on no net's
  are, those on a net are all on one net, its largest hole is at least 2 mm across, and
  it draws no body on silkscreen or fab. Such a part was read as any other: SparkFun's
  Qwiic Fingerprint FPC2534 had no holes, and its four `Standoff_Connected` on EGND
  were free to be placed anywhere. `Board.from_inputs` puts each with the new
  `Board.hole(footprint, at, part=)`: it is fixed, so other parts are kept clear of it
  and `board.fixed(...)` finds it; a build writes it where it is, with its reference
  and nets, so routing joins it (`Board.held`); and a statement that places it is a
  problem of the solve (`solve(held=)`). A part placed `near=` its pin is not placed
  by it: that is said as `placed by ST1, which nothing places`.
  `pkidl.importer.renamed(board)` says each, with its net. Of Olimex's 120 current
  KiCad boards, SparkFun's 108 and Olimex's 7 EAGLE boards, 53 parts on 19 boards are
  read so: besides the standoffs, RedBoard_Edge's two `STANDOFF_GROUNDING`, the TERES
  boards' `MountingHole`s and ESP32-ADF's `MH`s on GND, eduArdu's touch pads `CC1` to
  `CC7` (4.3 mm mounting holes on signal nets), the Qwiic Power Meter's 6.5 mm current
  lugs `J8` and `J9`, and two case platforms that draw the board's outline,
  STMP157-OLinuXino-LIME2's `LIME2_PLATFORM1` and AM3352-OLinuXino's `U$1`, which are
  now fixed where they draw it. The hole rule alone, with a pad on a net, takes 758
  parts on 165 of those boards, and 48 of the corpus's: pin headers, resistors, and the
  bench supply's banana posts, which its board file places in a row. No corpus board's
  inputs change.
- `pkidl.measure.regions`, and the scorecard's `poured_nets` and `split_pours` with it,
  takes a teardrop for no pour. KiCad saves each teardrop as a zone, and each was
  counted as a piece of its net's pour: on GateMateA1-EVB, whose 1,330 zones are 1,312
  teardrops, 261 nets read as poured and 205 as split, where 7 and 7 are. No corpus
  reference has a teardrop, so no score changes. (#108)
- `pkidl.importer` names apart what a board names alike, and says so in
  `pkidl.importer.renamed(board)`, which `scripts/corpus.py extract` prints. Parts that
  share a reference (the TERES boards' mounting holes with a pad on ground, all
  `MountingHole`; ESP32-ADF's two `MH3`) made `Board.from_inputs` raise `MountingHole
  is in the circuit twice`: the first by position on the board, x then y, keeps the
  reference and the others are given it with `_2`, `_3` and on, past any reference the
  board has. Versions of one footprint name that differ in their pads (number, type,
  shape, place, size or drill) were written as the one most parts carry, so a part
  with another had pads that were not its own, and LCD-OLinuXino-15.6FHD raised `its
  footprint ... has no pad 0`: each other version is now written under the name with
  `_2`, `_3` and on, and its parts and holes point at it. Versions that differ only in
  their drawings keep the rule of the most parts. Of the corpus, the SWR meter's R8,
  drilled 1.001 mm where the other resistors of its footprint are drilled 0.8 mm, is
  now `Resistor_Horizontal_RM10mm_2`. (#108)
- `pkidl.importer.mechanical()` takes for mounting holes only a footprint whose pads,
  all drilled and on no net, are each a hole with at most a ring of copper round it:
  unplated, or a round pad on a round drill or an oval one on an oval drill, centred
  on it. Any footprint of drilled pads on no net was a hole, so AgonLight2-PROTO's 554
  square prototyping pads read as 554 mounting holes, and SMT-PROTOBOARD's 32 grids
  and headers as 32. A hole with a ring of vias round it is still one, and so is a
  heatsink's pair of pins. `pkidl.importer.renamed(board)` says, a line for each
  footprint name with how many, the footprints of drilled pads on no net that are not
  holes, so a hole left out can be seen. (#108)
- `pkidl.importer.mechanical()` reads an outline drawn in a footprint, as KiCad takes
  Edge.Cuts items in a footprint for part of the board's outline: each where it is on
  the board, by the footprint's position, turn and side, and a rectangle turned off
  square as the polygon of its corners. It read none, and said nothing; six of
  Olimex's boards (FOSDEM-MUSIC-BOX, Lime2-SHIELD, OLIMEXINO-2560, STMP1-OLinuXino,
  OLIMEXINO-STM32F3, STMP157-OLinuXino-LIME2) have their outline only in a case's
  platform or a logo footprint, and `Board.from_inputs` then raised
  `min() iterable argument is empty`. `footprints()` leaves those items out of the
  footprint it writes: placed with them, the outline was drawn twice, and KiCad's DRC
  reported it as `malformed outline (self-intersecting)`. Where the footprint is a
  part of the circuit, as OLIMEXINO-2560's and OLIMEXINO-STM32F3's `PLATFORM1` and
  STMP157-OLinuXino-LIME2's `LIME2_PLATFORM1` are, the part is still placed as any
  other, and `pkidl.importer.renamed(board)` says so, naming it. (#108)
- `Board.edge()` joins two ends of an outline no more than 10 micrometres apart, as
  KiCad does: KiCad 10.0.8's DRC closes a square with a 10.0 um gap in it and not one
  with 10.1 um (`pkidl.edge.JOIN`). Ends are measured apart in whole nanometres, as
  KiCad measures them, so a 10.0 um gap joins wherever the board sits. Ends join in
  pairs, the closest first, and never in chains: an 8 um line in a corner's gap takes
  one of the corner's ends, not both, as KiCad's DRC has it. So the order the items
  are drawn in does not change the outline, and no end moves more than 10 um. Minibot's outline, with gaps of up to 6.6 um, was refused as not closing;
  and ESP32-PoE-ISO's slot, whose ends miss each other by 2 and 8.5 nm, was taken for
  lines that close nothing and left out of its board. eduArdu's outline
  (gaps of 12 and 25 um) and OSHW-GHOST's (25 um) are still refused, as KiCad's DRC
  refuses them. (#108)
- `pkidl.importer.mechanical()` reads a hole with an oval drill, `(drill oval W H)`: it
  raised `could not convert string to float: 'oval'`, and MOD-ENV, Minibot and
  ESP32-PoE-ISO of Olimex's boards could not be read. An oval drill is
  `[x, y, width, height, angle]` in `drills`, its sizes along the pad's own axes and
  the pad's angle on the board; a round one is `[x, y, diameter]` as before. (#108)
- A path's measurement reads as it should at its edges. A path of one stretch with no
  figure says `its one stretch is not measured`, where it said `none of its 1
  stretches is measured`. `float("nan") * A` is refused as `a current is a number of
  amps, not nan: write 1 * A`, where it was `cannot convert float NaN to integer`, and
  an infinite number of them the same way, `not inf`, where it was an `OverflowError`.
  And `scripts/corpus.py build` prints each
  path a board says as it was measured, and has them in `built.json` as `paths`. (#94)
- A pad's copper is where its drill's `(offset ...)` puts it. KiCad draws the copper
  of such a pad off its hole, turned with the pad, and the solver took it as centred
  on the hole: on the bench supply an LED's pad and a resistor's, 0.34 mm apart by
  its reckoning, overlapped by 0.1 mm, and two regulators against the top edge had
  their copper 0.15 mm from it where the rules say 0.5 mm. The clearance between
  pads, their distance from the board's edge and a part's outline now take the copper
  where it is. `near=`, `within=`, `at_least=` and `inset=` are still to the hole. (#68)
- A footprint whose courtyard or body is drawn with an arc is as large as the arc. The
  solver took an arc for its two ends and the point between, so a round LED's
  courtyard was 1.65 mm short above and below, and a resistor's pad was placed inside
  it: KiCad's `pth_inside_courtyard` on the next-bus clock.
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
