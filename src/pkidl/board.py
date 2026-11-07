"""Assemble a KiCad board file from placed footprints, tracks, zones and text.

Zones are written with their outline only. KiCad fills them: run
``kicad-cli pcb drc --refill-zones`` (add ``--save-board`` to keep the fill).
Every UUID is derived from what the item is, so the same board always
serialises to the same bytes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from pkidl.footprint import gen_uuid
from pkidl.sexpr import Node, Sym, dumps, num

VERSION = "20260206"  # KiCad 10 board format

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


def _xy(p: Point, key: str = "xy") -> Node:
    return [Sym(key), num(p[0]), num(p[1])]


def _stroke(width: float) -> Node:
    return [Sym("stroke"), [Sym("width"), num(width)], [Sym("type"), Sym("solid")]]


@dataclass
class Board:
    thickness: float = 1.6
    items: list[Node] = field(default_factory=list)
    _uuids: set[str] = field(default_factory=set, repr=False)

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
