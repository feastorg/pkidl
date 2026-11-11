"""pkidl.importer: a board's circuit and mechanical inputs, and nothing of its layout."""

from pkidl.importer import circuit, mechanical
from pkidl.sexpr import parse

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
