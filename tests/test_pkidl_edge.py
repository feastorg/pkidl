"""pkidl.edge: the area inside a board's outline, from the items it is drawn with."""

import math

import pytest

from pkidl import Board
from pkidl.edge import ARC, shape


def _line(a: tuple[float, float], b: tuple[float, float]) -> dict:
    return {"type": "gr_line", "start": list(a), "end": list(b)}


SQUARE = [_line((0, 0), (10, 0)), _line((10, 0), (10, 10)), _line((10, 10), (0, 10)),
          _line((0, 10), (0, 0))]  # fmt: skip


def test_lines_that_meet_end_to_end_enclose_their_area_in_whatever_order_they_are_drawn():
    assert shape(SQUARE).equals(shape(reversed(SQUARE)))
    assert shape(SQUARE).bounds == (0, 0, 10, 10) and shape(SQUARE).area == 100
    # An L: the box around it is not the board.
    corners = [(0, 0), (10, 0), (10, 4), (4, 4), (4, 10), (0, 10)]
    ell = [_line(a, b) for a, b in zip(corners, corners[1:] + corners[:1], strict=True)]
    assert shape(ell).area == 64 and shape(ell).bounds == (0, 0, 10, 10)


def test_an_arc_is_followed_to_within_a_micrometre_whichever_way_it_goes_round():
    # A 40 by 30 mm board with 4 mm corners: the box less what four quarter circles
    # leave of four 4 mm squares.
    board = Board()
    board.outline_rounded_rect(0, 0, 40, 30, 4)
    edge = board.edge()
    assert edge is not None and edge.bounds == pytest.approx((0, 0, 40, 30))
    exact = 40 * 30 - (16 - math.pi * 4) * 4
    # The lines standing in for the arcs are inside them, so the area is a little less.
    assert exact - 4 * math.tau * 4 * ARC < edge.area <= exact
    # The same corner drawn from its other end is the same corner.
    a, m, b = (0.0, 4.0), (4 - 4 * math.sqrt(0.5), 4 - 4 * math.sqrt(0.5)), (4.0, 0.0)
    rest = [_line((4, 0), (10, 0)), _line((10, 0), (10, 10)), _line((10, 10), (0, 10)),
            _line((0, 10), (0, 4))]  # fmt: skip
    one = shape([{"type": "gr_arc", "start": a, "mid": m, "end": b}, *rest])
    other = shape([{"type": "gr_arc", "start": b, "mid": m, "end": a}, *rest])
    assert (
        one.area == pytest.approx(other.area) == pytest.approx(100 - (16 - math.pi * 4), abs=0.01)
    )
    assert not one.contains(shape([_line((0, 0), (1, 0)), _line((1, 0), (0, 1)),
                                   _line((0, 1), (0, 0))]).centroid)  # fmt: skip


def test_a_rectangle_a_circle_and_a_polygon_are_each_an_outline():
    assert shape([{"type": "gr_rect", "start": [1, 2], "end": [11, 7]}]).bounds == (1, 2, 11, 7)
    round_board = shape([{"type": "gr_circle", "center": [5, 5], "end": [10, 5]}])
    assert round_board.area == pytest.approx(math.pi * 25, rel=1e-3)
    assert round_board.bounds == pytest.approx((0, 0, 10, 10), abs=ARC)
    kite = shape([{"type": "gr_poly", "pts": [[0, 5], [5, 0], [10, 5], [5, 10]]}])
    assert kite.area == 50


def test_a_cut_out_drawn_inside_the_outline_is_a_hole_in_the_board():
    slot = {"type": "gr_rect", "start": [4, 4], "end": [6, 6]}
    board = shape([*SQUARE, slot])
    assert board.area == 96 and len(board.interiors) == 1
    assert not board.contains(shape([slot]).centroid)
    # A frame: the cut-out is most of the box, and is still what is cut out.
    frame = shape([*SQUARE, {"type": "gr_rect", "start": [1, 1], "end": [9, 9]}])
    assert frame.area == 36 and frame.bounds == (0, 0, 10, 10)


def test_a_line_that_closes_nothing_is_ignored_within_the_box_around_the_board():
    # Real outlines have stubs where an edge is drawn on past a rounded corner.
    assert shape([*SQUARE, _line((10, 4), (10, 4.5))]).area == 100
    assert shape([*SQUARE, _line((4, 4), (5, 5))]).area == 100


@pytest.mark.parametrize(
    ("items", "message"),
    [
        (SQUARE[:3], "the outline does not close: its items do not meet end to end"),
        ([], "the outline does not close: its items do not meet end to end"),
        ([{"type": "gr_text", "start": [0, 0]}],
         "outline: 'gr_text' is not something Edge.Cuts is drawn with"),
        # Three sides of the board and a slot in it: the slot is not the board.
        ([*SQUARE[:3], {"type": "gr_rect", "start": [4, 4], "end": [6, 6]}],
         "the outline does not close: its items do not meet end to end"),
        ([*SQUARE, _line((10, 10), (12, 12))],
         "the outline does not close: its items do not meet end to end"),
        ([*SQUARE, {"type": "gr_rect", "start": [20, 0], "end": [30, 10]}],
         "the outline encloses 2 areas apart from each other, not one board"),
        # An island in a cut-out is a second board, and so are the halves of a bow-tie.
        ([*SQUARE, {"type": "gr_rect", "start": [1, 1], "end": [9, 9]},
          {"type": "gr_rect", "start": [4, 4], "end": [6, 6]}],
         "the outline encloses 2 areas apart from each other, not one board"),
        ([_line((0, 0), (10, 10)), _line((10, 10), (10, 0)), _line((10, 0), (0, 10)),
          _line((0, 10), (0, 0))],
         "the outline encloses 2 areas apart from each other, not one board"),
    ],
)  # fmt: skip
def test_an_outline_that_does_not_close_is_refused(items, message):
    with pytest.raises(ValueError) as e:
        shape(items)
    assert str(e.value) == message


def test_a_board_knows_its_edge_once_its_outline_is_drawn():
    assert Board(extent=(0.0, 0.0, 10.0, 10.0)).edge() is None
    board = Board()
    board.outline(SQUARE)
    edge = board.edge()
    assert edge is not None and edge.equals(shape(SQUARE)) and board.extent == (0, 0, 10, 10)


def test_a_board_whose_outline_is_not_one_board_has_that_as_its_problem_and_places_nothing():
    board = Board()
    board.outline(SQUARE[:3])
    solution = board.solve()
    assert solution.poses == {} and not solution.ok
    assert [p.text for p in solution.problems] == [
        "the outline does not close: its items do not meet end to end"
    ]
