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

import re
from collections import Counter
from pathlib import Path

from pkidl.footprint import library_form, pad_xy
from pkidl.sexpr import Node, dumps, find, find_all

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


def footprint_path(name: str) -> Path:
    """Where a footprint name's library footprint is kept under a board's ``footprints/``:
    KiCad's own library layout, ``<library>.pretty/<footprint>.kicad_mod``; a name with no
    library sits at the top."""
    lib, _, fp = name.rpartition(":")
    return Path(f"{lib}.pretty" if lib else "", f"{fp}.kicad_mod")


def _natural(ref: str) -> tuple:
    return tuple(int(t) if t.isdigit() else t for t in re.split(r"(\d+)", ref))


def _shape(lib: Node) -> str:
    """A library footprint's pads and graphics, whatever order or UUIDs they carry."""

    def bare(n: Node) -> Node:
        return [bare(c) if isinstance(c, list) else c
                for c in n if not (isinstance(c, list) and c and c[0] == "uuid")]  # fmt: skip

    items = [c for c in lib[2:] if isinstance(c, list) and c[0].startswith(("pad", "fp_"))]
    return "\n".join(sorted(dumps(bare(c)) for c in items))


def footprints(board: Node) -> tuple[dict[str, Node], dict[str, list[str]]]:
    """``({footprint name: library footprint}, {footprint name: [refs that differ]})`` for
    each footprint name a part of ``circuit`` or a hole of ``mechanical`` uses.

    Each placed footprint is put back in library form (``pkidl.footprint.library_form``).
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
            by_name.setdefault(str(fp[1]), []).append((_natural(ref), ref, library_form(fp)))
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
