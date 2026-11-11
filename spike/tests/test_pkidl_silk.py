"""pkidl places silkscreen text clear of pads, other silk and the board edge."""

from pkidl.footprint import board_xy
from pkidl.sexpr import find, find_all, parse
from pkidl.silk import nearest_clear_spot, place_references, text_box

PART = """(footprint "R" (at {x} {y}) (layer "F.Cu")
  (property "Reference" "{ref}" (at 0 0) (layer "F.SilkS")
    (effects (font (size 1 1) (thickness 0.15))))
  (fp_line (start -1.5 -1) (end 1.5 -1) (layer "F.CrtYd"))
  (fp_line (start -1.5 1) (end 1.5 1) (layer "F.CrtYd"))
  (pad "1" smd rect (at -0.9 0) (size 1 1.2) (layers "F.Cu"))
  (pad "2" smd rect (at 0.9 0) (size 1 1.2) (layers "F.Cu")))"""
OUTLINE = (0.0, 0.0, 40.0, 30.0)


def _ref_box(fp):
    prop = next(p for p in find_all(fp, "property") if p[1] == "Reference")
    at = find(prop, "at")
    assert at is not None
    return text_box(str(prop[2]), board_xy(fp, float(at[1]), float(at[2])), 1.0, 0.15, 0.0)


def test_reference_leaves_its_pads():
    fp = parse(PART.format(x=20, y=15, ref="R1"))
    assert place_references([fp], OUTLINE) == {}
    x0, y0, x1, y1 = _ref_box(fp)
    assert y1 <= 15 - 0.6 or y0 >= 15 + 0.6  # above or below the 1.2 mm pads


def test_reference_with_no_room_goes_to_fab():
    fp = parse(PART.format(x=20, y=15, ref="R1"))
    # Pads of a neighbour fill every spot around it.
    wall = parse('(footprint "W" (at 20 15) (layer "F.Cu") (property "Reference" "W1" '
                 '(at 0 0) (layer "F.Fab")) (pad "1" smd rect (at 0 0) (size 14 12) '
                 '(layers "F.Cu")))')  # fmt: skip
    assert place_references([fp, wall], OUTLINE) == {"R1": "F.Fab"}


def test_rotated_text_box_is_rotated():
    x0, y0, x1, y1 = text_box("ABCD", (0, 0), 1.0, 0.0, 90)
    assert round(x1 - x0, 6) == 1.0 and round(y1 - y0, 6) == 4.0
    x0, y0, x1, y1 = text_box("ABCD", (0, 0), 1.0, 0.0, 45)
    assert round(x1 - x0, 3) == round(y1 - y0, 3) == round(5 / 2**0.5, 3)


def test_nearest_clear_spot_steps_off_a_part():
    fp = parse(PART.format(x=20, y=15, ref="R1"))
    spot = nearest_clear_spot([fp], "LABEL", (20, 15), OUTLINE)
    assert spot is not None and spot != (20, 15)
    bx0, by0, bx1, by1 = text_box("LABEL", spot, 1.0, 0.15, 0)
    assert bx1 <= 20 - 1.4 or bx0 >= 20 + 1.4 or by1 <= 15 - 0.6 or by0 >= 15 + 0.6


def test_reference_skips_a_spot_on_a_neighbours_pad():
    """The first spot tried, above the part, is on a neighbour's pad: the next is used."""
    fp = parse(PART.format(x=20, y=15, ref="R1"))
    above = parse('(footprint "P" (at 20 13.3) (layer "F.Cu") (property "Reference" "P1" '
                  '(at 0 0) (layer "F.Fab")) (pad "1" smd rect (at 0 0) (size 3 1) '
                  '(layers "F.Cu")))')  # fmt: skip
    assert place_references([fp, above], OUTLINE) == {}
    x0, y0, x1, y1 = _ref_box(fp)
    assert y0 >= 15 + 0.6  # below the part, not on the pad above it
