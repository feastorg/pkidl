"""pkidl.paths: the way a current goes through a board, said and then measured.

A path is said in a board file and measured on the board a build routed. The router
here hands back what a test wrote, so each track is where the test put it.
"""

# The refusals below are of arguments of the wrong type, written on purpose.
# pyright: reportArgumentType=false, reportCallIssue=false

import hashlib
import json
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path as File

import pytest

import pkidl
from pkidl import A, Board, Edge, degC, mA, mm
from pkidl.build import BuildError
from pkidl.circuit import Circuit
from pkidl.dsn import Via, Wire
from pkidl.footprint import footprint_path, pad_xy
from pkidl.importer import circuit, footprints, mechanical
from pkidl.intent import Path, Rules, Stretch, path, rules
from pkidl.neck import KICAD, MODEL, Piece
from pkidl.paths import Measured, Reading, needed, widths
from pkidl.project import NetClass
from pkidl.routing import Job, Run
from pkidl.sexpr import dumps, find_all, parse
from pkidl.units import Length, Rise

HERE = "test_pkidl_paths.py"

# A board 140 by 40 mm with its corner at (100, 50). Two headers on IN and GND, one
# at each end; a transistor with one pad on IN and two on OUT; a header on OUT and
# GND; two resistors side by side from OUT to LOAD; and a header on LOAD and GND.
# A header's pins are in holes, and the transistor and the resistors are on the front.
SOURCE = """(kicad_pcb
  (gr_rect (start 100 50) (end 240 90) (layer "Edge.Cuts"))
  (footprint "Conn:P2" (layer "F.Cu") (at 0 0)
    (property "Reference" "J1" (at 0 0) (layer "F.SilkS"))
    (property "Value" "P" (at 0 0) (layer "F.Fab"))
    (fp_rect (start -1.5 -1.5) (end 1.5 5.5) (stroke (width 0.05) (type solid)) (fill no)
      (layer "F.CrtYd"))
    (pad "1" thru_hole circle (at 0 0) (size 2 2) (drill 1) (layers "*.Cu") (net "IN"))
    (pad "2" thru_hole circle (at 0 4) (size 2 2) (drill 1) (layers "*.Cu") (net "GND")))
  (footprint "Conn:P2" (layer "F.Cu") (at 0 0)
    (property "Reference" "J2" (at 0 0) (layer "F.SilkS"))
    (property "Value" "P" (at 0 0) (layer "F.Fab"))
    (fp_rect (start -1.5 -1.5) (end 1.5 5.5) (stroke (width 0.05) (type solid)) (fill no)
      (layer "F.CrtYd"))
    (pad "1" thru_hole circle (at 0 0) (size 2 2) (drill 1) (layers "*.Cu") (net "IN"))
    (pad "2" thru_hole circle (at 0 4) (size 2 2) (drill 1) (layers "*.Cu") (net "GND")))
  (footprint "Conn:P2" (layer "F.Cu") (at 0 0)
    (property "Reference" "J3" (at 0 0) (layer "F.SilkS"))
    (property "Value" "P" (at 0 0) (layer "F.Fab"))
    (fp_rect (start -1.5 -1.5) (end 1.5 5.5) (stroke (width 0.05) (type solid)) (fill no)
      (layer "F.CrtYd"))
    (pad "1" thru_hole circle (at 0 0) (size 2 2) (drill 1) (layers "*.Cu") (net "OUT"))
    (pad "2" thru_hole circle (at 0 4) (size 2 2) (drill 1) (layers "*.Cu") (net "GND")))
  (footprint "Conn:P2" (layer "F.Cu") (at 0 0)
    (property "Reference" "J4" (at 0 0) (layer "F.SilkS"))
    (property "Value" "P" (at 0 0) (layer "F.Fab"))
    (fp_rect (start -1.5 -1.5) (end 1.5 5.5) (stroke (width 0.05) (type solid)) (fill no)
      (layer "F.CrtYd"))
    (pad "1" thru_hole circle (at 0 0) (size 2 2) (drill 1) (layers "*.Cu") (net "LOAD"))
    (pad "2" thru_hole circle (at 0 4) (size 2 2) (drill 1) (layers "*.Cu") (net "GND")))
  (footprint "Device:Q" (layer "F.Cu") (at 0 0)
    (property "Reference" "Q1" (at 0 0) (layer "F.SilkS"))
    (property "Value" "Q" (at 0 0) (layer "F.Fab"))
    (fp_rect (start -3 -2) (end 3 2) (stroke (width 0.05) (type solid)) (fill no)
      (layer "F.CrtYd"))
    (pad "1" smd rect (at -2 0) (size 1 1) (layers "F.Cu") (net "IN"))
    (pad "2" smd rect (at 2 -1) (size 1 1) (layers "F.Cu") (net "OUT"))
    (pad "3" smd rect (at 2 1) (size 1 1) (layers "F.Cu") (net "OUT")))
  (footprint "Device:R" (layer "F.Cu") (at 0 0)
    (property "Reference" "R1" (at 0 0) (layer "F.SilkS"))
    (property "Value" "1" (at 0 0) (layer "F.Fab"))
    (fp_rect (start -1.8 -0.9) (end 1.8 0.9) (stroke (width 0.05) (type solid)) (fill no)
      (layer "F.CrtYd"))
    (pad "1" smd rect (at -1 0) (size 1 1.2) (layers "F.Cu") (net "OUT"))
    (pad "2" smd rect (at 1 0) (size 1 1.2) (layers "F.Cu") (net "LOAD")))
  (footprint "Device:R" (layer "F.Cu") (at 0 0)
    (property "Reference" "R2" (at 0 0) (layer "F.SilkS"))
    (property "Value" "1" (at 0 0) (layer "F.Fab"))
    (fp_rect (start -1.8 -0.9) (end 1.8 0.9) (stroke (width 0.05) (type solid)) (fill no)
      (layer "F.CrtYd"))
    (pad "1" smd rect (at -1 0) (size 1 1.2) (layers "F.Cu") (net "OUT"))
    (pad "2" smd rect (at 1 0) (size 1 1.2) (layers "F.Cu") (net "LOAD"))))"""

# Where the board below puts each part, across and down from its corner, and so where
# each pad is: J1.1 at (110, 60) and J2.1 at (210, 60), 100 mm apart.
PLACES = {"J1": (10, 10), "J2": (110, 10), "Q1": (20, 30), "J3": (72, 30), "R1": (90, 28),
          "R2": (90, 32), "J4": (120, 30)}  # fmt: skip
F, B = "F.Cu", "B.Cu"
VIA = "Via[0-1]_800:400_um"
STRAIGHT = Wire("IN", F, 0.5, [(110.0, 60.0), (210.0, 60.0)])


def ohms(long: float, wide: float, thick: float = 0.035) -> float:
    """A track *long*, *wide* and *thick* in millimetres, of copper at 20 degrees."""
    return 1.72e-8 * (long / 1000) / ((wide / 1000) * (thick / 1000))


def carrier(
    d: File, source: str = SOURCE, places: dict[str, tuple[float, float]] = PLACES,
    routed: bool = True, **said: object,
) -> Board:  # fmt: skip
    """The board above from inputs written into *d*, each part placed and the board
    to be routed, unless it is not *routed*, to its rules and what else of them is
    *said*."""
    drawn = parse(source)
    d.mkdir()
    (d / "circuit.json").write_text(json.dumps(circuit(drawn)))
    (d / "mechanical.json").write_text(json.dumps(mechanical(drawn)))
    for name, lib in footprints(drawn)[0].items():
        file = d / "footprints" / footprint_path(name)
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(dumps(lib) + "\n")
    board = Board.from_inputs(d)
    for ref, (x, y) in places.items():
        board.place(board[ref], at=(x * mm, y * mm), facing=Edge.TOP)
    board.rules(**{"track": 0.5 * mm, "clearance": 0.2 * mm, **said})
    if routed:
        board.route()
    return board


@pytest.fixture
def board(tmp_path: File) -> Board:
    return carrier(tmp_path / "carrier")


@dataclass
class Scripted:
    """A router that hands back what it was told to, and keeps what it was asked."""

    run: Run = Run((), ())
    asked: list[tuple[str, Job, File, str]] = field(default_factory=list)

    def route(self, job: Job, outdir: File, name: str, stage: str = "") -> Run:
        self.asked.append((stage, job, outdir, name))
        return self.run


def _line_no() -> int:
    """The line this is called on; the statement above it is on ``_line_no() - 1``."""
    return sys._getframe(1).f_lineno


def measure(board: Board, out: File, *wires: Wire, vias: tuple[Via, ...] = ()) -> list[Measured]:
    """Each path of *board*, measured on it as built with *wires* and *vias* laid."""
    built = board.build(out, router=Scripted(Run(tuple(wires), vias, 0)))
    assert built.routed is not None
    # A measurement that raises is a reading that says so and never stops a build: here
    # it is a failure, so that no test passes over one.
    assert [r.failed for m in built.routed.paths for r in m.stretches if r.failed] == []
    return list(built.routed.paths)


def one(board: Board, out: File, *wires: Wire, vias: tuple[Via, ...] = ()) -> Reading:
    """The one stretch of the one path of *board*."""
    (measured,) = measure(board, out, *wires, vias=vias)
    (reading,) = measured.stretches
    return reading


def test_the_parts_are_where_the_tracks_below_take_them_to_be(board, tmp_path):
    written = parse(board.build(tmp_path / "out", router=Scripted()).board.read_text())
    placed = {str(p[2]): fp for fp in find_all(written, "footprint")
              for p in find_all(fp, "property") if p[1] == "Reference"}  # fmt: skip
    at = {f"{ref}.{pad[1]}": pad_xy(fp, str(pad[1]))
          for ref, fp in placed.items() for pad in find_all(fp, "pad")}  # fmt: skip
    assert at == {
        "J1.1": (110, 60), "J1.2": (110, 64), "J2.1": (210, 60), "J2.2": (210, 64),
        "J3.1": (172, 80), "J3.2": (172, 84), "J4.1": (220, 80), "J4.2": (220, 84),
        "Q1.1": (118, 80), "Q1.2": (122, 79), "Q1.3": (122, 81),
        "R1.1": (189, 78), "R1.2": (191, 78), "R2.1": (189, 82), "R2.2": (191, 82),
    }  # fmt: skip


# The statement.


def test_a_current_has_its_unit_and_reads_as_it_was_written():
    assert 1 * A == A * 1 == 1000 * mA and 500 * mA == 0.5 * A
    assert (str(1 * A), str(500 * mA), str(2.5 * A), str(1500 * mA)) == (
        "1 A", "500 mA", "2.5 A", "1.5 A")  # fmt: skip
    assert (1 * A).a == 1.0 and (250 * mA).a == 0.25
    # To the nearest microamp, as a length is to the nearest nanometre.
    assert int(2.01 * 1_000_000) == 2_009_999 and (2.01 * A).ua == 2_010_000
    assert ((0.0006 * mA).ua, (0.0004 * mA).ua) == (1, 0)
    assert pkidl.A is A and pkidl.mA is mA and pkidl.path is path


def test_a_path_is_a_statement_of_its_stops_and_its_current(board):
    j1, j2, q1, j3 = board.parts("J1", "J2", "Q1", "J3")
    r1, r2 = board.parts("R1", "R2")
    said = board.path(j1, q1, j3, [r1, r2], "LOAD", board["J4"], current=1 * A)
    line = _line_no() - 1
    assert isinstance(said, Path) and said in board.statements()
    assert board.statements()[-1] is said
    assert str(said) == "path(J1, Q1, J3, [R1, R2], LOAD, J4, current=1 A)"
    assert said.source is not None and str(said.source) == f"{HERE}:{line}"
    assert said.mentions() == (j1, q1, j3, r1, r2, board["J4"])
    assert board.statements(about=r2) == (board.statements(about=r2)[0], said)
    assert said.claims() == {}
    # As data: a part by its reference, a net by the circuit's name for it, and parts
    # side by side as a list; the current in microamps.
    assert said.data() == {"path": ["J1", "Q1", "J3", ["R1", "R2"], {"net": "LOAD"}, "J4"],
                           "current": 1_000_000}  # fmt: skip
    json.dumps(said.data())
    # Made without a board it is the same statement, wherever it was written, and a
    # net is its name or the net itself.
    apart = path(j1, q1, j3, (r1, r2), board.net("LOAD"), board["J4"], current=1000 * mA)
    assert apart == said and apart.data() == said.data() and hash(apart) == hash(said)
    assert board.add(apart) == (apart,) and board.statements().count(said) == 1
    assert path(j1, "IN", j2, current=1 * A).data() == {
        "path": ["J1", {"net": "IN"}, "J2"], "current": 1_000_000}  # fmt: skip
    assert path(j1, "IN", j2, current=1 * A) != path(j1, "IN", j2, current=2 * A)
    with pytest.raises(AttributeError):
        said.current = 2 * A  # type: ignore[misc]


def test_a_path_said_any_way_is_one_statement_on_a_board_and_is_measured_once(board, tmp_path):
    j1, j2 = board.parts("J1", "J2")
    (supply,) = board.name_nets({"IN": "SUPPLY"})
    said = board.path(j1, "SUPPLY", j2, current=1 * A)
    ways = [
        path(j1, "SUPPLY", j2, current=1 * A),  # by the name the board file gave it
        path(j1, "IN", j2, current=1 * A),  # by the circuit's
        path(j1, supply, j2, current=1 * A),  # by the net
        path(j1, board.net("SUPPLY"), j2, current=1000 * mA),
    ]
    for way in ways:
        assert way == said and hash(way) == hash(said) and way.data() == said.data()
        assert str(way) == str(said) and way.stops == said.stops
        assert board.add(way) == (way,)
    assert board.path(j1, "IN", j2, current=1 * A) == said
    assert board.path(j1, supply, j2, current=1 * A) == said
    assert [s for s in board.statements() if isinstance(s, Path)] == [said]
    assert said.data() == {"path": ["J1", {"net": "IN"}, "J2"], "current": 1_000_000}
    assert said.stops == (j1, supply, j2)
    assert len(measure(board, tmp_path / "out", STRAIGHT)) == 1
    # A name that is no net of the circuit is refused where it is said.
    with pytest.raises(LookupError, match="no net 'NOWHERE'"):
        path(j1, "NOWHERE", j2, current=1 * A)


def test_a_net_a_path_names_is_one_of_the_circuit_by_either_name(board):
    j1, j2 = board.parts("J1", "J2")
    board.name_nets({"IN": "SUPPLY"})
    said = board.path(j1, "SUPPLY", j2, current=1 * A)
    assert str(said) == "path(J1, SUPPLY, J2, current=1 A)"
    assert said.data()["path"] == ["J1", {"net": "IN"}, "J2"]
    with pytest.raises(LookupError, match="no net 'NOWHERE'"):
        board.path(j1, "NOWHERE", j2, current=1 * A)
    # A board whose circuit has the parts and not the net does not take the statement.
    other = Board(circuit=Circuit({"nets": ["ELSE"], "parts": [
        {"ref": ref, "value": "", "footprint": "", "pads": {"1": "ELSE"}} for ref in ("J1", "J2")
    ]}))  # fmt: skip
    with pytest.raises(LookupError, match=r"path\(J1, SUPPLY, J2, current=1 A\): no net 'IN'"):
        other.add(said)


@pytest.mark.parametrize(
    ("current", "error", "told"),
    [
        (1, TypeError, r"current= takes a current, such as 1 \* A or 500 \* mA, not 1"),
        ("1A", TypeError, "current= takes a current, such as"),
        (1 * mm, TypeError, "current= takes a current, such as"),
        (0 * A, ValueError, "current= 0 mA is not a current to carry"),
    ],
)
def test_what_a_path_carries_is_a_current_and_is_refused_where_it_is_said(
    board, current, error, told
):
    j1, j2 = board.parts("J1", "J2")
    with pytest.raises(error, match=told):
        board.path(j1, "IN", j2, current=current)
    with pytest.raises(TypeError, match="current"):
        board.path(j1, "IN", j2)
    assert not [s for s in board.statements() if isinstance(s, Path)]


def test_a_path_that_is_not_one_is_refused_where_it_is_said(board):
    j1, j2, q1 = board.parts("J1", "J2", "Q1")
    with pytest.raises(ValueError, match="takes two parts or more"):
        board.path(j1, current=1 * A)
    with pytest.raises(ValueError, match="takes two parts or more"):
        board.path(j1, "IN", current=1 * A)
    with pytest.raises(ValueError, match="takes two parts or more"):
        path(current=1 * A)
    with pytest.raises(ValueError, match="IN and GND are two nets in a row"):
        board.path(j1, "IN", "GND", j2, current=1 * A)
    with pytest.raises(ValueError, match="J1 is at two stops of it"):
        board.path(j1, "IN", j1, current=1 * A)
    with pytest.raises(ValueError, match="J1 is at two stops of it"):
        board.path(j1, "IN", j2, "GND", j1, current=1 * A)
    with pytest.raises(ValueError, match="J1 is at two stops of it"):
        board.path(j1, "IN", [j2, q1], [j1, board["J3"]], current=1 * A)
    with pytest.raises(ValueError, match="J1 is at two stops of it"):
        board.path([j1, q1], j1, current=1 * A)
    with pytest.raises(TypeError, match="takes parts, nets and lists of parts side by side"):
        board.path(j1, 3, j2, current=1 * A)
    with pytest.raises(TypeError, match="takes parts, nets and lists of parts side by side"):
        board.path(j1, [j2, "IN"], current=1 * A)
    with pytest.raises(TypeError, match="takes parts, nets and lists of parts side by side"):
        board.path(j1, [], j2, current=1 * A)
    with pytest.raises(ValueError, match=r"path\(\): \[Q1, Q1\] has Q1 twice"):
        board.path(j1, [q1, q1], j2, current=1 * A)
    assert not [s for s in board.statements() if isinstance(s, Path)]


def test_the_thickness_of_the_copper_is_a_rule_and_one_ounce_where_none_is_said(board):
    (said,) = [s for s in board.statements() if isinstance(s, Rules)]
    assert said.copper == 0.035 * mm
    assert said == Rules(Length(500_000), Length(200_000), Length(500_000))
    # A board that does not say it reads, and is as data, what it was.
    assert str(said) == "rules(track=0.5 mm, clearance=0.2 mm, edge=0.5 mm)"
    assert said.data() == {"rules": {"track": 500_000, "clearance": 200_000, "edge": 500_000}}
    two = rules(track=0.5 * mm, clearance=0.2 * mm, copper="0.07mm")
    assert two.copper == Length(70_000) and two != said
    assert str(two) == "rules(track=0.5 mm, clearance=0.2 mm, edge=0.5 mm, copper=0.07 mm)"
    assert two.data() == {"rules": {"track": 500_000, "clearance": 200_000, "edge": 500_000,
                                    "copper": 70_000}}  # fmt: skip
    # Said once, as each rule is.
    board.add(two)
    (conflict,) = board.conflicts()
    assert str(conflict).startswith("the board: copper thickness is 0.035 mm (")
    assert " and 0.07 mm (" in str(conflict)
    with pytest.raises(ValueError, match=r"rules\(\): copper= 0 mm is not a thickness"):
        board.rules(track=0.5 * mm, clearance=0.2 * mm, copper=0 * mm)
    with pytest.raises(TypeError, match="has no unit"):
        board.rules(track=0.5 * mm, clearance=0.2 * mm, copper=0.035)


# Its stretches.


def test_a_path_is_a_stretch_of_one_net_between_each_two_parts(board):
    j1, q1, j3, j4 = board.parts("J1", "Q1", "J3", "J4")
    sides = board.parts("R1", "R2")
    said = board.path("IN", j1, q1, j3, sides, "LOAD", j4, "GND", current=1 * A)
    found, wrong = said.stretches(board.circuit)
    assert wrong == () and all(isinstance(s, Stretch) for s in found)
    assert [str(s) for s in found] == [
        "IN, J1 to Q1", "OUT, Q1 to J3", "OUT, J3 to [R1, R2]", "LOAD, [R1, R2] to J4",
    ]  # fmt: skip
    # An end is every pin the stop has on the net: both of the transistor's on OUT,
    # and one of each resistor.
    assert [[[str(pin) for pin in end] for end in s.ends] for s in found] == [
        [["J1.1"], ["Q1.1"]],
        [["Q1.2", "Q1.3"], ["J3.1"]],
        [["J3.1"], ["R1.1", "R2.1"]],
        [["R1.2", "R2.2"], ["J4.1"]],
    ]
    assert [s.net for s in found] == [board.net(n) for n in ("IN", "OUT", "OUT", "LOAD")]
    assert board.solve().problems == ()


def test_parts_that_share_no_net_are_a_problem_with_the_line(board, tmp_path):
    said = board.path(board["J1"], board["R1"], current=1 * A)
    line = _line_no() - 1
    (problem,) = board.solve().problems
    assert str(problem) == f"path(J1, R1, current=1 A): J1 and R1 share no net ({HERE}:{line})"
    assert problem.parts == ("J1", "R1") and problem.statements == (said,)
    with pytest.raises(BuildError, match="J1 and R1 share no net"):
        board.build(tmp_path / "out", router=Scripted())
    assert not (tmp_path / "out").exists()


def test_a_net_is_shared_where_every_part_of_a_list_has_it(board):
    j1, j3, q1, r1 = board.parts("J1", "J3", "Q1", "R1")
    # J3 and R1 are both on OUT, and J1 is not; Q1 is.
    for stops in ((j3, [r1, j1]), ([r1, j1], j3), ([j1, r1], j3), (j3, [j1, r1])):
        (wrong,) = path(*stops, current=1 * A).stretches(board.circuit)[1]
        assert wrong[1].endswith("share no net") and set(wrong[0]) == {"J1", "J3", "R1"}
    (found,) = path(j3, [r1, q1], current=1 * A).stretches(board.circuit)[0]
    assert str(found) == "OUT, J3 to [Q1, R1]"
    assert [str(pin) for pin in found.ends[1]] == ["Q1.2", "Q1.3", "R1.1"]


def test_a_list_of_one_part_is_the_part_and_a_list_is_the_same_in_any_order(board, tmp_path):
    j1, j2, q1, r1, r2 = board.parts("J1", "J2", "Q1", "R1", "R2")
    said = board.path(j1, "IN", j2, current=1 * A)
    ways = [
        path([j1], "IN", (j2,), current=1 * A),
        path(board.parts("J1"), "IN", j2, current=1 * A),
        path((p for p in [j1]), "IN", j2, current=1 * A),
    ]
    for way in ways:
        assert way == said and hash(way) == hash(said) and way.data() == said.data()
        assert way.stops == (j1, board.net("IN"), j2) and str(way) == str(said)
        board.add(way)
    one_way, other = path(q1, [r1, r2], current=1 * A), path(q1, (r2, r1), current=1 * A)
    assert one_way == other and hash(one_way) == hash(other)
    assert str(other) == "path(Q1, [R1, R2], current=1 A)"
    assert other.data() == {"path": ["Q1", ["R1", "R2"]], "current": 1_000_000}
    assert [str(s) for s in other.stretches(board.circuit)[0]] == ["OUT, Q1 to [R1, R2]"]
    assert path([r2, r1], q1, current=1 * A).mentions() == (r1, r2, q1)
    board.add(one_way, other)
    assert [str(s) for s in board.statements() if isinstance(s, Path)] == [
        "path(J1, IN, J2, current=1 A)", "path(Q1, [R1, R2], current=1 A)"]  # fmt: skip
    assert len(measure(board, tmp_path / "out", STRAIGHT)) == 2


def test_parts_that_share_two_nets_are_told_to_name_the_one_meant(board):
    board.path(board["J1"], board["J2"], current=1 * A)
    line = _line_no() - 1
    (problem,) = board.solve().problems
    assert str(problem) == (
        "path(J1, J2, current=1 A): J1 and J2 share IN and GND: name the one meant "
        f'between them as a stop, as in path(J1, "IN", J2, ...) ({HERE}:{line})'
    )
    board.path(board["J1"], "GND", board["J2"], current=1 * A)
    assert len(board.solve().problems) == 1  # and the one that names it is none


def test_a_part_that_is_not_on_the_net_named_is_a_problem_with_the_line(board):
    j1, j3, j4 = board.parts("J1", "J3", "J4")
    sides = board.parts("R1", "R2")
    board.path(j1, "OUT", j3, current=1 * A)
    first = _line_no() - 1
    board.path("LOAD", j3, sides, j4, "IN", current=1 * A)
    second = _line_no() - 1
    board.path(j1, "LOAD", [*sides, j3], current=1 * A)
    third = _line_no() - 1
    assert [str(p) for p in board.solve().problems] == [
        f"path(J1, LOAD, [J3, R1, R2], current=1 A): J1 has no pad on LOAD ({HERE}:{third})",
        f"path(J1, OUT, J3, current=1 A): J1 has no pad on OUT ({HERE}:{first})",
        f"path(J1, LOAD, [J3, R1, R2], current=1 A): J3 has no pad on LOAD ({HERE}:{third})",
        f"path(LOAD, J3, [R1, R2], J4, IN, current=1 A): J3 has no pad on LOAD ({HERE}:{second})",
        f"path(LOAD, J3, [R1, R2], J4, IN, current=1 A): J4 has no pad on IN ({HERE}:{second})",
    ]


# The measurement.


def test_a_straight_track_is_its_length_over_its_width_and_the_coppers_thickness(board, tmp_path):
    j1, j2 = board.parts("J1", "J2")
    board.path(j1, "IN", j2, current=1 * A)
    reading = one(board, tmp_path / "out", STRAIGHT)
    assert ohms(100, 0.5) == pytest.approx(0.0983, abs=5e-5)
    assert reading.ohms == pytest.approx(ohms(100, 0.5), rel=1e-9)
    assert (reading.length, reading.narrowest) == (100 * mm, 0.5 * mm)
    assert reading.volts == pytest.approx(ohms(100, 0.5), rel=1e-9) and not reading.poured
    assert str(reading) == (
        "IN, J1 to J2: 100 mm of track, 0.5 mm at its narrowest, 98.3 mΩ, 98.3 mV"
    )


def test_copper_twice_as_thick_is_half_the_resistance(tmp_path, board):
    j1, j2 = board.parts("J1", "J2")
    (thin,) = [s for s in board.statements() if isinstance(s, Rules)]
    del board._statements[thin]
    board.rules(track=0.5 * mm, clearance=0.2 * mm, copper=0.07 * mm)
    board.path(j1, "IN", j2, current=1 * A)
    reading = one(board, tmp_path / "out", STRAIGHT)
    assert reading.ohms == pytest.approx(ohms(100, 0.5) / 2, rel=1e-9)


def test_the_drop_is_the_resistance_times_the_current_the_path_carries(board, tmp_path):
    j1, j2 = board.parts("J1", "J2")
    said = board.path(j1, "IN", j2, current=250 * mA)
    line = _line_no() - 1
    (measured,) = measure(board, tmp_path / "out", STRAIGHT)
    (reading,) = measured.stretches
    assert measured.path is said
    assert reading.volts == pytest.approx(ohms(100, 0.5) / 4, rel=1e-9)
    assert measured.volts == pytest.approx(ohms(100, 0.5) / 4, rel=1e-9)
    assert str(measured) == (
        f"path(J1, IN, J2, current=250 mA) ({HERE}:{line}): 98.3 mΩ of track, 24.6 mV at "
        "250 mA\n"
        "  IN, J1 to J2: 100 mm of track, 0.5 mm at its narrowest, 98.3 mΩ, 24.6 mV"
    )


def test_two_tracks_in_parallel_are_in_parallel(board, tmp_path):
    j1, j2 = board.parts("J1", "J2")
    board.path(j1, "IN", j2, current=1 * A)
    # The same track again on the back: half.
    under = Wire("IN", B, 0.5, [(110.0, 60.0), (210.0, 60.0)])
    reading = one(board, tmp_path / "two", STRAIGHT, under)
    assert reading.ohms == pytest.approx(ohms(100, 0.5) / 2, rel=1e-9)
    assert reading.length == 100 * mm
    # A way round on the front, 10 mm up, 100 mm along and 10 mm down: 120 mm beside
    # the 100 mm.
    longer = Wire("IN", F, 0.5, [(110.0, 60.0), (110.0, 70.0), (210.0, 70.0), (210.0, 60.0)])
    reading = one(board, tmp_path / "detour", STRAIGHT, longer)
    short, long = ohms(100, 0.5), ohms(120, 0.5)
    assert reading.ohms == pytest.approx(short * long / (short + long), rel=1e-9)
    assert reading.ohms == pytest.approx(ohms(100, 0.5) * 6 / 11, rel=1e-9)
    assert reading.length == 100 * mm  # the way of least resistance is the straight one


def test_a_track_that_ends_on_the_middle_of_another_joins_it(board, tmp_path):
    j1, j2 = board.parts("J1", "J2")
    board.path(j1, "IN", j2, current=1 * A)
    # From J1 50 mm along to the middle of a track that runs from 5 mm above to 10 mm
    # below; from that track's lower end 50 mm along and 10 mm up to J2.
    stem = Wire("IN", F, 0.5, [(110.0, 60.0), (160.0, 60.0)])
    bar = Wire("IN", F, 0.5, [(160.0, 55.0), (160.0, 70.0)])
    rest = Wire("IN", F, 0.5, [(160.0, 70.0), (210.0, 70.0), (210.0, 60.0)])
    reading = one(board, tmp_path / "out", stem, bar, rest)
    assert reading.ohms == pytest.approx(ohms(120, 0.5), rel=1e-9)
    assert reading.length == 120 * mm
    # One that stops 1 mm short of the bar's copper does not.
    short = Wire("IN", F, 0.5, [(110.0, 60.0), (158.75, 60.0)])
    reading = one(board, tmp_path / "short", short, bar, rest)
    assert reading.ohms is None and str(reading) == "IN, J1 to J2: not joined by track"


def test_a_track_joins_a_pad_where_its_end_is_within_the_pads_copper(board, tmp_path):
    j1, j2 = board.parts("J1", "J2")
    board.path(j1, "IN", j2, current=1 * A)

    # J2.1 is round, 2 mm across at (210, 60): its copper starts at 209 mm.
    def to(x: float) -> Reading:
        return one(board, tmp_path / f"to-{x}", Wire("IN", F, 0.5, [(110.0, 60.0), (x, 60.0)]))

    inside = to(209.5)
    assert inside.ohms == pytest.approx(ohms(99.5, 0.5), rel=1e-9)
    assert inside.length == 99.5 * mm
    outside = to(208.99)  # 0.01 mm short, its round end over the pad
    assert (outside.ohms, outside.length, outside.narrowest, outside.volts) == (None,) * 4
    # Its copper touches the pad's all the same, and that is said: a neck.
    assert str(outside) == ("IN, J1 to J2: not joined by track; a neck of 0.497 mm, of track "
                            "at (209.011, 60) on F.Cu")  # fmt: skip


def test_a_route_through_a_via_is_the_sum_of_its_two_parts(board, tmp_path):
    j1, j2 = board.parts("J1", "J2")
    board.path(j1, "IN", j2, current=1 * A)
    front = Wire("IN", F, 0.5, [(110.0, 60.0), (160.0, 60.0)])
    back = Wire("IN", B, 1.0, [(160.0, 60.0), (210.0, 60.0)])
    reading = one(board, tmp_path / "via", front, back, vias=(Via("IN", VIA, (160.0, 60.0)),))
    assert reading.ohms == pytest.approx(ohms(50, 0.5) + ohms(50, 1.0), rel=1e-9)
    assert (reading.length, reading.narrowest) == (100 * mm, 0.5 * mm)
    # With no via the two meet on different faces, and are not joined.
    reading = one(board, tmp_path / "none", front, back)
    assert reading.ohms is None


def test_a_track_on_the_face_a_surface_pad_is_not_on_does_not_join_it(board, tmp_path):
    board.path(board["Q1"], board["J3"], current=1 * A)

    # Q1.3 is on the front at (122, 81), and J3.1 in a hole at (172, 80).
    def on(layer: str) -> Reading:
        wire = Wire("OUT", layer, 0.5, [(122.0, 81.0), (150.0, 81.0), (150.0, 80.0), (172.0, 80.0)])
        return one(board, tmp_path / layer, wire)

    assert on(F).ohms == pytest.approx(ohms(51, 0.5), rel=1e-9)
    assert on(B).ohms is None


def test_the_length_and_the_narrowest_width_are_of_the_way_of_least_resistance(board, tmp_path):
    j1, j2 = board.parts("J1", "J2")
    board.path(j1, "IN", j2, current=1 * A)
    # 100 mm of 0.25 mm track, and beside it 120 mm of 1 mm track with 10 mm of it
    # necked to 0.8 mm: the longer way is the one of less resistance.
    thin = Wire("IN", F, 0.25, [(110.0, 60.0), (210.0, 60.0)])
    wide = (
        Wire("IN", F, 1.0, [(110.0, 60.0), (110.0, 70.0), (150.0, 70.0)]),
        Wire("IN", F, 0.8, [(150.0, 70.0), (160.0, 70.0)]),
        Wire("IN", F, 1.0, [(160.0, 70.0), (210.0, 70.0), (210.0, 60.0)]),
    )
    reading = one(board, tmp_path / "out", thin, *wide)
    round_ = ohms(110, 1.0) + ohms(10, 0.8)
    assert round_ < ohms(100, 0.25)
    assert (reading.length, reading.narrowest) == (120 * mm, 0.8 * mm)
    assert reading.ohms == pytest.approx(
        round_ * ohms(100, 0.25) / (round_ + ohms(100, 0.25)), rel=1e-9
    )


def test_every_pad_a_part_has_on_the_net_is_one_end(board, tmp_path):
    board.path(board["Q1"], board["J3"], current=1 * A)
    # Q1.2 at (122, 79) and Q1.3 at (122, 81) are both on OUT; J3.1 is at (172, 80).
    upper = Wire("OUT", F, 0.5, [(122.0, 79.0), (162.0, 79.0), (172.0, 80.0)])
    lower = Wire("OUT", F, 0.5, [(122.0, 81.0), (162.0, 81.0), (172.0, 80.0)])
    long = 40 + 101**0.5
    alone = one(board, tmp_path / "lower", lower)
    assert alone.ohms == pytest.approx(ohms(long, 0.5), rel=1e-9)
    both = one(board, tmp_path / "both", upper, lower)
    assert both.ohms == pytest.approx(ohms(long, 0.5) / 2, rel=1e-9)
    assert str(both).startswith("OUT, Q1 to J3: 50 mm of track, 0.5 mm at its narrowest, ")


def test_parts_side_by_side_are_one_end_and_the_whole_current_is_taken_through(board, tmp_path):
    sides = board.parts("R1", "R2")
    board.path(board["J3"], sides, board["J4"], current=2 * A)
    # J3.1 at (172, 80) to R1.1 at (189, 78), and R1.2 and R2.2, at (191, 78) and
    # (191, 82), each to J4.1 at (220, 80). R2.1 has no track: R1.1 is the end.
    wires = (
        Wire("OUT", F, 0.5, [(172.0, 80.0), (172.0, 78.0), (189.0, 78.0)]),
        Wire("LOAD", F, 0.5, [(191.0, 78.0), (220.0, 78.0), (220.0, 80.0)]),
        Wire("LOAD", F, 0.5, [(191.0, 82.0), (220.0, 82.0), (220.0, 80.0)]),
    )
    (measured,) = measure(board, tmp_path / "out", *wires)
    out, load = measured.stretches
    assert out.ohms == pytest.approx(ohms(19, 0.5), rel=1e-9)
    assert load.ohms == pytest.approx(ohms(31, 0.5) / 2, rel=1e-9)
    assert out.volts == pytest.approx(2 * ohms(19, 0.5), rel=1e-9)
    assert load.volts == pytest.approx(ohms(31, 0.5), rel=1e-9)
    assert measured.ohms == pytest.approx(ohms(19, 0.5) + ohms(31, 0.5) / 2, rel=1e-9)
    assert measured.volts == pytest.approx(2 * (ohms(19, 0.5) + ohms(31, 0.5) / 2), rel=1e-9)
    assert measured.unmeasured == 0
    assert str(measured).splitlines()[1:] == [
        "  OUT, J3 to [R1, R2]: 19 mm of track, 0.5 mm at its narrowest where 2 A needs "
        "0.926 mm, 18.7 mΩ, 37.3 mV",
        "  LOAD, [R1, R2] to J4: 31 mm of track, 0.5 mm at its narrowest where 2 A needs "
        "0.926 mm, 15.2 mΩ, 30.5 mV; a neck of 1 mm in 2 pieces, the widest 0.5 mm of track "
        "at (191.5, 78) on F.Cu",
    ]
    # Two tracks side by side are a neck of both, which is all the current needs here.
    assert (load.neck, load.narrowest, len(load.across)) == (1 * mm, 0.5 * mm, 2)


def test_ends_that_no_track_joins_are_said_to_be_not_joined_and_are_not_in_the_total(
    board, tmp_path
):
    j1, q1, j3 = board.parts("J1", "Q1", "J3")
    board.path(j1, q1, j3, current=1 * A)
    line = _line_no() - 1
    wire = Wire("OUT", F, 0.5, [(122.0, 81.0), (150.0, 81.0), (150.0, 80.0), (172.0, 80.0)])
    (measured,) = measure(board, tmp_path / "out", wire)
    assert [r.ohms is None for r in measured.stretches] == [True, False]
    assert measured.unmeasured == 1
    assert measured.ohms == pytest.approx(ohms(51, 0.5), rel=1e-9)
    assert str(measured) == (
        f"path(J1, Q1, J3, current=1 A) ({HERE}:{line}): 50.1 mΩ of track, 50.1 mV at 1 A, "
        "1 of its 2 stretches not in it\n"
        "  IN, J1 to Q1: not joined by track\n"
        "  OUT, Q1 to J3: 51 mm of track, 0.5 mm at its narrowest, 50.1 mΩ, 50.1 mV"
    )
    # With no track at all there is no figure.
    (measured,) = measure(board, tmp_path / "bare")
    assert (measured.ohms, measured.volts, measured.unmeasured) == (None, None, 2)
    assert str(measured).splitlines()[0] == (
        f"path(J1, Q1, J3, current=1 A) ({HERE}:{line}): no figure: none of its 2 stretches "
        "is measured"
    )


def test_ends_that_only_a_pour_joins_have_its_neck_and_no_figure_for_its_resistance(
    board, tmp_path
):
    j1, j2 = board.parts("J1", "J2")
    board.pour("GND", layer="B.Cu")
    board.path(j1, "GND", j2, current=1 * A)
    reading = one(board, tmp_path / "out")
    assert reading.ohms is None and reading.volts is None and reading.poured
    # Each pin is in the pour on the four spokes of its relief, 0.5 mm wide.
    assert (reading.neck, reading.filled) == (2 * mm, MODEL)
    assert [(p.width, p.layer, p.of) for p in reading.across] == [
        (0.5 * mm, B, "the relief of J1.2")
    ] * 4
    assert str(reading) == (
        "GND, J1 to J2: not joined by track; GND has a pour, whose resistance is not measured; "
        "a neck of 2 mm in 4 pieces, the widest 0.5 mm of the relief of J1.2 at "
        "(109.17, 64.83) on B.Cu, on pkidl's model of the fill"
    )


def test_a_pour_that_does_not_reach_the_ends_is_said_not_to_join_them(board, tmp_path):
    # OUT is poured on the back, and the transistor's pads are on the front alone: no
    # copper of that pour is anywhere near them.
    board.pour("OUT", layer="B.Cu")
    board.path(board["Q1"], board["J3"], current=1 * A)
    reading = one(board, tmp_path / "out")
    assert reading.ohms is None and reading.poured
    assert (reading.neck, reading.across, reading.filled) == (Length(0), (), MODEL)
    assert str(reading) == (
        "OUT, Q1 to J3: not joined by track; OUT has a pour, which does not join them "
        "either, on pkidl's model of the fill"
    )


def test_a_track_beside_a_pour_is_measured_as_at_most_what_the_track_is(board, tmp_path):
    j1, j2 = board.parts("J1", "J2")
    board.pour("GND", layer="B.Cu")
    board.path(j1, "GND", j2, current=1 * A)
    line = _line_no() - 1
    # J1.2 at (110, 64) to J2.2 at (210, 64), on the front.
    wire = Wire("GND", F, 0.5, [(110.0, 64.0), (210.0, 64.0)])
    (measured,) = measure(board, tmp_path / "out", wire)
    (reading,) = measured.stretches
    assert reading.ohms == pytest.approx(ohms(100, 0.5), rel=1e-9) and reading.poured
    assert str(measured) == (
        f"path(J1, GND, J2, current=1 A) ({HERE}:{line}): at most 98.3 mΩ of track, "
        "98.3 mV at 1 A\n"
        "  GND, J1 to J2: 100 mm of track, 0.5 mm at its narrowest, at most 98.3 mΩ, "
        "98.3 mV: GND has a pour as well, whose resistance is not measured; a neck of 2.5 mm "
        "in 5 pieces, the widest 0.5 mm of the relief of J1.2 at (109.17, 64.83) on B.Cu, on "
        "pkidl's model of the fill"
    )
    # The track and the four spokes side by side: the drop is still of the track alone.
    assert (reading.neck, reading.narrowest) == (2.5 * mm, 0.5 * mm)
    assert sorted(p.of for p in reading.across) == ["the relief of J1.2"] * 4 + ["track"]


def test_a_total_is_at_most_only_where_a_stretch_that_is_measured_is_poured(board, tmp_path):
    j1, j2, q1 = board.parts("J1", "J2", "Q1")
    board.pour("GND", layer="B.Cu")
    # Round by ground, which is poured and has no track, and back on IN, which has a
    # track and no pour: the one figure in the total is of copper with no pour.
    board.path(j1, "GND", j2, "IN", q1, current=1 * A)
    wire = Wire("IN", F, 0.5, [(210.0, 60.0), (210.0, 70.0), (118.0, 70.0), (118.0, 80.0)])
    (measured,) = measure(board, tmp_path / "out", wire)
    assert [(r.ohms is None, r.poured) for r in measured.stretches] == [
        (True, True),
        (False, False),
    ]
    assert (
        str(measured)
        .splitlines()[0]
        .endswith("): 110 mΩ of track, 110 mV at 1 A, 1 of its 2 stretches not in it")
    )


def test_paths_are_measured_in_the_order_statements_have_each_once(board, tmp_path):
    j1, j2, q1, j3 = board.parts("J1", "J2", "Q1", "J3")
    first = board.path(j1, "IN", j2, current=1 * A)
    second = board.path(q1, j3, current=1 * A)
    board.add(first)
    assert [m.path for m in measure(board, tmp_path / "out", STRAIGHT)] == [first, second]
    # Whatever order they were added in.
    again = Board.from_inputs(tmp_path / "carrier")
    for statement in reversed(board.statements()):
        again.add(statement)
    assert [m.path for m in measure(again, tmp_path / "again", STRAIGHT)] == [first, second]
    # Two written on one line, in a loop, are in the order of what they say, as
    # statements are everywhere, and not the order they were made in.
    looped = [again.path(a, b, current=1 * A) for a, b in ((q1, j3), (j1, q1))]
    assert looped[0].source == looped[1].source and looped[0] == second
    assert [str(m.path) for m in measure(again, tmp_path / "looped", STRAIGHT)] == [
        "path(J1, IN, J2, current=1 A)",
        "path(Q1, J3, current=1 A)",
        "path(J1, Q1, current=1 A)",
    ]
    assert [str(s) for s in again.statements() if isinstance(s, Path)] == [
        "path(Q1, J3, current=1 A)",
        "path(J1, IN, J2, current=1 A)",
        "path(J1, Q1, current=1 A)",
    ]
    # A board that says none has none.
    bare = Board.from_inputs(tmp_path / "carrier")
    for statement in board.statements():
        if not isinstance(statement, Path):
            bare.add(statement)
    assert measure(bare, tmp_path / "bare", STRAIGHT) == []


def _hashes(d: File) -> dict[str, str]:
    return {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(d.iterdir())}


@pytest.mark.parametrize(
    "run", [Run((), ()), Run((STRAIGHT,), (Via("IN", VIA, (160.0, 60.0)),), 0)]
)
def test_a_board_that_says_a_path_is_built_as_the_same_files_as_one_that_does_not(
    board, tmp_path, run
):
    board.pour("GND", layer="B.Cu")
    plain = board.build(tmp_path / "plain" / "out", router=Scripted(run))
    j1, j2, q1, j3 = board.parts("J1", "J2", "Q1", "J3")
    board.path(j1, "IN", j2, current=1 * A)
    board.path(j1, "GND", j2, current=1 * A)
    board.path(q1, j3, board.parts("R1", "R2"), board["J4"], current=500 * mA)
    said = board.build(tmp_path / "said" / "out", router=Scripted(run))
    assert plain.routed is not None and said.routed is not None
    assert plain.routed.paths == () and len(said.routed.paths) == 3
    assert plain.solution == said.solution
    hashes = _hashes(tmp_path / "said" / "out")
    assert hashes == _hashes(tmp_path / "plain" / "out")
    assert sorted(hashes) == ["carrier.kicad_pcb", "carrier.kicad_pro"]


# What joins, and what is one piece of copper.


def _chopped(step: float, wide: float) -> list[Wire]:
    """J1.1 to J2.1 in a straight line, as tracks *step* long laid end to end."""
    count = round(100 / step)
    xs = [110 + 100 * i / count for i in range(count + 1)]
    return [Wire("IN", F, wide, [(a, 60.0), (b, 60.0)]) for a, b in zip(xs, xs[1:], strict=False)]


@pytest.mark.parametrize(
    ("step", "wide"),
    [(0.2, 0.5), (1, 0.5), (0.01, 3.0), (0.2, 3.0), (1, 3.0), (2, 3.0)],
)
def test_a_track_laid_in_pieces_however_short_is_the_one_track(board, tmp_path, step, wide):
    j1, j2 = board.parts("J1", "J2")
    board.path(j1, "IN", j2, current=1 * A)
    reading = one(board, tmp_path / "out", *_chopped(step, wide))
    assert reading.ohms == pytest.approx(ohms(100, wide), rel=1e-9)
    assert (reading.length, reading.narrowest) == (100 * mm, wide * mm)


def test_a_short_piece_in_a_wide_track_is_as_long_as_it_is(board, tmp_path):
    j1, j2 = board.parts("J1", "J2")
    board.path(j1, "IN", j2, current=1 * A)
    # 49 mm, 1 mm and 50 mm, 3 mm wide: the middle one shorter than half its width.
    wires = [Wire("IN", F, 3.0, [(a, 60.0), (b, 60.0)])
             for a, b in ((110.0, 159.0), (159.0, 160.0), (160.0, 210.0))]  # fmt: skip
    reading = one(board, tmp_path / "straight", *wires)
    assert reading.ohms == pytest.approx(ohms(100, 3.0), rel=1e-9) and reading.length == 100 * mm
    # And round a corner: 50 mm along, 0.2 mm down, 50 mm along and 0.2 mm up to J2.
    jog = Wire("IN", F, 3.0, [(110.0, 60.0), (160.0, 60.0), (160.0, 60.2), (210.0, 60.2),
                              (210.0, 60.0)])  # fmt: skip
    reading = one(board, tmp_path / "jog", jog)
    assert reading.length == Length(100_400_000)
    assert reading.ohms == pytest.approx(ohms(100.4, 3.0), rel=1e-9)


def test_tracks_whose_ends_are_near_and_do_not_meet_are_not_joined(board, tmp_path):
    j1, j2 = board.parts("J1", "J2")
    board.path(j1, "IN", j2, current=1 * A)

    # Two ends are joined where they are one place, and nowhere else: not 0.1 mm
    # apart with their round ends over each other.
    def gap(by: float) -> Reading:
        return one(board, tmp_path / f"gap-{by}",
                   Wire("IN", F, 0.5, [(110.0, 60.0), (160.0, 60.0)]),
                   Wire("IN", F, 0.5, [(160.0 + by, 60.0), (210.0, 60.0)]))  # fmt: skip

    assert gap(0.1).ohms is None
    assert gap(0.00004).ohms == pytest.approx(ohms(100, 0.5), rel=1e-6)
    # One place is no further apart than a tenth of a micrometre, wherever the two are.
    assert gap(0.0005).ohms is None and gap(0.00011).ohms is None
    assert gap(0.00009).ohms == pytest.approx(ohms(100, 0.5), rel=1e-6)
    assert gap(0.0001).ohms == pytest.approx(ohms(100, 0.5), rel=1e-6)

    def ends(first: float, second: float) -> Reading:
        return one(board, tmp_path / f"ends-{first}",
                   Wire("IN", F, 0.5, [(110.0, 60.0), (first, 60.0)]),
                   Wire("IN", F, 0.5, [(second, 60.0), (210.0, 60.0)]))  # fmt: skip

    assert ends(160.000049, 160.000051).ohms is not None  # 2 nm apart
    assert ends(159.999951, 160.000049).ohms is not None  # 98 nm apart

    # And whichever way one is from the other: 0.07 um along and 0.07 um aside is
    # 0.099 um, and 0.08 um of each is 0.113 um.
    def aside(by: float) -> Reading:
        return one(board, tmp_path / f"aside-{by}",
                   Wire("IN", F, 0.5, [(110.0, 60.0), (160.0, 60.0)]),
                   Wire("IN", F, 0.5, [(160.0 + by, 60.0 + by), (210.0, 60.0)]))  # fmt: skip

    assert aside(0.00007).ohms == pytest.approx(ohms(100, 0.5), rel=1e-6)
    assert aside(0.00008).ohms is None


def test_an_end_joins_another_track_part_way_along_where_it_is_within_its_copper(board, tmp_path):
    j1, j2 = board.parts("J1", "J2")
    board.path(j1, "IN", j2, current=1 * A)
    # A track from J1 that stops beside one 0.5 mm wide running down at 160 mm across,
    # which goes on to J2: that track's copper is from 159.75 mm.
    bar = Wire("IN", F, 0.5, [(160.0, 55.0), (160.0, 70.0), (210.0, 70.0), (210.0, 60.0)])

    def to(x: float) -> Reading:
        stem = Wire("IN", F, 0.5, [(110.0, 60.0), (x, 60.0)])
        return one(board, tmp_path / f"to-{x}", stem, bar)

    assert to(159.8).ohms == pytest.approx(ohms(49.8 + 70, 0.5), rel=1e-9)  # 0.2 mm off its middle
    assert to(159.7).ohms is None  # 0.3 mm off: within its width and not its copper
    # One that goes 0.2 mm past its middle crosses it there, and its end is no further.
    assert to(160.2).ohms == pytest.approx(ohms(50 + 70, 0.5), rel=1e-9)


def test_copper_laid_twice_is_the_one_strip_it_is(board, tmp_path):
    j1, j2 = board.parts("J1", "J2")
    board.path(j1, "IN", j2, current=1 * A)
    # The same track again on the same layer.
    reading = one(board, tmp_path / "twice", STRAIGHT, STRAIGHT)
    assert reading.ohms == pytest.approx(ohms(100, 0.5), rel=1e-9)
    # Two that run over each other from 150 to 170 mm.
    lapped = (Wire("IN", F, 0.5, [(110.0, 60.0), (170.0, 60.0)]),
              Wire("IN", F, 0.5, [(150.0, 60.0), (210.0, 60.0)]))  # fmt: skip
    reading = one(board, tmp_path / "lapped", *lapped)
    assert reading.ohms == pytest.approx(ohms(100, 0.5), rel=1e-9) and reading.length == 100 * mm
    # A wide track laid over a narrow one is the wide one.
    over = Wire("IN", F, 1.0, [(110.0, 60.0), (210.0, 60.0)])
    reading = one(board, tmp_path / "over", STRAIGHT, over)
    assert reading.ohms == pytest.approx(ohms(100, 1.0), rel=1e-9) and reading.narrowest == 1 * mm
    # The same track on the other face is a second strip, as it was.
    under = Wire("IN", B, 0.5, [(110.0, 60.0), (210.0, 60.0)])
    assert one(board, tmp_path / "under", STRAIGHT, under).ohms == pytest.approx(
        ohms(100, 0.5) / 2, rel=1e-9
    )


def test_a_via_part_way_along_a_track_joins_it_there(board, tmp_path):
    j1, j2 = board.parts("J1", "J2")
    board.path(j1, "IN", j2, current=1 * A)
    # The front track goes on 40 mm past the via; the back one is from the via to J2.
    front = Wire("IN", F, 0.5, [(110.0, 60.0), (200.0, 60.0)])
    back = Wire("IN", B, 1.0, [(160.0, 60.0), (210.0, 60.0)])
    reading = one(board, tmp_path / "out", front, back, vias=(Via("IN", VIA, (160.0, 60.0)),))
    assert reading.ohms == pytest.approx(ohms(50, 0.5) + ohms(50, 1.0), rel=1e-9)
    assert reading.length == 100 * mm
    assert one(board, tmp_path / "none", front, back).ohms is None


def test_a_track_that_runs_across_a_pad_joins_it_where_it_crosses(board, tmp_path):
    board.path(board["Q1"], board["J3"], current=1 * A)

    # Q1.3 is 1 mm square at (122, 81). A track from 6 mm left of it runs across it
    # 0.4 mm below its middle and on to J3.1 at (172, 80).
    def at(y: float) -> Reading:
        wire = Wire("OUT", F, 0.5, [(116.0, y), (150.0, y), (150.0, 80.0), (172.0, 80.0)])
        return one(board, tmp_path / f"at-{y}", wire)

    across = at(81.4)
    assert across.ohms == pytest.approx(ohms(28 + 1.4 + 22, 0.5), rel=1e-9)
    assert across.length == 51.4 * mm
    # One whose middle line misses the pad by 0.1 mm, its copper over the pad's edge,
    # does not: a track is where its middle line is, as at its ends.
    assert at(81.6).ohms is None


def test_tracks_of_one_net_that_cross_on_one_layer_are_joined_where_they_cross(board, tmp_path):
    j1, j2 = board.parts("J1", "J2")
    board.path(j1, "IN", j2, current=1 * A)
    # From J1 along and down, to 5 mm past the second, which runs from 10 mm short of
    # the first across it to J2: they cross at (160, 65), neither ending there.
    first = Wire("IN", F, 0.5, [(110.0, 60.0), (160.0, 60.0), (160.0, 70.0)])
    second = Wire("IN", F, 0.5, [(150.0, 65.0), (210.0, 65.0), (210.0, 60.0)])
    reading = one(board, tmp_path / "front", first, second)
    assert reading.ohms == pytest.approx(ohms(50 + 5 + 50 + 5, 0.5), rel=1e-9)
    assert reading.length == 110 * mm
    # On two faces they do not meet.
    under = Wire("IN", B, 0.5, [(150.0, 65.0), (210.0, 65.0), (210.0, 60.0)])
    assert one(board, tmp_path / "faces", first, under).ohms is None


def test_a_figure_is_printed_plainly_whatever_its_size(board):
    (stretch,) = path(board["Q1"], board["J3"], current=1 * A).stretches(board.circuit)[0]

    def shown(ohms: float, volts: float) -> str:
        return str(Reading(stretch, ohms, 10 * mm, 0.5 * mm, volts)).partition("narrowest, ")[2]

    assert shown(0.99949, 0.0983) == "999 mΩ, 98.3 mV"
    assert shown(0.9996, 0.9996) == "1 Ω, 1 V"
    assert shown(1.0, 1.25) == "1 Ω, 1.25 V"
    assert shown(999.4, 12.0) == "999 Ω, 12 V"
    assert shown(999.6, 999.6) == "1 kΩ, 1 kV"
    assert shown(1234.0, 1234.0) == "1.23 kΩ, 1.23 kV"
    assert shown(2_500_000.0, 0.0) == "2500 kΩ, 0 mV"
    assert shown(0.00009996, 0.000_000_16) == "0.1 mΩ, 0.00016 mV"
    # Three figures at any size, written out: thousands and more of kilohms, and as
    # little as there is.
    assert shown(999_500.0, 1e9) == "1000 kΩ, 1000000 kV"
    assert shown(1.2345e21, 1.2345e-12) == "1230000000000000000 kΩ, 0.00000000123 mV"
    assert shown(1.2345e-16, 0.0) == "0.000000000000123 mΩ, 0 mV"


# Round the corners: what never stops a build, and what else joins.


@pytest.mark.parametrize(
    ("dot", "vias"),
    [
        ((110.0, 60.0), ()),  # at the middle of J1.1
        ((110.3, 60.0), ()),  # inside J1.1, off its middle
        ((160.0, 60.0), (Via("IN", VIA, (160.0, 60.0)),)),  # at a via
        ((160.0, 60.0), ()),  # in the open, on the track
        ((150.0, 55.0), ()),  # by itself
    ],
)
def test_a_track_of_no_length_is_no_copper_and_the_board_is_built(board, tmp_path, dot, vias):
    wires = (STRAIGHT, Wire("IN", F, 0.5, [dot, dot]))
    run = Run(wires, vias, 0)
    plain = board.build(tmp_path / "plain" / "out", router=Scripted(run))
    j1, j2 = board.parts("J1", "J2")
    board.path(j1, "IN", j2, current=1 * A)
    reading = one(board, tmp_path / "said" / "out", *wires, vias=vias)
    assert reading.ohms == pytest.approx(ohms(100, 0.5), rel=1e-9) and reading.length == 100 * mm
    assert (
        plain.board.read_bytes() == (tmp_path / "said" / "out" / "carrier.kicad_pcb").read_bytes()
    )
    assert _hashes(tmp_path / "said" / "out") == _hashes(tmp_path / "plain" / "out")


def test_a_piece_shorter_than_a_place_is_wide_joins_what_is_either_side_of_it(board, tmp_path):
    j1, j2 = board.parts("J1", "J2")
    board.path(j1, "IN", j2, current=1 * A)
    for long in (0.00005, 0.00015):
        xs = (110.0, 160.0, 160.0 + long, 210.0)
        wires = [
            Wire("IN", F, 0.5, [(a, 60.0), (b, 60.0)]) for a, b in zip(xs, xs[1:], strict=False)
        ]
        reading = one(board, tmp_path / f"piece-{long}", *wires)
        assert reading.ohms == pytest.approx(ohms(100, 0.5), rel=1e-6)
        assert reading.length is not None and reading.length.mm == pytest.approx(100, abs=1e-4)


def test_a_measurement_that_fails_is_a_reading_that_says_so_and_the_board_is_built(
    board, tmp_path, monkeypatch
):
    from pkidl import paths

    plain = board.build(tmp_path / "plain" / "out", router=Scripted(Run((STRAIGHT,), (), 0)))
    j1, j2, j3 = board.parts("J1", "J2", "J3")
    board.path(j1, "IN", j2, "GND", j3, current=1 * A)
    line = _line_no() - 1

    def broken(*_):
        raise RuntimeError("no such luck")

    monkeypatch.setattr(paths, "_between", broken)
    built = board.build(tmp_path / "said" / "out", router=Scripted(Run((STRAIGHT,), (), 0)))
    assert built.routed is not None and plain.routed is not None
    (measured,) = built.routed.paths
    assert [r.failed for r in measured.stretches] == ["RuntimeError: no such luck"] * 2
    assert (measured.ohms, measured.unmeasured) == (None, 2)
    assert str(measured) == (
        f"path(J1, IN, J2, GND, J3, current=1 A) ({HERE}:{line}): no figure: none of its 2 "
        "stretches is measured\n"
        "  IN, J1 to J2: could not be measured: RuntimeError: no such luck\n"
        "  GND, J2 to J3: could not be measured: RuntimeError: no such luck"
    )
    assert _hashes(tmp_path / "said" / "out") == _hashes(tmp_path / "plain" / "out")
    # And where the tracks of a net cannot be read at all.
    monkeypatch.undo()
    monkeypatch.setattr(paths, "_tracks", broken)
    built = board.build(tmp_path / "read" / "out", router=Scripted(Run((STRAIGHT,), (), 0)))
    assert built.routed is not None
    assert {r.failed for r in built.routed.paths[0].stretches} == {"RuntimeError: no such luck"}
    # A resistance that is no number is not printed as one.
    monkeypatch.undo()
    monkeypatch.setattr(paths, "_between", lambda *_: (float("nan"), 1.0, 0.5))
    built = board.build(tmp_path / "nan" / "out", router=Scripted(Run((STRAIGHT,), (), 0)))
    assert built.routed is not None
    (reading, _) = built.routed.paths[0].stretches
    assert reading.ohms is None
    assert str(reading) == (
        "IN, J1 to J2: could not be measured: ArithmeticError: its resistance comes out as nan"
    )
    with pytest.raises(ValueError, match="nan is not a figure"):
        str(Reading(reading.stretch, float("nan"), 1 * mm, 1 * mm, 1.0))


def test_ends_that_are_one_piece_of_copper_are_joined_with_nothing_between(board, tmp_path):
    from pkidl.paths import _between, _Tracks

    tracks = _Tracks([(0, 1, 10.0, 0.5)], {}, [0, 1, 2])
    assert _between(tracks, [0], [0], 0.035) == (0.0, 0.0, 0.0)
    assert _between(tracks, [0, 1], [1], 0.035) == (0.0, 0.0, 0.0)
    assert _between(tracks, [2], [2, 0], 0.035) == (0.0, 0.0, 0.0)
    assert _between(tracks, [0], [2], 0.035) is None and _between(tracks, [], [0], 0.035) is None
    assert _between(tracks, [0], [1], 0.035) == pytest.approx((ohms(10, 0.5), 10.0, 0.5))
    # R1.1 and R2.1, whose copper is 2.8 mm apart, with five vias 0.8 mm across in a row
    # between them, each over the next: no track, and one piece of copper.
    board.path(board["R1"], "OUT", board["R2"], current=1 * A)
    line = _line_no() - 1
    row = tuple(Via("OUT", VIA, (189.0, y)) for y in (78.8, 79.4, 80.0, 80.6, 81.2))
    (measured,) = measure(board, tmp_path / "row", vias=row)
    (reading,) = measured.stretches
    assert (reading.ohms, reading.length, reading.narrowest, reading.volts) == (
        0.0, Length(0), None, 0.0)  # fmt: skip
    assert str(measured) == (
        f"path(R1, OUT, R2, current=1 A) ({HERE}:{line}): 0 mΩ of track, 0 mV at 1 A\n"
        "  OUT, R1 to R2: joined at one place, with no track between: 0 mΩ, 0 mV"
    )
    (apart,) = measure(board, tmp_path / "apart", vias=row[:4])
    assert apart.stretches[0].ohms is None


def test_a_via_within_a_pad_or_another_via_joins_it_with_no_track(board, tmp_path):
    q1, j3, j1, j2 = board.parts("Q1", "J3", "J1", "J2")
    board.path(q1, j3, current=1 * A)
    board.path(j1, "IN", j2, current=1 * A)

    # A via in the middle of Q1.2, a pad on the front at (122, 79), and from it a
    # track on the back to J3.1.
    def from_via(x: float) -> Reading:
        back = Wire("OUT", B, 0.5, [(x, 79.0), (x, 80.0), (172.0, 80.0)])
        out, _ = measure(board, tmp_path / f"via-{x}", back, vias=(Via("OUT", VIA, (x, 79.0)),))
        return out.stretches[0]

    inside = from_via(122.0)
    assert inside.ohms == pytest.approx(ohms(51, 0.5), rel=1e-9) and inside.length == 51 * mm
    # One 0.8 mm across whose copper is over the pad's edge at 122.5 mm is joined, and
    # one whose copper stops 0.1 mm short of it is not.
    assert from_via(122.7).ohms == pytest.approx(ohms(50.3, 0.5), rel=1e-9)
    assert from_via(123.0).ohms is None

    # Two vias, each 0.8 mm across, 0.5 mm apart, a track ending at each on its own face.
    def vias(apart: float) -> Reading:
        front = Wire("IN", F, 0.5, [(110.0, 60.0), (160.0, 60.0)])
        back = Wire("IN", B, 0.5, [(160.0 + apart, 60.0), (210.0, 60.0)])
        pair = (Via("IN", VIA, (160.0, 60.0)), Via("IN", VIA, (160.0 + apart, 60.0)))
        _, straight = measure(board, tmp_path / f"vias-{apart}", front, back, vias=pair)
        return straight.stretches[0]

    assert vias(0.5).ohms == pytest.approx(ohms(99.5, 0.5), rel=1e-9)
    assert vias(0.5).length == 99.5 * mm
    assert vias(0.9).ohms is None  # their copper 0.1 mm apart


def test_tracks_over_each_other_are_one_strip_whatever_else_touches_either(board, tmp_path):
    j1, j2 = board.parts("J1", "J2")
    board.path(j1, "IN", j2, current=1 * A)
    wide = Wire("IN", F, 1.0, [(110.0, 60.0), (210.0, 60.0)])
    # A stub that ends 0.4 mm off their line: within the wide one and not the narrow.
    stub = Wire("IN", F, 0.5, [(160.0, 60.4), (160.0, 70.0)])
    for name, wires in (("alone", (wide, STRAIGHT)), ("stub", (wide, STRAIGHT, stub)),
                        ("other", (STRAIGHT, stub, wide))):  # fmt: skip
        reading = one(board, tmp_path / name, *wires)
        assert reading.ohms == pytest.approx(ohms(100, 1.0), rel=1e-9)
        assert (reading.length, reading.narrowest) == (100 * mm, 1 * mm)
    # A narrow one from 110 to 170 and a wide one from 150 to 210, a via in the lap.
    lapped = (Wire("IN", F, 0.5, [(110.0, 60.0), (170.0, 60.0)]),
              Wire("IN", F, 1.0, [(150.0, 60.0), (210.0, 60.0)]))  # fmt: skip
    reading = one(board, tmp_path / "lap", *lapped, vias=(Via("IN", VIA, (160.0, 60.2)),))
    assert reading.ohms == pytest.approx(ohms(40, 0.5) + ohms(60, 1.0), rel=1e-9)


def test_stubs_that_end_either_side_of_a_track_at_one_place_leave_it_as_long_as_it_is(
    board, tmp_path
):
    j1, j2 = board.parts("J1", "J2")
    board.path(j1, "IN", j2, current=1 * A)
    up = Wire("IN", F, 0.5, [(160.0, 59.9), (160.0, 50.0)])
    down = Wire("IN", F, 0.5, [(160.0, 60.1), (160.0, 70.0)])
    reading = one(board, tmp_path / "out", STRAIGHT, up, down)
    assert reading.ohms == pytest.approx(ohms(100, 0.5), rel=1e-9) and reading.length == 100 * mm


def test_a_track_that_stops_short_of_another_does_not_cross_it(board, tmp_path):
    j1, j2 = board.parts("J1", "J2")
    board.path(j1, "IN", j2, current=1 * A)
    # From J1 along to 170 mm; and one that starts 1 mm below that line, at 160 mm,
    # and goes on to J2: its line crosses the first, and it does not reach it.
    first = Wire("IN", F, 0.5, [(110.0, 60.0), (170.0, 60.0)])
    second = Wire("IN", F, 0.5, [(160.0, 61.0), (160.0, 70.0), (210.0, 70.0), (210.0, 60.0)])
    assert one(board, tmp_path / "short", first, second).ohms is None


def test_a_pad_is_joined_at_the_point_nearest_its_hole_and_a_via_nearest_its_own_place(tmp_path):
    # J1.1 an oval 6 by 2 mm with its hole at (110, 60) and the middle of its copper
    # 2 mm to the right of it: a track that starts 0.5 mm left of the hole is joined
    # at the hole.
    head, name, rest = SOURCE.partition('(property "Reference" "J1"')
    oval = head.replace(
        '"Conn:P2" (layer "F.Cu") (at 0 0)\n    ', '"Conn:P2X" (layer "F.Cu") (at 0 0)\n    ', 1
    )
    oval += name + rest.replace(
        '(pad "1" thru_hole circle (at 0 0) (size 2 2) (drill 1) (layers "*.Cu") (net "IN"))',
        '(pad "1" thru_hole oval (at 0 0) (size 6 2) (drill 1 (offset 2 0)) (layers "*.Cu") '
        '(net "IN"))', 1)  # fmt: skip
    board = carrier(tmp_path / "carrier", oval)
    j1, j2 = board.parts("J1", "J2")
    board.path(j1, "IN", j2, current=1 * A)
    reading = one(board, tmp_path / "oval", Wire("IN", F, 0.5, [(109.5, 60.0), (210.0, 60.0)]))
    assert reading.length == 100 * mm
    # A via at (160, 65), off the line of the pads: the front track runs on 5 mm past
    # it, and the back one is from it to J2.
    front = Wire("IN", F, 0.5, [(110.0, 60.0), (160.0, 60.0), (160.0, 70.0)])
    back = Wire("IN", B, 0.5, [(160.0, 65.0), (210.0, 65.0), (210.0, 60.0)])
    reading = one(board, tmp_path / "via", front, back, vias=(Via("IN", VIA, (160.0, 65.0)),))
    assert reading.length == 110 * mm


def test_paths_of_two_files_are_in_the_order_of_the_files_and_then_the_lines(board, tmp_path):
    from dataclasses import replace

    from pkidl.intent import Source

    j1, j2, q1, j3 = board.parts("J1", "J2", "Q1", "J3")
    late = replace(path(j1, "IN", j2, current=1 * A), source=Source("/boards/b/board.py", 1))
    early = replace(path(q1, j3, current=1 * A), source=Source("/boards/a/blocks.py", 99))
    board.add(late, early)
    assert [m.path for m in measure(board, tmp_path / "out", STRAIGHT)] == [early, late]


# What each rule is bounded by.


def test_an_end_beside_the_end_of_another_track_is_not_part_way_along_it(board, tmp_path):
    j1, j2 = board.parts("J1", "J2")
    board.path(j1, "IN", j2, current=1 * A)
    # A track from J1 that stops 0.2 mm aside of the middle of one 0.5 mm wide, which
    # goes on to J2: within that track's copper, and *by* in from its end. Part way
    # along is more than a tenth of a micrometre from each end, whichever end it is.
    stem = Wire("IN", F, 0.5, [(110.0, 60.0), (159.8, 60.0)])

    def from_its_start(by: float) -> Reading:
        bar = Wire("IN", F, 0.5, [(160.0, 60.0 - by), (160.0, 70.0), (210.0, 70.0), (210.0, 60.0)])
        return one(board, tmp_path / f"start-{by}", stem, bar)

    def from_its_end(by: float) -> Reading:
        bar = Wire("IN", F, 0.5, [(210.0, 60.0), (210.0, 70.0), (160.0, 70.0), (160.0, 60.0 - by)])
        return one(board, tmp_path / f"end-{by}", bar, stem)

    for inside in (from_its_start, from_its_end):
        assert inside(0.00005).ohms is None
        joined = inside(0.0002)
        assert joined.ohms == pytest.approx(ohms(49.8 + 70, 0.5), rel=1e-9)
        assert joined.length == 119.8 * mm


def test_pads_over_each_other_on_two_faces_are_joined_only_by_a_via_through_both(tmp_path):
    # R2 on the back with its pad on OUT under R1.1, which is on the front at (189, 78).
    board = carrier(tmp_path / "carrier", places={k: v for k, v in PLACES.items() if k != "R2"})
    board.place(board["R2"], at=(88 * mm, 28 * mm), facing=Edge.TOP, side="back")
    board.path(board["R1"], "OUT", board["R2"], current=1 * A)
    built = board.build(tmp_path / "placed", router=Scripted())
    placed = {str(p[2]): fp for fp in find_all(parse(built.board.read_text()), "footprint")
              for p in find_all(fp, "property") if p[1] == "Reference"}  # fmt: skip
    assert pad_xy(placed["R1"], "1") == pad_xy(placed["R2"], "1") == (189, 78)
    layers = {ref: [str(layer) for pad in find_all(fp, "pad") if pad[1] == "1"
                    for layer in find_all(pad, "layers")[0][1:]]
              for ref, fp in placed.items()}  # fmt: skip
    assert (layers["R1"], layers["R2"]) == ([F], [B])
    apart = one(board, tmp_path / "apart")
    assert apart.ohms is None and str(apart) == "OUT, R1 to R2: not joined by track"
    through = one(board, tmp_path / "through", vias=(Via("OUT", VIA, (189.0, 78.0)),))
    assert (through.ohms, through.length, through.narrowest) == (0.0, Length(0), None)


def test_a_track_is_cut_where_its_middle_line_passes_within_a_place_of_a_point(board, tmp_path):
    j1, j2 = board.parts("J1", "J2")
    board.path(j1, "IN", j2, current=1 * A)

    # Two tracks that cross at (160, 60), each going *past* it: their ends are no
    # place together, and the crossing is too near the end of each to be one part way
    # along. Each passes within a place of the end of the other, and is cut there.
    def corner(past: float) -> Reading:
        along = Wire("IN", F, 0.5, [(110.0, 60.0), (160.0 + past, 60.0)])
        down = Wire("IN", F, 0.5, [(160.0, 60.0 - past), (160.0, 70.0), (210.0, 70.0),
                                   (210.0, 60.0)])  # fmt: skip
        return one(board, tmp_path / f"corner-{past}", along, down)

    assert 2**0.5 * 0.00009 > 0.0001
    met = corner(0.00009)
    assert met.ohms == pytest.approx(ohms(120, 0.5), rel=1e-6)
    assert met.length is not None and met.length.mm == pytest.approx(120, abs=2e-4)
    assert corner(0.0).ohms == pytest.approx(ohms(120, 0.5), rel=1e-9)


@pytest.mark.parametrize("order", [(0, 1, 2), (2, 0, 1), (0, 2, 1)])
def test_two_points_that_are_each_one_place_with_a_third_are_one_place(board, tmp_path, order):
    j1, j2 = board.parts("J1", "J2")
    board.path(j1, "IN", j2, current=1 * A)
    # Two tracks whose ends are 0.15 um apart are not joined; with the end of a third
    # between the two, within a place of each, they are, whichever is laid first.
    wires = (Wire("IN", F, 0.5, [(110.0, 60.0), (160.0, 60.0)]),
             Wire("IN", F, 0.5, [(160.00015, 60.0), (210.0, 60.0)]),
             Wire("IN", F, 0.5, [(160.000075, 60.0), (160.000075, 50.0)]))  # fmt: skip
    assert one(board, tmp_path / "two", *wires[:2]).ohms is None
    reading = one(board, tmp_path / "three", *(wires[n] for n in order))
    assert reading.ohms == pytest.approx(ohms(100 - 0.00015, 0.5), rel=1e-8)


def test_a_reading_that_failed_says_whether_its_net_has_a_pour(board, tmp_path, monkeypatch):
    from pkidl import paths

    j1, j2, j3 = board.parts("J1", "J2", "J3")
    board.pour("GND", layer="B.Cu")
    board.path(j1, "IN", j2, "GND", j3, current=1 * A)

    def broken(*_):
        raise RuntimeError("no such luck")

    monkeypatch.setattr(paths, "_between", broken)
    built = board.build(tmp_path / "out", router=Scripted(Run((STRAIGHT,), (), 0)))
    assert built.routed is not None
    (measured,) = built.routed.paths
    assert [(str(r.stretch.net), bool(r.failed), r.poured) for r in measured.stretches] == [
        ("IN", True, False),
        ("GND", True, True),
    ]


@pytest.mark.parametrize("order", [(0, 1, 2), (2, 0, 1)])
@pytest.mark.parametrize("down", [True, False])
def test_a_track_that_stops_short_of_another_cuts_it_nowhere(board, tmp_path, order, down):
    j1, j2 = board.parts("J1", "J2")
    board.path(j1, "IN", j2, current=1 * A)
    # A second track laid all but on the first: 0.2 um below its middle line at 130 mm
    # and 0.2 um above it at 190 mm, so that it ends within its copper at each and
    # crosses it at 160 mm. They are two strips either side of where they cross.
    lapped = Wire("IN", F, 0.5, [(130.0, 59.9998), (190.0, 60.0002)])
    two = one(board, tmp_path / "two", STRAIGHT, lapped)
    assert two.ohms == pytest.approx(ohms(20 + 15 + 15 + 20, 0.5), rel=1e-6)
    # A third comes down at 150 mm and stops 1 mm short of them: its line crosses
    # theirs past its end, or before its start laid the other way, and that is no
    # crossing. Neither is cut there, and what they are is what they were, whichever
    # is laid first.
    ends = [(150.0, 70.0), (150.0, 61.0)]
    short = Wire("IN", F, 0.5, ends if down else ends[::-1])
    wires = (STRAIGHT, lapped, short)
    three = one(board, tmp_path / f"three-{down}", *(wires[n] for n in order))
    assert three.ohms == pytest.approx(two.ohms, rel=1e-9)
    assert (three.length, three.narrowest) == (two.length, two.narrowest)


# How it reads.


def test_a_path_of_one_stretch_that_is_not_measured_says_so_of_the_one(board, tmp_path):
    j1, j2 = board.parts("J1", "J2")
    board.path(j1, "IN", j2, current=1 * A)
    line = _line_no() - 1
    (measured,) = measure(board, tmp_path / "bare")
    assert str(measured) == (
        f"path(J1, IN, J2, current=1 A) ({HERE}:{line}): no figure: its one stretch is not "
        "measured\n"
        "  IN, J1 to J2: not joined by track"
    )


@pytest.mark.parametrize("unit", [A, mA])
@pytest.mark.parametrize("count", [float("nan"), float("inf"), float("-inf")])
def test_a_current_of_no_number_of_amps_is_refused(unit, count):
    told = f"a current is a number of amps, not {count!r}: write 1 \\* A"
    with pytest.raises(ValueError, match=told):
        _ = count * unit
    with pytest.raises(ValueError, match=told):
        _ = unit * count


def test_the_corpus_build_says_each_path_as_it_was_measured(board, tmp_path, monkeypatch, capsys):
    import importlib.util
    from types import SimpleNamespace

    from pkidl.routing import Routed

    j1, j2, q1, j3 = board.parts("J1", "J2", "Q1", "J3")
    board.path(j1, "IN", j2, current=1 * A)
    board.path(q1, j3, current=1 * A)
    found = tuple(measure(board, tmp_path / "measured", STRAIGHT))
    spec = importlib.util.spec_from_file_location(
        "corpus_script", File(__file__).parent.parent / "scripts" / "corpus.py"
    )
    assert spec is not None and spec.loader is not None
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    routed = Routed((), (), (("", Run((), (), 0)),), paths=found)
    made = SimpleNamespace(routed=routed, solution=SimpleNamespace(poses={}, chosen=()))
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "board.py").write_text(
        "from types import SimpleNamespace\nboard = SimpleNamespace(build=lambda d, name: MADE)\n"
    )
    monkeypatch.setattr(script, "BOARDS", {"b": ("t0", "a board")})
    monkeypatch.setattr(script, "board_dir", lambda board_id: tmp_path / "src")
    monkeypatch.setattr("builtins.MADE", made, raising=False)
    assert script.build(tmp_path / "out") == 0
    said = json.loads((tmp_path / "out" / "b" / "built.json").read_text())
    assert said["paths"] == [str(m) for m in found] and len(said["paths"]) == 2
    printed = capsys.readouterr().out.splitlines()
    assert printed[1:] == [
        f"    {said['paths'][0].splitlines()[0]}",
        "      IN, J1 to J2: 100 mm of track, 0.5 mm at its narrowest, 98.3 mΩ, 98.3 mV",
        f"    {said['paths'][1].splitlines()[0]}",
        "      OUT, Q1 to J3: not joined by track",
    ]
    # A board that was not routed has none.
    monkeypatch.setattr("builtins.MADE", SimpleNamespace(routed=None, solution=made.solution))
    assert script.build(tmp_path / "out") == 0
    assert json.loads((tmp_path / "out" / "b" / "built.json").read_text())["paths"] == []


# The neck of a stretch, through all the copper of its net (tests/test_pkidl_neck.py
# has the shapes it is right on).


def test_one_chain_of_tracks_has_its_narrowest_for_a_neck_and_reads_as_it_did(board, tmp_path):
    board.path(board["J1"], "IN", board["J2"], current=1 * A)
    chain = (
        Wire("IN", F, 0.8, [(110.0, 60.0), (150.0, 60.0)]),
        Wire("IN", F, 0.3, [(150.0, 60.0), (150.0, 70.0), (180.0, 70.0)]),
        Wire("IN", B, 0.6, [(180.0, 70.0), (210.0, 60.0)]),
    )
    reading = one(board, tmp_path / "out", *chain, vias=(Via("IN", VIA, (180.0, 70.0)),))
    assert reading.neck == reading.narrowest == 0.3 * mm
    (piece,) = reading.across
    assert (piece.width, piece.layer, piece.of, reading.filled) == (0.3 * mm, F, "track", "")
    assert str(reading) == ("IN, J1 to J2: 111.6 mm of track, 0.3 mm at its narrowest, 116 mΩ, "
                            "116 mV")  # fmt: skip
    # Nothing is said twice of a reading whose neck is the narrowest of its tracks, and
    # a neck that is not is said after the rest.
    assert str(replace(reading, neck=0.29 * mm, across=(replace(piece, width=0.29 * mm),))) == (
        f"{reading}; a neck of 0.29 mm, of track at ({piece.at[0].mm:g}, {piece.at[1].mm:g}) "
        "on F.Cu"
    )


def test_a_via_joins_two_layers_and_its_pad_can_be_the_neck_of_wide_tracks(board, tmp_path):
    # Tracks 3 mm wide, through a via 0.8 mm across: the copper round the via's pad is
    # less than the tracks are wide. The via's barrel is not in it.
    board.path(board["J1"], "IN", board["J2"], current=1 * A)
    wide = (
        Wire("IN", F, 3.0, [(110.0, 60.0), (160.0, 60.0)]),
        Wire("IN", B, 3.0, [(160.0, 60.0), (210.0, 60.0)]),
    )
    reading = one(board, tmp_path / "out", *wide, vias=(Via("IN", VIA, (160.0, 60.0)),))
    assert reading.narrowest == 3 * mm and reading.neck == Length(2_512_000)
    assert str(reading) == (
        "IN, J1 to J2: 100 mm of track, 3 mm at its narrowest, 16.4 mΩ, 16.4 mV; a neck of "
        "2.512 mm, of the copper round a via at (160, 60) on F.Cu"
    )


def test_a_reading_says_where_its_neck_is_narrower_than_its_current_needs(board, tmp_path):
    j1, j2 = board.parts("J1", "J2")
    board.pour("GND", layer="B.Cu")
    board.path(j1, "GND", j2, current=3 * A)  # needs 1.874 mm: the 2 mm of spokes will do
    board.path(j1, "GND", j2, current=4 * A)  # needs 3.091 mm: they will not
    (enough,), (short,) = (m.stretches for m in measure(board, tmp_path / "out"))
    assert (enough.neck, enough.needs) == (2 * mm, Length(1_874_000))
    assert (short.neck, short.needs) == (2 * mm, Length(3_091_000))
    assert "; a neck of 2 mm in 4 pieces, the widest 0.5 mm of the relief of" in str(enough)
    assert str(short) == (
        "GND, J1 to J2: not joined by track; GND has a pour, whose resistance is not measured; "
        "a neck of 2 mm where 4 A needs 3.091 mm in 4 pieces, the widest 0.5 mm of the relief "
        "of J1.2 at (109.17, 64.83) on B.Cu, on pkidl's model of the fill"
    )
    # A neck as wide as is needed is wide enough, and one of a single piece says what
    # it is of with no count.
    piece = Piece(1 * mm, (5 * mm, 6.5 * mm), F, "pour")
    made = Reading(short.stretch, poured=True, current=2 * A, needs=1 * mm, neck=1 * mm,
                   across=(piece,), filled=KICAD)  # fmt: skip
    assert str(made) == (
        "GND, J1 to J2: not joined by track; GND has a pour, whose resistance is not measured; "
        "a neck of 1 mm, of pour at (5, 6.5) on F.Cu, on KiCad's fill"
    )
    assert "a neck of 1 mm where 2 A needs 1.001 mm, of pour" in str(
        replace(made, needs=Length(1_001_000))
    )
    # A pour that no fill was looked at for is said as it was: it is not measured.
    assert str(Reading(short.stretch, poured=True)) == (
        "GND, J1 to J2: not joined by track; GND has a pour, which is not measured"
    )


@pytest.mark.parametrize("where", ["the triangles", "the neck"])
def test_a_neck_that_cannot_be_measured_leaves_every_other_figure_as_it_is(
    board, tmp_path, monkeypatch, where
):
    import shapely

    from pkidl import neck

    j1, j2 = board.parts("J1", "J2")
    board.pour("GND", layer="B.Cu")
    board.path(j1, "IN", j2, current=2 * A)
    board.path(j1, "GND", j2, current=1 * A)
    board.path(board["Q1"], board["J3"], current=1 * A)
    whole = measure(board, tmp_path / "whole", STRAIGHT)

    def raises(*_, **__):
        raise shapely.errors.GEOSException("LocateFailureException: Could not locate vertex.")

    if where == "the triangles":  # as GEOS has raised, of points in a line
        monkeypatch.setattr(neck.shapely, "delaunay_triangles", raises)
    else:
        monkeypatch.setattr(neck.Necks, "between", raises)
    # ``measure`` fails on a reading that says it could not be measured: none does.
    broken = measure(board, tmp_path / "broken", STRAIGHT)
    why = "GEOSException: LocateFailureException: Could not locate vertex."
    pairs = [(a, b) for one, two in zip(whole, broken, strict=True)
             for a, b in zip(one.stretches, two.stretches, strict=True)]  # fmt: skip
    for was, now in pairs:
        if not now.neck_failed:  # copper with nothing to cut into triangles
            assert now == was
            continue
        bare = replace(was, neck=None, across=(), filled="")
        assert now == replace(bare, neck_failed=why)
        assert str(now) == f"{bare}; its neck could not be measured: {why}"
    track, pour, apart = (now for _, now in pairs)
    assert track.neck_failed and pour.neck_failed
    assert (track.ohms, track.length, track.narrowest, track.volts, track.needs) == (
        pytest.approx(ohms(100, 0.5), rel=1e-9), 100 * mm, 0.5 * mm,
        pytest.approx(2 * ohms(100, 0.5), rel=1e-9), Length(926_000))  # fmt: skip
    assert str(track) == (
        "IN, J1 to J2: 100 mm of track, 0.5 mm at its narrowest where 2 A needs 0.926 mm, "
        f"98.3 mΩ, 197 mV; its neck could not be measured: {why}"
    )
    assert str(pour) == ("GND, J1 to J2: not joined by track; GND has a pour, which is not "
                         f"measured; its neck could not be measured: {why}")  # fmt: skip
    assert bool(apart.neck_failed) == (where == "the neck")
    # The paths' totals, and the board that is written, are the same.
    assert [(m.ohms, m.volts, m.unmeasured) for m in broken] == [
        (m.ohms, m.volts, m.unmeasured) for m in whole
    ]
    assert _hashes(tmp_path / "broken") == _hashes(tmp_path / "whole")
    # Ends that are one piece of copper say it after what they said.
    one = Reading(track.stretch, 0.0, Length(0), None, 0.0, neck_failed="it broke")
    assert str(one) == ("IN, J1 to J2: joined at one place, with no track between: 0 mΩ, 0 mV; "
                        "its neck could not be measured: it broke")  # fmt: skip


def _refilled(written: File, layer: str, ring: list[tuple[float, float]]) -> File:
    """The board at *written* with a fill in each of its zones on *layer*, as KiCad
    leaves one it has refilled and saved: the one piece *ring* is round."""
    drawn = parse(written.read_text())
    for zone in find_all(drawn, "zone"):
        xy = [["xy", f"{x:g}", f"{y:g}"] for x, y in ring]
        zone.append(["filled_polygon", ["layer", layer], ["pts", *xy]])
    written.write_text(dumps(drawn))
    return written


def test_a_board_kicad_has_filled_is_measured_on_kicads_fill_and_the_scorecard_has_it(
    tmp_path, monkeypatch, capsys
):
    import importlib.util
    import runpy

    carrier(tmp_path / "src")  # its inputs, for the board file below
    board_py = tmp_path / "src" / "board.py"
    board_py.write_text(
        "from pkidl import A, Board, Edge, mm\n"
        f"board = Board.from_inputs({str(tmp_path / 'src')!r})\n"
        f"for ref, (x, y) in {PLACES!r}.items():\n"
        "    board.place(board[ref], at=(x * mm, y * mm), facing=Edge.TOP)\n"
        "board.rules(track=0.5 * mm, clearance=0.2 * mm)\n"
        'board.pour("GND", layer="B.Cu")\n'
        'board.path(board["J1"], "GND", board["J2"], current=10 * A)\n'
        "board.route()\n"
    )
    said = runpy.run_path(str(board_py))["board"]
    out = tmp_path / "build" / "b"
    built = said.build(out, "built", router=Scripted())
    ((reading,),) = (m.stretches for m in built.routed.paths)
    assert (reading.neck, reading.filled) == (2 * mm, MODEL)
    # KiCad's fill of it, here one no model would make: a strip 3 mm wide from pin to
    # pin, over both and with no relief, notched to 1 mm at (151, 63.5).
    _refilled(built.board, B, [(108, 62.5), (212, 62.5), (212, 65.5), (153, 65.5), (151, 63.5),
                               (149, 65.5), (108, 65.5)])  # fmt: skip
    spec = importlib.util.spec_from_file_location(
        "corpus_script", File(__file__).parent.parent / "scripts" / "corpus.py"
    )
    assert spec is not None and spec.loader is not None
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    (found,) = script.paths(board_py, parse(built.board.read_text()))
    line = ("  GND, J1 to J2: not joined by track; GND has a pour, whose resistance is not "
            "measured; a neck of 1 mm where 10 A needs 15.208 mm, of pour at (151, 63) on "
            "B.Cu, on KiCad's fill")  # fmt: skip
    assert found.splitlines()[1] == line
    # The scorecard's row for the built board has it, and it is printed under the row.
    (out / "built.json").write_text(json.dumps({"built": True, "placed": [], "routed": []}))
    for report in ("drc.json", "built-drc.json"):
        (out / report).write_text(json.dumps({"violations": []}))
    (out / "reference.kicad_pcb").write_text(built.board.read_text())
    monkeypatch.setattr(script, "BOARDS", {"b": ("t0", "a licence", "a source")})
    monkeypatch.setattr(script, "board_dir", lambda board_id: tmp_path / "src")
    script.score(tmp_path / "build")
    row = json.loads((tmp_path / "build" / "scorecard.json").read_text())["b"]
    assert row["built"]["paths"] == [found]
    assert f"       {line}" in capsys.readouterr().out.splitlines()
    # A board file that says no path has none.
    board_py.write_text("".join(line for line in board_py.read_text().splitlines(True)
                                if "board.path(" not in line))  # fmt: skip
    assert script.paths(board_py, parse(built.board.read_text())) == []


# How wide a current needs its tracks, and the nets that are laid that wide.


def _warms(amps: float, wide: Length, thick: Length) -> float:
    """How much a track warms by the fit, in degrees, the lengths in mils."""
    return 215.3 * amps**2 * (wide.mm / 0.0254) ** -1.15 / (thick.mm / 0.0254)


def test_a_current_needs_the_width_the_fit_to_ipc_2152_gives_an_outer_layer():
    ounce = 0.035 * mm
    # 22.10 mil and 3.27 mil, each up to the next whole micrometre.
    assert needed(1.5 * A, 10 * degC, ounce) == Length(562_000)
    assert needed(500 * mA, 10 * degC, ounce) == Length(84_000)
    for amps, rise, thick in ((1.5, 10, ounce), (0.5, 10, ounce), (7, 25, 0.07 * mm)):
        wide = needed(amps * A, rise * degC, thick)
        assert wide.nm % 1000 == 0
        # Put back into the fit, it warms by no more than the rise, and a micrometre
        # less by more.
        assert _warms(amps, wide, thick) <= rise < _warms(amps, wide - Length(1000), thick)
        assert _warms(amps, wide, thick) == pytest.approx(rise, rel=0.02)
    # Wider for more current, for thinner copper and for a smaller rise.
    wide = [needed(amps * A, 10 * degC, ounce) for amps in (0.5, 1, 1.5, 2, 5, 10)]
    assert wide == sorted(set(wide))
    assert needed(1.5 * A, 10 * degC, 0.018 * mm) > needed(1.5 * A, 10 * degC, ounce)
    assert needed(1.5 * A, 10 * degC, ounce) > needed(1.5 * A, 10 * degC, 0.07 * mm)
    assert needed(1.5 * A, 5 * degC, ounce) > needed(1.5 * A, 10 * degC, ounce)
    assert needed(1.5 * A, 10 * degC, ounce) > needed(1.5 * A, 20 * degC, ounce)


def test_how_much_a_track_may_warm_is_a_rule_and_ten_degrees_where_none_is_said(board):
    (said,) = [s for s in board.statements() if isinstance(s, Rules)]
    assert said.rise == 10 * degC
    # A board that does not say it reads, and is as data, what it was.
    assert str(said) == "rules(track=0.5 mm, clearance=0.2 mm, edge=0.5 mm)"
    assert said.data() == {"rules": {"track": 500_000, "clearance": 200_000, "edge": 500_000}}
    assert said.claims()["the board", "temperature rise"] == 10 * degC
    assert rules(track=0.5 * mm, clearance=0.2 * mm, rise=10 * degC) == said
    two = rules(track=0.5 * mm, clearance=0.2 * mm, rise=20 * degC)
    assert two.rise == Rise(20_000) and two != said
    assert str(two) == "rules(track=0.5 mm, clearance=0.2 mm, edge=0.5 mm, rise=20 °C)"
    assert two.data() == {"rules": {"track": 500_000, "clearance": 200_000, "edge": 500_000,
                                    "rise": 20_000}}  # fmt: skip
    json.dumps(two.data())
    assert two.claims()["the board", "temperature rise"] == 20 * degC
    # Said once, as each rule is.
    board.add(two)
    (conflict,) = board.conflicts()
    assert str(conflict).startswith("the board: temperature rise is 10 °C (")
    assert " and 20 °C (" in str(conflict)
    with pytest.raises(ValueError, match=r"rules\(\): rise= 0 °C is not a rise"):
        board.rules(track=0.5 * mm, clearance=0.2 * mm, rise=0 * degC)
    with pytest.raises(ValueError, match=r"rules\(\): rise= -5 °C is not a rise"):
        board.rules(track=0.5 * mm, clearance=0.2 * mm, rise=-5 * degC)
    for bare in (10, 10.0, "10", True, 10 * mm):
        with pytest.raises(TypeError, match=r"rise= takes a rise in temperature, such as "
                                            r"10 \* degC, not"):  # fmt: skip
            board.rules(track=0.5 * mm, clearance=0.2 * mm, rise=bare)
    assert len([s for s in board.statements() if isinstance(s, Rules)]) == 2


def _wide(board: Board) -> dict[str, Length]:
    (said,) = [s for s in board.statements() if isinstance(s, Rules)]
    paths = [s for s in board.statements() if isinstance(s, Path)]
    return widths(paths, board.circuit, said)


def test_a_net_no_path_goes_through_is_no_wider_than_a_track(board):
    assert _wide(board) == {}


def test_a_path_whose_current_needs_less_than_a_track_widens_nothing(board):
    # 1 A needs 0.278 mm, and a track is 0.5 mm.
    board.path(board["J1"], "IN", board["J2"], current=1 * A)
    assert needed(1 * A, 10 * degC, 0.035 * mm) == Length(278_000)
    assert _wide(board) == {}


def test_the_nets_of_a_path_are_as_wide_as_its_current_needs_and_no_other_net_is(board):
    j3, j4 = board.parts("J3", "J4")
    board.path("IN", board["Q1"], j3, board.parts("R1", "R2"), "LOAD", j4, "GND", current=2 * A)
    # OUT twice and LOAD: IN and GND say where it comes in and goes out, and are no
    # stretch. Parts side by side do not halve what their net is given.
    assert _wide(board) == {"LOAD": Length(926_000), "OUT": Length(926_000)}
    assert list(_wide(board)) == ["LOAD", "OUT"]


@pytest.mark.parametrize(
    ("said", "wide"),
    [({}, {"IN": Length(926_000)}), ({"rise": 20 * degC}, {"IN": Length(507_000)}),
     ({"rise": 21 * degC}, {}), ({"copper": 0.07 * mm}, {"IN": Length(507_000)}),
     ({"copper": 0.08 * mm}, {}), ({"track": 0.926 * mm}, {}),
     ({"track": 0.925 * mm}, {"IN": Length(926_000)})],
)  # fmt: skip
def test_a_net_is_as_wide_as_the_boards_rise_and_copper_ask_and_never_narrower_than_a_track(
    board, said, wide
):
    path = board.path(board["J1"], "IN", board["J2"], current=2 * A)
    held = rules(**{"track": 0.5 * mm, "clearance": 0.2 * mm, **said})
    assert widths([path], board.circuit, held) == wide


def test_a_net_on_two_paths_takes_the_larger_of_their_currents_and_not_their_sum(board):
    j1, j2, q1 = board.parts("J1", "J2", "Q1")
    board.path(j1, "IN", j2, current=2 * A)
    board.path(j1, "IN", q1, board["J3"], current=3 * A)
    three, five = needed(3 * A, 10 * degC, 0.035 * mm), needed(5 * A, 10 * degC, 0.035 * mm)
    assert (three, five) == (Length(1_874_000), Length(4_556_000))
    assert _wide(board) == {"IN": three, "OUT": three}
    # Whichever is said first.
    other = [s for s in board.statements() if isinstance(s, Path)][::-1]
    (said,) = [s for s in board.statements() if isinstance(s, Rules)]
    assert widths(other, board.circuit, said) == {"IN": three, "OUT": three}


def _classes(project: File) -> tuple[list[tuple[str, float, float]], list[dict[str, str]]]:
    wrote = json.loads(project.read_text())["net_settings"]
    return ([(c["name"], c["track_width"], c["clearance"]) for c in wrote["classes"]],
            wrote["netclass_patterns"])  # fmt: skip


def test_a_wider_net_is_in_a_class_of_its_width_for_the_router_and_in_the_project(board, tmp_path):
    from pkidl.dsn import write_dsn

    j1, j2, q1, j3 = board.parts("J1", "J2", "Q1", "J3")
    board.path(j1, "IN", j2, current=2 * A)
    board.path(q1, j3, board.parts("R1", "R2"), board["J4"], current=2 * A)
    board.path(j3, "GND", board["J4"], current=3 * A)
    router = Scripted(Run((STRAIGHT,), (), 0))
    built = board.build(tmp_path / "out", router=router)
    job = router.asked[0][1]
    # A class a width, named for it, the narrowest first after Default.
    assert list(job.netclasses) == [NetClass("Default", 0.2, 0.5), NetClass("0.926 mm", 0.2, 0.926),
                                    NetClass("1.874 mm", 0.2, 1.874)]  # fmt: skip
    assert dict(job.members) == {"0.926 mm": ["IN", "LOAD", "OUT"], "1.874 mm": ["GND"]}
    assert (job.neck_down, job.fan_out) == (False, False)
    assert all(asked.netclasses == job.netclasses and asked.members == job.members
               for _, asked, _, _ in router.asked)  # fmt: skip
    # As a router reads it: each net in its class, at its width.
    dsn = write_dsn(tmp_path / "told.dsn", list(job.footprints), list(job.outline),
                    list(job.netclasses), {c: list(n) for c, n in job.members.items()})  # fmt: skip
    told = [line.strip() for line in dsn.read_text().splitlines()]
    assert [
        (told[n], told[n + 2]) for n, line in enumerate(told) if line.startswith("(class ")
    ] == [
        ('(class "0.926 mm" "IN" "LOAD" "OUT"', "(rule (width 926) (clearance 200))"),
        ('(class "1.874 mm" "GND"', "(rule (width 1874) (clearance 200))"),
    ]
    # The project has the classes and which nets are in each.
    assert built.project is not None
    assert _classes(built.project) == (
        [("Default", 0.5, 0.2), ("0.926 mm", 0.926, 0.2), ("1.874 mm", 1.874, 0.2)],
        [{"netclass": "0.926 mm", "pattern": "IN"}, {"netclass": "0.926 mm", "pattern": "LOAD"},
         {"netclass": "0.926 mm", "pattern": "OUT"}, {"netclass": "1.874 mm", "pattern": "GND"}],
    )  # fmt: skip
    assert json.loads(built.project.read_text())["board"]["design_settings"]["rules"][
        "min_track_width"] == 0.5  # fmt: skip


def test_kicad_is_held_to_the_width_of_each_class_as_the_least(board, tmp_path):
    j1, j2, q1, j3 = board.parts("J1", "J2", "Q1", "J3")
    board.path(j1, "IN", j2, current=2 * A)
    board.path(q1, j3, current=3 * A)
    built = board.build(tmp_path / "out", router=Scripted(Run((STRAIGHT,), (), 0)))
    assert built.project is not None
    assert (
        built.project.with_suffix(".kicad_dru").read_text()
        == """(version 1)

# a path's 2 A needs 0.926 mm to warm by no more than 10 °C in 0.035 mm copper
(rule "0.926 mm width"
  (severity error)
  (condition "A.NetClass == '0.926 mm'")
  (constraint track_width (min 0.926mm)))

# a path's 3 A needs 1.874 mm to warm by no more than 10 °C in 0.035 mm copper
(rule "1.874 mm width"
  (severity error)
  (condition "A.NetClass == '1.874 mm'")
  (constraint track_width (min 1.874mm)))
"""
    )
    assert sorted(f.name for f in (tmp_path / "out").iterdir()) == [
        "carrier.kicad_dru", "carrier.kicad_pcb", "carrier.kicad_pro"]  # fmt: skip


def test_a_board_that_is_not_routed_has_its_wider_nets_in_the_project_all_the_same(tmp_path):
    bare = carrier(tmp_path / "carrier", routed=False)
    bare.path(bare["J1"], "IN", bare["J2"], current=2 * A)
    built = bare.build(tmp_path / "out", router=Scripted())
    assert built.routed is None and built.project is not None
    assert _classes(built.project) == ([("Default", 0.5, 0.2), ("0.926 mm", 0.926, 0.2)],
                                       [{"netclass": "0.926 mm", "pattern": "IN"}])  # fmt: skip
    assert built.project.with_suffix(".kicad_dru").exists()


@pytest.mark.parametrize("amps", [None, 1])
def test_a_board_with_no_wider_net_has_the_one_class_and_no_rules_file(board, tmp_path, amps):
    if amps is not None:
        board.path(board["J1"], "IN", board["J2"], current=amps * A)
    router = Scripted(Run((STRAIGHT,), (), 0))
    built = board.build(tmp_path / "out", router=router)
    job = router.asked[0][1]
    assert list(job.netclasses) == [NetClass("Default", 0.2, 0.5)] and dict(job.members) == {}
    assert built.project is not None
    assert _classes(built.project) == ([("Default", 0.5, 0.2)], [])
    assert sorted(f.name for f in (tmp_path / "out").iterdir()) == [
        "carrier.kicad_pcb", "carrier.kicad_pro"]  # fmt: skip


def test_a_reading_has_what_its_current_needs_and_says_so_where_the_track_is_narrower(
    board, tmp_path
):
    j1, j2 = board.parts("J1", "J2")
    board.path(j1, "IN", j2, current=1 * A)
    board.path(j1, "IN", j2, current=2 * A)
    board.path(board["Q1"], board["J3"], current=2 * A)
    wide = Wire("IN", F, 0.926, [(110.0, 60.0), (160.0, 60.0)])
    neck = Wire("IN", F, 0.925, [(160.0, 60.0), (210.0, 60.0)])
    for other, least, short in ((0.925, "0.925 mm", " where 2 A needs 0.926 mm"),
                                (0.926, "0.926 mm", ""), (1.5, "0.926 mm", "")):  # fmt: skip
        wires = (wide, replace(neck, width=other))
        less, more, apart = measure(board, tmp_path / f"out{other}", *wires)
        # Each reading has its own path's current and what that needs, measured or not.
        assert [(r.current, r.needs) for m in (less, more, apart) for r in m.stretches] == [
            (1 * A, Length(278_000)),
            (2 * A, Length(926_000)),
            (2 * A, Length(926_000)),
        ]
        (lesser,), (greater,), (unjoined,) = less.stretches, more.stretches, apart.stretches
        assert str(greater).startswith(
            f"IN, J1 to J2: 100 mm of track, {least} at its narrowest{short}, "
        )
        # The same copper is wide enough for the path that carries less.
        assert str(lesser).startswith(f"IN, J1 to J2: 100 mm of track, {least} at its narrowest, ")
        assert str(unjoined) == "OUT, Q1 to J3: not joined by track"
    # A reading made with nothing said of what it needs reads as it did.
    assert str(Reading(greater.stretch, 0.1, 10 * mm, 0.1 * mm, 0.2)) == (
        "IN, J1 to J2: 10 mm of track, 0.1 mm at its narrowest, 100 mΩ, 200 mV"
    )
    assert str(Reading(greater.stretch, 0.1, 10 * mm, 0.1 * mm, 0.2, True, "", 2 * A, 1 * mm)) == (
        "IN, J1 to J2: 10 mm of track, 0.1 mm at its narrowest where 2 A needs 1 mm, at most "
        "100 mΩ, 200 mV: IN has a pour as well, which is not measured"
    )


def test_what_a_reading_needs_is_by_the_rise_and_the_copper_the_board_says(tmp_path):
    warm = carrier(tmp_path / "carrier", rise=20 * degC, copper=0.07 * mm)
    warm.path(warm["J1"], "IN", warm["J2"], current=2 * A)
    reading = one(warm, tmp_path / "out", STRAIGHT)
    assert reading.needs == needed(2 * A, 20 * degC, 0.07 * mm) == Length(278_000)
    assert " 0.5 mm at its narrowest, " in str(reading)


def test_a_wider_class_has_the_clearance_the_boards_rules_say(tmp_path):
    from pkidl.dsn import write_dsn

    board = carrier(tmp_path / "carrier", clearance=0.35 * mm)
    board.path(board["J1"], "IN", board["J2"], current=2 * A)
    router = Scripted(Run((STRAIGHT,), (), 0))
    built = board.build(tmp_path / "out", router=router)
    job = router.asked[0][1]
    assert list(job.netclasses) == [NetClass("Default", 0.35, 0.5),
                                    NetClass("0.926 mm", 0.35, 0.926)]  # fmt: skip
    dsn = write_dsn(tmp_path / "told.dsn", list(job.footprints), list(job.outline),
                    list(job.netclasses), {c: list(n) for c, n in job.members.items()})  # fmt: skip
    told = [line.strip() for line in dsn.read_text().splitlines()]
    assert [told[n + 2] for n, line in enumerate(told) if line.startswith("(class ")] == [
        "(rule (width 500) (clearance 350))",
        "(rule (width 926) (clearance 350))",
    ]
    assert built.project is not None
    assert _classes(built.project)[0] == [("Default", 0.5, 0.35), ("0.926 mm", 0.926, 0.35)]


def test_the_classes_are_in_the_order_of_their_widths_and_not_of_their_names(board, tmp_path):
    j1, j2, j3 = board.parts("J1", "J2", "J3")
    # 5 A needs 4.556 mm and 10 A 15.208 mm, which a list of names has first.
    board.path(j1, "IN", j2, current=10 * A)
    board.path(j3, "GND", board["J4"], current=5 * A)
    router = Scripted(Run((STRAIGHT,), (), 0))
    built = board.build(tmp_path / "out", router=router)
    names = ["Default", "4.556 mm", "15.208 mm"]
    assert sorted(names[1:]) == names[:0:-1]
    assert [c.name for c in router.asked[0][1].netclasses] == names
    assert built.project is not None
    assert [name for name, _, _ in _classes(built.project)[0]] == names
    rules = built.project.with_suffix(".kicad_dru").read_text()
    assert [line for line in rules.splitlines() if line.startswith("(rule")] == [
        '(rule "4.556 mm width"',
        '(rule "15.208 mm width"',
    ]


def test_a_rule_says_the_most_a_path_carries_on_a_net_of_its_class(tmp_path):
    board = carrier(tmp_path / "carrier", rise=20 * degC, copper=0.07 * mm)
    j1, j2, q1, j3 = board.parts("J1", "J2", "Q1", "J3")
    # Two currents that need one width to the micrometre, the larger said second, and
    # a third on the net of the first that is less than either.
    board.path(j1, "IN", j2, current=3.9995 * A)
    board.path(q1, j3, current=4 * A)
    board.path(j1, "IN", q1, current=1 * A)
    assert needed(3.9995 * A, 20 * degC, 0.07 * mm) == needed(4 * A, 20 * degC, 0.07 * mm)
    built = board.build(tmp_path / "out", router=Scripted(Run((STRAIGHT,), (), 0)))
    assert built.project is not None
    assert _classes(built.project) == (
        [("Default", 0.5, 0.2), ("0.926 mm", 0.926, 0.2)],
        [{"netclass": "0.926 mm", "pattern": "IN"}, {"netclass": "0.926 mm", "pattern": "OUT"}],
    )
    said = built.project.with_suffix(".kicad_dru").read_text().splitlines()
    assert said[2:4] == [
        "# a path's 4 A needs 0.926 mm to warm by no more than 20 °C in 0.07 mm copper",
        '(rule "0.926 mm width"',
    ]


def test_a_board_with_no_wider_net_leaves_what_is_at_the_path_of_its_rules_file_alone(tmp_path):
    out = tmp_path / "out"
    wide = carrier(tmp_path / "wide")
    wide.path(wide["J1"], "IN", wide["J2"], current=2 * A)
    wide.build(out, name="carrier", router=Scripted(Run((STRAIGHT,), (), 0)))
    left = (out / "carrier.kicad_dru").read_bytes()
    assert b'(rule "0.926 mm width"' in left
    # The same board with the path taken out of its board file, built where it was:
    # the file the earlier build wrote stays, with a class no net is in now.
    built = carrier(tmp_path / "plain").build(out, name="carrier",
                                              router=Scripted(Run((STRAIGHT,), (), 0)))  # fmt: skip
    assert (out / "carrier.kicad_dru").read_bytes() == left
    assert built.project is not None and _classes(built.project) == ([("Default", 0.5, 0.2)], [])


@pytest.mark.parametrize("routed", [True, False])
def test_a_board_with_no_wider_net_is_built_whatever_is_at_the_path_of_its_rules_file(
    tmp_path, routed
):
    out = tmp_path / "out"
    out.mkdir()
    # Somebody's own, and not text a build could read: a degree sign as Latin-1 has it.
    own = '(version 1)\n# keep 5 \xb0C in hand\n(rule "0.926 mm width"\n)\n'.encode("latin-1")
    (out / "carrier.kicad_dru").write_bytes(own)
    with pytest.raises(UnicodeDecodeError):
        (out / "carrier.kicad_dru").read_text(encoding="utf-8")
    board = carrier(tmp_path / "carrier", routed=routed)
    board.path(board["J1"], "IN", board["J2"], current=1 * A)  # 0.278 mm: no wider than a track
    built = board.build(out, name="carrier", router=Scripted(Run((STRAIGHT,), (), 0)))
    assert built.board.read_text().startswith("(kicad_pcb") and built.project is not None
    assert (out / "carrier.kicad_dru").read_bytes() == own
    assert sorted(f.name for f in out.iterdir()) == [
        "carrier.kicad_dru", "carrier.kicad_pcb", "carrier.kicad_pro"]  # fmt: skip


def test_a_board_with_a_wider_net_writes_its_rules_file_over_what_is_at_its_path(board, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "carrier.kicad_dru").write_bytes(
        '(version 1)\n# 5 \xb0C\n(rule "mine"\n)\n'.encode("latin-1")
    )
    board.path(board["J1"], "IN", board["J2"], current=2 * A)
    board.build(out, name="carrier", router=Scripted(Run((STRAIGHT,), (), 0)))
    wrote = (out / "carrier.kicad_dru").read_text()
    assert '(rule "0.926 mm width"' in wrote and "mine" not in wrote


def test_a_reading_that_could_not_be_measured_has_its_current_and_what_that_needs(
    board, tmp_path, monkeypatch
):
    from pkidl import paths

    board.path(board["J1"], "IN", board["J2"], current=2 * A)

    def broken(*_):
        raise RuntimeError("no such luck")

    monkeypatch.setattr(paths, "_between", broken)
    built = board.build(tmp_path / "out", router=Scripted(Run((STRAIGHT,), (), 0)))
    assert built.routed is not None
    ((reading,),) = (m.stretches for m in built.routed.paths)
    assert reading.failed == "RuntimeError: no such luck"
    assert (reading.current, reading.needs) == (2 * A, Length(926_000))


@pytest.mark.parametrize(
    ("current", "rise", "copper", "told"),
    [
        (0 * A, 10 * degC, 0.035 * mm, r"needed\(\): 0 mA is not a current to carry"),
        (-1.5 * A, 10 * degC, 0.035 * mm, r"needed\(\): -1.5 A is not a current to carry"),
        (1 * A, 0 * degC, 0.035 * mm, r"needed\(\): 0 °C is not a rise"),
        (1 * A, -10 * degC, 0.035 * mm, r"needed\(\): -10 °C is not a rise"),
        (1 * A, 10 * degC, 0 * mm, r"needed\(\): 0 mm is not a thickness"),
        (1 * A, 10 * degC, -0.035 * mm, r"needed\(\): -0.035 mm is not a thickness"),
    ],
)
def test_a_width_is_not_given_for_what_is_no_current_rise_or_thickness(current, rise, copper, told):
    with pytest.raises(ValueError, match=told):
        needed(current, rise, copper)


def test_a_net_named_with_what_kicad_reads_as_a_pattern_is_in_its_class_alone(tmp_path):
    from pkidl.dsn import write_dsn

    # A net V+, on a path, and a net V, on none, which the name V+ read as a pattern is.
    named = SOURCE.replace('(net "IN")', '(net "V+")').replace('(net "OUT")', '(net "V")')
    named = named.replace('(net "LOAD")', '(net "Net-(R1-Pad2)")')
    board = carrier(tmp_path / "carrier", source=named)
    board.path(board["J1"], "V+", board["J2"], current=2 * A)
    board.path(board.parts("R1", "R2"), board["J4"], current=2 * A)
    router = Scripted(Run((), (), 0))
    built = board.build(tmp_path / "out", router=router)
    # The router is told of each net by its name, and KiCad by a pattern only it matches.
    job = router.asked[0][1]
    assert dict(job.members) == {"0.926 mm": ["Net-(R1-Pad2)", "V+"]}
    dsn = write_dsn(tmp_path / "told.dsn", list(job.footprints), list(job.outline),
                    list(job.netclasses), {c: list(n) for c, n in job.members.items()})  # fmt: skip
    assert '    (class "0.926 mm" "Net-(R1-Pad2)" "V+"' in dsn.read_text().splitlines()
    assert built.project is not None
    assert _classes(built.project)[1] == [
        {"netclass": "0.926 mm", "pattern": "Net-\\(R1-Pad2\\)"},
        {"netclass": "0.926 mm", "pattern": "V\\+"},
    ]
