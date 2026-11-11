"""pkidl.measure: a net's filled pieces joined across layers by its vias and pads."""

from pkidl.measure import regions
from pkidl.sexpr import parse

ZONE = """(zone (net "{net}") (layer "{layer}")
  (filled_polygon (layer "{layer}") (pts {pts})))"""


def _square(x0: float, y0: float, x1: float, y1: float) -> str:
    return " ".join(f"(xy {x} {y})" for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)))


def _board(*items: str) -> list:
    return parse("(kicad_pcb " + " ".join(items) + ")")


FRONT = ZONE.format(net="GND", layer="F.Cu", pts=_square(0, 0, 10, 10))
BACK = ZONE.format(net="GND", layer="B.Cu", pts=_square(5, 5, 20, 20))


def test_a_via_in_both_pieces_joins_them():
    joined = _board(FRONT, BACK, '(via (at 7 7) (size 0.8) (net "GND"))')
    assert regions(joined)["GND"].count == 1
    assert regions(joined)["GND"].pieces == {"F.Cu": 1, "B.Cu": 1}


def test_pieces_without_a_shared_joint_stay_apart():
    outside = _board(FRONT, BACK, '(via (at 15 15) (size 0.8) (net "GND"))')
    other_net = _board(FRONT, BACK, '(via (at 7 7) (size 0.8) (net "VS"))')
    assert regions(outside)["GND"].count == 2
    assert regions(other_net)["GND"].count == 2


def test_a_through_hole_pad_of_the_net_joins_them():
    pad = """(footprint "J" (at 7 7) (property "Reference" "J1")
      (pad "1" thru_hole circle (at 0 0) (size 2 2) (layers "*.Cu") (net "GND")))"""
    assert regions(_board(FRONT, BACK, pad))["GND"].count == 1


def test_keepouts_and_other_nets_are_not_counted():
    keepout = '(zone (net "") (layer "F.Cu") (keepout (tracks not_allowed)))'
    vs = ZONE.format(net="VS", layer="F.Cu", pts=_square(30, 30, 40, 40))
    got = regions(_board(FRONT, keepout, vs), {"GND"})
    assert set(got) == {"GND"} and got["GND"].count == 1
