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

from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from pkidl.footprint import Placement, place
from pkidl.intent import Route, Rules
from pkidl.placement import Solution
from pkidl.project import NetClass, write_project
from pkidl.route import Freerouting
from pkidl.routing import Job, Routed, Router, lay, staged

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

    built = replace(board, items=list(board.items), _uuids=set(board._uuids))
    for ref, pose in solution.poses.items():
        part = board[ref]
        nets = {pin.number: pin.net.name for pin in part.pins() if pin.net is not None}
        built.footprint(
            place(board.library[part.footprint],
                  Placement(part.footprint, ref, part.value, pose.x.mm, pose.y.mm, pose.rot,
                            pose.back, nets=nets))
        )  # fmt: skip

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
        if routes is not None:
            assert board.extent is not None  # a board with no outline has no solution
            x0, y0, x1, y1 = board.extent
            job = Job(
                footprints=[item for item in built.items if item[0] == "footprint"],
                outline=[(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
                netclasses=classes,
                members={},
                edge_clearance=rules.edge.mm,
                keepouts=keepouts,
            )
            routed = staged(router or Freerouting(), job, outdir, name)
            lay(built, routed)
        project = write_project(
            outdir / f"{name}.kicad_pro",
            netclasses=classes,
            members={},
            rules={"min_clearance": rules.clearance.mm, "min_track_width": rules.track.mm,
                   "min_copper_edge_clearance": rules.edge.mm},
            severities={},
        )  # fmt: skip
    return Built(built.write(outdir / f"{name}.kicad_pcb"), project, solution, routed)
