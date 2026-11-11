"""pkidl's stitching vias: a grid, kept off other copper, holes and the edge."""

import math

from pkidl.sexpr import parse
from pkidl.stitch import stitch_points

OUTLINE = [(0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0)]
TRACK = '(segment (start 0 10) (end 20 10) (width 1) (layer "F.Cu") (net "{net}"))'


def _points(items, keep_from=None):
    return stitch_points(items, "GND", OUTLINE, pitch=2.0, diameter=0.8, clearance=0.5,
                         edge=0.5, keep_from=keep_from)  # fmt: skip


def test_grid_keeps_off_other_nets_and_the_edge():
    pts = _points([parse(TRACK.format(net="SIG"))])
    assert pts
    # A via (r 0.4) keeps 0.5 from the 1 mm track's edge: centres at least 1.4 from y=10.
    assert all(abs(y - 10) >= 1.4 for _, y in pts)
    assert all(0.9 <= c <= 19.1 for p in pts for c in p)
    assert any(abs(y - 10) < 1.4 for _, y in _points([parse(TRACK.format(net="GND"))]))


def test_keep_from_holds_a_net_further_away():
    pts = _points([parse(TRACK.format(net="HV"))], keep_from={"HV": 5.6})
    assert pts and all(abs(y - 10) - 0.5 - 0.4 >= 5.6 for _, y in pts)


def test_pads_of_any_net_are_avoided():
    pad = parse('(footprint "P" (at 9 9) (property "Reference" "P1") (pad "1" thru_hole '
                'circle (at 0 0) (size 2 2) (layers "*.Cu") (net "GND")))')  # fmt: skip
    pts = _points([pad])
    assert all(math.dist(p, (9, 9)) >= 0.4 + math.hypot(2, 2) / 2 + 0.5 for p in pts)
    assert (9.0, 9.0) not in pts


def test_no_via_in_a_pocket_the_fill_would_drop():
    """A square of another net's tracks encloses a pocket; the pour there is an island the
    fill drops, so a via in it would connect on one layer only. None goes there, on
    either layer's account."""
    box = [((6, 6), (14, 6)), ((14, 6), (14, 14)), ((14, 14), (6, 14)), ((6, 14), (6, 6))]
    items = [parse(f'(segment (start {a[0]} {a[1]}) (end {b[0]} {b[1]}) (width 0.5) '
                   f'(layer "B.Cu") (net "SIG"))') for a, b in box]  # fmt: skip
    pts = _points(items)
    assert pts
    assert not [p for p in pts if 6 < p[0] < 14 and 6 < p[1] < 14]


def test_no_via_in_an_avoided_area():
    keepout = [(4.0, 4.0), (16.0, 4.0), (16.0, 16.0), (4.0, 16.0)]
    pts = stitch_points([], "GND", OUTLINE, pitch=2.0, diameter=0.8, clearance=0.5, edge=0.5,
                        avoid=[keepout])  # fmt: skip
    assert pts and not [p for p in pts if 3.1 < p[0] < 16.9 and 3.1 < p[1] < 16.9]
