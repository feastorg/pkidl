"""Routing: what a router is asked, what it hands back, and the stages a board is routed in.

A router is an engine behind one interface (``Router``). It is given a ``Job`` and
proposes tracks and vias; nothing here touches a board until ``lay`` puts a proposal on
one. What a router says of its own work (``Run.unrouted``) is reported, not trusted:
KiCad's DRC judges the board the routes are written into.

``staged`` routes a board in up to three runs:

1. **power**: the nets of every class but the first (Default), alone, with neck-down
   off. A router that may neck narrows a wide track along whole runs, not only into
   pins.
2. everything left, around those, fixed, with neck-down on.
3. **cross**, only on a board with planes: whatever the corridors between the pours
   left unconnected, which may now cross a signal net's pour and never a power one.

``pkidl.route.Freerouting`` is the first router.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from pkidl.dsn import Via, Wire, via_size
from pkidl.project import NetClass
from pkidl.sexpr import Node, find, find_all

if TYPE_CHECKING:
    from pkidl.board import Board

Point = tuple[float, float]

POWER, CROSS = "power", "cross"


@dataclass(frozen=True)
class Job:
    """One run of a router: what it routes, around what, and how.

    *footprints* are placed board nodes and *outline* the board edge as a closed polygon,
    in board millimetres; the router is kept *edge_clearance* inside it. *netclasses* and
    their *members* are as ``pkidl.project.write_project`` takes them: the first is
    Default. With *only*, just those nets are routed and every pin stays an obstacle.
    *wires* and *vias* are there before routing and kept. *class_clearances* is the
    clearance between two classes' nets, in mm, over their own. *keepouts* (layer,
    polygon) hold every track and via out. *planes* (net, layer, hole-free polygon, as
    ``pkidl.fill.prefill`` makes them) are pours the router may connect through.

    How: *neck_down* lets a track narrow into a pin; *cross_planes* lets another net's
    track cross a plane; *quick* leaves out the router's fan-out and its optimising
    passes.
    """

    footprints: Sequence[Node]
    outline: Sequence[Point]
    netclasses: Sequence[NetClass]
    members: Mapping[str, Sequence[str]]
    edge_clearance: float = 0.5
    only: frozenset[str] | None = None
    wires: Sequence[Wire] = ()
    vias: Sequence[Via] = ()
    class_clearances: Mapping[tuple[str, str], float] | None = None
    keepouts: Sequence[tuple[str, Sequence[Point]]] = ()
    planes: Sequence[tuple[str, str, Sequence[Point]]] = ()
    neck_down: bool = True
    cross_planes: bool = True
    quick: bool = False


@dataclass(frozen=True)
class Run:
    """What one run of a router hands back: the wiring of the nets it routed, the job's
    own wires and vias on those nets among it, and how many connections the router
    says it left unmade (None where it does not say)."""

    wires: tuple[Wire, ...]
    vias: tuple[Via, ...]
    unrouted: int | None = None


class Router(Protocol):
    def route(self, job: Job, outdir: Path, name: str, stage: str = "") -> Run:
        """Route *job*. What the router reads, writes and logs is left in *outdir*,
        named for the board (*name*) and the *stage* of its routing this run is."""
        ...


@dataclass(frozen=True)
class Routed:
    """The tracks and vias proposed for a board, each once, and the runs they came
    from in the order they were made: (stage, run), the stage with no name being the
    one that routes everything left."""

    wires: tuple[Wire, ...]
    vias: tuple[Via, ...]
    runs: tuple[tuple[str, Run], ...]


def staged(router: Router, job: Job, outdir: Path, name: str) -> Routed:
    """Route the whole board *job* describes, in stages (see the module).

    The job's ``class_clearances`` hold from the second stage on, between the first
    stage's copper and the rest. Its planes are ones every other net keeps out of
    until the last stage. Each stage says which nets it routes and how: what *job*
    has for ``only``, ``neck_down``, ``cross_planes`` and ``quick`` is not read.
    """
    power = frozenset(n for c in job.netclasses[1:] for n in job.members.get(c.name, ()))
    authored, vias = list(job.wires), list(job.vias)
    keepouts, planes = list(job.keepouts), list(job.planes)
    # Against planes, two of Freerouting 2.5.0's stages cost minutes for nothing: on one
    # board the optimizer's every pass was rejected (its output is byte-identical without
    # it, 2026-11-11) and fan-out spent 220 s in one pass, oscillating on a ground net.
    # Left out of the runs with planes; the result is checked on the filled board.
    quick = bool(planes)
    runs: list[tuple[str, Run]] = []
    # Every fixed via is an obstacle in every stage, whichever net it is on.
    fixed_wires, fixed_vias = authored, vias
    if power:
        # Only the power nets' pours are planes here: a plane makes its net one the router
        # connects, and the signal nets wait for the second stage. Their pours are plain
        # keepouts meanwhile, so the power routes still keep out of them.
        first = router.route(
            replace(
                job,
                only=power,
                class_clearances=None,
                keepouts=[
                    *keepouts,
                    *((layer, poly) for n, layer, poly in planes if n not in power),
                ],
                planes=[p for p in planes if p[0] in power],
                neck_down=False,
                cross_planes=not planes,
                quick=False,
            ),
            outdir,
            name,
            POWER,
        )
        runs.append((POWER, first))
        # A fixed via on a net this stage does not route may not come back: keep each once.
        kept = {(v.net, v.at) for v in first.vias}
        fixed_wires = _with(list(first.wires), authored)
        fixed_vias = [*first.vias, *(v for v in vias if (v.net, v.at) not in kept)]
    rest = router.route(
        replace(
            job,
            only=None,
            wires=fixed_wires,
            vias=fixed_vias,
            neck_down=True,
            cross_planes=not planes,
            quick=quick,
        ),
        outdir,
        name,
    )
    runs.append(("", rest))
    wires, routed_vias = list(rest.wires), list(rest.vias)
    if planes:
        # Everything routed so far is fixed, so only the missing connections are routed,
        # and the pours they cut show in the filled board's regions. The power nets are
        # complete by now, so their pours are plain keepouts here.
        signal_nets = frozenset(
            str(n[-1])
            for fp in job.footprints
            for pad in find_all(fp, "pad")
            if (n := find(pad, "net")) is not None and str(n[-1])
        ) - power  # fmt: skip
        last = router.route(
            replace(
                job,
                only=signal_nets,
                wires=_with(wires, authored),
                vias=routed_vias,
                keepouts=[*keepouts, *((layer, poly) for n, layer, poly in planes if n in power)],
                planes=[p for p in planes if p[0] not in power],
                neck_down=True,
                cross_planes=True,
                quick=quick,
            ),
            outdir,
            name,
            CROSS,
        )
        runs.append((CROSS, last))
        # The run hands back only the nets it routes: the rest carry forward.
        wires = [*last.wires, *(w for w in wires if w.net not in signal_nets)]
        routed_vias = [*last.vias, *(v for v in routed_vias if v.net not in signal_nets)]
    return Routed(tuple(_with(wires, authored)), tuple(routed_vias), tuple(runs))


def lay(board: Board, routed: Routed) -> None:
    """Put what was *routed* on *board*: a track for each segment of each wire, and
    each via."""
    for w in routed.wires:
        for a, b in zip(w.points, w.points[1:], strict=False):
            board.track(a, b, w.width, w.net, w.layer)
    for v in routed.vias:
        board.via(v.at, *via_size(v.padstack), v.net)


def _with(wires: list[Wire], authored: list[Wire]) -> list[Wire]:
    """*wires* plus each *authored* wire the router did not hand back. The router rounds
    what it hands back and may reverse it, so segments are compared to the micrometre."""
    have = {s for w in wires for s in _segments(w)}
    return wires + [w for w in authored if not _segments(w) <= have]


def _segments(w: Wire) -> set[tuple]:
    pts = [(round(x, 3), round(y, 3)) for x, y in w.points]
    return {(w.net, w.layer, frozenset((a, b))) for a, b in zip(pts, pts[1:], strict=False)}
