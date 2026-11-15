"""Placement: where each part goes, worked out from what the board file said.

``solve`` reads a board's statements and gives a ``Solution``: a pose for each part it
could place, the parts nothing places, and every statement it could not make hold, each
with the line that made it. It moves nothing and never drops a statement to make the
others fit.

What each statement means here:

- ``against=`` an edge: the part lies along it, its longer side to the edge. ``inset=`` is
  from the edge to the centres of the part's pads nearest it, or to its outline when it
  has no pads; with no inset the part's outline touches the edge from inside, or the
  part is as far in as the rules keep its copper from the edge. Along the
  edge it is centred, unless a second edge makes a corner, where it may lie along either.
- ``facing=`` an edge: the side of the part that is up in its footprint, as a library
  draws it, is turned to that edge of the board as the front shows it, whichever face
  the part is on.
- ``between=`` two parts: its centre is midway between theirs. With ``against=`` an
  edge as well, the edge says how far the part is from it, and ``between=`` where it is
  along it.
- ``near=`` a pin or part, ``within=`` a distance: the nearest place to it that is on the
  board and clear of every other part, a pad of the part no further than the distance
  from a pad of what it is near, centre to centre. ``toward=`` an edge: on that side of
  what it is near, its outline wholly beyond that part's outline. The distance is
  still between pads, so it has to reach past as much of that part as lies between its
  pads and that side.
- ``centre=True``: the middle of the part's outline is at the middle of the board.
- ``at=`` a point: the footprint's origin is there, two lengths across and down from
  the top left corner of the box around the outline, as the front shows the board
  whichever face the part is on. With ``of=`` a pin of the part, that pin is there
  and the origin is wherever that puts it, the way round the part is.
- ``on=`` something fixed on the board: the point is one of that thing, in its own
  footprint's coordinates, turned and mirrored as the thing is, and its origin where
  none is given. The part may overlap that thing, and nothing else.
- ``side=``: the face of the board it is on; the front when nothing says.
- ``row`` along an edge: each part lies against the edge as ``against=`` has it, and
  they follow one another in the order named, from the left or from the top. With an
  even pitch the gaps between their outlines, and from each end of the edge to the
  outline nearest it, are equal; with a length, the middles of their outlines are that
  far apart about the middle of the edge. Where a part of a row is depends on the
  sizes of the others, never on where anything else is. Its parts are turned the same
  way, the way that makes the row's connections to the rest of the board shortest,
  but for a part that is ``facing=`` an edge. The turn is counted from how each part
  lies along the edge with its length running the way the row runs, so a part drawn
  on end and one drawn across are in one row with pin 1 of each at the same end.
- ``row`` beside a part, toward an edge: the parts are side by side on that side of the
  part, in the order named, from the top down its left or right side or from the left
  along its top or bottom. Each stands across the row, the shorter side of its outline
  along the row's line and the near sides of them all in one line, turned as the parts
  of a row along an edge are. The middles of their outlines are one pitch apart: the
  length given, or the least that keeps each outline clear of the others and their
  pads as far apart as the rules say. The row is on that side of the part's outline:
  touching it, or as far off as keeps their pads apart, the middle of the row level
  with the middle of the part. Where that is not clear of all a part that looks for a
  place is kept clear of, the row is a step at a time further out and along its line,
  the place nearest that first one, and of two as near the one less far along, then
  the one toward the top or the left. One that has no place within 30 mm is a problem,
  and none of it is placed.
- ``decouple`` a part with capacitors: each capacitor is across ground, as the board
  file declares it, and one supply of the part, and is placed as ``near=`` one of the
  part's pins on that supply has it, with the capacitor's own pad on the supply the
  one within the distance. Capacitors take the part's pins on a supply one each, in
  the order named and the order of the pin numbers. One with no pin left is a problem,
  and so is one that is not across ground and a net the part is on.
- ``align``: the parts' first pins are a whole number of grid steps apart, across and
  along. It is checked, and moves nothing.
- ``keepout`` of an area of a part: no other part's outline reaches into the area, on
  the part's face or on both. It goes where its part goes, and ``Solution.keepouts``
  says where that is, for the copper drawn afterwards.
- ``keepout`` of something fixed on the board: the box around its outline, on its face
  or on both, is in ``Solution.keepouts`` for the copper drawn afterwards. It keeps no
  part out: a part is kept off a fixed thing with nothing said, but for one ``on=`` it.
  A pad on a net whose middle is inside the box, and not on its side, is a problem
  where every face it has copper on is kept: a pad on the surface of a kept face, and
  a pin in a hole when both are. No track can reach it.
- ``apart``: the outline of each part named is no nearer the outline of the thing
  than the distance, whichever face either is on. It places nothing. A part that looks
  for its place looks only where it holds, and a place that is given and breaks it is
  reported. Of the rules' distance between parts and every ``apart`` that speaks of
  the part and the thing, the largest holds. A part ``on=`` the thing it is kept
  apart from is a problem, and is left where it was put.

Which way round a part is, where nothing says, is the way that makes its connections
shortest. A part's outline is the box around its pads, courtyard and fabrication
drawing, or around its pads and what its silk draws where the footprint has neither,
as an older library draws a part's body; two parts on one face may touch and not
overlap, and a part with holes takes both faces. Pads of two parts on different nets
are no closer than the clearance the board's ``rules`` say, each pad taken as the box
around it: a pair that is closer is reported, and a part that looks for a place looks
only where its pads are clear.
A pad is no nearer the board's edge than the rules' edge clearance, held the same way,
and a part ``against=`` an edge with no inset is as far in as that takes.

Where the rules say how the board is assembled, the pads of two parts are kept as far
apart as they say whatever nets they are on, and so are the outlines of two parts, and
of a part and what is fixed on the board, between those that share a face. A part that
looks for a place looks only where both are kept; a row beside a part with no pitch
said takes the least pitch that keeps them and first looks that far from the part; and
a place that is given and breaks one is reported, a pair of parts once. The parts of a
row whose pitch is said are as far apart as it puts their outlines, and a part ``on=``
a thing as near that thing as it is put: their pads are held as any are.

A part lies inside the board's outline as it is drawn (``pkidl.edge``), rounded corners
and cut-outs included, and clear of what is fixed on the board: its mounting holes, each
taken as the box around its own footprint, as a part is. Neither moves a part: one that
is put outside the outline or over a hole is reported. A part that looks for a place
(``near=``) looks only where it is clear of both, and a row spreads over the longest
stretch of its edge that is clear, across the strip from the edge to the far side of
its parts. Only what is
fixed narrows a row, never another part, so a row still does not depend on where
anything is placed. An edge is a side of the box around the outline.

Everything is in whole nanometres, and parts are placed in an order made from what
depends on what, then those that look for a place after those given one, then from
their references, so the same statements give the same placement whatever order they
were added in.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from functools import cache, lru_cache
from itertools import combinations

import numpy as np
from shapely import intersects_xy, prepare
from shapely.geometry import Polygon
from shapely.geometry import box as _area
from shapely.prepared import prep

from pkidl.circuit import Area, Circuit, Pin, natural
from pkidl.edge import arc_bounds
from pkidl.intent import (
    Align,
    Apart,
    Decouple,
    Edge,
    Fixed,
    Inside,
    Keepout,
    Place,
    Region,
    Row,
    Rules,
    Side,
    Statement,
    canonical,
    conflicts,
)
from pkidl.sexpr import Node, find, find_all
from pkidl.units import Length

STEP = Length(100_000)  # how finely a place near something is looked for

Box = tuple[int, int, int, int]  # x0, y0, x1, y1
_BODY = {"F.CrtYd", "B.CrtYd", "F.Fab", "B.Fab"}
_SILK = {"F.SilkS", "B.SilkS"}  # where an older footprint draws its body, and nowhere else
_ROTATIONS = (0, 90, 180, 270)


@dataclass(frozen=True)
class Pose:
    """Where a part is: its footprint's origin, its rotation in degrees as KiCad counts
    them, and whether it is on the back."""

    x: Length
    y: Length
    rot: int = 0
    back: bool = False


@dataclass(frozen=True)
class Problem:
    """Something said that does not hold, the parts it is about and the statements that
    said it."""

    parts: tuple[str, ...]
    text: str
    statements: tuple[Statement, ...] = ()

    def __str__(self) -> str:
        lines = list(dict.fromkeys(str(s.source) for s in self.statements if s.source))
        return self.text + (f" ({', '.join(lines)})" if lines else "")


@dataclass(frozen=True)
class Kept:
    """An area kept clear, where it is on the board: its box (x0, y0, x1, y1) and the
    faces it is kept clear on."""

    statement: Keepout
    box: tuple[Length, Length, Length, Length]
    front: bool
    back: bool


@dataclass(frozen=True)
class Solution:
    """What ``solve`` found. ``chosen`` lists what it decided where nothing said, and
    ``keepouts`` where each area kept clear is, for those whose part is placed."""

    poses: Mapping[str, Pose]
    free: tuple[str, ...]
    problems: tuple[Problem, ...]
    chosen: tuple[str, ...]
    keepouts: tuple[Kept, ...] = ()

    @property
    def ok(self) -> bool:
        """Every part placed, and everything said about them holding."""
        return not self.free and not self.problems


@dataclass(frozen=True)
class _Shape:
    """A footprint's pads (number and centre, which is its hole where it has one) and
    outline, about its origin, the box around each pad's copper, and the numbers of
    the pads that are in holes, their copper on both faces."""

    pads: tuple[tuple[str, int, int], ...]
    box: Box
    through: bool
    copper: tuple[tuple[str, Box], ...] = ()
    holed: frozenset[str] = frozenset()


def _nm(value: object) -> int:
    return round(float(str(value)) * 1_000_000)


def _shape(footprint: Node) -> _Shape:
    pads, copper, xs, ys = [], [], [], []
    holed = set()
    through = False
    for pad in find_all(footprint, "pad"):
        at, size = find(pad, "at"), find(pad, "size")
        assert at is not None and size is not None
        x, y, w, h = _nm(at[1]), _nm(at[2]), _nm(size[1]), _nm(size[2])
        # The box around the pad once it is turned in its footprint.
        turn = math.radians(float(at[3])) if len(at) > 3 else 0.0
        cos, sin = abs(math.cos(turn)), abs(math.sin(turn))
        w, h = round(w * cos + h * sin), round(w * sin + h * cos)
        pads.append((str(pad[1]), x, y))
        # A pad's place is its hole's. Its copper is off that by the drill's offset,
        # which turns with the pad: counter-clockwise with y down.
        drill = find(pad, "drill")
        if drill is not None and (off := find(drill, "offset")) is not None:
            ox, oy = _nm(off[1]), _nm(off[2])
            x += round(ox * math.cos(turn) + oy * math.sin(turn))
            y += round(oy * math.cos(turn) - ox * math.sin(turn))
        xs += [x - (w + 1) // 2, x + (w + 1) // 2]
        ys += [y - (h + 1) // 2, y + (h + 1) // 2]
        copper.append((str(pad[1]), (xs[-2], ys[-2], xs[-1], ys[-1])))
        through = through or pad[2] in ("thru_hole", "np_thru_hole")
        if pad[2] == "thru_hole":
            holed.add(str(pad[1]))
    drawn = [(item, layer[1]) for item in footprint[2:]
             if isinstance(item, list) and str(item[0]).startswith("fp_") and item[0] != "fp_text"
             and (layer := find(item, "layer")) is not None]  # fmt: skip
    # A footprint with no courtyard and no fabrication drawing has its body on the silk.
    body = _BODY if any(layer in _BODY for _, layer in drawn) else _SILK
    for item, layer in drawn:
        if layer not in body:
            continue
        points = [p for k in ("start", "end") if (p := find(item, k)) is not None]
        points += find_all(find(item, "pts") or [], "xy")
        if (mid := find(item, "mid")) is not None and len(points) == 2:
            # An arc is all of itself: it bulges past its ends and the point between.
            start, end = ((float(p[1]), float(p[2])) for p in points)
            between = (float(mid[1]), float(mid[2]))
            bounds = [between, *arc_bounds(start, between, end)]
            xs += [_nm(x) for x, _ in bounds]
            ys += [_nm(y) for _, y in bounds]
        centre = find(item, "center")
        if centre is not None and (end := find(item, "end")) is not None:
            r = round(math.dist((_nm(centre[1]), _nm(centre[2])), (_nm(end[1]), _nm(end[2]))))
            xs += [_nm(centre[1]) - r, _nm(centre[1]) + r]
            ys += [_nm(centre[2]) - r, _nm(centre[2]) + r]
        xs += [_nm(p[1]) for p in points]
        ys += [_nm(p[2]) for p in points]
    if not xs:  # nothing drawn: a point
        return _Shape((), (0, 0, 0, 0), False)
    return _Shape(tuple(pads), (min(xs), min(ys), max(xs), max(ys)), through, tuple(copper),
                  frozenset(holed))  # fmt: skip


def _turn(x: int, y: int, rot: int, back: bool) -> tuple[int, int]:
    """A point of a footprint, turned as KiCad turns it: mirrored in Y on the back, then
    rotated counter-clockwise as seen from the front."""
    if back:
        y = -y
    return {0: (x, y), 90: (y, -x), 180: (-x, -y), 270: (-y, x)}[rot]


@cache
def _turned(shape: _Shape, rot: int, back: bool) -> _Shape:
    pads = [(number, *_turn(x, y, rot, back)) for number, x, y in shape.pads]
    x0, y0, x1, y1 = shape.box
    corners = [_turn(x, y, rot, back) for x in (x0, x1) for y in (y0, y1)]
    xs, ys = [c[0] for c in corners], [c[1] for c in corners]
    copper = []
    for number, (px0, py0, px1, py1) in shape.copper:
        (ax, ay), (bx, by) = _turn(px0, py0, rot, back), _turn(px1, py1, rot, back)
        copper.append((number, (min(ax, bx), min(ay, by), max(ax, bx), max(ay, by))))
    return _Shape(tuple(pads), (min(xs), min(ys), max(xs), max(ys)), shape.through,
                  tuple(copper), shape.holed)  # fmt: skip


_PASSES = 24  # how many times everything is placed before a placement is said not to settle


def _listed(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


_AT_A_TIME = 4096  # the offsets a place near something is looked for at, at once
_FURTHER = Length(30_000_000)  # as far as a place is looked for to say how far off it is
_EDGE = "the board's edge"
_AREA = "the edge of its area"
_Grid = tuple[list[tuple[int, int, int]], np.ndarray, np.ndarray]
_Stood = Mapping[str, tuple[_Shape, int, int]]  # each part's shape, and where its origin is
_SIFT = True  # whether those are sifted all at once first: off, each is tried in turn


@lru_cache(maxsize=8)  # a 30 mm distance is 44 MB of them, a 15 mm one 11
def _offsets(limit: int, step: int) -> _Grid:
    """Every offset on a grid of *step* within *limit*, nearest first: each as its
    distance squared, dy and dx, and the dx and dy of them all as arrays."""
    n = limit // step
    offsets = sorted((dx * dx + dy * dy, dy, dx)
                     for dx in range(-n * step, n * step + 1, step)
                     for dy in range(-n * step, n * step + 1, step)
                     if dx * dx + dy * dy <= limit * limit)  # fmt: skip
    return (offsets, np.array([dx for _, _, dx in offsets], dtype=np.int64),
            np.array([dy for _, dy, _ in offsets], dtype=np.int64))  # fmt: skip


@lru_cache(maxsize=2)
def _beyond(limit: int, step: int) -> tuple[np.ndarray, np.ndarray]:
    """Every place on a grid of *step* within *limit* that is no nearer a part than a
    row beside it starts: how far out from there and how far along, nearest first; of
    two as near, the one less far along, then the one back along the row's line."""
    n = limit // step
    out, along = (v.ravel() for v in np.meshgrid(np.arange(n + 1, dtype=np.int64),
                                                 np.arange(-n, n + 1, dtype=np.int64),
                                                 indexing="ij"))  # fmt: skip
    near = out * out + along * along <= n * n
    out, along = out[near], along[near]
    order = np.lexsort((along, np.abs(along), out * out + along * along))
    return out[order] * step, along[order] * step


def _apart(gap: int, d: int) -> int:
    """How far apart one way two pads *d* apart the other way are when they are *gap*
    apart in all, to the nanometre above."""
    return math.isqrt(gap * gap - d * d - 1) + 1


def _lies(row: Row) -> Edge:
    """The edge whose row the parts of *row* lie as: its own, or for a row beside a
    part one its line runs across, so that each part stands across the row."""
    if row.along is not None:
        return row.along
    return Edge.TOP if row.toward in (Edge.LEFT, Edge.RIGHT) else Edge.LEFT


def _moved(box: Box, x: int, y: int) -> Box:
    return (box[0] + x, box[1] + y, box[2] + x, box[3] + y)


def _overlap(a: Box, b: Box) -> bool:
    """Touching is not overlapping."""
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _off(a: Box, b: Box) -> int:
    """How far apart two boxes are: nothing where they touch or overlap."""
    dx, dy = max(a[0] - b[2], b[0] - a[2], 0), max(a[1] - b[3], b[1] - a[3], 0)
    return math.isqrt(dx * dx + dy * dy)


def _by(x0: np.ndarray, y0: np.ndarray, x1: np.ndarray, y1: np.ndarray, taken: Box,
        room: int) -> np.ndarray:  # fmt: skip
    """Whether each of the boxes overlaps *taken*, or with *room* is nearer it than that."""
    t0, t1, t2, t3 = taken
    if not room:
        return (x0 < t2) & (t0 < x1) & (y0 < t3) & (t1 < y1)
    # Within that of it both ways, which few are, and of those the ones by a corner
    # of it are as far off as they are from the corner.
    near = (x0 < t2 + room) & (t0 - room < x1) & (y0 < t3 + room) & (t1 - room < y1)
    at = np.nonzero(near)
    if at[0].size:
        xa, ya, xb, yb = (np.broadcast_to(v, near.shape)[at] for v in (x0, y0, x1, y1))
        dx = np.maximum(np.maximum(xa - t2, t0 - xb), 0)
        dy = np.maximum(np.maximum(ya - t3, t1 - yb), 0)
        near[at] = dx * dx + dy * dy < room * room
    return near


def _surely(taken: Box, room: int) -> Box:
    """*taken* grown so that a box overlapping it is surely nearer *taken* than *room*,
    by a corner too: what a sift may leave out without looking closer."""
    by = math.isqrt(room * room // 2)
    return (taken[0] - by, taken[1] - by, taken[2] + by, taken[3] + by)


def _area_of(kept: Keepout) -> Area:
    """The area of a part that *kept* is of, for one that is not of a fixed thing."""
    assert isinstance(kept.area, Area)
    return kept.area


def solve(
    circuit: Circuit,
    library: Mapping[str, Node],
    extent: tuple[float, float, float, float] | None,
    statements: Iterable[Statement],
    *,
    edge: Polygon | None = None,
    fixed: Iterable[Fixed] = (),
) -> Solution:
    """Place *circuit*'s parts, from footprints in *library*, on a board whose outline
    has the box *extent* (millimetres), as *statements* say. *edge* is the area inside
    the outline, where it is not the whole of that box, and *fixed* what is on the board
    already for parts to keep clear of."""
    statements = canonical(statements)
    if found := conflicts(statements):
        return Solution({}, (), tuple(Problem((c.part,), str(c)) for c in found), ())
    if extent is None:
        raise ValueError("a board is placed on once its outline is drawn")
    return _Solver(circuit, library, extent, statements, edge, tuple(fixed)).solution()


def _swung(x: int, y: int, rot: float, back: bool) -> tuple[int, int]:
    """A point of a footprint turned *rot* degrees, any angle, as ``_turn`` turns it."""
    if rot % 90 == 0:  # a right angle is exact
        return _turn(x, y, int(rot) % 360, back)
    a, y = math.radians(rot), -y if back else y
    return round(x * math.cos(a) + y * math.sin(a)), round(y * math.cos(a) - x * math.sin(a))


def _spun(box: Box, rot: float, back: bool) -> Box:
    """The box around *box* once its footprint is turned *rot* degrees, any angle, as
    KiCad turns it: mirrored in Y on the back, then counter-clockwise from the front."""
    corners = [(x, y) for x in (box[0], box[2]) for y in (box[1], box[3])]
    if rot % 90 == 0:  # a right angle is exact
        turned = [_turn(x, y, int(rot) % 360, back) for x, y in corners]
        xs, ys = [float(x) for x, _ in turned], [float(y) for _, y in turned]
    else:
        a = math.radians(rot)
        cos, sin = math.cos(a), math.sin(a)
        xs = [x * cos + (-y if back else y) * sin for x, y in corners]
        ys = [-x * sin + (-y if back else y) * cos for x, y in corners]
    return (math.floor(min(xs)), math.floor(min(ys)), math.ceil(max(xs)), math.ceil(max(ys)))


class _Solver:
    def __init__(
        self,
        circuit: Circuit,
        library: Mapping[str, Node],
        extent: tuple[float, float, float, float],
        statements: list[Statement],
        edge: Polygon | None = None,
        fixed: tuple[Fixed, ...] = (),
    ) -> None:
        self.board: Box = (_nm(extent[0]), _nm(extent[1]), _nm(extent[2]), _nm(extent[3]))
        # The area inside the outline, in nanometres, where it is not the whole box.
        self.edge: Polygon | None = None
        if edge is not None:
            # In whole nanometres, as everything here is: 129.54 mm is not 129540000 nm
            # until it is rounded, and a board is its box only when it is exactly that.
            inside = Polygon([(_nm(x), _nm(y)) for x, y in edge.exterior.coords],
                             [[(_nm(x), _nm(y)) for x, y in ring.coords]
                              for ring in edge.interiors])  # fmt: skip
            if not inside.equals(_area(*self.board)):
                self.edge, self.within = inside, prep(inside)
                # A hair larger, for sifting: no corner of a box on the board is off it.
                self.roomy = inside.buffer(2)
                prepare(self.roomy)
        # Where the box around the outline is not board, piece by piece: a part clear
        # of the box around each piece is on the board without looking further.
        self.cuts: list[Box] = []
        if self.edge is not None:
            off = _area(*self.board).difference(self.edge)
            for piece in getattr(off, "geoms", [off]):
                x0, y0, x1, y1 = piece.bounds
                self.cuts.append((math.floor(x0), math.floor(y0), math.ceil(x1), math.ceil(y1)))
        # What is fixed on the board: each with its outline there, and whether it has
        # holes and so takes both faces.
        self.fixed: list[tuple[Fixed, Box, bool]] = []
        # In an order of their own, so that which of two a problem names is not the
        # order they were put on the board in.
        for f in sorted(fixed, key=lambda f: (f.x.nm, f.y.nm, f.label, f.rot, f.back)):
            if f.footprint not in library:
                raise ValueError(f"{f.label}: no footprint {f.footprint!r} to keep clear of")
            shape = _shape(library[f.footprint])
            self.fixed.append((f, _moved(_spun(shape.box, f.rot, f.back), f.x.nm, f.y.nm),
                               shape.through))  # fmt: skip
        self.things = {f: box for f, box, _ in self.fixed}
        self.runs: dict[Row, tuple[int, int]] = {}  # the clear stretch of each row's edge
        # How far apart the board's rules keep copper on different nets, if it has rules.
        self.rules = [s for s in statements if isinstance(s, Rules)]
        self.gap = max((s.clearance.nm for s in self.rules), default=0)
        # And how far they keep copper from the board's edge.
        self.margin = max((s.edge.nm for s in self.rules), default=0)
        # And, for the way the board is assembled, the pads of different parts,
        # whatever their nets, and the outlines of parts and of what is fixed.
        self.pads_apart = max((s.apart()[0].nm for s in self.rules), default=0)
        self.bodies_apart = max((s.apart()[1].nm for s in self.rules), default=0)
        self._boxes: dict[str, tuple[Pose, Box]] = {}
        self.circuit = circuit
        self.asks: dict[str, list[Place]] = {}
        self.aligns = [s for s in statements if isinstance(s, Align)]
        # The areas of the board each part is said to be inside: each once, with where it
        # is on the board and every statement that says so.
        said: dict[str, dict[Region, list[Inside]]] = {}
        for s in statements:
            if isinstance(s, Inside):
                for part in s.parts:
                    said.setdefault(part.ref, {}).setdefault(s.area, []).append(s)
        self.areas: dict[str, list[tuple[Region, Box, tuple[Inside, ...]]]] = {
            ref: [(area, area.within(self.board), tuple(by)) for area, by in areas.items()]
            for ref, areas in said.items()
        }
        # Each area kept clear, as this circuit has it, whichever board's part the
        # statement was written with.
        self.keeps = [(s, circuit.part(s.area.part.ref).area(s.area.name).box)
                      for s in statements
                      if isinstance(s, Keepout) and isinstance(s.area, Area)]  # fmt: skip
        # And each thing fixed on the board that copper is kept from under.
        self.clears = [(s, s.area) for s in statements
                       if isinstance(s, Keepout) and isinstance(s.area, Fixed)]  # fmt: skip
        # What places each part: its place statements, then the rows it is in.
        self.rows: dict[str, list[Row]] = {}
        self.said: dict[str, list[Statement]] = {}
        for s in statements:
            if isinstance(s, Place):
                self.asks.setdefault(s.part.ref, []).append(s)
                self.said.setdefault(s.part.ref, []).append(s)
        self.unordered: list[Problem] = []  # found once, before anything is placed
        for s, thing in self.clears:
            if thing not in self.things:
                self.unordered.append(Problem((), f"{s}: {thing} is not fixed on the board", (s,)))
        # How far each part is kept from a thing by what is said of the two: the most
        # any ``apart`` says, with each statement that says that much.
        self.aparts: dict[str, dict[Fixed, tuple[int, tuple[Apart, ...]]]] = {}
        upon: dict[tuple[str, Fixed], list[Statement]] = {}
        for s in statements:
            if not isinstance(s, Apart):
                continue
            if s.thing not in self.things:
                refs = tuple(p.ref for p in s.parts)
                self.unordered.append(Problem(refs, f"{s}: {s.thing} is not fixed on the board",
                                              (s,)))  # fmt: skip
                continue
            for part in s.parts:
                if on := [ask for ask in self.asks.get(part.ref, []) if ask.on == s.thing]:
                    # Said to be on it and to be kept from it: it stays where it was
                    # put, and is told once, of the statement that keeps it furthest.
                    upon.setdefault((part.ref, s.thing), [*on]).append(s)
                    continue
                far, by = self.aparts.setdefault(part.ref, {}).get(s.thing, (0, ()))
                if s.distance.nm >= far:
                    by = (*by, s) if s.distance.nm == far else (s,)
                    self.aparts[part.ref][s.thing] = (s.distance.nm, by)
        for (ref, thing), said_of in upon.items():
            most = max((s for s in said_of if isinstance(s, Apart)), key=lambda s: s.distance.nm)
            self.unordered.append(Problem(
                (ref,), f"{ref} is placed on {thing}, and {most} keeps it {most.distance} "
                "from it", tuple(said_of)))  # fmt: skip
        for s in statements:
            if isinstance(s, Row):
                for part in s.parts:
                    self.asks.setdefault(part.ref, [])
                    self.rows.setdefault(part.ref, []).append(s)
                    self.said.setdefault(part.ref, []).append(s)
        self.shapes: dict[str, _Shape] = {}
        self.nets: dict[str, dict[str, str]] = {}
        for part in circuit.parts():
            if part.footprint not in library:
                raise ValueError(f"{part}: no footprint {part.footprint!r} to place")
            self.shapes[part.ref] = _shape(library[part.footprint])
            self.nets[part.ref] = {p.number: p.net.name for p in part.pins() if p.net is not None}
        self.barred: set[str] = set()  # parts a statement names and cannot place
        # What a decoupling makes of itself: the place it gives each capacitor, by its
        # identity, with the statement that said it and the capacitor's pads to be near.
        self.origin: dict[int, Statement] = {}
        self.pad: dict[int, set[str]] = {}
        self._decouple(circuit, [s for s in statements if isinstance(s, Decouple)])
        self.free = tuple(p.ref for p in circuit.parts() if p.ref not in self.asks)
        self.poses: dict[str, Pose] = {}
        self.problems: dict[Problem, None] = {}
        self.chosen: dict[str, None] = {}
        self.turns: dict[Row, int] = {}  # the way round each row's parts are, this pass
        # Where each row beside a part has its parts' origins, this pass, or None.
        self.banks: dict[Row, dict[str, tuple[int, int]] | None] = {}

    def _decouple(self, circuit: Circuit, statements: list[Decouple]) -> None:
        """Give each capacitor that decouples a part one of the part's pins to be near:
        a pin on the supply the capacitor is across, each pin to one capacitor. A part
        has one such statement, so the order is the one it names them in."""
        grounds = {net.name for net in circuit.nets() if net.is_ground}

        def refuse(s: Decouple, cap: str, why: str) -> None:
            self.barred.add(cap)
            self.unordered.append(Problem((cap,), f"{s}: {why}", (s,)))

        for s in statements:
            part = circuit.part(s.part.ref)
            pins = sorted(self.nets[part.ref], key=natural)
            taken: dict[str, str] = {}  # the part's pin -> the capacitor by it
            for cap in s.caps:
                self.asks.setdefault(cap.ref, [])
                self.said.setdefault(cap.ref, []).append(s)
                on = sorted(set(self.nets[cap.ref].values()))
                across = " and ".join(on) or "nothing"
                supplies = [net for net in on if net not in grounds]
                if not grounds:
                    refuse(s, cap.ref, f"{cap.ref} is across {across}, and no net is said to be "
                           'ground: say which is, as in ground("GND")')  # fmt: skip
                elif len(supplies) == len(on):
                    refuse(s, cap.ref, f"{cap.ref} is across {across}, neither of them ground")
                elif len(supplies) != 1:
                    refuse(s, cap.ref, f"{cap.ref} is across {across}, not ground and one supply")
                elif supplies[0] not in self.nets[part.ref].values():
                    refuse(
                        s,
                        cap.ref,
                        f"{cap.ref} is across {across}, and {part.ref} is not on {supplies[0]}",
                    )
                elif off := [
                    n for n in on if n in grounds and n not in self.nets[part.ref].values()
                ]:
                    # A ground of some other part's: an analogue ground, say.
                    refuse(
                        s,
                        cap.ref,
                        f"{cap.ref} is across {across}, and {part.ref} is not on {off[0]}",
                    )
                else:
                    net = supplies[0]
                    there = [n for n in pins if self.nets[part.ref][n] == net]
                    pin = next((n for n in there if n not in taken), None)
                    if pin is None:
                        by = " and ".join(f"{taken[n]} is by {part.ref}.{n}" for n in there)
                        refuse(
                            s, cap.ref, f"{cap.ref} has no pin of {part.ref} on {net} left: {by}"
                        )
                        continue
                    taken[pin] = cap.ref
                    place = Place(circuit.part(cap.ref), near=part.pin(pin), within=s.within,
                                  source=s.source)  # fmt: skip
                    self.asks[cap.ref].append(place)
                    self.origin[id(place)] = s
                    # The capacitor's pad on the supply is the one by the pin.
                    self.pad[id(place)] = {n for n, its in self.nets[cap.ref].items() if its == net}

    def solution(self) -> Solution:
        order = self._order()
        # Which way round a part goes depends on where its neighbours are, so place
        # everything, then again until nothing moves.
        passes: list[tuple[dict, dict, dict, dict]] = []
        before: dict[str, Pose] = {}
        for _ in range(_PASSES):
            before, done = dict(self.poses), set()
            self.problems, self.chosen, self.turns, self.banks = {}, {}, {}, {}
            for ref in order:
                if (pose := self._place(ref, done)) is not None:
                    self.poses[ref] = pose
                    done.add(ref)
                else:
                    self.poses.pop(ref, None)
            if self.poses == before:
                break
            # A placement come round to one it has been at before goes round for good:
            # parts that turn or move for each other, each pass undoing the last. One
            # of those it goes round is kept: the one with the fewest problems, what
            # only shows once everything is placed among them, and the first of those.
            again = next((i for i, seen in enumerate(passes) if seen[0] == self.poses), None)
            if again is not None:
                round_ = passes[again:]

                def told(seen: tuple[dict, dict, dict, dict]) -> int:
                    self.poses, self.problems, self.chosen, self.turns = (dict(v) for v in seen)
                    self._check()
                    return len(self.problems)

                kept = min(round_, key=told)
                moved = sorted({ref for seen in round_ for ref in order
                                if seen[0].get(ref) != kept[0].get(ref)}, key=natural)  # fmt: skip
                self.poses, self.problems, self.chosen, self.turns = (dict(v) for v in kept)
                self._chose(f"{_listed(moved)}: each is placed by where the others are, and "
                            f"they go round {len(round_)} placements; kept as in the one with "
                            "the fewest problems, the first of them")  # fmt: skip
                break
            passes.append((dict(self.poses), self.problems, self.chosen, self.turns))
        else:
            moved = sorted((ref for ref in order if self.poses.get(ref) != before.get(ref)),
                           key=natural)  # fmt: skip
            self._problem(tuple(moved), f"the placement does not settle: {_listed(moved)} still "
                          f"moved on pass {_PASSES}, each placed by where the others are",
                          *(s for ref in moved for s in self.said[ref]))  # fmt: skip
        # A part against an edge with no inset that is in from it is there for its copper.
        for ref in sorted(self.poses if self.margin else (), key=natural):
            box = self._box(ref)
            for edge, s in self._edges(ref).items():
                held = {Edge.LEFT: box[0] - self.board[0], Edge.RIGHT: self.board[2] - box[2],
                        Edge.TOP: box[1] - self.board[1],
                        Edge.BOTTOM: self.board[3] - box[3]}[edge]  # fmt: skip
                if s.inset is None and held > 0:
                    self._chose(f"{ref}: {Length(held)} in from the {edge.value} edge, to "
                                f"keep its copper {Length(self.margin)} from it")  # fmt: skip
        if self.pads_apart or self.bodies_apart:
            notes = []
            for i, (what, name) in enumerate((("the pads of different parts", "pads_apart"),
                                              ("parts", "bodies_apart"))):  # fmt: skip
                word = next((s.assembly for s in self.rules if s.assembly), None)
                by = (f"{name}=" if any(getattr(s, name) is not None for s in self.rules)
                      else f'assembly="{word}"' if word else "not said")  # fmt: skip
                notes.append(
                    f"{what} {Length((self.pads_apart, self.bodies_apart)[i])} apart ({by})"
                )
            self._chose(f"the rules keep {' and '.join(notes)}")
        self._check()
        problems = sorted(self.problems, key=lambda p: ([natural(r) for r in p.parts], p.text))
        kept = tuple(Kept(s, (Length(box[0]), Length(box[1]), Length(box[2]), Length(box[3])),
                          False in faces, True in faces)
                     for s, box, faces in self._kept(self.poses))  # fmt: skip
        for s, thing in self.clears:
            if (box := self.things.get(thing)) is not None:
                x0, y0, x1, y1 = (Length(side) for side in box)
                kept += (Kept(s, (x0, y0, x1, y1), s.both_sides or not thing.back,
                              s.both_sides or thing.back),)  # fmt: skip
        return Solution(dict(sorted(self.poses.items(), key=lambda kv: natural(kv[0]))),
                        self.free, tuple(problems), tuple(self.chosen), kept)  # fmt: skip

    def _problem(self, parts: tuple[str, ...], text: str, *statements: Statement) -> None:
        said = tuple(dict.fromkeys(self.origin.get(id(s), s) for s in statements))
        self.problems.setdefault(Problem(parts, text, said))

    def _chose(self, text: str) -> None:
        self.chosen.setdefault(text)

    def _order(self) -> list[str]:
        """The parts that are placed, each after the parts it is placed by, and one
        that looks for a place near something after those whose place is given: it
        looks with them, and what they keep clear, already there."""
        needs = {ref: {p.ref for s in asks for p in s.mentions()} - {ref}
                 for ref, asks in self.asks.items()}  # fmt: skip
        looks = {ref: any(s.near is not None or s.after is not None or s.before is not None
                          for s in asks)
                 for ref, asks in self.asks.items()}  # fmt: skip
        # A row beside a part looks for its place as one thing, after that part, where
        # the lowest of its references comes among the parts that look for a place: its
        # parts follow one another, and what is placed by one of them waits for all.
        first: dict[str, str] = {}
        banks = [(row.beside.ref, {p.ref for p in row.parts})
                 for row in dict.fromkeys(r for rows in self.rows.values() for r in rows)
                 if row.beside is not None]  # fmt: skip
        for by, members in banks:
            for ref in members & set(needs):
                needs[ref].add(by)
                looks[ref] = True
                first.setdefault(ref, min(members, key=natural))
        # Once every row has said what it is beside, so that the order the rows were
        # said in does not matter: a row beside a part of another row waits for that row.
        for _, members in banks:
            for ref, by in needs.items():
                if ref not in members and by & members:
                    by |= members
        order: list[str] = []
        while ready := sorted((r for r in needs if r not in order and needs[r] <= set(order)),
                              key=lambda r: (looks[r], natural(first.get(r, r)),
                                             natural(r))):  # fmt: skip
            order.append(ready[0])
        stuck = sorted(set(needs) - set(order), key=natural)
        for ref in stuck:
            by = sorted(needs[ref] - set(order), key=natural)
            if unplaced := [r for r in by if r not in stuck]:
                text = f"{ref} is placed by {', '.join(unplaced)}, which nothing places"
            else:
                text = f"{ref} is placed by {', '.join(by)}, which is placed by it in turn"
            self.unordered.append(Problem((ref,), text, tuple(self.said[ref])))
        return order

    def _place(self, ref: str, done: set[str]) -> Pose | None:
        if ref in self.barred:
            return None
        asks, rows = self.asks[ref], self.rows.get(ref, [])
        shape = self.shapes[ref]
        back, rots = self._back(ref), self._rots(ref)
        edges = self._edges(ref)
        # A row beside a part finds its place whole, when the first of its parts is placed.
        banks = [row for row in rows if row.beside is not None]
        lost = any(self._bank(row, done) is None for row in banks)
        if rows and not lost and not any(s.facing for s in asks):
            rots = ((self._lie(ref, _lies(rows[0])) + self._turn_of(rows[0])) % 360,)
        nears = [s for s in asks if s.near is not None]
        betweens = [s for s in asks if s.between]
        if nears:
            if rows:
                self._problem((ref,), f"{ref}: near= is solved alone: one near=, and no "
                              "row() beside it", *self.said[ref])  # fmt: skip
                return None
            if any(s.centre for s in asks):
                self._problem((ref,), f"{ref}: near= is solved alone: one near=, and no "
                              "centre=True beside it", *asks)  # fmt: skip
                return None
            if len(nears) > 1 or edges or betweens:
                self._problem((ref,), f"{ref}: near= is solved alone: one near=, and no "
                              "against= or between= beside it", *asks)  # fmt: skip
                return None
            if any(s.at for s in asks):
                self._problem((ref,), f"{ref}: near= is solved alone: one near=, and no "
                              "at= or on= beside it", *asks)  # fmt: skip
                return None
            return self._near(ref, nears[0], rots, back, done)
        if lost:
            return None
        if banks and len(rows) > 1:
            self._problem((ref,), f"{ref} is in two rows: {' and '.join(map(str, rows))}", *rows)
            return None
        # Each way round is tried from what was said before any of them: what is said
        # of a way that is not taken is not said of the part, and a way with no place
        # is passed over where another has one.
        best, failed = None, None
        problems, chosen = self.problems, self.chosen
        for rot in rots:
            self.problems, self.chosen = dict(problems), dict(chosen)
            turned = _turned(shape, rot, back)
            at = self._fixed(ref, turned, edges, betweens, done)
            if at is None:
                failed = failed or (self.problems, self.chosen)
                continue
            key = (self._wires(ref, turned, *at), rot)
            if best is None or key < best[0]:
                best = (key, Pose(Length(at[0]), Length(at[1]), rot, back),
                        self.problems, self.chosen)  # fmt: skip
        if best is None:
            # With no way round that has a place, what the first way tried ran into,
            # and what was said on the way that is not of where this part went: a row
            # says how much of its edge is clear whether or not its parts fit there.
            assert failed is not None
            self.problems = failed[0]
            self.chosen = {note: None for note in failed[1]
                           if note in chosen or not note.startswith(f"{ref}:")}  # fmt: skip
            return None
        self.problems, self.chosen = best[2], best[3]
        if len(rots) > 1:
            ways = ", ".join(map(str, rots))
            self._chose(f"{ref}: turned {best[1].rot} degrees, of {ways}, for the "
                               "shortest connections")  # fmt: skip
        return best[1]

    def _back(self, ref: str) -> bool:
        return any(s.side is Side.BACK for s in self.asks[ref])

    def _edges(self, ref: str) -> dict[Edge, Place | Row]:
        """The edges *ref* is against, each with the statement that says so: its own
        place, or else a row along that edge."""
        edges: dict[Edge, Place | Row] = {s.along: s for s in self.rows.get(ref, [])
                                          if s.along is not None}  # fmt: skip
        return {**edges, **{s.against: s for s in self.asks[ref] if s.against}}

    def _turned(self, ref: str) -> dict[int, Place]:
        """The ways round *ref* is said to be, each with a statement that says it:
        ``facing=`` an edge, the top of its footprint to it, and a side of it named
        ``outward=`` to the edge it is against. More than one is a problem."""
        turns = {Edge.TOP: 0, Edge.LEFT: 90, Edge.BOTTOM: 180, Edge.RIGHT: 270}
        back, said = self._back(ref), {}
        for s in self.asks.get(ref, []):
            sides = [(Edge.TOP, s.facing)] if s.facing else []
            if s.outward is not None and s.against is not None:
                sides.append((Edge(self.circuit.part(ref).side(s.outward)), s.against))
            for side, to in sides:
                # On the back a footprint is mirrored top to bottom before it is turned.
                if back and side in (Edge.TOP, Edge.BOTTOM):
                    side = Edge.BOTTOM if side is Edge.TOP else Edge.TOP
                said.setdefault((turns[to] - turns[side]) % 360, s)
        if len(said) > 1:
            self._problem((ref,), f"{ref} is turned {len(said)} ways by what is said of it: "
                          + " and ".join(f"{rot} degrees" for rot in said),
                          *said.values())  # fmt: skip
        return said

    def _rots(self, ref: str) -> tuple[int, ...]:
        """The ways round *ref* may be. Whichever is taken, it is as long along an edge
        it lies against."""
        shape, edges = self.shapes[ref], self._edges(ref)
        if said := self._turned(ref):
            return (next(iter(said)),)
        # A part in a row lies along the row's edge, whatever other edge it is against.
        lie = [_lies(s) for s in self.rows.get(ref, [])] or list(edges)
        if len(lie) == 1 or ref in self.rows:
            w, h = shape.box[2] - shape.box[0], shape.box[3] - shape.box[1]
            upright = lie[0] in (Edge.LEFT, Edge.RIGHT)
            return _ROTATIONS if w == h else (90, 270) if (w > h) == upright else (0, 180)
        return _ROTATIONS

    def _lie(self, ref: str, along: Edge) -> int:
        """The way round *ref* lies along an edge with its length, as its footprint
        draws it, running the way a row runs: from the left, or from the top. A part
        drawn on end is a quarter turn from one drawn across, and one on the back is
        mirrored, so pin 1 of each is at the same end."""
        x0, y0, x1, y1 = self.shapes[ref].box
        length = (1, 0) if x1 - x0 >= y1 - y0 else (0, 1)
        runs = (1, 0) if along in (Edge.TOP, Edge.BOTTOM) else (0, 1)
        rots = self._rots(ref)
        return next((r for r in rots if _turn(*length, r, self._back(ref)) == runs), rots[0])

    def _turn_of(self, row: Row) -> int:
        """How far round the parts of *row* are turned from the way each lies along the
        edge, all of them the same, but for those facing an edge: the turn that brings
        their pads nearest what they connect to outside the row."""
        if row not in self.turns:
            members = {p.ref for p in row.parts}
            refs = [p.ref for p in row.parts if not any(s.facing for s in self.asks[p.ref])]
            lies = {ref: self._lie(ref, _lies(row)) for ref in refs}
            ways = [turn for turn in _ROTATIONS
                    if all((lies[r] + turn) % 360 in self._rots(r) for r in refs)]  # fmt: skip
            # What a turn that is not taken would run into is not a problem to report.
            told = dict(self.problems), dict(self.chosen)

            def cost(turn: int) -> tuple[int, int]:
                wires = 0
                if row.beside is not None:
                    # Where the row first looks, which is where it is with nothing in
                    # the way, at the least pitch this way round: the way round it is
                    # does not depend on the pitch said, so the least pitch it is told
                    # of when that is too small is one that does.
                    stood = self._stood(row, turn, False)[0]
                    (dx, dy), _ = self._out(row, stood)
                    for ref in refs:
                        turned, x, y = stood[ref]
                        wires += self._wires(ref, turned, x + dx, y + dy, but=members)
                    return wires, turn
                for ref in refs:
                    turned = _turned(self.shapes[ref], (lies[ref] + turn) % 360, self._back(ref))
                    betweens = [s for s in self.asks[ref] if s.between]
                    at = self._fixed(ref, turned, self._edges(ref), betweens, set())
                    if at is not None:
                        wires += self._wires(ref, turned, *at, but=members)
                return wires, turn

            self.turns[row] = turn = min(ways, key=cost)
            self.problems, self.chosen = told
            if len(ways) > 1 and len(set(lies.values())) == 1:
                lie = next(iter(lies.values()))
                of = ", ".join(map(str, sorted((lie + way) % 360 for way in ways)))
                self._chose(f"{row}: turned {(lie + turn) % 360} degrees, of {of}, for the "
                            "shortest connections")  # fmt: skip
            elif len(ways) > 1:
                of = ", ".join(map(str, ways))
                how = "lies along the edge" if row.beside is None else "stands across the row"
                self._chose(f"{row}: turned {turn} degrees from how each part {how}, of {of}, "
                            "for the shortest connections")  # fmt: skip
        return self.turns[row]

    def _stood(
        self, row: Row, turn: int, said: bool = True
    ) -> tuple[_Stood, int, tuple[str, str], tuple[int, int]]:
        """The parts of a row beside a part, the row turned *turn*, where they are with
        the row touching the part and level with it: each part's shape and its origin,
        at the pitch *said* if one is, or else at the least.
        With them the least pitch that keeps them clear of each other, the two parts
        that need it, and how far the row is across the board and down it."""
        assert row.beside is not None
        refs = [p.ref for p in row.parts]
        a = 1 if row.toward in (Edge.LEFT, Edge.RIGHT) else 0  # the way the row's line runs
        out = row.toward in (Edge.RIGHT, Edge.BOTTOM)
        shapes = []
        for ref in refs:
            faced = any(s.facing for s in self.asks[ref])
            rot = self._rots(ref)[0] if faced else (self._lie(ref, _lies(row)) + turn) % 360
            shapes.append(_turned(self.shapes[ref], rot, self._back(ref)))
        # Each part's origin from the line their near sides are on, and the middle of
        # its outline along the row.
        off = [-(t.box[1 - a] if out else t.box[3 - a]) for t in shapes]
        mids = [(t.box[a] + t.box[a + 2]) // 2 for t in shapes]
        least, pair = 0, (refs[0], refs[1])
        pitched = said and isinstance(row.pitch, Length)
        for i, j in combinations(range(len(refs)), 2):
            s, t = shapes[i], shapes[j]
            # A pitch that is said is the distance between its parts' outlines, and
            # one that is not keeps them as far apart as the rules keep parts.
            need = (s.box[a + 2] - mids[i]) - (t.box[a] - mids[j])
            need += 0 if pitched else self.bodies_apart
            for n, p in s.copper if self.gap or self.pads_apart else ():
                net = self.nets[refs[i]].get(n)
                for m, q in t.copper:
                    gap = self._kept_apart(net, self.nets[refs[j]].get(m))[0]
                    # Across the row the two pads are where they are, whatever the pitch.
                    across = max(p[1 - a] + off[i] - q[3 - a] - off[j],
                                 q[1 - a] + off[j] - p[3 - a] - off[i], 0)  # fmt: skip
                    if across < gap:
                        need = max(need, _apart(gap, across)
                                   + (p[a + 2] - mids[i]) - (q[a] - mids[j]))  # fmt: skip
            each = -(-need // (j - i))  # the parts between them are at the one pitch too
            if each > least:
                least, pair = each, (refs[i], refs[j])
        pitch = row.pitch.nm if said and isinstance(row.pitch, Length) else least
        along = [k * pitch - mid for k, mid in enumerate(mids)]
        lo = min(o + t.box[a] for o, t in zip(along, shapes, strict=True))
        hi = max(o + t.box[a + 2] for o, t in zip(along, shapes, strict=True))
        deep = max(t.box[3 - a] - t.box[1 - a] for t in shapes)
        by = self._box(row.beside.ref)
        line = by[3 - a] if out else by[1 - a]
        level = (by[a] + by[a + 2]) // 2 - (lo + hi) // 2
        stood = {ref: (t, o + level, f + line) if a == 0 else (t, f + line, o + level)
                 for ref, t, o, f in zip(refs, shapes, along, off, strict=True)}  # fmt: skip
        return stood, least, pair, ((hi - lo, deep) if a == 0 else (deep, hi - lo))

    def _out(self, row: Row, stood: _Stood) -> tuple[tuple[int, int], int]:
        """Where a row beside a part first looks, from touching the part: off it as far
        as the rules keep parts apart, and their pads. Across and down, and how far."""
        assert row.beside is not None
        a = 1 if row.toward in (Edge.LEFT, Edge.RIGHT) else 0
        by = row.beside.ref
        pose = self.poses[by]
        there = _turned(self.shapes[by], pose.rot, pose.back)
        far = 0
        kept = self.gap or self.pads_apart or self.bodies_apart
        for ref, (turned, x, y) in stood.items() if kept else ():
            if not (turned.through or there.through or self._back(ref) == pose.back):
                continue
            far = max(far, self.bodies_apart)
            for n, p in turned.copper:
                p, net = _moved(p, x, y), self.nets[ref].get(n)
                for m, q in there.copper:
                    gap = self._kept_apart(net, self.nets[by].get(m))[0]
                    q = _moved(q, pose.x.nm, pose.y.nm)
                    along = max(p[a] - q[a + 2], q[a] - p[a + 2], 0)
                    across = max(p[1 - a] - q[3 - a], q[1 - a] - p[3 - a], 0)
                    if along < gap:
                        far = max(far, _apart(gap, along) - across)
        way = far if row.toward in (Edge.RIGHT, Edge.BOTTOM) else -far
        return ((way, 0) if a == 1 else (0, way)), far

    def _bank(self, row: Row, done: set[str]) -> dict[str, tuple[int, int]] | None:
        """Where each part of a row beside a part has its origin, or None with the
        reason reported, once for the row: the nearest place to the part, on the side
        said, where every part of the row is clear."""
        if row in self.banks:
            return self.banks[row]
        assert row.beside is not None and row.toward is not None
        self.banks[row] = None
        refs, by = tuple(p.ref for p in row.parts), row.beside.ref
        if by not in self.poses:
            self._problem(refs, f"{_listed(list(refs))} are placed by {by}, which is not "
                          "placed", row)  # fmt: skip
            return None
        faces = {on: [ref for ref in refs if self._back(ref) == on] for on in (False, True)}
        if faces[False] and faces[True]:
            self._problem(refs, f"{row} is on one face of the board, and its parts are said "
                          f"to be on two: {_listed(faces[False])} on the front, "
                          f"{_listed(faces[True])} on the back",
                          row, *(s for ref in refs for s in self.asks[ref] if s.side))  # fmt: skip
            return None
        back = bool(faces[True])
        stood, least, pair, (wide, high) = self._stood(row, self._turn_of(row))
        if isinstance(row.pitch, Length) and row.pitch.nm < least:
            apart = max(self.gap, self.pads_apart)
            pads = f", their pads {Length(apart)} apart," if apart else ""
            self._problem(refs, f"{row} does not fit: {pair[0]} and {pair[1]} are clear of "
                          f"each other{pads} at a pitch of {Length(least)} or more",
                          row)  # fmt: skip
            return None
        (fx, fy), far = self._out(row, stood)
        a = 1 if row.toward in (Edge.LEFT, Edge.RIGHT) else 0
        sign = 1 if row.toward in (Edge.RIGHT, Edge.BOTTOM) else -1
        outs, alongs = _beyond(_FURTHER.nm, STEP.nm)
        # What each part may not overlap wherever the row is tried: what is fixed on
        # the board, the parts placed that share a face with it, and what they keep clear.
        # With each, how far off the rules keep a part's outline: an area kept clear
        # is only kept out of.
        named: dict[str, list[tuple[str, Box, int]]] = {}
        for ref, (turned, _, _) in stood.items():
            holed = turned.through
            named[ref] = [(f.label, taken, room) for f, taken, through in self.fixed
                          if (room := self._room(ref, f, holed or through or f.back == back))
                          is not None]  # fmt: skip
            named[ref] += [(other, self._box(other), self.bodies_apart) for other in done
                           if other in self.poses and other not in refs
                           and (holed or self.shapes[other].through
                                or self.poses[other].back == back)]  # fmt: skip
            named[ref] += [(f"{_area_of(s).part.ref}'s {_area_of(s).name} area", kept, 0)
                           for s, kept, on in self._kept(done) if holed or back in on]  # fmt: skip
        b0, b1, b2, b3 = self.board
        blocked: dict[str, int] = {}

        def roughly(start: int, count: bool) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
            """The places from *start* on, a few thousand, as across and down from where
            the row first looks, and whether every part's outline there is on the
            board's box, in its areas and over nothing it may not be over."""
            o, v = outs[start : start + _AT_A_TIME], alongs[start : start + _AT_A_TIME]
            dx, dy = (fx + sign * o, v) if a == 1 else (v, fy + sign * o)
            ok = np.ones(o.shape, dtype=bool)
            for ref, (turned, x, y) in stood.items():
                x0, y0, x1, y1 = (c + d for c, d in zip(_moved(turned.box, x, y),
                                                        (dx, dy, dx, dy), strict=True))  # fmt: skip
                on = (x0 >= b0) & (y0 >= b1) & (x1 <= b2) & (y1 <= b3)
                # Where the outline is drawn in from its box, an outline by one of the
                # pieces cut away is on the board only if its corners are.
                by_cut = np.zeros(o.shape, dtype=bool)
                for t0, t1, t2, t3 in self.cuts:
                    by_cut |= (x0 < t2) & (t0 < x1) & (y0 < t3) & (t1 < y1)
                at = np.flatnonzero(on & by_cut)
                if at.size:
                    xa, ya, xb, yb = x0[at], y0[at], x1[at], y1[at]
                    on[at] = (intersects_xy(self.roomy, xa, ya) & intersects_xy(self.roomy, xb, ya)
                              & intersects_xy(self.roomy, xa, yb)
                              & intersects_xy(self.roomy, xb, yb))  # fmt: skip
                room = np.ones(o.shape, dtype=bool)
                for _, (r0, r1, r2, r3), _ in self.areas.get(ref, []):
                    room &= (x0 >= r0) & (y0 >= r1) & (x1 <= r2) & (y1 <= r3)
                ok &= on & room
                if count:
                    blocked[_EDGE] = blocked.get(_EDGE, 0) + int((~on).sum())
                    blocked[_AREA] = blocked.get(_AREA, 0) + int((on & ~room).sum())
                for name, taken, room_by in named[ref]:
                    over = (_by(x0, y0, x1, y1, taken, room_by) if count
                            else _by(x0, y0, x1, y1, _surely(taken, room_by), 0))  # fmt: skip
                    ok &= ~over
                    if count:
                        blocked[name] = blocked.get(name, 0) + int((on & room & over).sum())
            return ok, dx, dy

        for start in range(0, len(outs), _AT_A_TIME):
            ok, dxs, dys = roughly(start, False)
            for i in np.flatnonzero(ok).tolist():
                dx, dy = int(dxs[i]), int(dys[i])
                if all(not self._outside(ref, _moved(turned.box, x + dx, y + dy))
                       and self._clear(ref, _moved(turned.box, x + dx, y + dy), back,
                                       turned.through, done, True, (turned, x + dx, y + dy))
                       for ref, (turned, x, y) in stood.items()):  # fmt: skip
                    off = far + int(outs[start + i])
                    along = int(alongs[start + i])
                    way = ("above" if along < 0 else "below") if a == 1 else (
                        "left of" if along < 0 else "right of")  # fmt: skip
                    self._chose(f"{row}: " + (f"{Length(off)} from" if off else "touching")
                                + f" {by}, " + (f"{Length(abs(along))} {way} " if along else "")
                                + "level with it")  # fmt: skip
                    self.banks[row] = {ref: (x + dx, y + dy) for ref, (_, x, y) in stood.items()}
                    return self.banks[row]
        for start in range(0, len(outs), _AT_A_TIME):
            roughly(start, True)
        most = sorted((name for name, n in blocked.items() if n),
                      key=lambda name: (-blocked[name], natural(name)))[:3]  # fmt: skip
        areas = list(dict.fromkeys(area for ref in refs for area, _, _ in self.areas.get(ref, [])))
        held = [s for ref in refs for _, _, said in self.areas.get(ref, []) for s in said]
        also = f", {', '.join(f'inside {area}' for area in areas)}," if areas else ""
        kept = any(turned.through or back in on for _, _, on in self._kept(done)
                   for turned, _, _ in stood.values())  # fmt: skip
        self._problem(refs, f"{row} has no place within {_FURTHER} of {by}{also} that is on "
                      f"the {'back' if back else 'front'} of the board and clear of the other "
                      f"parts{' and its holes' if self.fixed else ''}"
                      + (" and of what is kept clear" if kept else "")
                      + f": it is {Length(wide)} across the board and {Length(high)} down it"
                      + (f", with {_listed(most)} in the way" if most else ""),
                      row, *held)  # fmt: skip
        return None

    def _run(self, row: Row) -> tuple[int, int]:
        """The stretch of its edge that *row* spreads over: the longest that is clear,
        across the strip from the edge to the far side of the row's parts, of what is
        fixed on the board and of where the outline is cut back from the edge. The
        whole edge where nothing is."""
        if row not in self.runs:
            assert row.along is not None
            axis = 0 if row.along in (Edge.TOP, Edge.BOTTOM) else 1
            lo, hi = self.board[axis], self.board[axis + 2]
            backs = {self._back(p.ref) for p in row.parts}
            holed = any(self.shapes[p.ref].through for p in row.parts)
            deep = (row.inset.nm if row.inset else 0) + max(
                (t := _turned(self.shapes[p.ref], self._rots(p.ref)[0], self._back(p.ref)))
                .box[3 - axis] - t.box[1 - axis] for p in row.parts)  # fmt: skip
            x0, y0, x1, y1 = self.board
            strip = {
                Edge.TOP: (x0, y0, x1, y0 + deep),
                Edge.BOTTOM: (x0, y1 - deep, x1, y1),
                Edge.LEFT: (x0, y0, x0 + deep, y1),
                Edge.RIGHT: (x1 - deep, y0, x1, y1),
            }[row.along]
            taken: list[tuple[int, int]] = []
            if self.edge is not None:
                off = _area(*strip).difference(self.edge)
                for piece in getattr(off, "geoms", [off]):
                    if piece.area > 0:
                        taken.append((math.floor(piece.bounds[axis]),
                                      math.ceil(piece.bounds[axis + 2])))  # fmt: skip
            for f, box, through in self.fixed:
                if (through or holed or f.back in backs) and _overlap(box, strip):
                    taken.append((box[axis], box[axis + 2]))
            clear, at = [], lo
            for a, b in sorted(taken):
                if a > at:
                    clear.append((at, a))
                at = max(at, b)
            if hi > at:
                clear.append((at, hi))
            self.runs[row] = max(clear, key=lambda run: (run[1] - run[0], -run[0]),
                                 default=(lo, lo))  # fmt: skip
        return self.runs[row]

    def _in_row(self, ref: str, row: Row, turned: _Shape) -> int | None:
        """Where *ref*'s origin goes along the edge *row* is along, or None with the
        reason reported, when the row is longer than the edge."""
        assert row.along is not None
        axis = 0 if row.along in (Edge.TOP, Edge.BOTTOM) else 1
        whole = self.board[axis + 2] - self.board[axis]
        lo, hi = self._run(row)
        long = [(t := _turned(self.shapes[p.ref], self._rots(p.ref)[0], self._back(p.ref)))
                .box[axis + 2] - t.box[axis] for p in row.parts]  # fmt: skip
        i = [p.ref for p in row.parts].index(ref)
        refs = tuple(p.ref for p in row.parts)
        edge = f"the {row.along.value} edge"
        if hi - lo < whole:
            edge = f"what is clear of {edge}"
            self._chose(f"{row}: over the {Length(hi - lo)} of the {row.along.value} edge that "
                        f"is clear, of {Length(whole)}")  # fmt: skip
        if not isinstance(row.pitch, Length):
            if sum(long) > hi - lo:
                self._problem(refs, f"{row} does not fit: its parts are {Length(sum(long))} "
                              f"along {edge}, which is {Length(hi - lo)}", row)  # fmt: skip
                return None
            gap = (hi - lo - sum(long)) // (len(long) + 1)
            if gap < self.bodies_apart:
                self._problem(refs, f"{row} does not fit: its parts are {Length(sum(long))} "
                              f"along {edge}, which is {Length(hi - lo)}: that leaves "
                              f"{Length(gap)} between them, and the rules keep parts "
                              f"{Length(self.bodies_apart)} apart", row, *self.rules)  # fmt: skip
                return None
            return lo + gap * (i + 1) + sum(long[:i]) - turned.box[axis]
        middles = [(lo + hi) // 2 + (2 * j - (len(long) - 1)) * row.pitch.nm // 2
                   for j in range(len(long))]  # fmt: skip
        # How far each outline reaches past an end of the edge. The row is about the
        # edge's middle by its parts' middles, so a long part at one end reaches furthest.
        past = [max(lo - (m - n // 2), m + (n + 1) // 2 - hi)
                for m, n in zip(middles, long, strict=True)]  # fmt: skip
        if max(past) > 0:
            worst = past.index(max(past))
            self._problem(refs, f"{row} does not fit: at that pitch {refs[worst]} reaches "
                          f"{Length(max(past))} past the end of {edge}", row)  # fmt: skip
            return None
        return middles[i] - (turned.box[axis] + turned.box[axis + 2]) // 2

    def _fixed(self, ref: str, turned: _Shape, edges: Mapping[Edge, Place | Row],
               betweens: list[Place], done: set[str]) -> tuple[int, int] | None:  # fmt: skip
        """Where the origin goes when edges, rows and neighbours fix it, or None with
        the reason reported."""
        x0, y0, x1, y1 = self.board
        bx0, by0, bx1, by1 = turned.box
        px = [p[1] for p in turned.pads] or [bx0, bx1]
        py = [p[2] for p in turned.pads] or [by0, by1]
        xs: list[tuple[int, Statement]] = []
        ys: list[tuple[int, Statement]] = []
        edged = {"across": [e for e in edges if e in (Edge.LEFT, Edge.RIGHT)],
                 "along": [e for e in edges if e in (Edge.TOP, Edge.BOTTOM)]}  # fmt: skip
        for row in self.rows.get(ref, []):
            if row.beside is not None:
                # Where the row found its place, this way round, both ways.
                if (bank := self.banks.get(row)) is None:
                    return None
                xs.append((bank[ref][0], row))
                ys.append((bank[ref][1], row))
                continue
            if (at := self._in_row(ref, row, turned)) is None:
                return None
            (xs if row.along in (Edge.TOP, Edge.BOTTOM) else ys).append((at, row))
        for s in self.asks[ref]:
            if s.centre:
                xs.append(((x0 + x1) // 2 - (bx0 + bx1) // 2, s))
                ys.append(((y0 + y1) // 2 - (by0 + by1) // 2, s))
            if s.at is not None:
                # A point of the board, from the top left of the box around it, or of
                # a thing fixed on it, turned as the thing is; and what of the part is
                # there: its origin, or the pin said, where this way round has it.
                ax, ay = (v.nm for v in s.at)
                if s.on is None:
                    ax, ay = x0 + ax, y0 + ay
                elif s.on in self.things:
                    tx, ty = _swung(ax, ay, s.on.rot, s.on.back)
                    ax, ay = s.on.x.nm + tx, s.on.y.nm + ty
                else:
                    self._problem((ref,), f"{ref} is placed on {s.on}, which is not fixed "
                                  "on the board", s)  # fmt: skip
                    return None
                ox, oy = 0, 0
                if s.of is not None:
                    pad = next(((x, y) for n, x, y in turned.pads if n == s.of.number), None)
                    if pad is None:
                        self._problem((ref,), f"{s.of} is to be at a point, and {ref}'s "
                                      f"footprint {self.circuit.part(ref).footprint!r} has "
                                      f"no pad {s.of.number}", s)  # fmt: skip
                        return None
                    ox, oy = pad
                xs.append((ax - ox, s))
                ys.append((ay - oy, s))
        # With no inset, against the edge: its outline on the edge, or as near as the
        # rules let its copper be, whichever is further in.
        cx0, cy0, cx1, cy1 = (
            (min(c[1][0] for c in turned.copper) - self.margin,
             min(c[1][1] for c in turned.copper) - self.margin,
             max(c[1][2] for c in turned.copper) + self.margin,
             max(c[1][3] for c in turned.copper) + self.margin)
            if turned.copper else turned.box
        )  # fmt: skip
        for edge, s in edges.items():
            d = None if s.inset is None else s.inset.nm
            if edge is Edge.LEFT:
                xs.append((x0 - min(bx0, cx0) if d is None else x0 + d - min(px), s))
            elif edge is Edge.RIGHT:
                xs.append((x1 - max(bx1, cx1) if d is None else x1 - d - max(px), s))
            elif edge is Edge.TOP:
                ys.append((y0 - min(by0, cy0) if d is None else y0 + d - min(py), s))
            else:
                ys.append((y1 - max(by1, cy1) if d is None else y1 - d - max(py), s))
        # Where along its edge, where that is said: the middle of the part's outline a
        # share of the edge, or a distance, from the edge's top end or its left end.
        for s in self.asks[ref]:
            if s.along is None:
                continue
            down = s.against in (Edge.LEFT, Edge.RIGHT)
            lo, hi = (y0, y1) if down else (x0, x1)
            d = s.along.nm if isinstance(s.along, Length) else round(s.along * (hi - lo))
            if down:
                ys.append((lo + d - (by0 + by1) // 2, s))
            else:
                xs.append((lo + d - (bx0 + bx1) // 2, s))
        # An edge says how far from it, and between= the place along it; edges that
        # make a corner leave between= nothing to say, so it is held to both.
        across, along = not xs or bool(ys), not ys or bool(xs)
        for s in betweens:
            assert s.between is not None
            if missing := [p.ref for p in s.between if p.ref not in self.poses]:
                self._problem((ref,), f"{ref} is placed by {', '.join(missing)}, which is "
                              "not placed", s)  # fmt: skip
                return None
            (ax, ay), (bx, by) = (self._centre(p.ref) for p in s.between)
            if across:
                xs.append(((ax + bx) // 2 - (bx0 + bx1) // 2, s))
            if along:
                ys.append(((ay + by) // 2 - (by0 + by1) // 2, s))
        at = []
        for axis, fixes, lo, hi, b0, b1 in (("across", xs, x0, x1, bx0, bx1),
                                            ("along", ys, y0, y1, by0, by1)):  # fmt: skip
            values = sorted({v for v, _ in fixes})
            if len(values) > 1 and values[-1] - values[0] > 1:
                apart = Length(values[-1] - values[0])
                self._problem((ref,), f"{ref} is put in two places {apart} apart {axis} the "
                              "board", *(s for _, s in fixes))  # fmt: skip
                return None
            beside = [s for s in self.asks[ref] if (s.after or s.before)
                      and (s.against in (Edge.TOP, Edge.BOTTOM)) == (axis == "across")]  # fmt: skip
            if beside:
                # Looked for along the edge with the other way settled, which the edge
                # says; and where something else says where along it, held to that.
                found = self._beside(ref, turned, beside, axis == "across", done,
                                     at[0] if at else min(v for v, _ in ys),
                                     values[0] if values else None)  # fmt: skip
                if found is None:
                    return None
                values = [found]
            if not values:
                other = edged["along" if axis == "across" else "across"]
                if not other:
                    self._problem((ref,), f"{ref} is not placed {axis} the board: nothing "
                                  "says where", *self.said[ref])  # fmt: skip
                    return None
                self._chose(f"{ref}: centred along the {other[0].value} edge")
                values = [(lo + hi) // 2 - (b0 + b1) // 2]
            at.append(values[0])
        return at[0], at[1]

    def _beside(self, ref: str, turned: _Shape, said: list[Place], level: bool,
                done: set[str], other: int, held: int | None) -> int | None:  # fmt: skip
        """Where along the edge it is against a part said to be ``after=`` or
        ``before=`` others goes: past each one's outline along the edge, on the side
        said, as near them as the part is clear of what is placed. *said* is every
        statement that says so; *level* for an edge that runs across the board, top or
        bottom; *other* is where the part is the other way, which its edge says. *held*
        is where along the edge something else puts it, a second edge or a row: it is
        then there, and after and before as said or a problem."""
        beside = [(word, p) for s in said for word, p in (("after", s.after), ("before", s.before))
                  if p is not None]  # fmt: skip
        missing = list(dict.fromkeys(p.ref for _, p in beside if p.ref not in self.poses))
        if missing:
            self._problem((ref,), f"{ref} is placed by {', '.join(missing)}, which is not "
                          "placed", *said)  # fmt: skip
            return None
        b, back = turned.box, self._back(ref)
        lo, hi = (self.board[0], self.board[2]) if level else (self.board[1], self.board[3])
        b0, b1 = (b[0], b[2]) if level else (b[1], b[3])
        first, last = lo - b0, hi - b1  # the origin with the outline at each end of the edge
        for word, p in beside:
            o = self._box(p.ref)
            if word == "after":
                first = max(first, (o[2] if level else o[3]) - b0)
            else:
                last = min(last, (o[0] if level else o[1]) - b1)
        words = " and ".join(f"{word} {p.ref}" for word, p in beside)
        edge = said[0].against
        assert edge is not None
        if held is not None:
            if first <= held <= last:
                return held
            self._problem((ref,), f"{ref} is not {words} along the {edge.value} edge where "
                          "it is put", *self.said[ref])  # fmt: skip
            return None
        # From what it is after, or back from what it is before: a step at a time, and
        # hard against the far side of each thing in the way, which a step may not land on.
        forward = any(word == "after" for word, _ in beside)
        ends = [box for f, box, _ in self.fixed]
        ends += [self._box(r) for r in done if r != ref and r in self.poses]
        # And as far off each of those as the rules keep parts apart.
        room = self.bodies_apart
        ends += [(o[0] - room, o[1] - room, o[2] + room, o[3] + room) for o in ends if room]
        # And as far off each thing as an ``apart`` keeps this part from it.
        ends += [
            (o[0] - far, o[1] - far, o[2] + far, o[3] + far)
            for f, (far, _) in self.aparts.get(ref, {}).items()
            for o in [self.things[f]]
        ]
        ends += [box for _, box, _ in self._kept(done)]
        tries = {(o[2] if level else o[3]) - b0 if forward else (o[0] if level else o[1]) - b1
                 for o in ends}  # fmt: skip
        tries |= set(range(first, last + 1, STEP.nm) if forward
                     else range(last, first - 1, -STEP.nm))  # fmt: skip
        for v in sorted((v for v in tries if first <= v <= last), reverse=not forward):
            x, y = (v, other) if level else (other, v)
            if not self._outside(ref, _moved(b, x, y)) and self._clear(
                ref, _moved(b, x, y), back, turned.through, done, True, (turned, x, y)
            ):
                self._chose(f"{ref}: {words} along the {edge.value} edge")
                return v
        self._problem((ref,), f"{ref} has no place against the {edge.value} edge {words} "
                      "that is on the board and clear of the other parts", *said)  # fmt: skip
        return None

    def _outside(self, ref: str, box: Box) -> list[tuple[Region, tuple[Inside, ...], int, str]]:
        """Each area *ref* is said to be inside that *box* is not wholly in: the area,
        the statements that say so, how far past it reaches, and past which side."""
        out = []
        for area, (x0, y0, x1, y1), said in self.areas.get(ref, []):
            past = (x0 - box[0], y0 - box[1], box[2] - x1, box[3] - y1)
            if max(past) > 0:
                side = ("left", "top", "right", "bottom")[past.index(max(past))]
                out.append((area, said, max(past), side))
        return out

    def _centre(self, ref: str) -> tuple[int, int]:
        x0, y0, x1, y1 = self._box(ref)
        return (x0 + x1) // 2, (y0 + y1) // 2

    def _box(self, ref: str) -> Box:
        pose = self.poses[ref]
        # Asked of every placed part for every place a part might go: kept for as long
        # as the part is where it was.
        if (kept := self._boxes.get(ref)) is not None and kept[0] is pose:
            return kept[1]
        box = _moved(_turned(self.shapes[ref], pose.rot, pose.back).box, pose.x.nm, pose.y.nm)
        self._boxes[ref] = (pose, box)
        return box

    def _pads(self, ref: str) -> list[tuple[str, int, int]]:
        pose = self.poses[ref]
        turned = _turned(self.shapes[ref], pose.rot, pose.back)
        return [(n, x + pose.x.nm, y + pose.y.nm) for n, x, y in turned.pads]

    def _wires(self, ref: str, turned: _Shape, x: int, y: int,
               but: Iterable[str] = ()) -> int:  # fmt: skip
        """How far this part's pads would be from the nearest pad on their net, summed,
        leaving out the pads of the parts *but*."""
        on: dict[str, list[tuple[int, int]]] = {}
        for other in self.poses:
            if other != ref and other not in but:
                for number, px, py in self._pads(other):
                    if (net := self.nets[other].get(number)) is not None:
                        on.setdefault(net, []).append((px, py))
        total = 0
        for number, px, py in turned.pads:
            if (net := self.nets[ref].get(number)) in on:
                total += min(abs(px + x - ox) + abs(py + y - oy) for ox, oy in on[net])
        return total

    def _kept(self, of: Iterable[str]) -> Iterator[tuple[Keepout, Box, set[bool]]]:
        """Each area kept clear whose part is one *of* those placed: where it is on the
        board, and the faces it is on (the back is True)."""
        of = set(of)
        for s, (x0, y0, x1, y1) in self.keeps:
            ref = _area_of(s).part.ref
            if ref in of:
                pose = self.poses[ref]
                (ax, ay), (bx, by) = (_turn(x, y, pose.rot, pose.back)
                                      for x, y in ((x0, y0), (x1, y1)))  # fmt: skip
                box = (min(ax, bx), min(ay, by), max(ax, bx), max(ay, by))
                faces = {False, True} if s.both_sides else {pose.back}
                yield s, _moved(box, pose.x.nm, pose.y.nm), faces

    def _on(self, box: Box) -> bool:
        """Whether *box* is inside the board's outline; touching it is inside."""
        if not (self.board[0] <= box[0] and self.board[1] <= box[1]
                and box[2] <= self.board[2] and box[3] <= self.board[3]):  # fmt: skip
            return False
        if self.edge is None or not any(_overlap(box, cut) for cut in self.cuts):
            return True
        return self.within.covers(_area(*box))

    def _shy(self, turned: _Shape, x: int, y: int) -> tuple[int, str] | None:
        """The pad of a part, turned and put there, that is nearer the board's edge than
        the rules keep copper from it: how near, and which, the nearest."""
        m = self.margin
        if not m:
            return None
        box = _moved(turned.box, x, y)
        if self._on((box[0] - m, box[1] - m, box[2] + m, box[3] + m)):
            return None
        worst: tuple[int, str] | None = None
        for n, pad in turned.copper:
            pad = _moved(pad, x, y)
            if self._on((pad[0] - m, pad[1] - m, pad[2] + m, pad[3] + m)):
                continue
            if self.edge is None:
                d = min(pad[0] - self.board[0], pad[1] - self.board[1],
                        self.board[2] - pad[2], self.board[3] - pad[3])  # fmt: skip
            else:
                # By a slanted or rounded edge the box grown by the margin reaches
                # outside before the pad is that near: the distance itself says.
                d = round(self.edge.boundary.distance(_area(*pad)))
                d = d if self.within.covers(_area(*pad)) else 0
                if d >= m:
                    continue
            d = max(d, 0)
            if worst is None or (d, natural(n)) < (worst[0], natural(worst[1])):
                worst = (d, n)
        return worst

    def _over(self, box: Box, back: bool, through: bool, ref: str = "") -> Fixed | None:
        """What is fixed on the board that *box*, on that face, overlaps: the first,
        leaving out what *ref* is said to be on."""
        on = {s.on for s in self.asks.get(ref, [])}
        for f, taken, holed in self.fixed:
            if (through or holed or f.back == back) and _overlap(box, taken) and f not in on:
                return f
        return None

    def _room(self, ref: str, thing: Fixed, shares: bool) -> int | None:
        """How far off *thing* the outline of *ref* is kept, which *shares* a face with
        it or does not: as far as the rules keep parts apart, between those that share
        a face, or as far as an ``apart`` keeps the two, whichever face either is on,
        the larger. None where they share no face and nothing keeps them apart: the
        thing is then nothing to the part."""
        far = self.aparts.get(ref, {}).get(thing, (0, ()))[0]
        if shares:
            return max(self.bodies_apart, far)
        return far or None

    def _close(self, box: Box, back: bool, through: bool,
               ref: str = "") -> list[tuple[Fixed, int, int, tuple[Apart, ...]]]:  # fmt: skip
        """What is fixed on the board that *box*, on that face, is not over and is
        nearer than it is kept: by the rules, which keep parts apart that share a face,
        or by an ``apart`` that speaks of *ref* and the thing, whichever face either
        is on. Each with how near, how far it is kept, the larger of the two, and the
        ``apart`` statements that keep it so, none where it is the rules. What *ref*
        is said to be on is left out."""
        aparts = self.aparts.get(ref, {})
        if not self.bodies_apart and not aparts:
            return []
        on = {s.on for s in self.asks.get(ref, [])}
        found = []
        for f, taken, holed in self.fixed:
            shares = through or holed or f.back == back
            far, said = aparts.get(f, (0, ()))
            if f in on or not (shares or far) or (shares and _overlap(box, taken)):
                continue  # on a face of its own, or over it, which is told as that
            if shares and self.bodies_apart >= far:
                far, said = self.bodies_apart, ()
            if far and (d := _off(box, taken)) < far:
                found.append((f, d, far, said))
        return found

    def _pitched(self, a: str, b: str) -> bool:
        """Whether the two parts are in one row whose pitch is said: how far apart
        their outlines are is then what the board file said."""
        return any(isinstance(row.pitch, Length) and any(p.ref == b for p in row.parts)
                   for row in self.rows.get(a, ()))  # fmt: skip

    def _kept_apart(self, one: str | None, two: str | None) -> tuple[int, str]:
        """How far apart the rules keep two pads of different parts, by the nets they
        are on, and what it is they keep that far apart: copper on different nets, or
        the pads of different parts where that is more."""
        gap = 0 if one is not None and one == two else self.gap
        if gap >= self.pads_apart:
            return gap, "copper"
        return self.pads_apart, "the pads of different parts"

    def _tight(self, ref: str, turned: _Shape, x: int, y: int,
               other: str) -> tuple[int, str, str, int, str] | None:  # fmt: skip
        """The pad of this part, turned and put there, and the pad of *other* that are
        closer than the rules keep them, as copper on different nets or as the pads of
        different parts: how far apart, which two, the nearest pair, and how far the
        rules keep what."""
        box, theirs = _moved(turned.box, x, y), self._box(other)
        reach = max(self.gap, self.pads_apart)
        if not reach or not _overlap(
            (box[0] - reach, box[1] - reach, box[2] + reach, box[3] + reach), theirs
        ):
            return None
        pose = self.poses[other]
        there = _turned(self.shapes[other], pose.rot, pose.back)
        worst: tuple[int, str, str, int, str] | None = None
        for n, a in turned.copper:
            a, net = _moved(a, x, y), self.nets[ref].get(n)
            for m, b in there.copper:
                gap, what = self._kept_apart(net, self.nets[other].get(m))
                if not gap:
                    continue
                d = _off(a, _moved(b, pose.x.nm, pose.y.nm))
                if d < gap and (worst is None or (d, natural(n), natural(m)) <
                                (worst[0], natural(worst[1]), natural(worst[2]))):  # fmt: skip
                    worst = (d, n, m, gap, what)
        return worst

    def _clear(self, ref: str, box: Box, back: bool, through: bool, of: Iterable[str],
               keeps: bool = True, at: tuple[_Shape, int, int] | None = None) -> bool:  # fmt: skip
        """Inside the board, over nothing fixed on it but what the part is on,
        overlapping none *of* the parts placed and, with *keeps*, in no area of theirs
        that is kept clear, and as far from each of those parts and things as the rules
        keep parts apart. With *at*, the part's shape and where it is, its pads are as
        far from theirs as the rules say as well."""
        if not self._on(box) or self._over(box, back, through, ref) is not None:
            return False
        if self._close(box, back, through, ref):
            return False
        if at is not None and self._shy(*at) is not None:
            return False
        for _, kept, faces in self._kept(of if keeps else ()):
            if (through or back in faces) and _overlap(box, kept):
                return False
        for other in of:
            if other == ref or other not in self.poses:
                continue
            shares = through or self.shapes[other].through or self.poses[other].back == back
            if shares and _overlap(box, self._box(other)):
                return False
            if (shares and self.bodies_apart and _off(box, self._box(other)) < self.bodies_apart
                    and not self._pitched(ref, other)):  # fmt: skip
                return False
            if shares and at is not None and self._tight(ref, *at, other) is not None:
                return False
        return True

    def _near(self, ref: str, s: Place, rots: tuple[int, ...], back: bool,
              done: set[str]) -> Pose | None:  # fmt: skip
        assert s.near is not None and s.within is not None
        target = s.near.part.ref if isinstance(s.near, Pin) else s.near.ref
        if target not in self.poses:
            self._problem((ref,), f"{ref} is placed by {target}, which is not placed", s)
            return None
        targets = [(x, y) for n, x, y in self._pads(target)
                   if not isinstance(s.near, Pin) or n == s.near.number]  # fmt: skip
        shape, limit, step = self.shapes[ref], s.within.nm, STEP.nm
        of = self._box(target)
        only = self.pad.get(id(s))  # the pads of this part that are to be near, if not any
        least = 0 if s.at_least is None else s.at_least.nm
        rooms = [box for _, box, _ in self.areas.get(ref, [])]

        def apart(turned: _Shape, x: int, y: int) -> bool:
            """No pad that is to be near nearer what it is near than the least said."""
            return all((px + x - tx) ** 2 + (py + y - ty) ** 2 >= least * least
                       for number, px, py in turned.pads if only is None or number in only
                       for tx, ty in targets)  # fmt: skip

        def beyond(box: Box) -> bool:
            """On the side of what it is near that the statement says, where it says."""
            if s.toward is None:
                return True
            return {Edge.TOP: box[3] <= of[1], Edge.BOTTOM: box[1] >= of[3],
                    Edge.LEFT: box[2] <= of[0], Edge.RIGHT: box[0] >= of[2]}[s.toward]  # fmt: skip

        within = _offsets(limit, step)

        # Each way the part may be turned, with each of its pads by each pad it is near.
        ways = [(rot, turned, px, py, tx, ty)
                for rot in rots for turned in [_turned(shape, rot, back)]
                for number, px, py in turned.pads if only is None or number in only
                for tx, ty in targets]  # fmt: skip
        through = shape.through
        # What a box may not overlap wherever it is tried: what is fixed on the board,
        # and the parts placed that share a face with this one.
        # With each, how far off it the part's outline is kept.
        named = [(f.label, taken, room) for f, taken, holed in self.fixed
                 if (room := self._room(ref, f, through or holed or f.back == back))
                 is not None]  # fmt: skip
        named += [(other, self._box(other), self.bodies_apart) for other in done
                  if other != ref and other in self.poses
                  and (through or self.shapes[other].through
                       or self.poses[other].back == back)]  # fmt: skip
        b0, b1, b2, b3 = self.board

        # Where each way puts the part's box, before the offset is added.
        wx = np.array([tx - px for _, _, px, _, tx, _ in ways], dtype=np.int64)[:, None]
        wy = np.array([ty - py for _, _, _, py, _, ty in ways], dtype=np.int64)[:, None]
        boxes = np.array([turned.box for _, turned, *_ in ways], dtype=np.int64).reshape(-1, 4)
        wx0, wy0 = wx + boxes[:, 0:1], wy + boxes[:, 1:2]
        wx1, wy1 = wx + boxes[:, 2:3], wy + boxes[:, 3:4]

        def boxes_at(grid: _Grid, a: int, b: int) -> tuple[np.ndarray, ...]:
            """The part's box each way, at each of *grid*'s offsets from *a* to *b*."""
            _, dxs, dys = grid
            return (wx0 + dxs[a:b], wy0 + dys[a:b], wx1 + dxs[a:b], wy1 + dys[a:b])

        def on_board(x0: np.ndarray, y0: np.ndarray, x1: np.ndarray, y1: np.ndarray) -> np.ndarray:
            return (x0 >= b0) & (y0 >= b1) & (x1 <= b2) & (y1 <= b3)

        def in_area(x0: np.ndarray, y0: np.ndarray, x1: np.ndarray, y1: np.ndarray) -> np.ndarray:
            """Inside every area of the board the part is said to be inside."""
            ok = np.ones(x0.shape, dtype=bool)
            for r0, r1, r2, r3 in rooms:
                ok &= (x0 >= r0) & (y0 >= r1) & (x1 <= r2) & (y1 <= r3)
            return ok

        def on_side(x0: np.ndarray, y0: np.ndarray, x1: np.ndarray, y1: np.ndarray) -> np.ndarray:
            """On the side of what it is near that the statement says, as ``beyond``."""
            if s.toward is None:
                return np.ones(x0.shape, dtype=bool)
            return {Edge.TOP: y1 <= of[1], Edge.BOTTOM: y0 >= of[3],
                    Edge.LEFT: x1 <= of[0], Edge.RIGHT: x0 >= of[2]}[s.toward]  # fmt: skip

        def roughly(keeps: bool, grid: _Grid, a: int, b: int) -> np.ndarray:
            """For each way and each of *grid*'s offsets from *a* to *b*, whether the
            part's box there is on the board's box, on the side said, and over nothing
            it may not be over: every place that is clear is one of these, and they are
            found all at once."""
            # An area kept clear is kept out of; a part or a thing is kept as far off
            # as the rules keep parts apart or an ``apart`` keeps the two, and here as
            # far as is surely too near.
            out = [_surely(box, room) for _, box, room in named]
            if keeps:
                out += [kept for _, kept, faces in self._kept(done) if through or back in faces]
            x0, y0, x1, y1 = boxes_at(grid, a, b)
            if not _SIFT:
                return np.ones(x0.shape, dtype=bool)
            ok = on_board(x0, y0, x1, y1) & on_side(x0, y0, x1, y1) & in_area(x0, y0, x1, y1)
            if least:  # nearer than the least said, by the pad this way puts near
                _, dxs, dys = grid
                ok &= (dxs[a:b] * dxs[a:b] + dys[a:b] * dys[a:b]) >= least * least
            for taken in out:
                ok &= ~_by(x0, y0, x1, y1, taken, 0)
            # Where the outline is drawn in from its box, a box by one of the pieces cut
            # away is on the board only if its corners are.
            by_cut = np.zeros(ok.shape, dtype=bool)
            for t0, t1, t2, t3 in self.cuts:
                by_cut |= (x0 < t2) & (t0 < x1) & (y0 < t3) & (t1 < y1)
            at = np.nonzero(ok & by_cut)
            if at[0].size:
                xa, ya, xb, yb = (np.broadcast_to(v, ok.shape)[at] for v in (x0, y0, x1, y1))
                on = intersects_xy(self.roomy, xa, ya) & intersects_xy(self.roomy, xb, ya)
                ok[at] = on & intersects_xy(self.roomy, xa, yb) & intersects_xy(self.roomy, xb, yb)
            return ok

        def nearest(keeps: bool, grid: _Grid = within) -> tuple[Pose | None, int]:
            best, found = None, -1
            offsets = grid[0]
            # The offsets are nearest first: a few thousand at a time, until one of them
            # is a place and none further off is as near.
            for a in range(0, len(offsets) if ways else 0, _AT_A_TIME):
                if best is not None and offsets[a][0] > found:
                    break
                rough = roughly(keeps, grid, a, a + _AT_A_TIME)
                for i in np.flatnonzero(rough.any(axis=0)).tolist():
                    d2, dy, dx = offsets[a + i]
                    if best is not None and d2 > found:
                        break
                    for w in np.flatnonzero(rough[:, i]).tolist():
                        rot, turned, px, py, tx, ty = ways[w]
                        x, y = tx + dx - px, ty + dy - py
                        at = (turned, x, y)
                        if least and (d2 < least * least or not apart(*at)):
                            continue
                        if rooms and self._outside(ref, _moved(turned.box, x, y)):
                            continue
                        if not (beyond(_moved(turned.box, x, y))
                                and self._clear(ref, _moved(turned.box, x, y), back, through,
                                                done, keeps, at)):  # fmt: skip
                            continue
                        key = (self._wires(ref, turned, x, y), rot, y, x)
                        if best is None or key < best[0]:
                            best, found = (key, Pose(Length(x), Length(y), rot, back)), d2
            return (None if best is None else best[1]), found

        pose, found = nearest(True)
        if pose is None:
            # What is kept clear is named only when it is what leaves the part no place.
            kept = [k for k, _, faces in self._kept(done) if shape.through or back in faces]
            if kept and nearest(False)[0] is None:
                kept = []
            holes = " and its holes" if self.fixed else ""
            # How far off the nearest place is, looking three times as far and no less
            # than 10 mm nor more than 30, and what is most in the way within the
            # distance said.
            reach = max(limit, min(max(3 * limit, _FURTHER.nm // 3), _FURTHER.nm))
            looked = reach > limit and bool(ways)  # further than was said, for a place
            further = nearest(True, _offsets(reach, step))[1] if looked else -1
            # To the next step up, so that the distance given is one that would do.
            off = math.isqrt(max(further, 0)) // step * step
            off += step if off * off < further else 0
            where = (f": the nearest is {Length(off)} from it" if further >= 0
                     else f": there is none within {Length(reach)} either" if looked
                     else "")  # fmt: skip
            blocked: dict[str, int] = {}
            for a in range(0, len(within[0]) if ways else 0, _AT_A_TIME):
                x0, y0, x1, y1 = boxes_at(within, a, a + _AT_A_TIME)
                side = on_side(x0, y0, x1, y1)
                on = on_board(x0, y0, x1, y1)
                blocked[_EDGE] = blocked.get(_EDGE, 0) + int((side & ~on).sum())
                room = in_area(x0, y0, x1, y1)
                blocked[_AREA] = blocked.get(_AREA, 0) + int((side & on & ~room).sum())
                for name, taken, kept_off in named:
                    over = side & on & room & _by(x0, y0, x1, y1, taken, kept_off)
                    blocked[name] = blocked.get(name, 0) + int(over.sum())
            most = sorted((name for name, n in blocked.items() if n),
                          key=lambda name: (-blocked[name], natural(name)))[:3]  # fmt: skip
            way = (
                ""
                if not most
                else (
                    (", with " if where else ": with ")
                    + (most[0] if len(most) == 1 else ", ".join(most[:-1]) + " and " + most[-1])
                    + " in the way"
                )
            )
            held = [a for _, _, said in self.areas.get(ref, []) for a in said]
            more = [f"at least {s.at_least} from it"] if s.at_least is not None else []
            more += [f"toward the {s.toward.value} edge"] if s.toward is not None else []
            more += [f"inside {area}" for area, _, _ in self.areas.get(ref, [])]
            also = f", {', '.join(more)}," if more else ""
            self._problem((ref,), f"{ref} has no place within {s.within} of {s.near}{also} "
                          f"that is on the {'back' if back else 'front'} of the board and "
                          f"clear of the other parts{holes}"
                          + (" and of what is kept clear" if kept else "")
                          + f"{where}{way}",
                          s, *held, *kept)  # fmt: skip
            return None
        self._chose(f"{ref}: {Length(math.isqrt(found))} from {s.near}, turned "
                           f"{pose.rot} degrees")  # fmt: skip
        return pose

    def _check(self) -> None:
        """What only shows once everything is placed."""
        for problem in self.unordered:
            self.problems.setdefault(problem)
        placed = sorted(self.poses, key=natural)
        for ref in placed:
            if self.circuit.part(ref).way_up_matters and not self._turned(ref):
                self._problem((ref,), f"{ref}'s way round matters and nothing says it: give "
                              "facing= an edge, or outward= a side of it",
                              *self.said[ref])  # fmt: skip
            box, names = self._box(ref), ("left", "top", "right", "bottom")
            for area, said, past, side in self._outside(ref, box):
                self._problem((ref,), f"{ref} is not inside {area}: it reaches "
                              f"{Length(past)} past its {side} side",
                              *said, *self.said[ref])  # fmt: skip
            over = (self.board[0] - box[0], self.board[1] - box[1],
                    box[2] - self.board[2], box[3] - self.board[3])  # fmt: skip
            for name, past in zip(names, over, strict=True):
                if past > 0:
                    self._problem((ref,), f"{ref} does not fit on the board: it reaches "
                                  f"{Length(past)} past the {name} edge",
                                  *self.said[ref])  # fmt: skip
            if max(over) <= 0 and not self._on(box):
                assert self.edge is not None
                # The point of the part furthest outside the outline, and how far.
                off = _area(*box).difference(self.edge)
                rings = [piece.exterior.coords for piece in getattr(off, "geoms", [off])]
                far, (x, y) = max((self.edge.distance(_area(x, y, x, y)), (x, y))
                                  for ring in rings for x, y in ring)  # fmt: skip
                where = f"({Length(round(x))}, {Length(round(y))})"
                self._problem((ref,), f"{ref} does not fit on the board: it reaches "
                              f"{Length(round(far))} outside the outline at {where}",
                              *self.said[ref])  # fmt: skip
            pose = self.poses[ref]
            if (f := self._over(box, pose.back, self.shapes[ref].through, ref)) is not None:
                self._problem((ref,), f"{ref} is over {f.label}", *self.said[ref])
            for f, d, far, said in self._close(box, pose.back, self.shapes[ref].through, ref):
                if said:
                    self._problem((ref,), f"{ref} is {Length(d)} from {f.label}, and "
                                  f"{said[0]} keeps it {Length(far)} from it",
                                  *self.said[ref], *said)  # fmt: skip
                    continue
                self._problem((ref,), f"{ref} is {Length(d)} from {f.label}, and the rules "
                              f"keep parts {Length(self.bodies_apart)} apart",
                              *self.said[ref], *self.rules)  # fmt: skip
            turned = _turned(self.shapes[ref], pose.rot, pose.back)
            if (
                max(over) <= 0
                and self._on(box)
                and (shy := self._shy(turned, pose.x.nm, pose.y.nm)) is not None
            ):
                d, n = shy
                pad = f"{ref}.{n}" if n else f"a hole of {ref}"
                self._problem((ref,), f"{pad} is {Length(d)} from the board's edge, and the "
                              f"rules keep copper {Length(self.margin)} from it",
                              *self.said[ref], *self.rules)  # fmt: skip
        for i, a in enumerate(placed):
            for b in placed[i + 1 :]:
                shares = (self.shapes[a].through or self.shapes[b].through
                          or self.poses[a].back == self.poses[b].back)  # fmt: skip
                if shares and _overlap(self._box(a), self._box(b)):
                    self._problem((a, b), f"{a} and {b} overlap", *self.said[a], *self.said[b])
                elif shares:
                    pose = self.poses[a]
                    turned = _turned(self.shapes[a], pose.rot, pose.back)
                    if (tight := self._tight(a, turned, pose.x.nm, pose.y.nm, b)) is not None:
                        d, n, m, gap, what = tight
                        one, two = (
                            f"{r}.{k}" if k else f"a hole of {r}" for r, k in ((a, n), (b, m))
                        )
                        self._problem((a, b), f"{one} is {Length(d)} from {two}, and the "
                                      f"rules keep {what} {Length(gap)} apart",
                                      *self.said[a], *self.said[b], *self.rules)  # fmt: skip
                    elif ((d := _off(self._box(a), self._box(b))) < self.bodies_apart
                          and not self._pitched(a, b)):  # fmt: skip
                        self._problem((a, b), f"{a} is {Length(d)} from {b}, and the rules "
                                      f"keep parts {Length(self.bodies_apart)} apart",
                                      *self.said[a], *self.said[b], *self.rules)  # fmt: skip
        for s, kept, faces in self._kept(placed):
            owner, name = _area_of(s).part.ref, _area_of(s).name
            for ref in placed:
                on = self.shapes[ref].through or self.poses[ref].back in faces
                if ref != owner and on and _overlap(self._box(ref), kept):
                    self._problem((ref, owner), f"{ref} is in {owner}'s {name} area, "
                                  "which is kept clear of copper", s, *self.said[ref])  # fmt: skip
        # A pad on a net whose middle is inside the box of a thing that copper is kept
        # from is one no track can reach where every face it has copper on is kept: a
        # pad on the surface on a kept face, and a pin in a hole when both are. One
        # problem for a part and a thing, whatever number of statements keep it clear.
        clear: dict[Fixed, tuple[set[bool], list[Keepout]]] = {}
        for s, thing in self.clears:
            if thing in self.things:
                on, said = clear.setdefault(thing, (set(), []))
                on |= {False, True} if s.both_sides else {thing.back}
                said.append(s)
        for thing, (on, said) in clear.items():
            k0, k1, k2, k3 = self.things[thing]
            for ref in placed:
                pose = self.poses[ref]
                turned = _turned(self.shapes[ref], pose.rot, pose.back)
                under = list(dict.fromkeys(
                    n for n, c in turned.copper
                    if self.nets[ref].get(n) is not None
                    and (len(on) == 2 or (n not in turned.holed and pose.back in on))
                    and 2 * k0 < c[0] + c[2] + 2 * pose.x.nm < 2 * k2
                    and 2 * k1 < c[1] + c[3] + 2 * pose.y.nm < 2 * k3))  # fmt: skip
                if under:
                    pads = _listed([f"{ref}.{n}" for n in under])
                    are, them = ("is", "it") if len(under) == 1 else ("are", "them")
                    where = (
                        "both sides" if len(on) == 2 else "the back" if True in on else "the front"
                    )
                    self._problem((ref,), f"{pads} {are} inside the outline of {thing}, which "
                                  f"is kept clear of copper on {where}: no track can reach "
                                  f"{them}", *self.said.get(ref, ()), *said)  # fmt: skip
        for s in self.aligns:
            firsts = [(p.ref, self._pads(p.ref)[0]) for p in s.parts
                      if p.ref in self.poses and self.shapes[p.ref].pads]  # fmt: skip
            for (a, (_, ax, ay)), (b, (_, bx, by)) in zip(firsts, firsts[1:], strict=False):
                for axis, apart in (("across", abs(bx - ax)), ("along", abs(by - ay))):
                    off = apart % s.grid.nm
                    if min(off, s.grid.nm - off) > 1:
                        self._problem((a, b), f"{s} does not hold: {a} and {b} are "
                                      f"{Length(apart)} apart {axis} the board, "
                                      f"{apart / s.grid.nm:.3g} steps", s, *self.said[a],
                                      *self.said[b])  # fmt: skip
