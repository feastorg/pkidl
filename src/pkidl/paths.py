"""Paths, measured: what the copper a current is said to go through comes to.

``path(jack, switch, regulator, current=1 * A)`` says the way a current goes, and a
build that routes the board measures each stretch of it on the board that is written:
its tracks and vias as they are. Nothing is changed for what is found, and nothing
found is a problem: ``Routed.paths`` has it.

A stretch is one net between two ends, each end every pad its part has on the net,
taken as one point. Its resistance is that of the net's tracks between them, as a
network: a track of length L and width w is ρ·L/(w·t), with ρ of copper at 20 °C and t
the thickness the board's ``rules`` give its copper, and tracks in parallel count as in
parallel. A via joins its two layers and a pad everything joined to it, each with no
resistance of its own.

A track is where its middle line is, and is as long as that line. What joins:

- two tracks of one layer whose ends are at one place, to a tenth of a micrometre;
- an end of a track to another track of its layer part way along: where the nearest
  point of that track's middle line to the end is between its ends, and the end is
  within its copper, half its width from that line. The track is split there;
- two tracks of one layer whose middle lines cross: both are split where they cross;
- a track to a pad or a via with copper on its layer, where the track's middle line
  is within that copper: at the point of the line there nearest the pad's own place,
  its hole's where it has one, or the via's. The track is split there. Tracks joined
  to each other within the copper are joined to it once, at the nearest such point of
  them all, so a track that comes into a pad in pieces counts as far as the one track
  would.

Nothing else does: not two ends near each other that are not at one place, and not a
track whose copper reaches a pad or another track that its middle line stays off.

Copper laid twice is one strip: of the pieces of track on one layer between the same
two places, the widest is the piece.

The length and the narrowest width are of the way of least resistance between the
ends, and the drop is the resistance times the path's whole current, parts side by side
being one end.

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
_SAME = 1e-4  # millimetres: two points this near are one place, and no track is shorter


@dataclass(frozen=True)
class Reading:
    """One stretch of a path as the routed board has it: the resistance of its tracks
    in ohms, the length and the narrowest width of the way of least resistance through
    them, and the drop in volts at the path's current. None of each where no track
    joins its ends. *poured* is whether its net has a pour on the board: a pour is not
    measured, and where it reaches is not looked at."""

    stretch: Stretch
    ohms: float | None = None
    length: Length | None = None
    narrowest: Length | None = None
    volts: float | None = None
    poured: bool = False

    def __str__(self) -> str:
        net = self.stretch.net
        if self.ohms is None or self.volts is None or self.length is None:
            pour = f"; {net} has a pour, which is not measured" if self.poured else ""
            return f"{self.stretch}: not joined by track{pour}"
        most, pour = "", ""
        if self.poured:
            most, pour = "at most ", f": {net} has a pour as well, which is not measured"
        return (f"{self.stretch}: {round(self.length.mm, 1):g} mm of track, {self.narrowest} "
                f"at its narrowest, {most}{_figure(self.ohms, 'Ω')}, {_figure(self.volts, 'V')}"
                f"{pour}")  # fmt: skip


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
        """How many of its stretches no track joins the ends of."""
        return sum(r.ohms is None for r in self.stretches)

    def __str__(self) -> str:
        at = f" ({self.path.source})" if self.path.source else ""
        ohms, volts = self.ohms, self.volts
        if ohms is None or volts is None:
            total = "not measured: no stretch of it is joined by track"
        else:
            most = "at most " if any(r.poured for r in self.stretches if r.ohms is not None) else ""
            total = (f"{most}{_figure(ohms, 'Ω')} of track, {_figure(volts, 'V')} at "
                     f"{self.path.current}")  # fmt: skip
            if self.unmeasured:
                total += f", {self.unmeasured} of its {len(self.stretches)} stretches not in it"
        return "\n".join([f"{self.path}{at}: {total}", *(f"  {r}" for r in self.stretches)])


def _figure(value: float, unit: str) -> str:
    """A resistance or a drop to three figures, in thousandths, ones or thousands of
    its unit, whichever leaves it under a thousand, and never with an exponent."""
    for scale, prefix in ((1e-3, "m"), (1.0, "")):
        if (shown := float(f"{value / scale:.3g}")) < 1000:
            return _plain(shown) + f" {prefix}{unit}"
    return _plain(float(f"{value / 1000:.3g}")) + f" k{unit}"


def _plain(shown: float) -> str:
    return f"{shown:.9f}".rstrip("0").rstrip(".")


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


def _tracks(items: list[Node], net: str) -> _Tracks:
    """The tracks of *net* among a board's *items* as resistors (see the module)."""
    nodes, of, vias = _on(items, net)
    group = list(range(len(nodes)))  # a pad or a via is a node; a track's are made below
    found = _Tracks([], {}, group)
    for i in of:
        found.pads.setdefault(nodes[i][0], []).append(i)
    segments = [(_xy(item, "start"), _xy(item, "end"), _num(item, "width"), _layers(item)[0])
                for item in items if str(item[0]) == "segment" and _net(item) == net]  # fmt: skip
    if not segments:
        return found
    places: dict[tuple[str, int, int], int] = {}

    def spot(layer: str, x: float, y: float) -> tuple[str, int, int]:
        return layer, round(x / _SAME), round(y / _SAME)

    def node(layer: str, x: float, y: float) -> int:
        """The node of a place on a layer: one place, one node."""
        key = spot(layer, x, y)
        if key not in places:
            places[key] = len(group)
            group.append(len(group))
        return places[key]

    # Where each track is cut, as how far along it and the node there: its two ends,
    # which are the nodes of their places, and after them whatever joins it between.
    cuts = [[(0.0, node(layer, *a)), (1.0, node(layer, *b))] for a, b, _, layer in segments]
    layers = np.array([layer for *_, layer in segments])
    for layer in sorted(set(layers)):
        on = np.flatnonzero(layers == layer)
        start = np.array([segments[k][0] for k in on])
        along = np.array([segments[k][1] for k in on]) - start
        wide = np.array([segments[k][2] for k in on])
        long = np.hypot(along[:, 0], along[:, 1])
        ends = np.concatenate([start, start + along])
        at = [cuts[k][0][1] for k in on] + [cuts[k][1][1] for k in on]
        for n, k in enumerate(on):
            if long[n] <= _SAME:
                continue
            ux, uy = along[n] / long[n]
            # Each end on the layer: how far along this track the nearest point of its
            # middle line is, and how far off that line the end is.
            off = ends - start[n]
            far = off[:, 0] * ux + off[:, 1] * uy
            aside = np.abs(off[:, 0] * uy - off[:, 1] * ux)
            between = (far > _SAME) & (far < long[n] - _SAME)
            for m in np.flatnonzero(between & (aside <= wide[n] / 2 + _NEAR)):
                cuts[k].append((far[m] / long[n], at[m]))
            # Each later track on the layer: where the two middle lines cross, as how
            # far along this one and what share of the way along that one.
            gap, theirs = start[n + 1 :] - start[n], along[n + 1 :]
            with np.errstate(divide="ignore", invalid="ignore"):
                turn = ux * theirs[:, 1] - uy * theirs[:, 0]
                mine = (gap[:, 0] * theirs[:, 1] - gap[:, 1] * theirs[:, 0]) / turn
                share = (gap[:, 0] * uy - gap[:, 1] * ux) / turn
                reach = share * long[n + 1 :]
                cross = ((mine > _SAME) & (mine < long[n] - _SAME)
                         & (reach > _SAME) & (reach < long[n + 1 :] - _SAME))  # fmt: skip
            for m in np.flatnonzero(cross):
                x, y = start[n] + mine[m] * np.array([ux, uy])
                here = node(layer, float(x), float(y))
                cuts[k].append((mine[m] / long[n], here))
                cuts[on[n + 1 + m]].append((share[m], here))
    # A pad or a via: each track whose middle line is within its copper is cut at the
    # point of it there nearest the pad's own place.
    lines = shapely.linestrings([[a, b] for a, b, *_ in segments])
    lumps = []
    for i in sorted({*of, *vias}):
        middle = SPoint(pad_at(*of[i])) if i in of else next(iter(nodes[i][1].values())).centroid
        for layer, copper in nodes[i][1].items():
            lumps.append((i, layer, copper, middle))
            for k in np.flatnonzero((layers == layer) & shapely.intersects(lines, copper)):
                inside = shapely.intersection(lines[k], copper)
                point = nearest_points(inside, middle)[0]
                share = float(shapely.line_locate_point(lines[k], point, normalized=True))
                cuts[k].append((share, node(layer, point.x, point.y)))
    # The pieces between the cuts. Copper laid twice is one strip: of the pieces on a
    # layer between the same two places, the widest.
    laid: dict[tuple[str, frozenset[tuple[str, int, int]]], tuple[int, int, float, float]] = {}
    marks: list[tuple[int, str, float, float]] = []  # each cut: its node, layer and place
    whole: list[tuple[int, int]] = []  # each piece, as its two cuts among those
    for (a, b, wide, layer), cut in zip(segments, cuts, strict=True):
        cut.sort()
        length = math.dist(a, b)
        first = len(marks)
        marks += [(n, layer, a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])) for t, n in cut]
        for m, ((t0, one), (t1, two)) in enumerate(zip(cut, cut[1:], strict=False), first):
            if (t1 - t0) * length <= _SAME:
                group[found.root(two)] = found.root(one)
                continue
            whole.append((m, m + 1))
            key = (layer, frozenset(spot(layer, x, y) for _, _, x, y in marks[m : m + 2]))
            if key not in laid or laid[key][3] < wide:
                laid[key] = (one, two, (t1 - t0) * length, wide)
    found.pieces.extend(laid.values())
    # A pad or a via is joined to the track within its copper at one place: of the cuts
    # within it that pieces of track within it join to each other, the nearest its own.
    was = [found.root(n) for n, *_ in marks]
    spots = shapely.points([(x, y) for _, _, x, y in marks])
    on = np.array([layer for _, layer, _, _ in marks])
    for i, layer, copper, middle in lumps:
        within = (on == layer) & (shapely.distance(spots, copper) <= _NEAR)
        together = {was[m]: was[m] for m in np.flatnonzero(within)}

        def head(x: int, together: dict[int, int] = together) -> int:
            while together[x] != x:
                x = together[x]
            return x

        for one, two in whole:
            if within[one] and within[two]:
                together[head(was[one])] = head(was[two])
        off = shapely.distance(spots, middle)
        nearest: dict[int, int] = {}
        for m in np.flatnonzero(within):
            if (h := head(was[m])) not in nearest or off[m] < off[nearest[h]]:
                nearest[h] = int(m)
        for m in nearest.values():
            group[found.root(marks[m][0])] = found.root(i)
    return found


def _between(
    tracks: _Tracks, one: Sequence[int], two: Sequence[int], thick: float
) -> tuple[float, float, float] | None:
    """What the tracks are between two ends, each the nodes of its pads taken as one
    point: the resistance in ohms with copper *thick* millimetres thick, and the
    length and the narrowest width, in millimetres, of the way of least resistance.
    None where the tracks do not join them."""
    first, last = -1, -2  # the two ends, each as one node
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
    stretches found in *circuit* and the board's copper *copper* thick."""
    poured = {_net(zone) for zone in _pours(items)}
    nets: dict[str, _Tracks] = {}
    found = []
    for path in paths:
        readings = []
        for stretch in path.stretches(circuit)[0]:
            net = stretch.net.name
            if net not in nets:
                nets[net] = _tracks(items, net)
            one, two = ([i for pin in end for i in nets[net].pads.get(str(pin), ())]
                        for end in stretch.ends)  # fmt: skip
            between = _between(nets[net], one, two, copper.mm)
            if between is None:
                readings.append(Reading(stretch, poured=net in poured))
                continue
            ohms, long, narrow = between
            readings.append(Reading(stretch, ohms, Length(round(long * 1_000_000)),
                                    Length(round(narrow * 1_000_000)),
                                    ohms * path.current.a, net in poured))  # fmt: skip
        found.append(Measured(path, tuple(readings)))
    return tuple(found)
