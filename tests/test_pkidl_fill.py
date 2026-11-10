"""pkidl.fill: pour fills before routing, given to the router as planes."""

from shapely.geometry import Point as SPoint
from shapely.geometry import Polygon
from shapely.ops import unary_union

from pkidl.fill import prefill
from pkidl.sexpr import parse

OUTLINE = [(0.0, 0.0), (30.0, 0.0), (30.0, 30.0), (0.0, 30.0)]
TOL = 0.001  # mm: coordinates are rounded to 0.1 um, the DSN resolution


def _fp(ref: str, x: float, y: float, pads: list[tuple[str, float, float, float, str]]) -> str:
    body = "".join(
        f'(pad "{n}" smd rect (at {px} {py}) (size {s} {s}) (layers "F.Cu") (net "{net}"))'
        for n, px, py, s, net in pads
    )
    return f'(footprint "t" (layer "F.Cu") (at {x} {y} 0) (property "Reference" "{ref}") {body})'


def _zone(
    net: str, pts: list[tuple[float, float]], priority: int = 0, keepout: bool = False
) -> str:
    rules = (
        "(keepout (tracks allowed) (vias allowed) (pads allowed) (copperpour not_allowed)"
        " (footprints allowed))"
    )
    xy = " ".join(f"(xy {x} {y})" for x, y in pts)
    return (
        f'(zone (net "{net}") (layer "F.Cu") (priority {priority})'
        f" (connect_pads (clearance 0.5)) (min_thickness 0.25)"
        f" {rules if keepout else ''} (polygon (pts {xy})))"
    )


def _items(*nodes: str):
    return [parse(n) for n in nodes]


def _covered(planes, net: str):
    return unary_union([Polygon(p) for n, layer, p in planes if n == net and layer == "F.Cu"])


SQUARE = [(2.0, 2.0), (28.0, 2.0), (28.0, 28.0), (2.0, 28.0)]


def test_other_nets_copper_keeps_its_clearance():
    items = _items(
        _fp("R1", 15, 15, [("1", -5, 0, 1, "GND"), ("2", 5, 0, 1, "SIG")]), _zone("GND", SQUARE)
    )
    fill = _covered(prefill(items, OUTLINE, 0.5), "GND")
    sig = SPoint(20, 15).buffer(0.5, cap_style="square")  # the SIG pad
    assert fill.distance(sig) >= 0.5 - TOL  # the zone's clearance
    assert fill.contains(SPoint(5, 25))  # and it fills elsewhere


def test_a_piece_touching_none_of_its_nets_copper_is_dropped():
    items = _items(_fp("R1", 15, 15, [("1", 0, 0, 1, "SIG")]), _zone("GND", SQUARE))
    assert prefill(items, OUTLINE, 0.5) == []


def test_a_higher_priority_pour_of_another_net_is_kept_clear_of():
    hi = [(10.0, 10.0), (20.0, 10.0), (20.0, 20.0), (10.0, 20.0)]
    items = _items(
        _fp("R1", 15, 15, [("1", 0, 0, 1, "VCC")]),
        _fp("R2", 5, 5, [("1", 0, 0, 1, "GND")]),
        _zone("GND", SQUARE, priority=0),
        _zone("VCC", hi, priority=1),
    )
    planes = prefill(items, OUTLINE, 0.5)
    vcc, gnd = _covered(planes, "VCC"), _covered(planes, "GND")
    assert vcc.contains(SPoint(12, 12))
    assert gnd.distance(vcc) >= 0.5 - TOL


def test_a_no_pour_corridor_is_cut_and_the_far_side_dropped():
    """A corridor across the whole pour leaves two pieces; only the one with a GND pad stays."""
    corridor = [(0.0, 14.0), (30.0, 14.0), (30.0, 16.0), (0.0, 16.0)]
    items = _items(
        _fp("R1", 5, 5, [("1", 0, 0, 1, "GND")]),
        _zone("GND", SQUARE),
        _zone("", corridor, keepout=True),
    )
    fill = _covered(prefill(items, OUTLINE, 0.5), "GND")
    assert fill.contains(SPoint(10, 8))
    assert not fill.intersects(SPoint(10, 15))  # the corridor
    assert not fill.contains(SPoint(10, 22))  # the far side: an island


def test_planes_have_no_holes_and_cover_the_fill():
    """A pad in the middle leaves a hole; a DSN plane can't have one, so the fill is split."""
    items = _items(
        _fp("R1", 15, 15, [("1", 0, 0, 2, "SIG")]),
        _fp("R2", 5, 5, [("1", 0, 0, 1, "GND")]),
        _zone("GND", SQUARE),
    )
    planes = [p for p in prefill(items, OUTLINE, 0.5) if p[0] == "GND"]
    assert len(planes) >= 2
    assert all(Polygon(p).is_valid and not Polygon(p).interiors for _, _, p in planes)
    whole = Polygon(SQUARE).difference(SPoint(15, 15).buffer(1.0 + 0.5, cap_style="square"))
    assert abs(unary_union([Polygon(p) for _, _, p in planes]).area - whole.area) < 0.5
