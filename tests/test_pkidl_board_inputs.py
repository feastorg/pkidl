"""pkidl.Board.from_inputs: a board from its circuit, its mechanical requirements and its
footprints, with the outline drawn and the holes placed."""

import json
from pathlib import Path

import pytest

from pkidl import Board
from pkidl.footprint import footprint_path
from pkidl.importer import circuit, footprints, mechanical
from pkidl.sexpr import Node, dumps, parse

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


@pytest.fixture
def inputs(tmp_path: Path) -> Path:
    """A directory of inputs read from SOURCE, as ``scripts/corpus.py extract`` writes one."""
    source = parse(SOURCE)
    (tmp_path / "circuit.json").write_text(json.dumps(circuit(source)))
    (tmp_path / "mechanical.json").write_text(json.dumps(mechanical(source)))
    for name, lib in footprints(source)[0].items():
        path = tmp_path / "footprints" / footprint_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dumps(lib) + "\n")
    return tmp_path


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
