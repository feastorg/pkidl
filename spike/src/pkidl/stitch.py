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

FILL_STEP = 0.25  # mm, the fill model's grid


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


def _main_fill(
    items: list[Node], net: str, outline: list[Point], layer: str, gap: float, step: float
) -> tuple[set[tuple[int, int]], float, float]:
    """A model of *net*'s pour on *layer*: grid cells (*step* mm) further than *gap* from
    every other net's copper and inside *outline*, keeping only the largest connected
    region, the one the fill keeps. Islands, which the fill drops, are left out."""
    blocked: set[tuple[int, int]] = set()
    xs, ys = [p[0] for p in outline], [p[1] for p in outline]
    x0, y0 = min(xs), min(ys)
    nx, ny = int((max(xs) - x0) / step) + 1, int((max(ys) - y0) / step) + 1

    def stamp(dist, bx0: float, by0: float, bx1: float, by1: float) -> None:
        for i in range(max(0, int((bx0 - x0) / step)), min(nx, int((bx1 - x0) / step) + 2)):
            for j in range(max(0, int((by0 - y0) / step)), min(ny, int((by1 - y0) / step) + 2)):
                if dist((x0 + i * step, y0 + j * step)) <= gap:
                    blocked.add((i, j))

    def on_layer(names: list[str]) -> bool:
        return layer in names or "*.Cu" in names

    for item in items:
        head = str(item[0])
        if head == "footprint":
            for pad in find_all(item, "pad"):
                pad_net, layers, size = find(pad, "net"), find(pad, "layers"), find(pad, "size")
                if (pad_net is not None and pad_net[1] == net) or layers is None or size is None:
                    continue
                if not on_layer([str(v) for v in layers[1:]]):
                    continue
                c, pr = pad_xy(item, str(pad[1])), math.hypot(float(size[1]), float(size[2])) / 2
                stamp(lambda q, c=c, pr=pr: math.dist(q, c) - pr, c[0] - pr - gap, c[1] - pr - gap,
                      c[0] + pr + gap, c[1] + pr + gap)  # fmt: skip
        elif head in ("segment", "via"):
            n = find(item, "net")
            if n is None or n[1] == net:
                continue
            if head == "segment":
                if str(find(item, "layer")[1]) != layer:  # type: ignore[index]
                    continue
                a, b = _xy(item, "start"), _xy(item, "end")
                w = float(find(item, "width")[1]) / 2  # type: ignore[index]
                stamp(lambda q, a=a, b=b, w=w: _seg_dist(q, a, b) - w,
                      min(a[0], b[0]) - w - gap, min(a[1], b[1]) - w - gap,
                      max(a[0], b[0]) + w + gap, max(a[1], b[1]) + w + gap)  # fmt: skip
            else:
                c, vr = _xy(item, "at"), float(find(item, "size")[1]) / 2  # type: ignore[index]
                stamp(lambda q, c=c, vr=vr: math.dist(q, c) - vr, c[0] - vr - gap,
                      c[1] - vr - gap, c[0] + vr + gap, c[1] + vr + gap)  # fmt: skip
    free = {
        (i, j)
        for i in range(nx)
        for j in range(ny)
        if (i, j) not in blocked and _inside((x0 + i * step, y0 + j * step), outline)
    }
    best: set[tuple[int, int]] = set()
    seen: set[tuple[int, int]] = set()
    for start in free:
        if start in seen:
            continue
        region, todo = {start}, [start]
        seen.add(start)
        while todo:
            i, j = todo.pop()
            for nb in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
                if nb in free and nb not in seen:
                    seen.add(nb)
                    region.add(nb)
                    todo.append(nb)
        if len(region) > len(best):
            best = region
    return best, x0, y0


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
    avoid: list[list[Point]] | None = None,
    fill_gap: float = 0.625,
) -> list[Point]:
    """Grid points, *pitch* apart, where a *diameter* via on *net* fits.

    *items* are the board's footprints, tracks and vias; *outline* is the board
    edge as a closed polygon. No via goes inside, or within *clearance* of, an *avoid*
    polygon (a keepout). And none goes where its net's pour would not reach it on both
    layers: *fill_gap* is the pour's clearance plus half its minimum width.
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
    fills = [_main_fill(items, net, outline, layer, fill_gap, FILL_STEP)
             for layer in ("F.Cu", "B.Cu")]  # fmt: skip
    xs, ys = [p[0] for p in outline], [p[1] for p in outline]
    out: list[Point] = []
    x = min(xs) + pitch / 2
    while x < max(xs):
        y = min(ys) + pitch / 2
        while y < max(ys):
            p = (round(x, 3), round(y, 3))
            ok = not any(
                _inside(p, a)
                or any(
                    _seg_dist(p, u, w) < r + clearance
                    for u, w in zip(a, a[1:] + a[:1], strict=True)
                )
                for a in avoid or []
            )
            ok = (
                ok
                and _inside(p, outline)
                and all(
                    _seg_dist(p, a, b) >= r + edge
                    for a, b in zip(outline, outline[1:] + outline[:1], strict=True)
                )
            )
            ok = ok and all(math.dist(p, c) >= r + cr + d for c, cr, d in circles)
            ok = ok and all(_seg_dist(p, a, b) >= r + w + d for a, b, w, d in segments)
            # And in the region each layer's pour keeps: in a pocket the fill drops as an
            # island, the via would connect on one layer only.
            if ok and all((round((p[0] - fx) / FILL_STEP), round((p[1] - fy) / FILL_STEP)) in cells
                          for cells, fx, fy in fills):  # fmt: skip
                out.append(p)
            y += pitch
        x += pitch
    return out
