"""pkidl.placement: where each part goes, worked out from what a board file said.

Where a pad ends up is read back through ``pkidl.footprint.place``, which is what puts a
footprint on a board, and not from the solver's own arithmetic.
"""

import math
import random
import sys

import pytest

from pkidl import Board, Edge, Side, align, mm, place
from pkidl.circuit import Circuit
from pkidl.footprint import Placement, pad_xy, pads
from pkidl.footprint import place as put
from pkidl.placement import Pose, Problem, Solution
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
          "N": "Mech:Nothing"}  # fmt: skip


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
    line = _line_no() - 1
    solution = board.solve()
    # Against the left edge its pad 1 is at x = 101; between the headers, at 111.
    assert _told(solution) == [
        f"U1 is put in two places 10 mm apart across the board ({HERE}:{line}, {HERE}:{line - 1})"
    ]
    assert set(solution.poses) == {"P1", "P2"} and solution.free == ()
    assert solution.problems[0].statements == (board.statements()[3], board.statements()[2])


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
    """A module between two headers with a strap on each side of it, as statements not
    yet added to the board."""
    board = _board(P1="A B VCC GND", P2="C D VCC GND", U1="A B D C GND", R1="VCC A", R2="VCC C")
    board.rails("VCC", "GND")
    p1, p2, u1, r1, r2 = board.parts("P1", "P2", "U1", "R1", "R2")
    said = [
        place(p1, against=Edge.LEFT, inset=2 * mm),
        place(p2, against=Edge.RIGHT, inset=2 * mm),
        align(p1, p2, grid=2 * mm),
        place(u1, between=(p1, p2), facing=Edge.TOP),
        place(r1, near=u1.pin_on(r1.signal_net), within=3 * mm, side="back"),
        place(r2, near=u1.pin_on(r2.signal_net), within=3 * mm),
        place(r2, side=Side.BACK),
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
                   solution.chosen))  # fmt: skip
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
    # is on a half nanometre: 15.5 mm from the left edge, as near as can be said.
    board.place(board["R1"], between=(board["FID1"], board["FID2"]), against=Edge.LEFT,
                inset=15.5 * mm)  # fmt: skip
    solution = board.solve()
    assert solution.ok, _told(solution)
    assert _pads(board, solution, "R1")["1"][0] == pytest.approx(115.5, abs=1e-6)


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
