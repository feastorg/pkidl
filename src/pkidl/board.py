"""Assemble a KiCad board file from placed footprints, tracks, zones and text.

Zones are written with their outline only. KiCad fills them: run
``kicad-cli pcb drc --refill-zones`` (add ``--save-board`` to keep the fill).
Every UUID is derived from what the item is, so the same board always
serialises to the same bytes.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pkidl.footprint import VERSION, gen_uuid, pad_xy
from pkidl.sexpr import Node, Sym, dumps, find, find_all, num

# The two-layer stack, as KiCad 10 writes it: (id, name, type, user name).
_LAYERS = [
    (0, "F.Cu", "signal", None),
    (2, "B.Cu", "signal", None),
    (9, "F.Adhes", "user", "F.Adhesive"),
    (11, "B.Adhes", "user", "B.Adhesive"),
    (13, "F.Paste", "user", None),
    (15, "B.Paste", "user", None),
    (5, "F.SilkS", "user", "F.Silkscreen"),
    (7, "B.SilkS", "user", "B.Silkscreen"),
    (1, "F.Mask", "user", None),
    (3, "B.Mask", "user", None),
    (17, "Dwgs.User", "user", "User.Drawings"),
    (19, "Cmts.User", "user", "User.Comments"),
    (21, "Eco1.User", "user", "User.Eco1"),
    (23, "Eco2.User", "user", "User.Eco2"),
    (25, "Edge.Cuts", "user", None),
    (27, "Margin", "user", None),
    (31, "F.CrtYd", "user", "F.Courtyard"),
    (29, "B.CrtYd", "user", "B.Courtyard"),
    (35, "F.Fab", "user", None),
    (33, "B.Fab", "user", None),
]

Point = tuple[float, float]


def pad_hull(parts: Iterable[Node], net: str, margin: float) -> list[Point]:
    """The convex hull of *net*'s pads on *parts* (placed footprints), each pad's square of
    side its larger dimension grown by *margin*, counter-clockwise."""
    pts: list[Point] = []
    for fp in parts:
        for pad in find_all(fp, "pad"):
            pad_net = find(pad, "net")
            if pad_net is None or pad_net[1] != net:
                continue
            size = find(pad, "size")
            assert size is not None
            r = max(float(size[1]), float(size[2])) / 2 + margin
            cx, cy = pad_xy(fp, str(pad[1]))
            pts += [(cx - r, cy - r), (cx + r, cy - r), (cx + r, cy + r), (cx - r, cy + r)]
    if not pts:
        raise ValueError(f"no pad on net {net!r}")
    return _hull(sorted(set(pts)))


def _hull(pts: list[Point]) -> list[Point]:
    """Convex hull of sorted points (Andrew's monotone chain), counter-clockwise."""

    def cross(o: Point, a: Point, b: Point) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[Point] = []
    upper: list[Point] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return [(round(x, 6), round(y, 6)) for x, y in lower[:-1] + upper[:-1]]


def _xy(p: Point, key: str = "xy") -> Node:
    return [Sym(key), num(p[0]), num(p[1])]


def _stroke(width: float) -> Node:
    return [Sym("stroke"), [Sym("width"), num(width)], [Sym("type"), Sym("solid")]]


@dataclass
class Board:
    thickness: float = 1.6
    items: list[Node] = field(default_factory=list)
    _uuids: set[str] = field(default_factory=set, repr=False)
    extent: tuple[float, float, float, float] | None = None  # the outline's box, once drawn

    def _uuid(self, *parts: str) -> str:
        """A UUID from what the item is; repeats of the same item are numbered."""
        uid, n = gen_uuid(*parts), 1
        while uid in self._uuids:
            uid, n = gen_uuid(*parts, str(n)), n + 1
        self._uuids.add(uid)
        return uid

    def footprint(self, node: Node) -> None:
        self.items.append(node)

    def outline_rounded_rect(self, x0: float, y0: float, x1: float, y1: float, r: float) -> None:
        """Board edge: a rectangle with radius-*r* corners, on Edge.Cuts."""
        self.extent = (x0, y0, x1, y1)
        w = 0.05
        for a, b in [
            ((x0 + r, y0), (x1 - r, y0)),
            ((x1, y0 + r), (x1, y1 - r)),
            ((x1 - r, y1), (x0 + r, y1)),
            ((x0, y1 - r), (x0, y0 + r)),
        ]:
            self.items.append(
                [Sym("gr_line"), _xy(a, "start"), _xy(b, "end"), _stroke(w),
                 [Sym("layer"), "Edge.Cuts"], [Sym("uuid"), self._uuid("edge", str(a), str(b))]]
            )  # fmt: skip
        k = r * (1 - math.sqrt(0.5))
        for start, mid, end in [
            ((x0, y0 + r), (x0 + k, y0 + k), (x0 + r, y0)),
            ((x1 - r, y0), (x1 - k, y0 + k), (x1, y0 + r)),
            ((x1, y1 - r), (x1 - k, y1 - k), (x1 - r, y1)),
            ((x0 + r, y1), (x0 + k, y1 - k), (x0, y1 - r)),
        ]:
            self.items.append(
                [Sym("gr_arc"), _xy(start, "start"), _xy(mid, "mid"), _xy(end, "end"),
                 _stroke(w), [Sym("layer"), "Edge.Cuts"],
                 [Sym("uuid"), self._uuid("edge-arc", str(start), str(end))]]
            )  # fmt: skip

    def track(self, start: Point, end: Point, width: float, net: str, layer: str = "F.Cu") -> None:
        self.items.append(
            [Sym("segment"), _xy(start, "start"), _xy(end, "end"), [Sym("width"), num(width)],
             [Sym("layer"), layer], [Sym("net"), net],
             [Sym("uuid"), self._uuid("track", net, layer, str(start), str(end))]]
        )  # fmt: skip

    def via(self, at: Point, size: float, drill: float, net: str) -> None:
        """A through via, F.Cu to B.Cu."""
        self.items.append(
            [Sym("via"), _xy(at, "at"), [Sym("size"), num(size)], [Sym("drill"), num(drill)],
             [Sym("layers"), "F.Cu", "B.Cu"], [Sym("net"), net],
             [Sym("uuid"), self._uuid("via", net, str(at))]]
        )  # fmt: skip

    def zone(
        self,
        net: str,
        layer: str,
        outline: list[Point],
        *,
        clearance: float = 0.4,
        min_thickness: float = 0.25,
        thermal_gap: float = 0.5,
        thermal_bridge: float = 0.5,
        priority: int = 0,
        solid: bool = False,
    ) -> None:
        """A copper pour; islands with no pad on *net* are removed when filled.

        Pads join it through thermal reliefs, or directly when *solid*.
        """
        node: Node = [Sym("zone"), [Sym("net"), net], [Sym("layer"), layer],
                      [Sym("uuid"), self._uuid("zone", net, layer)],
                      [Sym("hatch"), Sym("edge"), num(0.5)]]  # fmt: skip
        if priority:
            node.append([Sym("priority"), Sym(str(priority))])
        connect: Node = [Sym("connect_pads"), [Sym("clearance"), num(clearance)]]
        if solid:
            connect.insert(1, Sym("yes"))
        node += [
            connect,
            [Sym("min_thickness"), num(min_thickness)],
            [Sym("fill"), Sym("yes"), [Sym("thermal_gap"), num(thermal_gap)],
             [Sym("thermal_bridge_width"), num(thermal_bridge)],
             [Sym("island_removal_mode"), Sym("0")]],
            [Sym("polygon"), [Sym("pts"), *(_xy(p) for p in outline)]],
        ]  # fmt: skip
        self.items.append(node)

    def pour(
        self,
        net: str,
        layer: str,
        *,
        around: Iterable[Node] | None = None,
        margin: float = 0.0,
        **zone: Any,
    ) -> None:
        """Pour *net* on *layer*: over the whole board, or around its pads on the parts
        *around* (their convex hull, each pad grown by *margin*), which follows the
        placement, so a block placed twice gets its pour twice. Where the pour meets other
        copper the fill keeps its clearance; where it meets another pour, priorities
        decide. *zone* is as for ``zone``."""
        if around is None:
            if self.extent is None:
                raise ValueError("pour over the whole board before its outline is drawn")
            x0, y0, x1, y1 = self.extent
            outline = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        else:
            outline = pad_hull(around, net, margin)
        self.zone(net, layer, outline, **zone)

    def keepout(
        self,
        name: str,
        layer: str,
        outline: list[Point],
        *,
        tracks: bool = False,
        vias: bool = False,
        pours: bool = False,
    ) -> None:
        """A rule area on *layer*: no tracks, vias or pours inside unless allowed."""

        def allowed(ok: bool) -> Sym:
            return Sym("allowed" if ok else "not_allowed")

        self.items.append(
            [Sym("zone"), [Sym("layer"), layer], [Sym("uuid"), self._uuid("keepout", name, layer)],
             [Sym("name"), name], [Sym("hatch"), Sym("edge"), num(0.5)],
             [Sym("connect_pads"), [Sym("clearance"), num(0)]],
             [Sym("min_thickness"), num(0.25)],
             [Sym("keepout"), [Sym("tracks"), allowed(tracks)], [Sym("vias"), allowed(vias)],
              [Sym("pads"), allowed(True)], [Sym("copperpour"), allowed(pours)],
              [Sym("footprints"), allowed(True)]],
             [Sym("fill"), [Sym("thermal_gap"), num(0.5)], [Sym("thermal_bridge_width"), num(0.5)],
              [Sym("island_removal_mode"), Sym("0")]],
             [Sym("polygon"), [Sym("pts"), *(_xy(p) for p in outline)]]]
        )  # fmt: skip

    def text(
        self,
        text: str,
        at: Point,
        *,
        layer: str = "F.SilkS",
        size: float = 1.0,
        thickness: float = 0.15,
        angle: float = 0.0,
    ) -> None:
        pos = _xy(at, "at")
        if angle:
            pos.append(num(angle))
        effects: Node = [Sym("effects"), [Sym("font"), [Sym("size"), num(size), num(size)],
                                          [Sym("thickness"), num(thickness)]]]  # fmt: skip
        if layer.startswith("B."):
            effects.append([Sym("justify"), Sym("mirror")])  # read from the back
        self.items.append(
            [Sym("gr_text"), text, pos, [Sym("layer"), layer],
             [Sym("uuid"), self._uuid("text", text, layer)], effects]
        )  # fmt: skip

    def sexpr(self) -> Node:
        layers: Node = [Sym("layers")]
        for lid, name, kind, user in _LAYERS:
            entry: Node = [Sym(str(lid)), name, Sym(kind)]
            if user:
                entry.append(user)
            layers.append(entry)
        return [
            Sym("kicad_pcb"),
            [Sym("version"), Sym(VERSION)],
            [Sym("generator"), "pkidl"],
            [Sym("generator_version"), "0.1"],
            [Sym("general"), [Sym("thickness"), num(self.thickness)],
             [Sym("legacy_teardrops"), Sym("no")]],
            [Sym("paper"), "A4"],
            layers,
            [Sym("setup"), [Sym("pad_to_mask_clearance"), Sym("0")],
             [Sym("allow_soldermask_bridges_in_footprints"), Sym("no")]],
            *self.items,
        ]  # fmt: skip

    def write(self, path: Path) -> Path:
        path.write_text(dumps(self.sexpr()) + "\n")
        return path
