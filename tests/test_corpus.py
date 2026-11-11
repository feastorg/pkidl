"""The corpus inputs: what the importer reads from each reference, and nothing edited by hand.

``library_form`` is also checked here against every footprint KiCad saved in the
references: placed again where it was, each gives back the pads and graphics it had.
"""

import functools
import hashlib
import json
import math
from pathlib import Path

import pytest

from pkidl import Board, Edge, inch, mm
from pkidl.circuit import natural
from pkidl.footprint import Placement, footprint_path, library_form, pad_xy, place
from pkidl.importer import _property, circuit, footprints, mechanical
from pkidl.sexpr import Node, dumps, find, find_all, parse
from pkidl.units import Length

CORPUS = Path(__file__).parents[1] / "corpus"
BOARDS = sorted(p.parent for p in CORPUS.glob("*/*/reference.kicad_pcb"))
MANIFEST = json.loads((CORPUS / "manifest.json").read_text())["boards"]
PLACED_ONLY = ("uuid", "path", "sheetname", "sheetfile", "locked", "placed")

each_board = pytest.mark.parametrize("d", BOARDS, ids=lambda d: d.name)


@functools.cache
def reference(d: Path) -> Node:
    return parse((d / "reference.kicad_pcb").read_text())


def test_the_corpus_is_found():
    assert len(BOARDS) == 15  # an empty glob would skip every test below


@each_board
def test_the_inputs_are_what_the_importer_reads_from_the_reference(d):
    board = reference(d)
    assert json.loads((d / "circuit.json").read_text()) == circuit(board)
    assert json.loads((d / "mechanical.json").read_text()) == mechanical(board)
    libs, _ = footprints(board)
    files = {
        p.relative_to(d / "footprints"): p.read_text() for p in d.glob("footprints/**/*.kicad_mod")
    }
    assert files == {footprint_path(name): dumps(lib) + "\n" for name, lib in libs.items()}


@each_board
def test_the_manifest_is_of_these_files(d):
    entry = MANIFEST[d.name]
    files = [p for p in d.rglob("*") if p.is_file()]
    assert entry["sha256"] == {
        p.relative_to(d).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files
    }
    assert entry["other_footprint_versions"] == footprints(reference(d))[1]


@each_board
def test_every_part_and_hole_has_its_footprint(d):
    names = {p["footprint"] for p in json.loads((d / "circuit.json").read_text())["parts"]}
    names |= {h["footprint"] for h in json.loads((d / "mechanical.json").read_text())["holes"]}
    assert len({footprint_path(n) for n in names}) == len(names)
    for name in names:
        lib = parse((d / "footprints" / footprint_path(name)).read_text())
        assert lib[1] == name.rpartition(":")[2]
        assert find(lib, "at") is None and find(lib, "path") is None
        assert find(lib, "layer") == ["layer", "F.Cu"]
        assert not [p for p in find_all(lib, "pad") if find(p, "net") is not None]


def _body(fp: Node) -> list[str]:
    """A placed footprint's pads, graphics and texts: no UUIDs, a pad's children in any
    order (``place`` puts the net where KiCad may not), and angles as KiCad reads them: a
    pad's to the turn, a text's to the half turn, since ``place`` keeps texts upright."""

    def bare(n: Node, turn: int) -> Node:
        out = [bare(c, turn) if isinstance(c, list) else c
               for c in n if not (isinstance(c, list) and c and c[0] == "uuid")]  # fmt: skip
        if out and out[0] == "at":
            out[3:] = [str(float(str(out[3])) % turn if len(out) > 3 else 0.0)]
        if out and out[0] == "pad":
            out[4:] = sorted(out[4:], key=str)
        return out

    return [dumps(bare(c, 180 if c[0] == "fp_text" else 360)) for c in fp[2:]
            if isinstance(c, list) and c[0].startswith(("pad", "fp_"))]  # fmt: skip


@each_board
def test_library_form_placed_again_is_the_footprint_kicad_saved(d):
    for fp in find_all(reference(d), "footprint"):
        at, layer = find(fp, "at"), find(fp, "layer")
        assert at is not None and layer is not None
        nets = {str(p[1]): str(n[-1]) for p in find_all(fp, "pad") if (n := find(p, "net"))}
        where = Placement(str(fp[1]), _property(fp, "Reference"), _property(fp, "Value"),
                          float(at[1]), float(at[2]), float(at[3]) if len(at) > 3 else 0.0,
                          str(layer[1]).startswith("B."), nets)  # fmt: skip
        lib = library_form(fp)
        again = place(dumps(lib), where)
        assert _body(again) == _body(fp), where.ref
        assert dumps(library_form(again)) == dumps(lib), where.ref


def _uuids(node: Node) -> list[str]:
    found = [str(node[1])] if node and node[0] == "uuid" else []
    for child in node[1:]:
        if isinstance(child, list) and child:
            found += _uuids(child)
    return found


@each_board
def test_a_board_from_the_inputs_has_the_references_outline_and_holes(d):
    board = Board.from_inputs(d)
    assert board.circuit.data == json.loads((d / "circuit.json").read_text())
    written = parse(dumps(board.sexpr()))
    assert mechanical(written) == json.loads((d / "mechanical.json").read_text())
    assert circuit(written) == {"parts": [], "nets": []}  # no part is placed yet
    uuids = _uuids(written)
    assert len(set(uuids)) == len(uuids)
    assert board.extent is not None
    x0, y0, x1, y1 = board.extent
    points = [p for item in mechanical(reference(d))["outline"]
              for key in ("start", "mid", "end") if (p := item.get(key))]  # fmt: skip
    assert all(x0 <= x <= x1 and y0 <= y <= y1 for x, y in points)


@each_board
def test_the_circuit_as_objects_is_the_circuit_as_data(d):
    board = Board.from_inputs(d)
    data = json.loads((d / "circuit.json").read_text())
    assert [p.ref for p in board.parts()] == sorted((p["ref"] for p in data["parts"]), key=natural)
    assert [n.name for n in board.nets()] == data["nets"]
    on_nets = {(str(pin), pin.net.name) for part in board.parts() for pin in part.pins()
               if pin.net is not None}  # fmt: skip
    assert on_nets == {(f"{p['ref']}.{number}", net)
                       for p in data["parts"] for number, net in p["pads"].items()}  # fmt: skip
    assert {str(pin) for net in board.nets() for pin in net.pins()} == {p for p, _ in on_nets}
    for part in board.parts():
        numbered = [str(pad[1]) for pad in find_all(board.library[part.footprint], "pad")
                    if str(pad[1])]  # fmt: skip
        assert [pin.number for pin in part.pins()] == list(dict.fromkeys(numbered)), part.ref


def test_each_strap_of_the_t0_board_finds_the_module_pin_it_biases():
    """The lines of the T0 board file that read the circuit, on its real inputs."""
    board = Board.from_inputs(CORPUS / "t0" / "esp12-breakout_ESP12Breakout")
    board.rails("VCC", "GND")
    u1, p1, p2 = board.parts("U1", "P1", "P2")
    assert (u1.value, p1.value, p2.value) == ("ESP-12E", "CONN_01X08", "CONN_01X08")
    biased = [str(u1.pin_on(r.signal_net)) for r in board.parts("R1..R5")]
    assert biased == ["U1.1", "U1.3", "U1.18", "U1.17", "U1.16"]


def _t0(inset: Length, side: str | None = None) -> Board:
    """The T0 board's real inputs, and the placement lines of its board file."""
    board = Board.from_inputs(CORPUS / "t0" / "esp12-breakout_ESP12Breakout")
    board.rails("VCC", "GND")
    u1, p1, p2 = board.parts("U1", "P1", "P2")
    board.place(p1, against=Edge.LEFT, inset=inset)
    board.place(p2, against=Edge.RIGHT, inset=inset)
    board.align(p1, p2, grid=0.1 * inch)
    board.place(u1, between=(p1, p2), against=Edge.TOP, facing=Edge.TOP)
    board.keepout(u1.area("antenna"), copper=True, both_sides=True)
    for r in board.parts("R1..R5"):
        board.place(r, near=u1.pin_on(r.signal_net), within=3 * mm, side=side)
    return board


def test_what_the_t0_board_file_says_about_placement_places_every_part():
    board = _t0(0.075 * inch, "back")
    assert board.conflicts() == ()
    assert [s.data() for s in board.statements()] == [
        {"place": "P1", "against": "left", "inset": 1_905_000},
        {"place": "P2", "against": "right", "inset": 1_905_000},
        {"align": ["P1", "P2"], "grid": 2_540_000},
        {"place": "U1", "against": "top", "between": ["P1", "P2"], "facing": "top"},
        {"keepout": "U1", "area": "antenna", "copper": True, "both_sides": True},
        {"place": "R1", "near": "U1.1", "within": 3_000_000, "side": "back"},
        {"place": "R2", "near": "U1.3", "within": 3_000_000, "side": "back"},
        {"place": "R3", "near": "U1.18", "within": 3_000_000, "side": "back"},
        {"place": "R4", "near": "U1.17", "within": 3_000_000, "side": "back"},
        {"place": "R5", "near": "U1.16", "within": 3_000_000, "side": "back"},
    ]
    before = dumps(board.sexpr())
    solution = board.solve()
    assert solution.ok, [str(problem) for problem in solution.problems]
    assert dumps(board.sexpr()) == before  # worked out, and nothing has moved
    assert [p.ref for p in board.parts()] == list(solution.poses)

    def pads(ref: str) -> dict[str, tuple[float, float]]:
        part, pose = board[ref], solution.poses[ref]
        placed = place(board.library[part.footprint],
                       Placement(part.footprint, ref, part.value, pose.x.mm, pose.y.mm,
                                 pose.rot, pose.back))  # fmt: skip
        return {str(pad[1]): pad_xy(placed, str(pad[1])) for pad in find_all(placed, "pad")}

    p1, p2, u1 = pads("P1"), pads("P2"), pads("U1")
    x0, y0, x1, _ = board.extent or (0, 0, 0, 0)
    # The headers: every pin 0.075 inch in from its edge, so the rows are 0.9 inch apart
    # on the 1.05 inch board, with pin 1 of each level with the other's.
    assert {round(x - x0, 6) for x, _ in p1.values()} == {1.905}
    assert {round(x1 - x, 6) for x, _ in p2.values()} == {1.905}
    assert round(p2["1"][0] - p1["1"][0], 6) == 22.86 and p1["1"][1] == p2["1"][1]
    # The module is midway between them with its antenna end on the top edge, which its
    # footprint draws 8.4 mm above pad 1, and each header is the way round that puts its
    # pins beside the module's pads on their nets: P1.8 by U1.1, P2.8 by U1.22.
    assert round(u1["1"][0] - p1["1"][0], 6) == round(p2["1"][0] - u1["22"][0], 6)
    assert round(u1["1"][1] - y0, 6) == 8.4 and u1["1"][1] == u1["22"][1]
    # The antenna's area is kept clear on both faces: the width of the module between
    # its two rows of pads, from the top edge to 2.6 mm above pad 1.
    (kept,) = solution.keepouts
    assert kept.statement.area == board["U1"].area("antenna") and kept.front and kept.back
    assert [round(v.mm, 6) for v in kept.box] == [
        u1["1"][0], y0, u1["22"][0], round(u1["1"][1] - 2.6, 6)]  # fmt: skip
    assert u1["1"][1] < u1["8"][1] and p1["8"][1] < p1["1"][1] and p2["8"][1] < p2["1"][1]
    # Each strap is on the back, a pad of it within 3 mm of the pin it biases.
    for r in board.parts("R1..R5"):
        pin = u1[r.circuit.part("U1").pin_on(r.signal_net).number]
        assert solution.poses[r.ref].back
        assert min(math.dist(pad, pin) for pad in pads(r.ref).values()) <= 3.0
        assert all(y > kept.box[3].mm for _, y in pads(r.ref).values())


def test_what_does_not_fit_on_the_t0_board_is_said():
    """The same lines with the headers 0.05 inch in and the straps on the front, as the
    board file was first sketched: neither holds on this board, and both are reported."""
    solution = _t0(0.05 * inch).solve()
    assert [problem.text for problem in solution.problems] == [
        "P1 does not fit on the board: it reaches 0.48 mm past the left edge",
        "align(P1, P2, grid=2.54 mm) does not hold: P1 and P2 are 24.13 mm apart across "
        "the board, 9.5 steps",
        "P2 does not fit on the board: it reaches 0.48 mm past the right edge",
        *(f"R{n} has no place within 3 mm of U1.{pin} that is on the front of the board "
          "and clear of the other parts" for n, pin in enumerate((1, 3, 18, 17, 16), 1)),
    ]  # fmt: skip
    assert set(solution.poses) == {"P1", "P2", "U1"} and solution.free == ()
