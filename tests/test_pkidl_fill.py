"""pkidl.fill: pour fills before routing, given to the router as planes."""

from shapely.geometry import Point as SPoint
from shapely.geometry import Polygon
from shapely.ops import unary_union

from pkidl.fill import Cut, cut_off, fills, prefill
from pkidl.sexpr import parse

OUTLINE = [(0.0, 0.0), (30.0, 0.0), (30.0, 30.0), (0.0, 30.0)]
TOL = 0.001  # mm: coordinates are rounded to 0.1 um, the DSN resolution


def _fp(ref: str, x: float, y: float, pads: list[tuple[str, float, float, float, str]]) -> str:
    body = "".join(
        f'(pad "{n}" smd rect (at {px} {py}) (size {s} {s}) (layers "F.Cu") (net "{net}"))'
        for n, px, py, s, net in pads
    )
    return f'(footprint "t" (layer "F.Cu") (at {x} {y} 0) (property "Reference" "{ref}") {body})'


def _zone(
    net: str, pts: list[tuple[float, float]], priority: int = 0, keepout: bool = False
) -> str:
    rules = (
        "(keepout (tracks allowed) (vias allowed) (pads allowed) (copperpour not_allowed)"
        " (footprints allowed))"
    )
    xy = " ".join(f"(xy {x} {y})" for x, y in pts)
    return (
        f'(zone (net "{net}") (layer "F.Cu") (priority {priority})'
        f" (connect_pads (clearance 0.5)) (min_thickness 0.25)"
        f" {rules if keepout else ''} (polygon (pts {xy})))"
    )


def _items(*nodes: str):
    return [parse(n) for n in nodes]


def _covered(planes, net: str):
    return unary_union([Polygon(p) for n, layer, p in planes if n == net and layer == "F.Cu"])


SQUARE = [(2.0, 2.0), (28.0, 2.0), (28.0, 28.0), (2.0, 28.0)]


def test_other_nets_copper_keeps_its_clearance():
    items = _items(
        _fp("R1", 15, 15, [("1", -5, 0, 1, "GND"), ("2", 5, 0, 1, "SIG")]), _zone("GND", SQUARE)
    )
    fill = _covered(prefill(items, OUTLINE, 0.5), "GND")
    sig = SPoint(20, 15).buffer(0.5, cap_style="square")  # the SIG pad
    assert fill.distance(sig) >= 0.5 - TOL  # the zone's clearance
    assert fill.contains(SPoint(5, 25))  # and it fills elsewhere


def test_a_piece_touching_none_of_its_nets_copper_is_dropped():
    items = _items(_fp("R1", 15, 15, [("1", 0, 0, 1, "SIG")]), _zone("GND", SQUARE))
    assert prefill(items, OUTLINE, 0.5) == []


def test_a_higher_priority_pour_of_another_net_is_kept_clear_of():
    hi = [(10.0, 10.0), (20.0, 10.0), (20.0, 20.0), (10.0, 20.0)]
    items = _items(
        _fp("R1", 15, 15, [("1", 0, 0, 1, "VCC")]),
        _fp("R2", 5, 5, [("1", 0, 0, 1, "GND")]),
        _zone("GND", SQUARE, priority=0),
        _zone("VCC", hi, priority=1),
    )
    planes = prefill(items, OUTLINE, 0.5)
    vcc, gnd = _covered(planes, "VCC"), _covered(planes, "GND")
    assert vcc.contains(SPoint(12, 12))
    assert gnd.distance(vcc) >= 0.5 - TOL


def test_a_no_pour_corridor_is_cut_and_the_far_side_dropped():
    """A corridor across the whole pour leaves two pieces; only the one with a GND pad stays."""
    corridor = [(0.0, 14.0), (30.0, 14.0), (30.0, 16.0), (0.0, 16.0)]
    items = _items(
        _fp("R1", 5, 5, [("1", 0, 0, 1, "GND")]),
        _zone("GND", SQUARE),
        _zone("", corridor, keepout=True),
    )
    fill = _covered(prefill(items, OUTLINE, 0.5), "GND")
    assert fill.contains(SPoint(10, 8))
    assert not fill.intersects(SPoint(10, 15))  # the corridor
    assert not fill.contains(SPoint(10, 22))  # the far side: an island


def _shoelace(ring):
    edges = zip(ring, ring[1:] + ring[:1], strict=True)
    return abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in edges)) / 2


def _pad_hole(x, y):
    """The hole a 2 mm square SIG pad leaves: the pad grown by the 0.5 mm clearance."""
    return Polygon([(x - 1, y - 1), (x + 1, y - 1), (x + 1, y + 1), (x - 1, y + 1)]).buffer(0.5)


def test_a_fill_with_a_hole_is_one_plane_reaching_the_hole_by_a_slit():
    """A pad in the middle leaves a hole; a DSN plane can't have one, and the router must
    connect a net's planes to each other, so the fill is one outline with a slit."""
    items = _items(
        _fp("R1", 15, 15, [("1", 0, 0, 2, "SIG")]),
        _fp("R2", 5, 5, [("1", 0, 0, 1, "GND")]),
        _zone("GND", SQUARE),
    )
    planes = [p for n, _, p in prefill(items, OUTLINE, 0.5) if n == "GND"]
    assert len(planes) == 1
    hole = _pad_hole(15, 15)
    whole = Polygon(SQUARE).difference(hole)
    assert abs(_shoelace(planes[0]) - whole.area) < 0.05


def test_slits_never_cross_another_hole():
    """Two holes one above the other: the lower one's slit runs up into the upper one,
    already joined, not across it."""
    items = _items(
        _fp("R1", 15, 10, [("1", 0, 0, 2, "SIG")]),
        _fp("R3", 15, 20, [("1", 0, 0, 2, "SIG")]),
        _fp("R2", 5, 5, [("1", 0, 0, 1, "GND")]),
        _zone("GND", SQUARE),
    )
    planes = [p for n, _, p in prefill(items, OUTLINE, 0.5) if n == "GND"]
    assert len(planes) == 1
    ring = planes[0]
    holes = [_pad_hole(15, y).buffer(-0.02) for y in (10, 20)]
    for a, b in zip(ring, ring[1:] + ring[:1], strict=True):
        mid = SPoint((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        assert not any(h.contains(mid) for h in holes)
    whole = Polygon(SQUARE).difference(unary_union([_pad_hole(15, y) for y in (10, 20)]))
    assert abs(_shoelace(ring) - whole.area) < 0.1


def test_a_nets_class_clearance_wins_when_larger():
    """A pour keeps the larger of its own clearance and the other net's class clearance."""
    items = _items(
        _fp("R1", 15, 15, [("1", -5, 0, 1, "GND"), ("2", 5, 0, 1, "HV")]), _zone("GND", SQUARE)
    )
    fill = _covered(prefill(items, OUTLINE, 0.5, {"HV": 1.25}), "GND")
    hv = SPoint(20, 15).buffer(0.5, cap_style="square")
    assert fill.distance(hv) >= 1.25 - TOL


def _track(net: str, a: tuple[float, float], b: tuple[float, float], width: float = 0.5) -> str:
    return (f"(segment (start {a[0]} {a[1]}) (end {b[0]} {b[1]}) (width {width}) "
            f'(layer "F.Cu") (net "{net}"))')  # fmt: skip


# Two parts with a ground pad each, 20 mm apart across the middle of the pour.
TWO = [_fp("C1", 5, 15, [("1", 0, 0, 1, "GND")]), _fp("C2", 25, 15, [("1", 0, 0, 1, "GND")])]
WALL = _track("SIG", (15, 1), (15, 29))  # a track across the whole pour between them


def test_a_poured_net_whose_pads_the_pour_joins_is_one_piece():
    assert cut_off(_items(*TWO, _zone("GND", SQUARE)), OUTLINE, 0.5) == []
    # A track part of the way across leaves the pour one piece round its end.
    part_way = _track("SIG", (15, 1), (15, 20))
    assert cut_off(_items(*TWO, _zone("GND", SQUARE), part_way), OUTLINE, 0.5) == []


def test_pads_on_a_piece_of_pour_that_a_track_cuts_from_the_rest_are_said_with_the_track():
    more = _fp("C3", 8, 20, [("1", 0, 0, 1, "GND")])  # two pads one side, one the other
    cuts = cut_off(_items(*TWO, more, _zone("GND", SQUARE), WALL), OUTLINE, 0.5)
    assert cuts == [Cut("GND", ("C2.1",), "F.Cu", ("SIG",))]
    assert str(cuts[0]) == (
        "C2.1 is cut off from the rest of GND: on a piece of its pour on F.Cu that is "
        "apart from the rest, fenced in by tracks of SIG"
    )
    # The two pieces are there in the fill: it is the pads that say which is the net.
    assert len(fills(_items(*TWO, more, _zone("GND", SQUARE), WALL), OUTLINE, 0.5)) == 2


def test_a_track_of_the_net_across_the_cut_makes_it_one_piece_again():
    # Ground carried over the wall on the other layer and back is one net: a via each
    # side, each in its piece of the pour, and a track between them on the back.
    over = (
        '(via (at 13 15) (size 0.8) (net "GND"))',
        '(via (at 17 15) (size 0.8) (net "GND"))',
        '(segment (start 13 15) (end 17 15) (width 0.5) (layer "B.Cu") (net "GND"))',
    )
    cut = _items(*TWO, _zone("GND", SQUARE), WALL)
    assert [c.pads for c in cut_off(cut, OUTLINE, 0.5)] == [("C2.1",)]
    assert cut_off(_items(*TWO, _zone("GND", SQUARE), WALL, *over), OUTLINE, 0.5) == []
    # A via each side with no track between them joins nothing.
    assert [c.pads for c in cut_off([*cut, *_items(*over[:2])], OUTLINE, 0.5)] == [("C2.1",)]


def test_a_pad_no_pour_reaches_and_no_track_joins_is_said_so():
    # The pour is the left half of the board; C2's pad is outside it.
    left = [(2.0, 2.0), (14.0, 2.0), (14.0, 28.0), (2.0, 28.0)]
    more = _fp("C3", 8, 20, [("1", 0, 0, 1, "GND")])
    cuts = cut_off(_items(*TWO, more, _zone("GND", left)), OUTLINE, 0.5)
    assert cuts == [Cut("GND", ("C2.1",))]
    assert str(cuts[0]) == "C2.1 is cut off from the rest of GND: no pour reaches there"
    # Joined by a track it is on the net, though the pour is not under it.
    assert cut_off(_items(*TWO, more, _zone("GND", left), _track("GND", (5, 15), (25, 15))),
                   OUTLINE, 0.5) == []  # fmt: skip


def test_a_net_with_no_pour_is_not_asked_about():
    assert cut_off(_items(*TWO), OUTLINE, 0.5) == []
    assert cut_off(_items(*TWO, _zone("SIG", SQUARE), _fp("R1", 15, 5, [("1", 0, 0, 1, "SIG")])),
                   OUTLINE, 0.5) == []  # fmt: skip


def test_the_planes_are_the_fills_pieces_each_as_one_outline():
    items = _items(*TWO, _zone("GND", SQUARE), WALL)
    planes, pieces = prefill(items, OUTLINE, 0.5), fills(items, OUTLINE, 0.5)
    assert [(n, layer) for n, layer, _ in planes] == [(n, layer) for n, layer, _ in pieces]
    for (_, _, outline), (_, _, piece) in zip(planes, pieces, strict=True):
        assert abs(Polygon(outline).area - piece.area) < 0.01


def test_two_pads_of_one_number_are_each_where_they_are():
    # A shield's two pads share a number. One is across the wall from the other: it is
    # cut off, and the piece of pour it is on is there, not lost with it.
    shield = _fp("J1", 0, 15, [("SH", 5, 0, 1, "GND"), ("SH", 25, 0, 1, "GND")])
    more = _fp("C3", 8, 20, [("1", 0, 0, 1, "GND")])
    items = _items(shield, more, _zone("GND", SQUARE), WALL)
    assert len(fills(items, OUTLINE, 0.5)) == 2
    assert [c.pads for c in cut_off(items, OUTLINE, 0.5)] == [("J1.SH",)]
    # And a pour keeps clear of the second of two pads of another net.
    pair = _fp("J2", 0, 15, [("1", 10, 0, 1, "SIG"), ("1", 20, 0, 1, "SIG")])
    ((_, _, piece),) = fills(_items(TWO[0], pair, _zone("GND", SQUARE)), OUTLINE, 0.5)
    assert not piece.contains(SPoint(10, 15)) and not piece.contains(SPoint(20, 15))


def _relieved(net: str, gap: float = 0.5, connect: str = "") -> str:
    """A pour over the square that joins its pads by thermal reliefs: a *gap* round each
    pad and spokes 0.5 mm wide, or as *connect* says."""
    xy = " ".join(f"(xy {x} {y})" for x, y in SQUARE)
    return (f'(zone (net "{net}") (layer "F.Cu") (connect_pads {connect} (clearance 0.2)) '
            f"(min_thickness 0.25) (fill yes (thermal_gap {gap}) (thermal_bridge_width 0.5)) "
            f"(polygon (pts {xy})))")  # fmt: skip


def _boxed_in(off: float) -> list[str]:
    """C1's pad, 1 mm square at (5, 15), with a pad of another net *off* mm from each of
    its four sides: copper where its spokes would go."""
    around = [("1", -(1 + off), 0, 1, "SIG"), ("2", 1 + off, 0, 1, "SIG"),
              ("3", 0, -(1 + off), 1, "SIG"), ("4", 0, 1 + off, 1, "SIG")]  # fmt: skip
    return [*TWO, _fp("C3", 20, 20, [("1", 0, 0, 1, "GND")]), _fp("X1", 5, 15, around)]


def test_a_pad_is_joined_to_a_pour_by_its_spokes_and_not_by_lying_in_it():
    # With room on every side its four spokes reach the pour.
    assert cut_off(_items(*_boxed_in(3.0), _relieved("GND")), OUTLINE, 0.5) == []
    # With other copper 0.6 mm off each side, no spoke has the 0.5 mm gap and 0.25 mm of
    # pour beyond it clear of that copper's 0.2 mm: the pad lies in the pour's outline
    # and is joined to nothing.
    cuts = cut_off(_items(*_boxed_in(0.6), _relieved("GND")), OUTLINE, 0.5)
    assert [c.pads for c in cuts] == [("C1.1",)]


def test_a_pad_needs_two_spokes_as_kicad_asks():
    # Copper off three sides leaves one spoke: connected, by KiCad's fill, and starved.
    three = [("1", -1.6, 0, 1, "SIG"), ("2", 1.6, 0, 1, "SIG"), ("3", 0, -1.6, 1, "SIG")]
    items = [*TWO, _fp("C3", 20, 20, [("1", 0, 0, 1, "GND")]), _fp("X1", 5, 15, three)]
    assert [c.pads for c in cut_off(_items(*items, _relieved("GND")), OUTLINE, 0.5)] == [("C1.1",)]
    two = three[:2]
    items = [*TWO, _fp("C3", 20, 20, [("1", 0, 0, 1, "GND")]), _fp("X1", 5, 15, two)]
    assert cut_off(_items(*items, _relieved("GND")), OUTLINE, 0.5) == []


def test_a_solid_connection_joins_a_pad_wherever_the_pour_touches_it():
    boxed = _boxed_in(0.6)
    assert cut_off(_items(*boxed, _relieved("GND", connect="yes")), OUTLINE, 0.5) == []
    # And a zone that connects no pads joins none: each of the three is alone, the
    # first of them taken for the net and the other two said.
    alone = cut_off(_items(*boxed, _relieved("GND", connect="no")), OUTLINE, 0.5)
    assert sorted(p for c in alone for p in c.pads) == ["C2.1", "C3.1"]


def test_a_round_pads_spokes_are_on_its_diagonals():
    def round_pad(blockers):
        pad = ('(footprint "t" (layer "F.Cu") (at 5 15 0) (property "Reference" "C1") '
               '(pad "1" smd circle (at 0 0) (size 1 1) (layers "F.Cu") (net "GND")))')  # fmt: skip
        rest = [TWO[1], _fp("C3", 20, 20, [("1", 0, 0, 1, "GND")]), _fp("X1", 5, 15, blockers)]
        return [c.pads for c in cut_off(_items(pad, *rest, _relieved("GND")), OUTLINE, 0.5)]

    # Copper off its four sides leaves the diagonals, where a round pad's spokes are.
    sides = [("1", -1.9, 0, 1, "SIG"), ("2", 1.9, 0, 1, "SIG"),
             ("3", 0, -1.9, 1, "SIG"), ("4", 0, 1.9, 1, "SIG")]  # fmt: skip
    assert round_pad(sides) == []
    # Copper on its four diagonals takes them.
    corners = [("1", -1.2, -1.2, 1, "SIG"), ("2", 1.2, -1.2, 1, "SIG"),
               ("3", -1.2, 1.2, 1, "SIG"), ("4", 1.2, 1.2, 1, "SIG")]  # fmt: skip
    assert round_pad(corners) == [("C1.1",)]


def test_a_pour_keeps_its_hole_clearance_from_what_is_on_no_net():
    hole = (
        '(footprint "t" (layer "F.Cu") (at 15 15 0) (property "Reference" "H1") '
        '(pad "" np_thru_hole circle (at 0 0) (size 3 3) (drill 3) (layers "*.Cu")))'
    )
    items = _items(*TWO, hole, _relieved("GND"))

    def gap(clearances):
        ((_, _, piece),) = fills(items, OUTLINE, 0.5, clearances)
        return piece.distance(SPoint(15, 15)) - 1.5

    # The pour's own 0.2 mm, or what is asked of a hole where that is more.
    assert abs(gap(None) - 0.2) < 0.005 and abs(gap({"": 0.25}) - 0.25) < 0.005


def test_a_pour_fills_inside_the_outline_it_is_given_as_a_shape():
    # The board with its top right corner cut off, and with a slot through its middle.
    cornered = Polygon([(0, 0), (20, 0), (30, 10), (30, 30), (0, 30)])
    ((_, _, piece),) = fills(_items(*TWO, _zone("GND", SQUARE)), cornered, 0.5)
    assert not piece.contains(SPoint(27, 3)) and piece.contains(SPoint(3, 27))
    slotted = Polygon(OUTLINE, [[(14, 1), (16, 1), (16, 29), (14, 29)]])
    items = _items(*TWO, _fp("C3", 8, 20, [("1", 0, 0, 1, "GND")]), _zone("GND", SQUARE))
    assert [c.pads for c in cut_off(items, slotted, 0.5)] == [("C2.1",)]
    assert cut_off(items, OUTLINE, 0.5) == []
