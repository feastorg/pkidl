"""Build: a board's KiCad files, from what its board file said.

``build`` solves the statements, puts each part where the solution has it, draws each
area kept clear of copper as a rule area, has a router route the board if the board
file said ``route()``, and writes the board and its project. The ``Board`` is left as
it was: built twice, it gives the same files twice.

A board is not built from statements that conflict or do not hold, or with a part
nothing places: ``BuildError`` says each, with the line it was written on. A router
that leaves connections unmade does not stop the build. What it says is in the result
(``Built.routed``), and KiCad's DRC judges the board that was written.

A router is given the box around the board's outline. The placement keeps parts inside
the outline as it is drawn; the routing does not yet.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from shapely.geometry import Polygon

from pkidl.dsn import Via, Wire
from pkidl.fill import Cut, cut_off, prefill
from pkidl.footprint import Placement, place
from pkidl.intent import Route, Rules
from pkidl.kicad import kicad_command, unconnected
from pkidl.placement import Solution
from pkidl.project import NetClass, write_project
from pkidl.route import Freerouting
from pkidl.routing import Job, Routed, Router, lay, poured
from pkidl.sexpr import Node, find, num

if TYPE_CHECKING:
    from pkidl.board import Board


class BuildError(ValueError):
    """A board that cannot be built: ``problems`` is each reason, as a sentence."""

    def __init__(self, name: str, problems: list[str]) -> None:
        super().__init__(f"{name} is not built:\n" + "\n".join(f"  {p}" for p in problems))
        self.problems = tuple(problems)


@dataclass(frozen=True)
class Built:
    """What ``build`` wrote and what it was built from: the board file, the project
    file (None for a board with no ``rules``), where each part was put, and what the
    router proposed (None for a board that did not say ``route()``)."""

    board: Path
    project: Path | None
    solution: Solution
    routed: Routed | None


KICAD, MODEL = "KiCad", "model"  # whose word a build's pours are checked by


def _sized(item: Node, unsized: Mapping[str, tuple[str, ...]], clearance: float) -> Node:
    """*item*, or where it is a pour whose clearance or thermal gap was not said, a copy
    with them as the board's rules have its *clearance*. The thermal gap is between a
    pad and its own net's pour, which no rule widens: it is the clearance where that is
    less than the gap the zone was drawn with, and never more."""
    uid = find(item, "uuid") if item[0] == "zone" else None
    unsaid = unsized.get(str(uid[1]), ()) if uid is not None else ()
    if not unsaid:
        return item
    sized = copy.deepcopy(item)
    for key, inside in (("clearance", "connect_pads"), ("thermal_gap", "fill")):
        holder = find(sized, inside)
        value = find(holder, key) if holder is not None else None
        if key in unsaid and value is not None:
            drawn = float(str(value[1]))
            value[1] = num(min(clearance, drawn) if key == "thermal_gap" else clearance)
    return sized


def build(board: Board, outdir: Path, name: str, router: Router | None = None) -> Built:
    """Write *board*'s KiCad files into *outdir* as ``<name>.kicad_pcb`` and
    ``<name>.kicad_pro``, with what the router read and wrote beside them. *router*
    routes a board that says ``route()``: Freerouting where none is given."""
    said = board.statements()
    solution = board.solve()
    problems = [str(p) for p in solution.problems]  # a conflict is one of them
    problems += [f"{ref} is not placed: nothing says where it goes" for ref in solution.free]
    rules = next((s for s in said if isinstance(s, Rules)), None)
    routes = next((s for s in said if isinstance(s, Route)), None)
    if routes is not None and rules is None:
        at = f" ({routes.source})" if routes.source else ""
        problems.append(f"route(){at} needs the board's rules: say rules(track=, clearance=)")
    if problems:
        raise BuildError(name, problems)

    built = replace(board, items=list(board.items), _uuids=set(board._uuids),
                    _unsized=dict(board._unsized))  # fmt: skip
    for ref, pose in solution.poses.items():
        part = board[ref]
        nets = {pin.number: pin.net.name for pin in part.pins() if pin.net is not None}
        built.footprint(
            place(board.library[part.footprint],
                  Placement(part.footprint, ref, part.value, pose.x.mm, pose.y.mm, pose.rot,
                            pose.back, nets=nets))
        )  # fmt: skip

    if rules is not None:
        built.items = [_sized(item, board._unsized, rules.clearance.mm)
                       for item in built.items]  # fmt: skip

    keepouts: list[tuple[str, list[tuple[float, float]]]] = []
    for kept in solution.keepouts:
        x0, y0, x1, y1 = (side.mm for side in kept.box)
        box = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        for layer, on in (("F.Cu", kept.front), ("B.Cu", kept.back)):
            if on and (layer, box) not in keepouts:
                built.rule_area(f"{kept.statement.area.part.ref} {kept.statement.area.name}",
                                layer, box)  # fmt: skip
                keepouts.append((layer, box))

    outdir.mkdir(parents=True, exist_ok=True)
    project = routed = None
    if rules is not None:
        classes = [NetClass("Default", rules.clearance.mm, rules.track.mm)]

        def projected(path: Path) -> Path:
            """The board's rules as a KiCad project at *path*."""
            return write_project(
                path,
                netclasses=classes,
                members={},
                rules={"min_clearance": rules.clearance.mm, "min_track_width": rules.track.mm,
                       "min_copper_edge_clearance": rules.edge.mm},
                severities={},
            )  # fmt: skip

        if routes is not None:
            assert board.extent is not None  # a board with no outline has no solution
            x0, y0, x1, y1 = board.extent
            outline = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
            unrouted = list(built.items)  # the board as it is before a track is laid
            # A pour fills inside the outline as it is drawn, as far from its edge as the
            # rules say and from an unplated hole as KiCad asks.
            inside = board.edge() or Polygon(outline)
            # Said once, so the pour the router is told of and the one checked are one.
            fill_as = (inside, rules.edge.mm, {"": Job.hole_clearance})

            judged: list[str] = []  # who was asked, each time

            def cut(wires: Sequence[Wire], vias: Sequence[Via]) -> list[Cut]:
                """What the board's pours would leave cut off with these laid: by
                KiCad's own fill where KiCad is installed, and by pkidl's model of it
                where it is not or does not finish."""
                tried = replace(built, items=list(unrouted), _uuids=set(built._uuids))
                lay(tried, Routed(tuple(wires), tuple(vias), ()))
                if kicad_command() is not None:
                    # KiCad fills to the board's own rules: its project goes with it.
                    projected(outdir / f"{name}-poured-check.kicad_pro")
                    found = unconnected(tried.write(outdir / f"{name}-poured-check.kicad_pcb"))
                    if found is not None:
                        judged.append(KICAD)
                        return found
                judged.append(MODEL)
                return cut_off(tried.items, *fill_as)

            job = Job(
                footprints=[item for item in built.items if item[0] == "footprint"],
                outline=outline,
                netclasses=classes,
                members={},
                edge_clearance=rules.edge.mm,
                keepouts=keepouts,
                # The board's one track width is its minimum: a track that necks into
                # a pin is narrower than the rules allow, and so is a fan-out stub.
                neck_down=False,
                fan_out=False,
                # Each pour as it fills round the parts before there is a track, sized
                # as it is built: a net with a pour is joined through it where the
                # routed board shows it still is.
                planes=prefill(unrouted, *fill_as),
            )
            routed = poured(router or Freerouting(), job, outdir, name, cut)
            routed = replace(routed, judge=judged[-1] if judged else "")
            lay(built, routed)
        project = projected(outdir / f"{name}.kicad_pro")
    return Built(built.write(outdir / f"{name}.kicad_pcb"), project, solution, routed)
