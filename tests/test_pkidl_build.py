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
from pkidl.footprint import footprint_path
from pkidl.importer import circuit, footprints, mechanical
from pkidl.intent import Route, Rules, route, rules
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
