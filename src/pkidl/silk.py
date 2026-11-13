"""Place footprint reference designators where they can be read.

Each footprint's Reference goes to the first of a few spots around its courtyard (above,
below, left, right, then where the library put it) whose text box is clear of copper
pads, of silkscreen graphics and text already on that side, and of the board edge.
A reference with no clear spot moves to the fab layer: it stays in the assembly
drawing, off the silkscreen.

Text size is estimated from KiCad's stroke font: at most the height per character,
plus the stroke. Boxes are axis-aligned; a rotated pad or graphic is taken
by its bounding box, which is conservative.
"""

from __future__ import annotations

import math

from pkidl.board import Point
from pkidl.footprint import board_xy, pad_at
from pkidl.sexpr import Node, find, find_all, num

Box = tuple[float, float, float, float]  # x0, y0, x1, y1
MIN_TEXT = 0.8  # mm: the smallest reference height tried, the Slice minimum
NEAR = 4.0  # mm beyond a part's courtyard that its reference may go
_GRAPHICS = ("fp_line", "fp_rect", "fp_circle", "fp_arc", "fp_poly")


def _ref(fp: Node) -> Node:
    return next(p for p in find_all(fp, "property") if p[1] == "Reference")


def _side(layer: str) -> str:
    return "B" if layer.startswith("B.") else "F"


def _grow(b: Box, d: float) -> Box:
    return (b[0] - d, b[1] - d, b[2] + d, b[3] + d)


def _contains(outer: Box, b: Box) -> bool:
    return outer[0] <= b[0] and b[2] <= outer[2] and outer[1] <= b[1] and b[3] <= outer[3]


def _overlap(a: Box, b: Box) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def text_box(text: str, at: Point, size: float, thickness: float, angle: float) -> Box:
    """The axis-aligned box of a one-line text centred at *at*, rotated by *angle*."""
    w = len(text) * size * 1.0 + thickness
    h = size + thickness
    r = math.radians(angle)
    bw = abs(w * math.cos(r)) + abs(h * math.sin(r))
    bh = abs(w * math.sin(r)) + abs(h * math.cos(r))
    return (at[0] - bw / 2, at[1] - bh / 2, at[0] + bw / 2, at[1] + bh / 2)


def _graphic_boxes(fp: Node, layer_suffix: str) -> list[tuple[str, Box]]:
    """(side, box) of a placed footprint's graphics on layers ending *layer_suffix*."""
    out = []
    for g in fp[1:]:
        if not (isinstance(g, list) and g and str(g[0]) in _GRAPHICS):
            continue
        layer = find(g, "layer")
        if layer is None or not str(layer[1]).endswith(layer_suffix):
            continue
        pts: list[tuple[float, float]] = []
        for key in ("start", "mid", "end", "center"):
            v = find(g, key)
            if v is not None:
                pts.append((float(v[1]), float(v[2])))
        pts_node = find(g, "pts")
        if pts_node is not None:
            pts += [(float(p[1]), float(p[2])) for p in find_all(pts_node, "xy")]
        center = find(g, "center")
        if str(g[0]) == "fp_circle" and center is not None and len(pts) == 2:
            cx, cy = float(center[1]), float(center[2])
            r = math.dist(*pts)
            pts += [(cx - r, cy - r), (cx + r, cy + r)]
        board = [board_xy(fp, x, y) for x, y in pts]
        if board:
            xs, ys = [p[0] for p in board], [p[1] for p in board]
            out.append((_side(str(layer[1])), (min(xs), min(ys), max(xs), max(ys))))
    return out


def silk_box(fp: Node) -> Box | None:
    """The bounding box of a placed footprint's silkscreen graphics, either side."""
    boxes = [b for _, b in _graphic_boxes(fp, ".SilkS")]
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))  # fmt: skip


def _fp_text_boxes(fp: Node) -> list[tuple[str, Box]]:
    """A placed footprint's own visible silkscreen text (``fp_text user``)."""
    out = []
    for t in find_all(fp, "fp_text"):
        at, layer = find(t, "at"), find(t, "layer")
        if at is None or layer is None or not str(layer[1]).endswith("SilkS") or find(t, "hide"):
            continue
        effects = find(t, "effects")
        font = find(effects, "font") if effects is not None else None
        size_node = find(font, "size") if font is not None else None
        size = float(size_node[1]) if size_node is not None else 1.0
        angle = float(at[3]) if len(at) > 3 else 0.0
        pos = board_xy(fp, float(at[1]), float(at[2]))
        out.append((_side(str(layer[1])), text_box(str(t[2]), pos, size, 0.15, angle)))
    return out


def _pad_boxes(fp: Node) -> list[tuple[str, Box]]:
    out = []
    for pad in find_all(fp, "pad"):
        size, pa, layers = find(pad, "size"), find(pad, "at"), find(pad, "layers")
        if size is None or pa is None or layers is None:
            continue
        w, h = float(size[1]), float(size[2])
        angle = float(pa[3]) if len(pa) > 3 else 0.0
        if round(angle) % 180 == 90:
            w, h = h, w
        elif round(angle) % 90:
            w = h = math.hypot(w, h)
        x, y = pad_at(fp, pad)
        names = [str(n) for n in layers[1:]]
        sides = [s for s, n in (("F", "F.Cu"), ("B", "B.Cu")) if n in names or "*.Cu" in names]
        out += [(s, (x - w / 2, y - h / 2, x + w / 2, y + h / 2)) for s in sides]
    return out


def _local(fp: Node, bx: float, by: float) -> Point:
    """The inverse of ``board_xy``: a board point in the footprint's own frame."""
    at = find(fp, "at")
    assert at is not None
    x0, y0 = float(at[1]), float(at[2])
    r = math.radians(float(at[3]) if len(at) > 3 else 0.0)
    dx, dy = bx - x0, by - y0
    return (
        round(dx * math.cos(r) - dy * math.sin(r), 4),
        round(dx * math.sin(r) + dy * math.cos(r), 4),
    )


def multiline_box(text: str, at: Point, size: float, thickness: float, angle: float) -> Box:
    """The box of a text of one or more lines centred at *at*."""
    lines = text.split("\n")
    bx0, by0, bx1, by1 = text_box(max(lines, key=len), at, size, thickness, angle)
    grow = (len(lines) - 1) * size * 1.6 / 2  # KiCad's line spacing, about 1.6 x height
    if round(angle) % 180 == 90:
        return (bx0 - grow, by0, bx1 + grow, by1)
    return (bx0, by0 - grow, bx1, by1 + grow)


def _obstacles(items: list[Node], include_references: bool = True) -> list[tuple[str, Box]]:
    """(side, box) of everything a silkscreen text must keep off: pads, silk graphics,
    footprint and board silk text."""
    obstacles: list[tuple[str, Box]] = []
    for fp in items:
        if isinstance(fp, list) and fp and str(fp[0]) == "footprint":
            obstacles += _pad_boxes(fp)
            obstacles += _graphic_boxes(fp, ".SilkS")
            obstacles += _fp_text_boxes(fp)
            prop = _ref(fp)
            layer, pat = find(prop, "layer"), find(prop, "at")
            if (
                include_references
                and layer is not None
                and pat is not None
                and str(layer[1]).endswith("SilkS")
            ):
                angle = float(pat[3]) if len(pat) > 3 else 0.0
                pos = board_xy(fp, float(pat[1]), float(pat[2]))
                obstacles.append(
                    (_side(str(layer[1])), text_box(str(prop[2]), pos, 1.0, 0.15, angle))
                )
    for t in items:
        if not (isinstance(t, list) and t and str(t[0]) == "gr_text"):
            continue
        at, layer, effects = find(t, "at"), find(t, "layer"), find(t, "effects")
        font = find(effects, "font") if effects is not None else None
        size_node = find(font, "size") if font is not None else None
        size = float(size_node[1]) if size_node is not None else 1.0
        if at is None or layer is None or not str(layer[1]).endswith("SilkS"):
            continue
        angle = float(at[3]) if len(at) > 3 else 0.0
        box = multiline_box(str(t[1]), (float(at[1]), float(at[2])), size, 0.15, angle)
        obstacles.append((_side(str(layer[1])), box))
    return obstacles


def nearest_clear_spot(
    items: list[Node],
    text: str,
    near: Point,
    outline: Box,
    *,
    layer: str = "F.SilkS",
    size: float = 1.0,
    thickness: float = 0.15,
    gap: float = 0.25,
    edge: float = 0.5,
    step: float = 0.5,
) -> Point | None:
    """The spot nearest *near*, on a *step* grid, where *text* fits clear of everything.

    For a board text placed by the layout (a title or source label), so a placement
    change cannot leave it over a part.
    """
    obstacles = [o for s, o in _obstacles(items) if s == _side(layer)]
    x0, y0, x1, y1 = outline
    inside = (x0 + edge, y0 + edge, x1 - edge, y1 - edge)
    nx, ny = int((x1 - x0) / step) + 1, int((y1 - y0) / step) + 1
    grid = [
        (round(x0 + i * step, 3), round(y0 + j * step, 3)) for i in range(nx) for j in range(ny)
    ]
    for spot in sorted(grid, key=lambda p: (math.dist(p, near), p)):
        box = multiline_box(text, spot, size, thickness, 0.0)
        if not (
            inside[0] <= box[0]
            and box[2] <= inside[2]
            and inside[1] <= box[1]
            and box[3] <= inside[3]
        ):
            continue
        if not any(_overlap(_grow(box, gap), o) for o in obstacles):
            return spot
    return None


def place_references(
    items: list[Node],
    outline: Box,
    *,
    gap: float = 0.25,
    edge: float = 0.5,
    keep: frozenset[str] = frozenset(),
) -> dict[str, str]:
    """Move each footprint's Reference (refs in *keep* excepted) to a readable spot.

    *items* are the board's footprints and texts; *outline* the board's bounding box.
    Returns, per reference moved off the silkscreen, the fab layer it went to.
    """
    footprints = [i for i in items if isinstance(i, list) and i and str(i[0]) == "footprint"]
    obstacles = _obstacles(items, include_references=False)
    x0, y0, x1, y1 = outline
    inside = (x0 + edge, y0 + edge, x1 - edge, y1 - edge)
    moved: dict[str, str] = {}
    for fp in footprints:
        prop = _ref(fp)
        ref = str(prop[2])
        layer = find(prop, "layer")
        if (
            ref in keep
            or layer is None
            or not str(layer[1]).endswith("SilkS")
            or find(prop, "hide")
        ):
            continue
        side = _side(str(layer[1]))
        effects = find(prop, "effects")
        font = find(effects, "font") if effects is not None else None
        size_node = find(font, "size") if font is not None else None
        thick_node = find(font, "thickness") if font is not None else None
        size = float(size_node[1]) if size_node is not None else 1.0
        thick = float(thick_node[1]) if thick_node is not None else 0.15
        pat = find(prop, "at")
        assert pat is not None
        angle = float(pat[3]) if len(pat) > 3 else 0.0
        here = board_xy(fp, float(pat[1]), float(pat[2]))
        court = [b for s, b in _graphic_boxes(fp, ".CrtYd")]
        if court:
            cx0, cy0 = min(b[0] for b in court), min(b[1] for b in court)
            cx1, cy1 = max(b[2] for b in court), max(b[3] for b in court)
        else:
            cx0, cy0, cx1, cy1 = here[0], here[1], here[0], here[1]
        placed = False
        # At the library's size first, then at the Slice minimum text height.
        for sz, th_ in ((size, thick), (min(size, MIN_TEXT), min(thick, MIN_TEXT * 0.15))):
            w0, h0, w1, h1 = text_box(ref, (0.0, 0.0), sz, th_, angle)
            tw, th = w1 - w0, h1 - h0
            mx, my = (cx0 + cx1) / 2, (cy0 + cy1) / 2
            left, right = cx0 - gap - tw / 2, cx1 + gap + tw / 2
            above, below = cy0 - gap - th / 2, cy1 + gap + th / 2
            spots = [(mx, above), (mx, below), (left, my), (right, my), here, (mx, my),
                     (left, above), (right, above), (left, below), (right, below)]  # fmt: skip
            for spot in spots:
                box = text_box(ref, spot, sz, th_, angle)
                if _contains(inside, box) and not any(
                    s == side and _overlap(_grow(box, gap), o) for s, o in obstacles
                ):
                    lx, ly = _local(fp, *spot)
                    pat[1], pat[2] = num(lx), num(ly)
                    if sz != size and size_node is not None and thick_node is not None:
                        size_node[1], size_node[2], thick_node[1] = num(sz), num(sz), num(th_)
                    obstacles.append((side, box))
                    placed = True
                    break
            if placed:
                break
        if not placed:
            # Last, the nearest clear spot within reach of the part, at the minimum size.
            sz, th_ = min(size, MIN_TEXT), min(thick, MIN_TEXT * 0.15)
            centre = ((cx0 + cx1) / 2, (cy0 + cy1) / 2)
            reach = max(cx1 - cx0, cy1 - cy0) / 2 + NEAR
            steps = int(2 * reach / 0.25) + 1
            grid = [(round(centre[0] - reach + i * 0.25, 3), round(centre[1] - reach + j * 0.25, 3))
                    for i in range(steps) for j in range(steps)]  # fmt: skip
            for spot in sorted(grid, key=lambda q: (math.dist(q, centre), q)):
                box = text_box(ref, spot, sz, th_, angle)
                if _contains(inside, box) and not any(
                    s == side and _overlap(_grow(box, gap), o) for s, o in obstacles
                ):
                    lx, ly = _local(fp, *spot)
                    pat[1], pat[2] = num(lx), num(ly)
                    if size_node is not None and thick_node is not None:
                        size_node[1], size_node[2], thick_node[1] = num(sz), num(sz), num(th_)
                    obstacles.append((side, box))
                    placed = True
                    break
        if not placed:
            fab = f"{side}.Fab"
            layer[1] = fab
            moved[ref] = fab
    return moved
