"""The neck of a stretch: the least copper there is to cut to part its two ends.

``pkidl.paths`` measures the tracks of a stretch. This measures all the copper of its
net between the same two ends, on every layer: its tracks, its pads, its vias and its
pours as they fill. The neck is the least total width of copper that has to be cut
through to part one end from the other. It is a cut and not the narrowest passage:
four spokes of a relief 0.5 mm wide are a neck of 2 mm, the current dividing among
them, and two tracks side by side between the same two places are the sum of their
widths. Where one chain of tracks is all that joins the ends it is the narrowest of
them.

**What is cut, and what is not.** A pad and a via are each one piece that no cut goes
through, as each has no resistance in the figure for the tracks: a cut goes round
one, across the copper that meets it, which for a pad on a relief is its spokes. An
end is the pads its stop has on the net, and the cut may fall round those very pads.
Pads and vias whose copper touches on a layer are one piece, and ends that are one
piece have no neck. A via, and a pad with a hole, has its copper on every layer and
joins them without limit: **the barrel of a via is not counted**, only the copper of
each layer round its pad, so a neck through a via is at most what is said. A pad's
copper is the box, oval or circle of its size, as everywhere in ``pkidl.fill``.

**Which fill.** A zone the board has KiCad's fill of (``filled_polygon``, as a board
that KiCad refilled and saved has) is measured on that fill. A zone with none, as on
the board a build has just written, is measured on pkidl's model of how KiCad fills
it (``pkidl.fill``), where the outline to fill inside was given: its pieces cut back
round each pad that has a relief, and the spokes of the relief that have their
copper. A reading says which it was measured on.

**How.** The copper of the net on a layer, less its pads and vias, is cut into
triangles whose corners are all on its edge (``shapely.delaunay_triangles``, with
points put along the edge until each piece of it is a side of a triangle). A cut
along sides of triangles is then a set of straight chords from edge to edge, and the
least such cut is found as the most that flows from one end to the other, each side
letting through its length and each pad and via being one node that joins its layers.
A side is a chord the copper really has, so what is found is a cut that can be made
and **the neck is never wider than is said**; it can be narrower than is said only
where a shorter chord is not a side of any triangle. Three things put such chords in:

1. Points along every edge on a lattice of ``STEP`` in the edge's own direction, so
   that two parallel edges, the sides of a track or of a spoke, have points straight
   across from each other, at any angle and anywhere on the board.
2. Each chord that is the shortest between two walls of the copper no further apart
   than the neck found so far, each wall with the nearest sixty-four such, where it
   lies all in copper. Chords that cross are both kept, with a point where they cross.
3. The cut found, pulled tight: where it bends at a point, or two of its pieces end
   on one hole, the chord that goes straight; and where a piece ends on a wall, the
   point of the wall nearest its other end. The flow is found again until nothing
   shortens.

On shapes whose neck is known (strips, strips with holes, an hourglass, pads on
spokes, a slotted plane, a plane with holes in rows, chains of track, two layers, and
strips with a random scatter of holes against the shortest way from wall to wall
through the holes), at many angles and offsets, it is the neck to the micrometre the
figure is given in (``tests/test_pkidl_neck.py``). With pads and vias of the net
scattered among the holes as well, the least cut can bend round the corner of a pad:
a cut is pulled tight where it was found, and one that goes by another pad is not
looked for. Of a hundred such strips it is the neck to the micrometre on all but
two, where it is said 0.3 % and 2.3 % wider than it is.

Copper is taken to the nanometre, and a point of the mesh is moved by up to a
hundredth of that so that no three are in a line. Two pieces of copper nearer than
that are one, and a face of a pad is where an edge of the copper is within two
nanometres of the pad.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np
import shapely
from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.geometry import Point as SPoint
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from pkidl.fill import (
    _gap,
    _layers,
    _net,
    _on,
    _outline,
    _parts,
    _pours,
    _relief,
    _spokes,
    fills,
)
from pkidl.measure import filled
from pkidl.sexpr import Node, find_all
from pkidl.units import Length

KICAD, MODEL = "KiCad's fill", "pkidl's model of the fill"  # what a neck was measured on
STEP = 0.1  # millimetres: how far apart the points along an edge of the copper are
_GRID = 1e-6  # millimetres: copper is taken to the nanometre
_FACE = 2e-6  # millimetres: an edge of the copper this near a pad is a face of the pad
_ON = 1e-9  # millimetres: a corner no further off a chord is on it
_SHORT = 1e-3  # millimetres: an edge of the copper no longer is not held to
_RUN = 5.0  # millimetres: the most of a wall that is looked at as one
_NEAREST = 64  # how many of the walls near a wall its shortest chords are looked for to
_TURN = 0.5  # radians: a wall is another wall past a corner this sharp
_ROUNDS = 12  # how many times a cut is pulled tight


@dataclass(frozen=True)
class Piece:
    """One piece of copper that the cut of a neck goes across: how wide it is there;
    the middle of the cut across it, in board millimetres, which for a cut all round
    a pad is the pad; its layer; and what it is of: ``track``, ``pour``, ``the relief
    of J1.2``, ``the copper round J1.2``, ``the copper round a via``, or ``copper``
    where it is none of those."""

    width: Length
    at: tuple[Length, Length]
    layer: str
    of: str


@dataclass(frozen=True)
class Neck:
    """The neck between two ends: its *width*, nothing where no copper joins them;
    the pieces of copper its cut goes *across*, the widest first; and what the pours
    among it were measured on, ``KICAD``, ``MODEL`` or both, or nothing where the net
    has no fill to measure."""

    width: Length
    across: tuple[Piece, ...] = ()
    filled: str = ""


def _key(u: int, v: int) -> tuple[int, int]:
    return (u, v) if u < v else (v, u)


def _side(p: tuple[float, float], q: tuple[float, float], r: tuple[float, float]) -> float:
    """Which side of the line from *p* to *q* the point *r* is on, by its sign."""
    return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])


def _stations(ring: np.ndarray, step: float) -> np.ndarray:
    """The corners of a closed *ring* and, along each of its edges, the points of a
    lattice *step* apart in the edge's own direction: two parallel edges have theirs
    straight across from each other. The ring is given back open."""
    a, b = ring[:-1], ring[1:]
    long = np.hypot(*(b - a).T)
    a, b, long = a[long > 0], b[long > 0], long[long > 0]
    along = (b - a) / long[:, None]
    along[(along[:, 0] < 0) | ((along[:, 0] == 0) & (along[:, 1] < 0))] *= -1
    ta, tb = (a * along).sum(1), (b * along).sum(1)
    first = np.ceil((np.minimum(ta, tb) + 1e-7) / step)
    last = np.floor((np.maximum(ta, tb) - 1e-7) / step)
    count = np.maximum(last - first + 1, 0).astype(int) + 1  # the corner, then its points
    edge = np.repeat(np.arange(len(a)), count)
    k = np.arange(len(edge)) - np.repeat(np.cumsum(count) - count, count)
    at = np.where((ta <= tb)[edge], first[edge] + k - 1, last[edge] - k + 1) * step
    part = np.where(k == 0, 0.0, (at - ta[edge]) / (tb[edge] - ta[edge]))
    return a[edge] + part[:, None] * (b[edge] - a[edge])


class _Sheet:
    """The copper of a net on one layer, less its pads and vias, as triangles: each
    corner's place (``xy``), for each side the corners across from it (``wings``, one
    for a side on the edge of the copper), each corner's neighbours (``nbr``), the
    sides that are a face of a pad or a via and which (``face``), and the sides put in
    as chords, which are kept (``kept``)."""

    def __init__(self, layer: str, copper: BaseGeometry,
                 lumps: Sequence[tuple[int, BaseGeometry]], step: float,
                 rng: np.random.Generator) -> None:  # fmt: skip
        self.layer = layer
        self.xy: list[tuple[float, float]] = []
        self.wings: dict[tuple[int, int], list[int]] = {}
        self.nbr: dict[int, set[int]] = {}
        self.face: dict[tuple[int, int], int] = {}
        self.kept: set[tuple[int, int]] = set()
        self.looked: set[tuple[int, int, int, int]] = set()  # the walls already paired
        rings, polys = [], []
        copper = shapely.set_precision(copper, _GRID)
        for poly in getattr(copper, "geoms", [copper]):
            if not isinstance(poly, Polygon) or poly.is_empty:
                continue
            mine = []
            for ring in (poly.exterior, *poly.interiors):
                xy = _stations(np.asarray(ring.coords), step)
                xy = xy + rng.uniform(-_GRID / 100, _GRID / 100, xy.shape)
                mine.append(np.vstack([xy, xy[:1]]))
            rings += mine
            polys.append(Polygon(mine[0], mine[1:]))
        self.area = MultiPolygon(polys)
        shapely.prepare(self.area)
        if not rings:
            return
        tri = np.zeros((0, 3, 2))
        # Triangles of every point of the edge, with a point put in the middle of
        # each piece of the edge that is not a side of one, until each is.
        for _ in range(40):
            corners = shapely.get_coordinates(shapely.get_parts(shapely.delaunay_triangles(
                shapely.multipoints(np.unique(np.vstack(rings), axis=0)))))  # fmt: skip
            tri = corners.reshape(-1, 4, 2)[:, :3]
            z = tri[..., 0] + 1j * tri[..., 1]
            sides = np.stack([z, np.roll(z, -1, axis=1)], axis=2).reshape(-1, 2)
            have = set(zip(sides[:, 0].tolist(), sides[:, 1].tolist(), strict=True))
            missing = 0
            for n, ring in enumerate(rings):
                at = (ring[:, 0] + 1j * ring[:, 1]).tolist()
                gone = np.array([(p, q) not in have and (q, p) not in have
                                 for p, q in zip(at, at[1:], strict=False)])  # fmt: skip
                gone &= np.hypot(*(ring[1:] - ring[:-1]).T) > _SHORT
                if gone.any():
                    missing += int(gone.sum())
                    k = np.flatnonzero(gone)
                    rings[n] = np.insert(ring, k + 1, (ring[k] + ring[k + 1]) / 2, axis=0)
            if not missing:
                break
        middle = tri.mean(axis=1)
        tri = tri[shapely.contains_xy(self.area, middle[:, 0], middle[:, 1])]
        places, ids = np.unique((tri[..., 0] + 1j * tri[..., 1]).reshape(-1), return_inverse=True)
        self.xy = list(zip(places.real.tolist(), places.imag.tolist(), strict=True))
        for a, b, c in ids.reshape(-1, 3).tolist():
            for u, v, o in ((a, b, c), (b, c, a), (c, a, b)):
                self.wings.setdefault(_key(u, v), []).append(o)
                self.nbr.setdefault(u, set()).add(v)
                self.nbr.setdefault(v, set()).add(u)
        outer = [side for side, wings in self.wings.items() if len(wings) == 1]
        if lumps and outer:
            xy, ends = np.array(self.xy), np.array(outer)
            middles = shapely.points((xy[ends[:, 0]] + xy[ends[:, 1]]) / 2)
            tree = shapely.STRtree(np.array([shape for _, shape in lumps]))
            for m, s in zip(*tree.query(middles, predicate="dwithin", distance=_FACE).tolist(),
                            strict=True):  # fmt: skip
                self.face.setdefault(outer[m], lumps[s][0])

    def covers(self, p: tuple[float, float], q: tuple[float, float]) -> bool:
        """Whether the chord from *p* to *q*, both on the edge, is all in copper."""
        long = math.dist(p, q)
        if long < 10 * _FACE:
            return False
        ux, uy = (q[0] - p[0]) / long * _FACE, (q[1] - p[1]) / long * _FACE
        inner = LineString([(p[0] + ux, p[1] + uy), (q[0] - ux, q[1] - uy)])
        return bool(self.area.covers(inner))

    def flip(self, u: int, v: int) -> None:
        """The side between two triangles, taken out for the other diagonal of the
        four corners they have."""
        o1, o2 = self.wings.pop(_key(u, v))
        self.nbr[u].discard(v)
        self.nbr[v].discard(u)
        self.wings[_key(o1, o2)] = [u, v]
        self.nbr[o1].add(o2)
        self.nbr[o2].add(o1)
        for x, y, old, new in ((u, o1, v, o2), (v, o1, u, o2), (u, o2, v, o1), (v, o2, u, o1)):
            wings = self.wings[_key(x, y)]
            wings[wings.index(old)] = new

    def chord(self, a: int, b: int, deep: int = 0) -> bool:
        """Make the chord from corner *a* to corner *b* a side, and keep it: each side
        it crosses is flipped until none does. Where it crosses a side that is kept, a
        corner is put where they cross, and where it goes through a corner it is by
        way of that corner: either way it is two chords. False where it cannot be
        made, as where it leaves the copper."""
        if b in self.nbr[a]:
            self.kept.add(_key(a, b))
            return True
        if deep > 50:
            return False
        xy, wings = self.xy, self.wings
        pa, pb = xy[a], xy[b]
        long = math.dist(pa, pb)

        def off(i: int) -> float:
            """How far the corner *i* is off the line of the chord, by its sign."""
            return _side(pa, pb, xy[i]) / long

        def by(i: int) -> bool:
            return self.chord(a, i, deep + 1) and self.chord(i, b, deep + 1)

        for v in self.nbr[a]:
            along = (xy[v][0] - pa[0]) * (pb[0] - pa[0]) + (xy[v][1] - pa[1]) * (pb[1] - pa[1])
            if abs(off(v)) < _ON and 0 < along < long * long:
                return by(v)
        side = came = None
        for v in self.nbr[a]:
            for o in wings[_key(a, v)]:
                if off(v) * off(o) < 0 and _side(xy[v], xy[o], pa) * _side(xy[v], xy[o], pb) < 0:
                    side, came = (v, o), a
        if side is None or came is None:
            return False
        crossed: list[tuple[int, int]] = []
        while True:
            k = _key(*side)
            if len(wings[k]) != 2:
                return False
            if k in self.kept:
                su, sv = off(k[0]), off(k[1])
                part = su / (su - sv)
                at = (xy[k[0]][0] + part * (xy[k[1]][0] - xy[k[0]][0]),
                      xy[k[0]][1] + part * (xy[k[1]][1] - xy[k[0]][1]))  # fmt: skip
                for i in k:
                    if math.dist(at, xy[i]) < _GRID:
                        return by(i)
                if min(math.dist(at, pa), math.dist(at, pb)) < _GRID:
                    return False
                return by(self.cross(k[0], k[1], at))
            crossed.append(k)
            nxt = wings[k][0] if wings[k][1] == came else wings[k][1]
            if nxt == b:
                break
            turn = off(nxt)
            if abs(turn) < _ON:
                return by(nxt)
            if len(crossed) > len(wings):
                return False
            v, o = side
            side, came = ((o, nxt), v) if turn * off(v) > 0 else ((v, nxt), o)
        queue = deque(crossed)
        tries = 20 * len(crossed) + 100
        while queue and tries:
            tries -= 1
            u, v = queue.popleft()
            o1, o2 = wings[(u, v)]
            if _side(xy[o1], xy[o2], xy[u]) * _side(xy[o1], xy[o2], xy[v]) < 0:
                self.flip(u, v)
                if {o1, o2} != {a, b} and off(o1) * off(o2) < 0:
                    queue.append(_key(o1, o2))
            else:
                queue.append((u, v))
        if b not in self.nbr[a]:
            return False
        self.kept.add(_key(a, b))
        return True

    def cross(self, u: int, v: int, at: tuple[float, float]) -> int:
        """A new corner at *at* on the kept side from *u* to *v*, inside the copper."""
        o1, o2 = self.wings.pop(_key(u, v))
        self.kept.discard(_key(u, v))
        x = len(self.xy)
        self.xy.append(at)
        self.nbr[u].discard(v)
        self.nbr[v].discard(u)
        self.nbr[x] = {u, v, o1, o2}
        for y in (u, v, o1, o2):
            self.nbr[y].add(x)
        self.wings[_key(u, x)] = [o1, o2]
        self.wings[_key(x, v)] = [o1, o2]
        self.kept |= {_key(u, x), _key(x, v)}
        for o in (o1, o2):
            self.wings[_key(x, o)] = [u, v]
            for y, old in ((u, v), (v, u)):
                wings = self.wings[_key(y, o)]
                wings[wings.index(old)] = x
        return x

    def split(self, u: int, v: int, at: tuple[float, float]) -> int:
        """A new corner at *at* on the edge of the copper between *u* and *v*."""
        side = _key(u, v)
        (o,) = self.wings.pop(side)
        x = len(self.xy)
        self.xy.append(at)
        self.nbr[u].discard(v)
        self.nbr[v].discard(u)
        self.nbr[x] = {u, v, o}
        for y in (u, v, o):
            self.nbr[y].add(x)
        self.wings[_key(u, x)] = [o]
        self.wings[_key(x, v)] = [o]
        self.wings[_key(x, o)] = [u, v]
        for y, old in ((u, v), (v, u)):
            wings = self.wings[_key(y, o)]
            wings[wings.index(old)] = x
        if side in self.face:
            self.face[_key(u, x)] = self.face[_key(x, v)] = self.face.pop(side)
        return x

    def walls(self) -> list[tuple[list[int], int, int]]:
        """The edge of the copper that is no face of a pad or a via, as runs of corners
        in order (the run, and where in it one starts and ends): a run goes no further
        than a sharp corner, nor than ``_RUN``."""
        outer: dict[int, list[int]] = {}
        for (u, v), wings in self.wings.items():
            if len(wings) == 1 and (u, v) not in self.face:
                outer.setdefault(u, []).append(v)
                outer.setdefault(v, []).append(u)
        xy = self.xy
        used: set[tuple[int, int]] = set()
        found = []
        for start in [u for u, n in outer.items() if len(n) != 2] + list(outer):
            for first in outer[start]:
                if _key(start, first) in used:
                    continue
                run = [start, first]
                used.add(_key(start, first))
                while len(outer[run[-1]]) == 2 and run[-1] != start:
                    a, b = outer[run[-1]]
                    nxt = b if a == run[-2] else a
                    if _key(run[-1], nxt) in used:
                        break
                    used.add(_key(run[-1], nxt))
                    run.append(nxt)
                step = np.diff(np.array([xy[i] for i in run]), axis=0)
                long = np.hypot(step[:, 0], step[:, 1])
                way = np.arctan2(step[:, 1], step[:, 0])
                turn = np.abs((np.diff(way) + np.pi) % (2 * np.pi) - np.pi)
                cuts, gone = [0], 0.0
                for k in range(1, len(run) - 1):
                    gone += long[k - 1]
                    if turn[k - 1] > _TURN or gone > _RUN:
                        cuts.append(k)
                        gone = 0.0
                cuts.append(len(run) - 1)
                found += [(run, a, b) for a, b in zip(cuts, cuts[1:], strict=False)]
        return found

    def shortest(self, reach: float) -> int:
        """Put in, as chords, the shortest way between each two walls of the copper no
        further apart than *reach*, where it is all in copper and no shorter way is
        just past the end of either wall. How many were put in."""
        walls = self.walls()
        if not walls:
            return 0
        xy = self.xy
        lines = [LineString([xy[i] for i in run[a : b + 1]]) for run, a, b in walls]
        # Each wall with the nearest of the walls within reach of it, and of those the
        # ones its shortest way to is all in copper: what is further off is behind one
        # of them, or has its chord put in when a cut is pulled tight.
        one, two = shapely.STRtree(lines).query(lines, predicate="dwithin", distance=reach)
        one, two = one[one != two], two[one != two]
        every = np.array(lines)
        order = np.lexsort((shapely.distance(every[one], every[two]), one))
        one, two = one[order], two[order]
        near = (np.arange(len(one)) - np.searchsorted(one, one) < _NEAREST) & (one < two)
        one, two = one[near], two[near]
        ways = shapely.get_coordinates(shapely.shortest_line(every[one], every[two]))
        ways = ways.reshape(-1, 2, 2)
        long = np.hypot(*(ways[:, 1] - ways[:, 0]).T)
        clear = long >= 10 * _FACE
        one, two, ways, long = one[clear], two[clear], ways[clear], long[clear]
        inset = (ways[:, 1] - ways[:, 0]) / long[:, None] * _FACE
        inner = shapely.linestrings(np.stack([ways[:, 0] + inset, ways[:, 1] - inset], axis=1))
        clear = shapely.covers(self.area, inner)
        found = []  # each: how long, and its two ends as (run, where, how far on, place)
        for i, j, way in zip(one[clear].tolist(), two[clear].tolist(), ways[clear], strict=True):
            (ri, ai, bi), (rj, aj, bj) = walls[i], walls[j]
            pair = (ri[ai], ri[ai + 1], rj[aj], rj[aj + 1])
            if pair in self.looked:
                continue
            self.looked.add(pair)
            if ri is rj and (bi == aj or (ai == 0 and bj == len(rj) - 1 and rj[0] == rj[-1])):
                continue  # one wall goes on into the other
            ends = []
            for (run, a, b), p, far in ((walls[i], way[0], way[1]), (walls[j], way[1], way[0])):
                corners = np.array([xy[k] for k in run[a : b + 1]])
                start, along = corners[:-1], np.diff(corners, axis=0)
                part = np.clip(((p - start) * along).sum(1) / (along * along).sum(1), 0, 1)
                m = int(np.argmin(np.hypot(*(start + part[:, None] * along - p).T)))
                long = float(np.hypot(*along[m]))
                k, on = a + m, float(part[m])
                if on * long < _GRID:
                    on = 0.0
                elif (1 - on) * long < _GRID:
                    k, on = k + 1, 0.0
                if on == 0.0 and k in (a, b):
                    # At the end of its run: the wall goes on, and may come nearer.
                    past = (run[a - 1] if k == a and a > 0
                            else run[b + 1] if k == b and b < len(run) - 1
                            else None if run[0] != run[-1] or len(run) < 3
                            else run[1] if k == b else run[-2])  # fmt: skip
                    here = np.array(xy[run[k]])
                    on_past = None if past is None else np.array(xy[past]) - here
                    if on_past is not None and float((far - here) @ on_past) > 1e-12:
                        break
                ends.append((run, k, on, (float(p[0]), float(p[1]))))
            if len(ends) == 2:
                found.append((math.dist(way[0], way[1]), ends[0], ends[1]))
        # The new corners, each edge split in the order they come along it.
        on_edge: dict[tuple[int, int], list[tuple[float, tuple[float, float]]]] = {}
        for _, *ends in found:
            for run, k, on, at in ends:
                if on:
                    on_edge.setdefault((run[k], run[k + 1]), []).append((on, at))
        made: dict[tuple[float, float], int] = {}
        for (u, v), puts in on_edge.items():
            for _, at in sorted(set(puts)):
                if at not in made:
                    u = made[at] = self.split(u, v, at)
        # Those that are sides already are kept first, so that none is lost to another
        # put in across it; then the rest, the longest first.
        chords = [tuple(made[at] if on else run[k] for run, k, on, at in ends)
                  for _, *ends in sorted(found, key=lambda f: -f[0])]  # fmt: skip
        self.kept |= {_key(a, b) for a, b in chords if b in self.nbr[a]}
        return sum(a != b and self.chord(a, b) for a, b in chords)

    def taut(self, cut: Sequence[tuple[int, int]]) -> int:
        """Pull a *cut*, the sides it is of, tight: put in the chord that goes straight
        where it bends at a corner, or where two of its pieces end on one hole, and
        move each end on a wall to the point of the wall nearest the piece's other
        end. How many chords were put in."""
        xy = self.xy
        at: dict[int, list[int]] = {}
        for u, v in cut:
            at.setdefault(u, []).append(v)
            at.setdefault(v, []).append(u)

        def straight(a: int, b: int, round_: float) -> int:
            return int(a != b and b not in self.nbr[a]
                       and math.dist(xy[a], xy[b]) < round_ - 1e-7
                       and self.covers(xy[a], xy[b]) and self.chord(a, b))  # fmt: skip

        made = 0
        for w, ends in at.items():
            if len(ends) == 2:
                a, b = ends
                made += straight(a, b, math.dist(xy[a], xy[w]) + math.dist(xy[w], xy[b]))
            elif len(ends) == 1:
                made += self.slide(w, ends[0])
        # Which piece of the copper's edge each end of a piece is on.
        outer: dict[int, list[int]] = {}
        for (u, v), wings in self.wings.items():
            if len(wings) == 1:
                outer.setdefault(u, []).append(v)
                outer.setdefault(v, []).append(u)
        rim: dict[int, int] = {}
        for start in (w for w, ends in at.items() if len(ends) == 1 and w in outer):
            if start not in rim:
                rim[start] = start
                stack = [start]
                while stack:
                    for y in outer[stack.pop()]:
                        if y not in rim:
                            rim[y] = start
                            stack.append(y)
        on: dict[int, list[tuple[int, int]]] = {}
        for w, ends in at.items():
            if len(ends) == 1 and w in rim:
                on.setdefault(rim[w], []).append((w, ends[0]))
        for there in on.values():
            for n, (w1, a) in enumerate(there):
                for w2, b in there[n + 1 :]:
                    if a in self.nbr:
                        made += straight(a, b, math.dist(xy[a], xy[w1]) + math.dist(xy[w2], xy[b]))
        return made

    def slide(self, p: int, a: int) -> int:
        """The end *p* of a piece of a cut from *a*, moved along the wall it is on, no
        further than the piece is long, to where the wall is nearest *a*: the chord
        from *a* to there is put in. 1 where one was."""
        xy, wings = self.xy, self.wings

        def wall(u: int, v: int) -> bool:
            return len(wings[_key(u, v)]) == 1 and _key(u, v) not in self.face

        reach = math.dist(xy[a], xy[p])
        least, best = reach - 1e-7, None
        for first in [v for v in self.nbr[p] if wall(p, v)]:
            u, v, gone = p, first, 0.0
            while gone < reach and v != a:
                (ux, uy), (vx, vy) = xy[u], xy[v]
                dx, dy = vx - ux, vy - uy
                on = ((xy[a][0] - ux) * dx + (xy[a][1] - uy) * dy) / (dx * dx + dy * dy)
                on = min(1.0, max(0.0, on))
                at = (ux + on * dx, uy + on * dy)
                if math.dist(xy[a], at) < least:
                    least, best = math.dist(xy[a], at), (u, v, on, at)
                gone += math.hypot(dx, dy)
                nxt = [w for w in self.nbr[v] if w != u and wall(v, w)]
                if len(nxt) != 1:
                    break
                u, v = v, nxt[0]
        if best is None:
            return 0
        u, v, on, at = best
        if not self.covers(xy[a], at):
            return 0
        long = math.dist(xy[u], xy[v])
        x = u if on * long < _GRID else v if (1 - on) * long < _GRID else self.split(u, v, at)
        return int(x not in (p, a) and self.chord(a, x))


@dataclass(frozen=True)
class _Lump:
    """A pad or a via: its name where it is a pad, and its copper on each layer."""

    name: str
    copper: dict[str, BaseGeometry]


class _Copper:
    """All the copper of one net, for the necks between its pads (see the module):
    *sheets* its copper on each layer, pads and vias among it, and *lumps* each pad
    and via."""

    def __init__(self, sheets: dict[str, BaseGeometry], lumps: Sequence[_Lump],
                 step: float = STEP) -> None:  # fmt: skip
        self.lumps = list(lumps)
        self.group = list(range(len(self.lumps)))
        rng = np.random.default_rng(1)
        self.sheets: list[_Sheet] = []
        for layer in sorted(sheets):
            there = [(i, lump.copper[layer]) for i, lump in enumerate(self.lumps)
                     if layer in lump.copper]  # fmt: skip
            # Pads and vias whose copper touches on a layer are one piece.
            shapes = np.array([shape for _, shape in there])
            if len(there):
                near = shapely.STRtree(shapes).query(shapes, predicate="dwithin", distance=_GRID)
                for i, j in zip(*near.tolist(), strict=True):
                    self.group[self.root(there[i][0])] = self.root(there[j][0])
        for layer in sorted(sheets):
            there = [(i, lump.copper[layer]) for i, lump in enumerate(self.lumps)
                     if layer in lump.copper]  # fmt: skip
            free = sheets[layer]
            if there:
                free = free.difference(unary_union([shape for _, shape in there]))
            self.sheets.append(_Sheet(layer, free, [(-1 - self.root(i), shape)
                                                    for i, shape in there], step, rng))  # fmt: skip
        self.ways: dict[int, list] | None = None  # the flow's network, once made
        self.sides: list[tuple[int, int, int]] = []

    def root(self, i: int) -> int:
        while self.group[i] != i:
            self.group[i] = self.group[self.group[i]]
            i = self.group[i]
        return i

    def network(self) -> dict[int, list]:
        """The sheets as a network for flow: a node a triangle, and one each piece of
        pads and vias (numbered below nought); between two triangles, and between a
        triangle and the pad its side is a face of, a way that lets through the
        side's length. Less of it, and the same between pads: a dead end is taken off,
        and two ways that meet at a triangle nothing else is on are one, as wide as
        the narrower. Each way: its two nodes, its width and the side it is."""
        ways: dict[int, list] = {}
        at: dict[int, set[int]] = {}
        self.sides = []
        base = 0
        for n, sheet in enumerate(self.sheets):
            xy = sheet.xy
            tri: dict[tuple[int, int, int], int] = {}
            for (u, v), wings in sheet.wings.items():
                nodes = []
                for o in wings:
                    corners = (u, v, o) if o > v else (u, o, v) if o > u else (o, u, v)
                    nodes.append(tri.setdefault(corners, base + len(tri)))
                if len(nodes) == 1:
                    if (u, v) not in sheet.face:
                        continue
                    nodes.append(sheet.face[(u, v)])
                ways[len(ways)] = [nodes[0], nodes[1], math.dist(xy[u], xy[v]), len(self.sides)]
                self.sides.append((n, u, v))
            base += len(tri)
        for w, (a, b, _, _) in ways.items():
            at.setdefault(a, set()).add(w)
            at.setdefault(b, set()).add(w)
        count, spare = len(ways), [x for x in at if x >= 0]
        while spare:
            x = spare.pop()
            if x < 0 or len(at.get(x, ())) not in (1, 2):
                continue
            gone = at.pop(x)
            over = [ways.pop(w) for w in gone]
            far = [a if b == x else b for a, b, *_ in over]
            for y in far:
                at[y] -= gone
            if len(far) == 2 and far[0] != far[1]:
                narrow = min(over, key=lambda way: way[2])
                ways[count] = [far[0], far[1], narrow[2], narrow[3]]
                for y in far:
                    at[y].add(count)
                count += 1
            spare += far
        return ways

    def flow(self, one: set[int], two: set[int]) -> tuple[int, list[tuple[int, int, int]]]:
        """The most that flows from the nodes *one* to the nodes *two*, in nanometres
        of width, and the sides of the cut that stops it nearest *one*."""
        assert self.ways is not None
        index: dict[int | str, int] = {}
        head: list[list[int]] = []
        to: list[int] = []
        room: list[int] = []
        side: list[int] = []

        def node(x: int) -> int:
            name = "one" if x in one else "two" if x in two else x
            if name not in index:
                index[name] = len(head)
                head.append([])
            return index[name]

        for a, b, wide, s in self.ways.values():
            a, b = node(a), node(b)
            if a != b:
                for x, y in ((a, b), (b, a)):  # an arc and, next after it, the one back
                    head[x].append(len(to))
                    to.append(y)
                    room.append(round(wide * 1_000_000))
                    side.append(s)
        if "one" not in index or "two" not in index:
            return 0, []
        first, last = index["one"], index["two"]
        total = 0
        while True:
            # How far each node is from the first, by ways with room left; then every
            # way to the last that goes one further each step is filled.
            far = [-1] * len(head)
            far[first] = 0
            queue = deque([first])
            while queue:
                x = queue.popleft()
                for arc in head[x]:
                    if room[arc] > 0 and far[to[arc]] < 0:
                        far[to[arc]] = far[x] + 1
                        queue.append(to[arc])
            if far[last] < 0:
                break
            tried = [0] * len(head)
            while True:
                way: list[int] = []
                x = first
                while x != last:
                    arcs = head[x]
                    while tried[x] < len(arcs) and not (
                        room[arcs[tried[x]]] > 0 and far[to[arcs[tried[x]]]] == far[x] + 1
                    ):
                        tried[x] += 1
                    if tried[x] < len(arcs):
                        way.append(arcs[tried[x]])
                        x = to[way[-1]]
                    elif way:
                        far[x] = -1
                        x = to[way.pop() ^ 1]
                        tried[x] += 1
                    else:
                        break
                if x != last:
                    break
                push = min(room[arc] for arc in way)
                for arc in way:
                    room[arc] -= push
                    room[arc ^ 1] += push
                total += push
        cut = [self.sides[side[arc]] for x in range(len(head)) if far[x] >= 0
               for arc in head[x] if far[to[arc]] < 0]  # fmt: skip
        return total, cut

    def cut(self, one: Sequence[int], two: Sequence[int]
            ) -> tuple[int, list[list[tuple[str, tuple[float, float], tuple[float, float],
                                            int | None]]]] | None:  # fmt: skip
        """The neck between the lumps *one* and the lumps *two*: its width in
        nanometres and the pieces its cut is in, each the sides it is of as (layer,
        end, end, the lump it is a face of or None). None where the two are one
        piece."""
        first = {-1 - self.root(i) for i in one}
        last = {-1 - self.root(i) for i in two}
        if first & last:
            return None
        wide, cut, least = 0, [], math.inf
        for round_ in range(_ROUNDS):
            self.ways = self.ways or self.network()
            wide, cut = self.flow(first, last)
            # The shortest chords between walls no further apart than the neck is so
            # far: no chord of a narrower cut is longer.
            if round_ == 0 and sum(s.shortest(wide / 1_000_000) for s in self.sheets if wide):
                self.ways = self.network()
                wide, cut = self.flow(first, last)
            if wide > least - 1:
                break
            least = wide
            by: dict[int, list[tuple[int, int]]] = {}
            for n, u, v in cut:
                by.setdefault(n, []).append((u, v))
            if not sum(self.sheets[n].taut(sides) for n, sides in by.items()):
                break
            self.ways = None
        # The pieces: sides of the cut that share a corner are one piece.
        at: dict[tuple[int, int], tuple[int, int]] = {}

        def piece(x: tuple[int, int]) -> tuple[int, int]:
            while at.setdefault(x, x) != x:
                at[x] = at[at[x]]
                x = at[x]
            return x

        for n, u, v in cut:
            at[piece((n, u))] = piece((n, v))
        pieces: dict[tuple[int, int], list] = {}
        for n, u, v in cut:
            sheet = self.sheets[n]
            lump = sheet.face.get(_key(u, v))
            side = (sheet.layer, sheet.xy[u], sheet.xy[v], None if lump is None else -1 - lump)
            pieces.setdefault(piece((n, u)), []).append(side)
        return wide, list(pieces.values())


def _whole(piece: Polygon) -> list[Polygon]:
    """A piece of KiCad's fill, written as one outline that reaches each of its holes
    by a slit, as the areas of copper it is."""
    made = shapely.make_valid(piece)
    return [p for p in getattr(made, "geoms", [made]) if isinstance(p, Polygon) and not p.is_empty]


class Necks:
    """The necks of a board's *items*, net by net. *fill* is what ``pkidl.fill.fills``
    takes after the items, the outline to fill inside, how far from it and the nets'
    clearances: where it is given, a zone the board has no fill of is measured on
    pkidl's model of its fill, and where it is not, such a zone is no copper."""

    def __init__(self, items: list[Node], fill: tuple | None = None, step: float = STEP) -> None:
        self.items, self.fill, self.step = items, fill, step
        self.nets: dict[str, tuple[_Copper, dict[str, list[int]], str,
                                   Callable[..., str]]] = {}  # fmt: skip
        self.model: list[tuple[str, str, Polygon]] | None = None

    def _net(self, net: str) -> tuple[_Copper, dict[str, list[int]], str, Callable[..., str]]:
        items = self.items
        nodes, of, vias = _on(items, net)
        zones = [z for z in _pours(items) if _net(z) == net]
        copper: dict[str, list[BaseGeometry]] = {}
        for _, shapes in nodes:
            for layer, shape in shapes.items():
                copper.setdefault(layer, []).append(shape)
        poured: dict[str, list[BaseGeometry]] = {}
        said = set()
        for zone in zones:
            for layer, piece in filled(zone):
                poured.setdefault(layer, []).extend(_whole(piece))
                said.add(KICAD)
        bare = [z for z in zones if not find_all(z, "filled_polygon")]
        if bare and self.fill is not None:
            if self.model is None:
                self.model = fills(items, *self.fill)

            def zone_of(layer: str, piece: Polygon) -> Node:  # as ``pkidl.fill._parts`` has it
                on = [z for z in zones if layer in _layers(z)]
                at = piece.representative_point()
                return next((z for z in on if _outline(z).contains(at)), on[0])

            pieces = [(n, layer, piece) for n, layer, piece in self.model
                      if n == net and any(zone_of(layer, piece) is z for z in bare)]  # fmt: skip
            parts, whole = _parts(zones, pieces, net, nodes, of)
            for (layer, part), (zone, uncut) in zip(parts, whole, strict=True):
                poured.setdefault(layer, []).append(part)
                said.add(MODEL)
                near = part.buffer(0.001)
                # Each spoke that has its copper, as ``pkidl.fill._joined`` counts one.
                for i, (fp, pad) in of.items():
                    if layer in nodes[i][1] and _relief(zone, fp, pad) == "thermal":
                        shape = nodes[i][1][layer]
                        ring = shape.buffer(_gap(zone, pad))
                        poured[layer] += [
                            s.intersection(ring) for s in _spokes(fp, pad, zone)
                            if uncut.covers(s.intersection(ring).difference(shape))
                            and near.covers(s.difference(ring))
                        ]  # fmt: skip
        layers = sorted({*copper, *poured})
        # A via, and a pad with a hole, has its copper on every layer of the net's.
        lumps, named = [], {}
        for i in sorted({*of, *vias}):
            name, shapes = nodes[i]
            through = i in vias or str(of[i][1][2]) == "thru_hole"
            shape = next(iter(shapes.values()))
            if i in of:
                named.setdefault(name, []).append(len(lumps))
            lumps.append(_Lump(name, dict.fromkeys(layers, shape) if through else shapes))
        for lump in lumps:
            for layer, shape in lump.copper.items():
                copper.setdefault(layer, []).append(shape)
        sheets = {layer: unary_union(copper.get(layer, []) + poured.get(layer, []))
                  for layer in layers}  # fmt: skip
        # What a piece of a cut is of.
        tracks = {layer: unary_union([shapes[layer].buffer(_FACE) for n, (_, shapes)
                                      in enumerate(nodes)
                                      if n not in of and n not in vias and layer in shapes])
                  for layer in layers}  # fmt: skip
        reliefs = [(layer, nodes[i][0], nodes[i][1][layer].buffer(_gap(zone, of[i][1]) + 0.01))
                   for i in of for zone in zones for layer in _layers(zone)
                   if layer in nodes[i][1] and _relief(zone, *of[i]) == "thermal"
                   and _outline(zone).intersects(nodes[i][1][layer])]  # fmt: skip

        def what(layer: str, middles: Sequence[tuple[float, float]],
                 faces: dict[int, float], long: float) -> str:  # fmt: skip
            """What a piece of a cut on *layer* is of: the *middles* of its sides,
            how much of it is *faces* of each pad or via, and how *long* it is."""
            most = max(faces, key=lambda lump: faces[lump], default=None)
            round_ = "" if most is None else f"the copper round {lumps[most].name or 'a via'}"
            # Round a pad or a via where it is most of the way round that one.
            if most is not None and 2 * faces[most] > lumps[most].copper[layer].length:
                return round_
            if all(tracks[layer].covers(SPoint(middle)) for middle in middles):
                return "track"
            for on, name, ring in reliefs:
                if on == layer and ring.covers(SPoint(middles[0])):
                    return f"the relief of {name}"
            if most is not None and 2 * faces[most] > long:
                return round_
            return "pour" if poured.get(layer) else "copper"

        return (_Copper(sheets, lumps, self.step), named,
                " and ".join(sorted(said)), what)  # fmt: skip

    def between(self, net: str, one: Sequence[str], two: Sequence[str]) -> Neck | None:
        """The neck of *net* between the pads *one* and the pads *two*, each as
        ``C5.1``: None where the two are one piece of copper."""
        if net not in self.nets:
            self.nets[net] = self._net(net)
        copper, named, said, what = self.nets[net]
        found = copper.cut([i for name in one for i in named.get(name, ())],
                           [i for name in two for i in named.get(name, ())])  # fmt: skip
        if found is None:
            return None
        wide, pieces = found
        across = []
        for sides in pieces:
            sides.sort(key=lambda side: -math.dist(side[1], side[2]))
            layer = sides[0][0]
            middles = [((a[0] + b[0]) / 2, (a[1] + b[1]) / 2) for _, a, b, _ in sides]
            long = sum(math.dist(a, b) for _, a, b, _ in sides)
            faces: dict[int, float] = {}
            for _, a, b, lump in sides:
                if lump is not None:
                    faces[lump] = faces.get(lump, 0.0) + math.dist(a, b)
            # Where it is: the middle of its sides, each by its length, which for a
            # cut straight across is half way over and for one round a pad is the pad.
            x, y = (sum(middle[k] * math.dist(a, b) for middle, (_, a, b, _)
                        in zip(middles, sides, strict=True)) / long for k in (0, 1))  # fmt: skip
            across.append(Piece(
                Length(round(long * 1000) * 1000),
                (Length(round(x * 1000) * 1000), Length(round(y * 1000) * 1000)),
                layer, what(layer, middles, faces, long)))  # fmt: skip
        across.sort(key=lambda piece: (-piece.width.nm, piece.layer, piece.at))
        return Neck(Length(round(wide / 1000) * 1000), tuple(across), said)
