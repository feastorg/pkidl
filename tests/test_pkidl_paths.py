"""pkidl.paths: the way a current goes through a board, said and then measured.

A path is said in a board file and measured on the board a build routed. The router
here hands back what a test wrote, so each track is where the test put it.
"""

# The refusals below are of arguments of the wrong type, written on purpose.
# pyright: reportArgumentType=false, reportCallIssue=false

import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path as File

import pytest

import pkidl
from pkidl import A, Board, Edge, mA, mm
from pkidl.build import BuildError
from pkidl.dsn import Via, Wire
from pkidl.footprint import footprint_path, pad_xy
from pkidl.importer import circuit, footprints, mechanical
from pkidl.intent import Path, Rules, Stretch, path, rules
from pkidl.paths import Measured, Reading
from pkidl.routing import Job, Run
from pkidl.sexpr import dumps, find_all, parse
from pkidl.units import Length

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


@pytest.fixture
def board(tmp_path: File) -> Board:
    d = tmp_path / "carrier"
    source = parse(SOURCE)
    d.mkdir()
    (d / "circuit.json").write_text(json.dumps(circuit(source)))
    (d / "mechanical.json").write_text(json.dumps(mechanical(source)))
    for name, lib in footprints(source)[0].items():
        file = d / "footprints" / footprint_path(name)
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(dumps(lib) + "\n")
    board = Board.from_inputs(d)
    for ref, (x, y) in PLACES.items():
        board.place(board[ref], at=(x * mm, y * mm), facing=Edge.TOP)
    board.rules(track=0.5 * mm, clearance=0.2 * mm)
    board.route()
    return board


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


def test_a_net_a_path_names_is_one_of_the_circuit_by_either_name(board):
    j1, j2 = board.parts("J1", "J2")
    board.name_nets({"IN": "SUPPLY"})
    said = board.path(j1, "SUPPLY", j2, current=1 * A)
    assert str(said) == "path(J1, SUPPLY, J2, current=1 A)"
    assert said.data()["path"] == ["J1", {"net": "IN"}, "J2"]
    with pytest.raises(LookupError, match="no net 'NOWHERE'"):
        board.path(j1, "NOWHERE", j2, current=1 * A)
    with pytest.raises(LookupError, match=r"path\(J1, NOWHERE, J2, current=1 A\): no net"):
        board.add(path(j1, "NOWHERE", j2, current=1 * A))


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
    with pytest.raises(ValueError, match="J1 is at both ends of a stretch"):
        board.path(j1, "IN", j1, current=1 * A)
    with pytest.raises(ValueError, match="J1 is at both ends of a stretch"):
        board.path([j1, q1], j1, current=1 * A)
    with pytest.raises(TypeError, match="takes parts, nets and lists of parts side by side"):
        board.path(j1, 3, j2, current=1 * A)
    with pytest.raises(TypeError, match="takes parts, nets and lists of parts side by side"):
        board.path(j1, [j2, "IN"], current=1 * A)
    with pytest.raises(TypeError, match="takes parts, nets and lists of parts side by side"):
        board.path(j1, [], j2, current=1 * A)
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
        f"path(J1, LOAD, [R1, R2, J3], current=1 A): J1 has no pad on LOAD ({HERE}:{third})",
        f"path(J1, OUT, J3, current=1 A): J1 has no pad on OUT ({HERE}:{first})",
        f"path(J1, LOAD, [R1, R2, J3], current=1 A): J3 has no pad on LOAD ({HERE}:{third})",
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
    assert reading.ohms is None and str(reading) == "IN, J1 to J2: not joined"


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
    assert str(outside) == "IN, J1 to J2: not joined"


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
        "  OUT, J3 to [R1, R2]: 19 mm of track, 0.5 mm at its narrowest, 18.7 mΩ, 37.3 mV",
        "  LOAD, [R1, R2] to J4: 31 mm of track, 0.5 mm at its narrowest, 15.2 mΩ, 30.5 mV",
    ]


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
        "  IN, J1 to Q1: not joined\n"
        "  OUT, Q1 to J3: 51 mm of track, 0.5 mm at its narrowest, 50.1 mΩ, 50.1 mV"
    )
    # With no track at all there is no figure.
    (measured,) = measure(board, tmp_path / "bare")
    assert (measured.ohms, measured.volts, measured.unmeasured) == (None, None, 2)
    assert str(measured).splitlines()[0] == (
        f"path(J1, Q1, J3, current=1 A) ({HERE}:{line}): not measured: no stretch of it is "
        "joined by track"
    )


def test_ends_that_only_a_pour_joins_are_said_to_be_and_are_not_measured(board, tmp_path):
    j1, j2 = board.parts("J1", "J2")
    board.pour("GND", layer="B.Cu")
    board.path(j1, "GND", j2, current=1 * A)
    reading = one(board, tmp_path / "out")
    assert reading.ohms is None and reading.poured
    assert str(reading) == "GND, J1 to J2: joined through the pour of GND, not measured"


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
        "98.3 mV: the pour of GND is beside it, not measured"
    )


def test_paths_are_measured_in_the_order_they_were_written_each_once(board, tmp_path):
    j1, j2, q1, j3 = board.parts("J1", "J2", "Q1", "J3")
    first = board.path(j1, "IN", j2, current=1 * A)
    second = board.path(q1, j3, current=1 * A)
    board.add(first)
    assert [m.path for m in measure(board, tmp_path / "out", STRAIGHT)] == [first, second]
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
