"""Routing: what a router is asked, what it hands back, and the stages a board is routed in.

A router is an engine behind one interface (``Router``). It is given a ``Job`` and
proposes tracks and vias; nothing here touches a board until ``lay`` puts a proposal on
one. What a router says of its own work (``Run.unrouted``) is reported, not trusted:
KiCad's DRC judges the board the routes are written into.

``staged`` routes a board in up to three runs:

1. **power**: the nets of every class but the first (Default), alone, with neck-down
   off. A router that may neck narrows a wide track along whole runs, not only into
   pins.
2. everything left, around those, fixed, necking where the job lets a track neck.
3. **cross**, only on a board with planes: whatever the corridors between the pours
   left unconnected, which may now cross a signal net's pour and never a power one.

``poured`` routes a board whose pours are to carry their nets: with the pours known to
the router and free to be crossed, then checked. A router told of a pour counts every
pad on it as joined, and tracks across the pour can leave a piece of it apart with
pads on it. Where the check finds that of a run that made every connection, what was
cut off is joined to the rest of its net by a track: the run's tracks are kept, the
router is told of the pours as they fill round them, less each pad its pour joins to
nothing and each piece that joins only pads cut off, and is asked for the nets cut
off alone. The check is asked again of what it lays. Where that does not mend it, the
board is routed again with that net carried by tracks, the pour beside them. Either
way what was cut off is in the result.

``relieved`` mends what the board that is written is then found to have wrong where it
can be mended with no connection changed: a pad starved of its pour that a track joins
to its net is taken off the pour.

``pkidl.route.Freerouting`` is the first router.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from pkidl.dsn import Via, Wire, via_size
from pkidl.project import NetClass
from pkidl.sexpr import Node, find, find_all

if TYPE_CHECKING:
    from pkidl.board import Board
    from pkidl.fill import Cut
    from pkidl.paths import Measured

Point = tuple[float, float]

POWER, CROSS, POURED, JOIN = "power", "cross", "poured", "join"
TURNS = 5  # the times a board's pours are checked again for pads taken off them
JOINS = 3  # the times what a run left cut off is joined by track, and checked again
Plane = tuple[str, str, Sequence[Point]]  # net, layer, hole-free polygon in board mm
# How a board's pours stand with wires and vias laid and pads off them (``poured``).
Refill = Callable[[Sequence[Wire], Sequence[Via], Sequence[str]],
                  tuple[Mapping[str, str], Sequence[Plane], Sequence[Node]]]  # fmt: skip


@dataclass(frozen=True)
class Job:
    """One run of a router: what it routes, around what, and how.

    *footprints* are placed board nodes and *outline* the board edge as a closed polygon,
    in board millimetres; the router is kept *edge_clearance* inside it and
    *hole_clearance* from an unplated hole, as KiCad is asked to hold them. *netclasses* and
    their *members* are as ``pkidl.project.write_project`` takes them: the first is
    Default. With *only*, just those nets are routed and every pin stays an obstacle.
    *wires* and *vias* are there before routing and kept. *class_clearances* is the
    clearance between two classes' nets, in mm, over their own. *keepouts* (layer,
    polygon) hold every track and via out. *planes* (net, layer, hole-free polygon, as
    ``pkidl.fill.prefill`` makes them) are pours the router may connect through.

    How: *neck_down* lets a track narrow into a pin; *fan_out* lets the router lead
    each SMD pad out to a via before it routes, which a router may do with a narrower
    track whatever *neck_down* is; *cross_planes* lets another net's track cross a
    plane; *quick* leaves out the router's fan-out and its optimising passes.
    """

    footprints: Sequence[Node]
    outline: Sequence[Point]
    netclasses: Sequence[NetClass]
    members: Mapping[str, Sequence[str]]
    edge_clearance: float = 0.5
    hole_clearance: float = 0.25
    only: frozenset[str] | None = None
    wires: Sequence[Wire] = ()
    vias: Sequence[Via] = ()
    class_clearances: Mapping[tuple[str, str], float] | None = None
    keepouts: Sequence[tuple[str, Sequence[Point]]] = ()
    planes: Sequence[tuple[str, str, Sequence[Point]]] = ()
    neck_down: bool = True
    fan_out: bool = True
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
    # What a run with the pours known left cut off, and what each check of a track
    # laid to join it still found: for which it was joined by track (``joined``), or
    # the board routed again with those nets carried by tracks (``poured``).
    cut: tuple[Cut, ...] = ()
    # What the same check finds of the board as it was routed last, where that was
    # without its pours: they are still drawn, round the tracks that carry their nets,
    # and what they leave wrong is on the board that is written. Once ``relieved``, what
    # the last check finds of the board that is written, however it was routed.
    left: tuple[Cut, ...] = ()
    # Each pad taken off its pour (``poured``, ``relieved``), a line a pad: the pad,
    # its net, the layer of the pour where it starved the pad, and that a track joins it.
    unjoined: tuple[str, ...] = ()
    # Whose word it is that the pours join what they are left to: ``KiCad``, or
    # ``model`` for pkidl's model of KiCad's fill. Empty where nothing was asked.
    judge: str = ""
    # Each track and via the board that is written has in an area kept clear of copper
    # (``pkidl.build.kept_out``), a line each: nothing is changed for it.
    kept_out: tuple[str, ...] = ()
    # Each path the board file said, as the copper of the board that is written has it
    # (``pkidl.paths``): what the tracks of each stretch come to, and its neck through
    # all the copper of its net, pours among it as pkidl's model fills them
    # (``pkidl.neck``). In the order statements have (``pkidl.intent.canonical``): by
    # the file each was written in, then its line, then what it says. Nothing is
    # changed for it.
    paths: tuple[Measured, ...] = ()
    # Each net that kept its pour though a run left some of it cut off, a line a net:
    # the track and vias laid to join what was cut off to the rest of it, which the
    # check then found joined.
    joined: tuple[str, ...] = ()
    # The pads taken off their pours for those joins, as ``C5.1``: the pour joined each
    # to nothing, and the track does. Each is a line of ``unjoined``.
    taken_off: tuple[str, ...] = ()


def staged(router: Router, job: Job, outdir: Path, name: str) -> Routed:
    """Route the whole board *job* describes, in stages (see the module).

    The job's ``class_clearances`` hold from the second stage on, between the first
    stage's copper and the rest. Its planes are ones every other net keeps out of
    until the last stage. Each stage says which nets it routes and how: what *job*
    has for ``only``, ``cross_planes`` and ``quick`` is not read. Its ``neck_down`` is
    whether a track may neck at all: the power stage never does, and the others do
    only where it is set. With ``fan_out`` off no stage fans out, the power stage
    included; with it on, the stages that are quick still do not.
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
            neck_down=job.neck_down,
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
                neck_down=job.neck_down,
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


def poured(
    router: Router,
    job: Job,
    outdir: Path,
    name: str,
    cut: Callable[..., Sequence[Cut]],
    refill: Refill | None = None,
) -> Routed:
    """Route the whole board *job* describes with its pours carrying their nets, where
    they can be shown to (see the module).

    The job's planes are the pours. A run of the ``poured`` stage routes everything with
    them known and free to be crossed, without the router's optimising passes, which
    cost minutes against a plane; *cut* is then asked what the wires and vias it
    proposes leave cut off (``pkidl.fill.cut_off`` on the board with them laid). With
    nothing cut off and nothing the router says it left unmade, that run is the
    routing.

    A run that made every connection and left pads of poured nets cut off is mended
    first, where *refill* is given. It is asked how the pours stand with the run's
    wires and vias laid and the pads taken off so far off them: the pads cut off that
    their pour joins to nothing, each with its net, to take off it; the planes the
    pours fill to with those taken off as well, less each piece that joins only pads
    cut off; and the footprints as the router is to be told of them, which have the
    pads one track joins together on no net but for one. A run of the ``join`` stage
    then routes the nets cut off alone, the run's copper fixed, those planes theirs and
    the planes of each net it does not route keepouts: a pad on no plane is one the
    router has to bring to the rest of its net, by a track that ends on a pad or a
    track of the net or in its pour. *cut* is asked of what it lays, with the pads
    taken off as its third argument. Where it finds nothing that is the routing:
    ``Routed.joined`` says what was laid for each net, ``Routed.taken_off`` and
    ``Routed.unjoined`` each pad taken off. A relief it names as starved is something
    found, as it is of a run of ``poured``: a join is not kept for it.
    A connection the router says it left unmade does not undo that: each one it was
    asked for is of a net the check is of. A check that still finds something cut off
    is mended the same way, ``JOINS`` times at most, and not again once the router has
    said it left a connection unmade. Nothing is joined for a run of ``poured`` that
    left a connection unmade, by a run that lays nothing, for a net with no pour, or
    where nothing found is cut off but only starved.

    Otherwise the nets the run left cut off lose their planes, nothing laid to join
    them is kept, and the board is routed again, by ``staged`` once no plane is left:
    what is routed last is the routing, and ``Routed.cut`` has what each earlier check
    found cut off. A board routed by
    ``staged`` still has its pours drawn, as copper beside the tracks, and *cut* is
    asked of it too: what it finds is ``Routed.left``, and nothing is changed for it.
    Only the nets that have pours are checked. What a router says it left unmade of
    the others, and of a board routed with no pour left, is in each ``Run`` and is its
    own word.
    """
    planes, runs, cuts, turn = list(job.planes), [], [], 0
    while planes:
        turn += 1
        stage = POURED if turn == 1 else f"{POURED}-{turn}"
        known = replace(job, planes=planes, cross_planes=True, quick=True)
        run = router.route(known, outdir, name, stage)
        runs.append((stage, run))
        found = list(cut(run.wires, run.vias))
        cuts += found
        if not found and not run.unrouted:
            return Routed(tuple(_with(list(run.wires), list(job.wires))), tuple(run.vias),
                          tuple(runs), tuple(cuts))  # fmt: skip
        if refill is not None and not run.unrouted:
            mended = _join(router, known, outdir, name, stage, run, found, cut, refill,
                           runs, cuts)  # fmt: skip
            if mended is not None:
                return mended
        # The nets cut off give up their pours. Where none of them has one left to give,
        # a run that left a connection unmade or a net already carried by tracks, there
        # is no net to blame and every pour gives way: each turn has fewer than the last.
        lost = {c.net for c in found} & {net for net, _, _ in planes}
        planes = [p for p in planes if p[0] not in lost] if lost else []
    rest = staged(router, replace(job, planes=()), outdir, name)
    left = tuple(cut(rest.wires, rest.vias)) if job.planes else ()
    return Routed(rest.wires, rest.vias, (*runs, *rest.runs), tuple(cuts), left)


def _join(
    router: Router,
    job: Job,
    outdir: Path,
    name: str,
    stage: str,
    run: Run,
    found: Sequence[Cut],
    cut: Callable[..., Sequence[Cut]],
    refill: Refill,
    runs: list[tuple[str, Run]],
    cuts: list[Cut],
) -> Routed | None:
    """The routing of *job*, a run of ``poured`` with its planes, with what its *run*
    left cut off (*found*) joined to the rest of its net by track, the pours kept: None
    where that is not done or the check does not pass it (``poured``). Each run made
    for it is added to *runs* and what each check of one finds to *cuts*, either way."""
    pours = {net for net, _, _ in job.planes}
    wires, vias = list(run.wires), list(run.vias)
    off: dict[str, str] = {}  # each pad taken off its pour, and its net
    laid: dict[str, tuple[float, set[str], int]] = {}  # a net: mm of track, on, vias
    for turn in range(1, JOINS + 1):
        nets = frozenset(c.net for c in found)
        if not nets <= pours or all(c.starved for c in found):
            return None
        more, pieces, footprints = refill(wires, vias, tuple(off))
        off.update((pad, net) for pad, net in more.items() if net in nets)
        named = f"{stage}-{JOIN}" if turn == 1 else f"{stage}-{JOIN}-{turn}"
        join = router.route(
            replace(
                job,
                footprints=footprints,
                only=nets,
                wires=_with(list(wires), list(job.wires)),
                vias=vias,
                # The pour of a net not routed here is whole by the check: no track
                # is laid across as much of it as is its plane. The nets that are
                # routed here cross each other's, as in the run with the pours known.
                keepouts=[
                    *job.keepouts,
                    *((layer, poly) for n, layer, poly in pieces if n in pours - nets),
                ],
                planes=[p for p in pieces if p[0] in nets],
            ),
            outdir,
            name,
            named,
        )
        runs.append((named, join))
        had, holed = {s for w in wires for s in _segments(w)}, {(v.net, v.at) for v in vias}
        new = [s for w in join.wires for s in _segments(w) - had]
        drilled = [v for v in join.vias if (v.net, v.at) not in holed]
        if not (new or drilled):
            return None
        for net in sorted(nets & ({of for of, _, _ in new} | {v.net for v in drilled})):
            mm, on, holes = laid.get(net, (0.0, set(), 0))
            laid[net] = (
                mm + _length(join.wires, net) - _length(wires, net),
                on | {layer for of, layer, _ in new if of == net},
                holes + sum(v.net == net for v in drilled),
            )
        wires = [*join.wires, *(w for w in wires if w.net not in nets)]
        vias = [*join.vias, *(v for v in vias if v.net not in nets)]
        # Every connection this run was asked for is of a net the check is of: what
        # it says it left unmade is no verdict where the check finds nothing.
        found = list(cut(wires, vias, tuple(off)))
        cuts += found
        if found and join.unrouted:
            return None
        if not found:
            said = []
            for net, (mm, on, holes) in laid.items():
                by = [f"{round(mm, 3):g} mm of track on {' and '.join(sorted(on))}"] if on else []
                by += ["1 via"] if holes == 1 else [f"{holes} vias"] if holes else []
                said.append(f"{net} keeps its pour: {' and '.join(by)} "
                            f"{'joins' if len(by) == 1 and holes < 2 else 'join'} what was "
                            f"cut off to the rest of {net}")  # fmt: skip
            return Routed(
                tuple(_with(wires, list(job.wires))), tuple(vias), tuple(runs), tuple(cuts),
                joined=tuple(said), taken_off=tuple(off),
                unjoined=tuple(f"{pad} is taken off the pour of {net}, which joins it to "
                               f"nothing: a track joins it to the rest of {net}"
                               for pad, net in off.items()),
            )  # fmt: skip
    return None


def _length(wires: Sequence[Wire], net: str) -> float:
    """How long the *wires* of *net* are, in mm."""
    return sum(math.dist(a, b) for w in wires if w.net == net
               for a, b in zip(w.points, w.points[1:], strict=False))  # fmt: skip


def relieved(
    routed: Routed,
    found: Sequence[Cut],
    check: Callable[[Sequence[str]], Sequence[Cut]],
    spare: Callable[[], Collection[str]],
    turns: int = TURNS,
) -> Routed:
    """*routed* with each pad starved of its pour, and joined to its net without it,
    taken off the pour (decided 2026-11-14).

    *found* is what the check found of the board as routed. A pad it names as starved
    (``Cut.starved``) that is among *spare*'s, the pads a pour can be spared with no
    connection changed (``pkidl.fill.spare``), is taken off: *check* is asked what it
    finds with those pads, as ``C5.1``, off their pours, and of what it finds the same
    is asked, since a pad off a pour can change what another's relief reaches. It ends
    when a check names no pad to take off, or after *turns* checks.

    ``Routed.unjoined`` names each pad taken off, and ``Routed.left`` is what the last
    check found: a starved pad that only the pour joins is there, left as it was. No
    track or via is changed, and where nothing is taken off *check* is not asked.

    The pads *routed* already has off their pours (``Routed.taken_off``) stay off: each
    check is asked with them among the pads, none is taken off again, and their lines
    of ``Routed.unjoined`` are kept, first."""
    found, off, said = list(found), list(routed.taken_off), []
    spared: Collection[str] | None = None
    for _ in range(turns):
        starved = {pad: c for c in found if c.starved for pad in c.pads if pad not in off}
        if starved and spared is None:
            spared = spare()
        take = [pad for pad in starved if spared is not None and pad in spared]
        if not take:
            break
        for pad in take:
            c = starved[pad]
            on = f" on {c.layer}" if c.layer else ""
            said.append(f"{pad} is taken off the pour of {c.net}{on}, which starved its "
                        f"relief: a track joins it to the rest of {c.net}")  # fmt: skip
        off += take
        found = list(check(tuple(off)))
    return replace(routed, left=tuple(found), unjoined=(*routed.unjoined, *said))


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
