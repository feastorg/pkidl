"""Pour fills before routing, so the router can treat the pours as planes.

KiCad fills the pours after routing, and its fill is the one the board keeps. Before
routing there is no fill to give the router, so ``prefill`` makes one the same way:
each zone's outline, inside the board edge, less every other net's copper grown by
the most clearance asked of it (the zone's, its net's, its pad's own), less
higher-priority pours of other nets and no-pour rule areas, with pieces that touch no
pad or via of the net dropped (KiCad's default island removal). The result steers the
router; DRC on KiCad's own fill decides.

``cut_off`` asks the same fill a question once a board is routed: is each poured net
still one piece, or have tracks across a pour left some of its pads joined to nothing
but each other. A pad is joined to a pour as KiCad joins it: through the spokes of its
thermal relief, of which KiCad asks two, or all round where the zone, the footprint or
the pad says solid. A track or a via is joined where it touches.

It is a model, and is meant to be wrong only one way, calling a pad cut off that KiCad
joins: a spoke counts only where the fill covers its whole width out past the gap, and
not where it would cross the gap cut round another pad of the net, though KiCad may
join two such pads spoke to spoke. It has been wrong the other way five times, each
found by trying to break it and each now a test, which is why a build asks KiCad itself
where KiCad is installed (``pkidl.kicad``).
KiCad's DRC of its own fill is the judge of a built board.

Pads are modelled by their size and rotation as rectangles, ovals and circles;
custom pad primitives are taken as their bounding rectangle.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Callable, Collection
from dataclasses import dataclass

from shapely import affinity
from shapely.geometry import LineString, Polygon, box
from shapely.geometry import Point as SPoint
from shapely.geometry.base import BaseGeometry
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from pkidl.board import Point
from pkidl.circuit import natural
from pkidl.footprint import pad_at
from pkidl.sexpr import Node, Sym, find, find_all

Plane = tuple[str, str, list[Point]]  # net, layer, hole-free polygon in board mm
SPOKES = 2  # the spokes KiCad asks of a thermal relief before it calls it starved
QUAD_SEGS = 16  # segments per quarter circle in grown shapes


def _grow(shape: BaseGeometry, d: float) -> BaseGeometry:
    """*shape* grown by *d*, its arcs circumscribed: never closer than *d*."""
    return shape.buffer(d / math.cos(math.pi / (4 * QUAD_SEGS)), quad_segs=QUAD_SEGS)


def _xy(node: Node, key: str) -> Point:
    v = find(node, key)
    assert v is not None
    return (float(v[1]), float(v[2]))


def _layers(node: Node) -> list[str]:
    one, many = find(node, "layer"), find(node, "layers")
    names = [str(v) for v in (many[1:] if many is not None else one[1:] if one is not None else [])]
    return ["F.Cu", "B.Cu"] if "*.Cu" in names or "F&B.Cu" in names else names


def _net(node: Node) -> str:
    n = find(node, "net")
    return "" if n is None else str(n[-1])


def _turned(shape: BaseGeometry, fp: Node, pad: Node) -> BaseGeometry:
    """*shape*, drawn about a pad's copper in the pad's own frame, where it is on the
    board. A pad's place is its hole's, and its copper can be off that by the drill's
    ``offset``. KiCad's pad angle is on the board (footprint rotation included),
    counter-clockwise with y down: a negative rotation in shapely's y-up sense."""
    at, drill = find(pad, "at"), find(pad, "drill")
    angle = float(at[3]) if at is not None and len(at) > 3 else 0.0
    off = find(drill, "offset") if drill is not None else None
    if off is not None:
        shape = affinity.translate(shape, float(off[1]), float(off[2]))
    c = pad_at(fp, pad)
    return affinity.translate(affinity.rotate(shape, -angle, origin=(0, 0)), c[0], c[1])


def _pad_shape(fp: Node, pad: Node) -> BaseGeometry:
    """A pad's copper: its rectangle, oval or circle, rotated, at its board position."""
    size = find(pad, "size")
    assert size is not None
    w, h = float(size[1]), float(size[2]) if len(size) > 2 else float(size[1])
    kind = str(pad[3])
    if kind == "circle":
        shape = SPoint(0, 0).buffer(w / 2)
    elif kind == "oval":
        r, half = min(w, h) / 2, abs(w - h) / 2
        line = LineString([(-half, 0), (half, 0)] if w >= h else [(0, -half), (0, half)])
        shape = line.buffer(r) if half > 0 else SPoint(0, 0).buffer(r)
    else:
        shape = box(-w / 2, -h / 2, w / 2, h / 2)
    return _turned(shape, fp, pad)


def _relief(zone: Node, fp: Node, pad: Node) -> str:
    """How *pad* joins *zone*'s fill: ``solid``, ``thermal`` or ``none``. The pad's own
    ``zone_connect`` says first, then its footprint's, then the zone's
    ``connect_pads``."""
    own = find(pad, "zone_connect") or find(fp, "zone_connect")
    if own is not None:
        return {"0": "none", "2": "solid"}.get(str(own[1]), "thermal")
    said = find(zone, "connect_pads")
    mode = (
        str(said[1]) if said is not None and len(said) > 1 and not isinstance(said[1], list) else ""
    )
    if mode == "thru_hole_only":  # reliefs for pads with holes, the rest solid
        return "thermal" if str(pad[2]) == "thru_hole" else "solid"
    return {"yes": "solid", "no": "none"}.get(mode, "thermal")


def _gap(zone: Node, pad: Node) -> float:
    """The gap of *pad*'s thermal relief in *zone*: the pad's own where it says."""
    return _num(pad, "thermal_gap", default=_num(zone, "fill", "thermal_gap", 0.5))


def _spokes(fp: Node, pad: Node, zone: Node) -> list[BaseGeometry]:
    """Where each spoke of *pad*'s thermal relief in *zone* has to have copper: from the
    middle of the pad's copper out across the gap and as far again as the fill's least
    width, as wide as a spoke. KiCad draws four: at the pad's ``thermal_bridge_angle``
    where it says one, or else along a pad's own sides and on the diagonals of a round
    one (measured on fills KiCad made). The gap and the width are the pad's own where
    it says them."""
    size = find(pad, "size")
    assert size is not None
    w, h = float(size[1]), float(size[2]) if len(size) > 2 else float(size[1])
    round_ = str(pad[3]) == "circle"
    first = _num(pad, "thermal_bridge_angle", default=45.0 if round_ else 0.0) % 90
    beyond = _gap(zone, pad) + _num(zone, "min_thickness", default=0.25)
    wide = _num(pad, "thermal_bridge_width",
                default=_num(zone, "fill", "thermal_bridge_width", 0.5))  # fmt: skip
    out = []
    for turn in (first, first + 90, first + 180, first + 270):
        # As far as the pad reaches that way, at most: its half diagonal off its axes.
        reach = (w / 2 if round_ else h / 2 if turn % 180 == 90 else w / 2 if turn % 180 == 0
                 else math.hypot(w, h) / 2) + beyond  # fmt: skip
        strip = affinity.rotate(box(0, -wide / 2, reach, wide / 2), turn, origin=(0, 0))
        out.append(_turned(strip, fp, pad))
    return out


Copper = tuple[str, BaseGeometry, float, tuple[Node, Node] | None]


def _copper(items: list[Node], layer: str) -> list[Copper]:
    """Every pad, track and via on *layer*: its net, its shape, the clearance it asks
    for itself (a pad's own or its footprint's, else 0) and, for a pad, its footprint
    and itself."""
    out: list[Copper] = []
    for item in items:
        head = str(item[0])
        if head == "footprint":
            for pad in find_all(item, "pad"):
                if layer in _layers(pad) and find(pad, "size") is not None:
                    # A pad's own clearance, or its footprint's where it says none.
                    own = _num(pad, "clearance") or _num(item, "clearance")
                    out.append((_net(pad), _pad_shape(item, pad), own, (item, pad)))
        elif head == "segment" and layer in _layers(item):
            w = _num(item, "width")
            out.append(
                (_net(item), LineString([_xy(item, "start"), _xy(item, "end")]).buffer(w / 2),
                 0.0, None)
            )  # fmt: skip
        elif head == "via":
            dot = SPoint(_xy(item, "at")).buffer(_num(item, "size") / 2)
            out.append((_net(item), dot, 0.0, None))
    return out


def _outline(zone: Node) -> Polygon:
    poly = find(zone, "polygon")
    assert poly is not None
    return Polygon([(float(p[1]), float(p[2])) for p in find_all(find(poly, "pts"), "xy")])  # type: ignore[arg-type]


def _num(node: Node, key: str, sub: str | None = None, default: float = 0.0) -> float:
    v = find(node, key)
    if v is not None and sub is not None:
        v = find(v, sub)
    return float(v[1]) if v is not None and len(v) > 1 else default


def _no_pour(zone: Node) -> bool:
    """A rule area that keeps pours out."""
    rules = find(zone, "keepout")
    pour = find(rules, "copperpour") if rules is not None else None
    return pour is not None and str(pour[1]) == "not_allowed"


def _slit(poly: Polygon) -> list[Point]:
    """*poly* as one outline that reaches each hole along a zero-width slit, as KiCad
    writes a fill: a DSN plane can't have holes, and the router has to connect every
    plane of a net to the others, so a fill split into pieces would be routed between.

    Holes are joined in order of their topmost point (least y), each by a vertical slit
    from that point up to the outline built so far: whatever lies above it on that line
    has already been joined, so a slit never crosses a hole.
    """
    poly = orient(poly, sign=1.0)  # exterior one way round, holes the other
    ring: list[Point] = [(x, y) for x, y in poly.exterior.coords[:-1]]
    holes = sorted(
        ([(x, y) for x, y in h.coords[:-1]] for h in poly.interiors),
        key=lambda h: min(y for _, y in h),
    )
    for hole in holes:
        k = min(range(len(hole)), key=lambda i: (hole[i][1], hole[i][0]))
        px, py = hole[k]
        best: tuple[float, int, Point] | None = None
        for i, (a, b) in enumerate(zip(ring, ring[1:] + ring[:1], strict=True)):
            if (a[0] - px) * (b[0] - px) > 0 or a[0] == b[0]:
                continue  # the slit's line x = px doesn't cross this edge (or runs along it)
            y = a[1] + (px - a[0]) * (b[1] - a[1]) / (b[0] - a[0])
            if y <= py and (best is None or y > best[0]):
                best = (y, i, (px, y))
        assert best is not None, "a hole with no outline above it"
        _, i, x = best
        loop = hole[k:] + hole[:k] + [hole[k]]
        ring = ring[: i + 1] + [x, *loop, x] + ring[i + 1 :]
    return ring


def fills(
    items: list[Node],
    outline: list[Point] | Polygon,
    edge: float,
    clearances: dict[str, float] | None = None,
) -> list[tuple[str, str, Polygon]]:
    """Each pour's fill, as the pieces it is in: (net, layer, piece), holes and all.

    *items* are the board's nodes (footprints, tracks, vias, zones); *outline* the board
    edge, kept *edge* away from: its corners in order, or the area inside it with any
    cut-outs as holes (``Board.edge()``). Zones are filled highest priority first; a
    pour of another net already filled is copper to keep clear of. *clearances* (net:
    mm) are the nets' class clearances: a pour keeps the larger of its own and the other
    net's, as KiCad does. The clearance given for ``""`` is kept from what is on no net,
    an unplated hole among it, of which KiCad asks its hole clearance. A piece that
    touches no pad, track or via of its net is left out.
    """
    cl = clearances or {}
    board = (outline if isinstance(outline, Polygon) else Polygon(outline)).buffer(-edge)
    zones = [z for z in items if str(z[0]) == "zone"]
    nopour = {
        layer: unary_union([_outline(z) for z in zones if layer in _layers(z) and _no_pour(z)])
        for layer in ("F.Cu", "B.Cu")
    }
    copper = {layer: _copper(items, layer) for layer in ("F.Cu", "B.Cu")}
    filled: dict[str, list[tuple[str, BaseGeometry]]] = {"F.Cu": [], "B.Cu": []}
    found: list[tuple[str, str, Polygon]] = []
    pours = [z for z in zones if find(z, "keepout") is None and _net(z)]
    for zone in sorted(pours, key=lambda z: -_num(z, "priority")):
        net = _net(zone)
        gap = _num(zone, "connect_pads", "clearance", 0.5)
        thick = _num(zone, "min_thickness", default=0.25)
        for layer in _layers(zone):
            if layer not in filled:
                continue
            area = _outline(zone).intersection(board).difference(nopour[layer])
            # Other nets' copper, each kept the most that is asked of it: the pour's
            # clearance, its net's, or its own. And the net's own pads that join no pour:
            # KiCad cuts the fill back from those as from any other copper.
            foreign = [_grow(s, max(gap, cl.get(n, 0.0), own))
                       for n, s, own, _ in copper[layer] if n != net]  # fmt: skip
            apart = [(s, own) for n, s, own, of in copper[layer]
                     if n == net and of is not None and _relief(zone, *of) == "none"]  # fmt: skip
            foreign += [_grow(s, max(gap, own)) for s, own in apart]
            foreign += [_grow(s, max(gap, cl.get(n, 0.0))) for n, s in filled[layer] if n != net]
            if foreign:
                area = area.difference(unary_union(foreign))
            area = area.buffer(-thick / 2).buffer(thick / 2)  # nothing thinner than min_thickness
            # A piece is kept for touching copper of its net that it can be joined to.
            own = unary_union([
                s for n, s, _, of in copper[layer]
                if n == net and (of is None or _relief(zone, *of) != "none")
            ] or [Polygon()])  # fmt: skip
            pieces = [
                p
                for p in getattr(area, "geoms", [area])
                if isinstance(p, Polygon) and not p.is_empty
            ]
            kept = [p for p in pieces if p.intersects(own)]
            filled[layer].extend((net, p) for p in kept)
            found.extend((net, layer, p) for p in kept)
    return found


def prefill(
    items: list[Node],
    outline: list[Point] | Polygon,
    edge: float,
    clearances: dict[str, float] | None = None,
) -> list[Plane]:
    """Each pour's fill before routing, as hole-free planes: (net, layer, polygon).
    The pieces are ``fills``'s, each written as one outline that reaches its holes by
    slits."""
    return [(net, layer, [(round(x, 4), round(y, 4)) for x, y in _slit(piece)])
            for net, layer, piece in fills(items, outline, edge, clearances)]  # fmt: skip


def landings(
    items: list[Node],
    outline: list[Point] | Polygon,
    edge: float,
    clearances: dict[str, float] | None = None,
    *,
    wide: float,
    but: Collection[str] = (),
) -> list[Plane]:
    """Each pour's fill of a routed board where a track *wide* mm across can end in it:
    planes as ``prefill`` makes them, of each piece of the fill less what is nearer its
    edge than half that width. The middle of a track anywhere in one has all its copper
    in the pour, which a point of the fill itself does not: a router told of the whole
    fill can choose to end a track in a corner of it that the track does not fit, and
    lay nothing. A neck of the fill narrower than the track parts a piece in two. A
    part with no pad of its net on it is left out, the pads *but* (as ``C5.1``) not
    counted: with the pads that are cut off given, a piece apart from the rest is no
    plane, and a track that ends in a plane ends on the rest of the net. Other
    arguments as for ``fills``."""
    copper = {layer: _copper(items, layer) for layer in ("F.Cu", "B.Cu")}
    found: list[Plane] = []
    for net, layer, piece in fills(items, outline, edge, clearances):
        pads = [s for n, s, _, of in copper[layer] if n == net and of is not None
                and f"{_ref(of[0])}.{of[1][1]}" not in but]  # fmt: skip
        inner = piece.buffer(-wide / 2)
        for part in getattr(inner, "geoms", [inner]):
            if (
                isinstance(part, Polygon)
                and not part.is_empty
                and any(part.intersects(s) for s in pads)
            ):
                found.append((net, layer, [(round(x, 4), round(y, 4)) for x, y in _slit(part)]))
    return found


@dataclass(frozen=True)
class Cut:
    """Pads of a poured net that the board's copper joins to each other and not to the
    rest of their net: which *pads*, as ``C5.2``; the *layer* of the piece of pour they
    are on, or None where no pour reaches them; and the nets whose tracks run beside
    that piece, *fenced* in by them. One that KiCad reported has what KiCad said it
    *seen* as, in its own words.

    A *starved* one is not cut off: it is one pad whose thermal relief on *layer* does
    not join it to its pour as KiCad asks (``starved``), whatever else joins it."""

    net: str
    pads: tuple[str, ...]
    layer: str | None = None
    fenced: tuple[str, ...] = ()
    seen: str = ""
    starved: bool = False

    def __str__(self) -> str:
        if self.seen:
            return f"KiCad, of {self.net}: {self.seen}"
        pads = ", ".join(self.pads)
        are = "is" if len(self.pads) == 1 else "are"
        if self.starved:
            return (f"{pads} {are} starved of the pour of {self.net} on {self.layer}: fewer "
                    f"than {SPOKES} spokes of its relief reach a piece of the pour that "
                    f"another pad or a via of {self.net} is on")  # fmt: skip
        if self.layer is None:
            return f"{pads} {are} cut off from the rest of {self.net}: no pour reaches there"
        by = f", fenced in by tracks of {', '.join(self.fenced)}" if self.fenced else ""
        return (f"{pads} {are} cut off from the rest of {self.net}: on a piece of its pour "
                f"on {self.layer} that is apart from the rest{by}")  # fmt: skip


Copper_of = tuple[str, dict[str, BaseGeometry]]  # a pad's name or "", its copper by layer


def _pours(items: list[Node]) -> list[Node]:
    return [z for z in items if str(z[0]) == "zone" and find(z, "keepout") is None and _net(z)]


def _on(items: list[Node], net: str) -> tuple[list[Copper_of], dict[int, tuple[Node, Node]],
                                              set[int]]:  # fmt: skip
    """What is on *net*: each pad, track and via, with its name where it is a pad and
    its copper on each layer; for each that is a pad, its footprint and itself; and
    which are vias."""
    nodes: list[Copper_of] = []
    of: dict[int, tuple[Node, Node]] = {}
    vias: set[int] = set()
    for item in items:
        head = str(item[0])
        if head == "footprint":
            ref = next(str(p[2]) for p in find_all(item, "property") if p[1] == "Reference")
            for pad in find_all(item, "pad"):
                if _net(pad) == net and find(pad, "size") is not None:
                    shape = _pad_shape(item, pad)
                    of[len(nodes)] = (item, pad)
                    nodes.append((f"{ref}.{pad[1]}", dict.fromkeys(_layers(pad), shape)))
        elif head == "segment" and _net(item) == net:
            line = LineString([_xy(item, "start"), _xy(item, "end")])
            nodes.append(("", {_layers(item)[0]: line.buffer(_num(item, "width") / 2)}))
        elif head == "via" and _net(item) == net:
            dot = SPoint(_xy(item, "at")).buffer(_num(item, "size") / 2)
            vias.add(len(nodes))
            nodes.append(("", dict.fromkeys(("F.Cu", "B.Cu"), dot)))
    return nodes, of, vias


def _parts(
    zones: list[Node],
    pieces: list[tuple[str, str, Polygon]],
    net: str,
    nodes: list[Copper_of],
    of: dict[int, tuple[Node, Node]],
) -> tuple[list[tuple[str, Polygon]], list[tuple[Node, BaseGeometry]]]:
    """The fill of *net* as KiCad leaves it: each piece cut away, by its gap, round every
    pad of the net that has a relief there, and what is left thinner than the fill's
    least width gone. A pad in the only way through a wall parts the pour so. Each part
    with its layer, and for each its zone and the piece uncut."""
    mine_zones = [z for z in zones if _net(z) == net]
    poured: list[tuple[str, Polygon]] = []
    whole: list[tuple[Node, BaseGeometry]] = []
    for layer, piece in [(layer, piece) for n, layer, piece in pieces if n == net]:
        on = [z for z in mine_zones if layer in _layers(z)]
        at = piece.representative_point()
        zone = next((z for z in on if _outline(z).contains(at)), on[0])
        rings = unary_union([
            nodes[k][1][layer].buffer(_gap(zone, of[k][1]))
            for k in of if layer in nodes[k][1] and _relief(zone, *of[k]) == "thermal"
        ] or [Polygon()])  # fmt: skip
        thick = _num(zone, "min_thickness", default=0.25)
        left = piece.difference(rings).buffer(-thick / 2).buffer(thick / 2)
        for part in getattr(left, "geoms", [left]):
            if isinstance(part, Polygon) and not part.is_empty:
                poured.append((layer, part))
                whole.append((zone, piece.buffer(0.001)))
    return poured, whole


def _joined(
    nodes: list[Copper_of],
    of: dict[int, tuple[Node, Node]],
    poured: list[tuple[str, Polygon]],
    whole: list[tuple[Node, BaseGeometry]],
) -> tuple[Callable[[int], int], dict[int, list[int]], dict[int, list[int]]]:
    """What the copper of a net joins: *nodes* and after them the parts of its pour
    (*poured*, *whole*: ``_parts``), each numbered in that order. Gives the group a
    number is in, as the number of one of the group; for each pad with a relief, the
    part each spoke of its that has its copper reaches (a part's place in *poured*,
    once a spoke); and for each pad joined solidly, the parts it touches.

    With no parts it is what the pads, tracks and vias join by themselves."""
    first = len(nodes)
    nodes = [*nodes, *(("", {layer: part}) for layer, part in poured)]
    near = [part.buffer(0.001) for _, part in poured]
    group = list(range(len(nodes)))
    spoked: dict[int, list[int]] = {}
    solid: dict[int, list[int]] = {}

    def root(i: int) -> int:
        while group[i] != i:
            group[i] = group[group[i]]
            i = group[i]
        return i

    # A pad and the pour, as KiCad joins them: solidly where it touches, or by the
    # spokes of its relief, each with copper from the pad across its own gap and on
    # into a piece of the fill. Two spokes in all, and it is joined to every piece
    # one of them reaches.
    for i, (fp, pad) in of.items():
        reached: list[int] = []
        for j, (layer, part) in enumerate(poured):
            if layer not in nodes[i][1]:
                continue
            zone, uncut = whole[j]
            shape, how = nodes[i][1][layer], _relief(zone, fp, pad)
            if how == "solid" and shape.intersects(part):
                group[root(first + j)] = root(i)
                solid.setdefault(i, []).append(j)
            elif how == "thermal":
                ring = shape.buffer(_gap(zone, pad))
                reached += [j for s in _spokes(fp, pad, zone)
                            if uncut.covers(s.intersection(ring).difference(shape))
                            and near[j].covers(s.difference(ring))]  # fmt: skip
        if reached:
            spoked[i] = reached
        if len(reached) >= SPOKES:
            for j in reached:
                group[root(first + j)] = root(i)
    for i in range(len(nodes)):
        mine = nodes[i][1]
        for j in range(i + 1, len(nodes)):
            if root(i) == root(j) or (i in of and j >= first):
                continue
            theirs = nodes[j][1]
            if any(k in theirs and mine[k].intersects(theirs[k]) for k in mine):
                group[root(j)] = root(i)
    return root, spoked, solid


def starved(
    items: list[Node],
    outline: list[Point] | Polygon,
    edge: float,
    clearances: dict[str, float] | None = None,
) -> list[Cut]:
    """The pads of a routed board that a thermal relief does not join to their pour as
    KiCad asks, whatever else joins them: a ``Cut`` for each, ``starved``, with the
    layer. Arguments as for ``fills``.

    A pad is starved on a layer where a spoke of its relief has its copper, and fewer
    than ``SPOKES`` of them reach a part of the fill that another pad of the net is
    joined to, by a spoke or solidly, or that a via of the net is on. A part that only
    the pad holds is an island KiCad does not count."""
    zones = _pours(items)
    pieces = fills(items, outline, edge, clearances)
    found: list[Cut] = []
    for net in sorted({_net(z) for z in zones}):
        nodes, of, vias = _on(items, net)
        poured, whole = _parts(zones, pieces, net, nodes, of)
        _, spoked, solid = _joined(nodes, of, poured, whole)
        held: dict[int, set[int]] = {}  # a part: the pads joined to it
        for joins in (spoked, solid):
            for i, parts in joins.items():
                for j in parts:
                    held.setdefault(j, set()).add(i)
        for i, parts in sorted(spoked.items(), key=lambda kv: natural(nodes[kv[0]][0])):
            for layer in sorted({poured[j][0] for j in parts}):
                good = [
                    j for j in parts
                    if poured[j][0] == layer
                    and (held[j] - {i} or any(nodes[v][1][layer].intersects(poured[j][1])
                                              for v in vias))
                ]  # fmt: skip
                if len(good) < SPOKES:
                    found.append(Cut(net, (nodes[i][0],), layer, starved=True))
    return found


def _says(fp: Node, pad: Node) -> str:
    """What *pad*, or else its footprint, says of how it joins a pour: ``none``,
    ``solid``, or nothing where neither says or what is said is a relief."""
    own = find(pad, "zone_connect") or find(fp, "zone_connect")
    return "" if own is None else {"0": "none", "2": "solid"}.get(str(own[1]), "")


def spare(items: list[Node]) -> set[str]:
    """The pads, as ``C5.1``, that a pour can be spared: taken off it with no
    connection of the board changed. Each is on a poured net that its pads, tracks and
    vias join into one piece by themselves, with no pour, and neither it nor its
    footprint says that it joins no pour, which leaves nothing to take off, or joins
    solidly, which has no relief to starve. A pad's copper is taken as the box round
    it, as everywhere here: a track that ends in the cut corner of a rounded pad is
    taken to join it."""
    found: set[str] = set()
    for net in sorted({_net(z) for z in _pours(items)}):
        nodes, of, _ = _on(items, net)
        root, _, _ = _joined(nodes, of, [], [])
        if len({root(i) for i in of}) == 1:
            said: dict[str, set[str]] = {}
            for i, (fp, pad) in of.items():
                said.setdefault(nodes[i][0], set()).add(_says(fp, pad))
            found |= {name for name, says in said.items() if says == {""}}
    return found


def unreached(
    items: list[Node],
    outline: list[Point] | Polygon,
    edge: float,
    clearances: dict[str, float] | None = None,
) -> dict[str, str]:
    """The pads of a routed board, as ``C5.1`` and each with its net, that are cut off
    (``cut_off``) and that a pour of their net, drawn over them to join them by a
    relief, joins to nothing: one no pour reaches, which a router told of that pour
    counts as joined, and one alone on a piece of pour apart from the rest, whose
    relief is starved once a track joins it. Arguments as for ``fills``. A pad that
    joins no pour or joins solidly, by what it, its footprint or the zone says, is not
    among them."""
    zones = _pours(items)
    found: dict[str, str] = {}
    for c in cut_off(items, outline, edge, clearances):
        if c.layer is not None and len(c.pads) > 1:
            continue
        nodes, of, _ = _on(items, c.net)
        for i, (fp, pad) in of.items():
            if nodes[i][0] in c.pads and any(
                _net(z) == c.net and _relief(z, fp, pad) == "thermal"
                and any(layer in nodes[i][1] and _outline(z).intersects(nodes[i][1][layer])
                        for layer in _layers(z))
                for z in zones
            ):  # fmt: skip
                found[nodes[i][0]] = c.net
    return found


def surplus(items: list[Node], cuts: Collection[Cut]) -> set[str]:
    """Of the pads each of *cuts* names as cut off together, those a router asked to
    join them to the rest of their net is better not told of, as ``C5.1``: each but the
    first that no track or via joins to anything, the piece of pour they are on being
    all that joins it to the others. One track to the first joins them all; a router
    told of each lays a track to each."""
    found: set[str] = set()
    for c in cuts:
        if c.starved or len(c.pads) < 2:
            continue
        nodes, of, _ = _on(items, c.net)
        root, _, _ = _joined(nodes, of, [], [])
        size: dict[int, int] = {}
        for i in range(len(nodes)):
            size[root(i)] = size.get(root(i), 0) + 1
        found |= {nodes[i][0] for i in of
                  if nodes[i][0] in c.pads[1:] and size[root(i)] == 1}  # fmt: skip
    return found


def unnet(items: list[Node], pads: Collection[str]) -> list[Node]:
    """*items* with each of *pads* (as ``C5.1``) on no net, in a copy of its footprint:
    copper a router keeps clear of and joins nothing to. With no pads, the items as
    they are."""
    out = []
    for item in items:
        if str(item[0]) == "footprint" and any(
            f"{_ref(item)}.{pad[1]}" in pads for pad in find_all(item, "pad")
        ):
            item = copy.deepcopy(item)
            for pad in find_all(item, "pad"):
                net = find(pad, "net")
                if f"{_ref(item)}.{pad[1]}" in pads and net is not None:
                    net[1:] = [""]
        out.append(item)
    return out


def unjoin(items: list[Node], pads: Collection[str]) -> list[Node]:
    """*items* with each of *pads* (as ``C5.1``) off every pour: ``(zone_connect 0)`` on
    the pad, in a copy of its footprint. With no pads, the items as they are."""
    out = []
    for item in items:
        named = [] if str(item[0]) != "footprint" else [
            k for k, pad in enumerate(item)
            if isinstance(pad, list) and pad and str(pad[0]) == "pad" and len(pad) > 1
            and f"{_ref(item)}.{pad[1]}" in pads
        ]  # fmt: skip
        if named:
            item = copy.deepcopy(item)
            for k in named:
                pad = item[k]
                own, tail = find(pad, "zone_connect"), find(pad, "uuid")
                if own is not None:
                    own[1] = Sym("0")
                elif tail is not None:
                    pad.insert(pad.index(tail), [Sym("zone_connect"), Sym("0")])
                else:
                    pad.append([Sym("zone_connect"), Sym("0")])
        out.append(item)
    return out


def _ref(fp: Node) -> str:
    return next(str(p[2]) for p in find_all(fp, "property") if p[1] == "Reference")


def cut_off(
    items: list[Node],
    outline: list[Point] | Polygon,
    edge: float,
    clearances: dict[str, float] | None = None,
) -> list[Cut]:
    """What the pours of a routed board leave cut off: for each net that has a pour,
    the pads that its pads, tracks, vias and pieces of pour join to each other and not
    to the most of its pads. Arguments as for ``fills``. Nothing, where every poured
    net is one piece.

    A pad is joined to a piece of pour as KiCad joins it (see the module): by two
    spokes of its thermal relief, or by touching it where the connection is solid."""
    zones = _pours(items)
    pieces = fills(items, outline, edge, clearances)
    cuts: list[Cut] = []
    for net in sorted({_net(z) for z in zones}):
        nodes, of, _ = _on(items, net)
        poured, whole = _parts(zones, pieces, net, nodes, of)
        first = len(nodes)
        root, _, _ = _joined(nodes, of, poured, whole)
        nodes = [*nodes, *(("", {layer: part}) for layer, part in poured)]
        together: dict[int, list[int]] = {}
        for i in range(len(nodes)):
            together.setdefault(root(i), []).append(i)
        padded = {r: sorted((nodes[i][0] for i in members if nodes[i][0]), key=natural)
                  for r, members in together.items()}  # fmt: skip
        padded = {r: pads for r, pads in padded.items() if pads}
        if len(padded) < 2:
            continue
        most = max(padded, key=lambda r: (len(padded[r]), [-ord(c) for c in padded[r][0]]))
        for r, pads in sorted(padded.items(), key=lambda kv: natural(kv[1][0])):
            if r == most:
                continue
            on = [(layer, piece) for i in together[r] if i >= first
                  for layer, piece in [poured[i - first]]]  # fmt: skip
            if not on:
                cuts.append(Cut(net, tuple(pads)))
                continue
            layer, piece = on[0]
            zone = next(z for z in zones if _net(z) == net and layer in _layers(z))
            near = _num(zone, "connect_pads", "clearance", 0.5) + _num(
                zone, "min_thickness", default=0.25
            )
            beside = sorted(
                {other for item in items if str(item[0]) == "segment"
                 and layer in _layers(item) and (other := _net(item)) != net
                 and LineString([_xy(item, "start"), _xy(item, "end")])
                 .buffer(_num(item, "width") / 2).distance(piece) <= near},
                key=natural,
            )  # fmt: skip
            cuts.append(Cut(net, tuple(pads), layer, tuple(beside)))
    return cuts
