"""Read the inputs a board is designed from out of an existing KiCad board.

A board is designed from its circuit and its mechanical requirements. For a board
that exists only as a ``.kicad_pcb`` (the corpus), both are read from it here:

- ``circuit``: each part's reference, value, footprint and pad -> net map. No
  position, side or rotation: those are the layout, which is designed, not read.
- ``mechanical``: what a designer is given: the board outline and the mounting
  holes. Fixed connectors are added per board, with a reason, when its board file
  is written.

Nothing else of the board's layout is read: no tracks, vias, pours or positions of
other parts.
"""

from __future__ import annotations

from pkidl.footprint import pad_xy
from pkidl.sexpr import Node, find, find_all

EDGE_ITEMS = ("gr_line", "gr_arc", "gr_rect", "gr_circle", "gr_poly")


def _property(fp: Node, name: str) -> str:
    return next((str(p[2]) for p in find_all(fp, "property") if p[1] == name), "")


def _xy(node: Node | None) -> list[float] | None:
    return None if node is None else [float(node[1]), float(node[2])]


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
    (type and points), and each footprint whose pads are all on no net and drilled (a
    mounting hole), at its position, with each hole's drill."""
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
    holes = []
    for fp in find_all(board, "footprint"):
        pads = find_all(fp, "pad")
        drilled = [p for p in pads if find(p, "drill") is not None]
        if not pads or len(drilled) != len(pads):
            continue
        if any((n := find(p, "net")) is not None and str(n[-1]) for p in pads):
            continue
        at = find(fp, "at")
        assert at is not None
        holes.append({"ref": _property(fp, "Reference"), "footprint": str(fp[1]),
                      "at": [float(at[1]), float(at[2])],
                      "drills": [[*pad_xy(fp, str(p[1])), float(find(p, "drill")[1])]  # type: ignore[index]
                                 for p in drilled]})  # fmt: skip
    outline.sort(key=lambda i: (i["type"], str(i)))
    return {"outline": outline, "holes": sorted(holes, key=lambda h: h["ref"]), "fixed": {}}
