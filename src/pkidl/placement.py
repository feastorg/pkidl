"""Placement: where each part goes, worked out from what the board file said.

``solve`` reads a board's statements and gives a ``Solution``: a pose for each part it
could place, the parts nothing places, and every statement it could not make hold, each
with the line that made it. It moves nothing and never drops a statement to make the
others fit.

What each statement means here:

- ``against=`` an edge: the part lies along it, its longer side to the edge. ``inset=`` is
  from the edge to the centres of the part's pads nearest it, or to its outline when it
  has no pads; with no inset the part's outline touches the edge from inside. Along the
  edge it is centred, unless a second edge makes a corner, where it may lie along either.
- ``facing=`` an edge: the side of the part that is up in its footprint, as a library
  draws it, is turned to that edge of the board as the front shows it, whichever face
  the part is on.
- ``between=`` two parts: its centre is midway between theirs.
- ``near=`` a pin or part, ``within=`` a distance: the nearest place to it that is on the
  board and clear of every other part, a pad of the part no further than the distance
  from a pad of what it is near, centre to centre.
- ``side=``: the face of the board it is on; the front when nothing says.
- ``align``: the parts' first pins are a whole number of grid steps apart, across and
  along. It is checked, and moves nothing.

Which way round a part is, where nothing says, is the way that makes its connections
shortest. A part's outline is the box around its pads, courtyard and fabrication
drawing; two parts on one face may touch and not overlap, and a part with holes takes
both faces. The board is taken as the box around its outline.

Everything is in whole nanometres, and parts are placed in an order made from what
depends on what and then from their references, so the same statements give the same
placement whatever order they were added in.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import cache

from pkidl.circuit import Circuit, Pin, natural
from pkidl.intent import Align, Edge, Place, Side, Statement, canonical, conflicts
from pkidl.sexpr import Node, find, find_all
from pkidl.units import Length

STEP = Length(100_000)  # how finely a place near something is looked for

Box = tuple[int, int, int, int]  # x0, y0, x1, y1
_BODY = {"F.CrtYd", "B.CrtYd", "F.Fab", "B.Fab"}
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
class Solution:
    """What ``solve`` found. ``chosen`` lists what it decided where nothing said."""

    poses: Mapping[str, Pose]
    free: tuple[str, ...]
    problems: tuple[Problem, ...]
    chosen: tuple[str, ...]

    @property
    def ok(self) -> bool:
        """Every part placed, and everything said about them holding."""
        return not self.free and not self.problems


@dataclass(frozen=True)
class _Shape:
    """A footprint's pads (number and centre) and outline, about its origin."""

    pads: tuple[tuple[str, int, int], ...]
    box: Box
    through: bool


def _nm(value: object) -> int:
    return round(float(str(value)) * 1_000_000)


def _shape(footprint: Node) -> _Shape:
    pads, xs, ys = [], [], []
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
        xs += [x - (w + 1) // 2, x + (w + 1) // 2]
        ys += [y - (h + 1) // 2, y + (h + 1) // 2]
        through = through or pad[2] in ("thru_hole", "np_thru_hole")
    for item in footprint[2:]:
        if not isinstance(item, list) or not str(item[0]).startswith("fp_"):
            continue
        layer = find(item, "layer")
        if layer is None or layer[1] not in _BODY:
            continue
        points = [p for k in ("start", "mid", "end") if (p := find(item, k)) is not None]
        points += find_all(find(item, "pts") or [], "xy")
        centre = find(item, "center")
        if centre is not None and (end := find(item, "end")) is not None:
            r = round(math.dist((_nm(centre[1]), _nm(centre[2])), (_nm(end[1]), _nm(end[2]))))
            xs += [_nm(centre[1]) - r, _nm(centre[1]) + r]
            ys += [_nm(centre[2]) - r, _nm(centre[2]) + r]
        xs += [_nm(p[1]) for p in points]
        ys += [_nm(p[2]) for p in points]
    if not xs:  # nothing drawn: a point
        return _Shape((), (0, 0, 0, 0), False)
    return _Shape(tuple(pads), (min(xs), min(ys), max(xs), max(ys)), through)


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
    return _Shape(tuple(pads), (min(xs), min(ys), max(xs), max(ys)), shape.through)


def _moved(box: Box, x: int, y: int) -> Box:
    return (box[0] + x, box[1] + y, box[2] + x, box[3] + y)


def _overlap(a: Box, b: Box) -> bool:
    """Touching is not overlapping."""
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def solve(
    circuit: Circuit,
    library: Mapping[str, Node],
    extent: tuple[float, float, float, float] | None,
    statements: Iterable[Statement],
) -> Solution:
    """Place *circuit*'s parts, from footprints in *library*, on a board whose outline
    has the box *extent* (millimetres), as *statements* say."""
    statements = canonical(statements)
    if found := conflicts(statements):
        return Solution({}, (), tuple(Problem((c.part,), str(c)) for c in found), ())
    if extent is None:
        raise ValueError("a board is placed on once its outline is drawn")
    return _Solver(circuit, library, extent, statements).solution()


class _Solver:
    def __init__(
        self,
        circuit: Circuit,
        library: Mapping[str, Node],
        extent: tuple[float, float, float, float],
        statements: list[Statement],
    ) -> None:
        self.board: Box = (_nm(extent[0]), _nm(extent[1]), _nm(extent[2]), _nm(extent[3]))
        self.asks: dict[str, list[Place]] = {}
        self.aligns = [s for s in statements if isinstance(s, Align)]
        for s in statements:
            if isinstance(s, Place):
                self.asks.setdefault(s.part.ref, []).append(s)
        self.shapes: dict[str, _Shape] = {}
        self.nets: dict[str, dict[str, str]] = {}
        for part in circuit.parts():
            if part.footprint not in library:
                raise ValueError(f"{part}: no footprint {part.footprint!r} to place")
            self.shapes[part.ref] = _shape(library[part.footprint])
            self.nets[part.ref] = {p.number: p.net.name for p in part.pins() if p.net is not None}
        self.free = tuple(p.ref for p in circuit.parts() if p.ref not in self.asks)
        self.poses: dict[str, Pose] = {}
        self.problems: dict[Problem, None] = {}
        self.chosen: dict[str, None] = {}
        self.unordered: list[Problem] = []  # parts no order places, found once

    def solution(self) -> Solution:
        order = self._order()
        # Which way round a part goes depends on where its neighbours are, so place
        # everything, then again until nothing moves.
        for _ in range(4):
            before, done = dict(self.poses), set()
            self.problems, self.chosen = {}, {}
            for ref in order:
                if (pose := self._place(ref, done)) is not None:
                    self.poses[ref] = pose
                    done.add(ref)
                else:
                    self.poses.pop(ref, None)
            if self.poses == before:
                break
        else:
            self._problem(tuple(order), "the placement does not settle: each pass moves a part")
        self._check()
        problems = sorted(self.problems, key=lambda p: ([natural(r) for r in p.parts], p.text))
        return Solution(dict(sorted(self.poses.items(), key=lambda kv: natural(kv[0]))),
                        self.free, tuple(problems), tuple(self.chosen))  # fmt: skip

    def _problem(self, parts: tuple[str, ...], text: str, *statements: Statement) -> None:
        self.problems.setdefault(Problem(parts, text, statements))

    def _chose(self, text: str) -> None:
        self.chosen.setdefault(text)

    def _order(self) -> list[str]:
        """The parts that are placed, each after the parts it is placed by."""
        needs = {ref: {p.ref for s in asks for p in s.mentions()} - {ref}
                 for ref, asks in self.asks.items()}  # fmt: skip
        order: list[str] = []
        while ready := sorted((r for r in needs if r not in order and needs[r] <= set(order)),
                              key=natural):  # fmt: skip
            order.append(ready[0])
        stuck = sorted(set(needs) - set(order), key=natural)
        for ref in stuck:
            by = sorted(needs[ref] - set(order), key=natural)
            if unplaced := [r for r in by if r not in stuck]:
                text = f"{ref} is placed by {', '.join(unplaced)}, which nothing places"
            else:
                text = f"{ref} is placed by {', '.join(by)}, which is placed by it in turn"
            self.unordered.append(Problem((ref,), text, tuple(self.asks[ref])))
        return order

    def _place(self, ref: str, done: set[str]) -> Pose | None:
        asks = self.asks[ref]
        shape = self.shapes[ref]
        back = any(s.side is Side.BACK for s in asks)
        facing = next((s.facing for s in asks if s.facing), None)
        edges = {s.against: s for s in asks if s.against}
        nears = [s for s in asks if s.near is not None]
        betweens = [s for s in asks if s.between]
        if facing is not None:
            turns = {Edge.TOP: 0, Edge.LEFT: 90, Edge.BOTTOM: 180, Edge.RIGHT: 270}
            # On the back a footprint is mirrored top to bottom before it is turned.
            rots: tuple[int, ...] = ((turns[facing] + 180 * back) % 360,)
        elif len(edges) == 1:
            w, h = shape.box[2] - shape.box[0], shape.box[3] - shape.box[1]
            upright = next(iter(edges)) in (Edge.LEFT, Edge.RIGHT)
            rots = _ROTATIONS if w == h else (90, 270) if (w > h) == upright else (0, 180)
        else:
            rots = _ROTATIONS
        if nears:
            if len(nears) > 1 or edges or betweens:
                self._problem((ref,), f"{ref}: near= is solved alone: one near=, and no "
                              "against= or between= beside it", *asks)  # fmt: skip
                return None
            return self._near(ref, nears[0], rots, back, done)
        best = None
        for rot in rots:
            turned = _turned(shape, rot, back)
            at = self._fixed(ref, turned, edges, betweens)
            if at is None:
                return None
            key = (self._wires(ref, turned, *at), rot)
            if best is None or key < best[0]:
                best = (key, Pose(Length(at[0]), Length(at[1]), rot, back))
        assert best is not None
        if len(rots) > 1:
            ways = ", ".join(map(str, rots))
            self._chose(f"{ref}: turned {best[1].rot} degrees, of {ways}, for the "
                               "shortest connections")  # fmt: skip
        return best[1]

    def _fixed(self, ref: str, turned: _Shape, edges: dict[Edge, Place],
               betweens: list[Place]) -> tuple[int, int] | None:  # fmt: skip
        """Where the origin goes when edges and neighbours fix it, or None with the
        reason reported."""
        x0, y0, x1, y1 = self.board
        bx0, by0, bx1, by1 = turned.box
        px = [p[1] for p in turned.pads] or [bx0, bx1]
        py = [p[2] for p in turned.pads] or [by0, by1]
        xs: list[tuple[int, Place]] = []
        ys: list[tuple[int, Place]] = []
        for edge, s in edges.items():
            d = None if s.inset is None else s.inset.nm
            if edge is Edge.LEFT:
                xs.append((x0 - bx0 if d is None else x0 + d - min(px), s))
            elif edge is Edge.RIGHT:
                xs.append((x1 - bx1 if d is None else x1 - d - max(px), s))
            elif edge is Edge.TOP:
                ys.append((y0 - by0 if d is None else y0 + d - min(py), s))
            else:
                ys.append((y1 - by1 if d is None else y1 - d - max(py), s))
        for s in betweens:
            assert s.between is not None
            if missing := [p.ref for p in s.between if p.ref not in self.poses]:
                self._problem((ref,), f"{ref} is placed by {', '.join(missing)}, which is "
                              "not placed", s)  # fmt: skip
                return None
            (ax, ay), (bx, by) = (self._centre(p.ref) for p in s.between)
            xs.append(((ax + bx) // 2 - (bx0 + bx1) // 2, s))
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
            if not values:
                other = ys if axis == "across" else xs
                if not any(s.against for _, s in other):
                    self._problem((ref,), f"{ref} is not placed {axis} the board: nothing "
                                  "says where", *self.asks[ref])  # fmt: skip
                    return None
                edge = next(s.against for _, s in other if s.against)
                self._chose(f"{ref}: centred along the {edge.value} edge")
                values = [(lo + hi) // 2 - (b0 + b1) // 2]
            at.append(values[0])
        return at[0], at[1]

    def _centre(self, ref: str) -> tuple[int, int]:
        x0, y0, x1, y1 = self._box(ref)
        return (x0 + x1) // 2, (y0 + y1) // 2

    def _box(self, ref: str) -> Box:
        pose = self.poses[ref]
        return _moved(_turned(self.shapes[ref], pose.rot, pose.back).box, pose.x.nm, pose.y.nm)

    def _pads(self, ref: str) -> list[tuple[str, int, int]]:
        pose = self.poses[ref]
        turned = _turned(self.shapes[ref], pose.rot, pose.back)
        return [(n, x + pose.x.nm, y + pose.y.nm) for n, x, y in turned.pads]

    def _wires(self, ref: str, turned: _Shape, x: int, y: int) -> int:
        """How far this part's pads would be from the nearest pad on their net, summed."""
        on: dict[str, list[tuple[int, int]]] = {}
        for other in self.poses:
            if other != ref:
                for number, px, py in self._pads(other):
                    if (net := self.nets[other].get(number)) is not None:
                        on.setdefault(net, []).append((px, py))
        total = 0
        for number, px, py in turned.pads:
            if (net := self.nets[ref].get(number)) in on:
                total += min(abs(px + x - ox) + abs(py + y - oy) for ox, oy in on[net])
        return total

    def _clear(self, ref: str, box: Box, back: bool, through: bool, of: Iterable[str]) -> bool:
        """Inside the board, and overlapping none *of* the parts placed."""
        if not (self.board[0] <= box[0] and self.board[1] <= box[1]
                and box[2] <= self.board[2] and box[3] <= self.board[3]):  # fmt: skip
            return False
        for other in of:
            if other == ref or other not in self.poses:
                continue
            shares = through or self.shapes[other].through or self.poses[other].back == back
            if shares and _overlap(box, self._box(other)):
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
        n = limit // step
        offsets = sorted((dx * dx + dy * dy, dy, dx)
                         for dx in range(-n * step, n * step + 1, step)
                         for dy in range(-n * step, n * step + 1, step)
                         if dx * dx + dy * dy <= limit * limit)  # fmt: skip
        best, found = None, -1
        for d2, dy, dx in offsets:
            if best is not None and d2 > found:
                break
            for rot in rots:
                turned = _turned(shape, rot, back)
                for _, px, py in turned.pads:
                    for tx, ty in targets:
                        x, y = tx + dx - px, ty + dy - py
                        if not self._clear(
                            ref, _moved(turned.box, x, y), back, shape.through, done
                        ):
                            continue
                        key = (self._wires(ref, turned, x, y), rot, y, x)
                        if best is None or key < best[0]:
                            best, found = (key, Pose(Length(x), Length(y), rot, back)), d2
        if best is None:
            self._problem((ref,), f"{ref} has no place within {s.within} of {s.near} that is on "
                          f"the {'back' if back else 'front'} of the board and clear of the "
                          "other parts", s)  # fmt: skip
            return None
        self._chose(f"{ref}: {Length(math.isqrt(found))} from {s.near}, turned "
                           f"{best[1].rot} degrees")  # fmt: skip
        return best[1]

    def _check(self) -> None:
        """What only shows once everything is placed."""
        for problem in self.unordered:
            self.problems.setdefault(problem)
        placed = sorted(self.poses, key=natural)
        for ref in placed:
            box, names = self._box(ref), ("left", "top", "right", "bottom")
            over = (self.board[0] - box[0], self.board[1] - box[1],
                    box[2] - self.board[2], box[3] - self.board[3])  # fmt: skip
            for name, past in zip(names, over, strict=True):
                if past > 0:
                    self._problem((ref,), f"{ref} does not fit on the board: it reaches "
                                  f"{Length(past)} past the {name} edge",
                                  *self.asks[ref])  # fmt: skip
        for i, a in enumerate(placed):
            for b in placed[i + 1 :]:
                shares = (self.shapes[a].through or self.shapes[b].through
                          or self.poses[a].back == self.poses[b].back)  # fmt: skip
                if shares and _overlap(self._box(a), self._box(b)):
                    self._problem((a, b), f"{a} and {b} overlap", *self.asks[a], *self.asks[b])
        for s in self.aligns:
            firsts = [(p.ref, self._pads(p.ref)[0]) for p in s.parts
                      if p.ref in self.poses and self.shapes[p.ref].pads]  # fmt: skip
            for (a, (_, ax, ay)), (b, (_, bx, by)) in zip(firsts, firsts[1:], strict=False):
                for axis, apart in (("across", abs(bx - ax)), ("along", abs(by - ay))):
                    off = apart % s.grid.nm
                    if min(off, s.grid.nm - off) > 1:
                        self._problem((a, b), f"{s} does not hold: {a} and {b} are "
                                      f"{Length(apart)} apart {axis} the board, "
                                      f"{apart / s.grid.nm:.3g} steps", s, *self.asks[a],
                                      *self.asks[b])  # fmt: skip
