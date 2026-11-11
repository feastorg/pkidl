"""pkidl.importer: a board's circuit and mechanical inputs, and nothing of its layout."""

from pkidl.importer import circuit, footprints, mechanical
from pkidl.sexpr import find, find_all, parse

BOARD = """(kicad_pcb
  (gr_line (start 0 0) (end 40 0) (layer "Edge.Cuts"))
  (gr_arc (start 40 0) (mid 41 1) (end 42 2) (layer "Edge.Cuts"))
  (gr_line (start 5 5) (end 6 6) (layer "F.SilkS"))
  (footprint "Device:R" (at 10 10 90) (layer "F.Cu")
    (property "Reference" "R1") (property "Value" "10k")
    (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net "VCC"))
    (pad "2" smd rect (at 2 0) (size 1 1) (layers "F.Cu") (net "OUT")))
  (footprint "Conn:J" (at 20 10) (layer "B.Cu")
    (property "Reference" "J1") (property "Value" "CONN")
    (pad "1" thru_hole circle (at 0 0) (size 2 2) (drill 1) (layers "*.Cu") (net "OUT"))
    (pad "2" thru_hole circle (at 0 2.54) (size 2 2) (drill 1) (layers "*.Cu")))
  (footprint "Hole:M3" (at 3 3) (layer "F.Cu")
    (property "Reference" "H1") (property "Value" "M3")
    (pad "" np_thru_hole circle (at 0 0) (size 3.2 3.2) (drill 3.2) (layers "*.Cu")))
  (footprint "lib:VIA" (at 30 5) (layer "F.Cu")
    (property "Reference" "REF**") (property "Value" "VIA")
    (pad "1" thru_hole circle (at 0 0) (size 0.8 0.8) (drill 0.4) (layers "*.Cu") (net "VCC")))
  (footprint "Logo" (at 35 20) (layer "F.Cu") (property "Reference" "G***")))"""


def test_the_circuit_is_parts_values_footprints_and_pad_nets():
    c = circuit(parse(BOARD))
    assert c == {
        "parts": [
            {"ref": "J1", "value": "CONN", "footprint": "Conn:J", "pads": {"1": "OUT"}},
            {"ref": "R1", "value": "10k", "footprint": "Device:R",
             "pads": {"1": "VCC", "2": "OUT"}},
        ],
        "nets": ["OUT", "VCC"],
    }  # fmt: skip


def test_board_only_footprints_are_not_circuit():
    refs = {p["ref"] for p in circuit(parse(BOARD))["parts"]}
    assert not refs & {"H1", "REF**", "G***"}  # hole, via as footprint, logo


def test_no_position_side_or_rotation_is_read_into_the_circuit():
    for part in circuit(parse(BOARD))["parts"]:
        assert set(part) == {"ref", "value", "footprint", "pads"}
        assert all(isinstance(n, str) for n in part["pads"].values())


def test_mechanical_is_the_outline_and_the_holes():
    m = mechanical(parse(BOARD))
    assert m["outline"] == [
        {"type": "gr_arc", "start": [40.0, 0.0], "mid": [41.0, 1.0], "end": [42.0, 2.0]},
        {"type": "gr_line", "start": [0.0, 0.0], "end": [40.0, 0.0]},
    ]
    assert m["holes"] == [{"ref": "H1", "footprint": "Hole:M3", "at": [3.0, 3.0],
                           "drills": [[3.0, 3.0, 3.2]]}]  # fmt: skip
    assert m["fixed"] == {}


def _part(ref: str, at: str, size: str = "1 1", pad_first: bool = True) -> str:
    pad = f'(pad "1" smd rect (at 0 0) (size {size}) (layers "F.Cu") (net "VCC"))'
    line = '(fp_line (start 0 0) (end 1 0) (layer "F.SilkS"))'
    children = pad + line if pad_first else line + pad
    return f'(footprint "L:R" (at {at}) (layer "F.Cu") (property "Reference" "{ref}") {children})'


def _board(*parts: str):
    return parse("(kicad_pcb " + " ".join(parts) + ")")


def _pad_size(lib) -> list:
    return find(find_all(lib, "pad")[0], "size")[1:]  # type: ignore[index]


def test_footprints_are_the_packages_of_the_parts_and_holes():
    libs, differ = footprints(parse(BOARD))
    assert sorted(libs) == ["Conn:J", "Device:R", "Hole:M3"]  # not the via or the logo
    assert differ == {}
    for lib in libs.values():
        assert find(lib, "at") is None
        assert find(lib, "layer") == ["layer", "F.Cu"]
        assert not [p for p in find_all(lib, "pad") if find(p, "net") is not None]
    assert find(find_all(libs["Conn:J"], "pad")[1], "at") == ["at", "0", "-2.54"]  # from the back


def test_a_board_only_footprint_sharing_a_holes_reference_is_not_a_package():
    board = parse(BOARD.replace('"Reference" "H1"', '"Reference" "REF**"'))
    assert sorted(footprints(board)[0]) == ["Conn:J", "Device:R", "Hole:M3"]


def test_a_name_stands_for_the_version_most_parts_carry():
    libs, differ = footprints(
        _board(_part("R1", "0 0", "2 2"), _part("R2", "5 0"), _part("R3", "9 0"))
    )
    assert _pad_size(libs["L:R"]) == ["1", "1"]
    assert differ == {"L:R": ["R1"]}


def test_the_lowest_reference_decides_a_tie():
    libs, differ = footprints(_board(_part("R10", "0 0"), _part("R2", "5 0", "2 2")))
    assert _pad_size(libs["L:R"]) == ["2", "2"]  # R2 before R10: by number, not by text
    assert differ == {"L:R": ["R10"]}


def test_the_same_package_saved_in_another_order_does_not_differ():
    assert footprints(_board(_part("R1", "0 0"), _part("R2", "5 0", pad_first=False)))[1] == {}
