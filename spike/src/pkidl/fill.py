"""Pour fills before routing, so the router can treat the pours as planes.

KiCad fills the pours after routing, and its fill is the one the board keeps. Before
routing there is no fill to give the router, so ``prefill`` makes one the same way:
each zone's outline, inside the board edge, less every other net's copper grown by
the zone's clearance, less higher-priority pours of other nets and no-pour rule
areas, with pieces that touch no pad or via of the net dropped (KiCad's default
island removal). The result steers the router; DRC on KiCad's own fill decides.

Pads are modelled by their size and rotation as rectangles, ovals and circles;
custom pad primitives are taken as their bounding rectangle.
"""

from __future__ import annotations

import math

from shapely import affinity
from shapely.geometry import LineString, Polygon, box
from shapely.geometry import Point as SPoint
from shapely.geometry.base import BaseGeometry
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from pkidl.board import Point
from pkidl.footprint import pad_xy
from pkidl.sexpr import Node, find, find_all

Plane = tuple[str, str, list[Point]]  # net, layer, hole-free polygon in board mm
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


def _pad_shape(fp: Node, pad: Node) -> BaseGeometry:
    """A pad's copper: its rectangle, oval or circle, rotated, at its board position."""
    c = pad_xy(fp, str(pad[1]))
    size = find(pad, "size")
    assert size is not None
    w, h = float(size[1]), float(size[2]) if len(size) > 2 else float(size[1])
    at = find(pad, "at")
    angle = float(at[3]) if at is not None and len(at) > 3 else 0.0
    kind = str(pad[3])
    if kind == "circle":
        return SPoint(c).buffer(w / 2)
    if kind == "oval":
        r, half = min(w, h) / 2, abs(w - h) / 2
        line = LineString([(-half, 0), (half, 0)] if w >= h else [(0, -half), (0, half)])
        shape = line.buffer(r) if half > 0 else SPoint(0, 0).buffer(r)
    else:
        shape = box(-w / 2, -h / 2, w / 2, h / 2)
    # KiCad's pad angle is on the board (footprint rotation included), counter-clockwise
    # with y down: a negative rotation in shapely's y-up sense.
    return affinity.translate(affinity.rotate(shape, -angle, origin=(0, 0)), c[0], c[1])


def _copper(items: list[Node], layer: str) -> list[tuple[str, BaseGeometry]]:
    """Every pad, track and via on *layer*: (net, shape)."""
    out: list[tuple[str, BaseGeometry]] = []
    for item in items:
        head = str(item[0])
        if head == "footprint":
            for pad in find_all(item, "pad"):
                if layer in _layers(pad) and find(pad, "size") is not None:
                    out.append((_net(pad), _pad_shape(item, pad)))
        elif head == "segment" and layer in _layers(item):
            w = _num(item, "width")
            out.append(
                (_net(item), LineString([_xy(item, "start"), _xy(item, "end")]).buffer(w / 2))
            )
        elif head == "via":
            out.append((_net(item), SPoint(_xy(item, "at")).buffer(_num(item, "size") / 2)))
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


def prefill(
    items: list[Node], outline: list[Point], edge: float, clearances: dict[str, float] | None = None
) -> list[Plane]:
    """Each pour's fill before routing, as hole-free planes: (net, layer, polygon).

    *items* are the board's nodes (footprints, tracks, vias, zones); *outline* the board
    edge, kept *edge* away from. Zones are filled highest priority first; a pour of
    another net already filled is copper to keep clear of. *clearances* (net: mm) are
    the nets' class clearances: a pour keeps the larger of its own and the other net's,
    as KiCad does.
    """
    cl = clearances or {}
    board = Polygon(outline).buffer(-edge)
    zones = [z for z in items if str(z[0]) == "zone"]
    nopour = {
        layer: unary_union([_outline(z) for z in zones if layer in _layers(z) and _no_pour(z)])
        for layer in ("F.Cu", "B.Cu")
    }
    copper = {layer: _copper(items, layer) for layer in ("F.Cu", "B.Cu")}
    filled: dict[str, list[tuple[str, BaseGeometry]]] = {"F.Cu": [], "B.Cu": []}
    planes: list[Plane] = []
    pours = [z for z in zones if find(z, "keepout") is None and _net(z)]
    for zone in sorted(pours, key=lambda z: -_num(z, "priority")):
        net = _net(zone)
        gap = _num(zone, "connect_pads", "clearance", 0.5)
        thick = _num(zone, "min_thickness", default=0.25)
        for layer in _layers(zone):
            if layer not in filled:
                continue
            area = _outline(zone).intersection(board).difference(nopour[layer])
            foreign = [_grow(s, max(gap, cl.get(n, 0.0))) for n, s in copper[layer] if n != net]
            foreign += [_grow(s, max(gap, cl.get(n, 0.0))) for n, s in filled[layer] if n != net]
            if foreign:
                area = area.difference(unary_union(foreign))
            area = area.buffer(-thick / 2).buffer(thick / 2)  # nothing thinner than min_thickness
            own = unary_union([s for n, s in copper[layer] if n == net] or [Polygon()])
            pieces = [
                p
                for p in getattr(area, "geoms", [area])
                if isinstance(p, Polygon) and not p.is_empty
            ]
            kept = [p for p in pieces if p.intersects(own)]
            filled[layer].extend((net, p) for p in kept)
            for p in kept:
                planes.append((net, layer, [(round(x, 4), round(y, 4)) for x, y in _slit(p)]))
    return planes
