"""pkidl places footprints exactly as KiCad does.

The fixture holds the eight footprints of the hand-drawn Loaf_x004
(feastorg/Loaf_x004@ebf47df, hardware/BREAD_Loaf.kicad_pcb) as KiCad saved them:
front and back, rotated 0 and 180 degrees. Each is re-placed by pkidl from its
library file and compared with KiCad's copy: pads, Reference/Value text and
graphics. Rotations of 90 and 270 degrees do not occur on this board, so they
are not covered here.
"""

from pathlib import Path

import pytest

from kidl_spike import libs
from pkidl.footprint import Placement, place
from pkidl.sexpr import Node, find, find_all, parse

FIXTURE = Path(__file__).parent / "fixtures" / "loaf_x004_footprints.kicad_pcb"
GRAPHICS = ("fp_line", "fp_rect", "fp_circle", "fp_arc", "fp_poly")
KICAD_FOOTPRINTS = find_all(parse(FIXTURE.read_text()), "footprint")


def _prop(fp: Node, name: str) -> Node:
    return next(p for p in find_all(fp, "property") if p[1] == name)


def _at(node: Node) -> tuple[float, float, float]:
    at = find(node, "at")
    assert at is not None
    x, y, *rest = (float(v) for v in at[1:])
    return (x, y, rest[0] if rest else 0.0)


def _attr(node: Node, key: str) -> tuple | None:
    found = find(node, key)
    return tuple(found[1:]) if found is not None else None


def _summary(fp: Node) -> tuple:
    pads = [
        (p[1], _at(p), _attr(p, "size"), _attr(p, "layers"), _attr(p, "net"), _attr(p, "drill"))
        for p in find_all(fp, "pad")
    ]
    texts = []
    for name in ("Reference", "Value"):
        t = _prop(fp, name)
        effects = find(t, "effects")
        justify = find(effects, "justify") if effects is not None else None
        texts.append((name, _at(t), _attr(t, "layer"), tuple(justify[1:]) if justify else ()))
    graphics = sorted(
        repr((g[0], _attr(g, "layer"), [_attr(g, k) for k in ("start", "mid", "end", "center")]))
        for g in fp
        if isinstance(g, list) and g[0] in GRAPHICS
    )
    return pads, texts, graphics


@pytest.fixture(scope="module")
def footprint_file():
    try:
        libs.master_lib_root()
    except libs.LibraryError as e:
        pytest.skip(str(e))
    if libs.stock_dirs()[1] is None:
        pytest.skip("no stock KiCad footprint library present")
    return libs.footprint_file


@pytest.mark.parametrize(
    "theirs", KICAD_FOOTPRINTS, ids=[_prop(fp, "Reference")[2] for fp in KICAD_FOOTPRINTS]
)
def test_placement_matches_kicad(theirs, footprint_file):
    x, y, rot = _at(theirs)
    layer = find(theirs, "layer")
    assert layer is not None
    nets = {}
    for p in find_all(theirs, "pad"):
        net = find(p, "net")
        if net is not None:
            nets[p[1]] = net[1]
    placement = Placement(
        theirs[1],
        _prop(theirs, "Reference")[2],
        _prop(theirs, "Value")[2],
        x,
        y,
        rot,
        back=layer[1] == "B.Cu",
        nets=nets,
    )
    mine = place(footprint_file(theirs[1]), placement)
    assert _summary(mine) == _summary(theirs)
