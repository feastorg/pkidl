"""Assemble a KiCad board file from placed footprints, tracks, zones and text.

Zones are written with their outline only. KiCad fills them: run
``kicad-cli pcb drc --refill-zones`` (add ``--save-board`` to keep the fill).
Every UUID is derived from what the item is, so the same board always
serialises to the same bytes.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pkidl import annotations, intent
from pkidl.circuit import Area, Circuit, Net, Part, Pin, Selector
from pkidl.edge import shape as edge_shape
from pkidl.footprint import VERSION, Placement, footprint_path, gen_uuid, pad_xy, place
from pkidl.intent import (
    Align,
    Conflict,
    Decouple,
    Edge,
    Keepout,
    Place,
    Route,
    Row,
    Rules,
    Side,
    Statement,
)
from pkidl.placement import Fixed, Problem, Solution, solve
from pkidl.sexpr import Node, Sym, dumps, find, find_all, num, parse
from pkidl.units import Length, length, mm

if TYPE_CHECKING:
    from shapely.geometry import Polygon

    from pkidl.build import Built
    from pkidl.routing import Router

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


def _arc_bounds(start: Point, mid: Point, end: Point) -> list[Point]:
    """The points that bound the arc from *start* through *mid* to *end*: its ends, and
    where it passes the left, right, top and bottom of its circle."""
    (ax, ay), (bx, by), (cx, cy) = start, mid, end
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
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
    # What from_inputs loads: the circuit, and the library footprint behind each footprint
    # name it uses.
    circuit: Circuit = field(default_factory=Circuit, repr=False)
    library: dict[str, Node] = field(default_factory=dict, repr=False)
    # What the board file has said about the layout, each statement once.
    _statements: dict[Statement, None] = field(default_factory=dict, repr=False)
    name: str = ""  # what its files are called: from_inputs gives its directory's name
    # The outline as it was drawn, item by item, and what is on the board that the board
    # file does not place: its mounting holes.
    _edge: list[dict[str, Any]] = field(default_factory=list, repr=False)
    fixed: list[Fixed] = field(default_factory=list, repr=False)

    @classmethod
    def from_inputs(cls, where: Path | str) -> Board:
        """A board from its inputs: the directory holding ``circuit.json`` (the parts, their
        footprints and pad nets), ``mechanical.json`` (the outline and the mounting holes)
        and ``footprints/`` (laid out as KiCad libraries), or a file in that directory, so
        a board file passes ``__file__``.

        The outline is drawn and the holes are placed where ``mechanical.json`` puts them.
        The parts are not placed: where they go is the board file's to say. A footprint
        that pkidl ships an annotation for has its named areas (``pkidl.annotations``).
        """
        d = Path(where)
        if not d.is_dir():
            d = d.parent
        board = cls(name=d.resolve().name)
        circuit = json.loads((d / "circuit.json").read_text())
        mech = json.loads((d / "mechanical.json").read_text())
        uses = [(p["ref"], p["footprint"]) for p in circuit["parts"]]
        uses += [(f"the hole at {h['at']}", h["footprint"]) for h in mech["holes"]]
        for user, name in uses:
            path = d / "footprints" / footprint_path(name)
            if not path.is_file():
                raise ValueError(f"{user}: no footprint {name!r} at {path}")
            board.library.setdefault(name, parse(path.read_text()))
        pads = {name: [str(pad[1]) for pad in find_all(lib, "pad")]
                for name, lib in board.library.items()}  # fmt: skip
        for part in circuit["parts"]:
            if missing := sorted(set(part["pads"]) - set(pads[part["footprint"]])):
                raise ValueError(f"{part['ref']}: its footprint {part['footprint']!r} has no "
                                 f"pad {', '.join(missing)}")  # fmt: skip
        board.circuit = Circuit(circuit, pads)
        for name in dict.fromkeys(p["footprint"] for p in circuit["parts"]):
            if (note := annotations.shipped().get(name.rpartition(":")[2])) is not None:
                try:
                    board.circuit.annotate(name, annotations.fit(note, board.library[name]))
                except ValueError as e:
                    board.circuit.unfitted[name] = str(e)
        board.outline(mech["outline"])
        for hole in mech["holes"]:
            board.hole(hole["footprint"], tuple(hole["at"]), rot=hole["rot"], back=hole["back"],
                       ref=hole["ref"])  # fmt: skip
        return board

    def hole(self, footprint: str, at: Point, *, rot: float = 0.0, back: bool = False,
             ref: str = "REF**") -> Fixed:  # fmt: skip
        """Put a mounting hole on the board, or whatever else is fixed there and is no
        part of the circuit: the library footprint named *footprint*, *at* a place in
        board millimetres. Parts are kept clear of it, and a row along an edge spreads
        over what it leaves clear. Gives back what the solver is told of it."""
        if footprint not in self.library:
            raise ValueError(f"no footprint {footprint!r} in the board's library")
        x, y = at
        name = footprint.rpartition(":")[2]
        placed = Placement(footprint, ref, name, x, y, rot, back, board_only=True,
                           uid=f"hole:{x},{y}")  # fmt: skip
        self.footprint(place(self.library[footprint], placed))
        fx, fy = Length(round(x * 1_000_000)), Length(round(y * 1_000_000))
        where = ", ".join(str(v).removesuffix(" mm") for v in (fx, fy))
        fixed = Fixed(f"{name} at ({where})", footprint, fx, fy, float(rot), back)
        self.fixed.append(fixed)
        return fixed

    def __getitem__(self, ref: str) -> Part:
        """The part with this reference: ``board["U1"]``."""
        return self.circuit.part(ref)

    def parts(self, *which: str | Part | Selector) -> tuple[Part, ...]:
        """The parts selected, each once, in the order asked for: ``"U1"``, a run such as
        ``"R1..R5"``, or a selector such as ``on_net("GND")``; with nothing asked for,
        every part. See ``Circuit.parts``."""
        return self.circuit.parts(*which)

    def net(self, name: Net | str) -> Net:
        """A net by the circuit's name for it, or by the name ``name_nets`` gave it."""
        return self.circuit.net(name)

    def nets(self) -> tuple[Net, ...]:
        return self.circuit.nets()

    def rails(self, *nets: Net | str) -> tuple[Net, ...]:
        """Declare the supplies and grounds, and get them back: what ``signal_net`` leaves
        out. See ``Circuit.rails``."""
        return self.circuit.rails(*nets)

    def ground(self, *nets: Net | str) -> tuple[Net, ...]:
        """Declare which nets are ground, and get them back: ``board.ground("GND")``.
        ``decouple`` puts a capacitor by the pin on its other net. A ground is a rail
        as well. See ``Circuit.ground``."""
        return self.circuit.ground(*nets)

    def name_nets(self, names: Mapping[str, str]) -> tuple[Net, ...]:
        """Give anonymous nets a name to write and read, and get them back:
        ``vin, sw = board.name_nets({"Net-(C106-Pad1)": "VIN", "Net-(C105-Pad1)": "SW"})``.
        See ``Circuit.name_nets``."""
        return self.circuit.name_nets(names)

    def add(self, *statements: Statement) -> tuple[Statement, ...]:
        """Add statements made elsewhere, by a block function say, and give them back.
        Nothing moves: the board solves everything said about it together when it is
        built, whatever order it was said in. Saying the same thing twice says it once."""
        for statement in statements:
            if not isinstance(statement, Statement):
                raise TypeError(f"add() takes statements, such as place(...), not {statement!r}")
            try:
                statement.check(self.circuit)
            except LookupError as e:
                raise LookupError(f"{statement}: {e.args[0]}") from None
        for statement in statements:
            self._statements.setdefault(statement)
        return statements

    def place(
        self,
        part: Part,
        *,
        against: Edge | None = None,
        inset: Length | str | None = None,
        between: tuple[Part, Part] | None = None,
        facing: Edge | None = None,
        near: Pin | Part | None = None,
        within: Length | str | None = None,
        side: Side | str | None = None,
        toward: Edge | None = None,
        centre: bool = False,
    ) -> Place:
        """Say where *part* goes, and get the statement back. See ``pkidl.place``."""
        statement = intent.place(part, against=against, inset=inset, between=between,
                                 facing=facing, near=near, within=within, side=side,
                                 toward=toward, centre=centre)  # fmt: skip
        self.add(statement)
        return statement

    def align(self, *parts: Part, grid: Length | str) -> Align:
        """Say that *parts* sit a whole number of *grid* steps apart, and get the
        statement back. See ``pkidl.align``."""
        statement = intent.align(*parts, grid=grid)
        self.add(statement)
        return statement

    def row(self, parts: Iterable[Part], *, along: Edge, pitch: Length | str = "even",
            inset: Length | str | None = None) -> Row:  # fmt: skip
        """Say that *parts* go in a row along an edge, in the order named, and get the
        statement back. See ``pkidl.row``."""
        statement = intent.row(parts, along=along, pitch=pitch, inset=inset)
        self.add(statement)
        return statement

    def decouple(self, part: Part, caps: Iterable[Part], *, within: Length | str) -> Decouple:
        """Say that *caps* decouple *part*, one by each of its supply pins, and get the
        statement back. See ``pkidl.decouple``."""
        statement = intent.decouple(part, caps, within=within)
        self.add(statement)
        return statement

    def annotate(
        self, part: Part, *, pins: Mapping[str, int | str] | None = None,
        **areas: tuple[tuple[Length | str, Length | str], tuple[Length | str, Length | str]]
    ) -> tuple[Area, ...]:  # fmt: skip
        """Say what *part*'s footprint means, where no annotation ships for it: each
        named area by two opposite corners, in the footprint's own coordinates as a
        footprint editor shows them, and get the areas back.
        ``(antenna,) = board.annotate(u1, antenna=((0 * mm, -8.4 * mm), (16 * mm, -2.6 * mm)))``.
        Every part with that footprint has them.

        *pins* names *part*'s pins, each name with the pin's number:
        ``board.annotate(q, pins={"B": 1, "E": 2, "C": 3})``, and then ``q.pin("B")``.
        Only *part* has the names: a footprint does not say which pad of a transistor
        is its base."""
        part = self.circuit.part(part.ref)
        boxes = {}
        for name, corners in areas.items():
            (x0, y0), (x1, y1) = (tuple(length(v).nm for v in corner) for corner in corners)
            if x0 == x1 or y0 == y1:
                raise ValueError(f"{part}: area {name} has no size")
            boxes[name] = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        names = {name: str(number) for name, number in (pins or {}).items()}
        self.circuit.annotate(part.footprint, boxes, {part.ref: names})
        return tuple(part.area(name) for name in areas)

    def keepout(self, area: Area, *, copper: bool = False, both_sides: bool = False) -> Keepout:
        """Say what stays out of an area of a part, and get the statement back. See
        ``pkidl.keepout``."""
        statement = intent.keepout(area, copper=copper, both_sides=both_sides)
        self.add(statement)
        return statement

    def rules(self, *, track: Length | str, clearance: Length | str,
              edge: Length | str = 0.5 * mm) -> Rules:  # fmt: skip
        """Say the widths the board's copper is held to, and get the statement back. See
        ``pkidl.intent.rules``."""
        statement = intent.rules(track=track, clearance=clearance, edge=edge)
        self.add(statement)
        return statement

    def route(self) -> Route:
        """Say that the board is routed when it is built, and get the statement back.
        See ``pkidl.intent.route``."""
        statement = intent.route()
        self.add(statement)
        return statement

    def statements(self, about: Part | str | None = None) -> tuple[Statement, ...]:
        """What has been said about the layout, in the order it was added, which means
        nothing; with *about*, what speaks of that part."""
        if about is None:
            return tuple(self._statements)
        part = self.circuit.part(about.ref if isinstance(about, Part) else about)
        return tuple(s for s in self._statements if part in s.mentions())

    def conflicts(self) -> tuple[Conflict, ...]:
        """Each aspect of a part that two statements give differently, with both."""
        return intent.conflicts(self._statements)

    def solve(self) -> Solution:
        """Where everything said puts each part: a pose for each part placed, the parts
        nothing places, and what was said that does not hold, with its lines. Nothing
        on the board moves. See ``pkidl.placement``."""
        try:
            edge = self.edge()
        except ValueError as e:  # an outline that is not one board: nothing is placed on it
            return Solution({}, (), (Problem((), str(e)),), ())
        return solve(self.circuit, self.library, self.extent, self._statements,
                     edge=edge, fixed=self.fixed)  # fmt: skip

    def edge(self) -> Polygon | None:
        """The area inside the board's outline, in board millimetres, or None for a
        board whose outline was not drawn item by item (only its ``extent`` given).
        See ``pkidl.edge``."""
        return edge_shape(self._edge) if self._edge else None

    def build(self, outdir: Path | str, name: str | None = None, *,
              router: Router | None = None) -> Built:  # fmt: skip
        """Write the board's KiCad files into *outdir*, named *name* or, for a board
        from its inputs, after their directory: the parts where everything said puts
        them, each area kept clear as a rule area, and the board routed by *router*
        (Freerouting where none is given) if ``route()`` was said. The board itself is
        left as it was. See ``pkidl.build``."""
        from pkidl.build import build  # the router's files are written from a board

        if not (name or self.name):
            raise ValueError("build() needs a name for the board's files: give name=")
        return build(self, Path(outdir), name or self.name, router)

    def _uuid(self, *parts: str) -> str:
        """A UUID from what the item is; repeats of the same item are numbered."""
        uid, n = gen_uuid(*parts), 1
        while uid in self._uuids:
            uid, n = gen_uuid(*parts, str(n)), n + 1
        self._uuids.add(uid)
        return uid

    def footprint(self, node: Node) -> None:
        self.items.append(node)

    def outline(self, items: Iterable[dict[str, Any]]) -> None:
        """Board edge on Edge.Cuts from drawn items, as ``mechanical.json`` lists them:
        each a ``type`` (``gr_line``, ``gr_arc``, ``gr_rect``, ``gr_circle`` or ``gr_poly``)
        with the points that type has (``start`` and ``end``; ``mid`` for an arc; ``center``
        and a point on it, ``end``, for a circle; ``pts`` for a polygon)."""
        box: list[Point] = []
        for item in items:
            kind = item["type"]
            if kind not in ("gr_line", "gr_arc", "gr_rect", "gr_circle", "gr_poly"):
                raise ValueError(f"outline: {kind!r} is not something Edge.Cuts is drawn with")
            pts = {k: (float(item[k][0]), float(item[k][1]))
                   for k in ("start", "mid", "end", "center") if k in item}  # fmt: skip
            node: Node = [Sym(kind), *(_xy(p, k) for k, p in pts.items())]
            if kind == "gr_poly":
                corners = [(float(x), float(y)) for x, y in item["pts"]]
                node.append([Sym("pts"), *(_xy(p) for p in corners)])
                box += corners
            elif kind == "gr_arc":
                box += _arc_bounds(pts["start"], pts["mid"], pts["end"])
            elif kind == "gr_circle":
                (cx, cy), r = pts["center"], math.dist(pts["center"], pts["end"])
                box += [(cx - r, cy - r), (cx + r, cy + r)]
            else:
                box += [pts["start"], pts["end"]]
            node.append(_stroke(0.05))
            if kind in ("gr_rect", "gr_circle", "gr_poly"):
                node.append([Sym("fill"), Sym("no")])
            uid = self._uuid("edge", kind, str(sorted(item.items())))
            node += [[Sym("layer"), "Edge.Cuts"], [Sym("uuid"), uid]]
            self.items.append(node)
            self._edge.append(dict(item))
        if self.extent is not None:
            box += [self.extent[:2], self.extent[2:]]
        xs, ys = [round(x, 6) for x, _ in box], [round(y, 6) for _, y in box]
        self.extent = (min(xs), min(ys), max(xs), max(ys))

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
            self._edge.append({"type": "gr_line", "start": a, "end": b})
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
            self._edge.append({"type": "gr_arc", "start": start, "mid": mid, "end": end})

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

    def rule_area(
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
