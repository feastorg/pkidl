"""pkidl.build: a board's KiCad files, from what its board file said.

What was built is read back from the files written, with ``pkidl.importer`` where it
reads what is asked. The router is a scripted one: what a real one does with a job is
in ``test_pkidl_route.py``.
"""

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from pkidl import Board, Edge, mm
from pkidl.build import BuildError, Built
from pkidl.dsn import Via, Wire
from pkidl.fill import Cut
from pkidl.footprint import footprint_path, pad_xy
from pkidl.importer import circuit, footprints, mechanical
from pkidl.intent import Route, Rules, route, rules
from pkidl.kicad import KicadError
from pkidl.project import NetClass
from pkidl.routing import Job, Run
from pkidl.sexpr import Node, dumps, find, find_all, parse
from pkidl.units import Length

HERE = "test_pkidl_build.py"

# A board to take inputs from, 40 by 30 mm with its corner at (100, 50): a module, a
# header, a resistor and a mounting hole. Where its parts are is not an input.
SOURCE = """(kicad_pcb
  (gr_rect (start 100 50) (end 140 80) (layer "Edge.Cuts"))
  (footprint "RF:M" (layer "F.Cu") (at 0 0)
    (property "Reference" "U1" (at 0 0) (layer "F.SilkS"))
    (property "Value" "M" (at 0 0) (layer "F.Fab"))
    (fp_rect (start -1 -4) (end 9 3) (stroke (width 0.05) (type solid)) (fill no)
      (layer "F.CrtYd"))
    (pad "1" smd rect (at 0 0) (size 2 1) (layers "F.Cu") (net "A"))
    (pad "2" smd rect (at 0 2) (size 2 1) (layers "F.Cu") (net "B"))
    (pad "3" smd rect (at 8 2) (size 2 1) (layers "F.Cu") (net "GND"))
    (pad "4" smd rect (at 8 0) (size 2 1) (layers "F.Cu")))
  (footprint "Conn:H" (layer "F.Cu") (at 0 0)
    (property "Reference" "P1" (at 0 0) (layer "F.SilkS"))
    (property "Value" "H" (at 0 0) (layer "F.Fab"))
    (fp_rect (start -1.75 -1.75) (end 6.83 1.75) (stroke (width 0.05) (type solid)) (fill no)
      (layer "F.CrtYd"))
    (pad "1" thru_hole circle (at 0 0) (size 1.7 1.7) (drill 1) (layers "*.Cu") (net "A"))
    (pad "2" thru_hole circle (at 2.54 0) (size 1.7 1.7) (drill 1) (layers "*.Cu") (net "B"))
    (pad "3" thru_hole circle (at 5.08 0) (size 1.7 1.7) (drill 1) (layers "*.Cu")
      (net "GND")))
  (footprint "Device:R" (layer "F.Cu") (at 0 0)
    (property "Reference" "R1" (at 0 0) (layer "F.SilkS"))
    (property "Value" "10k" (at 0 0) (layer "F.Fab"))
    (fp_rect (start -1.8 -0.9) (end 1.8 0.9) (stroke (width 0.05) (type solid)) (fill no)
      (layer "F.CrtYd"))
    (pad "1" smd rect (at -1 0) (size 1 1.2) (layers "F.Cu") (net "B"))
    (pad "2" smd rect (at 1 0) (size 1 1.2) (layers "F.Cu") (net "GND")))
  (footprint "Mech:M3" (layer "F.Cu") (at 136 76)
    (property "Reference" "REF**" (at 0 0) (layer "F.SilkS"))
    (pad "" np_thru_hole circle (at 0 0) (size 3.2 3.2) (drill 3.2) (layers "*.Cu"))))"""

VIA = "Via[0-1]_800:400_um"
A_ROUTE = Wire("A", "F.Cu", 0.25, [(105.0, 60.0), (110.0, 60.0), (110.0, 65.0)])
B_ROUTE = Wire("B", "B.Cu", 0.25, [(105.0, 62.0), (112.0, 62.0)])
B_VIA = Via("B", VIA, (112.0, 62.0))


@pytest.fixture
def inputs(tmp_path: Path) -> Path:
    """A directory of inputs read from SOURCE, as ``scripts/corpus.py extract`` writes
    one, named as a board is."""
    d = tmp_path / "breakout"
    source = parse(SOURCE)
    d.mkdir()
    (d / "circuit.json").write_text(json.dumps(circuit(source)))
    (d / "mechanical.json").write_text(json.dumps(mechanical(source)))
    for name, lib in footprints(source)[0].items():
        path = d / "footprints" / footprint_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dumps(lib) + "\n")
    return d


@pytest.fixture
def board(inputs: Path) -> Board:
    """The board with every part given a place: the header down the left edge, the
    module against the top with its fourth pad's end marked as its antenna, and the
    resistor by the module's second pin."""
    board = Board.from_inputs(inputs)
    u1, p1, r1 = board.parts("U1", "P1", "R1")
    board.annotate(u1, antenna=((6 * mm, -4 * mm), (9 * mm, -1 * mm)))
    board.place(p1, against=Edge.LEFT, inset=3 * mm)
    board.place(u1, against=Edge.TOP, facing=Edge.TOP)
    board.place(r1, near=u1.pin(2), within=4 * mm)
    return board


@dataclass
class Scripted:
    """A router that hands back what it was told to, and keeps what it was asked."""

    run: Run = Run((), ())
    asked: list[tuple[str, Job, Path, str]] = field(default_factory=list)

    def route(self, job: Job, outdir: Path, name: str, stage: str = "") -> Run:
        self.asked.append((stage, job, outdir, name))
        return self.run


def _line_no() -> int:
    """The line this is called on; the statement above it is on ``_line_no() - 1``."""
    return sys._getframe(1).f_lineno


def _ref(footprint: Node) -> str:
    return next(str(p[2]) for p in find_all(footprint, "property") if p[1] == "Reference")


def _rule_areas(written: Node) -> list[tuple[str, str, list[tuple[float, float]]]]:
    """Each rule area of a board: its name, its layer and its corners."""
    found = []
    for zone in find_all(written, "zone"):
        if find(zone, "keepout") is not None:
            polygon = find(zone, "polygon")
            assert polygon is not None
            corners = [(float(xy[1]), float(xy[2])) for xy in find_all(polygon[1], "xy")]
            found.append((str(find(zone, "name")[1]), str(find(zone, "layer")[1]), corners))  # type: ignore[index]
    return found


def test_a_board_is_built_with_each_part_where_what_was_said_puts_it(board, inputs, tmp_path):
    solution = board.solve()
    built = board.build(tmp_path / "out")
    assert built == Built(tmp_path / "out" / "breakout.kicad_pcb", None, solution, None)
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["breakout.kicad_pcb"]
    written = parse(built.board.read_text())
    # The circuit and the mechanical requirements are the ones it was given.
    assert circuit(written) == json.loads((inputs / "circuit.json").read_text())
    assert mechanical(written) == json.loads((inputs / "mechanical.json").read_text())
    placed = {_ref(fp): fp for fp in find_all(written, "footprint") if _ref(fp) != "REF**"}
    assert list(placed) == ["P1", "R1", "U1"] == list(solution.poses)
    for ref, fp in placed.items():
        pose = solution.poses[ref]
        at = find(fp, "at")
        assert at is not None
        assert [float(v) for v in at[1:]] == [pose.x.mm, pose.y.mm, *([pose.rot] * bool(pose.rot))]
        assert find(fp, "layer")[1] == ("B.Cu" if pose.back else "F.Cu")  # type: ignore[index]
    # Nothing was routed, and nothing is kept clear.
    assert find_all(written, "segment") == find_all(written, "via") == []
    assert _rule_areas(written) == []


def test_a_part_on_the_back_is_built_on_the_back(board, tmp_path):
    board.place(board["R1"], side="back")
    written = parse(board.build(tmp_path).board.read_text())
    layers = {_ref(fp): find(fp, "layer")[1] for fp in find_all(written, "footprint")}  # type: ignore[index]
    assert layers == {"REF**": "F.Cu", "P1": "F.Cu", "R1": "B.Cu", "U1": "F.Cu"}


def test_the_board_is_left_as_it_was_and_builds_the_same_files_again(board, tmp_path):
    board.rules(track=0.25 * mm, clearance=0.2 * mm)
    board.route()
    board.keepout(board["U1"].area("antenna"), copper=True)
    before, said = dumps(board.sexpr()), board.statements()
    router = Scripted(Run((A_ROUTE, B_ROUTE), (B_VIA,), 0))
    first = board.build(tmp_path / "one", router=router)
    assert dumps(board.sexpr()) == before
    assert board.statements() == said
    second = board.build(tmp_path / "two", router=router)
    assert first.board.read_bytes() == second.board.read_bytes()
    assert first.project is not None and second.project is not None
    assert first.project.read_bytes() == second.project.read_bytes()


def test_the_files_are_named_for_the_inputs_directory_or_as_asked(board, tmp_path):
    assert board.name == "breakout"
    assert board.build(tmp_path).board == tmp_path / "breakout.kicad_pcb"
    board.rules(track=0.25 * mm, clearance=0.2 * mm)
    built = board.build(str(tmp_path), "rev-b")
    assert (built.board, built.project) == (tmp_path / "rev-b.kicad_pcb",
                                            tmp_path / "rev-b.kicad_pro")  # fmt: skip


def test_a_board_from_a_file_in_its_inputs_is_named_for_their_directory(inputs, monkeypatch):
    assert Board.from_inputs(inputs / "board.py").name == "breakout"
    # However the path was written: from inside the directory it is still that directory.
    monkeypatch.chdir(inputs)
    assert Board.from_inputs(".").name == "breakout"
    assert Board.from_inputs("board.py").name == "breakout"


def test_a_board_with_no_name_is_built_under_the_one_given(board, tmp_path):
    bare = Board(circuit=board.circuit, library=board.library, extent=board.extent)
    for statement in board.statements():
        bare.add(statement)
    with pytest.raises(ValueError, match=r"build\(\) needs a name for the board's files"):
        bare.build(tmp_path / "out")
    assert not (tmp_path / "out").exists()
    assert bare.build(tmp_path / "out", "bare").board == tmp_path / "out" / "bare.kicad_pcb"
    # A directory under one that is not there yet is made with it.
    deep = tmp_path / "not" / "yet" / "there"
    assert (
        bare.build(deep, "bare").board.read_text()
        == (tmp_path / "out" / "bare.kicad_pcb").read_text()
    )


def test_an_area_kept_clear_is_a_rule_area_on_the_parts_face(board, tmp_path):
    board.keepout(board["U1"].area("antenna"), copper=True)
    built = board.build(tmp_path)
    (kept,) = built.solution.keepouts
    x0, y0, x1, y1 = (side.mm for side in kept.box)
    box = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    written = parse(built.board.read_text())
    assert _rule_areas(written) == [("U1 antenna", "F.Cu", box)]
    # Nothing of copper is let in.
    (zone,) = [z for z in find_all(written, "zone") if find(z, "keepout") is not None]
    rule = find(zone, "keepout")
    assert rule is not None
    assert {str(k[0]): str(k[1]) for k in rule[1:]} == {
        "tracks": "not_allowed", "vias": "not_allowed", "copperpour": "not_allowed",
        "pads": "allowed", "footprints": "allowed",
    }  # fmt: skip


def test_an_area_kept_clear_on_both_sides_is_a_rule_area_on_each(board, tmp_path):
    area = board["U1"].area("antenna")
    board.keepout(area, copper=True, both_sides=True)
    board.keepout(area, copper=True)  # said of the front again: it is drawn once
    written = parse(board.build(tmp_path).board.read_text())
    assert [(name, layer) for name, layer, _ in _rule_areas(written)] == [
        ("U1 antenna", "F.Cu"), ("U1 antenna", "B.Cu"),
    ]  # fmt: skip
    assert _rule_areas(written)[0][2] == _rule_areas(written)[1][2]


def test_the_area_of_a_part_on_the_back_is_kept_clear_on_the_back(board, tmp_path):
    (pad,) = board.annotate(board["R1"], pad=((-1.5 * mm, -0.6 * mm), (-0.5 * mm, 0.6 * mm)))
    board.place(board["R1"], side="back")
    board.keepout(pad, copper=True)
    written = parse(board.build(tmp_path).board.read_text())
    assert [(name, layer) for name, layer, _ in _rule_areas(written)] == [("R1 pad", "B.Cu")]


def test_a_board_that_says_route_is_routed_by_the_router_to_its_rules(board, tmp_path):
    board.rules(track=0.25 * mm, clearance=0.2 * mm, edge=0.3 * mm)
    board.route()
    board.keepout(board["U1"].area("antenna"), copper=True, both_sides=True)
    router = Scripted(Run((A_ROUTE, B_ROUTE), (B_VIA,), 0))
    built = board.build(tmp_path, router=router)
    ((stage, job, outdir, name),) = router.asked
    assert (stage, outdir, name) == ("", tmp_path, "breakout")
    written = parse(built.board.read_text())
    # The router is given the board as it is built: every part placed, and the hole.
    on_board = find_all(written, "footprint")
    assert [dumps(fp) for fp in job.footprints] == [dumps(fp) for fp in on_board]
    assert [_ref(fp) for fp in job.footprints] == ["REF**", "P1", "R1", "U1"]
    assert list(job.outline) == [(100.0, 50.0), (140.0, 50.0), (140.0, 80.0), (100.0, 80.0)]
    assert list(job.netclasses) == [NetClass("Default", 0.2, 0.25)]
    assert (dict(job.members), job.edge_clearance) == ({}, 0.3)
    assert [(layer, list(box)) for layer, box in job.keepouts] == [
        (layer, box) for _, layer, box in _rule_areas(written)
    ]
    assert [layer for layer, _ in job.keepouts] == ["F.Cu", "B.Cu"]
    assert (list(job.wires), list(job.vias), list(job.planes)) == ([], [], [])
    # What it proposes is on the board that is written, and in the result.
    assert built.routed is not None
    assert (built.routed.wires, built.routed.vias) == ((A_ROUTE, B_ROUTE), (B_VIA,))
    assert built.routed.runs == (("", router.run),)
    tracks = [(str(find(s, "net")[1]), str(find(s, "layer")[1]),  # type: ignore[index]
               [float(v) for v in find(s, "start")[1:]], [float(v) for v in find(s, "end")[1:]])  # type: ignore[index]
              for s in find_all(written, "segment")]  # fmt: skip
    assert tracks == [("A", "F.Cu", [105.0, 60.0], [110.0, 60.0]),
                      ("A", "F.Cu", [110.0, 60.0], [110.0, 65.0]),
                      ("B", "B.Cu", [105.0, 62.0], [112.0, 62.0])]  # fmt: skip
    (via,) = find_all(written, "via")
    assert [float(v) for v in find(via, "at")[1:]] == [112.0, 62.0]  # type: ignore[index]
    assert [float(find(via, key)[1]) for key in ("size", "drill")] == [0.8, 0.4]  # type: ignore[index]


def test_connections_the_router_leaves_unmade_are_in_the_result_and_the_board_is_written(
    board, tmp_path
):
    board.rules(track=0.25 * mm, clearance=0.2 * mm)
    board.route()
    built = board.build(tmp_path, router=Scripted(Run((A_ROUTE,), (), 2)))
    assert built.routed is not None
    assert [(stage, run.unrouted) for stage, run in built.routed.runs] == [("", 2)]
    assert len(find_all(parse(built.board.read_text()), "segment")) == 2


def test_a_board_that_does_not_say_route_is_not_routed(board, tmp_path):
    board.rules(track=0.25 * mm, clearance=0.2 * mm)
    router = Scripted(Run((A_ROUTE,), (), 0))
    built = board.build(tmp_path, router=router)
    assert router.asked == [] and built.routed is None
    assert find_all(parse(built.board.read_text()), "segment") == []
    assert built.project == tmp_path / "breakout.kicad_pro"


def test_the_rules_are_the_projects(board, tmp_path):
    board.rules(track="0.3mm", clearance=0.15 * mm)
    project = board.build(tmp_path).project
    assert project is not None
    wrote = json.loads(project.read_text())
    (default,) = wrote["net_settings"]["classes"]
    assert (default["name"], default["clearance"], default["track_width"]) == ("Default", 0.15, 0.3)
    assert wrote["board"]["design_settings"]["rules"] == {
        "min_clearance": 0.15, "min_track_width": 0.3, "min_copper_edge_clearance": 0.5,
    }  # fmt: skip
    assert wrote["net_settings"]["netclass_patterns"] == []


def test_route_with_no_rules_is_not_built_and_says_where_it_was_said(board, tmp_path):
    board.route()
    line = _line_no() - 1
    with pytest.raises(BuildError) as told:
        board.build(tmp_path / "out", router=Scripted())
    assert told.value.problems == (
        f"route() ({HERE}:{line}) needs the board's rules: say rules(track=, clearance=)",
    )
    assert str(told.value) == f"breakout is not built:\n  {told.value.problems[0]}"
    assert not (tmp_path / "out").exists()


def test_what_conflicts_is_said_once_and_nothing_is_built(board, tmp_path):
    board.place(board["P1"], against=Edge.LEFT, inset=4 * mm)
    first = _line_no() - 1
    board.rules(track=0.25 * mm, clearance=0.2 * mm)
    board.rules(track=0.3 * mm, clearance=0.2 * mm)
    board.route()
    router = Scripted()
    with pytest.raises(BuildError) as told:
        board.build(tmp_path / "out", "b", router=router)
    conflict, rule = told.value.problems
    assert conflict.startswith("P1: inset from the left edge is 3 mm (")
    assert conflict.endswith(f") and 4 mm ({HERE}:{first})")
    assert rule == (f"the board: track width is 0.25 mm ({HERE}:{first + 2}) and 0.3 mm "
                    f"({HERE}:{first + 3})")  # fmt: skip
    assert told.value.problems == tuple(str(c) for c in board.conflicts())
    assert str(told.value) == f"b is not built:\n  {conflict}\n  {rule}"
    assert router.asked == [] and not (tmp_path / "out").exists()


def test_what_does_not_hold_or_is_not_placed_is_said_and_nothing_is_built(inputs, tmp_path):
    board = Board.from_inputs(inputs)
    u1, p1 = board.parts("U1", "P1")
    board.place(p1, against=Edge.LEFT, inset=3 * mm)
    board.place(u1, against=Edge.TOP, inset=40 * mm)
    line = _line_no() - 1
    board.rules(track=0.25 * mm, clearance=0.2 * mm)
    board.route()
    router = Scripted()
    with pytest.raises(BuildError) as told:
        board.build(tmp_path / "out", router=router)
    solution = board.solve()
    (problem,) = solution.problems
    assert problem.parts == ("U1",) and str(problem).endswith(f"({HERE}:{line})")
    assert solution.free == ("R1",)
    assert told.value.problems == (str(problem), "R1 is not placed: nothing says where it goes")
    assert router.asked == [] and not (tmp_path / "out").exists()


def test_rules_and_route_are_statements_about_the_board(board):
    said = board.rules(track=0.25 * mm, clearance="8mil")
    line = _line_no() - 1
    assert said == Rules(Length(250_000), Length(203_200), Length(500_000))
    assert str(said) == "rules(track=0.25 mm, clearance=0.2032 mm, edge=0.5 mm)"
    assert str(said.source) == f"{HERE}:{line}"
    assert said.data() == {"rules": {"track": 250_000, "clearance": 203_200, "edge": 500_000}}
    assert said.mentions() == ()
    assert rules(track=0.25 * mm, clearance="8mil") == said  # 0.5 mm from the edge, unasked
    routed = board.route()
    assert routed == Route() == route()
    assert (str(routed), routed.data(), routed.mentions()) == ("route()", {"route": True}, ())
    assert str(routed.source) == f"{HERE}:{_line_no() - 3}"
    # Each is said once, however often; neither is about a part.
    before = board.statements()
    board.rules(track=0.25 * mm, clearance="8mil")
    board.route()
    board.add(rules(track=250_000 * Length(1), clearance=0.2032 * mm, edge="0.5mm"))
    assert board.statements() == before
    assert board.conflicts() == ()
    assert said not in board.statements("U1") and routed not in board.statements("U1")
    # Where the parts go is what it was without them.
    assert board.solve().ok


def test_each_rule_is_said_once(board):
    board.rules(track=0.25 * mm, clearance=0.2 * mm)
    line = _line_no() - 1
    board.rules(track=0.25 * mm, clearance=0.15 * mm, edge=0.3 * mm)
    assert [str(c) for c in board.conflicts()] == [
        f"the board: clearance is 0.2 mm ({HERE}:{line}) and 0.15 mm ({HERE}:{line + 2})",
        f"the board: clearance from the edge is 0.5 mm ({HERE}:{line}) and 0.3 mm "
        f"({HERE}:{line + 2})",
    ]


@pytest.mark.parametrize(
    ("said", "told"),
    [
        ({"track": 0 * mm, "clearance": 0.2 * mm}, r"rules\(\): track= 0 mm is not a width"),
        ({"track": 0.25 * mm, "clearance": -0.2 * mm},
         r"rules\(\): clearance= -0.2 mm is not a width"),
        ({"track": 0.25 * mm, "clearance": 0.2 * mm, "edge": -0.1 * mm},
         r"rules\(\): edge= -0.1 mm is outside the board"),
    ],
)  # fmt: skip
def test_a_rule_that_is_not_a_width_is_refused(board, said, told):
    with pytest.raises(ValueError, match=told):
        board.rules(**said)
    assert board.statements() == board.statements()[:3]


def test_copper_may_reach_the_edge_where_the_rules_say_so(board, tmp_path):
    board.rules(track=0.25 * mm, clearance=0.2 * mm, edge=0 * mm)
    board.route()
    router = Scripted()
    board.build(tmp_path, router=router)
    assert router.asked[0][1].edge_clearance == 0.0


def test_a_bare_number_is_not_a_rule(board):
    with pytest.raises(TypeError, match="0.25 has no unit"):
        board.rules(track=0.25, clearance=0.2 * mm)  # type: ignore[arg-type]


def test_how_a_board_is_assembled_is_a_word_or_two_distances_or_both(board):
    said = board.rules(track=0.5 * mm, clearance=0.3 * mm, assembly="hand")
    line = _line_no() - 1
    assert said == Rules(Length(500_000), Length(300_000), Length(500_000), "hand")
    assert str(said) == 'rules(track=0.5 mm, clearance=0.3 mm, edge=0.5 mm, assembly="hand")'
    assert str(said.source) == f"{HERE}:{line}"
    assert said.data() == {"rules": {"track": 500_000, "clearance": 300_000, "edge": 500_000,
                                     "assembly": "hand"}}  # fmt: skip
    # The word's distances: between the pads of different parts, and between parts.
    assert said.apart() == (Length(1_270_000), Length(500_000))
    assert rules(track=0.5 * mm, clearance=0.3 * mm, assembly="machine").apart() == (
        Length(0), Length(0)
    )  # fmt: skip
    # A number said is the one, over the word's and with no word.
    over = rules(track=0.5 * mm, clearance=0.3 * mm, assembly="hand", pads_apart="1.5mm")
    assert over.apart() == (Length(1_500_000), Length(500_000))
    assert str(over) == ('rules(track=0.5 mm, clearance=0.3 mm, edge=0.5 mm, assembly="hand", '
                         "pads_apart=1.5 mm)")  # fmt: skip
    assert over.data() == {"rules": {"track": 500_000, "clearance": 300_000, "edge": 500_000,
                                     "assembly": "hand", "pads_apart": 1_500_000}}  # fmt: skip
    under = rules(track=0.5 * mm, clearance=0.3 * mm, assembly="hand", bodies_apart=0 * mm)
    assert under.apart() == (Length(1_270_000), Length(0))
    bare = rules(track=0.5 * mm, clearance=0.3 * mm, pads_apart=1 * mm, bodies_apart=0.3 * mm)
    assert bare.apart() == (Length(1_000_000), Length(300_000))
    assert str(bare) == ("rules(track=0.5 mm, clearance=0.3 mm, edge=0.5 mm, pads_apart=1 mm, "
                         "bodies_apart=0.3 mm)")  # fmt: skip
    assert bare.data() == {"rules": {"track": 500_000, "clearance": 300_000, "edge": 500_000,
                                     "pads_apart": 1_000_000, "bodies_apart": 300_000}}  # fmt: skip
    # With none of it said nothing is kept apart, and the statement is what it was.
    plain = rules(track=0.5 * mm, clearance=0.3 * mm)
    assert plain.apart() == (Length(0), Length(0))
    assert plain == Rules(Length(500_000), Length(300_000), Length(500_000))
    assert plain.data() == {"rules": {"track": 500_000, "clearance": 300_000, "edge": 500_000}}


@pytest.mark.parametrize(
    ("said", "error", "told"),
    [
        ({"assembly": ["hand"]}, ValueError,
         r"rules\(\): assembly= .* is not how a board is assembled"),
        ({"assembly": "wave"}, ValueError,
         r'rules\(\): assembly= "wave" is not how a board is assembled: "hand" or "machine"'),
        ({"assembly": True}, ValueError,
         r'rules\(\): assembly= True is not how a board is assembled: "hand" or "machine"'),
        ({"pads_apart": -1 * mm}, ValueError, r"rules\(\): pads_apart= -1 mm is not a distance"),
        ({"assembly": "hand", "bodies_apart": "-0.1mm"}, ValueError,
         r"rules\(\): bodies_apart= -0.1 mm is not a distance"),
        ({"pads_apart": 1.27}, TypeError, "1.27 has no unit"),
        ({"bodies_apart": "half a mil"}, ValueError, "'half a mil' is not a length"),
    ],
)  # fmt: skip
def test_a_way_of_assembling_that_is_not_one_is_refused_where_it_is_said(board, said, error, told):
    with pytest.raises(error, match=told):
        board.rules(track=0.25 * mm, clearance=0.2 * mm, **said)
    assert board.statements() == board.statements()[:3]


def test_how_a_board_is_assembled_is_said_once(board):
    board.rules(track=0.25 * mm, clearance=0.2 * mm, assembly="hand")
    line = _line_no() - 1
    # The same distances said the long way agree with the word.
    board.rules(track=0.25 * mm, clearance=0.2 * mm, pads_apart=1.27 * mm, bodies_apart=0.5 * mm)
    assert board.conflicts() == ()
    board.rules(track=0.25 * mm, clearance=0.2 * mm, assembly="machine")
    board.rules(track=0.25 * mm, clearance=0.2 * mm, assembly="hand", pads_apart=1 * mm)
    board.rules(track=0.25 * mm, clearance=0.2 * mm, assembly="hand", bodies_apart=1 * mm)
    assert [str(c) for c in board.conflicts()] == [
        f'the board: assembly is "hand" ({HERE}:{line}) and "machine" ({HERE}:{line + 5})',
        f"the board: distance between parts is 0.5 mm ({HERE}:{line}) and 0 mm ({HERE}:{line + 5})",
        f"the board: distance between parts is 0.5 mm ({HERE}:{line}) and 1 mm ({HERE}:{line + 7})",
        f"the board: distance between the pads of different parts is 1.27 mm ({HERE}:{line}) "
        f"and 0 mm ({HERE}:{line + 5})",
        f"the board: distance between the pads of different parts is 1.27 mm ({HERE}:{line}) "
        f"and 1 mm ({HERE}:{line + 6})",
    ]
    # Nothing is placed from statements that conflict.
    assert [p.text for p in board.solve().problems] == [str(c) for c in board.conflicts()]


def test_saying_nothing_of_assembly_and_saying_a_word_for_something_are_two_things(board):
    board.rules(track=0.25 * mm, clearance=0.2 * mm)
    line = _line_no() - 1
    board.rules(track=0.25 * mm, clearance=0.2 * mm, assembly="machine")  # which is nothing
    assert board.conflicts() == ()
    board.rules(track=0.25 * mm, clearance=0.2 * mm, assembly="hand")
    assert [str(c) for c in board.conflicts()] == [
        f'the board: assembly is "machine" ({HERE}:{line + 2}) and "hand" ({HERE}:{line + 4})',
        f"the board: distance between parts is 0 mm ({HERE}:{line}) and 0.5 mm ({HERE}:{line + 4})",
        f"the board: distance between the pads of different parts is 0 mm ({HERE}:{line}) and "
        f"1.27 mm ({HERE}:{line + 4})",
    ]


def test_nothing_of_how_a_board_is_assembled_is_written_into_its_project(inputs, tmp_path):
    def project(out: str, **how) -> str:
        board = Board.from_inputs(inputs)
        u1, p1, r1 = board.parts("U1", "P1", "R1")
        board.place(p1, against=Edge.LEFT, inset=3 * mm)
        board.place(u1, against=Edge.TOP, facing=Edge.TOP)
        board.place(r1, near=u1.pin(2), within=6 * mm)
        board.rules(track=0.25 * mm, clearance=0.2 * mm, **how)
        project = board.build(tmp_path / out, "b").project
        assert project is not None
        return project.read_text()

    assert project("hand", assembly="hand") == project("plain")


def _pours(built: Built) -> dict[tuple[str, str], tuple[float, float]]:
    """Each pour of a built board: by net and layer, its clearance and thermal gap."""
    found = {}
    for zone in find_all(parse(built.board.read_text()), "zone"):
        net, layer = find(zone, "net"), find(zone, "layer")
        if net is None or layer is None or find(zone, "keepout") is not None:
            continue
        gap, relief = (
            find(find(zone, "connect_pads") or [], "clearance"),
            find(find(zone, "fill") or [], "thermal_gap"),
        )
        assert gap is not None and relief is not None
        found[str(net[1]), str(layer[1])] = (float(str(gap[1])), float(str(relief[1])))
    return found


def test_a_pour_is_as_near_other_copper_and_its_pads_as_the_rules_let_a_track_be(board, tmp_path):
    board.pour("GND", layer="B.Cu")
    # On a board with no rules a pour is as a zone is drawn.
    assert _pours(board.build(tmp_path / "plain")) == {("GND", "B.Cu"): (0.4, 0.5)}
    board.rules(track=0.25 * mm, clearance=0.2 * mm)
    assert _pours(board.build(tmp_path / "ruled")) == {("GND", "B.Cu"): (0.2, 0.2)}
    # The board itself is as it was said, whatever was built from it.
    (drawn,) = find_all(parse(dumps(board.items[-1])), "connect_pads")
    assert float(str(find(drawn, "clearance")[1])) == 0.4  # type: ignore[index]


def test_what_a_pour_says_of_its_own_clearance_or_thermal_gap_is_kept(board, tmp_path):
    board.rules(track=0.25 * mm, clearance=0.2 * mm)
    board.pour("GND", layer="B.Cu", clearance=0.3)
    board.pour("GND", layer="F.Cu", thermal_gap=0.6)
    board.pour("A", layer="F.Cu", clearance=0.35, thermal_gap=0.45, priority=1)
    assert _pours(board.build(tmp_path / "out")) == {
        ("GND", "B.Cu"): (0.3, 0.2),
        ("GND", "F.Cu"): (0.2, 0.6),
        ("A", "F.Cu"): (0.35, 0.45),
    }


def test_rules_that_ask_more_clearance_do_not_widen_a_pours_thermal_gap(board, tmp_path):
    # The gap is between a pad and its own net's pour: a wider one starves the spokes.
    board.rules(track=0.25 * mm, clearance=0.8 * mm)
    board.pour("GND", layer="B.Cu")
    assert _pours(board.build(tmp_path / "out")) == {("GND", "B.Cu"): (0.8, 0.5)}


def test_a_pour_around_parts_is_sized_as_one_over_the_whole_board_is(board, tmp_path):
    board.rules(track=0.25 * mm, clearance=0.2 * mm)
    part = ('(footprint "R" (at {x} 60) (property "Reference" "{ref}") '
            '(pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net "A")))')  # fmt: skip
    around = [parse(part.format(x=105, ref="R8")), parse(part.format(x=110, ref="R9"))]
    board.pour("A", layer="F.Cu", around=around, margin=0.5)
    board.pour("A", layer="F.Cu", around=around, margin=1.0)  # and a second, the same net
    written = parse(board.build(tmp_path / "out").board.read_text())
    sized = [(float(str(find(find(z, "connect_pads") or [], "clearance")[1])),  # type: ignore[index]
              float(str(find(find(z, "fill") or [], "thermal_gap")[1])))  # type: ignore[index]
             for z in find_all(written, "zone") if find(z, "keepout") is None]  # fmt: skip
    assert sized == [(0.2, 0.2), (0.2, 0.2)]


def test_a_zone_drawn_by_hand_is_not_sized_by_the_rules(board, tmp_path):
    board.rules(track=0.25 * mm, clearance=0.2 * mm)
    board.zone("GND", "B.Cu", [(101.0, 51.0), (119.0, 51.0), (119.0, 69.0), (101.0, 69.0)])
    assert _pours(board.build(tmp_path / "out")) == {("GND", "B.Cu"): (0.4, 0.5)}


def test_a_board_with_a_pour_is_routed_with_it_known_and_checked_with_what_was_proposed(
    board, tmp_path
):
    board.rules(track=0.25 * mm, clearance=0.2 * mm)
    board.pour("GND", layer="B.Cu")
    board.route()
    # A router that proposes nothing leaves the two ground pads on the front joined to
    # nothing: the header's pin is in the pour, through the board, and they are not.
    nothing = Scripted()
    built = board.build(tmp_path / "first", router=nothing)
    assert built.routed is not None
    # It is asked to join them by a track, lays none, and is asked again with no pour.
    assert [stage for stage, *_ in nothing.asked] == ["poured", "poured-join", ""]
    assert [(net, layer) for net, layer, _ in nothing.asked[0][1].planes] == [("GND", "B.Cu")]
    assert nothing.asked[1][1].only == {"GND"} and list(nothing.asked[2][1].planes) == []
    assert built.routed.joined == () and built.routed.taken_off == ()
    assert [str(c) for c in built.routed.cut] == [
        "R1.2 is cut off from the rest of GND: no pour reaches there",
        "U1.3 is cut off from the rest of GND: no pour reaches there",
    ]
    # One that proposes a via down to the pour at each of them is taken at that: what
    # it proposed is laid before the pour is asked about.
    placed = {_ref(fp): fp for fp in find_all(parse(built.board.read_text()), "footprint")}
    down = tuple(
        Via("GND", VIA, pad_xy(placed[ref], pad)) for ref, pad in (("R1", "2"), ("U1", "3"))
    )
    joining = Scripted(Run((), down, 0))
    built = board.build(tmp_path / "second", router=joining)
    assert built.routed is not None
    assert [stage for stage, *_ in joining.asked] == ["poured"]
    assert built.routed.cut == () and built.routed.vias == down


def test_the_pour_the_router_is_told_of_keeps_the_rules_edge_and_kicads_hole_clearance(
    board, tmp_path
):
    from shapely.geometry import Point as At
    from shapely.geometry import Polygon

    board.rules(track=0.25 * mm, clearance=0.2 * mm, edge=1 * mm)
    board.pour("GND", layer="B.Cu")
    board.route()
    router = Scripted()
    board.build(tmp_path, router=router)
    ((_, _, outline),) = router.asked[0][1].planes
    plane = Polygon(outline)
    # 1 mm in from the 40 by 30 mm board's edge, as the rules say.
    assert [round(v, 3) for v in plane.bounds] == [101.0, 51.0, 139.0, 79.0]
    # And 0.25 mm from the mounting hole, 3.2 mm across at (136, 76), where the rules'
    # own clearance is 0.2 mm: the corner of the pour is cut back round it.
    assert abs(plane.distance(At(136, 76)) - (1.6 + 0.25)) < 0.005


KICAD_STUB = """import json, sys
from pathlib import Path
args = sys.argv[1:]
Path(__file__).with_suffix(".args").write_text("\\n".join(args))
Path(args[args.index("-o") + 1]).write_text(json.dumps({report}))
"""
LEFT = {"unconnected_items": [{"items": [
    {"description": "Zone [GND] on B.Cu, priority 0"},
    {"description": "PTH pad 3 [GND] of P1"},
]}]}  # fmt: skip


@pytest.fixture
def kicad(tmp_path, monkeypatch):
    """Stand a script in for KiCad's command line: it writes *report* as its DRC report
    and leaves the arguments it was run with to be read back."""

    def stand_in(report: dict):
        script = tmp_path / "kicad.py"
        script.write_text(KICAD_STUB.format(report=report))
        monkeypatch.setenv("KICAD_CLI", f"{sys.executable} {script}")
        return lambda: script.with_suffix(".args").read_text().split("\n")

    return stand_in


def _poured(board: Board) -> Board:
    board.rules(track=0.25 * mm, clearance=0.2 * mm)
    board.pour("GND", layer="B.Cu")
    board.route()
    return board


def test_where_kicad_is_installed_it_is_kicad_that_says_what_a_pour_leaves_cut_off(
    board, tmp_path, kicad
):
    ran_with = kicad({"unconnected_items": []})
    router = Scripted()
    built = _poured(board).build(tmp_path / "out", router=router)
    assert built.routed is not None
    # This router proposed nothing, which the model calls two pads cut off. KiCad was
    # asked, said nothing is unconnected, and its word stands: one run.
    assert [stage for stage, *_ in router.asked] == ["poured"]
    assert built.routed.cut == () and built.routed.judge == "KiCad"
    # It was given the board as proposed, with its project, and asked to fill it.
    args = ran_with()
    asked = tmp_path / "out" / "breakout-poured-check.kicad_pcb"
    assert args[:3] == ["pcb", "drc", "--refill-zones"] and args[-1] == str(asked)
    assert "--severity-all" in args and args[args.index("--format") + 1] == "json"
    assert asked.exists() and asked.with_suffix(".kicad_pro").exists()
    assert _pours(Built(asked, None, built.solution, None)) == {("GND", "B.Cu"): (0.2, 0.2)}


def test_what_kicad_leaves_unconnected_is_said_in_its_words_and_routed_again(
    board, tmp_path, kicad
):
    kicad(LEFT)
    router = Scripted()
    built = _poured(board).build(tmp_path / "out", router=router)
    assert built.routed is not None
    assert [stage for stage, *_ in router.asked] == ["poured", "poured-join", ""]
    (cut,) = built.routed.cut
    assert (cut.net, cut.pads) == ("GND", ("P1.3",))
    assert str(cut) == ("KiCad, of GND: Zone [GND] on B.Cu, priority 0 and PTH pad 3 [GND] of P1")
    assert built.routed.judge == "KiCad"
    # The board routed again still has its pour drawn, and is checked too: what KiCad
    # says of that one is of the board that was written.
    assert built.routed.left == (cut,)


def test_the_board_checked_again_has_the_last_routing_and_none_of_the_first(board, tmp_path, kicad):
    class Twice:
        """A track and a via on the back with the pour known, a track on the front without."""

        def route(self, job: Job, outdir: Path, name: str, stage: str = "") -> Run:
            return Run((B_ROUTE,), (B_VIA,)) if stage == "poured" else Run((A_ROUTE,), ())

    kicad(LEFT)
    built = _poured(board).build(tmp_path / "out", router=Twice())
    assert built.routed is not None and built.routed.wires == (A_ROUTE,)
    # What KiCad was shown last is the board that was written, with its pour: the first
    # run's track and via are not on it.
    checked = parse((tmp_path / "out" / "breakout-poured-check.kicad_pcb").read_text())
    written = parse(built.board.read_text())

    def nets(made: Node, kind: str) -> list[str]:
        return [str(net[1]) for item in find_all(made, kind)
                if (net := find(item, "net")) is not None]  # fmt: skip

    assert nets(checked, "segment") == nets(written, "segment") == ["A", "A"]
    assert find_all(checked, "via") == [] and nets(checked, "zone") == ["GND"]


def test_where_kicad_is_not_installed_the_model_says_and_the_result_says_it_was(board, tmp_path):
    built = _poured(board).build(tmp_path / "out", router=Scripted())
    assert built.routed is not None
    assert built.routed.judge == "model" and len(built.routed.cut) == 2
    assert not (tmp_path / "out" / "breakout-poured-check.kicad_pcb").exists()


def test_a_board_with_no_pour_asks_nobody(board, tmp_path, kicad):
    kicad(LEFT)
    board.rules(track=0.25 * mm, clearance=0.2 * mm)
    board.route()
    built = board.build(tmp_path / "out", router=Scripted())
    assert built.routed is not None and built.routed.judge == "" and built.routed.cut == ()


def test_kicad_that_is_there_and_gives_no_report_stops_the_build(board, tmp_path, monkeypatch):
    script = tmp_path / "broken.py"
    script.write_text("import sys; print('no display'); sys.exit(3)")
    monkeypatch.setenv("KICAD_CLI", f"{sys.executable} {script}")
    with pytest.raises(KicadError, match="exited 3 with no report:\nno display"):
        _poured(board).build(tmp_path / "out", router=Scripted())


def test_kicads_report_is_read_for_the_net_and_the_pads_it_names():
    from pkidl.kicad import cuts

    # As KiCad 10.0.6 wrote them, of three boards.
    report = {"unconnected_items": [
        {"items": [{"description": "Zone [GND] on F.Cu, priority 0"},
                   {"description": "Pad 1 [GND] of A on F.Cu"}]},
        {"items": [{"description": "Track [GND] on F.Cu, length 0.5767 mm"},
                   {"description": "Track [GND] on F.Cu, length 0.7204 mm"}]},
        {"items": [{"description": "Pad 1 [Net-(Q5-Pad1)] of Q5 on F.Cu"},
                   {"description": "Track [Net-(Q5-Pad1)] on F.Cu, length 0.7767 mm"}]},
    ]}  # fmt: skip
    assert [(c.net, c.pads) for c in cuts(report)] == [
        ("GND", ("A.1",)), ("GND", ()), ("Net-(Q5-Pad1)", ("Q5.1",)),
    ]  # fmt: skip
    assert cuts({"unconnected_items": []}) == [] and cuts({}) == []
    # A pad on one spoke is connected, by KiCad, and an error by its DRC: a pour that
    # leaves one so does not carry its net as the board's rules ask.
    one_spoke = {"violations": [
        {"type": "silk_overlap", "description": "x", "items": []},
        {"type": "starved_thermal",
         "description": "Thermal relief connection to zone incomplete (layer F.Cu; zone "
                        "min spoke count 2; actual 1)",
         "items": [{"description": "Zone [G1] on F.Cu, priority 0"},
                   {"description": "Pad 1 [G1] of A1 on F.Cu"}]},
    ]}  # fmt: skip
    (cut,) = cuts(one_spoke)
    assert (cut.net, cut.pads) == ("G1", ("A1.1",)) and "actual 1" in str(cut)


def test_kicad_that_does_not_finish_leaves_the_model_to_say(board, tmp_path, monkeypatch):
    from pkidl.kicad import unconnected

    slow = tmp_path / "slow.py"
    slow.write_text("import time; time.sleep(30)")
    monkeypatch.setenv("KICAD_CLI", f"{sys.executable} {slow}")
    asked = tmp_path / "b.kicad_pcb"
    asked.write_text("(kicad_pcb)")
    assert unconnected(asked, timeout=0.5) is None
    # And a build then has the model's word, and says it is the model's.
    monkeypatch.setattr("pkidl.build.unconnected", lambda path: None)
    built = _poured(board).build(tmp_path / "out", router=Scripted())
    assert built.routed is not None
    assert built.routed.judge == "model" and len(built.routed.cut) == 2


def test_the_judge_named_is_the_one_asked_last_and_an_old_report_is_not_read(
    board, tmp_path, monkeypatch
):
    from pkidl.kicad import unconnected

    # A report left from an earlier run is not this run's: KiCad that writes none fails.
    broken = tmp_path / "broken.py"
    broken.write_text("import sys; sys.exit(3)")
    monkeypatch.setenv("KICAD_CLI", f"{sys.executable} {broken}")
    asked = tmp_path / "b.kicad_pcb"
    asked.write_text("(kicad_pcb)")
    (tmp_path / "b-drc.json").write_text('{"unconnected_items": []}')
    with pytest.raises(KicadError):
        unconnected(asked)
    # KiCad answers the first time, does not finish the second, and answers the third,
    # of the board routed again: each check asks afresh, and the judge named is the one
    # that answered last.
    answers = iter([[Cut("GND", ("P1.3",), seen="x")], None, []])
    monkeypatch.setattr("pkidl.build.unconnected", lambda path: next(answers))
    board.pour("A", layer="F.Cu")
    built = _poured(board).build(tmp_path / "out", router=Scripted())
    assert built.routed is not None and built.routed.judge == "KiCad"
    assert built.routed.left == () and len(built.routed.cut) > 1
    # And the model's where it was the last to answer.
    answers = iter([[Cut("GND", ("P1.3",), seen="x")], None, None])
    built = _poured(board).build(tmp_path / "again", router=Scripted())
    assert built.routed is not None and built.routed.judge == "model"


# Three parts with a ground pad each: two through the board, as the next-bus clock's
# C5 and ESP1 are, and one on the front.
CLOCK = """(kicad_pcb
  (gr_rect (start 100 50) (end 140 80) (layer "Edge.Cuts"))
  (footprint "RF:M" (layer "F.Cu") (at 0 0)
    (property "Reference" "U1" (at 0 0) (layer "F.SilkS"))
    (property "Value" "M" (at 0 0) (layer "F.Fab"))
    (fp_rect (start -1 -4) (end 9 3) (stroke (width 0.05) (type solid)) (fill no)
      (layer "F.CrtYd"))
    (pad "1" smd rect (at 0 0) (size 2 1) (layers "F.Cu") (net "A"))
    (pad "2" smd rect (at 0 2) (size 2 1) (layers "F.Cu") (net "B"))
    (pad "3" smd rect (at 8 2) (size 2 1) (layers "F.Cu") (net "GND")))
  (footprint "Conn:H" (layer "F.Cu") (at 0 0)
    (property "Reference" "ESP1" (at 0 0) (layer "F.SilkS"))
    (property "Value" "H" (at 0 0) (layer "F.Fab"))
    (fp_rect (start -1.75 -1.75) (end 6.83 1.75) (stroke (width 0.05) (type solid)) (fill no)
      (layer "F.CrtYd"))
    (pad "1" thru_hole circle (at 0 0) (size 1.7 1.7) (drill 1) (layers "*.Cu") (net "A"))
    (pad "2" thru_hole circle (at 2.54 0) (size 1.7 1.7) (drill 1) (layers "*.Cu")
      (net "GND"))
    (pad "3" thru_hole circle (at 5.08 0) (size 1.7 1.7) (drill 1) (layers "*.Cu") (net "B")))
  (footprint "Device:C" (layer "F.Cu") (at 0 0)
    (property "Reference" "C5" (at 0 0) (layer "F.SilkS"))
    (property "Value" "100n" (at 0 0) (layer "F.Fab"))
    (fp_rect (start -2.2 -1.2) (end 2.2 1.2) (stroke (width 0.05) (type solid)) (fill no)
      (layer "F.CrtYd"))
    (pad "1" thru_hole rect (at -1.25 0) (size 1.2 1.2) (drill 0.7) (layers "*.Cu") SAID
      (net "GND"))
    (pad "2" thru_hole circle (at 1.25 0) (size 1.2 1.2) (drill 0.7) (layers "*.Cu")
      (net "B"))))"""
GROUND = (("ESP1", "2"), ("C5", "1"), ("U1", "3"))


def _clock(tmp_path: Path, said: str = "") -> Board:
    """The board of CLOCK with a ground pour on the back, to be routed. *said* is
    written on C5's ground pad in its footprint."""
    d = tmp_path / f"clock{len(said)}"
    source = parse(CLOCK.replace("SAID", said))
    d.mkdir()
    (d / "circuit.json").write_text(json.dumps(circuit(source)))
    (d / "mechanical.json").write_text(json.dumps(mechanical(source)))
    for name, lib in footprints(source)[0].items():
        path = d / "footprints" / footprint_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dumps(lib) + "\n")
    board = Board.from_inputs(d)
    u1, esp1, c5 = board.parts("U1", "ESP1", "C5")
    board.place(esp1, against=Edge.LEFT, inset=3 * mm)
    board.place(u1, against=Edge.TOP, facing=Edge.TOP)
    board.place(c5, near=u1.pin(2), within=6 * mm)
    return _poured(board)


def _ground_by_track(board: Board, tmp_path: Path, ground=GROUND) -> Scripted:
    """A router that joins the three ground pads by a track on the front, whatever it
    is asked: where the pads are is read from the board built once with nothing laid."""
    plain = board.build(tmp_path / "placed", router=Scripted())
    placed = {_ref(fp): fp for fp in find_all(parse(plain.board.read_text()), "footprint")}
    at = [pad_xy(placed[ref], pad) for ref, pad in ground]
    return Scripted(Run((Wire("GND", "F.Cu", 0.25, at),), (), 0))


def _off_the_pour(written: Path) -> list[str]:
    """The pads of the board at *written* that say they join no pour, as ``C5.1``."""
    return [f"{_ref(fp)}.{pad[1]}" for fp in find_all(parse(written.read_text()), "footprint")
            for pad in find_all(fp, "pad")
            if (own := find(pad, "zone_connect")) is not None and str(own[1]) == "0"]  # fmt: skip


def _starved_thermal(spokes: int, pad: str, ref: str) -> dict:
    return {"type": "starved_thermal", "severity": "error",
            "description": f"Thermal relief connection to zone incomplete (layer B.Cu; {spokes} "
                           "spokes connected to isolated island)",
            "items": [{"description": "Zone [GND] on B.Cu"},
                      {"description": f"PTH pad {pad} [GND] of {ref}"}]}  # fmt: skip


# As KiCad 10.0.6 reported the next-bus clock placed for hand assembly.
STARVED_C5, STARVED_ESP1 = _starved_thermal(4, "1", "C5"), _starved_thermal(1, "2", "ESP1")
KICAD_IN_TURN = """import json, sys
from pathlib import Path
args, here = sys.argv[1:], Path(__file__)
count = here.with_suffix(".count")
turn = int(count.read_text()) if count.exists() else 0
count.write_text(str(turn + 1))
here.with_suffix(f".{{turn}}.kicad_pcb").write_text(Path(args[-1]).read_text())
reports = {reports}
Path(args[args.index("-o") + 1]).write_text(json.dumps(reports[min(turn, len(reports) - 1)]))
"""


@pytest.fixture
def kicad_in_turn(tmp_path, monkeypatch):
    """Stand a script in for KiCad's command line that writes the next of *reports*
    each time it is run, the last from then on, and keeps each board it was shown.
    Gives back the boards shown so far, in order."""

    def stand_in(*reports: dict):
        script = tmp_path / "kicad.py"
        script.write_text(KICAD_IN_TURN.format(reports=list(reports)))
        monkeypatch.setenv("KICAD_CLI", f"{sys.executable} {script}")
        return lambda: sorted(tmp_path.glob("kicad.*.kicad_pcb"))

    return stand_in


def test_kicads_starved_reliefs_are_read_with_the_layer_and_marked():
    from pkidl.kicad import cuts

    found = cuts({"violations": [STARVED_C5, STARVED_ESP1],
                  "unconnected_items": [LEFT["unconnected_items"][0]]})  # fmt: skip
    assert [(c.net, c.pads, c.layer, c.starved) for c in found] == [
        ("GND", ("P1.3",), None, False),
        ("GND", ("C5.1",), "B.Cu", True),
        ("GND", ("ESP1.2",), "B.Cu", True),
    ]
    assert str(found[1]) == (
        "KiCad, of GND: Thermal relief connection to zone incomplete (layer B.Cu; 4 spokes "
        "connected to isolated island): Zone [GND] on B.Cu and PTH pad 1 [GND] of C5"
    )
    # One that names its layer only with the zone.
    older = {"type": "starved_thermal", "description": "Thermal relief incomplete",
             "items": [{"description": "Zone [G1] on F.Cu, priority 0"},
                       {"description": "Pad 1 [G1] of A1 on F.Cu"}]}  # fmt: skip
    (cut,) = cuts({"violations": [older]})
    assert (cut.pads, cut.layer, cut.starved) == (("A1.1",), "F.Cu", True)


def test_the_pads_kicad_says_are_starved_and_a_track_joins_are_taken_off_the_pour(
    tmp_path, kicad_in_turn
):
    board = _clock(tmp_path)
    router = _ground_by_track(board, tmp_path)
    both = {"violations": [STARVED_C5, STARVED_ESP1]}
    shown = kicad_in_turn(both, both, {"violations": []})
    built = board.build(tmp_path / "out", router=router)
    assert built.routed is not None and built.routed.judge == "KiCad"
    # KiCad was asked of the run with the pour known, which it did not pass, then of
    # the board routed again, and then of that board with the two pads off the pour.
    assert [stage for stage, *_ in router.asked[-2:]] == ["poured", ""]
    assert [sorted(_off_the_pour(pcb)) for pcb in shown()] == [[], [], ["C5.1", "ESP1.2"]]
    assert built.routed.unjoined == (
        "C5.1 is taken off the pour of GND on B.Cu, which starved its relief: a track "
        "joins it to the rest of GND",
        "ESP1.2 is taken off the pour of GND on B.Cu, which starved its relief: a track "
        "joins it to the rest of GND",
    )
    assert built.routed.left == () and len(built.routed.cut) == 2
    # The board written is the one KiCad passed: the two pads off the pour, and every
    # track and the pour as routed.
    assert sorted(_off_the_pour(built.board)) == ["C5.1", "ESP1.2"]
    assert built.board.read_text() == shown()[-1].read_text()
    plain = shown()[1].read_text()
    assert built.board.read_text().replace("\t\t\t(zone_connect 0)\n", "") == plain
    assert plain.count("(segment") == 2 and plain.count("(zone") == 1


def test_kicad_is_asked_again_of_each_board_with_the_pads_it_named_off(tmp_path, kicad_in_turn):
    board = _clock(tmp_path)
    router = _ground_by_track(board, tmp_path)
    # With C5's pad off the pour it names ESP1's, and with both off, none.
    first, then = {"violations": [STARVED_C5]}, {"violations": [STARVED_ESP1]}
    shown = kicad_in_turn(first, first, then, {"violations": []})
    built = board.build(tmp_path / "out", router=router)
    assert built.routed is not None
    assert [sorted(_off_the_pour(pcb)) for pcb in shown()] == [
        [], [], ["C5.1"], ["C5.1", "ESP1.2"],
    ]  # fmt: skip
    assert [line.split()[0] for line in built.routed.unjoined] == ["C5.1", "ESP1.2"]
    assert sorted(_off_the_pour(built.board)) == ["C5.1", "ESP1.2"] and built.routed.left == ()


def test_a_pad_kicad_says_is_starved_that_no_track_joins_is_left_as_it_is(tmp_path, kicad_in_turn):
    board = _clock(tmp_path)
    shown = kicad_in_turn({"violations": [STARVED_C5, STARVED_ESP1]})
    built = board.build(tmp_path / "out", router=Scripted())  # a router that lays nothing
    assert built.routed is not None
    # Asked of the run with the pour and of the board routed again, and no more: with
    # no track to carry them the pads stay on the pour, and are said.
    assert len(shown()) == 2
    assert built.routed.unjoined == () and _off_the_pour(built.board) == []
    assert [c.pads for c in built.routed.left] == [("C5.1",), ("ESP1.2",)]
    assert "zone_connect" not in built.board.read_text()


@pytest.mark.parametrize("said", ["(zone_connect 0)", "(zone_connect 2)"])
def test_a_pad_that_says_how_it_joins_a_pour_is_not_taken_off_whatever_kicad_says(
    tmp_path, kicad_in_turn, said
):
    board = _clock(tmp_path, said)
    router = _ground_by_track(board, tmp_path)
    both = {"violations": [STARVED_C5, STARVED_ESP1]}
    shown = kicad_in_turn(both, both, {"violations": [STARVED_C5]})
    built = board.build(tmp_path / "out", router=router)
    assert built.routed is not None
    assert [line.split()[0] for line in built.routed.unjoined] == ["ESP1.2"]
    assert [c.pads for c in built.routed.left] == [("C5.1",)]
    # C5's pad is as its footprint has it.
    (c5,) = (fp for fp in find_all(parse(built.board.read_text()), "footprint") if _ref(fp) == "C5")
    assert dumps(find(find_all(c5, "pad")[0], "zone_connect")) == said  # type: ignore[arg-type]
    assert len(shown()) == 3


def test_where_kicad_is_not_installed_the_model_finds_the_starved_pad_and_it_is_taken_off(
    board, tmp_path
):
    board = _poured(board)
    router = _ground_by_track(board, tmp_path, (("P1", "3"), ("R1", "2"), ("U1", "3")))
    built = board.build(tmp_path / "out", router=router)
    assert built.routed is not None and built.routed.judge == "model"
    # The track joins every pad of ground, so the model passes the run with the pour.
    # The header's pin is the one pad of ground through the board: the pour on the back
    # has nothing else of ground on it, and is an island that pin alone holds.
    assert [stage for stage, *_ in router.asked[-1:]] == ["poured"]
    assert built.routed.cut == () and built.routed.left == ()
    assert built.routed.unjoined == (
        "P1.3 is taken off the pour of GND on B.Cu, which starved its relief: a track "
        "joins it to the rest of GND",
    )
    assert _off_the_pour(built.board) == ["P1.3"]
    # No track is changed for it, and the pour is still drawn.
    written = parse(built.board.read_text())
    assert len(find_all(written, "segment")) == 2 and len(find_all(written, "zone")) == 1
    # The board itself is as it was said: built again, it is the same file.
    again = board.build(tmp_path / "again", router=router)
    assert again.board.read_text() == built.board.read_text()


def test_where_the_model_finds_a_starved_pad_that_only_the_pour_joins_it_is_left_and_said(
    board, tmp_path
):
    built = _poured(board).build(tmp_path / "out", router=Scripted())
    assert built.routed is not None and built.routed.judge == "model"
    assert built.routed.unjoined == () and "zone_connect" not in built.board.read_text()
    assert [str(c) for c in built.routed.left if c.starved] == [
        "P1.3 is starved of the pour of GND on B.Cu: fewer than 2 spokes of its relief "
        "reach a piece of the pour that another pad or a via of GND is on"
    ]
    # With a via down to the pour beside each pad on the front it is no island.
    placed = {_ref(fp): fp for fp in find_all(parse(built.board.read_text()), "footprint")}
    down = tuple(
        Via("GND", VIA, pad_xy(placed[ref], pad)) for ref, pad in (("R1", "2"), ("U1", "3"))
    )
    built = _poured(board).build(tmp_path / "joined", router=Scripted(Run((), down, 0)))
    assert built.routed is not None
    assert built.routed.left == () and built.routed.unjoined == ()
    assert "zone_connect" not in built.board.read_text()


def test_a_board_whose_pour_starves_no_pad_is_written_as_it_was_and_kicad_asked_once(
    board, tmp_path, kicad_in_turn
):
    shown = kicad_in_turn({"unconnected_items": []})
    built = _poured(board).build(tmp_path / "out", router=Scripted())
    assert built.routed is not None
    assert len(shown()) == 1 and built.routed.unjoined == () and built.routed.left == ()
    assert built.board.read_text() == shown()[0].read_text()
    assert "zone_connect" not in built.board.read_text()


class Fencing:
    """A router that, with the pours known, brings the module's ground pad down to the
    pour by a via and fences C5's ground pad in on the back with tracks of another
    net on three sides, 0.9 mm from its middle, so that one spoke of its relief has
    room and the pour still lies over the pad; and that, asked to join, lays *join*
    besides. It keeps what it was asked."""

    def __init__(self, board: Board, tmp_path: Path, join: bool = True) -> None:
        plain = board.build(tmp_path / "placed", router=Scripted())
        placed = {_ref(fp): fp for fp in find_all(parse(plain.board.read_text()), "footprint")}
        (ex, ey), (cx, cy), at_u1 = (pad_xy(placed[ref], pad) for ref, pad in GROUND)
        box = [(cx - 0.9, cy - 0.9), (cx + 0.9, cy - 0.9), (cx + 0.9, cy + 0.9),
               (cx - 0.9, cy + 0.9)]  # fmt: skip
        self.fence = tuple(Wire("B", "B.Cu", 0.25, [a, b])
                           for a, b in zip(box, box[1:], strict=False))  # fmt: skip
        self.down = Via("GND", VIA, at_u1)
        # From C5's pad along the front to the header's ground pin, which the pour joins.
        self.join = (Wire("GND", "F.Cu", 0.25, [(cx, cy), (ex, ey)]),) if join else ()
        self.asked: list[tuple[str, Job]] = []

    def route(self, job: Job, outdir: Path, name: str, stage: str = "") -> Run:
        self.asked.append((stage, job))
        if stage == "poured":
            return Run(self.fence, (self.down,), 0)
        if stage == "poured-join":
            return Run(self.join, (self.down,), 0)
        return Run((*self.fence, *self.join), (self.down,), 0)


def test_a_pad_the_pour_is_cut_off_from_is_joined_by_a_track_and_the_pour_kept(tmp_path):
    from shapely.geometry import Point as ShapelyPoint
    from shapely.geometry import Polygon as ShapelyPolygon

    board = _clock(tmp_path)
    router = Fencing(board, tmp_path)
    built = board.build(tmp_path / "out", router=router)
    assert built.routed is not None and built.routed.judge == "model"
    # The run with the pour known is kept, and one more joins the pad: no run without.
    assert [stage for stage, _ in router.asked[-2:]] == ["poured", "poured-join"]
    assert [str(c) for c in built.routed.cut] == [
        "C5.1 is cut off from the rest of GND: no pour reaches there"
    ]
    # That run routes ground alone, round the first run's tracks, with the pour as it
    # fills round them and less the pad: a plane a track 0.25 mm wide can end in.
    _, first = router.asked[-2]
    _, join = router.asked[-1]
    assert join.only == {"GND"} and list(join.wires) == list(router.fence)
    assert list(join.vias) == [router.down]
    ((net, layer, known),) = first.planes
    ((_, _, stands),) = join.planes
    assert (net, layer) == ("GND", "B.Cu")
    at_c5 = ShapelyPoint(router.fence[0].points[0][0] + 0.9, router.fence[0].points[0][1] + 0.9)
    assert ShapelyPolygon(known).buffer(0).contains(at_c5)
    assert not ShapelyPolygon(stands).buffer(0).intersects(at_c5.buffer(0.9))
    assert (
        ShapelyPolygon(known).buffer(0.001).covers(ShapelyPolygon(stands).buffer(0).buffer(0.125))
    )
    # The check passed what it laid, and the result says what was done.
    assert built.routed.left == ()
    assert built.routed.joined == (
        "GND keeps its pour: 12.379 mm of track on F.Cu joins what was cut off to the rest of GND",
    )
    assert built.routed.taken_off == ("C5.1",) and built.routed.unjoined == (
        "C5.1 is taken off the pour of GND, which joins it to nothing: a track joins it to "
        "the rest of GND",
    )
    # The board written has that track, the pad off the pour, and the pour.
    written = parse(built.board.read_text())
    assert _off_the_pour(built.board) == ["C5.1"]
    assert len(find_all(written, "segment")) == 4 and len(find_all(written, "zone")) == 1


def test_a_pad_whose_join_is_not_laid_stays_on_its_pour_and_the_net_is_routed_again(tmp_path):
    board = _clock(tmp_path)
    router = Fencing(board, tmp_path, join=False)
    built = board.build(tmp_path / "out", router=router)
    assert built.routed is not None
    assert [stage for stage, _ in router.asked[-3:]] == ["poured", "poured-join", ""]
    assert built.routed.joined == () and built.routed.taken_off == ()
    assert built.routed.unjoined == () and _off_the_pour(built.board) == []
    # What the check finds of the board routed again is said of the board as built.
    assert [c.pads for c in built.routed.cut] == [("C5.1",)]
    assert [c.pads for c in built.routed.left if not c.starved] == [("C5.1",)]


def test_kicad_is_asked_of_a_join_with_the_pad_off_its_pour_and_its_word_stands(
    tmp_path, kicad_in_turn
):
    board = _clock(tmp_path)
    router = Fencing(board, tmp_path)
    apart = {"type": "unconnected_items", "severity": "error",
             "description": "Missing connection between items",
             "items": [{"description": "PTH pad 1 [GND] of C5"},
                       {"description": "Zone [GND] on B.Cu, priority 0"}]}  # fmt: skip
    shown = kicad_in_turn({"unconnected_items": [apart], "violations": [STARVED_C5]},
                          {"unconnected_items": [], "violations": []})  # fmt: skip
    built = board.build(tmp_path / "out", router=router)
    assert built.routed is not None and built.routed.judge == "KiCad"
    assert [stage for stage, _ in router.asked[-2:]] == ["poured", "poured-join"]
    # KiCad said the pad is cut off and starved; it was shown the join with the pad off
    # its pour, passed it, and is asked no more: the pad is taken off once.
    assert [sorted(_off_the_pour(pcb)) for pcb in shown()] == [[], ["C5.1"]]
    assert len(built.routed.cut) == 2 and built.routed.left == ()
    assert built.routed.taken_off == ("C5.1",) and len(built.routed.unjoined) == 1
    assert len(built.routed.joined) == 1
    assert built.board.read_text() == shown()[-1].read_text()


def test_the_corpus_build_says_each_pad_taken_off_its_pour(tmp_path, monkeypatch, capsys):
    import importlib.util
    from types import SimpleNamespace

    from pkidl.routing import Routed

    spec = importlib.util.spec_from_file_location(
        "corpus_script", Path(__file__).parent.parent / "scripts" / "corpus.py"
    )
    assert spec is not None and spec.loader is not None
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    line = ("C5.1 is taken off the pour of GND on B.Cu, which starved its relief: a track "
            "joins it to the rest of GND")  # fmt: skip
    left = Cut("GND", ("ESP1.2",), "B.Cu", starved=True)
    in_it = "a via of B at (123, 51) is in U1's antenna area, which is kept clear of copper"
    kept = "GND keeps its pour: 1 via joins what was cut off to the rest of GND"
    routed = Routed((), (), (("", Run((), (), 0)),), left=(left,), unjoined=(line,),
                    judge="model", kept_out=(in_it,), joined=(kept,))  # fmt: skip
    made = SimpleNamespace(routed=routed, solution=SimpleNamespace(poses={}, chosen=()))
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "board.py").write_text(
        "from types import SimpleNamespace\nboard = SimpleNamespace(build=lambda d, name: MADE)\n"
    )
    monkeypatch.setattr(script, "BOARDS", {"b": ("t0", "a board")})
    monkeypatch.setattr(script, "board_dir", lambda board_id: tmp_path / "src")
    monkeypatch.setattr("builtins.MADE", made, raising=False)
    assert script.build(tmp_path / "out") == 0
    said = json.loads((tmp_path / "out" / "b" / "built.json").read_text())
    assert said["unjoined"] == [line] and said["left"] == [str(left)]
    assert said["kept_out"] == [in_it] and said["joined"] == [kept]
    printed = capsys.readouterr().out.splitlines()
    assert f"    {kept}" in printed
    assert f"    {line}" in printed and f"    left on the board as built: {left}" in printed
    assert f"    {in_it}" in printed


def test_the_model_is_asked_again_of_the_board_with_each_pad_it_named_off(
    board, tmp_path, monkeypatch
):
    from pkidl import fill

    board = _poured(board)
    router = _ground_by_track(board, tmp_path, (("P1", "3"), ("R1", "2"), ("U1", "3")))
    seen: list[list[str]] = []

    def starved(items, *fill_as):
        """The model's own word, and with the header's pin off the pour, the
        resistor's pad as well: what it was shown each time is kept."""
        off = [f"{_ref(fp)}.{pad[1]}" for fp in items if fp[0] == "footprint"
               for pad in find_all(fp, "pad") if find(pad, "zone_connect") is not None]  # fmt: skip
        seen.append(off)
        more = [Cut("GND", ("R1.2",), "B.Cu", starved=True)] if off == ["P1.3"] else []
        return [*fill.starved(items, *fill_as), *more]

    monkeypatch.setattr("pkidl.build.starved", starved)
    built = board.build(tmp_path / "out", router=router)
    assert built.routed is not None and built.routed.judge == "model"
    assert seen == [[], ["P1.3"], ["P1.3", "R1.2"]]
    assert [line.split()[0] for line in built.routed.unjoined] == ["P1.3", "R1.2"]
    assert sorted(_off_the_pour(built.board)) == ["P1.3", "R1.2"] and built.routed.left == ()


# A heatsink in the mounting hole's place: 12 by 8 mm about (120, 66), from 114 to 126 mm
# across and 62 to 70 down, on two pins that are on no net.
SINK = """(footprint "Sink:S" (layer "F.Cu") (at 120 66)
    (property "Reference" "REF**" (at 0 0) (layer "F.SilkS"))
    (fp_rect (start -6 -4) (end 6 4) (stroke (width 0.05) (type solid)) (fill no)
      (layer "F.CrtYd"))
    (pad "" thru_hole circle (at -5 0) (size 2 2) (drill 1.2) (layers "*.Cu"))
    (pad "" thru_hole circle (at 5 0) (size 2 2) (drill 1.2) (layers "*.Cu"))))"""
SINK_BOX = [(114.0, 62.0), (126.0, 62.0), (126.0, 70.0), (114.0, 70.0)]
SINK_NAME = "S at (120, 66)"


@pytest.fixture
def sunk(tmp_path: Path) -> Board:
    """The board with the heatsink on it and the header standing on the heatsink, as
    a regulator does: its pins at 117.46, 120 and 122.54 mm across, 68 mm down, inside
    the heatsink's outline. The module is against the top, and the resistor by it."""
    d = tmp_path / "sunk"
    head, hole, _ = SOURCE.partition('(footprint "Mech:M3"')
    assert hole
    source = parse(head + SINK)
    d.mkdir()
    (d / "circuit.json").write_text(json.dumps(circuit(source)))
    (d / "mechanical.json").write_text(json.dumps(mechanical(source)))
    for name, lib in footprints(source)[0].items():
        path = d / "footprints" / footprint_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dumps(lib) + "\n")
    board = Board.from_inputs(d)
    u1, p1, r1 = board.parts("U1", "P1", "R1")
    board.annotate(u1, antenna=((6 * mm, -4 * mm), (9 * mm, -1 * mm)))
    board.place(p1, on=board.fixed("S"), at=(-2.54 * mm, 2 * mm), facing=Edge.TOP)
    board.place(u1, against=Edge.TOP, facing=Edge.TOP)
    board.place(r1, near=u1.pin(2), within=4 * mm)
    return board


def _routed(board: Board) -> Board:
    board.rules(track=0.25 * mm, clearance=0.2 * mm)
    board.route()
    return board


def test_copper_kept_from_under_something_fixed_is_a_rule_area_on_its_face(sunk, tmp_path):
    sink = sunk.fixed("S")
    assert sink.label == SINK_NAME
    # With nothing said there is no rule area: nothing is kept from under it.
    assert _rule_areas(parse(sunk.build(tmp_path / "plain").board.read_text())) == []
    sunk.keepout(sink, copper=True)
    built = sunk.build(tmp_path / "front")
    written = parse(built.board.read_text())
    assert _rule_areas(written) == [(SINK_NAME, "F.Cu", SINK_BOX)]
    (zone,) = [z for z in find_all(written, "zone") if find(z, "keepout") is not None]
    rule = find(zone, "keepout")
    assert rule is not None
    # No track, via or pour; pads are let be, the thing's own and those of a part on it.
    assert {str(r[0]): str(r[1]) for r in rule[1:]} == {
        "tracks": "not_allowed", "vias": "not_allowed", "pads": "allowed",
        "copperpour": "not_allowed", "footprints": "allowed",
    }  # fmt: skip
    # The header is on it, its pins inside the area, as it was.
    placed = {_ref(fp): fp for fp in find_all(written, "footprint")}
    assert pad_xy(placed["P1"], "2") == pytest.approx((120, 68))


def test_copper_kept_from_under_something_fixed_on_both_sides_is_a_rule_area_on_each(
    board, tmp_path
):
    # The mounting hole, 3.2 mm across at (136, 76).
    hole = board.fixed("M3")
    box = [(134.4, 74.4), (137.6, 74.4), (137.6, 77.6), (134.4, 77.6)]
    board.keepout(hole, copper=True, both_sides=True)
    board.keepout(hole, copper=True)  # said of the front again: it is drawn once
    board.keepout(board["U1"].area("antenna"), copper=True)
    written = parse(board.build(tmp_path).board.read_text())
    assert _rule_areas(written) == [
        ("U1 antenna", "F.Cu", _rule_areas(written)[0][2]),
        ("M3 at (136, 76)", "F.Cu", box),
        ("M3 at (136, 76)", "B.Cu", box),
    ]


def test_the_router_is_told_of_the_copper_kept_from_under_something_fixed(sunk, tmp_path):
    from pkidl.dsn import write_dsn

    _routed(sunk).keepout(sunk.fixed("S"), copper=True)
    router = Scripted()
    sunk.build(tmp_path / "out", router=router)
    ((_, job, _, _),) = router.asked
    assert [(layer, list(box)) for layer, box in job.keepouts] == [("F.Cu", SINK_BOX)]
    # As a router reads it: a keepout on the front layer and none on the back, y up.
    areas = [(layer, list(box)) for layer, box in job.keepouts]
    dsn = write_dsn(tmp_path / "told.dsn", list(job.footprints), list(job.outline),
                    list(job.netclasses), {}, areas=areas)  # fmt: skip
    kept = [line.strip() for line in dsn.read_text().splitlines() if "polygon" in line]
    assert kept == ['(keepout "" (polygon F.Cu 0  114000 -62000  126000 -62000  126000 -70000  '
                    "114000 -70000  114000 -62000))"]  # fmt: skip
    # With nothing said the router is told of none.
    plain = Scripted()
    sink_free = sunk.statements()[-1]
    del sunk._statements[sink_free]
    sunk.build(tmp_path / "plain", router=plain)
    assert list(plain.asked[0][1].keepouts) == []


def test_a_pour_does_not_fill_under_something_fixed_on_the_face_kept_clear(sunk, tmp_path):
    from shapely.geometry import Point as At

    from pkidl.fill import fills

    def filled(said: bool) -> dict[str, bool]:
        """Whether each layer's pour covers a point under the heatsink, clear of every
        pad there: 2 mm above its middle."""
        board = Board.from_inputs(tmp_path / "sunk")
        for statement in sunk.statements():
            board.add(statement)
        _routed(board)
        for layer in ("F.Cu", "B.Cu"):
            board.pour("GND", layer=layer)
        if said:
            board.keepout(board.fixed("S"), copper=True)
        router = Scripted()
        built = board.build(tmp_path / f"filled-{said}", router=router)
        items = [n for n in parse(built.board.read_text())[1:] if isinstance(n, list)]
        outline = [(100.0, 50.0), (140.0, 50.0), (140.0, 80.0), (100.0, 80.0)]
        over = {layer: False for layer in ("F.Cu", "B.Cu")}
        for _, layer, piece in fills(items, outline, 0.5):
            over[layer] = over[layer] or piece.contains(At(120, 64))
        # And the pour the router is told of is the same.
        told = {layer: False for layer in ("F.Cu", "B.Cu")}
        for _, layer, plane in router.asked[0][1].planes:
            xs, ys = [x for x, _ in plane], [y for _, y in plane]
            told[layer] = told[layer] or (min(xs) < 114 and max(xs) > 126
                                          and min(ys) < 62 and max(ys) > 70)  # fmt: skip
        assert all(told.values())
        return over

    assert filled(False) == {"F.Cu": True, "B.Cu": True}
    assert filled(True) == {"F.Cu": False, "B.Cu": True}


F, B = "F.Cu", "B.Cu"


def test_a_track_or_a_via_in_an_area_kept_clear_of_copper_is_in_the_builds_result(sunk, tmp_path):
    sink = sunk.fixed("S")
    _routed(sunk).keepout(sink, copper=True)
    # With nothing proposed nothing is in it: not the heatsink's own pins, and not
    # the pins of the header that stands on it.
    built = sunk.build(tmp_path / "none", router=Scripted())
    assert built.routed is not None and built.routed.kept_out == ()
    # A track across it on the front, 12 mm of it inside, in two segments; one on the
    # back, where nothing is kept; one that ends 0.5 mm short of it on the front; and
    # a via in it, and one outside.
    wires = (
        Wire("A", F, 0.25, [(110.0, 64.0), (120.0, 64.0), (130.0, 64.0)]),
        Wire("B", B, 0.25, [(110.0, 65.0), (130.0, 65.0)]),
        Wire("B", F, 0.25, [(110.0, 63.0), (113.375, 63.0)]),
        Wire("GND", F, 0.25, [(120.0, 75.0), (120.0, 69.0)]),
    )
    vias = (Via("B", VIA, (124.0, 63.0)), Via("B", VIA, (110.0, 65.0)))
    built = sunk.build(tmp_path / "some", router=Scripted(Run(wires, vias, 0)))
    assert built.routed is not None
    assert built.routed.kept_out == (
        f"A has 2 segments of track in {SINK_NAME} on F.Cu, which is kept clear of copper: "
        "12 mm of it",
        f"GND has 1 segment of track in {SINK_NAME} on F.Cu, which is kept clear of copper: "
        "1 mm of it",
        f"a via of B at (124, 63) is in {SINK_NAME}, which is kept clear of copper",
    )
    # The board is written with them all the same: the result says, and nothing is changed.
    written = parse(built.board.read_text())
    assert len(find_all(written, "segment")) == 5 and len(find_all(written, "via")) == 2
    # With nothing said of the heatsink none of it is anything.
    board = Board.from_inputs(tmp_path / "sunk")
    for statement in sunk.statements()[:-1]:
        board.add(statement)
    built = board.build(tmp_path / "plain", router=Scripted(Run(wires, vias, 0)))
    assert built.routed is not None and built.routed.kept_out == ()


def test_a_track_whose_width_alone_reaches_into_an_area_kept_clear_is_in_the_result(sunk, tmp_path):
    # The heatsink's box starts 114 mm across. A track 0.25 mm wide down the board
    # 0.05 mm left of it has 0.075 mm of its copper inside and none of its middle
    # line; one 0.2 mm left of it is 0.075 mm clear.
    _routed(sunk).keepout(sunk.fixed("S"), copper=True)

    def beside(x: float) -> tuple[str, ...]:
        wires = (Wire("B", F, 0.25, [(x, 63.0), (x, 69.0)]),)
        built = sunk.build(tmp_path / f"at-{x}", router=Scripted(Run(wires, (), 0)))
        assert built.routed is not None
        return built.routed.kept_out

    assert beside(113.95) == (
        f"B has 1 segment of track in {SINK_NAME} on F.Cu, which is kept clear of copper: "
        "0 mm of it",
    )
    assert beside(113.8) == ()


def test_copper_in_an_area_of_a_part_or_on_either_face_kept_clear_is_in_the_result(board, tmp_path):
    hole = board.fixed("M3")  # 3.2 mm across at (136, 76), from 134.4 to 137.6 mm
    _routed(board).keepout(hole, copper=True, both_sides=True)
    board.keepout(board["U1"].area("antenna"), copper=True)
    built = board.build(tmp_path / "none", router=Scripted())
    assert built.routed is not None and built.routed.kept_out == ()
    (antenna, _) = built.solution.keepouts
    x0, y0, x1, y1 = (v.mm for v in antenna.box)
    wires = (
        Wire("A", B, 0.25, [(130.0, 76.0), (139.0, 76.0)]),  # under the hole, on the back
        Wire("A", F, 0.25, [(x0 - 1, y0 + 1), (x1 + 1, y0 + 1)]),  # across the antenna
        Wire("B", B, 0.25, [(x0 - 1, y0 + 1), (x1 + 1, y0 + 1)]),  # and under it
    )
    vias = (Via("B", VIA, (x0 + 1, y0 + 1)),)
    built = board.build(tmp_path / "some", router=Scripted(Run(wires, vias, 0)))
    assert built.routed is not None
    assert built.routed.kept_out == (
        "A has 1 segment of track in M3 at (136, 76) on B.Cu, which is kept clear of copper: "
        "3.2 mm of it",
        "A has 1 segment of track in U1's antenna area on F.Cu, which is kept clear of "
        "copper: 3 mm of it",
        "a via of B at (123, 51) is in U1's antenna area, which is kept clear of copper",
    )
    # The antenna is from 122 to 125 mm across at the top of the board.
    assert (x0, y0, x1, y1) == (122, 50, 125, 53)


def test_a_part_on_something_kept_clear_on_both_sides_is_not_built(sunk, tmp_path):
    said = sunk.keepout(sunk.fixed("S"), copper=True, both_sides=True)
    line = _line_no() - 1
    with pytest.raises(BuildError) as e:
        sunk.build(tmp_path)
    (problem,) = e.value.problems
    assert problem.startswith(
        f"P1.1, P1.2 and P1.3 are inside the outline of {SINK_NAME}, which is kept clear of "
        "copper on both sides: no track can reach them ("
    )
    assert problem.endswith(f"{HERE}:{line})") and said in sunk.statements()
    assert not list(tmp_path.glob("*.kicad_pcb"))
