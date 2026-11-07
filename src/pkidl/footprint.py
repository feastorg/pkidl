"""Place a library footprint on a board, the way KiCad stores it.

KiCad keeps a placed footprint's children in footprint-local coordinates. Placing
one on the back mirrors those coordinates in Y and swaps F./B. layers; the
footprint's own ``(at x y rot)`` carries position and rotation. Pad angles are
stored absolute (local angle plus footprint rotation); text angles are absolute
and kept upright. ``tests/test_pkidl_footprint.py`` checks these rules against
every footprint of a board KiCad itself saved.
"""

from __future__ import annotations

import copy
import math
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from pkidl.sexpr import Node, Sym, find, find_all, num, parse

# Fixed namespace so generated UUIDs depend only on what they identify.
NAMESPACE = uuid.UUID("5b1c0f3e-9a5d-4c4e-8a0b-6f1d2e3c4b5a")

_XY_KEYS = {"at", "start", "end", "mid", "center", "xy", "offset"}
_TEXT_KEYS = {"property", "fp_text"}
_DROP = {"version", "generator", "generator_version"}


def gen_uuid(*parts: str) -> str:
    return str(uuid.uuid5(NAMESPACE, ":".join(parts)))


def _norm(angle: float) -> float:
    """Normalise to (-180, 180]."""
    a = angle % 360
    return a - 360 if a > 180 else a


def _upright(angle: float) -> float:
    """KiCad keeps footprint text readable: never upside down."""
    a = _norm(angle)
    if a > 90 or a <= -90:
        a = _norm(a + 180)
    return a


def _swap_layer(name: str) -> str:
    if name.startswith("F."):
        return "B." + name[2:]
    if name.startswith("B."):
        return "F." + name[2:]
    return name


@dataclass
class Placement:
    lib_id: str  # "Library:Footprint"
    ref: str
    value: str
    x: float
    y: float
    rot: float = 0.0
    back: bool = False
    nets: dict[str, str] = field(default_factory=dict)  # pad number -> net name
    path: str | None = None  # "/<symbol uuid>", links the footprint to the schematic
    sheetfile: str | None = None
    sheetname: str = "/"
    fields: dict[str, str] = field(default_factory=dict)  # symbol fields, e.g. Description
    board_only: bool = False  # no schematic symbol; schematic parity skips it
    in_bom: bool | None = None  # override the library's exclude_from_bom to match the symbol
    solid_pads: bool = False  # pads join copper pours directly, without thermal reliefs


def _flip(node: Node) -> None:
    """Mirror a footprint child in Y and swap its layers, recursively."""
    head = node[0]
    if head in _XY_KEYS and len(node) >= 3 and not isinstance(node[2], list):
        node[2] = num(-float(node[2]))
    if head in ("layer", "layers"):
        for i in range(1, len(node)):
            if isinstance(node[i], str):
                node[i] = type(node[i])(_swap_layer(node[i]))
    for child in node[1:]:
        if isinstance(child, list):
            _flip(child)


def _set_angle(item: Node, angle: float) -> None:
    at = find(item, "at")
    if at is None:
        return
    del at[3:]
    if angle:
        at.append(num(angle))


def _local_angle(item: Node) -> float:
    at = find(item, "at")
    return float(at[3]) if at is not None and len(at) > 3 else 0.0


def place(library_footprint: Path | str, p: Placement) -> Node:
    """Return a board ``(footprint ...)`` node for placement *p*."""
    text = (
        library_footprint.read_text() if isinstance(library_footprint, Path) else library_footprint
    )
    lib = parse(text)

    out: Node = [Sym("footprint"), p.lib_id]
    out.append([Sym("layer"), "B.Cu" if p.back else "F.Cu"])
    out.append([Sym("uuid"), gen_uuid("fp", p.ref)])
    at = [Sym("at"), num(p.x), num(p.y)]
    if p.rot:
        at.append(num(p.rot))
    out.append(at)

    meta_done = False
    for child in lib[2:]:
        if not isinstance(child, list) or child[0] in _DROP or child[0] == "layer":
            continue
        item = copy.deepcopy(child)
        kind = item[0]
        local = _local_angle(item)
        if p.back:
            _flip(item)
            local = -local

        if kind == "attr" and p.board_only and Sym("board_only") not in item:
            item.insert(1, Sym("board_only"))
        if kind == "attr" and p.in_bom is not None:
            excluded = Sym("exclude_from_bom") in item
            if p.in_bom and excluded:
                item.remove(Sym("exclude_from_bom"))
            elif not p.in_bom and not excluded:
                item.append(Sym("exclude_from_bom"))
        if kind == "pad":
            _set_angle(item, _norm(local + p.rot))
            number = item[1]
            if number in p.nets:
                tail = find(item, "uuid")
                net = [Sym("net"), p.nets[number]]
                if tail is not None:
                    item.insert(item.index(tail), net)
                else:
                    item.append(net)
            if p.solid_pads and find(item, "zone_connect") is None:
                tail = find(item, "uuid")
                solid = [Sym("zone_connect"), Sym("2")]
                if tail is not None:
                    item.insert(item.index(tail), solid)
                else:
                    item.append(solid)
            if find(item, "uuid") is None:
                item.append([Sym("uuid"), gen_uuid("pad", p.ref, number, str(len(out)))])
        elif kind in _TEXT_KEYS:
            _set_angle(item, _upright(local + p.rot))
            if kind == "property" and item[1] == "Reference":
                item[2] = p.ref
            elif kind == "property" and item[1] == "Value":
                item[2] = p.value
            elif kind == "property" and item[1] in p.fields:
                item[2] = p.fields[item[1]]
            if p.back:
                text_effects = find(item, "effects")
                if text_effects is not None:
                    justify = find(text_effects, "justify")
                    if justify is None:
                        text_effects.append([Sym("justify"), Sym("mirror")])
                    elif Sym("mirror") not in justify:
                        justify.append(Sym("mirror"))

        # Schematic linkage goes after the properties, as KiCad writes it.
        if not meta_done and kind not in ("descr", "tags", "property"):
            for name in sorted(p.fields):
                if any(q[1] == name for q in find_all(out, "property")):
                    continue
                fab = "B.Fab" if p.back else "F.Fab"
                effects: Node = [Sym("effects"), [Sym("font"), [Sym("size"), num(1.27), num(1.27)],
                                                  [Sym("thickness"), num(0.15)]]]  # fmt: skip
                if p.back:
                    effects.append([Sym("justify"), Sym("mirror")])
                out.append(
                    [Sym("property"), name, p.fields[name], [Sym("at"), num(0), num(0), num(0)],
                     [Sym("layer"), fab], [Sym("hide"), Sym("yes")],
                     [Sym("uuid"), gen_uuid("field", p.ref, name)], effects]
                )  # fmt: skip
            if p.path:
                out.append([Sym("path"), p.path])
                out.append([Sym("sheetname"), p.sheetname])
            if p.sheetfile:
                out.append([Sym("sheetfile"), p.sheetfile])
            meta_done = True
        out.append(item)
    return out


def pads(footprint: Node) -> list[Node]:
    return find_all(footprint, "pad")


def pad_xy(footprint: Node, number: str) -> tuple[float, float]:
    """Board position of a placed footprint's pad *number* (y down, CCW angles)."""
    at = find(footprint, "at")
    assert at is not None
    x0, y0 = float(at[1]), float(at[2])
    r = math.radians(float(at[3]) if len(at) > 3 else 0.0)
    pad = next(p for p in pads(footprint) if p[1] == number)
    pa = find(pad, "at")
    assert pa is not None
    lx, ly = float(pa[1]), float(pa[2])
    return (
        round(x0 + lx * math.cos(r) + ly * math.sin(r), 6),
        round(y0 - lx * math.sin(r) + ly * math.cos(r), 6),
    )
