"""Part annotations: what a part's footprint means that the footprint does not say.

A KiCad footprint is pads, drawings and a courtyard. That one end of a radio module is
its antenna, with no copper to go under it, is in the part's datasheet and at best a
drawing in the footprint. An annotation holds it as a named area, which a board file
then speaks of: ``u1.area("antenna")``.

An annotation is written against the part's pads, not a footprint's origin: libraries
draw the same part about different origins and turned different ways, and its pads are
where they are. It names two pads and says where each is in its own coordinates
(millimetres, x to the right and y down, as a footprint is drawn), and gives each area
as two opposite corners in those coordinates. ``fit`` works out where that puts the
areas in a footprint's coordinates, and refuses a footprint whose two pads are not that
far apart at a right angle, which is some other part under the same name.

Annotations for common parts ship in ``pkidl/parts``, a TOML file each, and are found
by the footprint's name whichever library it is in::

    footprint = "ESP-12E"

    [pads]
    1 = [0, 0]
    22 = [16, 0]

    [areas]
    antenna = [[0, -8.4], [16, -2.6]]

A board file gives the areas of a part that has none shipped with ``board.annotate``.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Any

from pkidl.sexpr import Node, find, find_all

Box = tuple[int, int, int, int]  # x0, y0, x1, y1, in nanometres


@dataclass(frozen=True)
class Annotation:
    """What is known about one part: the footprint name it goes by, two of its pads and
    where the annotation has them, and its named areas, all in nanometres."""

    footprint: str
    pads: Mapping[str, tuple[int, int]]
    areas: Mapping[str, Box]


def _nm(value: object) -> int:
    return round(float(str(value)) * 1_000_000)


def _point(value: Any, what: str) -> tuple[int, int]:
    if (not isinstance(value, list) or len(value) != 2
            or not all(type(v) in (int, float) for v in value)):  # fmt: skip
        raise ValueError(f"{what} is {value!r}, not a point: write [x, y] in millimetres")
    return _nm(value[0]), _nm(value[1])


def read(text: str) -> Annotation:
    """The annotation a TOML file holds. Anything in it that is not understood is
    refused, since an area that is silently left out is copper where there should be
    none."""
    data = tomllib.loads(text)
    if unknown := sorted(set(data) - {"footprint", "pads", "areas"}):
        raise ValueError(f"an annotation has footprint, pads and areas, not {', '.join(unknown)}")
    name = data.get("footprint")
    if not isinstance(name, str) or not name or ":" in name:
        raise ValueError(f"footprint is {name!r}, not a footprint's name without its library")
    pads = {str(n): _point(at, f"{name}: pad {n}") for n, at in dict(data.get("pads", {})).items()}
    if len(pads) != 2 or len(set(pads.values())) != 2:
        raise ValueError(f"{name}: an annotation is written against two pads in two places, "
                         f"not {', '.join(pads) or 'none'}")  # fmt: skip
    areas: dict[str, Box] = {}
    for area, corners in dict(data.get("areas", {})).items():
        if not isinstance(corners, list) or len(corners) != 2:
            raise ValueError(f"{name}: area {area} is {corners!r}, not two opposite corners: "
                             "write [[x, y], [x, y]]")  # fmt: skip
        (x0, y0), (x1, y1) = (_point(c, f"{name}: a corner of area {area}") for c in corners)
        if x0 == x1 or y0 == y1:
            raise ValueError(f"{name}: area {area} has no size")
        areas[area] = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
    return Annotation(name, pads, areas)


@cache
def shipped() -> Mapping[str, Annotation]:
    """The annotations that come with pkidl, by footprint name."""
    found: dict[str, Annotation] = {}
    for file in sorted(resources.files("pkidl").joinpath("parts").iterdir(), key=lambda f: f.name):
        if file.name.endswith(".toml"):
            note = read(file.read_text())
            if note.footprint in found:
                raise ValueError(f"{file.name}: {note.footprint} is annotated twice")
            found[note.footprint] = note
    return found


def _quarter(x: int, y: int, turns: int) -> tuple[int, int]:
    """A point turned through *turns* right angles."""
    for _ in range(turns):
        x, y = y, -x
    return x, y


def fit(annotation: Annotation, footprint: Node) -> dict[str, Box]:
    """*annotation*'s areas in *footprint*'s own coordinates. Raises ``ValueError``, with
    the reason, for a footprint whose two pads are not where the part has them."""
    at: dict[str, tuple[int, int]] = {}
    for pad in find_all(footprint, "pad"):
        xy = find(pad, "at")
        assert xy is not None
        at.setdefault(str(pad[1]), (_nm(xy[1]), _nm(xy[2])))
    (a, (ax, ay)), (b, (bx, by)) = annotation.pads.items()
    if missing := [n for n in (a, b) if n not in at]:
        raise ValueError(f"it has no pad {' or '.join(missing)}")
    (fx, fy), (gx, gy) = at[a], at[b]
    for turns in range(4):
        if _quarter(bx - ax, by - ay, turns) == (gx - fx, gy - fy):
            break
    else:
        raise ValueError(f"its pads {a} and {b} are {_mm(gx - fx)} mm and {_mm(gy - fy)} mm "
                         f"apart, and the part's are {_mm(bx - ax)} mm and {_mm(by - ay)} mm "
                         "apart or that turned through right angles")  # fmt: skip
    areas: dict[str, Box] = {}
    for name, (x0, y0, x1, y1) in annotation.areas.items():
        (px, py), (qx, qy) = (_quarter(x - ax, y - ay, turns) for x, y in ((x0, y0), (x1, y1)))
        areas[name] = (fx + min(px, qx), fy + min(py, qy), fx + max(px, qx), fy + max(py, qy))
    return areas


def _mm(nm: int) -> str:
    return f"{nm / 1_000_000:.6f}".rstrip("0").rstrip(".")
