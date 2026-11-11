"""pkidl.footprint.library_form: a placed footprint put back as its library footprint."""

import pytest

from pkidl.footprint import Placement, library_form, place
from pkidl.sexpr import Node, dumps, find, find_all, parse

LIB = """(footprint "R_Test" (version 20260206) (generator "pkidl") (generator_version "0.1")
  (layer "F.Cu")
  (property "Reference" "REF**" (at 0 0) (layer "F.SilkS") (uuid "u1")
    (effects (font (size 1 1) (thickness 0.15))))
  (property "Value" "R_Test" (at 0 0) (layer "F.Fab") (uuid "u2")
    (effects (font (size 1 1) (thickness 0.15))))
  (attr smd)
  (fp_line (start -1 -0.5) (end 1 -0.5) (stroke (width 0.12) (type solid)) (layer "F.SilkS")
    (uuid "u3"))
  (fp_line (start -1.5 -1) (end 1.5 0.8) (stroke (width 0.05) (type solid)) (layer "F.CrtYd")
    (uuid "u4"))
  (fp_text user "${REFERENCE}" (at 0.3 1.2) (layer "F.Fab") (uuid "u5")
    (effects (font (size 0.5 0.5) (thickness 0.08))))
  (pad "1" smd rect (at -0.9 0.2 90) (size 1 1.3) (layers "F.Cu" "F.Mask" "F.Paste")
    (uuid "u6"))
  (pad "2" smd rect (at 0.9 0.2) (size 1 1.3) (layers "F.Cu" "F.Mask" "F.Paste") (uuid "u7")))"""

# As KiCad saves a part on the back, turned, its reference moved off the part and hidden.
PLACED = """(footprint "Lib:R_Test" (layer "B.Cu") (uuid "b0") (at 120.5 61.25 90)
  (property "Reference" "R7" (at -4.6 0.3 180) (layer "Cmts.User") (hide yes) (uuid "b1")
    (effects (font (size 1 1) (thickness 0.15)) (justify mirror)))
  (property "Value" "10k" (at 0 -2 90) (layer "B.Fab") (uuid "b2")
    (effects (font (size 1 1) (thickness 0.15)) (justify mirror)))
  (property "MPN" "RC0805" (at 0 0 90) (layer "B.Fab") (hide yes) (uuid "b3")
    (effects (font (size 1 1) (thickness 0.15)) (justify mirror)))
  (path "/0000-1111") (sheetname "/") (sheetfile "board.kicad_sch")
  (attr smd)
  (fp_line (start -1 0.5) (end 1 0.5) (stroke (width 0.12) (type solid)) (layer "B.SilkS")
    (uuid "b4"))
  (pad "1" smd rect (at -0.9 -0.2) (size 1 1.3) (layers "B.Cu" "B.Mask" "B.Paste")
    (net "VCC") (pinfunction "A") (pintype "passive") (uuid "b5"))
  (pad "2" smd rect (at 0.9 -0.2 90) (size 1 1.3) (layers "B.Cu" "B.Mask" "B.Paste")
    (net "OUT") (uuid "b6")))"""


def bare(node: Node) -> Node:
    """A node without its UUIDs."""
    return [bare(c) if isinstance(c, list) else c
            for c in node if not (isinstance(c, list) and c and c[0] == "uuid")]  # fmt: skip


def placed(rot: float, back: bool) -> Node:
    p = Placement("Lib:R_Test", "R7", "10k", 120.5, 61.25, rot, back,
                  nets={"1": "VCC", "2": "OUT"}, path="/0000-1111", sheetfile="board.kicad_sch",
                  fields={"MPN": "RC0805"})  # fmt: skip
    return place(LIB, p)


@pytest.mark.parametrize("rot", [0, 45, 90, 180, 270])
@pytest.mark.parametrize("back", [False, True])
def test_library_form_undoes_place(rot, back):
    assert dumps(bare(library_form(placed(rot, back)))) == dumps(bare(parse(LIB)))


def test_nothing_of_the_placement_is_left():
    board_fp = parse(PLACED)
    lib = library_form(board_fp)
    assert lib[1] == "R_Test"
    assert find(lib, "at") is None
    assert find(lib, "layer") == ["layer", "F.Cu"]
    assert not [
        c for c in lib if isinstance(c, list) and c[0] in ("path", "sheetname", "sheetfile")
    ]
    for pad in find_all(lib, "pad"):
        assert not [
            c for c in pad if isinstance(c, list) and c[0] in ("net", "pinfunction", "pintype")
        ]
    text = dumps(lib)
    for placed_only in ("R7", "10k", "RC0805", "VCC", "OUT", "120.5", "61.25", "B.", "mirror"):
        assert placed_only not in text
    assert not {str(u[1]) for u in _all(lib, "uuid")} & {str(u[1]) for u in _all(board_fp, "uuid")}


def test_a_label_moved_on_the_board_goes_back_to_the_origin():
    lib = library_form(parse(PLACED))
    reference, value = find_all(lib, "property")  # MPN, a symbol field, is dropped
    assert reference[:3] == ["property", "Reference", "REF**"]
    assert find(reference, "at") == ["at", "0", "0"]
    assert find(reference, "layer") == ["layer", "F.SilkS"]
    assert find(reference, "hide") is None
    assert value[:3] == ["property", "Value", "R_Test"]
    assert find(value, "at") == ["at", "0", "0"]
    assert find(value, "layer") == ["layer", "F.Fab"]


def test_pads_and_graphics_come_back_to_the_front_unrotated():
    lib = library_form(parse(PLACED))
    line = find(lib, "fp_line")
    assert line is not None
    assert (find(line, "start"), find(line, "end")) == (
        ["start", "-1", "-0.5"],
        ["end", "1", "-0.5"],
    )
    assert find(line, "layer") == ["layer", "F.SilkS"]
    one, two = find_all(lib, "pad")
    assert find(one, "at") == ["at", "-0.9", "0.2", "90"]
    assert find(two, "at") == ["at", "0.9", "0.2"]
    assert find(one, "layers") == ["layers", "F.Cu", "F.Mask", "F.Paste"]


@pytest.mark.parametrize("rot", [0, 90, 270])
@pytest.mark.parametrize("back", [False, True])
def test_library_form_is_the_same_however_the_part_was_placed(rot, back):
    lib = library_form(parse(PLACED))
    again = library_form(place(dumps(lib), Placement("Lib:R_Test", "R9", "1k", 3, 4, rot, back)))
    assert dumps(again) == dumps(lib)


def test_a_parsed_footprint_places_as_its_text_does_and_is_left_as_it_was():
    lib = parse(LIB)
    where = Placement("Lib:R_Test", "R7", "10k", 1, 2, 90, True, nets={"1": "VCC"})
    assert dumps(place(lib, where)) == dumps(place(LIB, where))
    assert dumps(lib) == dumps(parse(LIB))


def test_footprints_sharing_a_reference_can_have_uuids_of_their_own():
    def uuids(x: float, uid: str | None) -> set[str]:
        hole = place(LIB, Placement("Lib:R_Test", "REF**", "", x, 0, uid=uid))
        return {str(u[1]) for u in _all(hole, "uuid")}

    assert uuids(1, None) == uuids(2, None)  # what the reference alone gives
    assert not uuids(1, "hole:1") & uuids(2, "hole:2")


def _all(node: Node, head: str) -> list[Node]:
    found = [node] if node and node[0] == head else []
    for child in node[1:]:
        if isinstance(child, list) and child:
            found += _all(child, head)
    return found
