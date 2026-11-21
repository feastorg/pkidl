"""pkidl.neck: the least copper there is to cut to part the two ends of a stretch.

The shapes below have a neck that is known, and each is measured turned and moved off
any grid. Copper is given as shapes, or as the items of a board with a pour.
"""

import heapq
import math
import random

import pytest
from shapely import affinity, shortest_line
from shapely.geometry import LineString, Polygon, box
from shapely.geometry import Point as SPoint
from shapely.ops import unary_union

from pkidl import neck as necks
from pkidl.neck import KICAD, MODEL, Neck, Necks, Piece, _Copper, _Lump
from pkidl.sexpr import parse
from pkidl.units import Length, mm

F, B = "F.Cu", "B.Cu"
NM = 1e-6  # a nanometre, in millimetres
# A neck is right to within this: what moving each corner of the copper to the
# nanometre can make of a width, which is under the micrometre a neck is given to.
EXACT = 20 * NM
TURNS = [0, 30, 45, 61.7]
MOVES = [(0.0, 0.0), (100.123, 50.0377)]
EVERY_WAY = [(turn, move) for turn in TURNS for move in MOVES]


def moved(shape, turn, move):
    return affinity.translate(affinity.rotate(shape, turn, origin=(0, 0)), *move)


def copper(sheets, lumps, turn=0.0, move=(0.0, 0.0), step=necks.STEP):
    """The copper of a net given as its shape on each layer and its pads, turned and
    moved."""
    return _Copper({layer: moved(shape, turn, move) for layer, shape in sheets.items()},
                   [_Lump(f"P{n}", {layer: moved(shape, turn, move)
                                    for layer, shape in lump.items()})
                    for n, lump in enumerate(lumps, 1)], step)  # fmt: skip


def neck(sheets, lumps, turn=0.0, move=(0.0, 0.0), step=necks.STEP):
    """The neck between the first pad and the second, in millimetres, and its pieces,
    each the sides it is of."""
    found = copper(sheets, lumps, turn, move, step).cut([0], [1])
    assert found is not None
    return found[0] * NM, found[1]


def widths(pieces):
    """How wide each piece of a cut is, to a tenth of a micrometre, the narrowest
    first."""
    return sorted(round(sum(math.dist(p, q) for _, p, q, _ in piece), 4) for piece in pieces)


def ends(long, wide):
    """A pad over each end of a strip *long* along x, wider than anything between."""
    return box(-1, -wide, 0.5, wide), box(long - 0.5, -wide, long + 1, wide)


def strip(wide, long=20.0):
    a, b = ends(long, wide)
    return {F: unary_union([box(0, -wide / 2, long, wide / 2), a, b])}, [{F: a}, {F: b}]


@pytest.mark.parametrize(("turn", "move"), EVERY_WAY)
@pytest.mark.parametrize("wide", [0.25, 1.0, 7.3])
def test_a_straight_strip_is_as_wide_as_it_is_at_any_angle(wide, turn, move):
    found, pieces = neck(*strip(wide), turn, move)
    assert found == pytest.approx(wide, abs=EXACT)
    assert len(pieces) == 1


@pytest.mark.parametrize(("turn", "move"), EVERY_WAY)
def test_two_strips_side_by_side_are_the_sum_of_their_widths(turn, move):
    a, b = box(-1, -3, 0.5, 3), box(19.5, -3, 21, 3)
    sheet = unary_union([box(0, 1, 20, 2), box(0, -2, 20, -1.3), a, b])
    found, pieces = neck({F: sheet}, [{F: a}, {F: b}], turn, move)
    assert found == pytest.approx(1.7, abs=EXACT)
    assert widths(pieces) == [0.7, 1.0]


@pytest.mark.parametrize(("turn", "move"), EVERY_WAY)
@pytest.mark.parametrize(("wide", "across", "off"), [(3.0, 1.0, (0.0, 0.0)),
                                                     (3.0, 1.0, (0.31, 0.63)),
                                                     (1.0, 0.5, (0.017, 0.0))])  # fmt: skip
def test_a_strip_with_a_round_hole_is_its_width_less_the_hole(wide, across, off, turn, move):
    a, b = ends(20, wide)
    hole = SPoint(10 + off[0], off[1]).buffer(across / 2, quad_segs=64)
    sheet = unary_union([box(0, -wide / 2, 20, wide / 2).difference(hole), a, b])
    found, pieces = neck({F: sheet}, [{F: a}, {F: b}], turn, move)
    # The hole is drawn with straight sides: what is left either side of it, as drawn.
    left = hole.distance(LineString([(0, wide / 2), (20, wide / 2)])) + hole.distance(
        LineString([(0, -wide / 2), (20, -wide / 2)])
    )
    assert found == pytest.approx(left, abs=EXACT)
    assert left == pytest.approx(wide - across, abs=1e-3) and len(pieces) == 2


def hourglass(shift=0.0, wide=5.0, waist=1.3):
    """A strip pinched from both sides, the two tips *shift* either way along it."""
    a, b = ends(20, wide)
    body = Polygon([(0, -wide / 2), (7, -wide / 2), (10 + shift, -waist / 2), (13, -wide / 2),
                    (20, -wide / 2), (20, wide / 2), (13, wide / 2), (10 - shift, waist / 2),
                    (7, wide / 2), (0, wide / 2)])  # fmt: skip
    return {F: unary_union([body, a, b])}, [{F: a}, {F: b}]


@pytest.mark.parametrize(("turn", "move"), EVERY_WAY)
def test_an_hourglass_is_its_waist(turn, move):
    assert neck(*hourglass(), turn, move)[0] == pytest.approx(1.3, abs=EXACT)
    # Tips that are not across from each other: from one tip straight to the other
    # side, which is nearer than the other tip.
    tip, side = (10.4, -0.65), LineString([(9.6, 0.65), (13, 2.5)])
    assert side.distance(SPoint(tip)) < math.dist(tip, (9.6, 0.65))
    assert neck(*hourglass(0.4), turn, move)[0] == pytest.approx(
        side.distance(SPoint(tip)), abs=EXACT
    )


def spoked(spokes, wide=0.5, gap=0.5, pad=2.0):
    """A pad in a plane with a gap round it, joined across the gap by *spokes* spokes;
    the other end a pad along the plane's edge."""
    p = box(-pad / 2, -pad / 2, pad / 2, pad / 2)
    plane = box(-10, -10, 10, 10).difference(p.buffer(gap, join_style="mitre"))
    arms = [affinity.rotate(box(0, -wide / 2, pad / 2 + gap + 0.1, wide / 2), 90 * k,
                            origin=(0, 0)) for k in range(spokes)]  # fmt: skip
    rim = box(9, -10, 12, 10)
    return {F: unary_union([plane, p, rim, *arms])}, [{F: p}, {F: rim}]


@pytest.mark.parametrize(("turn", "move"), EVERY_WAY)
@pytest.mark.parametrize(("spokes", "wide"), [(4, 0.5), (2, 0.5), (4, 0.3), (1, 0.5)])
def test_a_pad_on_spokes_is_the_spokes_together(spokes, wide, turn, move):
    found, pieces = neck(*spoked(spokes, wide), turn, move)
    assert found == pytest.approx(spokes * wide, abs=EXACT)
    assert len(pieces) == spokes


@pytest.mark.parametrize(("turn", "move"), EVERY_WAY)
def test_a_pad_joined_all_round_is_cut_round_its_edge_and_not_through_it(turn, move):
    # 2 mm square in a plane: no cut goes through a pad, so the least is all round it.
    p, rim = box(-1, -1, 1, 1), box(9, -10, 12, 10)
    found, pieces = neck({F: unary_union([box(-10, -10, 10, 10), rim])}, [{F: p}, {F: rim}],
                         turn, move)  # fmt: skip
    assert found == pytest.approx(8.0, abs=EXACT)
    assert len(pieces) == 1 and all(lump == 0 for _, _, _, lump in pieces[0])


@pytest.mark.parametrize(("turn", "move"), EVERY_WAY)
def test_a_plane_with_a_slot_is_the_two_straits_it_leaves(turn, move):
    a, b = ends(20, 10)
    slot = box(9.5, -2.3, 10.5, 3.7)  # leaves 1.3 mm one side and 2.7 mm the other
    sheet = unary_union([box(0, -5, 20, 5).difference(slot), a, b])
    found, pieces = neck({F: sheet}, [{F: a}, {F: b}], turn, move)
    assert found == pytest.approx(4.0, abs=EXACT)
    assert widths(pieces) == [1.3, 2.7]


@pytest.mark.parametrize(("turn", "move"), EVERY_WAY)
def test_a_chain_of_tracks_is_the_narrowest_of_them(turn, move):
    a, b = box(-1, -1, 1, 1), box(29, 9, 31, 11)
    chain = [((0, 0), (10, 0), 0.8), ((10, 0), (17, 7), 0.5), ((17, 7), (17, 10), 0.6),
             ((17, 10), (30, 10), 1.0)]  # fmt: skip
    sheet = unary_union([LineString([p, q]).buffer(wide / 2) for p, q, wide in chain] + [a, b])
    assert neck({F: sheet}, [{F: a}, {F: b}], turn, move)[0] == pytest.approx(0.5, abs=EXACT)
    # One that comes into both of its pads on the slant.
    b = box(9, 6, 11, 8)
    sheet = unary_union([LineString([(0, 0), (10, 7)]).buffer(0.25), a, b])
    assert neck({F: sheet}, [{F: a}, {F: b}], turn, move)[0] == pytest.approx(0.5, abs=EXACT)


@pytest.mark.parametrize(("turn", "move"), EVERY_WAY)
def test_two_layers_are_joined_where_a_pad_or_a_via_has_copper_on_both(turn, move):
    # A pad on the front, a track to a via, and on from it on the back to a pad there:
    # one after the other, the narrower.
    a, b, via = box(-1, -1, 1, 1), box(19, -1, 21, 1), SPoint(10, 0).buffer(1.0)
    front = unary_union([LineString([(0, 0), (10, 0)]).buffer(0.25), a, via])
    back = unary_union([LineString([(10, 0), (20, 0)]).buffer(0.4), b, via])
    lumps = [{F: a}, {B: b}, {F: via, B: via}]
    assert neck({F: front, B: back}, lumps, turn, move)[0] == pytest.approx(0.5, abs=EXACT)
    # With no via the two layers are apart.
    assert neck({F: front, B: back}, lumps[:2], turn, move)[0] == 0
    # Two pads through the board with a track on each layer between them: side by
    # side, the sum.
    a, b = SPoint(0, 0).buffer(1.0), SPoint(20, 0).buffer(1.0)
    front = unary_union([LineString([(0, 0), (20, 0)]).buffer(0.25), a, b])
    back = unary_union([LineString([(0, 0), (10, 5), (20, 0)]).buffer(0.4), a, b])
    found, pieces = neck({F: front, B: back}, [{F: a, B: a}, {F: b, B: b}], turn, move)
    assert found == pytest.approx(1.3, abs=EXACT)
    assert sorted(piece[0][0] for piece in pieces) == [B, F]


def test_a_via_is_cut_round_and_its_barrel_is_not_counted():
    # A track 3 mm wide through a via 0.8 mm across onto the other layer: all the
    # copper there is round the via's pad is its edge, 0.8 mm times pi as it is drawn.
    a, b, via = box(-2, -2, 2, 2), box(18, -2, 22, 2), SPoint(10, 0).buffer(0.4)
    front = unary_union([LineString([(0, 0), (10, 0)]).buffer(1.5), a, via])
    back = unary_union([LineString([(10, 0), (20, 0)]).buffer(1.5), b, via])
    found, pieces = neck({F: front, B: back}, [{F: a}, {B: b}, {F: via, B: via}])
    assert found == pytest.approx(via.exterior.length, abs=EXACT) and found < 0.8 * math.pi
    assert len(pieces) == 1 and all(lump == 2 for _, _, _, lump in pieces[0])


def test_ends_whose_copper_touches_are_one_piece_and_have_no_neck():
    a, b = box(0, 0, 1, 1), box(1, 0, 2, 1)
    assert copper({F: unary_union([a, b])}, [{F: a}, {F: b}]).cut([0], [1]) is None
    # And so are two that a via with copper on both joins, each on its own layer.
    b, via = box(5, 0, 6, 1), SPoint(3, 0.5).buffer(2.5)
    joined = copper({F: unary_union([a, via]), B: unary_union([b, via])},
                    [{F: a}, {B: b}, {F: via, B: via}])  # fmt: skip
    assert joined.cut([0], [1]) is None
    # A pad at both ends is at neither.
    assert copper({F: a}, [{F: a}]).cut([0], [0]) is None


def test_an_end_of_several_pads_is_cut_from_as_one():
    # Two pads at one end, each with its own strip to the other end: both are cut.
    a1, a2, b = box(-1, 1, 0.5, 3), box(-1, -3, 0.5, -1), box(19.5, -4, 21, 4)
    sheet = unary_union([box(0, 1.5, 20, 2.5), box(0, -2.3, 20, -1.7), a1, a2, b])
    net = copper({F: sheet}, [{F: a1}, {F: a2}, {F: b}])

    def wide(one, two):
        found = net.cut(one, two)
        assert found is not None
        return found[0] * NM

    assert wide([0, 1], [2]) == pytest.approx(1.6, abs=EXACT)
    assert wide([0], [2]) == pytest.approx(1.0, abs=EXACT)
    # From one of them to the other, by way of the far pad: the narrower strip.
    assert wide([0], [1]) == pytest.approx(0.6, abs=EXACT)


def parted(net, one, two, pieces):
    """Whether the copper *net*, with a little taken out along each side of *pieces*,
    still joins the lumps *one* to the lumps *two*."""
    lumps = net.lumps
    left = []  # each piece of copper left, as (layer, shape)
    for sheet in net.sheets:
        cuts = [LineString([p, q]).buffer(1e-4) for piece in pieces
                for layer, p, q, _ in piece if layer == sheet.layer]  # fmt: skip
        gone = unary_union(cuts or [Polygon()])
        rest = sheet.area.difference(gone)
        left += [(sheet.layer, part) for part in getattr(rest, "geoms", [rest])]
    reached, seen, spare = set(), {net.root(i) for i in one}, [net.root(i) for i in one]
    while spare:
        group = spare.pop()
        mine = [lump for i, lump in enumerate(lumps) if net.root(i) == group]
        for n, (layer, part) in enumerate(left):
            if n not in reached and any(layer in lump.copper
                                        and lump.copper[layer].distance(part) < 1e-5
                                        for lump in mine):  # fmt: skip
                reached.add(n)
                for i, lump in enumerate(lumps):
                    if (net.root(i) not in seen and layer in lump.copper
                            and lump.copper[layer].distance(part) < 1e-5):  # fmt: skip
                        seen.add(net.root(i))
                        spare.append(net.root(i))
    return not seen & {net.root(i) for i in two}


def scattered(seed, many, small):
    """A strip 6 mm wide between two pads, with *many* holes scattered in it, round,
    square and long, most of them *small* where that is said: the copper, the pads,
    and the shortest way from one wall to the other through the holes, each step the
    distance between two of them. That way is the neck exactly."""
    rng = random.Random(seed)
    holes = []
    for _ in range(many):
        x, y = rng.uniform(1.5, 12.5), rng.uniform(-2.7, 2.7)
        kind, less = rng.choice("obs"), small and rng.random() < 0.8
        if kind == "o":
            hole = SPoint(x, y).buffer(rng.uniform(0.05, 0.2) if less else rng.uniform(0.15, 0.9))
        elif kind == "b":
            k = 0.15 if less else 1
            hole = affinity.rotate(
                box(x - rng.uniform(0.1, 1) * k, y - rng.uniform(0.1, 1) * k,
                    x + rng.uniform(0.1, 1) * k, y + rng.uniform(0.1, 1) * k),
                rng.uniform(0, 90))  # fmt: skip
        else:
            k = 0.2 if less else 1
            hole = LineString([(x, y), (x + rng.uniform(-2, 2) * k, y + rng.uniform(-2, 2) * k)]
                              ).buffer(rng.uniform(0.1, 0.4) * (0.5 if less else 1))  # fmt: skip
        holes.append(hole)
    voids = unary_union(holes).intersection(box(0.9, -6, 13.1, 6))  # clear of the pads
    a, b = box(-1, -6, 0.5, 6), box(13.5, -6, 15, 6)
    walls = [box(0.5, 3, 13.5, 4), box(0.5, -4, 13.5, -3)]
    parts = walls + list(getattr(voids, "geoms", [voids]))
    least = [math.inf] * len(parts)
    least[0] = 0.0
    queue = [(0.0, 0)]
    while queue:
        far, i = heapq.heappop(queue)
        if far <= least[i]:
            for j, other in enumerate(parts):
                if far + parts[i].distance(other) < least[j]:
                    least[j] = far + parts[i].distance(other)
                    heapq.heappush(queue, (least[j], j))
    sheet = unary_union([box(0, -3, 14, 3).difference(voids), a, b])
    return {F: sheet}, [{F: a}, {F: b}], least[1], rng.uniform(0, 180)


@pytest.mark.parametrize("seed", range(40))
@pytest.mark.parametrize(("many", "small"), [(9, False), (30, True)])
def test_a_strip_with_holes_scattered_in_it_is_the_shortest_way_through_them(seed, many, small):
    sheets, lumps, exact, turn = scattered(seed, many, small)
    net = copper(sheets, lumps, turn, (0.37, 0.61))
    found = net.cut([0], [1])
    assert found is not None
    wide, pieces = found
    assert wide * NM == pytest.approx(exact, abs=5 * EXACT)
    # And what is found is a cut: with it made, the ends are apart.
    assert parted(net, [0], [1], pieces)
    assert not parted(net, [0], [1], pieces[1:])


def among_pads(seed):
    """A strip 6 mm wide between two pads with holes scattered in it, and with pads and
    vias of its own net among them, each clear of the holes and of the others, a via
    drawn with eight sides: the copper, the pads, and the neck reckoned exactly. A cut
    crosses a hole for nothing, goes through no pad, and may go round the edge of one
    from corner to corner: the neck is the shortest such way from wall to wall, by
    holes and by corners of pads."""
    rng = random.Random(seed)
    holes, pads = [], []
    for _ in range(rng.randint(6, 24)):
        x, y = rng.uniform(1.5, 12.5), rng.uniform(-2.7, 2.7)
        kind = rng.choice("obsvvp")
        if kind == "o":
            holes.append(SPoint(x, y).buffer(rng.uniform(0.1, 0.8)))
        elif kind == "b":
            holes.append(affinity.rotate(
                box(x - rng.uniform(0.1, 1), y - rng.uniform(0.1, 1),
                    x + rng.uniform(0.1, 1), y + rng.uniform(0.1, 1)),
                rng.uniform(0, 90)))  # fmt: skip
        elif kind == "s":
            far = (x + rng.uniform(-2, 2), y + rng.uniform(-2, 2))
            holes.append(LineString([(x, y), far]).buffer(rng.uniform(0.1, 0.4)))
        elif kind == "v":
            pads.append(SPoint(x, y).buffer(0.4, quad_segs=2))
        else:
            pads.append(affinity.rotate(
                box(x - rng.uniform(0.3, 1), y - rng.uniform(0.2, 0.6),
                    x + rng.uniform(0.3, 1), y + rng.uniform(0.2, 0.6)),
                rng.uniform(0, 90)))  # fmt: skip
    voids = unary_union(holes).intersection(box(0.9, -6, 13.1, 6))
    kept: list = []
    for shape in pads:
        if (box(1.2, -2.6, 12.8, 2.6).contains(shape) and shape.distance(voids) > 0.05
                and all(shape.distance(other) > 0.05 for other in kept)):  # fmt: skip
            kept.append(shape)
    a, b = box(-1, -6, 0.5, 6), box(13.5, -6, 15, 6)
    sheet = unary_union([box(0, -3, 14, 3).difference(voids), a, b, *kept])
    solid = unary_union(kept or [Polygon()])

    def clear(p, q):
        return math.dist(p, q) < 1e-9 or not solid.relate_pattern(LineString([p, q]), "T********")

    # The walls, then the holes, then each corner of each pad.
    parts = [box(0.5, 3, 13.5, 4), box(0.5, -4, 13.5, -3),
             *(g for g in getattr(voids, "geoms", [voids]) if not g.is_empty)]  # fmt: skip
    corners = [SPoint(c) for shape in kept for c in shape.exterior.coords[:-1]]
    nodes = [*parts, *corners]
    ways: list[list[tuple[int, float]]] = [[] for _ in nodes]
    for i, one in enumerate(nodes):
        for j in range(i + 1, len(nodes)):
            p, q = shortest_line(one, nodes[j]).coords
            if clear(p, q):
                ways[i].append((j, math.dist(p, q)))
                ways[j].append((i, math.dist(p, q)))
    least = [math.inf] * len(nodes)
    least[0] = 0.0
    queue = [(0.0, 0)]
    while queue:
        far, i = heapq.heappop(queue)
        if far <= least[i]:
            for j, more in ways[i]:
                if far + more < least[j]:
                    least[j] = far + more
                    heapq.heappush(queue, (least[j], j))
    return {F: sheet}, [{F: a}, {F: b}, *({F: shape} for shape in kept)], least[1]


# Of the hundred strips below, the two where a narrower cut than the one found is
# known, and by how much the neck is said wider than it is: the least cut bends round
# the corner of a pad that the cut found does not go by.
WIDER = {52: 0.0233, 68: 0.0026}


@pytest.mark.parametrize("seed", range(100))
def test_among_pads_and_vias_a_neck_is_never_narrower_than_is_said_and_seldom_wider(seed):
    sheets, lumps, exact = among_pads(seed)
    net = copper(sheets, lumps, 3.7 * seed, (0.37, 0.61))
    found = net.cut([0], [1])
    assert found is not None
    wide, pieces = found
    if seed in WIDER:
        assert wide * NM == pytest.approx(exact * (1 + WIDER[seed]), rel=1e-3)
    else:
        assert wide * NM == pytest.approx(exact, abs=1e-3)
    # Whichever it is, what is found is a cut, and none of it is to spare.
    assert parted(net, [0], [1], pieces)
    assert not parted(net, [0], [1], pieces[1:])


@pytest.mark.parametrize(("turn", "move"), EVERY_WAY)
def test_a_plane_with_holes_in_rows_and_vias_between_is_cut_along_a_row(turn, move):
    # 20 mm square, a hole 1.2 mm across every 2.5 mm and a via of the net between each
    # four: the vias of one half from those of the other. The least cut goes down a row
    # of holes, where its chords are all on one line and cross others at one point.
    holes = [SPoint(2.5 * i, 2.5 * j).buffer(0.6) for i in range(1, 8) for j in range(1, 8)]
    vias = [SPoint(2.5 * i + 1.25, 2.5 * j + 1.25).buffer(0.4)
            for i in range(1, 7) for j in range(1, 7)]  # fmt: skip
    sheet = unary_union([box(0, 0, 20, 20).difference(unary_union(holes)), *vias])
    net = copper({F: sheet}, [{F: via} for via in vias], turn, move)
    left = [n for n, via in enumerate(vias) if via.centroid.x < 10]
    found = net.cut(left, [n for n in range(len(vias)) if n not in left])
    assert found is not None
    assert found[0] * NM == pytest.approx(2 * 1.9 + 6 * 1.3, abs=5 * EXACT)
    assert widths(found[1]) == [1.3] * 6 + [1.9] * 2


@pytest.mark.parametrize("step", [0.05, 0.1, 0.4])
def test_the_neck_does_not_depend_on_how_far_apart_the_points_along_an_edge_are(step):
    sheets, lumps, exact, turn = scattered(3, 30, True)
    assert neck(sheets, lumps, turn, step=step)[0] == pytest.approx(exact, abs=5 * EXACT)
    assert neck(*hourglass(0.4), 17, step=step)[0] == pytest.approx(1.5242, abs=1e-4)


# Boards: a pour, as pkidl's model fills it and as KiCad did.

OUTLINE = [(0.0, 0.0), (30.0, 0.0), (30.0, 30.0), (0.0, 30.0)]
SQUARE = [(2.0, 2.0), (28.0, 2.0), (28.0, 28.0), (2.0, 28.0)]
FILL = (OUTLINE, 0.5)


def pad(ref, x, y, net="GND", *, kind="smd rect", size="1 1", more=""):
    """A footprint of one pad at (x, y)."""
    layers = '"*.Cu"' if "thru_hole" in kind else '"F.Cu"'
    return (f'(footprint "t" (layer "F.Cu") (at {x} {y} 0) (property "Reference" "{ref}") '
            f'(pad "1" {kind} (at 0 0 0) (size {size}) {more} (layers {layers}) '
            f'(net "{net}")))')  # fmt: skip


def pour(net="GND", layer=F, connect="", filled=""):
    """A pour over the square that joins its pads by reliefs, a gap of 0.5 mm round
    each and spokes 0.5 mm wide, or as *connect* says; with KiCad's fill of it where
    one is given."""
    xy = " ".join(f"(xy {x} {y})" for x, y in SQUARE)
    return (f'(zone (net "{net}") (layer "{layer}") (connect_pads {connect} (clearance 0.2)) '
            f"(min_thickness 0.25) (fill yes (thermal_gap 0.5) (thermal_bridge_width 0.5)) "
            f"(polygon (pts {xy})) {filled})")  # fmt: skip


def track(net, a, b, wide=0.5, layer=F):
    return (f"(segment (start {a[0]} {a[1]}) (end {b[0]} {b[1]}) (width {wide}) "
            f'(layer "{layer}") (net "{net}"))')  # fmt: skip


def board(*nodes):
    return [parse(node) for node in nodes]


TWO = [pad("C1", 5, 15), pad("C2", 25, 15)]


def test_a_pad_on_a_relief_is_its_spokes_as_the_model_of_the_fill_has_them():
    found = Necks(board(*TWO, pour()), FILL).between("GND", ["C1.1"], ["C2.1"])
    assert found is not None
    assert (found.width, found.filled) == (2 * mm, MODEL)
    # The cut is round the pad at the end it starts from, a spoke a piece.
    assert [(p.width, p.layer, p.of) for p in found.across] == [
        (0.5 * mm, F, "the relief of C1.1")
    ] * 4
    assert sorted((p.at[0].mm, p.at[1].mm) for p in found.across) == [
        (4.5, 15.0), (5.0, 14.5), (5.0, 15.5), (5.5, 15.0)]  # fmt: skip
    # Copper of another net where a spoke would go takes the spoke: all of it, and
    # so does copper that leaves the spoke some of its width, as the model has it.
    for x, y in ((6.6, 15), (6.85, 15.85)):
        blocked = pad("X1", x, y, "SIG")
        found = Necks(board(*TWO, blocked, pour()), FILL).between("GND", ["C1.1"], ["C2.1"])
        assert found is not None and found.width == 1.5 * mm and len(found.across) == 3
    # A spoke as wide as the pad says its own are.
    wide = pad("C1", 5, 15, more="(thermal_bridge_width 0.3)")
    found = Necks(board(wide, TWO[1], pour()), FILL).between("GND", ["C1.1"], ["C2.1"])
    assert found is not None and found.width == 1.2 * mm


def test_a_pad_joined_solidly_is_cut_round_and_one_joined_to_no_pour_is_not_joined():
    solid = Necks(board(*TWO, pour(connect="yes")), FILL).between("GND", ["C1.1"], ["C2.1"])
    assert solid is not None and solid.width == 4 * mm
    assert [(p.width, p.of) for p in solid.across] == [(4 * mm, "the copper round C1.1")]
    apart = Necks(board(*TWO, pour(connect="no")), FILL).between("GND", ["C1.1"], ["C2.1"])
    assert apart == Neck(Length(0), (), "")
    # One pad that says it joins solidly, in a pour of reliefs: the other's spokes.
    one = pad("C1", 5, 15, more="(zone_connect 2)")
    found = Necks(board(one, TWO[1], pour()), FILL).between("GND", ["C1.1"], ["C2.1"])
    assert found is not None and found.width == 2 * mm
    assert {p.of for p in found.across} == {"the relief of C2.1"}


def test_a_track_beside_a_relief_is_cut_as_well_and_is_said_to_be_a_track():
    # A track 0.2 mm wide from C1 out by its corner, between two of its spokes, and
    # into the pour: round C1 it is one more way out, and C2's four spokes are then
    # the least.
    join = track("GND", (5, 15), (8, 18), 0.2)
    found = Necks(board(*TWO, join, pour()), FILL).between("GND", ["C1.1"], ["C2.1"])
    assert found is not None and found.width == 2 * mm
    assert {p.of for p in found.across} == {"the relief of C2.1"}
    # With one from each pad, each end is five ways out: four spokes and a track.
    more = track("GND", (25, 15), (22, 18), 0.2)
    found = Necks(board(*TWO, join, more, pour()), FILL).between("GND", ["C1.1"], ["C2.1"])
    assert found is not None and found.width == 2.2 * mm
    assert [(p.width, p.of) for p in found.across] == [
        *[(0.5 * mm, "the relief of C1.1")] * 4,
        (0.2 * mm, "track"),
    ]
    # A track that lies along a spoke is the spoke's copper over again, and adds none.
    along = track("GND", (5, 15), (5, 20))
    found = Necks(board(*TWO, along, more, pour()), FILL).between("GND", ["C1.1"], ["C2.1"])
    assert found is not None and found.width == 2 * mm
    assert sorted(p.of for p in found.across) == ["the relief of C1.1"] * 3 + ["track"]


def test_a_pad_through_the_board_joins_a_pour_on_each_side_of_it():
    holed = [pad(ref, x, 15, kind="thru_hole circle", size="2 2", more="(drill 1)")
             for ref, x in (("J1", 5), ("J2", 25))]  # fmt: skip
    one = Necks(board(*holed, pour()), FILL).between("GND", ["J1.1"], ["J2.1"])
    both = Necks(board(*holed, pour(), pour(layer=B)), FILL).between("GND", ["J1.1"], ["J2.1"])
    assert one is not None and both is not None
    assert (one.width, both.width) == (2 * mm, 4 * mm)
    assert sorted(p.layer for p in both.across) == [B] * 4 + [F] * 4


def kicads(*rings, layer=F):
    """KiCad's fill of a zone on *layer*: a piece each of *rings*."""
    pts = [" ".join(f"(xy {x} {y})" for x, y in ring) for ring in rings]
    return " ".join(f'(filled_polygon (layer "{layer}") (pts {ring}))' for ring in pts)


def test_kicads_fill_is_what_is_measured_where_the_board_has_it():
    # A fill no model would make: a strip 1.25 mm wide from pad to pad, and no relief.
    strip = [(4, 14.5), (26, 14.5), (26, 15.75), (4, 15.75)]
    items = board(*TWO, pour(filled=kicads(strip)))
    for fill in (FILL, None):
        found = Necks(items, fill).between("GND", ["C1.1"], ["C2.1"])
        assert found is not None and (found.width, found.filled) == (1.25 * mm, KICAD)
        assert [(p.width, p.at, p.layer, p.of) for p in found.across] == [
            (1.25 * mm, (5.5 * mm, 15.125 * mm), F, "the relief of C1.1")
        ]
    # A zone the board has no fill of is the model's where there is an outline to fill
    # inside, and is no copper where there is none.
    bare = board(*TWO, pour())
    assert Necks(bare, FILL).between("GND", ["C1.1"], ["C2.1"]) == Necks(
        board(*TWO, pour()), FILL
    ).between("GND", ["C1.1"], ["C2.1"])
    assert Necks(bare).between("GND", ["C1.1"], ["C2.1"]) == Neck(Length(0), (), "")
    # One zone of each: both are measured, and both are said.
    holed = [pad(ref, x, 15, kind="thru_hole circle", size="2 2", more="(drill 1)")
             for ref, x in (("J1", 5), ("J2", 25))]  # fmt: skip
    mixed = board(*holed, pour(filled=kicads(strip)), pour(layer=B))
    found = Necks(mixed, FILL).between("GND", ["J1.1"], ["J2.1"])
    assert found is not None
    assert (found.width, found.filled) == (3.25 * mm, f"{KICAD} and {MODEL}")


def test_a_pad_through_the_board_has_its_copper_on_an_inner_layer_too():
    # A plane inside the board, as KiCad filled it: a strip 1.25 mm wide from pin to
    # pin. The pins go through it, and nothing else joins them.
    holed = [pad(ref, x, 15, kind="thru_hole circle", size="2 2", more="(drill 1)")
             for ref, x in (("J1", 5), ("J2", 25))]  # fmt: skip
    strip = [(4, 14.5), (26, 14.5), (26, 15.75), (4, 15.75)]
    inner = pour(layer="In1.Cu", connect="yes", filled=kicads(strip, layer="In1.Cu"))
    found = Necks(board(*holed, inner)).between("GND", ["J1.1"], ["J2.1"])
    assert found is not None and (found.width, found.filled) == (1.25 * mm, KICAD)
    assert [(p.layer, p.of) for p in found.across] == [("In1.Cu", "pour")]
    # A pad on the front alone is not on it.
    found = Necks(board(*TWO, inner)).between("GND", ["C1.1"], ["C2.1"])
    assert found is not None and found.width == Length(0)


def test_a_fill_written_with_a_slit_to_its_hole_is_the_copper_round_the_hole():
    # KiCad writes a fill with a hole as one outline that goes in to the hole along a
    # slit and back: a plate 10 mm wide with a hole 4 mm across is 3 mm each side.
    plate = [(4, 10), (26, 10), (26, 20), (4, 20), (4, 15), (13, 15), (13, 17), (17, 17),
             (17, 13), (13, 13), (13, 15), (4, 15)]  # fmt: skip
    found = Necks(board(*TWO, pour(connect="yes", filled=kicads(plate)))).between(
        "GND", ["C1.1"], ["C2.1"]
    )
    assert found is not None and found.width == 4 * mm  # round a pad, 1 mm square
    wide = [pad(ref, x, 15, size="1 9.5") for ref, x in (("C1", 5), ("C2", 25))]
    found = Necks(board(*wide, pour(connect="yes", filled=kicads(plate)))).between(
        "GND", ["C1.1"], ["C2.1"]
    )
    assert found is not None and found.width == 6 * mm
    assert [(p.width, p.of) for p in found.across] == [(3 * mm, "pour")] * 2


def test_a_piece_is_where_its_cut_is_and_what_it_is_of():
    assert Piece(0.5 * mm, (1 * mm, 2 * mm), F, "track").at == (1 * mm, 2 * mm)
    # A track from pad to pad, with no pour: one piece, of track, at the middle of the
    # cut across it.
    found = Necks(board(*TWO, track("GND", (5, 15), (25, 15), 0.4))).between(
        "GND", ["C1.1"], ["C2.1"]
    )
    assert found is not None and (found.width, found.filled) == (0.4 * mm, "")
    (piece,) = found.across
    assert (piece.width, piece.layer, piece.of) == (0.4 * mm, F, "track")
    assert piece.at[1] == 15 * mm and 5.5 * mm <= piece.at[0] <= 24.5 * mm
    # A net with nothing between its pads.
    assert Necks(board(*TWO)).between("GND", ["C1.1"], ["C2.1"]) == Neck(Length(0), (), "")
