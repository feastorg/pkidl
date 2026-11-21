"""Build: a board's KiCad files, from what its board file said.

``build`` solves the statements, puts each part where the solution has it, draws each
area kept clear of copper as a rule area, has a router route the board if the board
file said ``route()``, and writes the board and its project. The ``Board`` is left as
it was: built twice, it gives the same files twice.

A board is not built from statements that conflict or do not hold, or with a part
nothing places: ``BuildError`` says each, with the line it was written on. A router
that leaves connections unmade does not stop the build. What it says is in the result
(``Built.routed``), and KiCad's DRC judges the board that was written. What a run with
the pours known leaves cut off is joined to the rest of its net by a track where one
can be laid, the pour kept, and the result says so (``Routed.joined``). A pad starved of
its pour that a track joins to its net is taken off the pour, and the result names it
(``Routed.unjoined``). A track or a via the routed board has in an area kept clear of
copper is in the result too (``Routed.kept_out``): the router was told of the area, and
the board is checked for what it did. Each ``path`` the board file said is measured
on the routed board, and what its copper comes to is in the result as well
(``Routed.paths``).

A net a ``path`` goes through whose current needs a wider track than the board's
``rules(track=)`` is in a net class of that width, named for it (``0.562 mm``): the
router lays the whole net that wide, the project has the class and its nets, and
``<name>.kicad_dru`` beside it holds KiCad to the width as the least a track of the
class may be, which a class alone does not, and says above each rule the current that
needs it. That file is written whole, in place of whatever is at its path: KiCad
reads only the rules file named for the project, and a rule of one's own put in it
is lost to the next such build. A board with no such net has the one class, and its
build writes no such file and leaves that path alone: it is not opened, and a file
an earlier build left there stays, holding to a class no net is in.

A router is given the box around the board's outline. The placement keeps parts inside
the outline as it is drawn; the routing does not yet.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from shapely.geometry import LineString, Point, Polygon

from pkidl.dsn import Via, Wire
from pkidl.fill import Cut, Plane, cut_off, prefill, spare, standing, starved, unjoin
from pkidl.footprint import Placement, place
from pkidl.intent import Fixed, Route, Rules, canonical
from pkidl.intent import Path as Said
from pkidl.kicad import kicad_command, unconnected
from pkidl.paths import carried, measured, widths
from pkidl.placement import Solution
from pkidl.project import NetClass, width_rules, write_project, write_rules
from pkidl.route import Freerouting
from pkidl.routing import Job, Routed, Router, lay, poured, relieved
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
_SLIVER = 1e-9  # square millimetres: copper that only touches an area is not in it


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


def kept_out(
    items: Sequence[Node], areas: Sequence[tuple[str, str, Sequence[tuple[float, float]]]]
) -> tuple[str, ...]:
    """Each track and via among a board's *items* that is in one of *areas*, each what
    a sentence calls it, the layer it is kept clear of copper on, and its corners: a
    line for a net's tracks in an area on a layer, and one for a via, which is on every
    layer. A track is in an area where its copper is, to its width; how much of it is
    said by its middle line. A pad is not looked at: it is no copper that is kept out."""
    shapes = [(what, layer, Polygon(corners)) for what, layer, corners in areas]
    tracks: dict[tuple[str, str, str], list[float]] = {}
    vias: dict[tuple[str, float, float, str], None] = {}
    for item in items if shapes else ():
        head = str(item[0])
        if head not in ("segment", "via"):
            continue
        net = find(item, "net")
        of = str(net[1]) if net is not None else ""
        if head == "via":
            at, size = find(item, "at"), find(item, "size")
            assert at is not None and size is not None
            x, y = float(str(at[1])), float(str(at[2]))
            dot = Point(x, y).buffer(float(str(size[1])) / 2)
            for what, _, shape in shapes:
                if dot.intersection(shape).area > _SLIVER:
                    vias.setdefault((of, x, y, what))
            continue
        start, end, width, on = (find(item, key) for key in ("start", "end", "width", "layer"))
        assert start is not None and end is not None and width is not None and on is not None
        line = LineString([(float(str(p[1])), float(str(p[2]))) for p in (start, end)])
        copper = line.buffer(float(str(width[1])) / 2)
        for what, layer, shape in shapes:
            if layer == str(on[1]) and copper.intersection(shape).area > _SLIVER:
                found = tracks.setdefault((of, layer, what), [0, 0.0])
                found[0] += 1
                found[1] += line.intersection(shape).length
    said = []
    for (of, layer, what), (count, long) in tracks.items():
        segments = "1 segment" if count == 1 else f"{count:g} segments"
        said.append(f"{of} has {segments} of track in {what} on {layer}, which is kept "
                    f"clear of copper: {round(long, 3):g} mm of it")  # fmt: skip
    for of, x, y, what in vias:
        said.append(f"a via of {of} at ({x:g}, {y:g}) is in {what}, which is kept clear of copper")
    return tuple(said)


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
    # Each part where the solution puts it, and each that is a hole where it is fixed.
    poses = [(ref, pose.x.mm, pose.y.mm, pose.rot, pose.back)
             for ref, pose in solution.poses.items()]  # fmt: skip
    poses += [(ref, f.x.mm, f.y.mm, f.rot, f.back) for ref, f in board.held.items()]
    for ref, x, y, rot, back in poses:
        part = board[ref]
        nets = {pin.number: pin.net.name for pin in part.pins() if pin.net is not None}
        built.footprint(
            place(board.library[part.footprint],
                  Placement(part.footprint, ref, part.value, x, y, rot, back, nets=nets))
        )  # fmt: skip

    if rules is not None:
        built.items = [_sized(item, board._unsized, rules.clearance.mm)
                       for item in built.items]  # fmt: skip

    keepouts: list[tuple[str, list[tuple[float, float]]]] = []
    called: list[str] = []  # what a sentence calls each of them
    for kept in solution.keepouts:
        x0, y0, x1, y1 = (side.mm for side in kept.box)
        box = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        what = kept.statement.area
        if isinstance(what, Fixed):
            label = spoken = what.label
        else:
            label, spoken = f"{what.part.ref} {what.name}", f"{what.part.ref}'s {what.name} area"
        for layer, on in (("F.Cu", kept.front), ("B.Cu", kept.back)):
            if on and (layer, box) not in keepouts:
                built.rule_area(label, layer, box)
                keepouts.append((layer, box))
                called.append(spoken)

    outdir.mkdir(parents=True, exist_ok=True)
    project = routed = None
    if rules is not None:
        classes = [NetClass("Default", rules.clearance.mm, rules.track.mm)]
        # A net a path makes wider is in a class of its width, named for the width.
        paths = [s for s in canonical(said) if isinstance(s, Said)]
        members: dict[str, list[str]] = {}
        for net, wide in widths(paths, board.circuit, rules).items():
            if str(wide) not in members:
                classes.append(NetClass(str(wide), rules.clearance.mm, wide.mm))
            members.setdefault(str(wide), []).append(net)
        classes.sort(key=lambda c: (c.name != "Default", c.track_width))
        # Why each is as wide as it is, for whoever opens the rules file: the most a
        # path carries on a net of the class.
        most = carried(paths, board.circuit)
        why = {c.name: (c.track_width,
                        f"a path's {max(most[net] for net in members[c.name])} needs {c.name} "
                        f"to warm by no more than {rules.rise} in {rules.copper} copper")
               for c in classes[1:]}  # fmt: skip

        def projected(path: Path) -> Path:
            """The board's rules as a KiCad project at *path*."""
            return write_project(
                path,
                netclasses=classes,
                members=members,
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

            def laid(wires: Sequence[Wire], vias: Sequence[Via],
                     off: Sequence[str] = ()) -> Board:  # fmt: skip
                """The board with these laid, and the pads *off* taken off their pours."""
                tried = replace(built, items=unjoin(unrouted, off), _uuids=set(built._uuids))
                lay(tried, Routed(tuple(wires), tuple(vias), ()))
                return tried

            def cut(wires: Sequence[Wire], vias: Sequence[Via], off: Sequence[str] = (),
                    written: bool = False) -> list[Cut]:  # fmt: skip
                """What the board's pours would leave cut off with these laid and the
                pads *off* taken off their pours: by KiCad's own fill where KiCad is
                installed, and by pkidl's model of it where it is not or does not
                finish. Asked of the board to be *written*, the model says the pads its
                pours starve as well, as KiCad does each time."""
                tried = laid(wires, vias, off)
                if kicad_command() is not None:
                    # KiCad fills to the board's own rules: its project goes with it.
                    projected(outdir / f"{name}-poured-check.kicad_pro")
                    found = unconnected(tried.write(outdir / f"{name}-poured-check.kicad_pcb"))
                    if found is not None:
                        judged.append(KICAD)
                        return found
                judged.append(MODEL)
                found = cut_off(tried.items, *fill_as)
                return [*found, *starved(tried.items, *fill_as)] if written else found

            def refill(wires: Sequence[Wire], vias: Sequence[Via], off: Sequence[str]
                       ) -> tuple[dict[str, str], list[Plane], list[Node]]:  # fmt: skip
                """How the pours stand with these laid and the pads *off* taken off
                them, by pkidl's model, which steers the router as ``prefill`` does and
                judges nothing (``pkidl.fill.standing``): the pads cut off that the
                pour joins to nothing; the pours as they fill with those off as well,
                where a track of the board's widest class can end in them and less
                each piece that joins only pads cut off; and the footprints, with the
                pads cut off together that one track joins on no net but for one."""
                wide = max(c.track_width for c in classes)
                apart, planes, items = standing(laid(wires, vias, off).items, *fill_as, wide=wide)
                return apart, planes, [item for item in items if item[0] == "footprint"]

            job = Job(
                footprints=[item for item in built.items if item[0] == "footprint"],
                outline=outline,
                netclasses=classes,
                members=members,
                edge_clearance=rules.edge.mm,
                keepouts=keepouts,
                # A class's track width is its minimum: a track that necks into a pin
                # is narrower than the rules allow, and so is a fan-out stub.
                neck_down=False,
                fan_out=False,
                # Each pour as it fills round the parts before there is a track, sized
                # as it is built: a net with a pour is joined through it where the
                # routed board shows it still is.
                planes=prefill(unrouted, *fill_as),
            )
            routed = poured(router or Freerouting(), job, outdir, name, cut, refill)
            if judged:
                # The board to be written: as routed with its pours where that run
                # stood, which the check passed, with any pad a join took off its pour
                # off it, or as routed again, of which it found ``left``. The model was
                # not asked there what its pours starve.
                wires, vias, found = routed.wires, routed.vias, list(routed.left)
                if judged[-1] == MODEL:
                    found += starved(laid(wires, vias, routed.taken_off).items, *fill_as)
                off = list(routed.taken_off)  # the pads taken off their pours, as last asked

                def again(pads: Sequence[str]) -> list[Cut]:
                    off[:] = pads
                    return cut(wires, vias, pads, True)

                routed = relieved(routed, found, again,
                                  lambda: spare(laid(wires, vias).items))  # fmt: skip
                built.items = unjoin(built.items, off)
            lay(built, routed)
            areas = [(spoken, layer, box) for spoken, (layer, box)
                     in zip(called, keepouts, strict=True)]  # fmt: skip
            routed = replace(routed, judge=judged[-1] if judged else "",
                             kept_out=kept_out(built.items, areas),
                             paths=measured(built.items, paths, board.circuit,
                                            rules.copper, rules.rise))  # fmt: skip
        project = projected(outdir / f"{name}.kicad_pro")
        if members:
            # A class's width is what KiCad draws a track at, and no minimum: this is.
            write_rules(outdir / f"{name}.kicad_dru", width_rules(classes[1:], "error", why))
    return Built(built.write(outdir / f"{name}.kicad_pcb"), project, solution, routed)
