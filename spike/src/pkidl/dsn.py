"""Write a Specctra DSN file for an autorouter, and read its SES routes back.

The DSN is written from the board pkidl assembled, not from KiCad. Each placed
footprint becomes its own image whose pins already carry their final position,
rotation and layer, and every component is placed unrotated on the front. So the
router never applies a rotation or a back-side mirror of its own, and nothing
depends on how it would.

Coordinates: DSN is in micrometres, y up; KiCad is in millimetres, y down. SES
routes come back in tenths of a micrometre (``resolution um 10``).

The router's output is not trusted: the routes are written into the board and
KiCad's DRC judges the result.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from pkidl.board import Point
from pkidl.project import NetClass
from pkidl.sexpr import Node, find, find_all, parse

VIA = "Via[0-1]_{d}:{h}_um"


def via_padstack(diameter: float, drill: float) -> str:
    """The DSN padstack name of a through via, sizes in mm."""
    return VIA.format(d=round(diameter * 1000), h=round(drill * 1000))


def via_size(padstack: str) -> tuple[float, float]:
    """(diameter, drill) in mm of a padstack named by ``via_padstack``."""
    sizes = padstack.removeprefix("Via[0-1]_").removesuffix("_um").split(":")
    return float(sizes[0]) / 1000, float(sizes[1]) / 1000


def _q(s: str) -> str:
    return '"' + s.replace('"', "") + '"'


def _n(x: float) -> str:
    """Micrometres, to the 0.1 um the DSN declares."""
    s = f"{x:.1f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def _rot(x: float, y: float, deg: float) -> tuple[float, float]:
    """KiCad's rotation: counter-clockwise on screen, y down."""
    r = math.radians(deg)
    return x * math.cos(r) + y * math.sin(r), -x * math.sin(r) + y * math.cos(r)


def _roundrect(w: float, h: float, r: float, segments: int = 4) -> list[tuple[float, float]]:
    """Outline of a w x h rectangle with radius-r corners, centred on the origin."""
    pts = []
    for cx, cy, a0 in ((w / 2 - r, -h / 2 + r, 270), (w / 2 - r, h / 2 - r, 0),
                       (-w / 2 + r, h / 2 - r, 90), (-w / 2 + r, -h / 2 + r, 180)):  # fmt: skip
        for i in range(segments + 1):
            a = math.radians(a0 + 90 * i / segments)
            # Through the corner's outer bound, so the polygon never undercuts the pad.
            k = r / math.cos(math.radians(45 / segments)) if 0 < i < segments else r
            pts.append((cx + k * math.cos(a), cy + k * math.sin(a)))
    return pts


@dataclass(frozen=True)
class _Pin:
    padstack: str
    name: str
    x: float  # um, image-local, y up
    y: float


def _pad_offset(pad: Node, angle: float) -> tuple[float, float]:
    """Where *pad*'s copper sits from its hole, in um, y up: a drill's (offset)."""
    drill = find(pad, "drill")
    off = find(drill, "offset") if drill is not None else None
    if off is None:
        return 0.0, 0.0
    x, y = _rot(float(off[1]) * 1000, float(off[2]) * 1000, angle)
    return x, -y


def _pad_shapes(pad: Node, angle: float) -> list[str]:
    """DSN shape primitives for *pad*, in um about the pad's hole (its centre), y up."""
    kind, shape = str(pad[2]), str(pad[3])
    cx, cy = _pad_offset(pad, angle)
    size = find(pad, "size")
    assert size is not None
    w, h = float(size[1]) * 1000, float(size[2]) * 1000
    layers_node = find(pad, "layers")
    assert layers_node is not None
    names = [str(n) for n in layers_node[1:]]
    if "*.Cu" in names or kind == "thru_hole":
        layers = ["F.Cu", "B.Cu"]
    else:
        layers = [n for n in ("F.Cu", "B.Cu") if n in names]

    def poly(pts: list[tuple[float, float]]) -> str:
        out = []
        for x, y in pts:
            rx, ry = _rot(x, y, angle)
            out.append(f"{_n(rx + cx)} {_n(-ry + cy)}")
        return "  ".join(out)

    shapes = []
    for layer in layers:
        if shape == "circle":
            at = f" {_n(cx)} {_n(cy)}" if (cx, cy) != (0.0, 0.0) else ""
            shapes.append(f"(circle {layer} {_n(w)}{at})")
        elif shape == "oval":
            d = min(w, h)
            half = (max(w, h) - d) / 2
            a, b = ((-half, 0), (half, 0)) if w >= h else ((0, -half), (0, half))
            shapes.append(f"(path {layer} {_n(d)}  {poly([a, b])})")
        elif shape == "rect" and angle % 90 == 0:
            ww, hh = (w, h) if angle % 180 == 0 else (h, w)
            x0, y0, x1, y1 = cx - ww / 2, cy - hh / 2, cx + ww / 2, cy + hh / 2
            shapes.append(f"(rect {layer} {_n(x0)} {_n(y0)} {_n(x1)} {_n(y1)})")
        elif shape in ("rect", "roundrect"):
            ratio = find(pad, "roundrect_rratio")
            r = float(ratio[1]) * min(w, h) if shape == "roundrect" and ratio is not None else 0
            pts = _roundrect(w, h, r) if r else [(-w / 2, -h / 2), (w / 2, -h / 2),
                                                 (w / 2, h / 2), (-w / 2, h / 2)]  # fmt: skip
            shapes.append(f"(polygon {layer} 0  {poly(pts + pts[:1])})")
        else:
            raise ValueError(f"pad shape {shape!r} is not supported")
    return shapes


def _cut(span: tuple[float, float], holes: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """*span* less every interval in *holes*."""
    spans = [span]
    for h0, h1 in holes:
        spans = [s for a, b in spans for s in ((a, min(b, h0)), (max(a, h1), b)) if s[1] > s[0]]
    return spans


def _copper_keepouts(
    fp: Node, rot: float, pad_boxes: list[tuple[float, float, float, float]]
) -> list[str]:
    """Keepouts for a footprint's copper polygons (a net tie's bridge, say): the router
    sees pads, not graphics, and would route other nets across them.

    An axis-aligned rectangle is written less the pads that span it, so its own pads
    stay reachable; any other polygon is written whole. In image um, y up.
    """
    out = []
    for g in find_all(fp, "fp_poly"):
        layer = find(g, "layer")
        pts_node = find(g, "pts")
        if layer is None or str(layer[1]) not in ("F.Cu", "B.Cu") or pts_node is None:
            continue
        pts = []
        for xy in find_all(pts_node, "xy"):
            lx, ly = _rot(float(xy[1]), float(xy[2]), rot)
            pts.append((lx * 1000, -ly * 1000))
        xs, ys = sorted({round(x, 1) for x, _ in pts}), sorted({round(y, 1) for _, y in pts})
        if len(pts) != 4 or len(xs) != 2 or len(ys) != 2:
            coords = " ".join(f"{_n(x)} {_n(y)}" for x, y in pts + pts[:1])
            out.append(f'(keepout "" (polygon {layer[1]} 0 {coords}))')
            continue
        # Subtract, along one axis, each pad spanning the rectangle across the other.
        e = 0.5  # um: rotation leaves the pads' edges a hair off the rectangle's
        across_x = [(b[1], b[3]) for b in pad_boxes if b[0] <= xs[0] + e and b[2] >= xs[1] - e]
        across_y = [(b[0], b[2]) for b in pad_boxes if b[1] <= ys[0] + e and b[3] >= ys[1] - e]
        if across_x or not across_y:  # pads stacked in y: cut y spans
            for a, b in _cut((ys[0], ys[1]), across_x):
                out.append(
                    f'(keepout "" (rect {layer[1]} {_n(xs[0])} {_n(a)} {_n(xs[1])} {_n(b)}))'
                )
        else:  # pads side by side in x: cut x spans
            for a, b in _cut((xs[0], xs[1]), across_y):
                out.append(
                    f'(keepout "" (rect {layer[1]} {_n(a)} {_n(ys[0])} {_n(b)} {_n(ys[1])}))'
                )
    return out


def write_dsn(
    path: Path,
    footprints: list[Node],
    outline: list[Point],
    netclasses: list[NetClass],
    members: dict[str, list[str]],
    *,
    edge_clearance: float = 0.5,
    only: set[str] | None = None,
    fixed: tuple[list[Wire], list[Via]] = ([], []),
    class_clearances: dict[tuple[str, str], float] | None = None,
    areas: list[tuple[str, list[Point]]] | None = None,
    planes: list[tuple[str, str, list[Point]]] | None = None,
) -> Path:
    """Write *path* for routing *footprints* (placed board nodes) inside *outline*.

    *outline* is the board edge as a closed polygon in board millimetres; the
    router is kept *edge_clearance* inside it. Netclasses and their members are
    as given to ``pkidl.project.write_project``: the first is Default.

    With *only*, just those nets are routed; every pin stays an obstacle. *fixed*
    routes (as ``read_ses`` returns them) are written as protected wiring: the
    router keeps them and routes around them. *class_clearances* sets the router's
    clearance between two classes' nets, in mm, over their own. *areas* are keepouts
    no track or via may enter on their layer: (layer, polygon in board mm). *planes*
    are pours the router may connect through: (net, layer, hole-free polygon in
    board mm), as ``pkidl.fill.prefill`` makes them; route with ``plane_as_obstacle``
    so other nets keep out of them.
    """
    padstacks: dict[str, list[str]] = {}
    images: list[str] = []
    places: list[str] = []
    nets: dict[str, list[str]] = {}

    for fp in footprints:
        ref = next(p[2] for p in find_all(fp, "property") if p[1] == "Reference")
        at = find(fp, "at")
        assert at is not None
        x0, y0 = float(at[1]), float(at[2])
        rot = float(at[3]) if len(at) > 3 else 0.0
        pins: list[_Pin] = []
        keepouts: list[str] = []
        pad_boxes: list[tuple[float, float, float, float]] = []
        seen: dict[str, int] = {}
        for pad in find_all(fp, "pad"):
            pa = find(pad, "at")
            assert pa is not None
            lx, ly = _rot(float(pa[1]), float(pa[2]), rot)
            x, y = lx * 1000, -ly * 1000
            if str(pad[2]) == "np_thru_hole":
                drill = find(pad, "drill")
                assert drill is not None
                keepouts.append(f'(keepout "" (circle signal {_n(float(drill[1]) * 1000)} '
                                f"{_n(x)} {_n(y)}))")  # fmt: skip
                continue
            angle = float(pa[3]) if len(pa) > 3 else 0.0
            size = find(pad, "size")
            assert size is not None
            w, h = float(size[1]) * 1000, float(size[2]) * 1000
            if round(angle) % 180 == 90:
                w, h = h, w
            ox, oy = _pad_offset(pad, angle)
            pad_boxes.append((x + ox - w / 2, y + oy - h / 2, x + ox + w / 2, y + oy + h / 2))
            shapes = _pad_shapes(pad, angle)
            key = "|".join(shapes)
            name = next((n for n, s in padstacks.items() if "|".join(s) == key), None)
            if name is None:
                name = f"Pad{len(padstacks)}"
                padstacks[name] = shapes
            number = str(pad[1])
            # Pads sharing a number are one pin electrically; DSN pin names are unique.
            k = seen.get(number, 0)
            seen[number] = k + 1
            pin_name = number if k == 0 else f"{number}@{k}"
            pins.append(_Pin(name, pin_name, x, y))
            net = find(pad, "net")
            if net is not None:
                nets.setdefault(str(net[1]), []).append(f"{ref}-{pin_name}")
        keepouts += _copper_keepouts(fp, rot, pad_boxes)
        body = [f"(pin {p.padstack} {_q(p.name)} {_n(p.x)} {_n(p.y)})" for p in pins] + keepouts
        images.append(f"    (image {_q(ref)}\n" + "".join(f"      {b}\n" for b in body) + "    )")
        places.append(
            f"    (component {_q(ref)}\n"
            f"      (place {_q(ref)} {_n(x0 * 1000)} {_n(-y0 * 1000)} front 0)\n    )"
        )

    via_names = {}
    for c in netclasses:
        name = via_padstack(c.via_diameter, c.via_drill)
        via_names[c.name] = name
        padstacks.setdefault(
            name, [f"(circle {layer} {_n(c.via_diameter * 1000)})" for layer in ("F.Cu", "B.Cu")]
        )
    for v in fixed[1]:  # fixed vias may be sizes no netclass uses
        diameter = via_size(v.padstack)[0]
        padstacks.setdefault(
            v.padstack, [f"(circle {layer} {_n(diameter * 1000)})" for layer in ("F.Cu", "B.Cu")]
        )

    inset = _inset(outline, edge_clearance)
    boundary = "  ".join(f"{_n(x * 1000)} {_n(-y * 1000)}" for x, y in inset + inset[:1])
    default = netclasses[0]
    lines = [
        f"(pcb {_q(path.name)}",
        "  (parser",
        '    (string_quote ")',
        "    (space_in_quoted_tokens on)",
        '    (host_cad "pkidl")',
        '    (host_version "0.1")',
        "  )",
        "  (resolution um 10)",
        "  (unit um)",
        "  (structure",
        "    (layer F.Cu (type signal) (property (index 0)))",
        "    (layer B.Cu (type signal) (property (index 1)))",
        f"    (boundary (path pcb 0  {boundary}))",
        *(f'    (keepout "" (polygon {layer} 0  '
          + "  ".join(f"{_n(x * 1000)} {_n(-y * 1000)}" for x, y in poly + poly[:1]) + "))"
          for layer, poly in areas or []),
        *(f"    (plane {_q(net)} (polygon {layer} 0  "
          + "  ".join(f"{_n(x * 1000)} {_n(-y * 1000)}" for x, y in poly + poly[:1]) + "))"
          for net, layer, poly in planes or []),
        f"    (via {_q(via_names[default.name])})",
        f"    (rule (width {_n(default.track_width * 1000)}) "
        f"(clearance {_n(default.clearance * 1000)}))",
        "  )",
        "  (placement",
        *places,
        "  )",
        "  (library",
        *images,
        *(f"    (padstack {_q(name)}\n" + "".join(f"      (shape {s})\n" for s in shapes)
          + "      (attach off)\n    )" for name, shapes in padstacks.items()),
        "  )",
        "  (network",
    ]  # fmt: skip
    for net in sorted(nets):
        if len(nets[net]) > 1 and (only is None or net in only):
            lines.append(f"    (net {_q(net)} (pins {' '.join(sorted(nets[net]))}))")
    routed = {n for n in nets if len(nets[n]) > 1 and (only is None or n in only)}
    classed: set[str] = set()
    for c in netclasses[1:]:
        classed |= set(members.get(c.name, []))
    written: set[str] = set()
    for c in netclasses:
        names = sorted(routed - classed if c is default else routed & set(members.get(c.name, [])))
        if not names:
            continue
        written.add(c.name)
        width, clearance = _n(c.track_width * 1000), _n(c.clearance * 1000)
        lines.append(
            f"    (class {_q(c.name)} {' '.join(_q(n) for n in names)}\n"
            f"      (circuit (use_via {_q(via_names[c.name])}))\n"
            f"      (rule (width {width}) (clearance {clearance}))\n"
            "    )"
        )
    for (a, b), clearance in (class_clearances or {}).items():
        if a in written and b in written:
            lines.append(f"    (class_class (classes {_q(a)} {_q(b)}) "
                         f"(rule (clearance {_n(clearance * 1000)})))")  # fmt: skip
    lines += ["  )", "  (wiring"]
    wires, vias = fixed
    for w in wires:
        pts = " ".join(f"{_n(x * 1000)} {_n(-y * 1000)}" for x, y in w.points)
        lines.append(f"    (wire (path {w.layer} {_n(w.width * 1000)} {pts}) (net {_q(w.net)}) "
                     "(type protect))")  # fmt: skip
    for v in vias:
        lines.append(f"    (via {_q(v.padstack)} {_n(v.at[0] * 1000)} {_n(-v.at[1] * 1000)} "
                     f"(net {_q(v.net)}) (type protect))")  # fmt: skip
    lines += ["  )", ")"]
    path.write_text("\n".join(lines) + "\n")
    return path


def _inset(outline: list[Point], d: float) -> list[Point]:
    """Offset a convex polygon, of either winding, inward by *d*."""
    n = len(outline)
    area = sum(outline[i][0] * outline[(i + 1) % n][1] - outline[(i + 1) % n][0] * outline[i][1]
               for i in range(n))  # fmt: skip
    sign = 1 if area > 0 else -1
    lines = []
    for i in range(n):
        (x1, y1), (x2, y2) = outline[i], outline[(i + 1) % n]
        length = math.hypot(x2 - x1, y2 - y1)
        nx, ny = -(y2 - y1) / length * sign, (x2 - x1) / length * sign
        lines.append(((x1 + nx * d, y1 + ny * d), (x2 + nx * d, y2 + ny * d)))
    out = []
    for i in range(n):
        (p1, p2), (p3, p4) = lines[i - 1], lines[i]
        den = (p1[0] - p2[0]) * (p3[1] - p4[1]) - (p1[1] - p2[1]) * (p3[0] - p4[0])
        if abs(den) < 1e-12:
            out.append(p3)
            continue
        a = p1[0] * p2[1] - p1[1] * p2[0]
        b = p3[0] * p4[1] - p3[1] * p4[0]
        out.append((round((a * (p3[0] - p4[0]) - (p1[0] - p2[0]) * b) / den, 6),
                    round((a * (p3[1] - p4[1]) - (p1[1] - p2[1]) * b) / den, 6)))  # fmt: skip
    return out


@dataclass(frozen=True)
class Wire:
    net: str
    layer: str
    width: float  # mm
    points: list[Point]  # board mm, y down


@dataclass(frozen=True)
class Via:
    net: str
    padstack: str
    at: Point


def read_ses(path: Path) -> tuple[list[Wire], list[Via]]:
    """The routed wires and vias of a Specctra session file, in board millimetres."""
    session = parse(path.read_text())
    routes = find(session, "routes")
    assert routes is not None
    res = find(routes, "resolution")
    scale = 1000 * (float(res[2]) if res is not None else 1)  # units per mm
    network = find(routes, "network_out")
    wires: list[Wire] = []
    vias: list[Via] = []
    for net in find_all(network, "net") if network is not None else []:
        name = str(net[1])
        for wire in find_all(net, "wire"):
            p = find(wire, "path")
            assert p is not None
            coords = [float(v) for v in p[3:] if not isinstance(v, list)]
            pts = [(round(coords[i] / scale, 6), round(-coords[i + 1] / scale, 6))
                   for i in range(0, len(coords), 2)]  # fmt: skip
            wires.append(Wire(name, str(p[1]), float(p[2]) / scale, pts))
        for via in find_all(net, "via"):
            vias.append(
                Via(
                    name,
                    str(via[1]),
                    (round(float(via[2]) / scale, 6), round(-float(via[3]) / scale, 6)),
                )
            )
    return wires, vias
