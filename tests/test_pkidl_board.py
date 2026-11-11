"""pkidl.Board.pour: a net's pour by intent, the whole board or around its pads."""

import pytest

from pkidl.board import Board
from pkidl.sexpr import find, find_all, parse

PART = """(footprint "R" (at {x} {y}) (property "Reference" "{ref}")
  (pad "1" smd rect (at 0 0) (size 1 2) (layers "F.Cu") (net "VS"))
  (pad "2" smd rect (at 3 0) (size 1 1) (layers "F.Cu") (net "GND")))"""


def _outline(board: Board) -> list[tuple[float, float]]:
    zone = board.items[-1]
    pts = find(find(zone, "polygon"), "pts")  # type: ignore[arg-type]
    return [(float(p[1]), float(p[2])) for p in find_all(pts, "xy")]  # type: ignore[arg-type]


def test_a_pour_with_nothing_around_covers_the_board():
    board = Board()
    board.outline_rounded_rect(0, 0, 40, 30, 2)
    board.pour("GND", "B.Cu", solid=True)
    assert _outline(board) == [(0, 0), (40, 0), (40, 30), (0, 30)]
    assert find(board.items[-1], "layer") == ["layer", "B.Cu"]


def test_a_whole_board_pour_needs_the_outline_first():
    with pytest.raises(ValueError, match="outline"):
        Board().pour("GND", "B.Cu")


def test_a_pour_around_parts_hulls_its_nets_pads_grown_by_the_margin():
    parts = [parse(PART.format(x=10, y=10, ref="R1")), parse(PART.format(x=20, y=14, ref="R2"))]
    board = Board()
    board.pour("VS", "F.Cu", around=parts, margin=0.5)
    # Each VS pad, 1 x 2, is a 2 x 2 square grown to 3 x 3: about (10, 10) and (20, 14).
    assert sorted(_outline(board)) == sorted(
        [(8.5, 8.5), (11.5, 8.5), (21.5, 12.5), (21.5, 15.5), (18.5, 15.5), (8.5, 11.5)]
    )


def test_a_pour_around_parts_without_the_net_says_so():
    with pytest.raises(ValueError, match="no pad on net 'OUT1'"):
        Board().pour("OUT1", "F.Cu", around=[parse(PART.format(x=0, y=0, ref="R1"))])
