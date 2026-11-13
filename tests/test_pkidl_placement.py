"""pkidl.placement: where each part goes, worked out from what a board file said.

Where a pad ends up is read back through ``pkidl.footprint.place``, which is what puts a
footprint on a board, and not from the solver's own arithmetic.
"""

import math
import random
import re
import sys

import pytest

from pkidl import Board, Edge, Side, align, decouple, keepout, mm, place, row
from pkidl.circuit import Circuit
from pkidl.footprint import Placement, pad_xy, pads
from pkidl.footprint import place as put
from pkidl.placement import Pose, Problem, Solution, _shape, _Solver
from pkidl.sexpr import Node, dumps, parse
from pkidl.units import Length

HERE = "test_pkidl_placement.py"


def _footprint(name: str, body: str, *pad: str) -> Node:
    return parse(f'(footprint "{name}" (layer "F.Cu")\n'
                 f'  (property "Reference" "REF**" (at 0 0) (layer "F.SilkS"))\n'
                 f'  (property "Value" "{name}" (at 0 0) (layer "F.Fab"))\n'
                 f"  {body}\n  " + "\n  ".join(pad) + ")")  # fmt: skip


def _line(x0: float, y0: float, x1: float, y1: float) -> str:
    return (f"(fp_line (start {x0} {y0}) (end {x1} {y1}) (stroke (width 0.05) (type solid)) "
            '(layer "F.CrtYd"))')  # fmt: skip


def _smd(number: int, x: float, y: float, w: float, h: float, angle: str = "") -> str:
    return (f'(pad "{number}" smd rect (at {x} {y}{angle}) (size {w} {h}) '
            '(layers "F.Cu" "F.Mask" "F.Paste"))')  # fmt: skip


LIBRARY = {
    # A header: four pins in holes, 2.54 mm apart along +x from pin 1 at the origin, in a
    # courtyard 11.12 by 3.5 mm drawn as four lines.
    "Conn:H": _footprint(
        "H",
        " ".join(_line(*ends) for ends in [(-1.75, -1.75, 9.37, -1.75), (9.37, -1.75, 9.37, 1.75),
                                           (9.37, 1.75, -1.75, 1.75), (-1.75, 1.75, -1.75, -1.75)]),
        *(f'(pad "{n + 1}" thru_hole circle (at {2.54 * n} 0) (size 1.7 1.7) (drill 1) '
          '(layers "*.Cu" "*.Mask"))' for n in range(4)),
    ),
    # The same header drawn on end: its pins along +y.
    "Conn:V": _footprint(
        "V",
        " ".join(_line(*ends) for ends in [(-1.75, -1.75, 1.75, -1.75), (1.75, -1.75, 1.75, 9.37),
                                           (1.75, 9.37, -1.75, 9.37), (-1.75, 9.37, -1.75, -1.75)]),
        *(f'(pad "{n + 1}" thru_hole circle (at 0 {2.54 * n}) (size 1.7 1.7) (drill 1) '
          '(layers "*.Cu" "*.Mask"))' for n in range(4)),
    ),
    # A resistor: pads 1 mm either side of the origin, in a courtyard 3.6 by 1.8 mm drawn
    # as a polygon.
    "Device:R": _footprint(
        "R",
        "(fp_poly (pts (xy -1.8 -0.9) (xy 1.8 -0.9) (xy 1.8 0.9) (xy -1.8 0.9)) "
        '(stroke (width 0.05) (type solid)) (fill no) (layer "F.CrtYd"))',
        _smd(1, -1, 0, 1, 1.2),
        _smd(2, 1, 0, 1, 1.2),
    ),
    # A module: pads 1 and 2 down its left side, 3 and 4 up its right, pad 5 below them
    # turned on end and reaching 4 mm under the origin; its body is drawn on the
    # fabrication layer, 4 mm of it above the pads. 10 by 8 mm, its middle at (4, 0).
    "RF:M": _footprint(
        "M",
        "(fp_rect (start -1 -4) (end 9 3) (stroke (width 0.1) (type solid)) (fill no) "
        '(layer "F.Fab"))',
        _smd(1, 0, 0, 2, 1),
        _smd(2, 0, 2, 2, 1),
        _smd(3, 8, 2, 2, 1),
        _smd(4, 8, 0, 2, 1),
        _smd(5, 4, 3, 2, 1, " 90"),
    ),
    # A mark: no pads, a courtyard circle of radius 1.5 mm.
    "Mech:Dot": _footprint(
        "Dot",
        "(fp_circle (center 0 0) (end 1.5 0) (stroke (width 0.05) (type solid)) (fill no) "
        '(layer "F.CrtYd"))',
    ),
    # A test point: one pad 1 mm square, and nothing drawn around it.
    "Test:TP": _footprint("TP", "", _smd(1, 0, 0, 1, 1)),
    # A square part: pads 1 mm either side of the origin in a courtyard 3 mm square.
    "Device:Q": _footprint(
        "Q",
        "(fp_rect (start -1.5 -1.5) (end 1.5 1.5) (stroke (width 0.05) (type solid)) (fill no) "
        '(layer "F.CrtYd"))',
        _smd(1, -1, 0, 1, 1),
        _smd(2, 1, 0, 1, 1),
    ),
    # A sensor, 8 by 6 mm: pad 1 is 1 mm in from one long side and pad 2 1 mm in from
    # the other, both on its centre line.
    "Sensor:K": _footprint(
        "K",
        "(fp_rect (start -4 -5) (end 4 1) (stroke (width 0.05) (type solid)) (fill no) "
        '(layer "F.CrtYd"))',
        _smd(1, 0, 0, 1, 1),
        _smd(2, 0, -4, 1, 1),
    ),
    # A diode with one pad, 2 by 1 mm, turned 45 degrees.
    "Device:D": _footprint("D", "", _smd(1, 0, 0, 2, 1, " 45")),
    # A chip whose footprint lists its pads out of order: 10, then 2, then 3, in a row
    # 4 mm apart, in a courtyard 12 by 4 mm.
    "Chip:Z": _footprint(
        "Z",
        "(fp_rect (start -2 -2) (end 10 2) (stroke (width 0.05) (type solid)) (fill no) "
        '(layer "F.CrtYd"))',
        _smd(10, 0, 0, 1, 1),
        _smd(2, 4, 0, 1, 1),
        _smd(3, 8, 0, 1, 1),
    ),
    # A mounting hole: 2 mm across, unplated, with no number.
    "Mech:Hole": _footprint(
        "Hole",
        "",
        '(pad "" np_thru_hole circle (at 0 0) (size 2 2) (drill 2) (layers "*.Cu" "*.Mask"))',
    ),
    # A footprint with nothing drawn and no pads.
    "Mech:Nothing": _footprint("Nothing", ""),
}  # fmt: skip
_KINDS = {"P": "Conn:H", "R": "Device:R", "U": "RF:M", "F": "Mech:Dot", "T": "Test:TP",
          "Q": "Device:Q", "K": "Sensor:K", "D": "Device:D", "H": "Mech:Hole",
          "N": "Mech:Nothing", "V": "Conn:V", "Z": "Chip:Z"}  # fmt: skip


def _board(**parts: str) -> Board:
    """A board 30 mm square, from (100, 50) to (130, 80), and its parts: each a reference
    and the nets of its pads in order, its footprint by its first letter."""
    listed = [{"ref": ref, "value": ref, "footprint": _KINDS[ref[0]],
               "pads": {str(n): net for n, net in enumerate(nets.split(), 1)}}
              for ref, nets in parts.items()]  # fmt: skip
    nets = sorted({net for part in listed for net in part["pads"].values()})
    return Board(circuit=Circuit({"parts": listed, "nets": nets}), library=dict(LIBRARY),
                 extent=(100.0, 50.0, 130.0, 80.0))  # fmt: skip


def _pads(board: Board, solution: Solution, ref: str) -> dict[str, tuple[float, float]]:
    """Where *ref*'s pads are once its footprint is put on the board as *solution* says."""
    part, pose = board[ref], solution.poses[ref]
    placed = put(board.library[part.footprint],
                 Placement(part.footprint, ref, part.value, pose.x.mm, pose.y.mm, pose.rot,
                           pose.back))  # fmt: skip
    return {str(pad[1]): pad_xy(placed, str(pad[1])) for pad in pads(placed)}


def _line_no() -> int:
    """The line this is called on; the statement above it is on ``_line_no() - 1``."""
    return sys._getframe(1).f_lineno


def _told(solution: Solution) -> list[str]:
    return [str(problem) for problem in solution.problems]


@pytest.mark.parametrize(
    ("edge", "nearest", "along"),
    [
        (Edge.LEFT, lambda x, y: x - 100, lambda x, y: y - 50),
        (Edge.RIGHT, lambda x, y: 130 - x, lambda x, y: y - 50),
        (Edge.TOP, lambda x, y: y - 50, lambda x, y: x - 100),
        (Edge.BOTTOM, lambda x, y: 80 - y, lambda x, y: x - 100),
    ],
)
def test_against_an_edge_a_part_lies_along_it_its_pads_inset_and_centred(edge, nearest, along):
    board = _board(P1="A B C D")
    board.place(board["P1"], against=edge, inset=2 * mm)
    solution = board.solve()
    assert solution.ok and solution.free == () and solution.problems == ()
    at = _pads(board, solution, "P1").values()
    # Every pin is 2 mm from the edge: the header lies along it.
    assert [nearest(x, y) for x, y in at] == pytest.approx([2.0] * 4)
    # The pins are 2.54 mm apart along it, about the middle of the 30 mm edge.
    assert sorted(along(x, y) for x, y in at) == pytest.approx([11.19, 13.73, 16.27, 18.81])
    assert f"P1: centred along the {edge.value} edge" in solution.chosen


def test_inset_is_to_the_centres_of_the_pads_nearest_the_edge():
    # The module's top row of pads is 2 mm from the top edge; turned over, pad 5 is.
    board = _board(U1="A B C D GND")
    board.place(board["U1"], against=Edge.TOP, inset=2 * mm)
    at = _pads(board, board.solve(), "U1")
    assert [at[n][1] for n in "12345"] == [52.0, 54.0, 54.0, 52.0, 55.0]
    board = _board(U1="A B C D GND")
    board.place(board["U1"], against=Edge.TOP, inset=2 * mm, facing=Edge.BOTTOM)
    at = _pads(board, board.solve(), "U1")
    assert [at[n][1] for n in "12345"] == [55.0, 53.0, 53.0, 55.0, 52.0]


def test_with_no_inset_the_outline_touches_the_edge():
    board = _board(P1="A B C D", U1="E F G H GND", R1="J K", FID1="")
    board.place(board["P1"], against=Edge.RIGHT)
    board.place(board["U1"], against=Edge.BOTTOM, facing=Edge.TOP)
    board.place(board["R1"], against=Edge.TOP)
    board.place(board["FID1"], against=Edge.LEFT)
    solution = board.solve()
    assert solution.ok
    # The header's courtyard is 1.75 mm out from its pins.
    assert {x for x, _ in _pads(board, solution, "P1").values()} == {128.25}
    # The module's outline is as far down as pad 5 reaches, turned on end: 1 mm past its
    # centre, which the body drawn on the fabrication layer stops level with.
    assert _pads(board, solution, "U1")["5"] == (115.0, 79.0)
    # The resistor's courtyard, a polygon, is 0.9 mm out from its pads.
    assert _pads(board, solution, "R1") == {"1": (114.0, 50.9), "2": (116.0, 50.9)}
    # A part with no pads is its outline: a circle of radius 1.5 mm.
    assert solution.poses["FID1"] == Pose(Length(101_500_000), Length(65_000_000))


def test_a_part_with_no_pads_is_inset_to_its_outline():
    board = _board(FID1="")
    board.place(board["FID1"], against=Edge.LEFT, inset=2 * mm)
    board.place(board["FID1"], against=Edge.BOTTOM, inset=1 * mm)
    assert board.solve().poses == {"FID1": Pose(Length(103_500_000), Length(77_500_000))}


def test_two_edges_make_a_corner():
    board = _board(R1="A B")
    board.place(board["R1"], against=Edge.LEFT, inset=2 * mm)
    board.place(board["R1"], against=Edge.TOP, inset=3 * mm)
    solution = board.solve()
    assert solution.ok
    assert _pads(board, solution, "R1") == {"1": (102.0, 53.0), "2": (104.0, 53.0)}
    # Nothing is centred, and which edge it lies along is chosen and said.
    assert solution.chosen == (
        "R1: turned 0 degrees, of 0, 90, 180, 270, for the shortest connections",
    )


@pytest.mark.parametrize("side", [Side.FRONT, Side.BACK])
@pytest.mark.parametrize(
    ("edge", "up"),
    [
        (Edge.TOP, lambda x, y: -y),
        (Edge.LEFT, lambda x, y: -x),
        (Edge.BOTTOM, lambda x, y: y),
        (Edge.RIGHT, lambda x, y: x),
    ],
)
def test_facing_turns_the_side_that_is_up_in_the_library_to_that_edge(edge, up, side):
    board = _board(U1="A B C D GND")
    board.place(board["U1"], against=Edge.TOP, facing=edge, side=side)
    solution = board.solve()
    assert solution.ok and solution.poses["U1"].back is (side is Side.BACK)
    at = _pads(board, solution, "U1")
    # Pads 1 and 4 are the row nearer the top of the footprint, 2 and 3 the row under it
    # and 5 lower still; towards the edge faced they come in that order, 2 and 1 mm apart.
    heights = [up(*at[n]) for n in "14235"]
    assert heights == pytest.approx([heights[0]] * 2 + [heights[0] - 2] * 2 + [heights[0] - 3])
    # Seen from the front, pad 1 is to the left of pad 4 with the part the right way up
    # on the front, and to the right of it on the back.
    across = {Edge.TOP: lambda x, y: x, Edge.LEFT: lambda x, y: -y,
              Edge.BOTTOM: lambda x, y: -x, Edge.RIGHT: lambda x, y: y}[edge]  # fmt: skip
    assert across(*at["4"]) - across(*at["1"]) == pytest.approx(-8 if side is Side.BACK else 8)
    assert not any("turned" in note for note in solution.chosen)


def test_between_two_parts_is_midway_between_their_middles_both_ways():
    board = _board(R1="A B", R2="C D", U1="E F G H GND")
    r1, r2, u1 = board.parts("R1", "R2", "U1")
    board.place(r1, against=Edge.LEFT, inset=2 * mm)
    board.place(r1, against=Edge.TOP, inset=3 * mm)
    board.place(r2, against=Edge.RIGHT, inset=4 * mm)
    board.place(r2, against=Edge.BOTTOM, inset=7 * mm)
    board.place(u1, between=(r2, r1), facing=Edge.TOP)
    solution = board.solve()
    assert solution.ok
    # The resistors' middles are at (103, 53) and (125, 73); the module's, 4 mm right of
    # its pad 1, is at (114, 63).
    assert _pads(board, solution, "R2") == {"1": (124.0, 73.0), "2": (126.0, 73.0)}
    assert _pads(board, solution, "U1")["1"] == (110.0, 63.0)


def _module_at_the_top(**parts: str) -> Board:
    """The module against the top edge, the right way up: its pads 1 to 4 at (111, 54),
    (111, 56), (119, 56) and (119, 54), its outline from (110, 50) to (120, 58)."""
    board = _board(U1="A B D C GND", **parts)
    board.place(board["U1"], against=Edge.TOP, facing=Edge.TOP)
    return board


def test_near_a_pin_is_the_nearest_place_clear_of_the_other_parts():
    board = _module_at_the_top(R1="VCC A")
    board.place(board["R1"], near=board["U1"].pin(1), within=3 * mm)
    solution = board.solve()
    assert solution.ok
    assert _pads(board, solution, "U1")["1"] == (111.0, 54.0)
    # Beside the module, its courtyard touching the module's outline at x = 110: its pad
    # on the pin's net 0.8 mm inside its courtyard, 1.8 mm from the pin.
    assert _pads(board, solution, "R1") == {"1": (107.2, 54.0), "2": (109.2, 54.0)}
    assert "R1: 1.8 mm from U1.1, turned 0 degrees" in solution.chosen


def test_which_way_round_is_the_way_that_makes_the_connections_shortest():
    board = _module_at_the_top(R1="A VCC")
    board.place(board["R1"], near=board["U1"].pin(1), within=3 * mm)
    solution = board.solve()
    # The same place, turned round: pad 1 is now the one on the pin's net.
    assert _pads(board, solution, "R1") == {"1": (109.2, 54.0), "2": (107.2, 54.0)}
    assert "R1: 1.8 mm from U1.1, turned 180 degrees" in solution.chosen


def test_on_the_back_a_part_may_sit_under_one_on_the_front():
    board = _module_at_the_top(R1="VCC A")
    board.place(board["R1"], near=board["U1"].pin(1), within=3 * mm, side="back")
    solution = board.solve()
    assert solution.ok and solution.poses["R1"].back and not solution.poses["U1"].back
    assert _pads(board, solution, "R1") == {"1": (109.0, 54.0), "2": (111.0, 54.0)}
    assert "R1: 0 mm from U1.1, turned 0 degrees" in solution.chosen


def test_a_part_with_no_place_near_enough_is_reported_and_not_placed():
    board = _module_at_the_top(R1="VCC A")
    board.place(board["R1"], near=board["U1"].pin(1), within=1.7 * mm)
    line = _line_no() - 1
    solution = board.solve()
    assert not solution.ok and solution.free == () and set(solution.poses) == {"U1"}
    assert _told(solution) == [
        "R1 has no place within 1.7 mm of U1.1 that is on the front of the board and clear "
        f"of the other parts ({HERE}:{line})"
    ]
    assert solution.problems[0].parts == ("R1",)
    assert solution.problems[0].statements == board.statements(about="R1")


def test_near_a_part_is_near_any_of_its_pads():
    board = _module_at_the_top(R1="VCC C")
    board.place(board["R1"], near=board["U1"], within=3 * mm)
    solution = board.solve()
    # 1.8 mm from pad 1 on the left or pad 4 on the right; pad 4 is on its net.
    assert _pads(board, solution, "R1") == {"1": (122.8, 54.0), "2": (120.8, 54.0)}
    assert "R1: 1.8 mm from U1, turned 180 degrees" in solution.chosen


def test_a_part_placed_near_keeps_clear_of_the_ones_placed_before_it():
    board = _module_at_the_top(R1="VCC A", R2="VCC A")
    for r in board.parts("R1", "R2"):
        board.place(r, near=board["U1"].pin(1), within=3 * mm)
    solution = board.solve()
    assert solution.ok
    # R1 has the nearest place; R2 the next, its courtyard touching R1's from above.
    assert _pads(board, solution, "R1") == {"1": (107.2, 54.0), "2": (109.2, 54.0)}
    assert _pads(board, solution, "R2") == {"1": (107.2, 52.2), "2": (109.2, 52.2)}


def test_a_part_with_holes_takes_both_faces():
    def tried(within: Length, side: str) -> tuple[Board, Solution]:
        board = _board(P1="A B C D", R1="VCC A")
        board.place(board["P1"], against=Edge.TOP, inset=5 * mm)
        board.place(board["R1"], near=board["P1"].pin(1), within=within, side=side)
        return board, board.solve()

    # The header's courtyard is 1.75 mm out from pin 1, and the resistor's pad 0.8 mm
    # inside its own: on either face the nearest it gets is 2.6 mm, in 0.1 mm steps.
    for side in ("front", "back"):
        board, solution = tried(2.5 * mm, side)
        assert _told(solution) == [
            f"R1 has no place within 2.5 mm of P1.1 that is on the {side} of the board and "
            f"clear of the other parts ({HERE}:{_line_no() - 9})"
        ]
        board, solution = tried(2.6 * mm, side)
        assert solution.ok and solution.poses["R1"].back is (side == "back")
        assert "R1: 2.6 mm from P1.1, turned 0 degrees" in solution.chosen


def test_a_part_is_turned_to_meet_what_it_connects_to_once_that_is_placed():
    def header(nets: str) -> tuple[dict[str, tuple[float, float]], Solution]:
        board = _board(P1=nets, U1="A B D C GND")
        board.place(board["P1"], against=Edge.LEFT, inset=2 * mm)
        board.place(board["U1"], against=Edge.RIGHT, facing=Edge.TOP)
        solution = board.solve()
        assert solution.ok
        return _pads(board, solution, "P1"), solution

    # The module's A is above its B, both level with the header. P1 is placed before U1,
    # with nothing to be near; it is turned on the second pass, when the module is there.
    at, solution = header("A X Y B")
    assert at["1"][1] < at["4"][1]
    assert "P1: turned 270 degrees, of 90, 270, for the shortest connections" in solution.chosen
    at, solution = header("B X Y A")
    assert at["1"][1] > at["4"][1]
    assert "P1: turned 90 degrees, of 90, 270, for the shortest connections" in solution.chosen


def test_align_holds_when_first_pins_are_whole_grid_steps_apart():
    board = _board(P1="A B C D", P2="E F G H")
    p1, p2 = board.parts("P1", "P2")
    board.place(p1, against=Edge.LEFT, inset=2 * mm)
    board.place(p2, against=Edge.RIGHT, inset=2 * mm)
    board.align(p1, p2, grid=2 * mm)
    solution = board.solve()
    assert solution.ok
    assert _pads(board, solution, "P1")["1"] == (102.0, 68.81)
    assert _pads(board, solution, "P2")["1"] == (128.0, 68.81)


def test_align_that_does_not_hold_is_reported_with_how_far_off_and_moves_nothing():
    board = _board(P1="A B C D", P2="E F G H")
    p1, p2 = board.parts("P1", "P2")
    board.place(p1, against=Edge.LEFT, inset=2 * mm)
    board.place(p2, against=Edge.RIGHT, inset=2 * mm)
    placed = board.solve().poses
    board.align(p1, p2, grid=2.54 * mm)
    line = _line_no() - 1
    solution = board.solve()
    assert not solution.ok and solution.poses == placed
    assert _told(solution) == [
        "align(P1, P2, grid=2.54 mm) does not hold: P1 and P2 are 26 mm apart across the "
        f"board, 10.2 steps ({HERE}:{line}, {HERE}:{line - 3}, {HERE}:{line - 2})"
    ]
    assert solution.problems[0].parts == ("P1", "P2")


def test_align_is_checked_along_the_board_too():
    # P2's pins are P1's in the other order, so it is turned the other way to meet them:
    # their first pins are 26 mm apart across and 7.62 mm apart along.
    board = _board(P1="A B C D", P2="D C B A")
    p1, p2 = board.parts("P1", "P2")
    board.place(p1, against=Edge.LEFT, inset=2 * mm)
    board.place(p2, against=Edge.RIGHT, inset=2 * mm)
    board.align(p1, p2, grid=2 * mm)
    assert [p.text for p in board.solve().problems] == [
        "align(P1, P2, grid=2 mm) does not hold: P1 and P2 are 7.62 mm apart along the "
        "board, 3.81 steps"
    ]
    board.align(p1, p2, grid=1.27 * mm)  # a second grid they do not meet across
    board.align(p1, p2, grid=0.02 * mm)  # and one they meet both ways
    assert [p.text for p in board.solve().problems] == [
        "align(P1, P2, grid=1.27 mm) does not hold: P1 and P2 are 26 mm apart across the "
        "board, 20.5 steps",
        "align(P1, P2, grid=2 mm) does not hold: P1 and P2 are 7.62 mm apart along the "
        "board, 3.81 steps",
    ]


def test_a_part_put_in_two_places_is_reported_with_both_lines_and_not_placed():
    board = _board(P1="A B C D", P2="E F G H", U1="J K L M GND")
    p1, p2, u1 = board.parts("P1", "P2", "U1")
    board.place(p1, against=Edge.LEFT, inset=2 * mm)
    board.place(p2, against=Edge.RIGHT, inset=2 * mm)
    board.place(u1, between=(p1, p2), facing=Edge.TOP)
    board.place(u1, against=Edge.LEFT)
    board.place(u1, against=Edge.TOP)
    line = _line_no() - 2
    solution = board.solve()
    # In the top left corner its pad 1 is at x = 101; between the headers, at 111.
    assert _told(solution) == [
        f"U1 is put in two places 10 mm apart across the board ({HERE}:{line}, {HERE}:{line - 1})"
    ]
    assert set(solution.poses) == {"P1", "P2"} and solution.free == ()
    assert solution.problems[0].statements == (board.statements()[3], board.statements()[2])


@pytest.mark.parametrize(
    ("edge", "pad"),
    # The marks' middles are at (102.5, 53.5) and (128.5, 75.5), and midway is (115.5,
    # 64.5), off the middle of the board both ways. The module's pad 1 is 1 mm in from
    # its left side, 4 mm down from its top and 4 mm left of its middle.
    [(Edge.TOP, (111.5, 54.0)), (Edge.BOTTOM, (111.5, 76.0)),
     (Edge.LEFT, (101.0, 64.5)), (Edge.RIGHT, (121.0, 64.5))],
)  # fmt: skip
def test_with_an_edge_the_edge_says_how_far_and_between_where_along_it(edge, pad):
    board = _board(FID1="", FID2="", U1="J K L M GND")
    fid1, fid2, u1 = board.parts("FID1", "FID2", "U1")
    board.place(fid1, against=Edge.LEFT, inset=1 * mm)
    board.place(fid1, against=Edge.TOP, inset=2 * mm)
    board.place(fid2, against=Edge.RIGHT)
    board.place(fid2, against=Edge.BOTTOM, inset=3 * mm)
    board.place(u1, between=(fid1, fid2), against=edge, facing=Edge.TOP)
    solution = board.solve()
    assert solution.ok, _told(solution)
    assert _pads(board, solution, "U1")["1"] == pad
    assert not any(note.startswith("U1: centred") for note in solution.chosen)


def test_opposite_edges_put_a_part_in_two_places():
    board = _board(R1="A B")
    board.place(board["R1"], against=Edge.TOP, inset=2 * mm)
    board.place(board["R1"], against=Edge.BOTTOM, inset=2 * mm)
    assert [p.text for p in board.solve().problems] == [
        "R1 is put in two places 26 mm apart along the board"
    ]


@pytest.mark.parametrize(("facing", "side"), [(Edge.TOP, None), (None, Side.BACK)])
def test_a_part_nothing_says_where_to_put_is_reported_and_not_placed(facing, side):
    board = _board(U1="A B C D GND")
    board.place(board["U1"], facing=facing, side=side)
    line = _line_no() - 1
    solution = board.solve()
    assert _told(solution) == [
        f"U1 is not placed across the board: nothing says where ({HERE}:{line})"
    ]
    assert solution.poses == {} and solution.free == () and not solution.ok


def test_a_part_that_does_not_fit_is_placed_where_it_was_said_and_reported():
    board = _board(P1="A B C D")
    board.place(board["P1"], against=Edge.LEFT, inset=0.5 * mm)
    board.place(board["P1"], against=Edge.BOTTOM, inset=1 * mm)
    line = _line_no() - 1
    solution = board.solve()
    assert not solution.ok
    # Turned to lie along the left edge or the bottom, its courtyard is 1.75 mm out from
    # its pins either way.
    assert _pads(board, solution, "P1")["1"] == (100.5, 79.0)
    assert _told(solution) == [
        "P1 does not fit on the board: it reaches 0.75 mm past the bottom edge "
        f"({HERE}:{line - 1}, {HERE}:{line})",
        "P1 does not fit on the board: it reaches 1.25 mm past the left edge "
        f"({HERE}:{line - 1}, {HERE}:{line})",
    ]


@pytest.mark.parametrize(
    ("edge", "names"),
    [(Edge.RIGHT, "right"), (Edge.TOP, "top")],
)
def test_past_which_edge_a_part_reaches_is_named(edge, names):
    board = _board(R1="A B")
    board.place(board["R1"], against=edge, inset=0.5 * mm)
    assert [p.text for p in board.solve().problems] == [
        f"R1 does not fit on the board: it reaches 0.4 mm past the {names} edge"
    ]


def test_parts_on_one_face_may_touch_and_not_overlap():
    def tried(inset: Length, side: str | None = None) -> Solution:
        board = _board(R1="A B", R2="C D")
        board.place(board["R1"], against=Edge.LEFT)
        board.place(board["R2"], against=Edge.LEFT, inset=inset, side=side)
        return board.solve()

    said = _line_no() - 4

    # R1's courtyard is from the edge to 1.8 mm in; R2's is 0.9 mm out from its pads.
    assert tried(2.7 * mm).ok
    solution = tried(2.699999 * mm)
    assert _told(solution) == [f"R1 and R2 overlap ({HERE}:{said}, {HERE}:{said + 1})"]
    assert solution.problems[0].parts == ("R1", "R2") and set(solution.poses) == {"R1", "R2"}
    # On the other face it is clear of it.
    assert tried(1 * mm, side="back").ok
    assert not tried(1 * mm, side="front").ok


def test_a_part_with_holes_overlaps_a_part_on_either_face():
    for side in ("front", "back"):
        board = _board(P1="A B C D", R1="E F")
        board.place(board["P1"], against=Edge.LEFT)
        board.place(board["R1"], against=Edge.LEFT, side=side)
        assert [p.text for p in board.solve().problems] == ["P1 and R1 overlap"]


def test_parts_nothing_places_are_left_free_and_named():
    board = _board(P1="A B C D", R2="E F", R10="G H")
    board.place(board["P1"], against=Edge.LEFT)
    solution = board.solve()
    assert solution.free == ("R2", "R10") and solution.problems == ()
    assert set(solution.poses) == {"P1"} and not solution.ok
    assert _board().solve() == Solution({}, (), (), ())


def test_a_part_placed_by_one_that_nothing_places_is_reported():
    board = _board(U1="A B C D GND", R1="VCC A", P1="E F G H", P2="J K L M")
    u1, r1, p1, p2 = board.parts("U1", "R1", "P1", "P2")
    board.place(r1, near=u1.pin(1), within=3 * mm)
    board.place(p1, between=(u1, p2))
    board.place(p2, against=Edge.RIGHT)
    solution = board.solve()
    assert _told(solution) == [
        f"P1 is placed by U1, which nothing places ({HERE}:{_line_no() - 4})",
        f"R1 is placed by U1, which nothing places ({HERE}:{_line_no() - 6})",
    ]
    assert solution.free == ("U1",) and set(solution.poses) == {"P2"}


def test_parts_placed_by_each_other_are_reported():
    board = _board(R1="A B", R2="A C", R3="B C")
    r1, r2, r3 = board.parts("R1", "R2", "R3")
    board.place(r1, near=r2, within=3 * mm)
    board.place(r2, near=r3, within=3 * mm)
    board.place(r3, near=r1, within=3 * mm)
    solution = board.solve()
    assert [p.text for p in solution.problems] == [
        "R1 is placed by R2, which is placed by it in turn",
        "R2 is placed by R3, which is placed by it in turn",
        "R3 is placed by R1, which is placed by it in turn",
    ]
    assert solution.poses == {} and solution.free == ()


def test_a_part_placed_by_one_that_could_not_be_placed_is_reported():
    board = _board(U1="A B C D GND", R1="VCC A", P1="E F G H", P2="J K L M")
    u1, r1, p1, p2 = board.parts("U1", "R1", "P1", "P2")
    board.place(u1, facing=Edge.TOP)
    board.place(r1, near=u1.pin(1), within=3 * mm)
    board.place(p1, between=(u1, p2))
    board.place(p2, against=Edge.RIGHT)
    solution = board.solve()
    assert _told(solution) == [
        f"P1 is placed by U1, which is not placed ({HERE}:{_line_no() - 4})",
        f"R1 is placed by U1, which is not placed ({HERE}:{_line_no() - 6})",
        f"U1 is not placed across the board: nothing says where ({HERE}:{_line_no() - 8})",
    ]
    assert set(solution.poses) == {"P2"} and solution.free == ()


@pytest.mark.parametrize("beside", ["against", "between"])
def test_near_is_solved_alone(beside):
    board = _board(U1="A B C D GND", R1="VCC A", P1="E F G H", P2="J K L M")
    u1, r1, p1, p2 = board.parts("U1", "R1", "P1", "P2")
    board.place(p1, against=Edge.LEFT)
    board.place(p2, against=Edge.RIGHT)
    board.place(u1, against=Edge.TOP, facing=Edge.TOP)
    board.place(r1, near=u1.pin(1), within=3 * mm)
    line = _line_no() - 1
    if beside == "against":
        board.place(r1, against=Edge.BOTTOM)
    else:
        board.place(r1, between=(p1, p2))
    solution = board.solve()
    assert _told(solution) == [
        "R1: near= is solved alone: one near=, and no against= or between= beside it "
        f"({HERE}:{line}, {HERE}:{line + (3 if beside == 'against' else 5)})"
    ]
    assert "R1" not in solution.poses

    board = _module_at_the_top(R1="VCC A")
    board.place(board["R1"], near=board["U1"].pin(1), within=3 * mm)
    board.place(board["R1"], near=board["U1"].pin(2), within=3 * mm)
    assert [p.text for p in board.solve().problems] == [
        "R1: near= is solved alone: one near=, and no against= or between= beside it"
    ]


def test_statements_that_conflict_are_the_problems_and_nothing_is_placed():
    board = _board(P1="A B C D", R1="E F")
    board.place(board["P1"], against=Edge.LEFT, inset=1 * mm)
    board.place(board["P1"], against=Edge.LEFT, inset=2 * mm)
    line = _line_no() - 1
    board.place(board["R1"], against=Edge.TOP)
    solution = board.solve()
    assert solution == Solution({}, (), (Problem(("P1",), str(board.conflicts()[0])),), ())
    assert _told(solution) == [
        f"P1: inset from the left edge is 1 mm ({HERE}:{line - 1}) and 2 mm ({HERE}:{line})"
    ]
    # A conflict is found before the board is looked at.
    off_board = Board(circuit=board.circuit)
    off_board.add(*board.statements())
    assert off_board.solve() == solution


def _a_breakout() -> tuple[Board, list]:
    """A module between two headers with a strap on each side of it, the 3 mm of the
    module above its pads kept clear on both faces and a mark between them on its own,
    as statements not yet added to the board."""
    board = _board(P1="A B VCC GND", P2="C D VCC GND", U1="A B D C GND", R1="VCC A", R2="VCC C")
    board.rails("VCC", "GND")
    p1, p2, u1, r1, r2 = board.parts("P1", "P2", "U1", "R1", "R2")
    antenna, mark = board.annotate(u1, antenna=((-1 * mm, -4 * mm), (9 * mm, -1 * mm)),
                                   mark=((3 * mm, 0 * mm), (5 * mm, 1 * mm)))  # fmt: skip
    said = [
        place(p1, against=Edge.LEFT, inset=2 * mm),
        place(p2, against=Edge.RIGHT, inset=2 * mm),
        align(p1, p2, grid=2 * mm),
        place(u1, between=(p1, p2), facing=Edge.TOP),
        place(r1, near=u1.pin_on(r1.signal_net), within=3 * mm, side="back"),
        place(r2, near=u1.pin_on(r2.signal_net), within=3 * mm),
        place(r2, side=Side.BACK),
        keepout(antenna, copper=True, both_sides=True),
        keepout(mark, copper=True),
    ]
    return board, said


def test_a_whole_board_is_placed():
    board, said = _a_breakout()
    board.add(*said)
    solution = board.solve()
    assert solution.ok, _told(solution)
    assert list(solution.poses) == ["P1", "P2", "R1", "R2", "U1"]
    at = {ref: _pads(board, solution, ref) for ref in solution.poses}
    # The module in the middle, each header with its pins beside the module's pads on
    # their nets, and each strap's pad on the pad it biases, from the back, its other
    # pad towards the other strap's: they are on one rail, 4 mm apart.
    assert at["U1"] == {"1": (111.0, 65.0), "2": (111.0, 67.0), "3": (119.0, 67.0),
                        "4": (119.0, 65.0), "5": (115.0, 68.0)}  # fmt: skip
    assert at["P1"]["1"] == (102.0, 61.19) and at["P1"]["4"] == (102.0, 68.81)
    assert at["P2"]["1"] == (128.0, 61.19) and at["P2"]["4"] == (128.0, 68.81)
    assert at["R1"] == {"1": (113.0, 65.0), "2": (111.0, 65.0)}
    assert at["R2"] == {"1": (117.0, 65.0), "2": (119.0, 65.0)}
    assert solution.poses["R1"].back and solution.poses["R2"].back
    assert solution.chosen == (
        "P1: centred along the left edge",
        "P1: turned 270 degrees, of 90, 270, for the shortest connections",
        "P2: centred along the right edge",
        "P2: turned 270 degrees, of 90, 270, for the shortest connections",
        "R1: 0 mm from U1.1, turned 180 degrees",
        "R2: 0 mm from U1.4, turned 0 degrees",
    )
    # What is kept clear, in the order it was written in: above the module's pads, the
    # straps' courtyards 0.1 mm below it, and the mark.
    assert _areas(solution) == [
        ('U1.area("antenna")', (110.0, 61.0, 120.0, 64.0), True, True),
        ('U1.area("mark")', (114.0, 65.0, 116.0, 66.0), True, False),
    ]


def test_the_order_statements_are_added_in_never_matters():
    _, said = _a_breakout()
    found = set()
    shuffled = random.Random(0)
    orders = [said, said[::-1], *(shuffled.sample(said, len(said)) for _ in range(40))]
    for order in orders:
        board, _ = _a_breakout()
        board.add(*order)
        solution = board.solve()
        found.add((tuple(solution.poses.items()), solution.free, solution.problems,
                   solution.chosen, solution.keepouts))  # fmt: skip
    assert len(found) == 1
    # And what does not hold is told the same way, in the same order.
    told = set()
    wrong = [*said, place(said[0].part, against=Edge.TOP, inset=0.5 * mm),
             align(said[0].part, said[1].part, grid=2.54 * mm)]  # fmt: skip
    for order in (wrong, wrong[::-1], wrong[4:] + wrong[:4]):
        board, _ = _a_breakout()
        board.add(*order)
        told.add(tuple(_told(board.solve())))
    assert len(told) == 1 and len(next(iter(told))) > 1


def test_solving_moves_nothing_and_adds_nothing():
    board, said = _a_breakout()
    board.add(*said)
    before, statements = dumps(board.sexpr()), board.statements()
    assert board.solve() == board.solve()
    assert dumps(board.sexpr()) == before and board.statements() == statements


def test_a_board_with_no_outline_or_a_part_with_no_footprint_is_refused():
    board = _board(P1="A B C D")
    board.place(board["P1"], against=Edge.LEFT)
    board.extent = None
    with pytest.raises(ValueError, match="a board is placed on once its outline is drawn"):
        board.solve()
    board = _board(P1="A B C D")
    del board.library["Conn:H"]
    with pytest.raises(ValueError, match="P1: no footprint 'Conn:H' to place"):
        board.solve()


def test_a_problem_gives_a_line_once_however_many_statements_it_made():
    board = _board(R1="A B", R2="A B")
    for ref in ("R1", "R2"):
        board.place(board[ref], against=Edge.LEFT)
    assert _told(board.solve()) == [f"R1 and R2 overlap ({HERE}:{_line_no() - 1})"]


def test_a_pad_turned_in_its_footprint_takes_the_room_it_covers():
    board = _board(D1="A")
    board.place(board["D1"], against=Edge.LEFT)
    solution = board.solve()
    assert solution.ok
    # 2 by 1 mm at 45 degrees is (2 + 1) / sqrt(2) = 2.1213 mm across and along, so its
    # middle is half that in from the edge its corner touches.
    assert _pads(board, solution, "D1")["1"] == pytest.approx((101.06066, 65.0), abs=1e-6)


def test_an_unplated_hole_takes_both_faces_too():
    for side in ("front", "back"):
        board = _board(H1="", R1="A B")
        board.place(board["H1"], against=Edge.LEFT)
        board.place(board["R1"], against=Edge.LEFT, side=side)
        assert [p.text for p in board.solve().problems] == ["H1 and R1 overlap"]


def test_a_footprint_with_nothing_drawn_is_a_point():
    board = _board(N1="")
    board.place(board["N1"], against=Edge.TOP)
    solution = board.solve()
    assert solution.ok
    assert solution.poses == {"N1": Pose(Length(115_000_000), Length(50_000_000))}


def test_on_the_back_a_part_is_mirrored_and_its_up_side_still_faces_where_it_was_said():
    board = _board(U1="A B C D E")
    board.place(board["U1"], against=Edge.TOP, inset=5 * mm, facing=Edge.TOP, side="back")
    solution = board.solve()
    assert solution.ok and solution.poses["U1"].back
    # Pads 1 and 4 are still the ones nearest the top edge, with the body above them;
    # seen from the front pad 1 is now on the right.
    assert _pads(board, solution, "U1") == {"1": (119.0, 55.0), "2": (119.0, 57.0),
                                            "3": (111.0, 57.0), "4": (111.0, 55.0),
                                            "5": (115.0, 58.0)}  # fmt: skip


def test_a_placement_that_does_not_settle_is_reported_and_a_part_with_no_place_has_none():
    board = _board(K1="X A", R1="A B")
    board.place(board["K1"], against=Edge.TOP)
    board.place(board["R1"], near=board["K1"].pin(1), within=2 * mm)
    said = _line_no() - 1
    solution = board.solve()
    # With pad 1 towards the middle of the board the resistor fits 1.8 mm below it. The
    # sensor's pad 2 is on the resistor's net, so the sensor is then turned to bring it
    # nearer; that puts pad 1 a millimetre from the top edge, deep in the sensor's own
    # outline, where the resistor has no place; and with no resistor the sensor has no
    # reason to be turned. Neither way round holds, and that is what is said.
    assert _told(solution) == [
        "the placement does not settle: each pass moves a part",
        "R1 has no place within 2 mm of K1.1 that is on the front of the board and clear of "
        f"the other parts ({HERE}:{said})",
    ]
    assert solution.problems[0].parts == ("K1", "R1")
    assert list(solution.poses) == ["K1"]


def test_a_square_part_against_an_edge_is_turned_any_way_round():
    board = _board(Q1="A B", T1="A")
    board.place(board["Q1"], against=Edge.LEFT)
    board.place(board["T1"], against=Edge.RIGHT)
    solution = board.solve()
    assert solution.ok
    # Pad 1 is turned towards the point on its net at the far edge.
    assert _pads(board, solution, "Q1") == {"1": (102.5, 65.0), "2": (100.5, 65.0)}
    assert ("Q1: turned 180 degrees, of 0, 90, 180, 270, for the shortest connections"
            in solution.chosen)  # fmt: skip


def test_one_place_given_twice_to_the_nanometre_is_one_place():
    board = _board(FID1="", FID2="", R1="A B")
    board.place(board["FID1"], against=Edge.LEFT, inset=1 * mm)
    board.place(board["FID2"], against=Edge.RIGHT, inset=Length(1))
    # The marks' middles are an odd number of nanometres apart, so midway between them
    # is on a half nanometre: 15.5 mm from the left edge, as near as can be said. Two
    # edges make a corner, which holds the resistor to between= both ways: the marks
    # are half way down the board, and its pads 1 mm either side of that.
    board.place(board["R1"], between=(board["FID1"], board["FID2"]), against=Edge.LEFT,
                inset=15.5 * mm, facing=Edge.LEFT)  # fmt: skip
    board.place(board["R1"], against=Edge.TOP, inset=14 * mm)
    solution = board.solve()
    assert solution.ok, _told(solution)
    assert _pads(board, solution, "R1")["1"] == pytest.approx((115.5, 66.0), abs=1e-6)
    assert _pads(board, solution, "R1")["2"] == pytest.approx((115.5, 64.0), abs=1e-6)


@pytest.mark.parametrize(
    ("edge", "pin", "turned"),
    [(Edge.LEFT, (100.5, 65.0), 0), (Edge.TOP, (115.0, 50.5), 90),
     (Edge.RIGHT, (129.5, 65.0), 0), (Edge.BOTTOM, (115.0, 79.5), 90)],
)  # fmt: skip
def test_a_part_placed_near_stays_on_the_board(edge, pin, turned):
    board = _board(T1="A", R1="B C")
    board.place(board["T1"], against=edge)
    board.place(board["R1"], near=board["T1"].pin(1), within=2 * mm, side="back")
    solution = board.solve()
    assert solution.ok, _told(solution)
    assert _pads(board, solution, "T1")["1"] == pin
    # Under the point, on the other face, the resistor's pad would be on the point's.
    # Its courtyard is 0.8 mm past its pad and the edge is 0.5 mm from the point.
    at = _pads(board, solution, "R1").values()
    assert min(math.dist(pad, pin) for pad in at) == pytest.approx(0.3, abs=1e-6)
    assert f"R1: 0.3 mm from T1.1, turned {turned} degrees" in solution.chosen


def test_a_part_with_holes_placed_near_one_on_the_back_keeps_clear_of_it():
    board = _board(P1="A B C D", R1="E F")
    board.place(board["R1"], against=Edge.BOTTOM, side="back")
    board.place(board["P1"], near=board["R1"].pin(1), within=3 * mm)
    solution = board.solve()
    assert solution.ok, _told(solution)
    # The resistor's courtyard is 0.9 mm above its pads and the header's 1.75 mm below
    # its pins: 2.65 mm, and 2.7 mm in steps of 0.1 mm.
    assert "P1: 2.7 mm from R1.1, turned 0 degrees" in solution.chosen


def test_within_is_as_the_crow_flies():
    def tried(within: Length) -> Solution:
        board = _board(T1="A", R1="B C")
        board.place(board["T1"], against=Edge.LEFT)
        board.place(board["T1"], against=Edge.TOP)
        board.place(board["R1"], near=board["T1"].pin(1), within=within, side="back")
        return board.solve()

    # In the corner the resistor's pad is 0.3 mm from the point one way and 0.4 mm the
    # other: 0.5 mm from it.
    solution = tried(0.5 * mm)
    assert solution.ok and "R1: 0.5 mm from T1.1, turned 0 degrees" in solution.chosen
    assert [p.text for p in tried(0.4 * mm).problems] == [
        "R1 has no place within 0.4 mm of T1.1 that is on the back of the board and clear of "
        "the other parts"
    ]


def test_align_holds_a_nanometre_either_side_of_a_whole_step():
    for inset in (2_299_999, 2_300_000, 2_300_001):
        board = _board(P1="A B C D", P2="E F G H")
        board.place(board["P1"], against=Edge.LEFT, inset=2.3 * mm)
        board.place(board["P2"], against=Edge.RIGHT, inset=Length(inset))
        board.align(board["P1"], board["P2"], grid=2.54 * mm)
        solution = board.solve()
        # 30 - 2.3 - 2.3 = 25.4 mm: ten steps.
        assert solution.ok, _told(solution)


def test_align_is_by_first_pins():
    board = _board(U1="A B C D E", R1="F G")
    board.place(board["U1"], against=Edge.TOP, facing=Edge.TOP)
    board.place(board["R1"], against=Edge.BOTTOM, inset=2 * mm)
    board.align(board["U1"], board["R1"], grid=3 * mm)
    solution = board.solve()
    at = {ref: _pads(board, solution, ref) for ref in ("U1", "R1")}
    # Pin 1 to pin 1 is 3 mm across and 24 mm along; the last pins are 1 mm across.
    assert at["U1"]["1"] == (111.0, 54.0) and at["R1"]["1"] == (114.0, 78.0)
    assert at["U1"]["5"] == (115.0, 57.0) and at["R1"]["2"] == (116.0, 78.0)
    assert solution.ok, _told(solution)


def _areas(solution: Solution) -> list[tuple[str, tuple[float, ...], bool, bool]]:
    """Each area kept clear: which, its box on the board in millimetres, and whether it
    is kept clear on the front and on the back."""
    return [(str(k.statement.area), tuple(v.mm for v in k.box), k.front, k.back)
            for k in solution.keepouts]  # fmt: skip


@pytest.mark.parametrize("edge", list(Edge))
@pytest.mark.parametrize("side", ["front", "back"])
@pytest.mark.parametrize("both", [False, True])
def test_an_area_kept_clear_goes_where_its_part_goes(edge, side, both):
    board = _board(U1="A B D C GND")
    u1 = board["U1"]
    # From the middle of pad 1 to the middle of pad 5.
    (area,) = board.annotate(u1, corner=((0 * mm, 0 * mm), (4 * mm, 3 * mm)))
    board.place(u1, against=edge, facing=edge, side=side)
    said = board.keepout(area, copper=True, both_sides=both)
    solution = board.solve()
    assert solution.ok, _told(solution)
    at = _pads(board, solution, "U1")
    xs, ys = sorted([at["1"][0], at["5"][0]]), sorted([at["1"][1], at["5"][1]])
    assert _areas(solution) == [('U1.area("corner")', (xs[0], ys[0], xs[1], ys[1]),
                                 both or side == "front", both or side == "back")]  # fmt: skip
    assert solution.keepouts[0].statement == said


@pytest.mark.parametrize(("side", "both", "pads", "chose"), [
    # On the module's face the nearest place is left of the area: 2 mm further than the
    # 1.8 mm it is with nothing kept clear.
    ("front", False, {"1": (105.2, 54.0), "2": (107.2, 54.0)}, "3.8 mm from U1.1, turned 0"),
    # On the other face nothing is kept clear, and it is on the pin as it would be.
    ("back", False, {"1": (109.0, 54.0), "2": (111.0, 54.0)}, "0 mm from U1.1, turned 0"),
    # Kept clear there too, it is still on the pin, turned out of the area: the least
    # turn that does it is a quarter, its other pad down the board.
    ("back", True, {"1": (111.0, 56.0), "2": (111.0, 54.0)}, "0 mm from U1.1, turned 90"),
])  # fmt: skip
def test_a_part_looking_for_a_place_keeps_out_of_an_area_kept_clear_on_its_face(
    side, both, pads, chose
):
    board = _module_at_the_top(R1="VCC A")
    # A strip 2 mm wide down the left of the module's outline: (108, 50) to (110, 58).
    (area,) = board.annotate(board["U1"], beside=((-3 * mm, -4 * mm), (-1 * mm, 4 * mm)))
    board.keepout(area, copper=True, both_sides=both)
    board.place(board["R1"], near=board["U1"].pin(1), within=5 * mm, side=side)
    solution = board.solve()
    assert solution.ok, _told(solution)
    assert _areas(solution) == [('U1.area("beside")', (108.0, 50.0, 110.0, 58.0), True, both)]
    assert _pads(board, solution, "R1") == pads
    assert f"R1: {chose} degrees" in solution.chosen


def _under_the_module(within: Length, side: str) -> tuple[Board, Solution, int]:
    """A strap looking for a place at the module's pin 1, where the top of the module is
    kept clear on both faces down to the lower edge of that pad: (110, 50) to (120, 54.5)."""
    board = _module_at_the_top(R1="VCC A")
    (area,) = board.annotate(board["U1"], antenna=((-1 * mm, -4 * mm), (9 * mm, 0.5 * mm)))
    board.keepout(area, copper=True, both_sides=True)
    board.place(board["R1"], near=board["U1"].pin(1), within=within, side=side)
    return board, board.solve(), _line_no() - 1


def test_a_part_looking_for_a_place_goes_no_nearer_than_what_is_kept_clear():
    board, solution, _ = _under_the_module(1.3 * mm, "back")
    assert solution.ok, _told(solution)
    assert _areas(solution) == [('U1.area("antenna")', (110.0, 50.0, 120.0, 54.5), True, True)]
    # Below the area and touching it: its courtyard ends 0.8 mm past its pad, so the pad
    # is 1.3 mm below the pin it would otherwise be on.
    assert _pads(board, solution, "R1") == {"1": (111.0, 57.3), "2": (111.0, 55.3)}
    assert "R1: 1.3 mm from U1.1, turned 90 degrees" in solution.chosen


def test_a_part_with_no_place_out_of_what_is_kept_clear_is_reported_with_the_keepout():
    board, solution, line = _under_the_module(1.2 * mm, "back")
    assert _told(solution) == [
        "R1 has no place within 1.2 mm of U1.1 that is on the back of the board and clear "
        f"of the other parts and of what is kept clear ({HERE}:{line}, {HERE}:{line - 1})"
    ]
    assert solution.problems[0].parts == ("R1",) and "R1" not in solution.poses
    near, kept = board.statements(about="R1")[0], solution.keepouts[0].statement
    assert solution.problems[0].statements == (near, kept)
    # On the front it is the module that leaves it no place, and the keepout is not named.
    board, solution, line = _under_the_module(1.7 * mm, "front")
    assert _told(solution) == [
        "R1 has no place within 1.7 mm of U1.1 that is on the front of the board and clear "
        f"of the other parts ({HERE}:{line})"
    ]
    assert solution.problems[0].statements == board.statements(about="R1")


def test_only_what_is_kept_clear_on_the_parts_face_is_named_for_its_having_no_place():
    board = _module_at_the_top(R1="VCC A")
    u1 = board["U1"]
    antenna, mark = board.annotate(u1, antenna=((-1 * mm, -4 * mm), (9 * mm, 0.5 * mm)),
                                   mark=((3 * mm, 0 * mm), (5 * mm, 1 * mm)))  # fmt: skip
    on_the_front = board.keepout(mark, copper=True)
    on_both = board.keepout(antenna, copper=True, both_sides=True)
    near = board.place(board["R1"], near=u1.pin(1), within=1.2 * mm, side="back")
    solution = board.solve()
    assert [k.statement for k in solution.keepouts] == [on_the_front, on_both]
    assert solution.problems[0].statements == (near, on_both)


def _over_a_strap(within: Length) -> tuple[Board, Solution, int]:
    """A header, which takes both faces, looking for a place at pin 1 of a strap on the
    back, where a strip 2 mm deep above the strap's outline is kept clear on the back
    alone: (107, 76.2) to (123, 78.2)."""
    board = _board(P1="A B C D", R1="E F")
    r1 = board["R1"]
    board.place(r1, against=Edge.BOTTOM, side="back")
    (area,) = board.annotate(r1, above=((-8 * mm, 0.9 * mm), (8 * mm, 2.9 * mm)))
    board.keepout(area, copper=True)
    board.place(board["P1"], near=r1.pin(1), within=within)
    return board, board.solve(), _line_no() - 1


def test_a_part_with_holes_keeps_out_of_what_is_kept_clear_on_either_face():
    board, solution, _ = _over_a_strap(5 * mm)
    assert solution.ok, _told(solution)
    assert _areas(solution) == [('R1.area("above")', (107.0, 76.2, 123.0, 78.2), False, True)]
    # Above the strip and touching it, 2 mm further than the 2.7 mm it is from the strap
    # with nothing kept clear.
    assert _pads(board, solution, "P1")["4"] == (114.0, 74.4)
    assert "P1: 4.7 mm from R1.1, turned 0 degrees" in solution.chosen


def test_a_part_with_holes_with_no_place_names_what_is_kept_clear_on_the_other_face():
    board, solution, line = _over_a_strap(4.6 * mm)
    assert _told(solution) == [
        "P1 has no place within 4.6 mm of R1.1 that is on the front of the board and clear "
        f"of the other parts and of what is kept clear ({HERE}:{line}, {HERE}:{line - 1})"
    ]
    assert solution.problems[0].statements == (board.statements(about="P1")[0],
                                               solution.keepouts[0].statement)  # fmt: skip


@pytest.mark.parametrize(("ref", "side", "both", "kept_out"), [
    ("R1", "front", False, True),
    ("R1", "back", False, False),
    ("R1", "back", True, True),
    # A part with holes is on both faces.
    ("P1", "back", False, True),
])  # fmt: skip
def test_a_part_given_a_place_in_an_area_kept_clear_is_reported_and_stays(
    ref, side, both, kept_out
):
    board = _board(U1="A B D C GND", **{ref: "E F G H" if ref == "P1" else "E F"})
    u1, part = board.parts("U1", ref)
    board.place(u1, against=Edge.BOTTOM, facing=Edge.TOP)
    # The 8 mm of board above the module's outline: (110, 64) to (120, 72).
    (area,) = board.annotate(u1, antenna=((-1 * mm, -12 * mm), (9 * mm, -4 * mm)))
    said = board.keepout(area, copper=True, both_sides=both)
    line = _line_no() - 1
    board.place(part, against=Edge.TOP, inset=15 * mm, side=side)
    solution = board.solve()
    assert _areas(solution) == [('U1.area("antenna")', (110.0, 64.0, 120.0, 72.0), True, both)]
    assert {y for _, y in _pads(board, solution, ref).values()} == {65.0}
    assert solution.ok is not kept_out
    told = (f"{ref} is in U1's antenna area, which is kept clear of copper "
            f"({HERE}:{line}, {HERE}:{line + 2})")  # fmt: skip
    assert _told(solution) == ([told] if kept_out else [])
    if kept_out:
        assert solution.problems[0].parts == (ref, "U1")
        assert solution.problems[0].statements == (said, *board.statements(about=ref))


def test_an_area_of_a_part_that_is_not_placed_is_nowhere():
    board = _board(U1="A B D C GND")
    u1 = board["U1"]
    (area,) = board.annotate(u1, antenna=((-1 * mm, -4 * mm), (9 * mm, -1 * mm)))
    board.keepout(area, copper=True)
    # Keeping an area of it clear does not say where the part goes.
    solution = board.solve()
    assert solution.free == ("U1",) and not solution.poses and not solution.problems
    assert solution.keepouts == ()
    board.place(u1, against=Edge.LEFT)
    board.place(u1, against=Edge.RIGHT)
    solution = board.solve()
    assert len(solution.problems) == 1 and not solution.poses and solution.keepouts == ()


def test_an_area_is_where_the_board_being_solved_has_it():
    other = _board(U1="A B D C GND")
    (theirs,) = other.annotate(other["U1"], antenna=((-1 * mm, -4 * mm), (9 * mm, -1 * mm)))
    board = _module_at_the_top()
    # Here the area is the box between the pads: (111, 54) to (119, 56).
    board.annotate(board["U1"], antenna=((0 * mm, 0 * mm), (8 * mm, 2 * mm)))
    board.add(keepout(theirs, copper=True))
    assert _areas(board.solve()) == [('U1.area("antenna")', (111.0, 54.0, 119.0, 56.0),
                                      True, False)]  # fmt: skip


def _a_point_with_a_strap(**parts: str) -> Board:
    """The module at the top, and a test point 5 mm in from the left edge beside its
    pad 1, at (105, 54), with a strap looking for a place at it."""
    board = _module_at_the_top(T1="X", R1="X VCC", **parts)
    t1, r1 = board.parts("T1", "R1")
    board.place(t1, against=Edge.LEFT, inset=5 * mm)
    board.place(t1, against=Edge.TOP, inset=4 * mm)
    board.place(r1, near=t1, within=3 * mm)
    return board


def test_a_part_that_looks_for_a_place_looks_once_those_given_one_are_placed():
    board = _a_point_with_a_strap()
    # With nothing kept clear the strap is right of the point, its courtyard touching
    # it, and reaches to x = 109.1.
    assert _pads(board, board.solve(), "R1") == {"1": (106.3, 54.0), "2": (108.3, 54.0)}
    # The strip left of the module starts at x = 108. R1 comes before U1 by its
    # reference and still looks after U1 is placed: it goes left of the point.
    (area,) = board.annotate(board["U1"], beside=((-3 * mm, -4 * mm), (-1 * mm, 4 * mm)))
    board.keepout(area, copper=True)
    solution = board.solve()
    assert solution.ok, _told(solution)
    assert _pads(board, solution, "R1") == {"1": (103.7, 54.0), "2": (101.7, 54.0)}
    assert "R1: 1.3 mm from T1, turned 180 degrees" in solution.chosen


def test_an_area_of_a_part_that_looks_for_its_place_is_not_kept_out_of_but_reported():
    def tried(keep: bool) -> tuple[Solution, int]:
        board = _board(T1="X", R1="X VCC", U1="A B D C GND")
        t1, r1, u1 = board.parts("T1", "R1", "U1")
        board.place(t1, against=Edge.LEFT, inset=15 * mm)
        board.place(r1, near=t1, within=3 * mm)
        board.place(u1, near=t1, within=12 * mm)
        # 10 mm all round the module's outline.
        (area,) = board.annotate(u1, around=((-11 * mm, -14 * mm), (19 * mm, 14 * mm)))
        if keep:
            board.keepout(area, copper=True)
        return board.solve(), _line_no() - 1

    (without, _), (solution, line) = tried(False), tried(True)
    # R1 found its place before U1 had one, and U1 looks for room for its outline and
    # not for its area: nothing moves, and what is in the area is said.
    assert without.ok and solution.poses == without.poses
    assert _told(solution) == [
        "R1 is in U1's around area, which is kept clear of copper "
        f"({HERE}:{line}, {HERE}:{line - 5})",
        "T1 is in U1's around area, which is kept clear of copper "
        f"({HERE}:{line}, {HERE}:{line - 6})",
    ]


def _xs(board: Board, solution: Solution, *refs: str) -> list[float]:
    """Where the pads of *refs* are across the board, part by part, each from the left."""
    return [x for ref in refs for x in sorted(x for x, _ in _pads(board, solution, ref).values())]


def test_a_row_spreads_its_parts_along_an_edge_with_equal_gaps_the_ends_too():
    # Three resistors, 3.6 mm each, along a 30 mm edge: four gaps of 4.8 mm.
    board = _board(R1="A B", R2="C D", R3="E F")
    board.row(board.parts("R1..R3"), along=Edge.BOTTOM)
    solution = board.solve()
    assert solution.ok and solution.free == ()
    # Each lies along the edge, its courtyard touching it, 0.9 mm out from its pads.
    assert {y for ref in ("R1", "R2", "R3") for _, y in _pads(board, solution, ref).values()} == {
        79.1
    }
    assert _xs(board, solution, "R1", "R2", "R3") == pytest.approx(
        [105.6, 107.6, 114.0, 116.0, 122.4, 124.4]
    )


def test_a_row_is_in_the_order_its_parts_are_named_whatever_their_sizes():
    # A resistor, a 3 mm square part and a resistor: 10.2 mm, and four gaps of 4.95 mm.
    board = _board(R1="A B", Q1="C D", R2="E F")
    board.add(row([board["R2"], board["Q1"], board["R1"]], along=Edge.TOP))
    solution = board.solve()
    assert solution.ok
    assert [solution.poses[ref].x.mm for ref in ("R2", "Q1", "R1")] == pytest.approx(
        [106.75, 115.0, 123.25]
    )
    assert {solution.poses[ref].y.mm for ref in ("R1", "R2")} == {50.9}


@pytest.mark.parametrize(("edge", "x"), [(Edge.LEFT, 100.9), (Edge.RIGHT, 129.1)])
def test_a_row_along_a_side_runs_from_the_top_down(edge, x):
    board = _board(R1="A B", R2="C D", R3="E F")
    board.row(board.parts("R1..R3"), along=edge)
    solution = board.solve()
    assert solution.ok
    assert [(solution.poses[ref].x.mm, solution.poses[ref].y.mm) for ref in ("R1", "R2", "R3")] == [
        pytest.approx((x, y)) for y in (56.6, 65.0, 73.4)
    ]
    assert all(solution.poses[ref].rot in (90, 270) for ref in ("R1", "R2", "R3"))


def test_a_row_with_a_pitch_has_its_parts_that_far_apart_about_the_middle_of_the_edge():
    board = _board(R1="A B", R2="C D", R3="E F")
    board.row(board.parts("R1..R3"), along=Edge.TOP, pitch=5 * mm, inset=2 * mm)
    solution = board.solve()
    assert solution.ok
    assert [solution.poses[ref].x.mm for ref in ("R1", "R2", "R3")] == [110.0, 115.0, 120.0]
    # Inset is to the pads, as it is for one part against an edge.
    assert {y for ref in ("R1", "R2", "R3") for _, y in _pads(board, solution, ref).values()} == {
        52.0
    }


def test_a_row_does_not_depend_on_when_it_was_said_and_places_what_is_placed_by_it():
    def said(board: Board) -> list:
        p1, p2 = board.parts("P1", "P2")
        return [row([p1, p2], along=Edge.BOTTOM),
                place(board["U1"], between=(p1, p2), against=Edge.TOP),
                place(board["R1"], near=p1.pin(1), within=4 * mm)]  # fmt: skip

    first, second = (_board(P1="A B C D", P2="E F G H", U1="A E C G GND", R1="A X")
                     for _ in range(2))  # fmt: skip
    first.add(*said(first))
    second.add(*reversed(said(second)))
    solution = first.solve()
    assert solution.ok and solution == second.solve()
    # Two headers 11.12 mm long: three gaps of 2.5867 mm, to the nanometre below, and
    # the pins 1.75 mm in from each header's courtyard, whichever way round it is.
    assert _xs(first, solution, "P1", "P2") == pytest.approx(
        [start + 2.54 * n for start in (104.336667, 118.043333) for n in range(4)], abs=2e-6
    )


def test_a_row_too_long_for_its_edge_is_said_and_none_of_it_is_placed():
    board = _board(P1="A B C D", P2="E F G H", P3="J K L M", R1="A X")
    board.row(board.parts("P1..P3"), along=Edge.BOTTOM)
    line = _line_no() - 1
    board.place(board["R1"], against=Edge.TOP)
    solution = board.solve()
    assert not solution.ok and list(solution.poses) == ["R1"] and solution.free == ()
    assert _told(solution) == [
        'row(P1, P2, P3, along=Edge.BOTTOM, pitch="even") does not fit: its parts are '
        f"33.36 mm along the bottom edge, which is 30 mm ({HERE}:{line})"
    ]
    assert solution.problems[0].parts == ("P1", "P2", "P3")


def test_a_row_and_another_place_for_one_of_its_parts_are_held_together():
    board = _board(R1="A B", R2="C D", R3="E F")
    board.row(board.parts("R1..R3"), along=Edge.BOTTOM)
    line = _line_no() - 1
    # The left edge puts R1 4.8 mm from where the row has it.
    board.place(board["R1"], against=Edge.LEFT)
    board.place(board["R3"], near=board["R2"], within=3 * mm)
    assert _told(board.solve()) == [
        f"R1 is put in two places 4.8 mm apart across the board ({HERE}:{line}, {HERE}:{line + 3})",
        f"R3: near= is solved alone: one near=, and no row() beside it ({HERE}:{line + 4}, "
        f"{HERE}:{line})",
    ]


def test_the_parts_of_a_row_are_turned_the_same_way_for_the_rows_shortest_connections():
    # A header along the top with its pins A to D from the left, and under it a row of
    # three resistors. R1 and R2 have a pad nearer its pin turned 0 degrees; R3 alone
    # would turn 180, to bring its pad 2 nearer D.
    def board() -> Board:
        board = _board(P1="A B C D", R1="X A", R2="B Y", R3="Z D")
        board.place(board["P1"], against=Edge.TOP, facing=Edge.TOP)
        board.row(board.parts("R1..R3"), along=Edge.BOTTOM)
        return board

    solution = board().solve()
    assert solution.ok
    assert [solution.poses[ref].rot for ref in ("R1", "R2", "R3")] == [0, 0, 0]
    assert solution.chosen == (
        "P1: centred along the top edge",
        'row(R1, R2, R3, along=Edge.BOTTOM, pitch="even"): turned 0 degrees, of 0, 180, for '
        "the shortest connections",
    )
    # With each resistor's nets the other way round, the row is turned the other way.
    turned = _board(P1="A B C D", R1="A X", R2="Y B", R3="D Z")
    turned.place(turned["P1"], against=Edge.TOP, facing=Edge.TOP)
    turned.row(turned.parts("R1..R3"), along=Edge.BOTTOM)
    solution = turned.solve()
    assert solution.ok
    assert [solution.poses[ref].rot for ref in ("R1", "R2", "R3")] == [180, 180, 180]
    # A part of the row that faces an edge keeps to it, and the rest are turned together.
    faced = board()
    faced.place(faced["R3"], facing=Edge.BOTTOM)
    solution = faced.solve()
    assert solution.ok
    assert [solution.poses[ref].rot for ref in ("R1", "R2", "R3")] == [0, 0, 180]
    assert _xs(faced, solution, "R3") == pytest.approx([122.4, 124.4])


def test_a_part_of_a_row_lies_along_the_rows_edge_whatever_other_edge_it_is_against():
    # Three headers down the left edge are 33.36 mm, on end; the first is against the
    # top edge as well, which does not leave any of them lying across the board.
    board = _board(P1="A B C D", P2="E F G H", P3="J K L M")
    board.row(board.parts("P1..P3"), along=Edge.LEFT)
    board.place(board["P1"], against=Edge.TOP)
    assert [p.text for p in board.solve().problems] == [
        'row(P1, P2, P3, along=Edge.LEFT, pitch="even") does not fit: its parts are 33.36 mm '
        "along the left edge, which is 30 mm"
    ]


def test_a_row_holds_a_part_drawn_on_end_beside_one_drawn_across():
    # A resistor, 3.6 mm long as drawn, and a header drawn on end, 11.12 mm long once it
    # lies along the edge: three gaps of 5.0933 mm.
    board = _board(R1="A B", V1="C D E F")
    board.row(board.parts("R1", "V1"), along=Edge.BOTTOM)
    solution = board.solve()
    assert solution.ok
    assert solution.poses["R1"].rot in (0, 180) and solution.poses["V1"].rot in (90, 270)
    header = _pads(board, solution, "V1").values()
    assert {y for _, y in header} == {78.25}
    assert sorted(x for x, _ in header) == pytest.approx(
        [115.536667 + 2.54 * n for n in range(4)], abs=2e-6
    )
    assert _xs(board, solution, "R1") == pytest.approx([105.893333, 107.893333], abs=2e-6)
    assert solution.chosen == (
        'row(R1, V1, along=Edge.BOTTOM, pitch="even"): turned 0 degrees from how each part '
        "lies along the edge, of 0, 180, for the shortest connections",
    )


def test_a_part_in_rows_along_two_edges_is_said_to_be_in_two_places():
    board = _board(R1="A B", R2="C D", R3="E F", R4="G H", R5="J K")
    board.row(board.parts("R1..R3"), along=Edge.BOTTOM)
    board.row(board.parts("R1", "R4", "R5"), along=Edge.LEFT)
    solution = board.solve()
    # R1 lies along the edge of the first row it is in, and the other row goes on
    # without it.
    assert [p.text for p in solution.problems] == [
        "R1 is put in two places 4.8 mm apart across the board"
    ]
    assert sorted(solution.poses) == ["R2", "R3", "R4", "R5"]


def test_what_a_turn_a_row_does_not_take_would_run_into_is_not_said():
    # The module is not the same about its middle, so each way round puts it somewhere
    # else against the top edge; only the way the row is turned is reported.
    board = _board(U1="A B C D GND", U2="E F G H GND")
    board.row(board.parts("U1", "U2"), along=Edge.BOTTOM, inset=1 * mm)
    board.place(board["U1"], against=Edge.TOP)
    assert [p.text for p in board.solve().problems] == [
        "U1 is put in two places 22 mm apart along the board"
    ]


def test_a_row_with_a_pitch_that_runs_past_its_edge_is_said_and_none_of_it_is_placed():
    # Middles 14 mm apart about the middle of a 30 mm edge: the outer two are 1 mm
    # from its ends, and half a resistor is 1.8 mm.
    board = _board(R1="A B", R2="C D", R3="E F")
    board.row(board.parts("R1..R3"), along=Edge.BOTTOM, pitch=14 * mm)
    solution = board.solve()
    assert solution.poses == {} and [p.text for p in solution.problems] == [
        "row(R1, R2, R3, along=Edge.BOTTOM, pitch=14 mm) does not fit: at that pitch R1 "
        "reaches 0.8 mm past the end of the bottom edge"
    ]
    # A header and a resistor 20 mm apart are 27.36 mm from end to end, which is less
    # than the edge; the header's middle is 5 mm from the end and half of it is 5.56 mm.
    board = _board(P1="A B C D", R1="E F")
    board.row(board.parts("P1", "R1"), along=Edge.BOTTOM, pitch=20 * mm)
    solution = board.solve()
    assert solution.poses == {} and [p.text for p in solution.problems] == [
        "row(P1, R1, along=Edge.BOTTOM, pitch=20 mm) does not fit: at that pitch P1 reaches "
        "0.56 mm past the end of the bottom edge"
    ]


def test_a_row_is_turned_for_its_connections_to_the_rest_of_the_board_not_to_itself():
    # R1's pad on A is nearer the header's pin turned 0 degrees, by 2 mm. R1 and R2
    # share a net whose pads would be nearer each other turned 180, by more.
    board = _board(P1="A B C D", R1="N A", R2="Y N", R3="Z W")
    board.place(board["P1"], against=Edge.TOP, facing=Edge.TOP)
    board.row(board.parts("R1..R3"), along=Edge.BOTTOM)
    solution = board.solve()
    assert solution.ok
    assert [solution.poses[ref].rot for ref in ("R1", "R2", "R3")] == [0, 0, 0]


@pytest.mark.parametrize("edge", [Edge.TOP, Edge.BOTTOM, Edge.LEFT, Edge.RIGHT])
@pytest.mark.parametrize("side", [Side.FRONT, Side.BACK])
def test_in_a_row_a_header_drawn_on_end_has_its_pin_1_at_the_same_end_as_one_drawn_across(
    edge, side
):
    board = _board(P1="A B C D", V1="E F G H")
    board.row(board.parts("P1", "V1"), along=edge)
    for part in board.parts("P1", "V1"):
        board.place(part, side=side)
    solution = board.solve()
    assert solution.ok
    along = 0 if edge in (Edge.TOP, Edge.BOTTOM) else 1
    runs = []
    for ref in ("P1", "V1"):
        at = _pads(board, solution, ref)
        runs.append(at["4"][along] - at["1"][along])
    # Each header's pins run 7.62 mm along the edge, and both the same way.
    assert [abs(run) for run in runs] == pytest.approx([7.62, 7.62])
    assert runs[0] * runs[1] > 0


def test_centre_puts_the_middle_of_a_parts_outline_at_the_middle_of_the_board():
    # The module's outline is 10 by 8 mm with its middle 4 mm right of its origin.
    board = _board(U1="A B C D GND", Q1="E F")
    board.place(board["U1"], centre=True)
    solution = board.solve()
    assert solution.poses == {"U1": Pose(Length(111_000_000), Length(65_000_000))}
    assert solution.free == ("Q1",) and solution.problems == ()
    assert solution.chosen == (
        "U1: turned 0 degrees, of 0, 90, 180, 270, for the shortest connections",
    )
    # It is one place: an edge as well is another.
    board.place(board["U1"], against=Edge.LEFT)
    (problem,) = board.solve().problems
    assert problem.text.startswith("U1 is put in two places ")
    assert problem.statements == board.statements()
    # And a part that looks for a place near something is not also at the centre.
    board = _board(U1="A B C D GND", Q1="E F")
    board.place(board["U1"], against=Edge.TOP)
    board.place(board["Q1"], near=board["U1"], within=3 * mm, centre=True)
    assert [p.text for p in board.solve().problems] == [
        "Q1: near= is solved alone: one near=, and no centre=True beside it"
    ]


@pytest.mark.parametrize(
    ("edge", "beyond"),
    [
        (Edge.TOP, lambda x, y: 63.25 - y),
        (Edge.BOTTOM, lambda x, y: y - 66.75),
        (Edge.LEFT, lambda x, y: 109.44 - x),
        (Edge.RIGHT, lambda x, y: x - 120.56),
    ],
)
def test_toward_an_edge_a_part_is_on_that_side_of_what_it_is_near(edge, beyond):
    # A header at the centre of the board: its courtyard is from 109.44 to 120.56 mm
    # across and from 63.25 to 66.75 mm down. A resistor's pads are 0.8 mm or more in
    # from its own courtyard, so they are that far beyond the header's.
    board = _board(P1="A B C D", R1="B X")
    board.place(board["P1"], centre=True, facing=Edge.TOP)
    board.place(board["R1"], near=board["P1"], within=4 * mm, toward=edge)
    solution = board.solve()
    assert solution.ok
    assert all(beyond(x, y) > 0.8 - 1e-6 for x, y in _pads(board, solution, "R1").values())


def test_a_part_with_no_place_on_the_side_it_is_to_be_on_is_said():
    board = _board(P1="A B C D", R1="B X")
    board.place(board["P1"], against=Edge.BOTTOM)
    board.place(board["R1"], near=board["P1"], within=4 * mm, toward=Edge.BOTTOM)
    line = _line_no() - 1
    assert _told(board.solve()) == [
        "R1 has no place within 4 mm of P1, toward the bottom edge, that is on the front of "
        f"the board and clear of the other parts ({HERE}:{line})"
    ]


def test_toward_an_edge_a_parts_whole_outline_is_beyond_what_it_is_near():
    # The module at the centre is from 110 to 120 mm across and 61 to 69 mm down, with
    # its pin 1 at (111, 65): 1 mm in from its left side and 4 mm down from its top. The
    # nearest clear place to that pin is beside the module; toward the top edge the
    # test point is above it, the whole of its 1 mm pad.
    board = _board(U1="A B C D GND", T1="A")
    board.place(board["U1"], centre=True, facing=Edge.TOP)
    board.place(board["T1"], near=board["U1"].pin(1), within=5 * mm)
    assert _pads(board, board.solve(), "T1")["1"][0] == pytest.approx(109.5)
    board = _board(U1="A B C D GND", T1="A")
    board.place(board["U1"], centre=True, facing=Edge.TOP)
    board.place(board["T1"], near=board["U1"].pin(1), within=5 * mm, toward=Edge.TOP)
    solution = board.solve()
    assert solution.ok
    assert _pads(board, solution, "T1")["1"] == pytest.approx((111.0, 60.5))


def _rounded(r: float, **parts: str) -> Board:
    """The 30 mm board with its corners rounded to radius *r*."""
    board = _board(**parts)
    board.outline_rounded_rect(100, 50, 130, 80, r)
    return board


def test_a_part_put_in_a_rounded_corner_is_outside_the_outline_and_is_said_to_be():
    # A resistor in the corner of the box around the board. On a board that is that box
    # it fits; with the corner rounded to 4 mm, the resistor's own corner is 4 mm from
    # each edge of the arc's square and so 4 * sqrt(2) - 4 outside the arc.
    def corner(board: Board) -> Solution:
        board.place(board["R1"], against=Edge.LEFT)
        board.place(board["R1"], against=Edge.TOP)
        return board.solve()

    assert corner(_board(R1="A B")).ok
    solution = corner(_rounded(4, R1="A B"))
    (problem,) = solution.problems
    far, where = re.fullmatch(
        r"R1 does not fit on the board: it reaches ([\d.]+) mm outside the outline at (.*)",
        problem.text,
    ).groups()  # pyright: ignore[reportOptionalMemberAccess]
    assert float(far) == pytest.approx(4 * math.sqrt(2) - 4, abs=1e-3)
    assert where == "(100 mm, 50 mm)" and len(problem.statements) == 2
    # It is said, and the part is left where it was put.
    assert "R1" in solution.poses
    # Brought in from the corner, it is inside.
    board = _rounded(4, R1="A B")
    board.place(board["R1"], against=Edge.LEFT, inset=3 * mm)
    board.place(board["R1"], against=Edge.TOP, inset=3 * mm)
    assert board.solve().ok


def test_a_part_that_looks_for_a_place_looks_inside_the_outline():
    # Corners of 10 mm. A resistor near the arc, and a test point to its left: level
    # with the resistor's pad it would be outside the arc, so it goes where it is not.
    board = _rounded(10, R1="A B", T1="Z")
    board.place(board["R1"], against=Edge.LEFT, inset=2.6 * mm)
    board.place(board["R1"], against=Edge.TOP, inset=6 * mm)
    board.place(board["T1"], near=board["R1"], within=3 * mm, toward=Edge.LEFT)
    solution = board.solve()
    assert solution.ok
    x, y = _pads(board, solution, "T1")["1"]
    assert x <= 101.3 + 1e-6 and y > 56.0
    # On the box around that board the nearest place is level with the pad.
    box = _board(R1="A B", T1="Z")
    box.place(box["R1"], against=Edge.LEFT, inset=2.6 * mm)
    box.place(box["R1"], against=Edge.TOP, inset=6 * mm)
    box.place(box["T1"], near=box["R1"], within=3 * mm, toward=Edge.LEFT)
    assert _pads(box, box.solve(), "T1")["1"] == pytest.approx((101.3, 56.0))


def test_a_part_over_a_mounting_hole_is_said_and_one_that_looks_for_a_place_avoids_it():
    board = _board(U1="A B C D GND", T1="A")
    hole = board.hole("Mech:Hole", (115, 65))
    assert (hole.label, hole.footprint, hole.x.mm, hole.y.mm) == ("Hole at (115, 65)", "Mech:Hole",
                                                                  115, 65)  # fmt: skip
    assert board.fixed == [hole]
    board.place(board["U1"], centre=True)
    line = _line_no() - 1
    solution = board.solve()
    assert _told(solution) == [f"U1 is over Hole at (115, 65) ({HERE}:{line})"]
    assert not solution.ok and "U1" in solution.poses
    # Without the hole, the nearest clear place to the module's pin 1 is on its left,
    # level with the pin. A hole there, 2 mm across, sends the test point elsewhere.
    board = _board(U1="A B C D GND", T1="A")
    board.hole("Mech:Hole", (109, 65))
    board.place(board["U1"], centre=True, facing=Edge.TOP)
    board.place(board["T1"], near=board["U1"].pin(1), within=5 * mm)
    solution = board.solve()
    assert solution.ok
    # The hole is from 108 to 110 mm across and 64 to 66 down, and the test point 1 mm.
    x, y = _pads(board, solution, "T1")["1"]
    assert not (107.5 < x < 110.5 and 63.5 < y < 66.5)
    with pytest.raises(ValueError, match="no footprint 'Mech:Nowhere' in the board's library"):
        board.hole("Mech:Nowhere", (0, 0))


def test_what_is_fixed_takes_the_face_it_is_on_unless_it_has_holes_and_turns_as_a_part_does():
    # A resistor's footprint fixed on the back: a part on the front is clear of it, one
    # on the back is not.
    for side, told in ((Side.FRONT, []), (Side.BACK, ["Q1 is over R at (115, 65)"])):
        board = _board(Q1="A B")
        board.hole("Device:R", (115, 65), back=True)
        board.place(board["Q1"], centre=True, side=side)
        assert [p.text for p in board.solve().problems] == told
    # A header fixed across the board is clear of a test point 7 mm above its pins;
    # turned a quarter turn it runs up the board, under the test point.
    for rot, told in ((0, []), (90, ["T1 is over H at (115, 65)"])):
        board = _board(T1="A")
        board.hole("Conn:H", (115, 65), rot=rot)
        board.place(board["T1"], against=Edge.TOP, inset=8 * mm)
        assert [p.text for p in board.solve().problems] == told


def test_a_row_spreads_over_what_mounting_holes_leave_clear_of_its_edge():
    # Holes 2 mm across, 2 mm in from the bottom corners: in the strip the resistors
    # take up, the edge is clear from 103 to 127 mm. Four gaps of 3.3 mm.
    board = _board(R1="A B", R2="C D", R3="E F")
    board.hole("Mech:Hole", (102, 78))
    board.hole("Mech:Hole", (128, 78))
    board.row(board.parts("R1..R3"), along=Edge.BOTTOM)
    solution = board.solve()
    assert solution.ok
    assert _xs(board, solution, "R1", "R2", "R3") == pytest.approx(
        [107.1, 109.1, 114.0, 116.0, 120.9, 122.9]
    )
    assert solution.chosen[-1] == (
        'row(R1, R2, R3, along=Edge.BOTTOM, pitch="even"): over the 24 mm of the bottom edge '
        "that is clear, of 30 mm"
    )
    # Holes further in than the resistors reach leave the whole edge.
    board = _board(R1="A B", R2="C D", R3="E F")
    board.hole("Mech:Hole", (102, 70))
    board.hole("Mech:Hole", (128, 70))
    board.row(board.parts("R1..R3"), along=Edge.BOTTOM)
    solution = board.solve()
    assert _xs(board, solution, "R1", "R2", "R3") == pytest.approx(
        [105.6, 107.6, 114.0, 116.0, 122.4, 124.4]
    )
    assert not any("clear" in line for line in solution.chosen)


def test_a_row_spreads_over_the_straight_of_an_edge_between_rounded_corners():
    # Corners of 4 mm: the bottom edge is straight from 104 to 126 mm. Four gaps of 2.8.
    board = _rounded(4, R1="A B", R2="C D", R3="E F")
    board.row(board.parts("R1..R3"), along=Edge.BOTTOM)
    solution = board.solve()
    assert solution.ok
    assert _xs(board, solution, "R1", "R2", "R3") == pytest.approx(
        [107.6, 109.6, 114.0, 116.0, 120.4, 122.4]
    )


def test_a_row_that_does_not_fit_what_is_clear_is_said_with_how_much_is():
    # Holes at 109 and 121 mm leave 10 mm between them, and 8 mm either side.
    board = _board(R1="A B", R2="C D", R3="E F")
    board.hole("Mech:Hole", (109, 79))
    board.hole("Mech:Hole", (121, 79))
    board.row(board.parts("R1..R3"), along=Edge.BOTTOM)
    solution = board.solve()
    assert solution.poses == {} and [p.text for p in solution.problems] == [
        'row(R1, R2, R3, along=Edge.BOTTOM, pitch="even") does not fit: its parts are 10.8 mm '
        "along what is clear of the bottom edge, which is 10 mm"
    ]


def test_a_row_with_a_pitch_is_about_the_middle_of_what_is_clear():
    # One hole, at the left: the edge is clear from 103 to 130 mm, its middle at 116.5.
    board = _board(R1="A B", R2="C D", R3="E F")
    board.hole("Mech:Hole", (102, 78))
    board.row(board.parts("R1..R3"), along=Edge.BOTTOM, pitch=5 * mm)
    solution = board.solve()
    assert solution.ok
    assert [solution.poses[ref].x.mm for ref in ("R1", "R2", "R3")] == [111.5, 116.5, 121.5]
    # Too far apart for what is clear, though not for the edge.
    board = _board(R1="A B", R2="C D", R3="E F")
    board.hole("Mech:Hole", (102, 78))
    board.row(board.parts("R1..R3"), along=Edge.BOTTOM, pitch=12 * mm)
    assert [p.text for p in board.solve().problems] == [
        "row(R1, R2, R3, along=Edge.BOTTOM, pitch=12 mm) does not fit: at that pitch R1 reaches "
        "0.3 mm past the end of what is clear of the bottom edge"
    ]


def _drawn(x0: float, y0: float, x1: float, y1: float, **parts: str) -> Board:
    """A board whose outline is drawn as four lines between those corners."""
    made = _board(**parts)
    board = Board(circuit=made.circuit, library=made.library)
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    board.outline({"type": "gr_line", "start": a, "end": b}
                  for a, b in zip(corners, corners[1:] + corners[:1], strict=True))  # fmt: skip
    return board


@pytest.mark.parametrize("edge", [Edge.LEFT, Edge.RIGHT, Edge.TOP, Edge.BOTTOM])
def test_a_plain_board_drawn_where_millimetres_are_not_whole_nanometres_is_still_its_box(edge):
    # 129.54 mm times a million is 129539999.99999999: an outline scaled and not
    # rounded is a hair off its box, and a part touching that edge was outside it.
    board = _drawn(149.86, 96.52, 238.76, 129.54, R1="A B", R2="C D", R3="E F")
    board.place(board["R1"], against=edge)
    board.row(board.parts("R2", "R3"), along=edge, inset=5 * mm)
    solution = board.solve()
    assert solution.problems == ()
    assert not any("clear" in line or "outside" in line for line in solution.chosen)


@pytest.mark.parametrize("rot", [0, 90, 180, 270])
def test_what_is_fixed_is_the_same_size_turned_through_right_angles(rot):
    # A 3 mm part at the centre of the board is from 113.5 mm; a 2 mm hole at 112.5
    # ends there. Touching is not overlapping, whichever way round the hole is.
    board = _board(Q1="A B")
    board.hole("Mech:Hole", (112.5, 65), rot=rot)
    board.place(board["Q1"], centre=True)
    assert board.solve().problems == ()
    # And 1 micrometre further in, it is over it.
    board = _board(Q1="A B")
    board.hole("Mech:Hole", (112.501, 65), rot=rot)
    board.place(board["Q1"], centre=True)
    assert [p.text for p in board.solve().problems] == ["Q1 is over Hole at (112.501, 65)"]


def test_which_hole_a_problem_names_does_not_depend_on_which_was_put_on_the_board_first():
    told = []
    for holes in ([(112, 65), (118, 65)], [(118, 65), (112, 65)]):
        board = _board(U1="A B C D GND")
        for at in holes:
            board.hole("Mech:Hole", at)
        board.place(board["U1"], centre=True, facing=Edge.TOP)
        told.append([p.text for p in board.solve().problems])
    assert told[0] == told[1] == ["U1 is over Hole at (112, 65)"]


def test_a_hole_is_called_by_where_it_is_to_the_nanometre():
    board = _board(Q1="A B")
    assert board.hole("Mech:Hole", (115.1234567, 65.7654321)).label == (
        "Hole at (115.123457, 65.765432)"
    )


def test_a_part_with_no_place_on_a_board_with_holes_is_told_they_are_among_what_it_avoids():
    board = _board(P1="A B C D", R1="B X")
    board.hole("Mech:Hole", (102, 52))
    board.place(board["P1"], against=Edge.BOTTOM)
    board.place(board["R1"], near=board["P1"], within=4 * mm, toward=Edge.BOTTOM)
    assert [p.text for p in board.solve().problems] == [
        "R1 has no place within 4 mm of P1, toward the bottom edge, that is on the front of "
        "the board and clear of the other parts and its holes"
    ]


def test_a_part_a_hair_outside_a_rounded_corner_is_outside_it():
    # Corners of 4 mm: 0.15 mm short of where the top edge runs straight, the arc is
    # 2.8 micrometres below the box. A test point touching the top of the box there is
    # that far outside the outline, and is said to be.
    board = _rounded(4, T1="A")
    board.place(board["T1"], against=Edge.TOP)
    board.place(board["T1"], against=Edge.LEFT, inset=4.35 * mm)
    (problem,) = board.solve().problems
    far = re.fullmatch(
        r"T1 does not fit on the board: it reaches ([\d.]+) mm outside the outline at "
        r"\(103.85 mm, 50 mm\)",
        problem.text,
    )
    assert far is not None and float(far[1]) == pytest.approx(0.0028, abs=0.0011)
    # Where the edge runs straight it is on the board.
    board = _rounded(4, T1="A")
    board.place(board["T1"], against=Edge.TOP)
    board.place(board["T1"], against=Edge.LEFT, inset=4.5 * mm)
    assert board.solve().ok


def test_a_part_in_a_notch_drawn_on_the_boards_edge_is_off_the_board():
    made = _board(R1="A B")
    board = Board(circuit=made.circuit, library=made.library)
    board.outline([{"type": "gr_rect", "start": (100, 50), "end": (130, 80)},
                   {"type": "gr_rect", "start": (100, 60), "end": (106, 70)}])  # fmt: skip
    board.place(board["R1"], against=Edge.LEFT)
    assert [p.text for p in board.solve().problems] == [
        "R1 does not fit on the board: it reaches 3.2 mm outside the outline at (101.8 mm, 66.8 mm)"
    ]


def _by(solution: Solution) -> dict[str, str]:
    """Which pin each part that looked for a place was put by."""
    return {line.split(":")[0]: line.partition(",")[0].split(" from ")[1]
            for line in solution.chosen if " from " in line}  # fmt: skip


def _supplied(**more: str) -> Board:
    """A module with two pins on VCC (1 and 3) and one on GND at the centre of the
    board, and three capacitors across VCC and GND, which the board says is ground."""
    board = _board(U1="VCC X VCC Y GND", R1="VCC GND", R2="VCC GND", R3="VCC GND", **more)
    board.ground("GND")
    board.place(board["U1"], centre=True, facing=Edge.TOP)
    return board


def test_capacitors_decouple_a_part_one_by_each_of_its_supply_pins():
    board = _supplied()
    board.decouple(board["U1"], board.parts("R1", "R2"), within=3 * mm)
    solution = board.solve()
    assert solution.problems == () and solution.free == ("R3",)
    assert [line.partition(",")[0].split(" from ")[1] for line in solution.chosen
            if " from " in line] == ["U1.1", "U1.3"]  # fmt: skip
    # Each has its own pad on the supply, pad 1, within the distance of its pin: pin 1
    # is at (111, 65), pin 3 at (119, 67). The pad on ground may be anywhere.
    for ref, pin in (("R1", (111.0, 65.0)), ("R2", (119.0, 67.0))):
        assert math.dist(_pads(board, solution, ref)["1"], pin) <= 3
    # Ground has fewer pins on it than the supply here, and that does not matter: the
    # board file said which is ground.
    assert len(board.net("GND").pins()) < len(board.net("VCC").pins())


def test_a_parts_decoupling_is_said_once_so_that_the_order_named_is_the_order():
    # Two statements for one part would leave which capacitor has the first pin to
    # which was written first, or where.
    board = _supplied()
    board.decouple(board["U1"], [board["R1"]], within=3 * mm)
    line = _line_no() - 1
    board.decouple(board["U1"], [board["R2"]], within=3 * mm)
    solution = board.solve()
    assert solution.poses == {} and _told(solution) == [
        f"U1: decoupling is decouple(U1, R1, within=3 mm) ({HERE}:{line}) and "
        f"decouple(U1, R2, within=3 mm) ({HERE}:{line + 2})"
    ]
    # The order named is the order of the pins: the other way round, the other pins.
    swapped = _supplied()
    swapped.decouple(swapped["U1"], swapped.parts("R2", "R1"), within=3 * mm)
    assert _by(swapped.solve()) == {"R2": "U1.1", "R1": "U1.3"}


def test_a_capacitor_with_no_pin_left_is_said_and_is_not_put_by_a_pin_that_has_one():
    board = _supplied()
    board.decouple(board["U1"], board.parts("R1..R3"), within=3 * mm)
    line = _line_no() - 1
    solution = board.solve()
    assert _told(solution) == [
        "decouple(U1, R1, R2, R3, within=3 mm): R3 has no pin of U1 on VCC left: R1 is by "
        f"U1.1 and R2 is by U1.3 ({HERE}:{line})"
    ]
    # It is asked for and not placed; the two with pins are.
    assert sorted(solution.poses) == ["R1", "R2", "U1"] and "R3" not in solution.free
    # The problem is the statement the board file wrote.
    assert solution.problems[0].statements == board.statements()[-1:]


def test_a_capacitor_that_is_not_across_ground_and_one_of_the_parts_supplies_is_said():
    board = _supplied(R4="V2 GND", R5="X Y", R6="GND GND", R7="VCC AGND")
    board.ground("AGND")
    board.decouple(board["U1"], board.parts("R1", "R4", "R5", "R6", "R7"), within=3 * mm)
    solution = board.solve()
    said = "decouple(U1, R1, R4, R5, R6, R7, within=3 mm)"
    assert [p.text for p in solution.problems] == [
        # On ground and a supply the module is not on: it is some other part's.
        f"{said}: R4 is across GND and V2, and U1 is not on V2",
        f"{said}: R5 is across X and Y, neither of them ground",
        f"{said}: R6 is across GND, not ground and one supply",
        # On a supply of the module's and a ground it is not on.
        f"{said}: R7 is across AGND and VCC, and U1 is not on AGND",
    ]
    assert sorted(solution.poses) == ["R1", "U1"]


def test_decoupling_needs_to_be_told_which_net_is_ground():
    board = _board(U1="VCC X VCC Y GND", R1="VCC GND")
    board.rails("VCC")
    board.place(board["U1"], centre=True, facing=Edge.TOP)
    board.decouple(board["U1"], [board["R1"]], within=3 * mm)
    assert [p.text for p in board.solve().problems] == [
        "decouple(U1, R1, within=3 mm): R1 is across GND and VCC, and no net is said to be "
        'ground: say which is, as in ground("GND")'
    ]
    # A ground is a rail, and is given back as the rails are.
    (gnd,) = board.ground("GND")
    assert gnd.is_ground and gnd.is_rail and not board.net("VCC").is_ground
    assert board.solve().problems == ()


def test_decoupling_does_not_depend_on_when_it_was_said_and_is_the_capacitors_one_place():
    def said(board: Board) -> list:
        return [decouple(board["U1"], board.parts("R1", "R2"), within=3 * mm),
                place(board["R3"], near=board["R1"], within=3 * mm)]  # fmt: skip

    first, second = _supplied(), _supplied()
    first.add(*said(first))
    second.add(*reversed(said(second)))
    solution = first.solve()
    assert solution.problems == () and solution == second.solve()
    # A capacitor that decouples a part and is put somewhere else as well is in two
    # places.
    board = _supplied()
    board.decouple(board["U1"], [board["R1"]], within=3 * mm)
    board.place(board["R1"], against=Edge.TOP)
    assert [p.text for p in board.solve().problems] == [
        "R1: near= is solved alone: one near=, and no against= or between= beside it"
    ]


def test_a_decoupling_capacitor_is_within_the_distance_said_of_its_pin_or_has_no_place():
    # Pin 1 is 1 mm inside the module's outline: nothing clear of the module is within
    # 0.3 mm of it.
    board = _supplied()
    said = board.decouple(board["U1"], [board["R1"]], within=0.3 * mm)
    line = _line_no() - 1
    solution = board.solve()
    assert _told(solution) == [
        "R1 has no place within 0.3 mm of U1.1 that is on the front of the board and clear "
        f"of the other parts ({HERE}:{line})"
    ]
    # The problem is of the statement the board file wrote, not of what was made of it.
    assert solution.problems[0].statements == (said,)


def test_capacitors_take_a_parts_pins_in_the_order_of_their_numbers():
    # The chip's footprint lists pad 10 before pad 2, and "10" sorts before "2" as
    # text. The first capacitor named has pin 2.
    cap = {"value": "100n", "footprint": "Device:R", "pads": {"1": "VCC", "2": "GND"}}
    listed = [{"ref": "Z1", "value": "Z1", "footprint": "Chip:Z",
               "pads": {"10": "VCC", "2": "VCC", "3": "GND"}},
              {"ref": "R1", **cap}, {"ref": "R2", **cap}]  # fmt: skip
    board = Board(circuit=Circuit({"parts": listed, "nets": ["GND", "VCC"]}),
                  library=dict(LIBRARY), extent=(100.0, 50.0, 130.0, 80.0))  # fmt: skip
    assert [p.number for p in board["Z1"].pins()] == ["10", "2", "3"]
    board.ground("GND")
    board.place(board["Z1"], centre=True, facing=Edge.TOP)
    board.decouple(board["Z1"], board.parts("R1", "R2"), within=4 * mm)
    solution = board.solve()
    assert solution.problems == () and _by(solution) == {"R1": "Z1.2", "R2": "Z1.10"}


def _apart(inset: float, *, rules: bool = True, nets: str = "A B") -> Board:
    """Two test points against the left edge, each a pad 1 mm square and nothing else:
    the first 1 mm in, the second *inset* mm in, so 2 mm is touching."""
    one, two = nets.split()
    board = _board(T1=one, T2=two)
    board.place(board["T1"], against=Edge.LEFT, inset=1 * mm)
    board.place(board["T2"], against=Edge.LEFT, inset=inset * mm)
    if rules:
        board.rules(track=0.25 * mm, clearance=0.2 * mm)
    return board


def test_pads_on_different_nets_closer_than_the_rules_say_are_a_problem():
    solution = _apart(2.1).solve()
    (problem,) = solution.problems
    assert problem.text == "T1.1 is 0.1 mm from T2.1, and the rules keep copper 0.2 mm apart"
    assert problem.parts == ("T1", "T2")
    # It is about both places and the rules, any of which could be what changes.
    assert [str(s) for s in problem.statements] == [
        "place(T1, against=Edge.LEFT, inset=1 mm)",
        "place(T2, against=Edge.LEFT, inset=2.1 mm)",
        "rules(track=0.25 mm, clearance=0.2 mm, edge=0.5 mm)",
    ]
    # Touching is closer than the rules say too, and as far apart as they say is not.
    assert [p.text for p in _apart(2.0).solve().problems] == [
        "T1.1 is 0 mm from T2.1, and the rules keep copper 0.2 mm apart"
    ]
    assert _apart(2.2).solve().problems == ()


def test_pads_may_be_as_close_as_they_like_on_one_net_or_on_a_board_with_no_rules():
    assert _apart(2.1, nets="A A").solve().problems == ()
    assert _apart(2.1, rules=False).solve().problems == ()


def test_a_part_that_looks_for_its_place_keeps_its_pads_as_far_off_as_the_rules_say():
    def gap(rules: bool, nets: str) -> float:
        one, two = nets.split()
        board = _board(T1=one, T2=two)
        board.place(board["T1"], centre=True)
        board.place(board["T2"], near=board["T1"], within=3 * mm)
        if rules:
            board.rules(track=0.25 * mm, clearance=0.2 * mm)
        solution = board.solve()
        assert solution.problems == ()
        (x1, y1), (x2, y2) = _pads(board, solution, "T1")["1"], _pads(board, solution, "T2")["1"]
        return round(math.dist((x1, y1), (x2, y2)) - 1, 6)  # each pad is 1 mm square

    assert gap(False, "A B") == 0  # touching, as two parts may
    assert gap(True, "A B") == 0.2
    assert gap(True, "A A") == 0


def test_a_hole_of_a_part_is_kept_as_far_from_another_parts_pad_as_the_rules_say():
    board = _board(H1="", T1="A")
    # The hole is 2 mm across with its middle 2 mm in, and the pad 1 mm square with its
    # middle 3.6 mm in: 0.1 mm between them.
    board.place(board["H1"], against=Edge.LEFT, inset=2 * mm)
    board.place(board["T1"], against=Edge.LEFT, inset=3.6 * mm)
    board.rules(track=0.25 * mm, clearance=0.2 * mm)
    assert [p.text for p in board.solve().problems] == [
        "a hole of H1 is 0.1 mm from T1.1, and the rules keep copper 0.2 mm apart"
    ]


def _ruled(**parts: str) -> Board:
    board = _board(**parts)
    board.rules(track=0.25 * mm, clearance=0.2 * mm)  # and copper 0.5 mm from the edge
    return board


@pytest.mark.parametrize(
    ("edge", "at"),
    [(Edge.LEFT, (101.0, 65.0)), (Edge.RIGHT, (129.0, 65.0)),
     (Edge.TOP, (115.0, 51.0)), (Edge.BOTTOM, (115.0, 79.0))],
)  # fmt: skip
def test_against_an_edge_is_as_near_it_as_the_rules_let_the_parts_copper_be(edge, at):
    # A test point is a pad 1 mm square and nothing else: on the edge, its copper is.
    board = _ruled(T1="A")
    board.place(board["T1"], against=edge)
    solution = board.solve()
    assert solution.problems == () and _pads(board, solution, "T1") == {"1": at}
    said = f"T1: 0.5 mm in from the {edge.value} edge, to keep its copper 0.5 mm from it"
    assert said in solution.chosen
    # A resistor's courtyard reaches 0.3 mm past its pads, so it comes in 0.2 mm.
    board = _ruled(R1="A B")
    board.place(board["R1"], against=edge)
    said = f"R1: 0.2 mm in from the {edge.value} edge, to keep its copper 0.5 mm from it"
    assert said in board.solve().chosen


def test_a_board_with_no_rules_has_a_part_against_an_edge_on_the_edge():
    board = _board(T1="A")
    board.place(board["T1"], against=Edge.LEFT)
    solution = board.solve()
    assert _pads(board, solution, "T1") == {"1": (100.5, 65.0)}
    assert solution.chosen[0] == "T1: centred along the left edge"


def test_copper_nearer_the_edge_than_the_rules_say_is_a_problem_where_an_inset_puts_it():
    board = _ruled(T1="A")
    board.place(board["T1"], against=Edge.LEFT, inset=0.7 * mm)  # its pad from 0.2 mm in
    (problem,) = board.solve().problems
    assert problem.text == (
        "T1.1 is 0.2 mm from the board's edge, and the rules keep copper 0.5 mm from it"
    )
    assert [str(s) for s in problem.statements] == [
        "place(T1, against=Edge.LEFT, inset=0.7 mm)",
        "rules(track=0.25 mm, clearance=0.2 mm, edge=0.5 mm)",
    ]
    board = _ruled(T1="A")
    board.place(board["T1"], against=Edge.LEFT, inset=1 * mm)
    assert board.solve().problems == ()


def test_a_part_that_looks_for_its_place_keeps_its_copper_from_the_edge():
    def above(ruled: bool) -> Solution:
        # T1's pad is from 1.2 mm in from the top edge: room for a pad 1 mm square
        # between it and the edge, and not for one 0.5 mm from the edge.
        board = _ruled(T1="A", T2="A") if ruled else _board(T1="A", T2="A")
        board.place(board["T1"], against=Edge.TOP, inset=1.7 * mm)
        board.place(board["T2"], near=board["T1"], within=3 * mm, toward=Edge.TOP)
        return board.solve()

    assert above(False).problems == () and "T2" in above(False).poses
    (problem,) = above(True).problems
    assert problem.text.startswith("T2 has no place within 3 mm of T1, toward the top edge,")


def test_a_footprint_with_no_courtyard_or_fabrication_drawing_has_its_body_on_the_silk():
    def drawn(layer: str, x: float, y: float) -> str:
        return (f"(fp_rect (start {-x} {-y}) (end {x} {y}) (stroke (width 0.1) (type solid)) "
                f'(fill no) (layer "{layer}"))')  # fmt: skip

    pad = _smd(1, 0, 0, 1, 1)

    def mm_box(fp: Node) -> tuple[float, ...]:
        return tuple(v / 1_000_000 for v in _shape(fp).box)

    # An older footprint draws its housing on the silk and nowhere else.
    assert mm_box(_footprint("S", drawn("F.SilkS", 3, 2), pad)) == (-3, -2, 3, 2)
    # One with a courtyard is its courtyard, whatever its silk shows.
    both = drawn("F.SilkS", 3, 2) + " " + drawn("F.CrtYd", 1, 1)
    assert mm_box(_footprint("S", both, pad)) == (-1, -1, 1, 1)
    # Text is not a drawing of the part: a value written on the fabrication layer does
    # not make that layer the body's.
    text = '(fp_text value "x" (at 9 9) (layer "F.Fab"))'
    assert mm_box(_footprint("S", text + " " + drawn("F.SilkS", 3, 2), pad)) == (-3, -2, 3, 2)
    assert mm_box(_footprint("S", text, pad)) == (-0.5, -0.5, 0.5, 0.5)


def test_a_placed_parts_outline_is_where_the_part_is_now():
    board = _board(T1="A")
    solver = _Solver(board.circuit, board.library, (100.0, 50.0, 130.0, 80.0), [])
    solver.poses["T1"] = Pose(110 * mm, 60 * mm)
    assert solver._box("T1") == (109_500_000, 59_500_000, 110_500_000, 60_500_000)
    # Asked again once the part has moved, as it is between one pass and the next.
    solver.poses["T1"] = Pose(120 * mm, 60 * mm)
    assert solver._box("T1") == (119_500_000, 59_500_000, 120_500_000, 60_500_000)


def _moved_in(solution: Solution) -> list[str]:
    return [line for line in solution.chosen if " in from " in line]


def test_a_part_is_said_to_be_in_from_an_edge_only_where_it_ends_up_in_from_it():
    # The module's pads are by the side that is down in its footprint, and its drawing
    # reaches 4 mm above them. Turned either way against the top edge, only one way
    # has copper at the edge, and it is the other way that is taken.
    board = _ruled(U1="A B C D E")
    board.place(board["U1"], against=Edge.TOP)
    solution = board.solve()
    assert solution.poses["U1"].rot == 0 and _moved_in(solution) == []
    # Turned the way that has, it is moved in and said to be.
    board = _ruled(U1="A B C D E")
    board.place(board["U1"], against=Edge.TOP, facing=Edge.BOTTOM)
    assert _moved_in(board.solve()) == [
        "U1: 0.5 mm in from the top edge, to keep its copper 0.5 mm from it"
    ]
    # A part that is not placed is not said to be anywhere.
    board = _ruled(T1="A")
    board.place(board["T1"], against=Edge.LEFT)
    board.place(board["T1"], centre=True)
    solution = board.solve()
    assert solution.poses == {} and solution.chosen == ()


def test_by_a_slanted_edge_copper_is_as_far_from_it_as_it_is_and_not_as_its_box_is():
    def by_the_corner(inset: float) -> list[str]:
        # The board's top right corner is cut off at 45 degrees, 6 mm along each edge.
        made = _board(T1="A")
        board = Board(circuit=made.circuit, library=made.library)
        corners = [(100, 50), (124, 50), (130, 56), (130, 80), (100, 80)]
        board.outline({"type": "gr_line", "start": a, "end": b}
                      for a, b in zip(corners, corners[1:] + corners[:1], strict=True))  # fmt: skip
        board.rules(track=0.25 * mm, clearance=0.2 * mm)
        board.place(board["T1"], against=Edge.TOP, inset=inset * mm)
        board.place(board["T1"], against=Edge.RIGHT, inset=inset * mm)
        return [p.text for p in board.solve().problems]

    # The pad's corner is 0.566 mm from the cut: the box 0.5 mm around the pad reaches
    # past the cut, and the pad is still further from it than the rules ask.
    assert by_the_corner(3.9) == []
    assert by_the_corner(3.8) == [
        "T1.1 is 0.424264 mm from the board's edge, and the rules keep copper 0.5 mm from it"
    ]


def test_a_hole_of_a_part_too_near_the_edge_is_called_a_hole():
    board = _ruled(H1="")
    board.place(board["H1"], against=Edge.LEFT, inset=1.2 * mm)  # 2 mm across
    assert [p.text for p in board.solve().problems] == [
        "a hole of H1 is 0.2 mm from the board's edge, and the rules keep copper 0.5 mm from it"
    ]
