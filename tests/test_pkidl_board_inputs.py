"""pkidl.Board.from_inputs: a board from its circuit, its mechanical requirements and its
footprints, with the outline drawn and the holes placed."""

import json
import math
from pathlib import Path

import pytest

from pkidl import Board, Edge, mm
from pkidl.build import BuildError
from pkidl.footprint import footprint_path
from pkidl.importer import circuit, footprints, mechanical
from pkidl.placement import Pose
from pkidl.sexpr import Node, dumps, find, find_all, parse
from pkidl.units import Length

# A board to take inputs from: a part with one pad on no net, a two-hole bracket turned and
# on the back, and two holes that share the reference KiCad gives a footprint with no symbol.
SOURCE = """(kicad_pcb
  (gr_line (start 0 0) (end 40 0) (layer "Edge.Cuts"))
  (gr_line (start 40 0) (end 40 30) (layer "Edge.Cuts"))
  (gr_arc (start 40 30) (mid 20 36) (end 0 30) (layer "Edge.Cuts"))
  (gr_line (start 0 30) (end 0 0) (layer "Edge.Cuts"))
  (footprint "Device:R" (layer "F.Cu") (at 10 10 90)
    (property "Reference" "R1" (at 0 -2) (layer "F.SilkS") (uuid "a1"))
    (property "Value" "10k" (at 0 2) (layer "F.Fab") (uuid "a2"))
    (pad "1" smd rect (at -1 0 90) (size 1 1) (layers "F.Cu") (net "VCC") (uuid "a3"))
    (pad "2" smd rect (at 1 0 90) (size 1 1) (layers "F.Cu") (net "OUT") (uuid "a4"))
    (pad "3" smd rect (at 0 1 90) (size 1 1) (layers "F.Cu") (uuid "a5")))
  (footprint "Mech:Bracket" (layer "B.Cu") (at 20 15 90)
    (property "Reference" "H1" (at 0 0) (layer "B.SilkS") (uuid "b1"))
    (pad "" np_thru_hole circle (at 0 0) (size 3 3) (drill 3) (layers "*.Cu") (uuid "b2"))
    (pad "" np_thru_hole circle (at 6 2) (size 2 2) (drill 2) (layers "*.Cu") (uuid "b3")))
  (footprint "Mech:M3" (layer "F.Cu") (at 3 3)
    (property "Reference" "REF**" (at 0 0) (layer "F.SilkS") (uuid "c1"))
    (pad "" np_thru_hole circle (at 0 0) (size 3.2 3.2) (drill 3.2) (layers "*.Cu") (uuid "c2")))
  (footprint "Mech:M3" (layer "F.Cu") (at 37 3)
    (property "Reference" "REF**" (at 0 0) (layer "F.SilkS") (uuid "d1"))
    (pad "" np_thru_hole circle (at 0 0) (size 3.2 3.2) (drill 3.2) (layers "*.Cu")
      (uuid "d2"))))"""


def _inputs(d: Path, source: Node) -> Path:
    """*d*, holding the inputs read from *source*, as ``scripts/corpus.py extract`` writes
    them."""
    (d / "circuit.json").write_text(json.dumps(circuit(source)))
    (d / "mechanical.json").write_text(json.dumps(mechanical(source)))
    for name, lib in footprints(source)[0].items():
        path = d / "footprints" / footprint_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dumps(lib) + "\n")
    return d


@pytest.fixture
def inputs(tmp_path: Path) -> Path:
    """A directory of inputs read from SOURCE."""
    return _inputs(tmp_path, parse(SOURCE))


def _written(board: Board) -> Node:
    return parse(dumps(board.sexpr()))


def _uuids(node: Node) -> list[str]:
    found = [str(node[1])] if node and node[0] == "uuid" else []
    for child in node[1:]:
        if isinstance(child, list) and child:
            found += _uuids(child)
    return found


def test_the_outline_is_drawn_and_the_holes_are_where_they_were(inputs):
    built = mechanical(_written(Board.from_inputs(inputs)))
    assert built == mechanical(parse(SOURCE))
    # The bracket's second hole is only where it was if its turn and its side are kept.
    assert built["holes"][0]["drills"] == [[20.0, 15.0, 3.0], [22.0, 9.0, 2.0]]
    assert [h["at"] for h in built["holes"][1:]] == [[3.0, 3.0], [37.0, 3.0]]
    assert len(built["outline"]) == 4


def test_the_circuit_and_its_footprints_are_loaded_and_no_part_is_placed(inputs):
    board = Board.from_inputs(inputs)
    assert board.circuit.data == circuit(parse(SOURCE))
    assert set(board.library) == {"Device:R", "Mech:Bracket", "Mech:M3"}
    assert circuit(_written(board)) == {"parts": [], "nets": []}


def test_the_boards_parts_pins_and_nets_are_its_circuits(inputs):
    board = Board.from_inputs(inputs)
    r1 = board["R1"]
    assert (r1.value, r1.footprint) == ("10k", "Device:R")
    assert board.parts("R1") == board.parts() == (r1,)
    assert [n.name for n in board.nets()] == ["OUT", "VCC"]
    # The footprint says which pins there are; the circuit, which of them are on a net.
    assert [(p.number, p.net and p.net.name) for p in r1.pins()] == [
        ("1", "VCC"), ("2", "OUT"), ("3", None)]  # fmt: skip
    assert board.rails("VCC") == (board.net("VCC"),)
    assert r1.signal_net == board.net("OUT")
    (sense,) = board.name_nets({"OUT": "SENSE"})
    assert str(sense) == "SENSE" and r1.pin_on("SENSE") == r1.pin(2)
    assert board.circuit.data == circuit(parse(SOURCE))  # the circuit is as it was


def test_a_board_file_passes_its_own_path(inputs):
    board_file = inputs / "board.py"
    board_file.write_text("")
    assert dumps(Board.from_inputs(board_file).sexpr()) == dumps(Board.from_inputs(inputs).sexpr())
    assert dumps(Board.from_inputs(str(inputs)).sexpr()) == dumps(Board.from_inputs(inputs).sexpr())


def test_holes_sharing_a_reference_are_items_of_their_own(inputs):
    uuids = _uuids(_written(Board.from_inputs(inputs)))
    assert len(uuids) > 10 and len(set(uuids)) == len(uuids)


def test_an_outline_drawn_in_a_footprint_is_drawn_once(tmp_path):
    # A case's platform: its outline and a mounting hole in one footprint, and no
    # outline on the board, as Olimex's STMP1-OLinuXino has it.
    source = parse("""(kicad_pcb (footprint "Case:Platform" (layer "F.Cu") (at 10 10)
      (property "Reference" "REF**")
      (fp_rect (start 0 0) (end 40 30) (layer "Edge.Cuts"))
      (fp_line (start 0 0) (end 40 30) (layer "Cmts.User"))
      (pad "" np_thru_hole circle (at 4 4) (size 3.2 3.2) (drill 3.2) (layers "*.Cu"))))""")
    (tmp_path / "circuit.json").write_text(json.dumps(circuit(source)))
    (tmp_path / "mechanical.json").write_text(json.dumps(mechanical(source)))
    (lib,) = footprints(source)[0].values()
    assert [str(c[0]) for c in lib if isinstance(c, list) and str(c[0]).startswith("fp_")] == [
        "fp_line"]  # the platform less its outline  # fmt: skip
    path = tmp_path / "footprints" / footprint_path("Case:Platform")
    path.parent.mkdir(parents=True)
    path.write_text(dumps(lib))
    board = Board.from_inputs(tmp_path)
    edge = board.edge()
    assert edge is not None and edge.bounds == (10, 10, 50, 40)
    # KiCad takes an outline drawn twice for one that crosses itself.
    assert mechanical(_written(board))["outline"] == [
        {"type": "gr_rect", "start": [10.0, 10.0], "end": [50.0, 40.0]}]  # fmt: skip


# A grounded standoff, turned, as SparkFun's Qwiic Fingerprint FPC2534 has four, and two
# parts on its net.
STANDOFF = """(kicad_pcb
  (gr_rect (start 0 0) (end 40 30) (layer "Edge.Cuts"))
  (footprint "Hw:Standoff" (layer "{side}.Cu") (at 5 6 30)
    (property "Reference" "ST1") (property "Value" "Standoff")
    (pad "1" thru_hole circle (at 0 0) (size 4.5 4.5) (drill 3.1) (layers "*.Cu")
      (net "EGND")))
  (footprint "Device:R" (layer "F.Cu") (at 20 15)
    (property "Reference" "R1") (property "Value" "0")
    (pad "1" smd rect (at -1 0) (size 1 1) (layers "F.Cu") (net "EGND"))
    (pad "2" smd rect (at 1 0) (size 1 1) (layers "F.Cu") (net "GND")))
  (footprint "Device:R" (layer "F.Cu") (at 25 15)
    (property "Reference" "C1") (property "Value" "1u")
    (pad "1" smd rect (at -1 0) (size 1 1) (layers "F.Cu") (net "EGND"))
    (pad "2" smd rect (at 1 0) (size 1 1) (layers "F.Cu") (net "GND"))))"""


def _standoff(d: Path, side: str = "F") -> Board:
    return Board.from_inputs(_inputs(d, parse(STANDOFF.format(side=side))))


def _footprint(written: Node, ref: str) -> Node:
    named = ["property", "Reference", ref]
    (fp,) = [fp for fp in find_all(written, "footprint")
             if named in [p[:3] for p in find_all(fp, "property")]]  # fmt: skip
    return fp


@pytest.mark.parametrize("side", ["F", "B"])
def test_a_hole_on_a_net_is_built_where_the_board_has_it_with_its_net(tmp_path, side):
    board = _standoff(tmp_path, side)
    standoff = board.fixed("Standoff")
    assert board.held == {"ST1": standoff} and board["ST1"].pin(1).net == board.net("EGND")
    board.place(board["R1"], at=(20 * mm, 15 * mm))
    board.place(board["C1"], at=(25 * mm, 15 * mm))
    board.rules(track=0.25 * mm, clearance=0.2 * mm)  # which keep copper off the edge
    built = board.build(tmp_path / "out", "t")
    # Placed by the board, where it has it, turned as it has it, on its side.
    assert built.solution.free == ()
    assert built.solution.poses["ST1"] == Pose(Length(5_000_000), Length(6_000_000), 30.0,
                                               side == "B")  # fmt: skip
    st1 = _footprint(parse(built.board.read_text()), "ST1")
    assert find(st1, "at") == ["at", "5", "6", "30"]
    assert find(st1, "layer") == ["layer", f"{side}.Cu"]
    assert find(find_all(st1, "pad")[0], "net") == ["net", "EGND"]
    assert len(find_all(parse(built.board.read_text()), "footprint")) == 3  # not put twice
    # Nothing else places it.
    board.place(board["ST1"], at=(30 * mm, 20 * mm))
    with pytest.raises(BuildError, match=r"ST1 is fixed on the board, as Standoff at \(5, 6\): "
                                         "nothing places it"):  # fmt: skip
        board.build(tmp_path / "out", "t")


def _problems(board: Board) -> list[str]:
    return [p.text for p in board.solve().problems]


def test_what_is_said_of_a_held_part_is_checked_where_the_board_has_it(tmp_path):
    def board() -> Board:
        b = _standoff(tmp_path)
        b.place(b["R1"], at=(20.13 * mm, 15 * mm))
        b.place(b["C1"], at=(25 * mm, 15 * mm))
        return b

    assert _problems(board()) == []
    inside = board()
    inside.inside(inside.area(box=(("30 mm", "20 mm"), ("39 mm", "29 mm"))), [inside["ST1"]])
    assert _problems(inside) == [
        "ST1 is held where the board has it, as Standoff at (5, 6), and is not inside "
        "area(box=((30 mm, 20 mm), (39 mm, 29 mm))): it reaches 29.198557 mm past its left "
        "side"]  # fmt: skip
    apart = board()
    other = apart.hole("Hw:Standoff", (13, 6))
    apart.apart(apart["ST1"], other, 10 * mm)
    assert _problems(apart) == [
        "ST1 is held where the board has it, as Standoff at (5, 6), 0.727886 mm from "
        "Standoff at (13, 6), and apart(ST1, Standoff at (13, 6), 10 mm) keeps it 10 mm "
        "from it"]  # fmt: skip
    align = board()
    align.align(align["ST1"], align["R1"], grid="1 mm")
    assert _problems(align) == [
        "align(R1, ST1, grid=1 mm) does not hold: R1 and ST1 are 14.13 mm apart across the "
        "board, 14.1 steps"]  # fmt: skip
    # Copper kept from it on both faces cuts its pad off, as any part's.
    kept = board()
    kept.keepout(kept.fixed("Standoff"), copper=True, both_sides=True)
    assert _problems(kept) == [
        "ST1.1 is inside the outline of Standoff at (5, 6), which is kept clear of copper on "
        "both sides: no track can reach it"]  # fmt: skip
    # A part is kept off it as off any hole.
    over = _standoff(tmp_path)
    over.place(over["R1"], at=(6 * mm, 6 * mm))
    over.place(over["C1"], at=(25 * mm, 15 * mm))
    assert _problems(over) == ["R1 is over Standoff at (5, 6)"]


def test_held_parts_whose_copper_on_two_nets_meets_are_said_to(tmp_path):
    def held(x: float, net: str, ref: str) -> str:
        return (f'(footprint "Hw:Standoff" (layer "F.Cu") (at {x} 6) (property "Reference" '
                f'"{ref}") (pad "1" thru_hole circle (at 0 0) (size 4.5 4.5) (drill 3.1) '
                f'(layers "*.Cu") (net "{net}")))')  # fmt: skip

    def problems(x: float, net: str, rules: bool) -> list[str]:
        source = parse('(kicad_pcb (gr_rect (start 0 0) (end 40 30) (layer "Edge.Cuts")) '
                       f'{held(5, "EGND", "ST1")} {held(x, net, "ST2")})')  # fmt: skip
        board = Board.from_inputs(_inputs(tmp_path, source))
        if rules:
            board.rules(track=0.25 * mm, clearance=0.2 * mm)
        return _problems(board)

    # Neither is moved: what is wrong is said.
    assert problems(8, "GND", False) == [
        "ST1.1 on EGND overlaps ST2.1 on GND, both held where the board has them"]  # fmt: skip
    assert problems(9.6, "GND", True) == [
        "ST1.1 on EGND is 0.1 mm from ST2.1 on GND, both held where the board has them, and "
        "the rules keep copper 0.2 mm apart"]  # fmt: skip
    assert problems(9.6, "GND", False) == []  # no rule says how far
    assert problems(8, "EGND", True) == []  # one net


def test_a_part_is_placed_by_a_held_part_as_by_any(tmp_path):
    near = _standoff(tmp_path)
    near.place(near["R1"], near=near["ST1"].pin(1), within=6 * mm)
    near.place(near["C1"], at=(25 * mm, 15 * mm))
    solution = near.solve()
    assert solution.problems == () and solution.free == ()
    r1 = solution.poses["R1"]
    assert math.dist((r1.x.mm, r1.y.mm), (5, 6)) <= 6 + 1  # its pad within 6 mm of the pin
    between = _standoff(tmp_path)
    between.place(between["R1"], at=(25 * mm, 16 * mm))
    between.place(between["C1"], between=(between["ST1"], between["R1"]))
    solution = between.solve()
    assert solution.problems == ()
    assert (solution.poses["C1"].x.mm, solution.poses["C1"].y.mm) == (15, 11)
    beside = _standoff(tmp_path)
    beside.row(beside.parts("R1", "C1"), beside=beside["ST1"], toward=Edge.RIGHT)
    solution = beside.solve()
    assert solution.problems == () and {"R1", "C1"} <= set(solution.poses)
    assert all(solution.poses[r].x.mm > 5 for r in ("R1", "C1"))


def test_a_hole_is_its_part_s_footprint(tmp_path):
    board = _standoff(tmp_path)
    with pytest.raises(ValueError, match="hole\\('Device:R'\\): ST1's footprint is 'Hw:Standoff'"):
        board.hole("Device:R", (30, 20), part=board["ST1"])


def test_a_footprint_of_holes_takes_its_holes_and_its_body_from_the_board(tmp_path):
    # A case's platform: two holes 50 mm apart and a peg drawn as a circle, as
    # STMP157-OLinuXino-LIME2's; and a heatsink's pins with its body drawn in lines.
    text = """(kicad_pcb
      (gr_rect (start 0 0) (end 80 60) (layer "Edge.Cuts"))
      (footprint "Case:Platform" (layer "F.Cu") (at 10 10)
        (property "Reference" "REF**")
        (fp_circle (center 25 40) (end 27 40) (layer "B.CrtYd"))
        (pad "" np_thru_hole circle (at 0 0) (size 3.3 3.3) (drill 3.3) (layers "*.Cu"))
        (pad "" np_thru_hole circle (at 50 0) (size 3.3 3.3) (drill 3.3) (layers "*.Cu")))
      (footprint "Mech:Sink" (layer "F.Cu") (at 10 50)
        (property "Reference" "REF**")
        (fp_line (start -2 -4) (end 22 -4) (layer "F.Fab"))
        (fp_line (start 22 -4) (end 22 4) (layer "F.Fab"))
        (fp_line (start 22 4) (end -2 4) (layer "F.Fab"))
        (pad "" np_thru_hole circle (at 0 0) (size 2 2) (drill 2) (layers "*.Cu"))
        (pad "" np_thru_hole circle (at 20 0) (size 2 2) (drill 2) (layers "*.Cu")))
      (footprint "Device:R" (layer "F.Cu") (at 70 30)
        (property "Reference" "R1") (property "Value" "0")
        (pad "1" smd rect (at -1 0) (size 1 1) (layers "F.Cu") (net "A"))
        (pad "2" smd rect (at 1 0) (size 1 1) (layers "F.Cu") (net "B"))))"""
    source = parse(text)

    def at(x: float, y: float) -> list[str]:
        board = Board.from_inputs(_inputs(tmp_path, source))
        board.place(board["R1"], at=(x * mm, y * mm))
        return _problems(board)

    assert at(35, 10) == []  # between the platform's holes
    assert at(35, 30) == []  # over the platform's middle
    assert at(10, 10) == ["R1 is over Platform at (10, 10)"]  # on a hole
    assert at(35, 50) == ["R1 is over Platform at (10, 10)"]  # on the peg
    assert at(20, 50) == ["R1 is over Sink at (10, 50)"]  # between the pins, under the body
    # The same platform held, its holes on ground: a part looks for its place between them.
    ring = '(pad "1" thru_hole circle (at {}) (size 6 6) (drill 3.3) (layers "*.Cu") (net "GND"))'
    # In the board's top left corner, so a part by it is over its middle.
    corner = text.replace(
        '(footprint "Case:Platform" (layer "F.Cu") (at 10 10)',
        '(footprint "Case:Platform" (layer "F.Cu") (at 3 3)',
    )
    held = parse(corner.replace('"Reference" "REF**"', '"Reference" "PL1"', 1)
                 .replace('(pad "" np_thru_hole circle (at 0 0) (size 3.3 3.3) (drill 3.3) '
                          '(layers "*.Cu"))', ring.format("0 0"))
                 .replace('(pad "" np_thru_hole circle (at 50 0) (size 3.3 3.3) (drill 3.3) '
                          '(layers "*.Cu"))', ring.format("50 0")))  # fmt: skip
    board = Board.from_inputs(_inputs(tmp_path, held))
    assert set(board.held) == {"PL1"}
    board.place(board["R1"], near=board["PL1"], within=4 * mm)
    solution = board.solve()
    assert solution.problems == ()
    r1 = solution.poses["R1"]
    assert r1.x.mm < 10 and r1.y.mm < 10  # by the hole in the corner, over the platform
    # An area kept clear of a part over the platform's middle is clear of the platform.
    quiet = Board.from_inputs(_inputs(tmp_path, held))
    (area,) = quiet.annotate(quiet["R1"], quiet=((-1 * mm, -1 * mm), (1 * mm, 1 * mm)))
    quiet.keepout(area, copper=True)
    quiet.place(quiet["R1"], at=(30 * mm, 20 * mm))
    assert _problems(quiet) == []


def test_a_part_whose_footprint_is_missing_is_named(inputs):
    (inputs / "footprints" / footprint_path("Device:R")).unlink()
    with pytest.raises(ValueError, match="R1: no footprint 'Device:R' at .*R.kicad_mod"):
        Board.from_inputs(inputs)


def test_a_hole_whose_footprint_is_missing_is_named(inputs):
    (inputs / "footprints" / footprint_path("Mech:Bracket")).unlink()
    with pytest.raises(ValueError, match=r"the hole at \[20.0, 15.0\]: no footprint"):
        Board.from_inputs(inputs)


def test_a_part_on_a_pad_its_footprint_lacks_is_named(inputs):
    c = json.loads((inputs / "circuit.json").read_text())
    c["parts"][0]["pads"]["7"] = "GND"
    (inputs / "circuit.json").write_text(json.dumps(c))
    with pytest.raises(ValueError, match="R1: its footprint 'Device:R' has no pad 7"):
        Board.from_inputs(inputs)


@pytest.mark.parametrize(
    "item",
    [
        {"type": "gr_line", "start": [0.0, 0.0], "end": [40.0, 0.0]},
        {"type": "gr_arc", "start": [40.0, 30.0], "mid": [20.0, 36.0], "end": [0.0, 30.0]},
        {"type": "gr_rect", "start": [0.0, 0.0], "end": [40.0, 30.0]},
        {"type": "gr_circle", "center": [20.0, 15.0], "end": [30.0, 15.0]},
        {"type": "gr_poly", "pts": [[0.0, 0.0], [40.0, 0.0], [20.0, 30.0]]},
    ],
    ids=lambda item: item["type"],
)
def test_each_kind_of_edge_is_written_as_drawn(item):
    board = Board()
    board.outline([item])
    assert mechanical(_written(board))["outline"] == [item]


def test_something_edge_cuts_is_not_drawn_with_is_refused():
    with pytest.raises(ValueError, match="gr_text"):
        Board().outline([{"type": "gr_text", "start": [0, 0]}])


def _extent(*items: dict) -> tuple[float, float, float, float]:
    board = Board()
    board.outline(items)
    assert board.extent is not None
    return board.extent


def test_the_extent_is_the_box_of_what_was_drawn():
    assert _extent({"type": "gr_rect", "start": [5, 30], "end": [40, 2]}) == (5, 2, 40, 30)
    assert _extent({"type": "gr_circle", "center": [20, 15], "end": [30, 15]}) == (10, 5, 30, 25)
    assert _extent({"type": "gr_poly", "pts": [[0, 0], [40, 0], [20, 30]]}) == (0, 0, 40, 30)
    two_lines = [{"type": "gr_line", "start": [0, 0], "end": [4, 0]},
                 {"type": "gr_line", "start": [4, 0], "end": [4, -3]}]  # fmt: skip
    assert _extent(*two_lines) == (0, -3, 4, 0)


S = 0.7071067811865476  # the 45-degree point of a unit circle


@pytest.mark.parametrize(
    ("start", "mid", "end", "box"),
    [
        # A quarter turn stays inside the corner it spans.
        ((1, 0), (S, S), (0, 1), (0, 0, 1, 1)),
        # The same two ends the long way round reach the other three sides.
        ((1, 0), (-S, -S), (0, 1), (-1, -1, 1, 1)),
        # A cap bulges past the chord between its ends.
        ((S, S), (0, 1), (-S, S), (-S, S, S, 1)),
        # A half turn through the left.
        ((0, 1), (-1, 0), (0, -1), (-1, -1, 0, 1)),
    ],
)
def test_the_extent_follows_an_arc_where_it_bulges(start, mid, end, box):
    there = _extent({"type": "gr_arc", "start": start, "mid": mid, "end": end})
    back = _extent({"type": "gr_arc", "start": end, "mid": mid, "end": start})
    assert there == back == pytest.approx(box, abs=1e-6)
