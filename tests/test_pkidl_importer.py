"""pkidl.importer: a board's circuit and mechanical inputs, and nothing of its layout."""

import math

import pytest
from shapely.geometry import Polygon

from pkidl.importer import circuit, footprints, mechanical, renamed
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
    assert m["holes"] == [{"ref": "H1", "footprint": "Hole:M3", "at": [3.0, 3.0], "rot": 0.0,
                           "back": False, "drills": [[3.0, 3.0, 3.2]]}]  # fmt: skip
    assert m["fixed"] == {}


def test_unnumbered_drills_are_each_where_they_are():
    bracket = """(kicad_pcb (footprint "Mech:Bracket" (layer "B.Cu") (at 20 15 90)
      (property "Reference" "H1")
      (pad "" np_thru_hole circle (at 0 0) (size 3 3) (drill 3) (layers "*.Cu"))
      (pad "" np_thru_hole circle (at 6 2) (size 2 2) (drill 2) (layers "*.Cu"))))"""
    (hole,) = mechanical(parse(bracket))["holes"]
    assert hole["drills"] == [[20.0, 15.0, 3.0], [22.0, 9.0, 2.0]]
    assert (hole["rot"], hole["back"]) == (90.0, True)


def _holes(*footprints: str) -> list[str]:
    board = parse("(kicad_pcb " + " ".join(footprints) + ")")
    return [h["footprint"] for h in mechanical(board)["holes"]]


def _on_no_net(name: str, *pads: str) -> str:
    head = f'(footprint "{name}" (at 5 5) (layer "F.Cu") (property "Reference" "REF**")'
    return head + " ".join(pads) + ")"


def test_a_hole_is_a_hole_with_at_most_a_ring_and_vias_round_it():
    plated = '(pad "1" thru_hole circle (at 0 0) (size 6 6) (drill 3.3) (layers "*.Cu"))'
    vias = [f'(pad "1" thru_hole circle (at {x} {y}) (size 1.2 1.2) (drill 0.6) (layers "*.Cu"))'
            for x, y in ((2.4, 0), (0, 2.4), (-2.4, 0), (0, -2.4))]  # fmt: skip
    slot = '(pad "" thru_hole oval (at 0 0) (size 4 3) (drill oval 2.5 0.7) (layers "*.Cu"))'
    # The bench supply's heatsink: two pins, numbered, which its board file holds fixed.
    sink = ['(pad "1" thru_hole circle (at 0 0) (size 4 4) (drill 2.667))',
            '(pad "2" thru_hole circle (at 25.4 0) (size 4 4) (drill 2.667))']  # fmt: skip
    # Unplated, it is a hole whatever its pad's shape: it has no copper.
    unplated = '(pad "" np_thru_hole rect (at 0 0) (size 3 3) (drill 3) (layers "*.Cu"))'
    assert _holes(_on_no_net("H:Plated", plated), _on_no_net("H:Shield", plated, *vias),
                  _on_no_net("H:Slot", slot), _on_no_net("H:Sink", *sink),
                  _on_no_net("H:NPTH", unplated)) == [
        "H:Plated", "H:Shield", "H:Slot", "H:Sink", "H:NPTH"]  # fmt: skip


def test_a_prototyping_boards_pads_are_not_holes_and_are_said_to_be_left_out():
    # AgonLight2-PROTO's 554 square pads; SMT-PROTOBOARD's headers, square and oval.
    square = '(pad "1" thru_hole rect (at 0 0) (size 1.778 1.778) (drill 1) (layers "*.Cu"))'
    pins = ['(pad "1" thru_hole circle (at 0 0) (size 1.7 1.7) (drill 1))',
            '(pad "2" thru_hole oval (at 2.54 0) (size 1.7 1.9) (drill 1))']  # fmt: skip
    off = '(pad "" thru_hole circle (at 0 0) (size 2 2) (drill 1 (offset 0.3 0)) (layers "*.Cu"))'
    found = [_on_no_net("P:Pad", square), _on_no_net("P:Pad", square),
             _on_no_net("P:Header", *pins), _on_no_net("P:Off", off)]  # fmt: skip
    assert _holes(*found) == []
    # One line a name, with how many: a hole lost to the rule can be seen.
    assert renamed(parse("(kicad_pcb " + " ".join(found) + ")")) == [
        "P:Header: 1 footprint of drilled pads on no net, not holes: not every pad is a "
        "hole with at most a ring",
        "P:Off: 1 footprint of drilled pads on no net, not holes: not every pad is a hole "
        "with at most a ring",
        "P:Pad: 2 footprints of drilled pads on no net, not holes: not every pad is a hole "
        "with at most a ring",
    ]


def test_an_oval_drill_is_its_two_sizes_and_the_pads_angle_on_the_board():
    slot = """(kicad_pcb (footprint "Mech:Slot" (layer "F.Cu") (at 20 15 90)
      (property "Reference" "H1")
      (pad "" np_thru_hole oval (at 0 0 135) (size 2 4) (drill oval 2 4) (layers "*.Cu"))
      (pad "" np_thru_hole circle (at 6 2 90) (size 3 3) (drill 2 (offset 0.5 0))
        (layers "*.Cu"))))"""
    (hole,) = mechanical(parse(slot))["holes"]
    # A round hole keeps its form, and is where its pad is: the offset moves the copper.
    assert hole["drills"] == [[20.0, 15.0, 2.0, 4.0, 135.0], [22.0, 9.0, 2.0]]


def test_an_outline_drawn_in_a_footprint_is_read_where_kicad_has_it_on_the_board():
    # On the back and turned 30 degrees. Where each point is was read from KiCad
    # 10.0.8's Gerber of this board's Edge.Cuts (kicad-cli pcb export gerbers).
    board = """(kicad_pcb (footprint "T:Edge" (layer "B.Cu") (at 50 40 30)
      (property "Reference" "X1")
      (fp_line (start 0 0) (end 10 0) (layer "Edge.Cuts"))
      (fp_arc (start 10 0) (mid 12 -3) (end 10 -6) (layer "Edge.Cuts"))
      (fp_rect (start 2 -1) (end 4 -2) (layer "Edge.Cuts"))
      (fp_poly (pts (xy 5 -1) (xy 7 -1) (xy 6 -3)) (layer "Edge.Cuts"))
      (fp_circle (center 3 -4) (end 3.5 -4) (layer "Edge.Cuts"))
      (fp_line (start 0 0) (end 0 -6) (layer "B.SilkS"))))"""
    read = mechanical(parse(board))["outline"]
    assert len(read) == 5  # not the silkscreen line
    outline = {i["type"]: i for i in read if i["type"] != "gr_poly"}
    polys = [i["pts"] for i in read if i["type"] == "gr_poly"]
    assert outline["gr_line"] == {
        "type": "gr_line",
        "start": [50.0, 40.0],
        "end": [58.660254, 35.0],
    }
    arc = outline["gr_arc"]
    assert (arc["start"], arc["end"]) == ([58.660254, 35.0], [55.660254, 29.803848])
    # The arc's centre, from KiCad's: its start plus (I, J).
    assert math.dist(arc["mid"], (56.077722, 33.026924)) == pytest.approx(3.25, abs=1e-5)
    assert math.dist(arc["mid"], arc["end"]) < math.dist(arc["start"], arc["end"])
    circle = outline["gr_circle"]
    assert circle["center"] == [50.598076, 35.035898]
    assert math.dist(circle["center"], circle["end"]) == pytest.approx(0.5)
    # The rectangle is turned, so it is the polygon of its corners, in order round it.
    rect = {(50.732051, 37.267949), (52.464102, 36.267949), (52.964102, 37.133975),
            (51.232051, 38.133975)}  # fmt: skip
    triangle = {(53.830127, 36.633975), (55.562178, 35.633975), (53.696152, 34.401924)}
    assert [{tuple(p) for p in pts} for pts in polys] == [rect, triangle]
    assert Polygon(polys[0]).area == pytest.approx(2)


def test_a_part_whose_footprint_draws_the_outline_is_said_to_float():
    # OLIMEXINO-2560's PLATFORM1, whose pads are the Arduino header pins. A hole, or a
    # logo, drawing the outline goes unsaid: a hole is fixed, a logo is not placed.
    edge = '(fp_rect (start 0 0) (end 10 10) (layer "Edge.Cuts"))'
    pin = '(pad "1" thru_hole circle (at 0 0) (size 1.7 1.7) (drill 1) (net "GND"))'
    hole = '(pad "" np_thru_hole circle (at 0 0) (size 3 3) (drill 3))'

    def fp(name: str, ref: str, *children: str) -> str:
        head = f'(footprint "{name}" (at 0 0) (layer "F.Cu") (property "Reference" "{ref}")'
        return " ".join([head, *children, edge]) + ")"

    # Text on Edge.Cuts is no outline: KiCad draws no edge from it.
    text = ('(footprint "C:Marked" (at 20 0) (layer "F.Cu") (property "Reference" "J1") '
            f'{pin} (fp_text user "CUT" (at 0 0) (layer "Edge.Cuts")))')  # fmt: skip
    board = _board(fp("C:Platform", "PLATFORM1", pin), fp("H:M3", "H1", hole),
                   fp("L:Logo", "G***"), text)  # fmt: skip
    assert len(mechanical(board)["outline"]) == 3
    assert renamed(board) == [
        "PLATFORM1: the board's outline is drawn in its footprint, C:Platform; the outline "
        "is read, and PLATFORM1 is placed as any part, not fixed where it draws the outline"
    ]


def _part(ref: str, at: str, size: str = "1 1", pad_first: bool = True, silk: str = "1 0") -> str:
    pad = f'(pad "1" smd rect (at 0 0) (size {size}) (layers "F.Cu") (net "VCC"))'
    line = f'(fp_line (start 0 0) (end {silk}) (layer "F.SilkS"))'
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


def _silk_end(lib) -> list:
    return find(find(lib, "fp_line"), "end")[1:]  # type: ignore[arg-type, index]


def test_a_name_stands_for_the_version_most_parts_carry():
    # Versions that differ in their graphics only.
    board = _board(_part("R1", "0 0", silk="2 0"), _part("R2", "5 0"), _part("R3", "9 0"))
    libs, differ = footprints(board)
    assert _silk_end(libs["L:R"]) == ["1", "0"]
    assert differ == {"L:R": ["R1"]}
    assert renamed(board) == []


def test_the_lowest_reference_decides_a_tie():
    libs, differ = footprints(_board(_part("R10", "0 0"), _part("R2", "5 0", silk="2 0")))
    assert _silk_end(libs["L:R"]) == ["2", "0"]  # R2 before R10: by number, not by text
    assert differ == {"L:R": ["R10"]}


def test_a_version_with_other_pads_is_a_footprint_of_its_own():
    # LCD-OLinuXino-15.6FHD: one connector's version of the name has a pad 0 more.
    extra = '(pad "0" smd rect (at 3 0) (size 1 1) (layers "F.Cu") (net "GND"))'
    other = _part("R2", "5 0", "2 2").replace('(net "VCC"))', '(net "VCC"))' + extra)
    board = _board(_part("R1", "0 0"), other, _part("R3", "9 0"), _part("R4", "12 0", "2 2"))
    libs, differ = footprints(board)
    assert sorted(libs) == ["L:R", "L:R_2", "L:R_3"] and differ == {}
    assert _pad_size(libs["L:R"]) == ["1", "1"] and libs["L:R"][1] == "R"
    assert [str(p[1]) for p in find_all(libs["L:R_2"], "pad")] == ["1", "0"]
    assert libs["L:R_2"][1] == "R_2"
    assert {p["ref"]: p["footprint"] for p in circuit(board)["parts"]} == {
        "R1": "L:R", "R2": "L:R_2", "R3": "L:R", "R4": "L:R_3"}  # fmt: skip
    assert renamed(board) == [
        "L:R: the version on R2 has other pads, and is written as L:R_2",
        "L:R: the version on R4 has other pads, and is written as L:R_3",
    ]


def test_a_holes_version_with_other_pads_is_a_footprint_of_its_own():
    # TERES-PCB2-IO: two holes of one name, each drilled off its origin differently.
    hole = (
        '(footprint "H:M2" (at {}) (layer "F.Cu") (property "Reference" "REF**")'
        ' (pad "" np_thru_hole circle (at {}) (size 2.2 2.2) (drill 2.2) (layers "*.Cu")))'
    )
    board = _board(hole.format("10 10", "-20.804 1.1338"), hole.format("30 10", "-21.406 2.5808"))
    holes = mechanical(board)["holes"]
    assert [h["footprint"] for h in holes] == ["H:M2", "H:M2_2"]
    assert sorted(footprints(board)[0]) == ["H:M2", "H:M2_2"]


def test_parts_that_share_a_reference_are_told_apart_by_where_they_are():
    # TERES's mounting holes with a pad on ground, all "MountingHole".
    def hole(at: str, ref: str = "MountingHole") -> str:
        pad = '(pad "1" thru_hole circle (at 0 0) (size 5 5) (drill 3) (net "GND"))'
        return f'(footprint "H:MH" (at {at}) (layer "F.Cu") (property "Reference" "{ref}") {pad})'

    # One is already called MountingHole_2, and keeps it.
    board = _board(hole("50 5"), hole("10 40"), hole("10 5"), hole("0 0", "MountingHole_2"))
    assert [p["ref"] for p in circuit(board)["parts"]] == [
        "MountingHole", "MountingHole_2", "MountingHole_3", "MountingHole_4"]  # fmt: skip
    # And each is a mounting hole on a net.
    refs = ("MountingHole", "MountingHole_2", "MountingHole_3", "MountingHole_4")
    said = [f"{ref}: a mounting hole on GND, H:MH: fixed where the board has it, and a part "
            "of the circuit with its net" for ref in refs]  # fmt: skip
    assert [h["ref"] for h in mechanical(board)["holes"]] == list(refs)
    assert renamed(board) == [
        "MountingHole is on 3 parts: the one at (10.0, 40.0) is MountingHole_3",
        "MountingHole is on 3 parts: the one at (50.0, 5.0) is MountingHole_4",
        *said,
    ]


def test_the_same_package_saved_in_another_order_does_not_differ():
    assert footprints(_board(_part("R1", "0 0"), _part("R2", "5 0", pad_first=False)))[1] == {}


def test_a_part_that_is_a_hole_on_a_net_is_a_hole_and_a_part():
    # SparkFun's Qwiic Fingerprint FPC2534's standoffs on EGND, and RedBoard_Edge's,
    # a hole with vias round it; and parts with round pads on round drills that are not.
    def fp(name: str, ref: str, *children: str) -> str:
        head = f'(footprint "{name}" (at 5 5) (layer "F.Cu") (property "Reference" "{ref}")'
        return " ".join([head, *children]) + ")"

    def pad(net: str, drill: float, at: str = "0 0", number: str = "1") -> str:
        size = drill + 1.4
        return (f'(pad "{number}" thru_hole circle (at {at}) (size {size} {size}) '
                f'(drill {drill}) (layers "*.Cu") (net "{net}"))')  # fmt: skip

    vias = [pad("JP1", 0.5, at) for at in ("2.4 0", "0 2.4", "-2.4 0", "0 -2.4")]
    body = '(fp_circle (center 0 0) (end 5 0) (layer "F.SilkS"))'
    yard = '(fp_circle (center 0 0) (end 3 0) (layer "F.CrtYd"))'  # no body, a courtyard
    board = _board(
        fp("H:Standoff", "ST1", pad("EGND", 3.1), yard),
        fp("H:Grounding", "U3", pad("JP1", 3.302), *vias),
        fp("C:1x01", "TP1", pad("EGND", 1.016)),  # a test point: a lead's hole
        fp("C:Banana", "P1", pad("OUT", 6.096), body),  # a post, which draws its body
        fp("D:Speaker", "SPK1", pad("A", 18), pad("B", 3.5, "10 0", "2")),  # two nets
        # A square pad: a lead's, whatever its drill.
        fp("C:Lug", "J1", pad("OUT", 3.2).replace("circle", "rect")),
    )  # fmt: skip
    holes = mechanical(board)["holes"]
    assert [(h["ref"], h["footprint"], h.get("part")) for h in holes] == [
        ("ST1", "H:Standoff", True), ("U3", "H:Grounding", True)]  # fmt: skip
    assert holes[0]["drills"] == [[5.0, 5.0, 3.1]]
    # Each stays in the circuit with its net, so it is routed to.
    assert [(p["ref"], p["pads"]) for p in circuit(board)["parts"]] == [
        ("J1", {"1": "OUT"}), ("P1", {"1": "OUT"}), ("SPK1", {"1": "A", "2": "B"}),
        ("ST1", {"1": "EGND"}), ("TP1", {"1": "EGND"}), ("U3", {"1": "JP1"})]  # fmt: skip
    assert renamed(board) == [
        "ST1: a mounting hole on EGND, H:Standoff: fixed where the board has it, and a part "
        "of the circuit with its net",
        "U3: a mounting hole on JP1, H:Grounding: fixed where the board has it, and a part of "
        "the circuit with its net",
    ]


def test_items_on_kicads_undefined_layer_are_left_out_of_a_footprint_and_counted():
    # KiCad's EAGLE import puts EAGLE's tTest layer there, as on Olimex's C0603_DWS.
    undefined = ['(fp_line (start 0 0) (end 1 0) (layer "UNDEFINED"))',
                 '(fp_arc (start 0 0) (mid 1 1) (end 2 0) (layer "UNDEFINED"))']  # fmt: skip
    pad = '(pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net "VCC"))'
    silk = '(fp_line (start 0 0) (end 0 1) (layer "F.SilkS"))'
    board = _board(f'(footprint "E:C0603_DWS" (at 5 5) (layer "F.Cu") (property "Reference" "C1") '
                   f"{pad} {silk} {' '.join(undefined)})")  # fmt: skip
    (lib,) = footprints(board)[0].values()
    drawn = [find(c, "layer") for c in lib if isinstance(c, list) and str(c[0]).startswith("fp_")]
    assert drawn == [["layer", "F.SilkS"]]
    assert renamed(board) == [
        "E:C0603_DWS: 2 items on KiCad's UNDEFINED layer left out of the footprint"]  # fmt: skip


def test_a_cut_out_drawn_in_a_part_is_said_to_be_one():
    # SparkFun's Qwiic Power Meter: U1's SO-16 Wide package cuts a slot under it.
    slot = '(fp_rect (start -7 -0.635) (end 7 0.635) (layer "Edge.Cuts"))'
    pad = '(pad "1" smd rect (at 0 -5) (size 1 1) (layers "F.Cu") (net "IP+"))'
    part = (
        f'(footprint "P:SO16W" (at 20 15) (layer "F.Cu") (property "Reference" "U1") {pad} {slot})'
    )
    outline = '(gr_rect (start 0 0) (end 40 30) (layer "Edge.Cuts"))'
    assert renamed(_board(outline, part)) == [
        "U1: a cut-out of the board is drawn in its footprint, P:SO16W; the cut-out is read, "
        "and U1 is placed as any part, not fixed where it draws the cut-out"]  # fmt: skip
    # Where it is all there is, it is the outline; and where what is drawn does not
    # close, what it is cannot be told.
    assert renamed(_board(part))[0].startswith("U1: the board's outline is drawn")
    assert renamed(_board(part.replace("fp_rect", "fp_line")))[0].startswith(
        "U1: part of the board's edge is drawn")  # fmt: skip
