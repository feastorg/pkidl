"""Paths, measured: what the copper a current is said to go through comes to.

``path(jack, switch, regulator, current=1 * A)`` says the way a current goes, and a
build that routes the board measures each stretch of it on the board that is written:
its tracks and vias as they are. Nothing is changed for what is found, and nothing
found is a problem: ``Routed.paths`` has it. A measurement never stops a build: one
that raises is a reading that says so (``Reading.failed``).

A stretch is one net between two ends, each end every pad its part has on the net,
taken as one point. Its resistance is that of the net's tracks between them, as a
network: a track of length L and width w is ρ·L/(w·t), with ρ of copper at 20 °C and t
the thickness the board's ``rules`` give its copper, and tracks in parallel count as in
parallel. A via joins its two layers and a pad everything joined to it, each with no
resistance of its own.

A track is where its middle line is, and is as long as that line; one no longer than a
tenth of a micrometre is no copper. Two points of a layer are one place where they are
no more than a tenth of a micrometre apart, and so are two that are each one place with
a third. A line passes through a point where it is no further than that from it, and
its point nearest is then one place with that one. What joins:

1. Two tracks of one layer, where an end of each is at one place.
2. An end of a track to another track of its layer part way along it: where the point
   of that track's middle line nearest the end is more than a tenth of a micrometre
   from each of that track's ends, and the end is no further from that point than
   half that track's width. They are joined at that point.
3. Two tracks of one layer whose middle lines cross, where they cross, if that is
   more than a tenth of a micrometre from each end of both.
4. A track to a pad or a via with copper on its layer, where the track's middle line
   touches that copper: at the point of the line within the copper nearest the pad's
   own place, which is where its hole is, or its middle where it has none, and for a
   via its middle. Where pieces of track that lie within the copper join several such
   points to each other, the pad is joined to the nearest of them alone, so a track
   that comes into a pad in pieces counts as far as the one track would.
5. A pad or a via to another pad or via, where the copper of the two touches on a
   layer both have copper on.

Every track is cut at each end of a track of its layer, and at each point of 2, 3 and
4 on its layer, that its middle line passes through, and is joined there to every other
track cut there. Nothing else joins: not two ends
near each other that are not at one place, not an end beside the end of another track,
and not a track whose copper reaches a pad, a via or another track that its middle line
stays off.

Copper laid twice is one strip: of the pieces of track on one layer between the same
two places, the widest is the piece. Tracks side by side that are not on one line are
two, however near.

The length and the narrowest width are of the way of least resistance between the
ends, and the drop is the resistance times the path's whole current, parts side by side
being one end. Ends that are one piece of copper, with no track between them, are
joined, at nothing.

A pour is not measured, and neither is what it reaches. Ends that no track joins have
no figure, and where their net has a pour that is said, since the pour may join them.
Where tracks join them and the net has a pour as well, the figure is at most what the
stretch is. What a part is between its own pads is not counted.
"""

from __future__ import annotations

import heapq
import math
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

import numpy as np
import shapely
from shapely.geometry import Point as SPoint
from shapely.ops import nearest_points

from pkidl.circuit import Circuit
from pkidl.fill import _layers, _net, _num, _on, _pours, _xy
from pkidl.footprint import pad_at
from pkidl.intent import Path, Stretch
from pkidl.sexpr import Node
from pkidl.units import Length

RHO = 1.72e-8  # ohm metres: copper at 20 °C
_NEAR = 1e-6  # millimetres: a point this near copper is within it
# Millimetres: two points no further apart are one place, and a track no longer is no
# copper. A router's file is in tenths of a micrometre, and two points of it one tenth
# apart are that far apart here to within the arithmetic, which the picometre is for.
_SAME = 1e-4 + 1e-9


@dataclass(frozen=True)
class Reading:
    """One stretch of a path as the routed board has it: the resistance of its tracks
    in ohms, the length and the narrowest width of the way of least resistance through
    them, and the drop in volts at the path's current. None of each where no track
    joins its ends, and no width where its ends are one piece of copper with no track
    between. *poured* is whether its net has a pour on the board: a pour is not
    measured, and where it reaches is not looked at. *failed* is why it could not be
    measured, where measuring it raised."""

    stretch: Stretch
    ohms: float | None = None
    length: Length | None = None
    narrowest: Length | None = None
    volts: float | None = None
    poured: bool = False
    failed: str = ""

    def __str__(self) -> str:
        net = self.stretch.net
        if self.failed:
            return f"{self.stretch}: could not be measured: {self.failed}"
        if self.ohms is None or self.volts is None or self.length is None:
            pour = f"; {net} has a pour, which is not measured" if self.poured else ""
            return f"{self.stretch}: not joined by track{pour}"
        figures = f"{_figure(self.ohms, 'Ω')}, {_figure(self.volts, 'V')}"
        if self.narrowest is None:
            return f"{self.stretch}: joined at one place, with no track between: {figures}"
        most, pour = "", ""
        if self.poured:
            most, pour = "at most ", f": {net} has a pour as well, which is not measured"
        return (f"{self.stretch}: {round(self.length.mm, 1):g} mm of track, {self.narrowest} "
                f"at its narrowest, {most}{figures}{pour}")  # fmt: skip


@dataclass(frozen=True)
class Measured:
    """A path as the routed board has it: each of its stretches, in order."""

    path: Path
    stretches: tuple[Reading, ...]

    @property
    def ohms(self) -> float | None:
        """The resistance of the stretches that are measured, together: None where
        none is."""
        found = [r.ohms for r in self.stretches if r.ohms is not None]
        return sum(found) if found else None

    @property
    def volts(self) -> float | None:
        """The drop over them at the path's current."""
        return None if self.ohms is None else self.ohms * self.path.current.a

    @property
    def unmeasured(self) -> int:
        """How many of its stretches have no figure."""
        return sum(r.ohms is None for r in self.stretches)

    def __str__(self) -> str:
        at = f" ({self.path.source})" if self.path.source else ""
        ohms, volts = self.ohms, self.volts
        if ohms is None or volts is None:
            total = f"no figure: none of its {len(self.stretches)} stretches is measured"
        else:
            most = "at most " if any(r.poured for r in self.stretches if r.ohms is not None) else ""
            total = (f"{most}{_figure(ohms, 'Ω')} of track, {_figure(volts, 'V')} at "
                     f"{self.path.current}")  # fmt: skip
            if self.unmeasured:
                total += f", {self.unmeasured} of its {len(self.stretches)} stretches not in it"
        return "\n".join([f"{self.path}{at}: {total}", *(f"  {r}" for r in self.stretches)])


def _figure(value: float, unit: str) -> str:
    """A resistance or a drop to three figures, written out with no exponent: in
    thousandths of its unit where that is under a thousand of them, in ones where
    that is, and in thousands of it otherwise. What is no number is refused:
    ``measured`` makes a reading of nothing else."""
    if not math.isfinite(value):
        raise ValueError(f"{value} is not a figure")
    for scale, prefix in ((1e-3, "m"), (1.0, "")):
        if (shown := float(f"{value / scale:.3g}")) < 1000:
            return f"{_plain(shown)} {prefix}{unit}"
    return f"{_plain(float(f'{value / 1000:.3g}'))} k{unit}"


def _plain(shown: float) -> str:
    return f"{Decimal(repr(shown)).normalize():f}"


@dataclass(frozen=True)
class _Tracks:
    """The tracks of one net as resistors: each piece of track between two places
    something joins it, as (node, node, length, width) in millimetres; which node each
    pad is, by its name, a name once for each pad that has it; and the node a node is
    one with."""

    pieces: list[tuple[int, int, float, float]]
    pads: dict[str, list[int]]
    group: list[int]

    def root(self, i: int) -> int:
        while self.group[i] != i:
            self.group[i] = self.group[self.group[i]]
            i = self.group[i]
        return i

    def join(self, one: int, two: int) -> None:
        self.group[self.root(one)] = self.root(two)


def _tracks(items: list[Node], net: str) -> _Tracks:
    """The tracks of *net* among a board's *items* as resistors (see the module)."""
    nodes, of, vias = _on(items, net)
    group = list(range(len(nodes)))  # a pad or a via is a node; a track's are made below
    found = _Tracks([], {}, group)
    for i in of:
        found.pads.setdefault(nodes[i][0], []).append(i)
    # Each pad and via: its node, its own place and its copper on each layer.
    lumps = [(i, SPoint(pad_at(*of[i])) if i in of else next(iter(nodes[i][1].values())).centroid,
              nodes[i][1]) for i in sorted({*of, *vias})]  # fmt: skip
    # Two of them are joined where their copper touches on a layer both have.
    for layer in sorted({layer for _, _, copper in lumps for layer in copper}):
        there = [(i, copper[layer]) for i, _, copper in lumps if layer in copper]
        shapes = np.array([shape for _, shape in there])
        for n, (i, shape) in enumerate(there):
            for m in np.flatnonzero(shapely.distance(shapes[n + 1 :], shape) <= _NEAR):
                found.join(there[n + 1 + m][0], i)
    segments = [(a, b, wide, layer)
                for a, b, wide, layer in (
                    (_xy(item, "start"), _xy(item, "end"), _num(item, "width"), _layers(item)[0])
                    for item in items if str(item[0]) == "segment" and _net(item) == net)
                if math.dist(a, b) > _SAME]  # fmt: skip
    if not segments:
        return found
    # The places: each point looked up is one with every point looked up before it
    # that is no further from it than a place is wide.
    cells: dict[tuple[str, int, int], list[tuple[float, float, int]]] = {}

    def node(layer: str, x: float, y: float) -> int:
        cx, cy = math.floor(x / _SAME), math.floor(y / _SAME)
        near = [(math.hypot(px - x, py - y), n)
                for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                for px, py, n in cells.get((layer, cx + dx, cy + dy), ())]  # fmt: skip
        near = [(off, n) for off, n in near if off <= _SAME]
        if not near:
            group.append(len(group))
            near = [(1.0, len(group) - 1)]
        for _, other in near[1:]:
            found.join(other, near[0][1])
        if min(off for off, _ in near) > 0:
            cells.setdefault((layer, cx, cy), []).append((x, y, near[0][1]))
        return near[0][1]

    layers = np.array([layer for *_, layer in segments])
    lines = shapely.linestrings([[a, b] for a, b, *_ in segments])
    # Every point where something joins a track, by layer, and what is joined there
    # that is not on the track: an end beside it, as (the end, the point).
    points: dict[str, list[tuple[float, float]]] = {}
    beside: list[tuple[tuple[float, float], str, float, float]] = []
    for layer in sorted(set(layers)):
        on = np.flatnonzero(layers == layer)
        start = np.array([segments[k][0] for k in on])
        along = np.array([segments[k][1] for k in on]) - start
        wide = np.array([segments[k][2] for k in on])
        long = np.hypot(along[:, 0], along[:, 1])
        ends = np.concatenate([start, start + along])
        here = points.setdefault(layer, [(float(x), float(y)) for x, y in ends])
        for n in range(len(on)):
            ux, uy = along[n] / long[n]
            # Each end on the layer: how far along this track the nearest point of its
            # middle line is, and how far off that line the end is.
            off = ends - start[n]
            far = off[:, 0] * ux + off[:, 1] * uy
            aside = np.abs(off[:, 0] * uy - off[:, 1] * ux)
            between = (far > _SAME) & (far < long[n] - _SAME)
            for m in np.flatnonzero(between & (aside <= wide[n] / 2 + _NEAR)):
                x, y = (float(v) for v in start[n] + far[m] * np.array([ux, uy]))
                here.append((x, y))
                beside.append(((float(ends[m][0]), float(ends[m][1])), layer, x, y))
            # Each later track on the layer: where the two middle lines cross, as how
            # far along this one and how far along that one.
            gap, theirs = start[n + 1 :] - start[n], along[n + 1 :]
            with np.errstate(divide="ignore", invalid="ignore"):
                turn = ux * theirs[:, 1] - uy * theirs[:, 0]
                mine = (gap[:, 0] * theirs[:, 1] - gap[:, 1] * theirs[:, 0]) / turn
                reach = (gap[:, 0] * uy - gap[:, 1] * ux) / turn * long[n + 1 :]
                cross = ((mine > _SAME) & (mine < long[n] - _SAME)
                         & (reach > _SAME) & (reach < long[n + 1 :] - _SAME))  # fmt: skip
            for m in np.flatnonzero(cross):
                x, y = (float(v) for v in start[n] + mine[m] * np.array([ux, uy]))
                here.append((x, y))
    # A pad or a via: for each track whose middle line is within its copper, the point
    # of the line there nearest the pad's own place.
    for _, place, copper in lumps:
        for layer, shape in copper.items():
            for k in np.flatnonzero((layers == layer) & shapely.intersects(lines, shape)):
                point = nearest_points(shapely.intersection(lines[k], shape), place)[0]
                points[layer].append((point.x, point.y))
    # Every track is cut at each of those points its middle line passes through: at
    # the point of the line nearest it, which is one place with it. Each cut is how
    # far along the track it is, its node and where it is.
    cuts: list[list[tuple[float, int, float, float]]] = []
    every = {layer: np.array(here) for layer, here in points.items()}
    for a, b, _, layer in segments:
        spots = every[layer]
        length = math.dist(a, b)
        ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
        off = spots - np.array(a)
        far = np.clip(off[:, 0] * ux + off[:, 1] * uy, 0.0, length)
        away = np.hypot(off[:, 0] - far * ux, off[:, 1] - far * uy)
        cut = []
        for m in np.flatnonzero(away <= _SAME):
            x, y = a[0] + float(far[m]) * ux, a[1] + float(far[m]) * uy
            cut.append((float(far[m]), node(layer, x, y), x, y))
        cuts.append(sorted(cut))
    ends = [(node(layer, ex, ey), node(layer, x, y)) for (ex, ey), layer, x, y in beside]
    # The pieces between the cuts, each between two places, so none is of no length.
    # Copper laid twice is one strip: of the pieces on a layer between the same two
    # places, the widest.
    marks: list[tuple[int, str, float, float]] = []  # each cut: its node, layer and place
    whole: list[tuple[int, int]] = []  # each piece, as its two cuts among those
    laid: dict[tuple[str, frozenset[int]], tuple[int, int, float, float]] = {}
    for (_, _, wide, layer), cut in zip(segments, cuts, strict=True):
        first = len(marks)
        marks += [(n, layer, x, y) for _, n, x, y in cut]
        for m, ((at0, one, *_), (at1, two, *_)) in enumerate(
            zip(cut, cut[1:], strict=False), first
        ):
            if found.root(one) == found.root(two):
                continue
            whole.append((m, m + 1))
            key = (layer, frozenset((found.root(one), found.root(two))))
            if key not in laid or laid[key][3] < wide:
                laid[key] = (one, two, at1 - at0, wide)
    found.pieces.extend(laid.values())
    for one, two in ends:
        found.join(one, two)
    # A pad or a via is joined to the track within its copper at one place: of the cuts
    # within it that pieces of track within it join to each other, the nearest its own.
    was = [found.root(n) for n, *_ in marks]
    where = shapely.points([(x, y) for _, _, x, y in marks])
    on = np.array([layer for _, layer, _, _ in marks])
    joins = []
    for i, place, copper in lumps:
        for layer, shape in copper.items():
            within = (on == layer) & (shapely.distance(where, shape) <= _NEAR)
            together = {was[m]: was[m] for m in np.flatnonzero(within)}

            def head(x: int, together: dict[int, int] = together) -> int:
                while together[x] != x:
                    x = together[x]
                return x

            for one, two in whole:
                if within[one] and within[two]:
                    together[head(was[one])] = head(was[two])
            off = shapely.distance(where, place)
            nearest: dict[int, int] = {}
            for m in np.flatnonzero(within):
                if (h := head(was[m])) not in nearest or off[m] < off[nearest[h]]:
                    nearest[h] = int(m)
            joins += [(marks[m][0], i) for m in nearest.values()]
    for one, two in joins:
        found.join(one, two)
    return found


def _between(
    tracks: _Tracks, one: Sequence[int], two: Sequence[int], thick: float
) -> tuple[float, float, float] | None:
    """What the tracks are between two ends, each the nodes of its pads taken as one
    point: the resistance in ohms with copper *thick* millimetres thick, and the
    length and the narrowest width, in millimetres, of the way of least resistance.
    Nothing of each where the ends are one piece of copper with no track between
    them. None where the tracks do not join them."""
    first, last = -1, -2  # the two ends, each as one node
    if {tracks.root(i) for i in one} & {tracks.root(i) for i in two}:
        return 0.0, 0.0, 0.0
    ends = {tracks.root(i): first for i in one} | {tracks.root(i): last for i in two}
    # Each resistor as (node, node, ohms, length, narrowest width), and at each node
    # the resistors that end there.
    ways: dict[int, tuple[int, int, float, float, float]] = {}
    at: dict[int, set[int]] = {}
    for a, b, long, wide in tracks.pieces:
        a, b = (ends.get(r, r) for r in (tracks.root(a), tracks.root(b)))
        if a != b:
            at.setdefault(a, set()).add(len(ways))
            at.setdefault(b, set()).add(len(ways))
            ways[len(ways)] = (a, b, RHO * (long / 1000) / ((wide / 1000) * (thick / 1000)),
                               long, wide)  # fmt: skip
    # Less of it, and the same between the ends: a dead end carries nothing and is
    # taken off, and two resistors that meet at a node nothing else is on are one.
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
            (_, _, r0, long0, wide0), (_, _, r1, long1, wide1) = over
            ways[count] = (far[0], far[1], r0 + r1, long0 + long1, min(wide0, wide1))
            for y in far:
                at[y].add(count)
            count += 1
        spare += far
    # The way of least resistance from the first end, to everything it reaches.
    best: dict[int, tuple[float, float, float]] = {}
    queue: list[tuple[float, float, float, int]] = [(0.0, 0.0, math.inf, first)]
    while queue:
        r, long, narrow, here = heapq.heappop(queue)
        if here in best:
            continue
        best[here] = (r, long, narrow)
        for a, b, more, further, wide in (ways[w] for w in at.get(here, ())):
            to = a if b == here else b
            if to not in best:
                heapq.heappush(queue, (r + more, long + further, min(narrow, wide), to))
    if last not in best:
        return None
    # The resistance of the network between the ends: one amp in at the first and out
    # at the last, which is held at nought, and the first end's voltage is the ohms.
    index = {x: n for n, x in enumerate(x for x in best if x != last)}
    g = np.zeros((len(index), len(index)))
    for x in index:
        for a, b, r, _, _ in (ways[w] for w in at[x]):
            g[index[x], index[x]] += 1 / r
            if (to := a if b == x else b) != last:
                g[index[x], index[to]] -= 1 / r
    amps = np.zeros(len(index))
    amps[index[first]] = 1.0
    return float(np.linalg.solve(g, amps)[index[first]]), best[last][1], best[last][2]


def measured(
    items: list[Node], paths: Sequence[Path], circuit: Circuit, copper: Length
) -> tuple[Measured, ...]:
    """Each of *paths* as a routed board's *items* have it (see the module), their
    stretches found in *circuit* and the board's copper *copper* thick. It does not
    raise for what the board is: a stretch whose measuring raises has a reading that
    says what was raised."""
    poured = {_net(zone) for zone in _pours(items)}
    nets: dict[str, _Tracks] = {}

    def read(stretch: Stretch, amps: float) -> Reading:
        net = stretch.net.name
        if net not in nets:
            nets[net] = _tracks(items, net)
        one, two = ([i for pin in end for i in nets[net].pads.get(str(pin), ())]
                    for end in stretch.ends)  # fmt: skip
        between = _between(nets[net], one, two, copper.mm)
        if between is None:
            return Reading(stretch, poured=net in poured)
        ohms, long, narrow = between
        if not all(math.isfinite(v) for v in between):
            raise ArithmeticError(f"its resistance comes out as {ohms:g}")
        return Reading(stretch, ohms, Length(round(long * 1_000_000)),
                       Length(round(narrow * 1_000_000)) if long else None,
                       ohms * amps, net in poured)  # fmt: skip

    found = []
    for path in paths:
        readings = []
        for stretch in path.stretches(circuit)[0]:
            try:
                readings.append(read(stretch, path.current.a))
            except Exception as e:  # whatever it is, the board is still written
                readings.append(Reading(stretch, poured=stretch.net.name in poured,
                                        failed=f"{type(e).__name__}: {e}"))  # fmt: skip
        found.append(Measured(path, tuple(readings)))
    return tuple(found)
