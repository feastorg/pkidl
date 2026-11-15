"""Paths, measured: what the copper a current is said to go through comes to.

``path(jack, switch, regulator, current=1 * A)`` says the way a current goes, and a
build that routes the board measures each stretch of it on the board that is written:
its tracks and vias as they are. Nothing is changed for what is found, and nothing
found is a problem: ``Routed.paths`` has it.

A stretch is one net between two ends, each end every pad its part has on the net,
taken as one point. Its resistance is that of the net's tracks between them, as a
network: a track of length L and width w is ρ·L/(w·t), with ρ of copper at 20 °C and t
the thickness the board's ``rules`` give its copper, and tracks in parallel count as in
parallel. A via joins its two layers and a pad everything that ends on it, each with no
resistance of its own. A track is joined to a pad or a via where an end of it is within
that copper on its own layer, and to another track of its layer where an end of it is
within that track's copper, at an end or part way along. Tracks that cross with neither
ending on the other are not taken as joined.

The length and the narrowest width are of the way of least resistance between the
ends, and the drop is the resistance times the path's whole current, parts side by side
being one end.

A pour is not measured. Ends that no track joins have no figure, and are said to be
joined through the pour where their net has one. Where tracks join them and the net is
poured as well, the pour is beside the tracks, and the figure is at most what the
stretch is. What a part is between its own pads is not counted.
"""

from __future__ import annotations

import heapq
import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from shapely.geometry import Point as SPoint

from pkidl.circuit import Circuit
from pkidl.fill import _layers, _net, _num, _on, _pours, _xy
from pkidl.intent import Path, Stretch
from pkidl.sexpr import Node
from pkidl.units import Length

RHO = 1.72e-8  # ohm metres: copper at 20 °C
_NEAR = 1e-6  # millimetres: nearer than this is there


@dataclass(frozen=True)
class Reading:
    """One stretch of a path as the routed board has it: the resistance of its tracks
    in ohms, the length and the narrowest width of the way of least resistance through
    them, and the drop in volts at the path's current. None of each where no track
    joins its ends. *poured* is whether its net has a pour, which is not measured."""

    stretch: Stretch
    ohms: float | None = None
    length: Length | None = None
    narrowest: Length | None = None
    volts: float | None = None
    poured: bool = False

    def __str__(self) -> str:
        net = self.stretch.net
        if self.ohms is None or self.volts is None or self.length is None:
            how = f"joined through the pour of {net}, not measured" if self.poured else "not joined"
            return f"{self.stretch}: {how}"
        most, beside = "", ""
        if self.poured:
            most, beside = "at most ", f": the pour of {net} is beside it, not measured"
        return (f"{self.stretch}: {round(self.length.mm, 1):g} mm of track, {self.narrowest} "
                f"at its narrowest, {most}{_milli(self.ohms, 'Ω')}, {_milli(self.volts, 'V')}"
                f"{beside}")  # fmt: skip


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
            total = (f"{most}{_milli(ohms, 'Ω')} of track, {_milli(volts, 'V')} at "
                     f"{self.path.current}")  # fmt: skip
            if self.unmeasured:
                total += f", {self.unmeasured} of its {len(self.stretches)} stretches not in it"
        return "\n".join([f"{self.path}{at}: {total}", *(f"  {r}" for r in self.stretches)])


def _milli(value: float, unit: str) -> str:
    return f"{value:.3g} {unit}" if value >= 1 else f"{value * 1000:.3g} m{unit}"


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


def _foot(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    """How far along the line from *a* to *b*, from 0 to 1, the point of it nearest
    *p* is."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    long = dx * dx + dy * dy
    return (
        0.0 if long == 0 else min(1.0, max(0.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / long))
    )


def _tracks(items: list[Node], net: str) -> _Tracks:
    """The tracks of *net* among a board's *items* as resistors (see the module)."""
    nodes, of, vias = _on(items, net)
    group = list(range(len(nodes)))  # a pad or a via is a node; a track's are made below
    found = _Tracks([], {}, group)
    for i in of:
        found.pads.setdefault(nodes[i][0], []).append(i)
    lumps = [(i, nodes[i][1]) for i in sorted({*of, *vias})]
    segments = [(_xy(item, "start"), _xy(item, "end"), _num(item, "width"), _layers(item)[0])
                for item in items if str(item[0]) == "segment" and _net(item) == net]  # fmt: skip

    def node() -> int:
        group.append(len(group))
        return len(group) - 1

    # Each track's two ends, and after them each place another track ends on it.
    cuts = [[(0.0, node()), (1.0, node())] for _ in segments]
    for k, (a, b, _, layer) in enumerate(segments):
        for (_, end), p in zip(cuts[k][:2], (a, b), strict=True):
            at = SPoint(p)
            for i, copper in lumps:
                if layer in copper and copper[layer].distance(at) <= _NEAR:
                    group[found.root(end)] = found.root(i)
            for j, (c, d, wide, on) in enumerate(segments):
                if j == k or on != layer:
                    continue
                t = _foot(p, c, d)
                if math.dist(p, (c[0] + t * (d[0] - c[0]), c[1] + t * (d[1] - c[1]))) <= (
                    wide / 2 + _NEAR
                ):
                    cuts[j].append((t, node()))
                    group[found.root(end)] = found.root(len(group) - 1)
    for (a, b, wide, _), places in zip(segments, cuts, strict=True):
        places.sort()
        for (t0, one), (t1, two) in zip(places, places[1:], strict=False):
            long = (t1 - t0) * math.dist(a, b)
            if long <= _NEAR:
                group[found.root(two)] = found.root(one)
            else:
                found.pieces.append((one, two, long, wide))
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
    ways: dict[int, list[tuple[int, float, float, float]]] = {}
    for a, b, long, wide in tracks.pieces:
        a, b = (ends.get(r, r) for r in (tracks.root(a), tracks.root(b)))
        if a != b:
            r = RHO * (long / 1000) / ((wide / 1000) * (thick / 1000))
            ways.setdefault(a, []).append((b, r, long, wide))
            ways.setdefault(b, []).append((a, r, long, wide))
    # The way of least resistance from the first end, to everything it reaches.
    best: dict[int, tuple[float, float, float]] = {}
    queue: list[tuple[float, float, float, int]] = [(0.0, 0.0, math.inf, first)]
    while queue:
        r, long, narrow, at = heapq.heappop(queue)
        if at in best:
            continue
        best[at] = (r, long, narrow)
        for to, more, further, wide in ways.get(at, ()):
            if to not in best:
                heapq.heappush(queue, (r + more, long + further, min(narrow, wide), to))
    if last not in best:
        return None
    # The resistance of the network between the ends: one amp in at the first and out
    # at the last, which is held at nought, and the first end's voltage is the ohms.
    index = {at: n for n, at in enumerate(at for at in best if at != last)}
    g = np.zeros((len(index), len(index)))
    for a in index:
        for b, r, _, _ in ways[a]:
            g[index[a], index[a]] += 1 / r
            if b != last:
                g[index[a], index[b]] -= 1 / r
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
