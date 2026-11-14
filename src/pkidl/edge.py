"""The board's edge as a shape.

An outline is drawn item by item: lines and arcs that meet end to end, or a rectangle,
a circle or a polygon. ``shape`` joins them into the area they enclose, which is what a
part has to lie inside. A board is rarely the box around its outline: its corners are
rounded, or it is cut to fit a case.

An arc becomes short straight lines no further than a micrometre from it.
"""

from __future__ import annotations

import functools
import math
from collections.abc import Iterable, Mapping
from typing import Any

from shapely.geometry import LineString, Polygon
from shapely.ops import polygonize_full, unary_union

Point = tuple[float, float]

ARC = 0.001  # mm: how far a line standing in for an arc may be from it


def _point(value: Any) -> Point:
    return round(float(value[0]), 6), round(float(value[1]), 6)


def _arc(start: Point, mid: Point, end: Point) -> list[Point]:
    """The arc from *start* through *mid* to *end*, as points along it."""
    (ax, ay), (bx, by), (cx, cy) = start, mid, end
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:  # three points in a line: no arc, a line
        return [start, end]
    a2, b2, c2 = ax * ax + ay * ay, bx * bx + by * by, cx * cx + cy * cy
    ox = (a2 * (by - cy) + b2 * (cy - ay) + c2 * (ay - by)) / d
    oy = (a2 * (cx - bx) + b2 * (ax - cx) + c2 * (bx - ax)) / d
    r = math.hypot(ax - ox, ay - oy)
    a0, am, a1 = (math.atan2(y - oy, x - ox) for x, y in (start, mid, end))
    span = (a1 - a0) % math.tau
    if (am - a0) % math.tau > span:  # it goes round the other way, by way of mid
        span -= math.tau
    return [start, *_round(ox, oy, r, a0, span)[1:-1], end]


def arc_bounds(start: Point, mid: Point, end: Point) -> list[Point]:
    """The points that bound the arc from *start* through *mid* to *end*: its ends, and
    where it passes the left, right, top and bottom of its circle."""
    (ax, ay), (bx, by), (cx, cy) = start, mid, end
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:  # three points in a line: no arc, a line
        return [start, end]
    a2, b2, c2 = ax * ax + ay * ay, bx * bx + by * by, cx * cx + cy * cy
    ox = (a2 * (by - cy) + b2 * (cy - ay) + c2 * (ay - by)) / d
    oy = (a2 * (cx - bx) + b2 * (ax - cx) + c2 * (bx - ax)) / d
    r = math.hypot(ax - ox, ay - oy)
    a0, am, a1 = (math.degrees(math.atan2(y - oy, x - ox)) for x, y in (start, mid, end))
    span = (a1 - a0) % 360
    rising = (am - a0) % 360 <= span  # the angle grows from start to end, by way of mid
    pts = [start, end]
    for t in (0, 90, 180, 270):
        along = (t - a0) % 360
        if (along <= span) if rising else (along >= span):
            pts.append((ox + r * math.cos(math.radians(t)), oy + r * math.sin(math.radians(t))))
    return pts


def _round(ox: float, oy: float, r: float, a0: float, span: float) -> list[Point]:
    """Points round a circle from angle *a0* through *span*, both ends among them."""
    step = 2 * math.acos(max(0.0, 1 - ARC / r)) if r > ARC else math.pi / 2
    n = max(2, math.ceil(abs(span) / step))
    return [(ox + r * math.cos(a0 + span * i / n), oy + r * math.sin(a0 + span * i / n))
            for i in range(n + 1)]  # fmt: skip


def shape(items: Iterable[Mapping[str, Any]]) -> Polygon:
    """The area the outline *items* enclose, in board millimetres: each item as
    ``mechanical.json`` lists it. A cut-out drawn inside the outline is a hole in it,
    one drawn on its edge a notch, and a line that closes nothing is ignored within
    the box around the board. Raises
    ``ValueError`` for an outline that does not close, or has a line left over that
    reaches outside that box, and for one that encloses two areas apart from each
    other."""
    lines: list[LineString] = []
    loops: list[Polygon] = []  # what is drawn closed: a rectangle, a circle, a polygon
    for item in items:
        kind = item["type"]
        if kind == "gr_line":
            lines.append(LineString([_point(item["start"]), _point(item["end"])]))
        elif kind == "gr_arc":
            lines.append(LineString(_arc(*(_point(item[k]) for k in ("start", "mid", "end")))))
        elif kind == "gr_rect":
            (x0, y0), (x1, y1) = _point(item["start"]), _point(item["end"])
            loops.append(Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)]))
        elif kind == "gr_circle":
            (ox, oy), on = _point(item["center"]), _point(item["end"])
            loops.append(Polygon(_round(ox, oy, math.dist((ox, oy), on), 0.0, math.tau)[:-1]))
        elif kind == "gr_poly":
            loops.append(Polygon([_point(p) for p in item["pts"]]))
        else:
            raise ValueError(f"outline: {kind!r} is not something Edge.Cuts is drawn with")
    open_ended = "the outline does not close: its items do not meet end to end"
    rest: list[Any] = []
    if lines:
        found, *rest = polygonize_full(unary_union(lines))
        loops += [Polygon(face.exterior) for face in found.geoms]
    if not loops:
        raise ValueError(open_ended)
    # Each closed line turns board into cut-out and cut-out into board: what is inside
    # an odd number of them is board. So a cut-out is one whether it is drawn inside the
    # outline or on its edge, as a notch.
    board = functools.reduce(lambda area, loop: area.symmetric_difference(loop), loops)
    if board.is_empty:
        raise ValueError("the outline encloses nothing: what it cuts out is all of it")
    if not isinstance(board, Polygon):
        apart = len(getattr(board, "geoms", ()))
        raise ValueError(f"the outline encloses {apart} areas apart from each other, "
                         "not one board")  # fmt: skip
    # A line that closes nothing is no harm within the box around the board: real
    # outlines have stubs where an edge is drawn on past a rounded corner. One that
    # reaches outside that box is an outline left open.
    box = board.envelope.buffer(1e-6)
    if not all(box.covers(line) for left in rest for line in left.geoms):
        raise ValueError(open_ended)
    return board
