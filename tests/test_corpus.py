"""The corpus inputs: what the importer reads from each reference, and nothing edited by hand.

``library_form`` is also checked here against every footprint KiCad saved in the
references: placed again where it was, each gives back the pads and graphics it had.
"""

import functools
import hashlib
import json
import math
import re
import runpy
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from pkidl import Board, Edge, inch, mm
from pkidl.circuit import natural
from pkidl.footprint import Placement, footprint_path, library_form, pad_xy, place
from pkidl.importer import _property, circuit, footprints, mechanical
from pkidl.project import NetClass
from pkidl.route import RouterError, router_command
from pkidl.routing import Job, Run
from pkidl.sexpr import Node, dumps, find, find_all, parse
from pkidl.units import Length

CORPUS = Path(__file__).parents[1] / "corpus"
T0 = CORPUS / "t0" / "esp12-breakout_ESP12Breakout"
BOARD_FILES = Path(__file__).parents[1] / "docs" / "design" / "board-files.md"
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


def _board_file() -> Board:
    """The T0 board, as its board file leaves it."""
    return runpy.run_path(str(T0 / "board.py"))["board"]


def test_the_t0_board_file_is_the_one_the_design_shows_and_under_30_lines():
    text = (T0 / "board.py").read_text()
    shown = re.findall(r"^```python\n(.*?)^```$", BOARD_FILES.read_text(), re.S | re.M)
    assert shown[0] == text
    # The README shows the same file.
    readme = Path(__file__).parents[1] / "README.md"
    assert re.findall(r"^```python\n(.*?)^```$", readme.read_text(), re.S | re.M) == [text]
    assert len(text.splitlines()) < 30


def _t0(inset: Length, side: str | None = None) -> Board:
    """The T0 board's real inputs, and the placement lines of its board file with the
    headers *inset* and the straps on *side*."""
    board = Board.from_inputs(T0)
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


def test_what_the_t0_board_file_says_places_every_part():
    board = _board_file()
    assert board.conflicts() == ()
    said = [s.data() for s in board.statements()]
    assert said == [
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
        {"rules": {"track": 250_000, "clearance": 200_000, "edge": 500_000}},
        {"route": True},
    ]
    assert [s.data() for s in _t0(0.075 * inch, "back").statements()] == said[:-2]
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


@dataclass
class Scripted:
    """A router that proposes nothing, and keeps what it was asked."""

    asked: list[tuple[str, Job, Path, str]] = field(default_factory=list)

    def route(self, job: Job, outdir: Path, name: str, stage: str = "") -> Run:
        self.asked.append((stage, job, outdir, name))
        return Run((), ())


def _nets(board: Node, kind: str) -> set[str]:
    return {str(net[1]) for item in find_all(board, kind) for net in find_all(item, "net")}


def test_the_t0_board_file_builds_its_circuit_with_every_part_placed(tmp_path):
    router = Scripted()
    built = _board_file().build(tmp_path, router=router)
    assert built.board == tmp_path / "esp12-breakout_ESP12Breakout.kicad_pcb"
    assert built.project == tmp_path / "esp12-breakout_ESP12Breakout.kicad_pro"
    made = parse(built.board.read_text())
    wanted = json.loads((T0 / "circuit.json").read_text())
    assert circuit(made) == wanted
    assert mechanical(made) == json.loads((T0 / "mechanical.json").read_text())
    assert sorted(built.solution.poses) == sorted(p["ref"] for p in wanted["parts"])
    assert built.solution.free == () and built.solution.problems == ()
    # The router is asked for the whole board with the ground pour known, its fill one
    # piece on the back. This one proposed nothing, which leaves the module's ground
    # pad on the front joined to no other, so it is asked again with no pour.
    (known, poured, _, _), (stage, job, outdir, name) = router.asked
    assert known == "poured" and [(net, layer) for net, layer, _ in poured.planes] == [
        ("GND", "B.Cu")
    ]
    assert built.routed is not None
    assert [str(c).partition(":")[0] for c in built.routed.cut] == [
        "U1.15 is cut off from the rest of GND"
    ]
    assert (stage, outdir, name) == ("", tmp_path, "esp12-breakout_ESP12Breakout")
    assert list(job.planes) == []
    # Either way it has the board file's rules and the antenna's area on both faces,
    # and nothing is laid.
    assert job.netclasses == [NetClass("Default", 0.2, 0.25)] and job.edge_clearance == 0.5
    # Its one track width is the least the rules allow, so no track may neck below it.
    assert job.neck_down is False and job.fan_out is False
    assert len(job.footprints) == len(wanted["parts"])
    (kept,) = built.solution.keepouts
    x0, y0, x1, y1 = (side.mm for side in kept.box)
    box = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    assert job.keepouts == [("F.Cu", box), ("B.Cu", box)]
    assert built.routed is not None and built.routed.wires == () and built.routed.vias == ()
    assert find_all(made, "segment") == [] and find_all(made, "via") == []
    assert _nets(made, "zone") == {"GND"}  # the pour the board file asks for


def test_the_t0_board_file_is_routed_by_freerouting_with_nothing_left(tmp_path):
    """Where Freerouting is installed. What it says it left is its own word: KiCad's DRC
    of the board this writes is ``just corpus``."""
    try:
        router_command()
    except RouterError as e:
        pytest.skip(str(e))
    built = _board_file().build(tmp_path)
    assert built.routed is not None
    # Routed once, with the ground pour known: nothing left unmade, and nothing the
    # pour leaves cut off.
    assert [(stage, run.unrouted) for stage, run in built.routed.runs] == [("poured", 0)]
    assert built.routed.cut == ()
    made = parse(built.board.read_text())
    wanted = json.loads((T0 / "circuit.json").read_text())
    assert circuit(made) == wanted
    # Every net with two pads or more has track on it, and no track is on another net.
    pads: dict[str, int] = {}
    for part in wanted["parts"]:
        for net in part["pads"].values():
            pads[net] = pads.get(net, 0) + 1
    # Ground is joined by its pour, with a track only where a pad on the front has to
    # be brought to it.
    assert _nets(made, "segment") == {net for net, n in pads.items() if net and n > 1}
    assert sum(1 for s in find_all(made, "segment") if find(s, "net")[1] == "GND") < 4  # type: ignore[index]


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


@each_board
def test_every_outline_encloses_one_area_with_the_extent_the_board_is_drawn_to(d):
    board = Board.from_inputs(d)
    edge = board.edge()
    assert edge is not None and edge.is_valid and board.extent is not None
    assert edge.bounds == pytest.approx(board.extent, abs=1e-6)
    assert len(board.fixed) == len(json.loads((d / "mechanical.json").read_text())["holes"])


def test_the_boards_that_are_not_the_box_around_their_outline_are_known():
    """Arcs at the corners of four, and one that narrows on a slant to a tab: where a
    part can be inside the box and off the board."""
    cut = {}
    for d in BOARDS:
        board = Board.from_inputs(d)
        edge, (x0, y0, x1, y1) = board.edge(), board.extent  # pyright: ignore[reportGeneralTypeIssues]
        share = edge.area / ((x1 - x0) * (y1 - y0))  # pyright: ignore[reportOptionalMemberAccess]
        if share < 1 - 1e-9:
            cut[d.name] = round(share, 2)
    assert cut == {
        "fan_controller_fan_controller": 0.99,
        "icehat_icehat": 1.0,
        "pcb-usb-ft245r-parallel-adapter_pcb-usb-ft245r-parallel-adapter": 0.68,
        "qrp_swr_meter_swr_meter_rev_a": 0.96,
        "usb2serial-CH340G_USB2TTL-CH340G": 0.99,
    }


def test_the_fan_controllers_headers_are_in_a_row_between_its_mounting_holes():
    """Four fan headers along the 60 mm bottom edge, each 10.3 mm by its housing, which
    its footprint draws on the silk and nowhere else: its pads alone are 9.398 mm. The
    holes 4 mm in from the corners are 3.302 mm across and reach into the strip the
    headers take up, so the edge is clear for 48.698 mm between them: five gaps of
    1.4996 mm."""
    board = Board.from_inputs(CORPUS / "t2" / "fan_controller_fan_controller")
    board.row(board.parts("P3", "P4", "P5", "P6"), along=Edge.BOTTOM)
    solution = board.solve()
    assert solution.problems == ()
    assert [solution.poses[ref].x.mm for ref in ("P3", "P4", "P5", "P6")] == pytest.approx(
        [121.3166, 133.1162, 144.9158, 156.7154]
    )
    assert solution.chosen[-1] == (
        'row(P3, P4, P5, P6, along=Edge.BOTTOM, pitch="even"): over the 48.698 mm of the '
        "bottom edge that is clear, of 60 mm"
    )
    # In the corner of the box around the board, a part is off it and over a hole.
    board.place(board["U2"], against=Edge.LEFT)
    board.place(board["U2"], against=Edge.TOP)
    told = [p.text for p in board.solve().problems]
    assert told[1] == "U2 is over MountingHole_0.13in at (112.966, 57.932)"
    assert told[0].startswith("U2 does not fit on the board: it reaches 1.65")


def _is_its_box(d: Path) -> bool:
    board = Board.from_inputs(d)
    edge, (x0, y0, x1, y1) = board.edge(), board.extent  # pyright: ignore[reportGeneralTypeIssues]
    return edge.area >= (x1 - x0) * (y1 - y0) * (1 - 1e-9)  # pyright: ignore[reportOptionalMemberAccess]


PLAIN = [d for d in BOARDS if _is_its_box(d)]


def test_ten_of_the_boards_are_plain_rectangles():
    assert len(PLAIN) == 10  # an empty list would skip the test below


@pytest.mark.parametrize("d", PLAIN, ids=lambda d: d.name)
def test_on_a_board_that_is_its_box_a_part_against_any_edge_is_on_the_board(d):
    """Drawn where they were drawn: 129.54 mm is not a whole number of nanometres until
    it is rounded."""
    board = Board.from_inputs(d)
    part = board.parts()[0]
    for side in Edge:
        tried = Board.from_inputs(d)
        tried.fixed.clear()  # the holes are another matter
        tried.place(tried[part.ref], against=side)
        solution = tried.solve()
        assert solution.problems == (), (side, solution.problems)


def test_the_fan_controllers_processor_is_decoupled_by_capacitors_on_its_own_supply():
    """U1 has two pins on +5V, 13 and 28, and pin 20 alone on a net with C12. Three
    capacitors are on +5V, C2, C8 and C9, and so is the regulator's output: one of the
    three has no pin of U1, and the netlist does not say which is which. C1 is across
    +12V and ground, which U1 is not on."""
    board = Board.from_inputs(CORPUS / "t2" / "fan_controller_fan_controller")
    board.rails("+12V", "+5V")
    board.ground("GND")
    board.place(board["U1"], centre=True)
    board.decouple(board["U1"], board.parts("C2", "C8", "C9", "C12", "C1"), within=3 * mm)
    solution = board.solve()
    said = "decouple(U1, C2, C8, C9, C12, C1, within=3 mm)"
    assert [p.text for p in solution.problems] == [
        f"{said}: C1 is across +12V and GND, and U1 is not on +12V",
        f"{said}: C9 has no pin of U1 on +5V left: C2 is by U1.13 and C8 is by U1.28",
    ]
    assert set(solution.poses) == {"C2", "C8", "C12", "U1"}
    by = {line.split(":")[0]: line.partition(",")[0].split(" from ")[1]
          for line in solution.chosen if " from " in line}  # fmt: skip
    assert by == {"C2": "U1.13", "C8": "U1.28", "C12": "U1.20"}


FAN = CORPUS / "t2" / "fan_controller_fan_controller"


def test_the_fan_controllers_board_file_is_the_one_the_design_shows():
    text = (FAN / "board.py").read_text()
    shown = re.findall(r"^```python\n(.*?)^```$", BOARD_FILES.read_text(), re.S | re.M)
    assert text in shown


@pytest.fixture(scope="module")
def fan_built(tmp_path_factory):
    """The fan controller as its board file builds it, with a router that lays nothing.
    Solving its 49 parts takes about half a minute, so once for the tests that read it."""
    router = Scripted()
    board = runpy.run_path(str(FAN / "board.py"))["board"]
    return board, board.build(tmp_path_factory.mktemp("fan"), router=router), router


def test_the_fan_controllers_board_file_places_every_part_by_what_it_says(fan_built):
    board, built, _ = fan_built
    wanted = json.loads((FAN / "circuit.json").read_text())
    assert len(wanted["parts"]) == 49
    # A build refuses a board with a problem or a part left free: this one built.
    assert sorted(built.solution.poses) == sorted(p["ref"] for p in wanted["parts"])
    made = parse(built.board.read_text())
    assert circuit(made) == wanted
    assert mechanical(made) == json.loads((FAN / "mechanical.json").read_text())
    # Each fan has the same six statements about its own parts, from one function.
    said = [str(s) for s in board.statements()]
    channel = runpy.run_path(str(FAN / "board.py"))["fan_channel"]
    for refs in zip(("P3", "P4", "P5", "P6"), ("Q2", "Q3", "Q4", "Q5"),
                    ("R15", "R16", "R17", "R18"), ("R10", "R11", "R12", "R13"),
                    ("D1", "D2", "D3", "D4"), ("R7", "R8", "R9", "R19"),
                    ("C3", "C4", "C5", "C6"), strict=True):  # fmt: skip
        mine = [str(s) for s in channel(*(board[ref] for ref in refs))]
        assert len(mine) == 6 and all(line in said for line in mine)
    # A tach pull-up is behind its header, not in the gap between two housings.
    for fan, pull_up in (("P3", "R10"), ("P4", "R11"), ("P5", "R12"), ("P6", "R13")):
        assert built.solution.poses[pull_up].y < built.solution.poses[fan].y - 3 * mm
    # The regulator's tab and the encoder's lug are in from the edge for their copper.
    assert [line for line in built.solution.chosen if " in from " in line] == [
        "SW1: 0.5 mm in from the right edge, to keep its copper 0.5 mm from it",
        "U2: 0.4492 mm in from the left edge, to keep its copper 0.5 mm from it",
    ]


def test_the_fan_controller_is_routed_with_its_tracks_as_wide_as_its_rules_say(fan_built):
    _, _, router = fan_built
    *_, (_, job, _, _) = router.asked
    assert job.netclasses == [NetClass("Default", 0.2, 0.25)]
    assert job.neck_down is False and job.fan_out is False


def test_the_fan_controllers_board_file_is_routed_by_freerouting_with_nothing_left(tmp_path):
    """Where Freerouting is installed. This is the board whose tracks it narrowed: with
    neck-down off, 13 paths out of its fan-out stage were three quarters of the width."""
    try:
        router_command()
    except RouterError as e:
        pytest.skip(str(e))
    built = runpy.run_path(str(FAN / "board.py"))["board"].build(tmp_path)
    assert built.routed is not None
    # With the ground pour known the router makes every connection by its own count,
    # and tracks on the back leave pads of ground on pieces of the pour apart from the
    # rest. That is found and said, and the board is routed again with ground carried
    # by tracks: the routing that stands.
    assert [(stage, run.unrouted) for stage, run in built.routed.runs] == [("poured", 0), ("", 0)]
    assert built.routed.cut and {c.net for c in built.routed.cut} == {"GND"}
    assert all(c.layer == "B.Cu" and c.fenced for c in built.routed.cut)
    assert {wire.width for wire in built.routed.wires} == {0.25}
    made = parse(built.board.read_text())
    assert {float(str(w[1])) for s in find_all(made, "segment")
            if (w := find(s, "width")) is not None} == {0.25}  # fmt: skip
