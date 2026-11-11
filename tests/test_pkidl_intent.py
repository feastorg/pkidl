"""pkidl.intent: what a board file says about the layout, as statements that are values,
added to a board and read together."""

# The refusals below are of arguments of the wrong type, written on purpose.
# pyright: reportArgumentType=false

import dataclasses
import itertools
import sys
from pathlib import Path

import pytest

import pkidl
from pkidl import Board, Edge, Side, align, inch, keepout, mil, mm, place
from pkidl.circuit import Circuit
from pkidl.intent import Align, Keepout, Place, canonical, conflicts
from pkidl.sexpr import dumps

HERE = "test_pkidl_intent.py"

# A module between two headers, with two straps on its pins.
DATA = {
    "parts": [
        {"ref": "P1", "value": "HDR", "footprint": "Conn:H", "pads": {"1": "A", "2": "GND"}},
        {"ref": "P2", "value": "HDR", "footprint": "Conn:H", "pads": {"1": "B", "2": "VCC"}},
        {"ref": "R1", "value": "10k", "footprint": "Device:R", "pads": {"1": "VCC", "2": "A"}},
        {"ref": "R2", "value": "10k", "footprint": "Device:R", "pads": {"1": "VCC", "2": "B"}},
        {"ref": "U1", "value": "MOD", "footprint": "RF:M",
         "pads": {"1": "A", "2": "B", "3": "VCC", "4": "GND"}},
    ],
    "nets": ["A", "B", "GND", "VCC"],
}  # fmt: skip


@pytest.fixture
def board() -> Board:
    return Board(circuit=Circuit(DATA))


def _line() -> int:
    """The line this is called on; the statement above it is on ``_line() - 1``."""
    return sys._getframe(1).f_lineno


def test_a_statement_is_a_value_whatever_line_and_units_it_was_written_in(board):
    p1 = board["P1"]
    a = place(p1, against=Edge.LEFT, inset=1.27 * mm)
    b = place(p1, against=Edge.LEFT, inset="1.27mm")
    c = place(Circuit(DATA).part("P1"), inset=50 * mil, against=Edge.LEFT)
    assert a == b == c and len({a, b, c}) == 1
    assert a != place(p1, against=Edge.LEFT, inset=1.28 * mm)
    assert a != place(p1, against=Edge.RIGHT, inset=1.27 * mm)
    assert a != place(board["P2"], against=Edge.LEFT, inset=1.27 * mm)
    assert str(a) == "place(P1, against=Edge.LEFT, inset=1.27 mm)"
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.inset = 2 * mm  # pyright: ignore[reportAttributeAccessIssue]


def test_a_statement_records_the_line_that_wrote_it(board):
    s, line = place(board["P1"], against=Edge.LEFT), _line()
    assert s.source is not None
    assert (s.source.file, s.source.line, str(s.source)) == (__file__, line, f"{HERE}:{line}")
    on_board, line = board.place(board["P2"], against=Edge.RIGHT), _line()
    assert str(on_board.source) == f"{HERE}:{line}"
    aligned, line = board.align(board["P1"], board["P2"], grid=0.1 * inch), _line()
    assert str(aligned.source) == f"{HERE}:{line}"
    assert str(align(board["P1"], board["P2"], grid="0.1in").source) == f"{HERE}:{_line()}"


def test_a_board_file_beside_pkidl_is_not_taken_for_pkidl(board):
    # A directory whose name starts as pkidl's does: src/pkidl_boards/ beside src/pkidl/.
    beside = str(Path(pkidl.__file__).parent) + "_boards/board.py"
    scope = {"place": place, "p1": board["P1"], "Edge": Edge}
    exec(compile("\n\ns = place(p1, against=Edge.LEFT)", beside, "exec"), scope)
    assert (scope["s"].source.file, scope["s"].source.line) == (beside, 3)


def test_a_block_is_a_function_whose_statements_say_where_in_it_they_were_written(board):
    def strap(r, u):
        return [place(r, near=u.pin_on(r.nets()[1]), within=3 * mm)]  # the line recorded

    written = strap.__code__.co_firstlineno + 1
    added = board.add(*strap(board["R1"], board["U1"]), *strap(board["R2"], board["U1"]))
    assert [str(s) for s in added] == ["place(R1, near=U1.1, within=3 mm)",
                                       "place(R2, near=U1.2, within=3 mm)"]  # fmt: skip
    assert [s.source and s.source.line for s in added] == [written, written]
    assert board.statements() == added


def test_placing_gives_the_statement_back_and_moves_nothing(board):
    before = dumps(board.sexpr())
    s = board.place(board["U1"], between=(board["P1"], board["P2"]), facing=Edge.TOP)
    assert isinstance(s, Place) and (s.part, s.facing) == (board["U1"], Edge.TOP)
    a = board.align(board["P1"], board["P2"], grid=0.1 * inch)
    assert isinstance(a, Align) and a.grid == 2.54 * mm
    assert board.statements() == (s, a)
    assert dumps(board.sexpr()) == before and board.items == []


def test_the_same_thing_said_twice_is_said_once(board):
    first = board.place(board["P1"], against=Edge.LEFT, inset=1.27 * mm)
    again = board.place(board["P1"], against=Edge.LEFT, inset=50 * mil)
    assert again == first and again.source != first.source
    assert board.statements() == (first,) and board.statements()[0].source == first.source
    assert board.conflicts() == ()


def test_what_is_said_about_a_part_is_found_by_the_part(board):
    p1, p2, r1, r2, u1 = board.parts()
    left = board.place(p1, against=Edge.LEFT)
    middle = board.place(u1, between=(p1, p2))
    strap = board.place(r1, near=u1.pin(1), within=3 * mm)
    beside = board.place(r2, near=r1, within=2 * mm)
    grid = board.align(p1, p2, grid=0.1 * inch)
    assert board.statements(about=p1) == board.statements(about="P1") == (left, middle, grid)
    assert board.statements(about=u1) == (middle, strap)
    assert board.statements(about=r1) == (strap, beside)
    assert board.statements(about=r2) == (beside,)
    with pytest.raises(LookupError, match="no part 'R9'"):
        board.statements(about="R9")


def test_a_statement_about_something_the_board_has_not_got_is_refused_whole(board):
    other = Circuit({"parts": [{"ref": "R9", "value": "1k", "footprint": "Device:R",
                                "pads": {"1": "X"}},
                               {"ref": "U1", "value": "MOD", "footprint": "RF:M",
                                "pads": {"9": "X"}}],
                     "nets": ["X"]})  # fmt: skip
    good = place(board["P1"], against=Edge.LEFT)
    with pytest.raises(LookupError, match=r"place\(R9, against=Edge.TOP\): no part 'R9'"):
        board.add(good, place(other.part("R9"), against=Edge.TOP))
    with pytest.raises(LookupError, match=r"place\(P1, near=R9, within=1 mm\): no part 'R9'"):
        board.add(place(board["P1"], near=other.part("R9"), within=mm))
    with pytest.raises(LookupError, match=r"place\(R1, near=U1.9, .*\): U1 has no pin 9"):
        board.add(place(board["R1"], near=other.part("U1").pin(9), within=mm))
    with pytest.raises(LookupError, match=r"align\(P1, R9, grid=2.54 mm\): no part 'R9'"):
        board.add(align(board["P1"], other.part("R9"), grid=0.1 * inch))
    with pytest.raises(TypeError, match=r"add\(\) takes statements, such as place\(...\), not \["):
        board.add([good])  # pyright: ignore[reportArgumentType]
    assert board.statements() == ()


@pytest.mark.parametrize(
    ("said", "error", "message"),
    [
        (lambda b: place(b["U1"]), ValueError,
         r"place\(U1\) does not say where: give against=, between=, facing=, near= or side="),
        (lambda b: place(b["U1"], facing=Edge.TOP, inset=mm), ValueError,
         "U1: inset= is measured from an edge"),
        (lambda b: place(b["U1"], against=Edge.TOP, inset=-mm), ValueError,
         "U1: inset= -1 mm is outside the board"),
        (lambda b: place(b["R1"], near=b["U1"]), ValueError, "R1: near= and within= go together"),
        (lambda b: place(b["R1"], against=Edge.TOP, within=mm), ValueError,
         "R1: near= and within= go together"),
        (lambda b: place(b["R1"], near=b["U1"], within=0 * mm), ValueError,
         "R1: within= 0 mm leaves no room"),
        (lambda b: place(b["U1"], near=b["U1"], within=mm), ValueError,
         "U1: near= U1 is the part itself"),
        (lambda b: place(b["U1"], near=b["U1"].pin(2), within=mm), ValueError,
         "U1: near= U1.2 is the part itself"),
        (lambda b: place(b["U1"], between=(b["P1"], b["P1"])), ValueError,
         "U1: between= takes two other parts, not P1 and P1"),
        (lambda b: place(b["U1"], between=(b["U1"], b["P1"])), ValueError,
         "U1: between= takes two other parts, not U1 and P1"),
        (lambda b: place(b["U1"], between=(b["P1"], b["P2"], b["R1"])), TypeError,
         "U1: between= takes two parts"),
        (lambda b: place(b["U1"], between=("P1", "P2")), TypeError, "U1: between= takes two parts"),
        (lambda b: place(b["U1"], against="left"), TypeError,
         "U1: against= takes an edge, such as Edge.LEFT, not 'left'"),
        (lambda b: place(b["U1"], facing="top"), TypeError, "U1: facing= takes an edge"),
        (lambda b: place(b["U1"], side="under"), TypeError,
         "U1: side= takes Side.FRONT or Side.BACK, not 'under'"),
        (lambda b: place(b["U1"], side=Edge.TOP), TypeError,
         "U1: side= takes Side.FRONT or Side.BACK, not <Edge.TOP"),
        (lambda b: place(b["R1"], near="U1", within=mm), TypeError,
         "R1: near= takes a part or a pin, not 'U1'"),
        (lambda b: place("U1", against=Edge.TOP), TypeError,
         r"place\(\) takes a part, such as board\[\"U1\"\], not 'U1'"),
        (lambda b: place(b["U1"], against=Edge.TOP, inset=1.27), TypeError, "1.27 has no unit"),
        (lambda b: place(b["R1"], near=b["U1"], within=3), TypeError, "3 has no unit"),
        (lambda b: align(b["P1"], grid=mm), ValueError, r"align\(\) takes two parts or more"),
        (lambda b: align(b["P1"], b["P1"], grid=mm), ValueError, "takes two parts or more"),
        (lambda b: align(b["P1"], b["P2"], grid=0 * mm), ValueError, "grid= 0 mm is not a step"),
        (lambda b: align(b["P1"], "P2", grid=mm), TypeError, r"align\(\) takes parts"),
        (lambda b: align(b["P1"], b["P2"], grid=2.54), TypeError, "2.54 has no unit"),
    ],
)  # fmt: skip
def test_a_statement_that_does_not_say_one_thing_clearly_is_refused(board, said, error, message):
    with pytest.raises(error, match=message):
        said(board)


def test_between_and_align_do_not_depend_on_the_order_their_parts_are_named(board):
    p1, p2, _, _, u1 = board.parts()
    assert place(u1, between=(p2, p1)) == place(u1, between=(p1, p2))
    assert place(u1, between=(p2, p1)).between == (p1, p2)
    assert align(p2, u1, p1, p2, grid=mm) == align(p1, p2, u1, grid=mm)
    assert align(p2, u1, p1, grid=mm).parts == (p1, p2, u1)


def test_a_statement_is_plain_data(board):
    p1, p2, r1, _, u1 = board.parts()
    assert place(p1, against=Edge.LEFT, inset=1.27 * mm).data() == {
        "place": "P1", "against": "left", "inset": 1_270_000}  # fmt: skip
    assert place(u1, between=(p2, p1), facing=Edge.TOP).data() == {
        "place": "U1", "between": ["P1", "P2"], "facing": "top"}  # fmt: skip
    assert place(r1, near=u1.pin(1), within="3mm").data() == {
        "place": "R1", "near": "U1.1", "within": 3_000_000}  # fmt: skip
    assert place(r1, near=u1, within="3mm").data() == {
        "place": "R1", "near": "U1", "within": 3_000_000}  # fmt: skip
    assert align(p2, p1, grid=0.1 * inch).data() == {"align": ["P1", "P2"], "grid": 2_540_000}


def test_one_aspect_given_two_ways_is_a_conflict_naming_both_lines(board):
    p1, _, r1, _, u1 = board.parts()
    board.place(p1, against=Edge.LEFT, inset=1.27 * mm)
    a = _line() - 1
    board.place(p1, against=Edge.TOP)  # a corner: another edge is another aspect
    board.place(p1, against=Edge.LEFT, inset=2.54 * mm)
    b = _line() - 1
    board.place(u1, facing=Edge.TOP)
    c = _line() - 1
    board.place(u1, facing=Edge.BOTTOM, against=Edge.TOP)
    d = _line() - 1
    board.place(r1, near=u1.pin(1), within=3 * mm)
    e = _line() - 1
    board.place(r1, near=u1.pin(2), within=5 * mm)  # another pin is another aspect
    board.place(r1, near=u1.pin(1), within=2 * mm)
    f = _line() - 1
    assert [str(x) for x in board.conflicts()] == [
        f"P1: inset from the left edge is 1.27 mm ({HERE}:{a}) and 2.54 mm ({HERE}:{b})",
        f"R1: distance from U1.1 is 3 mm ({HERE}:{e}) and 2 mm ({HERE}:{f})",
        f"U1: facing is the top edge ({HERE}:{c}) and the bottom edge ({HERE}:{d})",
    ]
    first = board.conflicts()[0]
    assert (first.part, first.aspect) == ("P1", "inset from the left edge")
    assert (first.first, first.second) == (board.statements()[0], board.statements()[2])


def test_an_inset_given_and_an_inset_left_out_are_two_things(board):
    board.place(board["P1"], against=Edge.LEFT)
    a = _line() - 1
    board.place(board["P1"], against=Edge.LEFT, inset=mm)
    b = _line() - 1
    assert [str(x) for x in board.conflicts()] == [
        f"P1: inset from the left edge is left unsaid ({HERE}:{a}) and 1 mm ({HERE}:{b})"
    ]


def test_a_third_way_is_held_to_the_first_and_a_repeat_is_not_reported_again(board):
    p1 = board["P1"]
    said = [place(p1, against=Edge.LEFT, inset=n * mm) for n in (1, 2, 3)]
    # The same inset again, by a statement that says something else as well.
    again = place(p1, against=Edge.LEFT, inset=2 * mm, facing=Edge.TOP)
    board.add(said[0], said[1], again, said[2])
    found = board.conflicts()
    assert [(x.first, x.second) for x in found] == [(said[0], said[1]), (said[0], said[2])]


def test_conflicts_come_by_part_as_references_are_read():
    circuit = Circuit({"parts": [{"ref": r, "value": "", "footprint": "", "pads": {}}
                                 for r in ("R10", "R2", "C1")], "nets": []})  # fmt: skip
    said = [place(circuit.part(r), facing=e) for r in ("R10", "R2", "C1")
            for e in (Edge.TOP, Edge.LEFT)]  # fmt: skip
    assert [x.part for x in conflicts(said)] == ["C1", "R2", "R10"]


def test_what_is_found_does_not_depend_on_the_order_things_were_added(board):
    p1, p2, r1, _, u1 = board.parts()
    said = [
        place(p1, against=Edge.LEFT, inset=1.27 * mm),
        place(p1, against=Edge.LEFT, inset=2.54 * mm),
        place(u1, between=(p1, p2), facing=Edge.TOP),
        place(u1, facing=Edge.BOTTOM),
        align(p1, p2, grid=0.1 * inch),
        place(r1, near=u1.pin(1), within=3 * mm),
    ]
    expected = [str(x) for x in conflicts(said)]
    order = [s.data() for s in canonical(said)]
    assert len(expected) == 2 and order == [s.data() for s in said]  # as written, top to bottom
    for shuffled in itertools.permutations(said):
        added = Board(circuit=Circuit(DATA))
        added.add(*shuffled)
        assert [str(x) for x in added.conflicts()] == expected
        assert [s.data() for s in canonical(added.statements())] == order


def test_statements_made_without_a_line_are_reported_without_one(board):
    p1 = board["P1"]
    said = [Place(p1, against=Edge.LEFT, inset=2 * mm), Place(p1, against=Edge.LEFT, inset=mm)]
    assert said[0].source is None
    # With no line to go by, the order is by what they say: inset 1 mm sorts first.
    assert [str(x) for x in conflicts(said)] == ["P1: inset from the left edge is 1 mm and 2 mm"]
    assert [str(x) for x in conflicts(reversed(said))] == [
        "P1: inset from the left edge is 1 mm and 2 mm"]  # fmt: skip


def test_an_edge_prints_as_it_is_written():
    assert [str(e) for e in Edge] == ["Edge.LEFT", "Edge.RIGHT", "Edge.TOP", "Edge.BOTTOM"]


def test_which_face_a_part_is_on_is_said_with_the_face_or_its_name(board):
    u1, r1 = board.parts("U1", "R1")
    under = place(r1, near=u1.pin(1), within=3 * mm, side="back")
    assert under == place(r1, near=u1.pin(1), within=3 * mm, side=Side.BACK)
    assert under != place(r1, near=u1.pin(1), within=3 * mm, side="front")
    assert under != place(r1, near=u1.pin(1), within=3 * mm)
    assert str(under) == "place(R1, near=U1.1, within=3 mm, side=Side.BACK)"
    assert under.data() == {"place": "R1", "near": "U1.1", "within": 3_000_000, "side": "back"}
    # The face alone is something to say, and a board passes it on.
    alone = board.place(u1, side="front")
    assert alone.side is Side.FRONT and str(alone) == "place(U1, side=Side.FRONT)"
    assert board.statements() == (alone,)
    assert pkidl.Side is Side and str(Side.BACK) == "Side.BACK"


def test_two_faces_for_one_part_are_a_conflict(board):
    u1 = board["U1"]
    board.place(u1, side="front")
    board.place(u1, facing=Edge.TOP)  # no face said: it claims none
    assert board.conflicts() == ()
    board.place(u1, against=Edge.TOP, side=Side.BACK)
    line = _line() - 1
    (found,) = board.conflicts()
    assert (found.part, found.aspect) == ("U1", "side")
    assert str(found) == f"U1: side is the front ({HERE}:{line - 3}) and the back ({HERE}:{line})"


@pytest.fixture
def antenna(board):
    """The module's antenna: the 3 mm of it above its pads."""
    (area,) = board.annotate(board["U1"], antenna=((0 * mm, -4 * mm), (8 * mm, -1 * mm)))
    return area


def test_a_keepout_is_a_statement_about_an_area_of_a_part(board, antenna):
    u1 = board["U1"]
    s, line = keepout(antenna, copper=True), _line()
    assert isinstance(s, Keepout) and (s.area, s.copper, s.both_sides) == (antenna, True, False)
    assert s == keepout(u1.area("antenna"), copper=1) and s.mentions() == (u1,)
    assert s != keepout(antenna, copper=True, both_sides=True)
    assert str(s.source) == f"{HERE}:{line}"
    assert str(s) == 'keepout(U1.area("antenna"), copper=True)'
    assert s.data() == {"keepout": "U1", "area": "antenna", "copper": True, "both_sides": False}
    both = keepout(antenna, both_sides=True, copper=True)
    assert str(both) == 'keepout(U1.area("antenna"), copper=True, both_sides=True)'
    assert both.data() == {"keepout": "U1", "area": "antenna", "copper": True, "both_sides": True}
    assert pkidl.keepout is keepout


def test_a_board_keeps_an_area_clear_and_gives_the_statement_back(board, antenna):
    before = dumps(board.sexpr())
    s, line = board.keepout(antenna, copper=True, both_sides=True), _line()
    assert s == keepout(antenna, copper=True, both_sides=True)
    assert str(s.source) == f"{HERE}:{line}"
    assert board.keepout(antenna, both_sides=True, copper=True) == s
    assert board.statements() == board.statements(about="U1") == (s,)
    assert board.statements(about="P1") == ()
    assert dumps(board.sexpr()) == before and board.items == []


def test_keepouts_add_up_and_are_never_a_conflict(board, antenna):
    one = board.keepout(antenna, copper=True)
    both = board.keepout(antenna, copper=True, both_sides=True)
    board.place(board["U1"], against=Edge.TOP)
    assert one.claims() == both.claims() == {}
    assert board.conflicts() == () and board.statements()[:2] == (one, both)


def test_a_keepout_that_does_not_say_what_of_or_what_is_kept_out_is_refused(board, antenna):
    with pytest.raises(TypeError) as e:
        keepout(board["U1"], copper=True)
    assert str(e.value) == ('keepout() takes an area of a part, such as u1.area("antenna"), '
                            "not Part(ref='U1')")  # fmt: skip
    for said in ({}, {"copper": False}, {"both_sides": True}):
        with pytest.raises(ValueError) as e:
            board.keepout(antenna, **said)
        assert str(e.value) == ('keepout(U1.area("antenna")) does not say what is kept out: '
                                "give copper=True")  # fmt: skip
    assert board.statements() == ()


def test_a_keepout_of_an_area_the_board_has_not_got_is_refused_whole(board, antenna):
    other = Board(circuit=Circuit(DATA))
    (shield,) = other.annotate(other["U1"], shield=((0 * mm, 0 * mm), (8 * mm, 2 * mm)))
    good = place(board["P1"], against=Edge.LEFT)
    with pytest.raises(LookupError) as e:
        board.add(good, keepout(shield, copper=True))
    assert e.value.args == ('keepout(U1.area("shield"), copper=True): U1 has no area '
                            "'shield': its footprint 'RF:M' has antenna",)  # fmt: skip
    assert board.statements() == ()
    # The same area on another board that has it is that board's to keep clear, and an
    # area is the same area whichever board's part it was asked of.
    assert other.add(keepout(shield, copper=True)) == other.statements()
    (theirs,) = other.annotate(other["U1"], antenna=((0 * mm, 0 * mm), (1 * mm, 1 * mm)))
    assert board.add(keepout(theirs, copper=True)) == (keepout(antenna, copper=True),)
