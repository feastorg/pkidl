"""Read the inputs a board is designed from out of an existing KiCad board.

A board is designed from its circuit and its mechanical requirements. For a board
that exists only as a ``.kicad_pcb`` (the corpus), both are read from it here:

- ``circuit``: each part's reference, value, footprint and pad -> net map. No
  position, side or rotation: those are the layout, which is designed, not read.
- ``mechanical``: what a designer is given: the board outline and the mounting
  holes. Fixed connectors are added per board, with a reason, when its board file
  is written.
- ``footprints``: the library footprint each footprint name stands for, which the
  board carries a copy of in every placed part. It is the part's package, as a
  footprint library holds it: no position, rotation or side.

Nothing else of the board's layout is read: no tracks, vias, pours or positions of
other parts.
"""

from __future__ import annotations

from collections import Counter

from pkidl.circuit import natural
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
    if not isinstance(item, list) or not str(item[0]).startswith("fp_"):
        return False
    layer = find(item, "layer")
    return layer is not None and str(layer[1]) == "Edge.Cuts"


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


def circuit(board: Node) -> dict:
    """``{"parts": [{ref, value, footprint, pads: {number: net}}], "nets": [...]}``,
    parts sorted by reference. Pads on no net are left out of ``pads``; a footprint
    with no pad on a net (a logo, a mounting hole) is not part of the circuit, and nor
    is one KiCad never annotated from a schematic (reference empty or with ``*``, as
    ``REF**``): those are board-only, such as vias placed as footprints."""
    parts = []
    nets: set[str] = set()
    for fp in find_all(board, "footprint"):
        ref = _property(fp, "Reference")
        if not ref or "*" in ref:
            continue
        pads: dict[str, str] = {}
        for pad in find_all(fp, "pad"):
            net = find(pad, "net")
            if net is not None and str(net[-1]):
                pads[str(pad[1])] = str(net[-1])
                nets.add(str(net[-1]))
        if not pads:
            continue
        parts.append({"ref": ref, "value": _property(fp, "Value"),
                      "footprint": str(fp[1]), "pads": dict(sorted(pads.items()))})  # fmt: skip
    return {"parts": sorted(parts, key=lambda p: p["ref"]), "nets": sorted(nets)}


def mechanical(board: Node) -> dict:
    """``{"outline": [...], "holes": [...], "fixed": {}}``: the Edge.Cuts items as drawn
    (type and points), on the board or in a footprint, and each footprint that is
    mounting holes, at its position, rotation and side, with each hole's drill.

    A footprint is mounting holes when its pads are all on no net, all drilled, and
    each a hole with at most a ring of copper round it: unplated, or a round pad on a
    round drill or an oval one on an oval drill, centred on it. A hole with a ring of
    vias round it is one, and so is a heatsink's pair of pins; a prototyping board's
    square pads are not."""
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
    holes = []
    for fp in find_all(board, "footprint"):
        pads = find_all(fp, "pad")
        drilled = [p for p in pads if find(p, "drill") is not None]
        if not pads or len(drilled) != len(pads):
            continue
        if any((n := find(p, "net")) is not None and str(n[-1]) for p in pads):
            continue
        if not all(_ringed(p) for p in pads):
            continue
        at, layer = find(fp, "at"), find(fp, "layer")
        assert at is not None and layer is not None
        holes.append({"ref": _property(fp, "Reference"), "footprint": str(fp[1]),
                      "at": [float(at[1]), float(at[2])],
                      "rot": float(at[3]) if len(at) > 3 else 0.0,
                      "back": str(layer[1]).startswith("B."),
                      "drills": [_drill(fp, p) for p in drilled]})  # fmt: skip
    outline.sort(key=lambda i: (i["type"], str(i)))
    return {"outline": outline, "holes": sorted(holes, key=lambda h: h["ref"]), "fixed": {}}


def _shape(lib: Node) -> str:
    """A library footprint's pads and graphics, whatever order or UUIDs they carry."""

    def bare(n: Node) -> Node:
        return [bare(c) if isinstance(c, list) else c
                for c in n if not (isinstance(c, list) and c and c[0] == "uuid")]  # fmt: skip

    items = [c for c in lib[2:] if isinstance(c, list) and c[0].startswith(("pad", "fp_"))]
    return "\n".join(sorted(dumps(bare(c)) for c in items))


def _package(fp: Node) -> Node:
    """A placed footprint in library form, less what it draws on Edge.Cuts: that is the
    board's outline, which ``mechanical`` reads, and would be drawn twice."""
    return [c for c in library_form(fp) if not _is_edge(c)]


def footprints(board: Node) -> tuple[dict[str, Node], dict[str, list[str]]]:
    """``({footprint name: library footprint}, {footprint name: [refs that differ]})`` for
    each footprint name a part of ``circuit`` or a hole of ``mechanical`` uses.

    Each placed footprint is put back in library form (``pkidl.footprint.library_form``),
    without what it draws on Edge.Cuts, which is in ``mechanical``'s outline.
    Where a board's parts carry different versions under one name, the name stands for
    the version most of them carry (the lowest reference deciding a tie), and the parts
    carrying another are listed.
    """
    # By name, not reference: board-only footprints share references such as REF**.
    wanted = {p["footprint"] for p in circuit(board)["parts"]}
    wanted |= {h["footprint"] for h in mechanical(board)["holes"]}
    by_name: dict[str, list[tuple[tuple, str, Node]]] = {}
    for fp in find_all(board, "footprint"):
        if str(fp[1]) in wanted:
            ref = _property(fp, "Reference")
            by_name.setdefault(str(fp[1]), []).append((natural(ref), ref, _package(fp)))
    libs: dict[str, Node] = {}
    differ: dict[str, list[str]] = {}
    for name, found in sorted(by_name.items()):
        found.sort(key=lambda f: f[0])
        shapes = [_shape(lib) for _, _, lib in found]
        most = Counter(shapes).most_common(1)[0][0]  # ties: the first seen, the lowest ref
        libs[name] = found[shapes.index(most)][2]
        others = [ref for (_, ref, _), shape in zip(found, shapes, strict=True) if shape != most]
        if others:
            differ[name] = others
    return libs, differ
