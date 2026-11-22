"""Read the inputs a board is designed from out of an existing KiCad board.

A board is designed from its circuit and its mechanical requirements. For a board
that exists only as a ``.kicad_pcb`` (the corpus), both are read from it here:

- ``circuit``: each part's reference, value, footprint and pad -> net map. No
  position, side or rotation: those are the layout, which is designed, not read.
- ``mechanical``: what a designer is given: the board outline and the mounting
  holes, a hole on a net among them as well as in the circuit. Fixed connectors
  are added per board, with a reason, when its board file is written.
- ``footprints``: the library footprint each footprint name stands for, which the
  board carries a copy of in every placed part. It is the part's package, as a
  footprint library holds it: no position, rotation or side.

Nothing else of the board's layout is read: no tracks, vias, pours or positions of
other parts.
"""

from __future__ import annotations

from collections import Counter

from shapely.geometry import Point, Polygon

from pkidl.circuit import natural
from pkidl.edge import JOIN
from pkidl.edge import shape as edge_shape
from pkidl.footprint import board_xy, library_form
from pkidl.sexpr import Node, dumps, find, find_all

EDGE_ITEMS = ("gr_line", "gr_arc", "gr_rect", "gr_circle", "gr_poly")


def _property(fp: Node, name: str) -> str:
    return next((str(p[2]) for p in find_all(fp, "property") if p[1] == name), "")


def _xy(node: Node | None) -> list[float] | None:
    return None if node is None else [float(node[1]), float(node[2])]


def _drill(fp: Node, pad: Node) -> list[float]:
    """``[x, y, diameter]`` of a drilled pad, on the board, or ``[x, y, width, height,
    angle]`` of an oval one: its size along the pad's own axes, and the pad's angle on
    the board. By the pad's own position, not its number: a hole's pads are often
    unnumbered. The hole is where the pad is; a drill's ``offset`` moves its copper."""
    at, drill = find(pad, "at"), find(pad, "drill")
    assert at is not None and drill is not None
    xy = board_xy(fp, float(at[1]), float(at[2]))
    if drill[1] == "oval":
        return [*xy, float(drill[2]), float(drill[3]), float(at[3]) if len(at) > 3 else 0.0]
    return [*xy, float(drill[1])]


def _ringed(pad: Node) -> bool:
    """Whether a drilled pad is a hole with at most a ring of copper round it."""
    drill = find(pad, "drill")
    assert drill is not None
    if pad[2] == "np_thru_hole":
        return True
    shape = "oval" if drill[1] == "oval" else "circle"
    return str(pad[3]) == shape and find(drill, "offset") is None


def _is_edge(item: object) -> bool:
    """Whether a footprint's child is drawn on Edge.Cuts."""
    if not isinstance(item, list) or not str(item[0]).startswith("fp_") or item[0] == "fp_text":
        return False
    layer = find(item, "layer")
    return layer is not None and str(layer[1]) == "Edge.Cuts"


def _undefined(item: object) -> bool:
    """Whether a footprint's child is on KiCad's UNDEFINED layer, where its EAGLE import
    puts layers it has no place for. KiCad will not load a board with such an item."""
    if not isinstance(item, list):
        return False
    layer = find(item, "layer")
    return layer is not None and str(layer[1]) == "UNDEFINED"


def _footprint_edge(fp: Node) -> list[dict]:
    """The Edge.Cuts items drawn in a placed footprint, as board items where KiCad has
    them: part of the board's outline. A rectangle turned other than square to the board
    is a polygon."""
    items = []
    for g in fp[2:]:
        if not _is_edge(g) or (kind := "gr_" + str(g[0])[3:]) not in EDGE_ITEMS:
            continue
        local = {k: (float(n[1]), float(n[2])) for k in ("start", "mid", "end", "center")
                 if (n := find(g, k)) is not None}  # fmt: skip
        item: dict = {"type": kind, **{k: list(board_xy(fp, *p)) for k, p in local.items()}}
        if kind == "gr_rect":
            (x0, y0), (x1, y1) = local["start"], local["end"]
            corners = [
                list(board_xy(fp, x, y)) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
            ]
            if corners[0][0] != corners[1][0] and corners[0][1] != corners[1][1]:
                item = {"type": "gr_poly", "pts": corners}
        if (pts := find(g, "pts")) is not None:
            item["pts"] = [
                list(board_xy(fp, float(p[1]), float(p[2]))) for p in find_all(pts, "xy")
            ]
        items.append(item)
    return items


def _drawn(items: list[dict], edge: Polygon | None) -> tuple[str, str] | None:
    """What a footprint's Edge.Cuts *items* are of the board whose edge is *edge*, as a
    sentence says it, with its verb, and then again as its object: the board's outline,
    where each point they are drawn through is on the outside of *edge*, or the cut-outs
    they are on the inside of. Where they are some of each, or the board has no one
    edge, they are its edge. None where none of them is on the edge: lines that close
    nothing, which ``pkidl.edge.shape`` leaves out."""
    points = [Point(item[k]) for item in items for k in ("start", "mid", "end") if k in item]
    points += [Point(p) for item in items for p in item.get("pts", [])]
    if edge is not None and points:
        if all(edge.exterior.distance(p) <= JOIN for p in points):
            return "the board's outline is", "the outline"
        cut = {i for p in points for i, ring in enumerate(edge.interiors)
               if ring.distance(p) <= JOIN}  # fmt: skip
        if not cut and all(edge.exterior.distance(p) > JOIN for p in points):
            return None
        if all(any(ring.distance(p) <= JOIN for ring in edge.interiors) for p in points):
            if len(cut) == 1:
                return "a cut-out of the board is", "the cut-out"
            return f"{len(cut)} cut-outs of the board are", "the cut-outs"
    return "part of the board's edge is", "it"


def circuit(board: Node) -> dict:
    """``{"parts": [{ref, value, footprint, pads: {number: net}}], "nets": [...]}``,
    parts sorted by reference. Pads on no net are left out of ``pads``; a footprint
    with no pad on a net (a logo, a hole on no net) is not part of the circuit, and nor
    is one KiCad never annotated from a schematic (reference empty or with ``*``, as
    ``REF**``): those are board-only, such as vias placed as footprints."""
    read = _Read(board)
    parts = [{"ref": read.ref[id(fp)], "value": _property(fp, "Value"),
              "footprint": read.name[id(fp)], "pads": pads}
             for fp, pads in read.parts]  # fmt: skip
    nets = {net for _, pads in read.parts for net in pads.values()}
    return {"parts": sorted(parts, key=lambda p: p["ref"]), "nets": sorted(nets)}


def renamed(board: Node) -> list[str]:
    """What ``circuit``, ``mechanical`` and ``footprints`` name otherwise than the board
    does, each said in a line. Where parts share a reference, the first by position on
    the board (x, then y) keeps it and the others are given it with ``_2``, ``_3`` and
    on, past any reference the board has. Where versions of one footprint name differ
    in their pads, the version most footprints carry keeps the name and each other is
    written under the name with ``_2``, ``_3`` and on, its parts and holes with it.

    It also says what is read that a board's author may not expect: a part of the
    circuit that is a mounting hole as well, with the net it is on (``mechanical``); a
    part of the circuit whose footprint draws the board's outline or a cut-out in it,
    told apart by where on the board's edge it is drawn (it is read, and the part is
    still placed as any other, not fixed where the edge needs it, unless it is a hole);
    by footprint name with their number, footprints whose pads are all drilled and on no
    net but are not holes, so that a hole left out can be seen; and, by footprint name,
    how many of its items are on KiCad's UNDEFINED layer and left out of it
    (``footprints``)."""
    return _Read(board).said


def _pads(fp: Node) -> dict[str, str]:
    """A placed footprint's pads on a net: ``{number: net}``."""
    pads: dict[str, str] = {}
    for pad in find_all(fp, "pad"):
        net = find(pad, "net")
        if net is not None and str(net[-1]):
            pads[str(pad[1])] = str(net[-1])
    return dict(sorted(pads.items()))


def _split(fp: Node) -> dict[str, list[str]]:
    """Each pad number of a placed footprint that is on more than one net, with its nets:
    the circuit can have it on one of them only, the last."""
    nets: dict[str, list[str]] = {}
    for pad in find_all(fp, "pad"):
        net = find(pad, "net")
        if net is not None and str(net[-1]) and str(net[-1]) not in nets.get(str(pad[1]), []):
            nets.setdefault(str(pad[1]), []).append(str(net[-1]))
    return {n: on for n, on in sorted(nets.items()) if len(on) > 1}


def _drilled(fp: Node) -> list[Node]:
    """A footprint's drilled pads, where every other pad it has is the ring of one of
    them: a round pad on a surface, numbered as that pad is and centred on its hole, as
    a hole drawn with its ring as a pad on each face has it. Otherwise none."""
    pads = find_all(fp, "pad")
    holes = [p for p in pads if find(p, "drill") is not None]

    def where(pad: Node) -> tuple[str, list]:
        at = find(pad, "at")
        assert at is not None
        return str(pad[1]), [float(at[1]), float(at[2])]

    centres = [where(p) for p in holes]
    for pad in pads:
        if find(pad, "drill") is None and not (str(pad[3]) == "circle" and where(pad) in centres):
            return []
    return holes


def _drilled_on_no_net(fp: Node) -> bool:
    """Whether a footprint has pads, all drilled, or rings of those that are, and all on
    no net."""
    if not _drilled(fp):
        return False
    return not any((n := find(p, "net")) is not None and str(n[-1]) for p in find_all(fp, "pad"))


def _is_hole(fp: Node) -> bool:
    return _drilled_on_no_net(fp) and all(_ringed(p) for p in _drilled(fp))


_BODY = ("F.SilkS", "B.SilkS", "F.Fab", "B.Fab")  # where a footprint draws a part's body
_SCREW = 2.0  # mm: the least a mounting hole is across, an M2 screw's clearance and more


def _across(pad: Node) -> float:
    """How far across a pad's drill is: its diameter, or an oval's narrower size."""
    drill = find(pad, "drill")
    assert drill is not None
    return min(float(drill[2]), float(drill[3])) if drill[1] == "oval" else float(drill[1])


def _is_held(fp: Node, pads: dict[str, str]) -> bool:
    """Whether a part of the circuit, with *pads* on nets, is a mounting hole on a net,
    such as a grounded standoff: its pads all drilled, or rings of those that are, and
    each a hole with at most a ring, as a hole's are; those on a net all on the one
    net; its largest hole at least ``_SCREW`` across; and no body drawn on silkscreen or
    fab. A pin header or a resistor has holes too small; a banana post or a speaker
    draws its body, and a speaker's two pads are on two nets."""
    found = _drilled(fp)
    if not found or not all(_ringed(p) for p in found):
        return False
    if len(set(pads.values())) != 1 or max(_across(p) for p in found) < _SCREW:
        return False
    drawn = [c for c in fp[2:] if isinstance(c, list) and str(c[0]).startswith("fp_")]
    layers = [find(c, "layer") for c in drawn if c[0] != "fp_text"]
    return not any(layer is not None and str(layer[1]) in _BODY for layer in layers)


def _pad_form(lib: Node) -> list[str]:
    """A library footprint's pads: number, type, shape, place, size and drill, each to
    the micrometre."""

    def kept(n: Node | None) -> list[str]:
        if n is None:
            return []
        out = []
        for t in n[1:]:
            try:
                out.append(f"{float(t):.3f}")
            except (TypeError, ValueError):
                out.append(dumps(t) if isinstance(t, list) else str(t))
        return out

    return sorted(" ".join([str(p[1]), str(p[2]), str(p[3]), *kept(find(p, "at")),
                            *kept(find(p, "size")), *kept(find(p, "drill"))])
                  for p in find_all(lib, "pad"))  # fmt: skip


def _where(fp: Node) -> tuple[float, float]:
    at = find(fp, "at")
    assert at is not None
    return float(at[1]), float(at[2])


def _free(name: str, taken: set[str]) -> str:
    """*name* with the first of ``_2``, ``_3``, ... that is not *taken*, in any case."""
    k = 2
    while f"{name}_{k}".lower() in taken:
        k += 1
    taken.add(f"{name}_{k}".lower())
    return f"{name}_{k}"


class _Read:
    """What the importer reads of a board's footprints: the parts of its circuit with
    their pads on nets, its holes, the reference and footprint name each goes by, the
    library footprint each name stands for, and what ``renamed`` says of them."""

    def __init__(self, board: Node) -> None:
        fps = find_all(board, "footprint")
        self.parts: list[tuple[Node, dict[str, str]]] = []
        for fp in fps:
            ref = _property(fp, "Reference")
            if ref and "*" not in ref and (pads := _pads(fp)):
                self.parts.append((fp, pads))
        # The parts that are mounting holes as well: fixed where the board has them. Not
        # one with a pad number on two nets, which the circuit has on one.
        self.held = {id(fp) for fp, pads in self.parts
                     if _is_held(fp, pads) and not _split(fp)}  # fmt: skip
        self.holes = [fp for fp in fps if _is_hole(fp) or id(fp) in self.held]
        self.said: list[str] = []
        self.ref: dict[int, str] = {}
        self._refs(fps)
        self.name: dict[int, str] = {}
        self.libs: dict[str, Node] = {}
        self.differ: dict[str, list[str]] = {}
        self.undefined: dict[str, int] = {}
        self._names(fps)
        for fp, pads in sorted(self.parts, key=lambda part: natural(self.ref[id(part[0])])):
            if id(fp) in self.held:
                self.said.append(f"{self.ref[id(fp)]}: a mounting hole on "
                                 f"{next(iter(pads.values()))}, {self.name[id(fp)]}: fixed "
                                 "where the board has it, and a part of the circuit with "
                                 "its net")  # fmt: skip
        try:
            edge: Polygon | None = edge_shape(_outline(board))
        except ValueError:  # an outline that is not one board: nothing is told apart
            edge = None
        for fp, _ in self.parts:
            if any(_is_edge(c) for c in fp[2:]):
                ref, name = self.ref[id(fp)], self.name[id(fp)]
                if (what := _drawn(_footprint_edge(fp), edge)) is None:
                    continue
                where = (
                    f"is placed as any part, not fixed where it draws {what[1]}"
                    if id(fp) not in self.held
                    else "is fixed where the board has it"
                )
                self.said.append(f"{ref}: {what[0]} drawn in its footprint, {name}; "
                                 f"{what[1]} is read, and {ref} {where}")  # fmt: skip
        for fp, pads in sorted(self.parts, key=lambda part: natural(self.ref[id(part[0])])):
            for number, nets in _split(fp).items():
                self.said.append(f"{self.ref[id(fp)]}: pad {number} is on {', '.join(nets)}; "
                                 f"the circuit has it on {pads[number]} only")  # fmt: skip
        left = Counter(str(fp[1]) for fp in fps if _drilled_on_no_net(fp) and not _is_hole(fp))
        for name, n in sorted(left.items()):
            self.said.append(f"{name}: {n} footprint{'s' if n > 1 else ''} of drilled pads "
                             "on no net, not holes: not every pad is a hole with at most "
                             "a ring")  # fmt: skip
        for name, n in sorted(self.undefined.items()):
            self.said.append(f"{name}: {n} item{'s' if n > 1 else ''} on KiCad's UNDEFINED "
                             "layer left out of the footprint")  # fmt: skip

    def _refs(self, fps: list[Node]) -> None:
        taken = {_property(fp, "Reference").lower() for fp in fps}
        by_ref: dict[str, list[Node]] = {}
        for fp, _ in self.parts:
            by_ref.setdefault(_property(fp, "Reference"), []).append(fp)
        for ref, same in sorted(by_ref.items()):
            same.sort(key=_where)
            self.ref[id(same[0])] = ref
            for fp in same[1:]:
                self.ref[id(fp)] = new = _free(ref, taken)
                self.said.append(f"{ref} is on {len(same)} parts: the one at {_where(fp)} "
                                 f"is {new}")  # fmt: skip

    def _names(self, fps: list[Node]) -> None:
        used = {id(fp) for fp, _ in self.parts} | {id(fp) for fp in self.holes}
        wanted = {str(fp[1]) for fp in fps if id(fp) in used}
        taken = {str(fp[1]).lower() for fp in fps}
        # By name, not reference: board-only footprints share references such as REF**.
        by_name: dict[str, list[tuple[tuple, str, Node, Node]]] = {}
        for fp in fps:
            if str(fp[1]) in wanted:
                ref = self.ref.get(id(fp), _property(fp, "Reference"))
                by_name.setdefault(str(fp[1]), []).append((natural(ref), ref, fp, _package(fp)))
        for name, found in sorted(by_name.items()):
            found.sort(key=lambda f: f[0])
            versions: dict[str, list[tuple[tuple, str, Node, Node]]] = {}
            for f in found:
                versions.setdefault("\n".join(_pad_form(f[3])), []).append(f)
            # The most footprints first; ties: the one with the lowest reference.
            ranked = sorted(versions.values(), key=lambda v: -len(v))
            ranked = [v for v in ranked if any(id(f[2]) in used for f in v)]
            for i, version in enumerate(ranked):
                called = name if i == 0 else _free(name, taken)
                if i:
                    refs = ", ".join(r for _, r, fp, _ in version if id(fp) in used)
                    self.said.append(f"{name}: the version on {refs} has other pads, "
                                     f"and is written as {called}")  # fmt: skip
                for _, _, fp, _ in version:
                    self.name[id(fp)] = called
                self._lib(called, version)

    def _lib(self, name: str, found: list[tuple[tuple, str, Node, Node]]) -> None:
        """The version most of *found* carry stands for *name*; the others are listed."""
        shapes = [_shape(lib) for _, _, _, lib in found]
        most = Counter(shapes).most_common(1)[0][0]  # ties: the first seen, the lowest ref
        _, _, fp, lib = found[shapes.index(most)]
        self.libs[name] = [lib[0], name.rpartition(":")[2], *lib[2:]]
        if n := sum(_undefined(c) for c in fp[2:]):
            self.undefined[name] = n
        others = [ref for (_, ref, _, _), shape in zip(found, shapes, strict=True) if shape != most]
        if others:
            self.differ[name] = others


def mechanical(board: Node) -> dict:
    """``{"outline": [...], "holes": [...], "fixed": {}}``: the Edge.Cuts items as drawn
    (type and points), on the board or in a footprint, and each footprint that is
    mounting holes, at its position, rotation and side, with each hole's drill.

    A footprint is mounting holes when its pads are all on no net, all drilled, and
    each a hole with at most a ring of copper round it: unplated, or a round pad on a
    round drill or an oval one on an oval drill, centred on it. A round pad on a face,
    numbered as a hole is and centred on it, is that hole's ring. A hole with a ring
    of vias round it is one, and so is a heatsink's pair of pins; a prototyping board's
    square pads are not.

    A part of the circuit is mounting holes too, with ``"part": true``, its reference as
    ``circuit`` has it, when its pads are holes with at most a ring as those are, those
    on a net all on one net, the largest at least 2 mm across, and it draws no body on
    silkscreen or fab: a grounded standoff. It is fixed where the board has it, and
    stays in the circuit with its net."""
    outline = _outline(board)
    holes = []
    read = _Read(board)
    for fp in read.holes:
        at, layer = find(fp, "at"), find(fp, "layer")
        assert at is not None and layer is not None
        hole = {"ref": read.ref.get(id(fp), _property(fp, "Reference")),
                "footprint": read.name[id(fp)], "at": [float(at[1]), float(at[2])],
                "rot": float(at[3]) if len(at) > 3 else 0.0,
                "back": str(layer[1]).startswith("B."),
                "drills": [_drill(fp, p) for p in _drilled(fp)]}  # fmt: skip
        if id(fp) in read.held:
            hole["part"] = True
        holes.append(hole)
    return {"outline": outline, "holes": sorted(holes, key=lambda h: h["ref"]), "fixed": {}}


def _outline(board: Node) -> list[dict]:
    """The Edge.Cuts items as drawn, on the board or in a footprint, in an order of their
    own."""
    outline = []
    for kind in EDGE_ITEMS:
        for g in find_all(board, kind):
            layer = find(g, "layer")
            if layer is None or str(layer[1]) != "Edge.Cuts":
                continue
            item: dict = {"type": kind}
            for key in ("start", "mid", "end", "center"):
                if (xy := _xy(find(g, key))) is not None:
                    item[key] = xy
            if (pts := find(g, "pts")) is not None:
                item["pts"] = [_xy(p) for p in find_all(pts, "xy")]
            outline.append(item)
    for fp in find_all(board, "footprint"):
        outline += _footprint_edge(fp)
    outline.sort(key=lambda i: (i["type"], str(i)))
    return outline


def _shape(lib: Node) -> str:
    """A library footprint's pads and graphics, whatever order or UUIDs they carry."""

    def bare(n: Node) -> Node:
        return [bare(c) if isinstance(c, list) else c
                for c in n if not (isinstance(c, list) and c and c[0] == "uuid")]  # fmt: skip

    items = [c for c in lib[2:] if isinstance(c, list) and c[0].startswith(("pad", "fp_"))]
    return "\n".join(sorted(dumps(bare(c)) for c in items))


def _package(fp: Node) -> Node:
    """A placed footprint in library form, less what it draws on Edge.Cuts: that is the
    board's outline, which ``mechanical`` reads, and would be drawn twice. Less, too,
    what is on KiCad's UNDEFINED layer, which KiCad will not load a board with."""
    return [c for c in library_form(fp) if not _is_edge(c) and not _undefined(c)]


def footprints(board: Node) -> tuple[dict[str, Node], dict[str, list[str]]]:
    """``({footprint name: library footprint}, {footprint name: [refs that differ]})`` for
    each footprint name a part of ``circuit`` or a hole of ``mechanical`` uses.

    Each placed footprint is put back in library form (``pkidl.footprint.library_form``),
    without what it draws on Edge.Cuts, which is in ``mechanical``'s outline, or on
    KiCad's UNDEFINED layer, which KiCad will not load a board with (``renamed``).
    Versions of one name that differ in their pads are written under names of their
    own (``renamed``). Where a board's parts carry versions that differ in no more than
    their graphics, the name stands for the version most of them carry (the lowest
    reference deciding a tie), and the parts carrying another are listed.
    """
    read = _Read(board)
    return dict(sorted(read.libs.items())), read.differ
