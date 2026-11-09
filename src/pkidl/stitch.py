"""Stitching vias: a grid of vias on one net, placed after routing where nothing else is.

A candidate is kept only if the via, grown by *clearance*, touches no other copper:
no pad (of any net: a via is not put in a pad), no hole, no track or via of another
net, and nothing on the nets in *keep_from* within that net's distance. It must lie
inside *outline* by *edge*. Whether the pours then reach it is for the zone fill;
check the filled board.
"""

from __future__ import annotations

import math

from pkidl.board import Point
from pkidl.footprint import pad_xy
from pkidl.sexpr import Node, find, find_all


def _seg_dist(p: Point, a: Point, b: Point) -> float:
    ax, ay, bx, by = *a, *b
    dx, dy = bx - ax, by - ay
    t = (
        0.0
        if dx == dy == 0
        else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / (dx * dx + dy * dy)))
    )
    return math.dist(p, (ax + t * dx, ay + t * dy))


def _inside(p: Point, poly: list[Point]) -> bool:
    x, y = p
    inside = False
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1], strict=True):
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            inside = not inside
    return inside


def _xy(node: Node, key: str) -> Point:
    v = find(node, key)
    assert v is not None
    return (float(v[1]), float(v[2]))


def stitch_points(
    items: list[Node],
    net: str,
    outline: list[Point],
    *,
    pitch: float,
    diameter: float,
    clearance: float,
    edge: float,
    keep_from: dict[str, float] | None = None,
) -> list[Point]:
    """Grid points, *pitch* apart, where a *diameter* via on *net* fits.

    *items* are the board's footprints, tracks and vias; *outline* is the board
    edge as a closed polygon.
    """
    keep_from = keep_from or {}
    r = diameter / 2
    # Obstacles: (kind, geometry, radius of the obstacle, distance the via must keep).
    circles: list[tuple[Point, float, float]] = []
    segments: list[tuple[Point, Point, float, float]] = []

    def keep(other: str) -> float:
        return keep_from.get(other, clearance)

    for item in items:
        head = str(item[0])
        if head == "footprint":
            for pad in find_all(item, "pad"):
                size = find(pad, "size")
                assert size is not None
                pad_r = math.hypot(float(size[1]), float(size[2])) / 2  # conservative
                pad_net = find(pad, "net")
                other = str(pad_net[1]) if pad_net is not None else ""
                circles.append((pad_xy(item, str(pad[1])), pad_r, keep(other)))
        elif head == "segment":
            seg_net = str(find(item, "net")[1])  # type: ignore[index]
            if seg_net != net or seg_net in keep_from:
                w = float(find(item, "width")[1]) / 2  # type: ignore[index]
                segments.append((_xy(item, "start"), _xy(item, "end"), w, keep(seg_net)))
        elif head == "via":
            via_net = str(find(item, "net")[1])  # type: ignore[index]
            size = float(find(item, "size")[1]) / 2  # type: ignore[index]
            # Vias of the same net still keep a pitch apart: no two drills touch.
            circles.append((_xy(item, "at"), size, keep(via_net) if via_net != net else clearance))
    xs, ys = [p[0] for p in outline], [p[1] for p in outline]
    out: list[Point] = []
    x = min(xs) + pitch / 2
    while x < max(xs):
        y = min(ys) + pitch / 2
        while y < max(ys):
            p = (round(x, 3), round(y, 3))
            ok = _inside(p, outline) and all(
                _seg_dist(p, a, b) >= r + edge
                for a, b in zip(outline, outline[1:] + outline[:1], strict=True)
            )
            ok = ok and all(math.dist(p, c) >= r + cr + d for c, cr, d in circles)
            ok = ok and all(_seg_dist(p, a, b) >= r + w + d for a, b, w, d in segments)
            if ok:
                out.append(p)
            y += pitch
        x += pitch
    return out
