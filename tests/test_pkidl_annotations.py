"""pkidl.annotations: what a part's footprint means that the footprint does not say, as
named areas written against two of the part's pads."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import pkidl.annotations
from pkidl import Board, mm
from pkidl.annotations import Annotation, fit, read, shipped
from pkidl.circuit import Circuit
from pkidl.footprint import footprint_path
from pkidl.importer import circuit, footprints, mechanical
from pkidl.sexpr import Node, dumps, find, find_all, parse

CORPUS = Path(__file__).parents[1] / "corpus"

# A part 10 mm across between its pads 1 and 2, with an antenna above them and a mark
# below and to the right of pad 1, which says which way round a footprint has it.
PART = """
footprint = "X-1"

[pads]
1 = [0, 0]
2 = [10, 0]

[areas]
antenna = [[10, -2], [0, -5]]
mark = [[1, 1], [3, 2]]
"""
MM = 1_000_000


def _footprint(*pads: tuple[str, float, float]) -> Node:
    return parse('(footprint "X-1" (layer "F.Cu")\n  '
                 + "\n  ".join(f'(pad "{n}" smd rect (at {x} {y}) (size 1 1) (layers "F.Cu"))'
                               for n, x, y in pads) + ")")  # fmt: skip


def _mm(box: tuple[int, int, int, int]) -> tuple[float, ...]:
    return tuple(v / MM for v in box)


def test_an_annotation_is_read_in_whole_nanometres_with_each_area_as_a_box():
    note = read(PART)
    assert note == Annotation(
        "X-1",
        {"1": (0, 0), "2": (10 * MM, 0)},
        {"antenna": (0, -5 * MM, 10 * MM, -2 * MM), "mark": (1 * MM, 1 * MM, 3 * MM, 2 * MM)},
    )
    assert read('footprint = "Y"\n[pads]\nA1 = [0.0000004, 0]\nB2 = [0, 1.27]').pads == {
        "A1": (0, 0),
        "B2": (0, 1_270_000),
    }


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('footprint = "X"\nheight = 3\npins = 2\n[pads]\n1 = [0, 0]\n2 = [1, 0]',
         "an annotation has footprint, pads and areas, not height, pins"),
        ("[pads]\n1 = [0, 0]\n2 = [1, 0]",
         "footprint is None, not a footprint's name without its library"),
        ('footprint = ""\n[pads]\n1 = [0, 0]\n2 = [1, 0]',
         "footprint is '', not a footprint's name without its library"),
        ('footprint = "RF:X"\n[pads]\n1 = [0, 0]\n2 = [1, 0]',
         "footprint is 'RF:X', not a footprint's name without its library"),
        ('footprint = 7\n[pads]\n1 = [0, 0]\n2 = [1, 0]',
         "footprint is 7, not a footprint's name without its library"),
        ('footprint = "X"',
         "X: an annotation is written against two pads in two places, not none"),
        ('footprint = "X"\n[pads]\n1 = [0, 0]',
         "X: an annotation is written against two pads in two places, not 1"),
        ('footprint = "X"\n[pads]\n1 = [0, 0]\n2 = [1, 0]\n3 = [2, 0]',
         "X: an annotation is written against two pads in two places, not 1, 2, 3"),
        ('footprint = "X"\n[pads]\n1 = [0, 0]\n2 = [1, 0]\n3 = [1, 0]',
         "X: an annotation is written against two pads in two places, not 1, 2, 3"),
        ('footprint = "X"\n[pads]\n1 = [1, 0]\n2 = [1, 0]',
         "X: an annotation is written against two pads in two places, not 1, 2"),
        ('footprint = "X"\n[pads]\n1 = [0, 0, 0]\n2 = [1, 0]',
         "X: pad 1 is [0, 0, 0], not a point: write [x, y] in millimetres"),
        ('footprint = "X"\n[pads]\n1 = [0, 0]\n2 = "1, 0"',
         "X: pad 2 is '1, 0', not a point: write [x, y] in millimetres"),
        ('footprint = "X"\n[pads]\n1 = [0, 0]\n2 = [true, 0]',
         "X: pad 2 is [True, 0], not a point: write [x, y] in millimetres"),
        ('footprint = "X"\n[pads]\n1 = [0, 0]\n2 = [1, 0]\n[areas]\na = [0, 0, 1, 1]',
         "X: area a is [0, 0, 1, 1], not two opposite corners: write [[x, y], [x, y]]"),
        ('footprint = "X"\n[pads]\n1 = [0, 0]\n2 = [1, 0]\n[areas]\na = "top"',
         "X: area a is 'top', not two opposite corners: write [[x, y], [x, y]]"),
        ('footprint = "X"\n[pads]\n1 = [0, 0]\n2 = [1, 0]\n[areas]\na = [[0, 0], [1]]',
         "X: a corner of area a is [1], not a point: write [x, y] in millimetres"),
        ('footprint = "X"\n[pads]\n1 = [0, 0]\n2 = [1, 0]\n[areas]\na = [[0, 0], [0, 1]]',
         "X: area a has no size"),
        ('footprint = "X"\n[pads]\n1 = [0, 0]\n2 = [1, 0]\n[areas]\na = [[0, 1], [2, 1]]',
         "X: area a has no size"),
    ],
)  # fmt: skip
def test_an_annotation_that_is_not_understood_is_refused(text, message):
    with pytest.raises(ValueError) as e:
        read(text)
    assert str(e.value) == message


@pytest.mark.parametrize(
    ("pads", "antenna", "mark"),
    [
        # Drawn as the annotation has it.
        ([("1", 0, 0), ("2", 10, 0)], (0, -5, 10, -2), (1, 1, 3, 2)),
        # About another origin: everything 5 mm left and 2 mm down.
        ([("1", -5, 2), ("2", 5, 2)], (-5, -3, 5, 0), (-4, 3, -2, 4)),
        # Pad 2 above pad 1: what was above the pads is to their left, and what was to
        # the right of pad 1 is above it.
        ([("1", 0, 0), ("2", 0, -10)], (-5, -10, -2, 0), (1, -3, 2, -1)),
        # Pad 2 to the left: upside down.
        ([("1", 0, 0), ("2", -10, 0)], (-10, 2, 0, 5), (-3, -2, -1, -1)),
        # Pad 2 below pad 1: what was above is to the right.
        ([("1", 0, 0), ("2", 0, 10)], (2, 0, 5, 10), (-2, 1, -1, 3)),
        # Turned, about another origin, and its pads in another order among others.
        ([("3", 9, 9), ("2", 1.5, 12.25), ("1", 1.5, 2.25)], (3.5, 2.25, 6.5, 12.25),
         (-0.5, 3.25, 0.5, 5.25)),
    ],
)  # fmt: skip
def test_areas_are_fitted_to_a_footprint_by_where_its_two_pads_are(pads, antenna, mark):
    areas = fit(read(PART), _footprint(*pads))
    assert list(areas) == ["antenna", "mark"]
    assert _mm(areas["antenna"]) == antenna
    assert _mm(areas["mark"]) == mark


def test_an_annotation_need_not_be_written_about_its_first_pad():
    # The same part as PART, written about a point 2 mm left of pad 1 and 3 mm above it.
    note = read('footprint = "X-1"\n[pads]\n1 = [2, 3]\n2 = [12, 3]\n'
                "[areas]\nantenna = [[12, 1], [2, -2]]")  # fmt: skip
    assert _mm(fit(note, _footprint(("1", 0, 0), ("2", 10, 0)))["antenna"]) == (0, -5, 10, -2)
    assert _mm(fit(note, _footprint(("1", 0, 0), ("2", 0, 10)))["antenna"]) == (2, 0, 5, 10)


def test_pads_sharing_a_number_are_fitted_by_the_first():
    areas = fit(read(PART), _footprint(("1", 0, 0), ("2", 10, 0), ("2", 10, 4), ("1", 3, 3)))
    assert _mm(areas["antenna"]) == (0, -5, 10, -2)


@pytest.mark.parametrize(
    ("pads", "message"),
    [
        ([("1", 0, 0), ("3", 10, 0)], "it has no pad 2"),
        ([("A", 0, 0), ("B", 10, 0)], "it has no pad 1 or 2"),
        ([("1", 0, 0), ("2", 8, 0)],
         "its pads 1 and 2 are 8 mm and 0 mm apart, and the part's are 10 mm and 0 mm apart or "
         "that turned through right angles"),
        ([("1", 1, 1), ("2", 8.5, -6.07)],
         "its pads 1 and 2 are 7.5 mm and -7.07 mm apart, and the part's are 10 mm and 0 mm "
         "apart or that turned through right angles"),
        ([("1", 0, 0), ("2", 10, 0.000001)],
         "its pads 1 and 2 are 10 mm and 0.000001 mm apart, and the part's are 10 mm and 0 mm "
         "apart or that turned through right angles"),
    ],
)  # fmt: skip
def test_a_footprint_whose_pads_are_not_the_parts_is_refused_with_the_reason(pads, message):
    with pytest.raises(ValueError) as e:
        fit(read(PART), _footprint(*pads))
    assert str(e.value) == message


def test_every_annotation_that_ships_is_read_and_found_by_its_footprints_name():
    files = sorted(Path(__file__).parents[1].glob("src/pkidl/parts/*.toml"))
    assert files
    notes = [read(f.read_text()) for f in files]
    assert dict(shipped()) == {note.footprint: note for note in notes}
    assert "ESP-12E" in shipped()


@pytest.fixture
def shipping(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Ship the files written into the directory this gives, and no others."""
    parts = tmp_path / "parts"
    parts.mkdir()
    monkeypatch.setattr(pkidl.annotations, "resources",
                        SimpleNamespace(files=lambda package: tmp_path))  # fmt: skip
    shipped.cache_clear()
    yield parts
    shipped.cache_clear()


def test_only_the_toml_files_among_what_ships_are_annotations(shipping):
    (shipping / "X-1.toml").write_text(PART)
    (shipping / "X-1.toml~").write_text(PART)
    (shipping / "README.md").write_text("What ships here.")
    assert dict(shipped()) == {"X-1": read(PART)}


def test_a_footprint_that_ships_annotated_twice_is_refused(shipping):
    (shipping / "a.toml").write_text(PART)
    (shipping / "b.toml").write_text(PART.replace("[10, 0]", "[12, 0]"))
    with pytest.raises(ValueError) as e:
        shipped()
    assert str(e.value) == "b.toml: X-1 is annotated twice"


def test_the_esp12e_annotation_is_the_box_its_footprint_marks_no_copper():
    """The T0 board's footprint for the module draws a crossed box on its courtyard layer
    and writes "No Copper" in it; the annotation that ships says the same box."""
    d = CORPUS / "t0" / "esp12-breakout_ESP12Breakout"
    footprint = parse((d / "footprints" / "ESP8266.pretty" / "ESP-12E.kicad_mod").read_text())
    yard = ["layer", "F.CrtYd"]
    lines = [ln for ln in find_all(footprint, "fp_line") if find(ln, "layer") == yard]
    ends = [p for ln in lines for p in (find(ln, "start"), find(ln, "end")) if p is not None]
    drawn = [(float(p[1]), float(p[2])) for p in ends]
    label = next(t for t in find_all(footprint, "fp_text") if t[2] == "No Copper")
    at = find(label, "at")
    assert drawn and at is not None
    box = (min(x for x, _ in drawn), min(y for _, y in drawn),
           max(x for x, _ in drawn), max(y for _, y in drawn))  # fmt: skip
    assert box[0] < float(at[1]) < box[2] and box[1] < float(at[2]) < box[3]
    areas = fit(shipped()["ESP-12E"], footprint)
    assert list(areas) == ["antenna"] and _mm(areas["antenna"]) == box == (0, -8.4, 16, -2.6)


# A board to take inputs from: the module in two libraries, one of them some other part
# under its name, and two resistors. The first module is drawn about a point 2 mm right
# of and 3 mm below its pad 1, with pad 22 above pad 1.
SOURCE = """(kicad_pcb
  (gr_rect (start 0 0) (end 60 40) (layer "Edge.Cuts"))
  (footprint "RF:ESP-12E" (layer "F.Cu") (at 20 20)
    (property "Reference" "U1" (at 0 0) (layer "F.SilkS") (uuid "a1"))
    (property "Value" "ESP-12E" (at 0 0) (layer "F.Fab") (uuid "a2"))
    (pad "1" smd rect (at 2 3) (size 1 1) (layers "F.Cu") (net "A") (uuid "a3"))
    (pad "22" smd rect (at 2 -13) (size 1 1) (layers "F.Cu") (net "B") (uuid "a4")))
  (footprint "Other:ESP-12E" (layer "F.Cu") (at 40 20)
    (property "Reference" "U2" (at 0 0) (layer "F.SilkS") (uuid "b1"))
    (property "Value" "ESP-12E" (at 0 0) (layer "F.Fab") (uuid "b2"))
    (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net "A") (uuid "b3"))
    (pad "22" smd rect (at 12 0) (size 1 1) (layers "F.Cu") (net "B") (uuid "b4")))
  (footprint "Device:R" (layer "F.Cu") (at 10 30)
    (property "Reference" "R1" (at 0 0) (layer "F.SilkS") (uuid "c1"))
    (property "Value" "10k" (at 0 0) (layer "F.Fab") (uuid "c2"))
    (pad "1" smd rect (at -1 0) (size 1 1) (layers "F.Cu") (net "A") (uuid "c3"))
    (pad "2" smd rect (at 1 0) (size 1 1) (layers "F.Cu") (net "B") (uuid "c4")))
  (footprint "Device:R" (layer "F.Cu") (at 20 30)
    (property "Reference" "R2" (at 0 0) (layer "F.SilkS") (uuid "d1"))
    (property "Value" "10k" (at 0 0) (layer "F.Fab") (uuid "d2"))
    (pad "1" smd rect (at -1 0) (size 1 1) (layers "F.Cu") (net "A") (uuid "d3"))
    (pad "2" smd rect (at 1 0) (size 1 1) (layers "F.Cu") (net "B") (uuid "d4"))))"""


@pytest.fixture
def board(tmp_path: Path) -> Board:
    source = parse(SOURCE)
    (tmp_path / "circuit.json").write_text(json.dumps(circuit(source)))
    (tmp_path / "mechanical.json").write_text(json.dumps(mechanical(source)))
    for name, lib in footprints(source)[0].items():
        path = tmp_path / "footprints" / footprint_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dumps(lib) + "\n")
    return Board.from_inputs(tmp_path)


def test_a_board_from_inputs_has_the_areas_of_the_footprints_pkidl_knows(board):
    antenna = board["U1"].area("antenna")
    assert str(antenna) == 'U1.area("antenna")'
    assert (antenna.part, antenna.name) == (board["U1"], "antenna")
    # Turned with the footprint: the antenna, above the module as the part is drawn, is
    # to the left of pad 1 here, from 2.6 mm to 8.4 mm of it and as long as the module
    # is wide.
    assert _mm(antenna.box) == (-6.4, -13, -0.6, 3)
    assert antenna == board["U1"].area("antenna") and antenna != board["U2"]
    assert board.circuit.unfitted == {
        "Other:ESP-12E": "its pads 1 and 22 are 12 mm and 0 mm apart, and the part's are "
        "16 mm and 0 mm apart or that turned through right angles"
    }


def test_a_part_with_no_such_area_says_why(board):
    with pytest.raises(LookupError) as e:
        board["U1"].area("shield")
    assert e.value.args == ("U1 has no area 'shield': its footprint 'RF:ESP-12E' has antenna",)
    with pytest.raises(LookupError) as e:
        board["U2"].area("antenna")
    assert e.value.args == (
        "U2 has no area 'antenna': the annotation that ships for ESP-12E is not of its "
        "footprint 'Other:ESP-12E': its pads 1 and 22 are 12 mm and 0 mm apart, and the "
        "part's are 16 mm and 0 mm apart or that turned through right angles",
    )
    with pytest.raises(LookupError) as e:
        board["R1"].area("antenna")
    assert e.value.args == (
        "R1 has no area 'antenna': its footprint 'Device:R' has no annotation: say where "
        "the area is with annotate()",
    )


def test_a_board_file_says_the_areas_of_a_part_that_has_none_shipped(board):
    r1, r2, u2 = board.parts("R1", "R2", "U2")
    # The areas come back in the order they were said in.
    end, body = board.annotate(r1, end=((1 * mm, -0.5 * mm), ("1.5mm", 0.5 * mm)),
                               body=((1 * mm, "0.5mm"), (-1 * mm, -0.5 * mm)))  # fmt: skip
    assert (str(body), str(end)) == ('R1.area("body")', 'R1.area("end")')
    assert _mm(body.box) == (-1, -0.5, 1, 0.5) and _mm(end.box) == (1, -0.5, 1.5, 0.5)
    # Every part with that footprint has them, and no other.
    assert r2.area("end").box == end.box and r2.area("end") != end
    with pytest.raises(LookupError, match="U2 has no area 'body'"):
        u2.area("body")
    # Areas said later are added to the ones there.
    (mark,) = board.annotate(r2, mark=((-1 * mm, -0.5 * mm), (-0.5 * mm, 0 * mm)))
    assert r1.area("mark").box == mark.box and r1.area("body") == body and r1.area("end") == end
    # A part whose shipped annotation did not fit is annotated the same way.
    (antenna,) = board.annotate(u2, antenna=((0 * mm, -8 * mm), (12 * mm, -2 * mm)))
    assert _mm(antenna.box) == (0, -8, 12, -2)
    with pytest.raises(LookupError) as e:
        u2.area("shield")
    assert e.value.args == ("U2 has no area 'shield': its footprint 'Other:ESP-12E' has antenna",)


def test_an_area_is_said_once(board):
    r1, r2, u1 = board.parts("R1", "R2", "U1")
    said = ((-1 * mm, -0.5 * mm), (1 * mm, 0.5 * mm))
    (body,) = board.annotate(r1, body=said)
    # Said again the same, by either part and from either corner, it is the same area.
    assert board.annotate(r2, body=said[::-1])[0].box == body.box
    with pytest.raises(ValueError) as e:
        board.annotate(r2, end=((1 * mm, -0.5 * mm), (1.5 * mm, 0.5 * mm)),
                       body=((-1 * mm, -0.5 * mm), (1 * mm, 0.6 * mm)))  # fmt: skip
    assert str(e.value) == "Device:R has an area body already, somewhere else"
    with pytest.raises(LookupError, match="its footprint 'Device:R' has body$"):
        r1.area("end")
    with pytest.raises(ValueError) as e:
        board.annotate(u1, antenna=((0 * mm, -8.4 * mm), (16 * mm, -2.6 * mm)))
    assert str(e.value) == "RF:ESP-12E has an area antenna already, somewhere else"
    assert r1.area("body").box == body.box and _mm(u1.area("antenna").box) == (-6.4, -13, -0.6, 3)


@pytest.mark.parametrize(
    ("corners", "error", "message"),
    [
        (((0 * mm, 0 * mm), (0 * mm, 1 * mm)), ValueError, "R1: area body has no size"),
        (((0 * mm, 1 * mm), (2 * mm, 1 * mm)), ValueError, "R1: area body has no size"),
        (((0, 0), (1, 1)), TypeError, "0 has no unit: write 0 * mm or \"0mm\""),
    ],
)  # fmt: skip
def test_an_area_with_no_size_or_no_units_is_refused_and_nothing_is_kept(
    board, corners, error, message
):
    with pytest.raises(error) as e:
        board.annotate(board["R1"], end=((1 * mm, 0 * mm), (2 * mm, 1 * mm)), body=corners)
    assert str(e.value) == message
    with pytest.raises(LookupError, match="has no annotation"):
        board["R1"].area("end")


def test_a_part_is_annotated_on_the_board_that_is_told(board, tmp_path):
    twin = Board.from_inputs(tmp_path)
    (body,) = board.annotate(twin["R1"], body=((-1 * mm, -0.5 * mm), (1 * mm, 0.5 * mm)))
    assert body == board["R1"].area("body") and body.part is not twin["R1"]
    with pytest.raises(LookupError, match="has no annotation"):
        twin["R1"].area("body")


def test_a_part_the_board_has_not_got_is_not_annotated(board):
    other = Board.from_inputs(CORPUS / "t0" / "esp12-breakout_ESP12Breakout")
    with pytest.raises(LookupError):
        board.annotate(other["P1"], body=((0 * mm, 0 * mm), (1 * mm, 1 * mm)))


def test_a_board_file_names_the_pins_of_a_part(board):
    r1, r2 = board.parts("R1", "R2")
    # A pin by its name is the pin by its number. Naming pins gives no areas back.
    assert board.annotate(r1, pins={"K": 2, "A": "1"}) == ()
    k, a = r1.pin("K"), r1.pin("A")
    assert (k, a) == (r1.pin(2), r1.pin(1))
    assert (str(k), k.number, k.net) == ("R1.2", "2", board.net("B"))
    assert r1.pins("A", 2) == (a, k)
    # Only the part that was named has the names: a footprint does not say which pad
    # of a part is which.
    with pytest.raises(LookupError) as e:
        r2.pin("K")
    assert e.value.args == ("R2 has no pin K: name its pins with annotate(pins=)",)
    with pytest.raises(LookupError) as e:
        r1.pin("G")
    assert e.value.args == ("R1 has no pin G: its pins are named K, A",)
    # A number it has not got is answered as one, not with its names.
    with pytest.raises(LookupError) as e:
        r1.pin(9)
    assert e.value.args == ("R1 has no pin 9",)
    # Names said later are added to the ones there, and a pin may have two.
    board.annotate(r1, pins={"cathode": 2})
    assert r1.pin("cathode") == k and r1.pin("A") == a
    # Said with areas, the areas come back as they do alone.
    got = board.annotate(r2, pins={"A": 1}, body=((-1 * mm, -0.5 * mm), (1 * mm, 0.5 * mm)))
    assert got == (r2.area("body"),) and r2.pin("A") == r2.pin(1)


def test_a_statement_about_a_pin_by_name_is_about_the_pin(board):
    r1, r2 = board.parts("R1", "R2")
    board.annotate(r1, pins={"K": 2})
    by_name = board.place(r2, near=r1.pin("K"), within=2 * mm)
    assert by_name == board.place(r2, near=r1.pin(2), within=2 * mm)
    assert by_name.data() == {"place": "R2", "near": "R1.2", "within": 2_000_000}
    assert len(board.statements()) == 1


def test_a_pin_name_is_said_once_and_names_a_pin_the_part_has(board):
    r1 = board["R1"]
    board.annotate(r1, pins={"K": 2})
    board.annotate(r1, pins={"K": "2"})
    for pins, error, message in [
        ({"A": 1, "K": 1}, ValueError, "R1: pin K is 2, and cannot also be 1"),
        ({"A": 3}, LookupError, "R1 has no pin 3"),
        ({"A": 1, "2": 1}, ValueError, "R1 has a pin numbered 2: a name is not a number"),
        # A number the part has not got would be taken for one, and so is not a name.
        ({"A": 1, "4": 1}, ValueError, "R1: a pin's name is a word, such as B, not '4'"),
        ({"A": 1, "": 1}, ValueError, "R1: a pin's name is a word, such as B, not ''"),
        ({"A": 1, 2: 1}, TypeError, "R1: a pin's name is a word, such as B, not 2"),
        ({"A": 1, 7: 1}, TypeError, "R1: a pin's name is a word, such as B, not 7"),
    ]:
        with pytest.raises(error) as e:
            board.annotate(r1, pins=pins, body=((-1 * mm, -0.5 * mm), (1 * mm, 0.5 * mm)))  # pyright: ignore[reportArgumentType]
        assert e.value.args == (message,)
        # Nothing of what was said with it is kept, a name or an area.
        with pytest.raises(LookupError, match="R1 has no pin A: its pins are named K$"):
            r1.pin("A")
        with pytest.raises(LookupError, match="has no annotation"):
            r1.area("body")
    # An area that is refused keeps the names said with it out too.
    board.annotate(r1, body=((-1 * mm, -0.5 * mm), (1 * mm, 0.5 * mm)))
    with pytest.raises(ValueError, match="has an area body already"):
        board.annotate(r1, pins={"A": 1}, body=((-1 * mm, -0.5 * mm), (1 * mm, 0.6 * mm)))
    with pytest.raises(LookupError, match="R1 has no pin A"):
        r1.pin("A")


def test_the_fan_controllers_drivers_named_have_their_base_on_the_base_resistor():
    """The T2 board's drivers are SOT-23 with value Q_NPN_BEC: base, emitter, collector
    on pads 1, 2, 3. Named so, each has its base on its base resistor's net, its emitter
    on ground and its collector on its fan header's pin 4."""
    board = Board.from_inputs(CORPUS / "t2" / "fan_controller_fan_controller")
    board.rails("+12V", "+5V", "GND")
    drivers = board.parts("Q2..Q5")
    assert {q.value for q in drivers} == {"Q_NPN_BEC"}
    for q, base_r, fan in zip(drivers, board.parts("R15..R18"), board.parts("P3..P6"),
                              strict=True):  # fmt: skip
        board.annotate(q, pins={"B": 1, "E": 2, "C": 3})
        base = q.pin("B").net
        assert base is not None and base in base_r.nets() and not base.is_rail
        assert q.pin("E").net == board.net("GND")
        assert q.pin("C").net == fan.pin(4).net


def test_a_pin_number_that_is_not_digits_is_not_a_name_either():
    """A grid array numbers its pads A1, B2: a name is none of the part's own numbers."""
    part = {"ref": "U1", "value": "BGA", "footprint": "f", "pads": {"A1": "X", "B2": "Y"}}
    circuit = Circuit({"parts": [part], "nets": ["X", "Y"]})
    with pytest.raises(ValueError) as e:
        circuit.annotate("f", {}, {"U1": {"VDD": "A1", "B2": "A1"}})
    assert e.value.args == ("U1 has a pin numbered B2: a name is not a number",)
    with pytest.raises(LookupError, match="U1 has no pin VDD: name its pins"):
        circuit.part("U1").pin("VDD")
    circuit.annotate("f", {}, {"U1": {"VDD": "A1"}})
    assert circuit.part("U1").pin("VDD") == circuit.part("U1").pin("A1")
