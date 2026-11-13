"""pkidl's Freerouting router: how the command is run, what a job becomes, and what the
router itself does with one.

The first tests run a stand-in for the command through ``$FREEROUTING``. The last run
Freerouting, and are skipped where it is not installed.
"""

import os
import sys
from dataclasses import replace

import pytest

from pkidl.board import Board
from pkidl.dsn import Via, Wire, write_dsn
from pkidl.project import NetClass
from pkidl.route import Freerouting, RouterError, freerouting, router_command, unrouted
from pkidl.routing import Job, lay, staged
from pkidl.sexpr import find, find_all, parse

STUB = """import sys
args = sys.argv[1:]
open(sys.argv[0] + ".args", "w").write("\\n".join(args))
open(args[args.index("-do") + 1], "w").write({session!r})
print({said!r})
"""
SESSION = """(session b (routes (resolution um 10) (network_out
  (net A (wire (path F.Cu 5000 50000 -100000 60000 -100000 60000 -120000))
         (via "Via[0-1]_800:400_um" 60000 -120000))
  (net B (wire (path B.Cu 10000 250000 -100000 70000 -100000))))))"""
# As Freerouting 2.5.0 wrote them, routing the walled board below.
PASS = (
    "2026-11-11 17:36:04.236 INFO   [6D59A4\\36DED3] Auto-routing pass #1 on board "
    "'2063c411b60bcc4962ea24532ea5096d' was completed in 0.13 seconds with score 0.00 "
    "({n} unrouted and 0 violations)."
)
COMPLETED = (
    "2026-11-11 17:36:04.512 INFO   [6D59A4\\36DED3] Auto-routing stage completed: started "
    "with 2 unrouted nets, completed in 0.61 seconds, final score: 0.00 ({n} unrouted and "
    "{v} violations), using 0.00 total CPU seconds, 0.00 GB total allocated, and 0.0 MB "
    "peak heap usage."
)

FOOTPRINT = """(footprint "R" (at {x} 10) (property "Reference" "{ref}")
  (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net "{one}"))
  (pad "2" smd rect (at 2 0) (size 1 1) (layers "F.Cu") (net "{two}")))"""
# Two resistors 20 mm apart, each net joining one's first pad to the other's second.
FOOTPRINTS = [parse(FOOTPRINT.format(x=5, ref="R1", one="A", two="B")),
              parse(FOOTPRINT.format(x=25, ref="R2", one="B", two="A"))]  # fmt: skip
PADS = {"A": ((5.0, 10.0), (27.0, 10.0)), "B": ((7.0, 10.0), (25.0, 10.0))}
OUTLINE = [(0.0, 0.0), (40.0, 0.0), (40.0, 20.0), (0.0, 20.0)]
CLASSES = [NetClass("Default", 0.2, 0.5), NetClass("Wide", 0.2, 1.0)]
# A strip across the board on both layers, between the two resistors.
WALL = [(15.0, 0.0), (17.0, 0.0), (17.0, 20.0), (15.0, 20.0)]
WALLS = [("F.Cu", WALL), ("B.Cu", WALL)]


@pytest.fixture
def stub(tmp_path, monkeypatch):
    """Stand a script in for the router: it writes a session, says *said*, and leaves
    the arguments it was run with to be read back."""

    def stand_in(said: str = "", session: str = SESSION):
        script = tmp_path / "router.py"
        script.write_text(STUB.format(session=session, said=said))
        monkeypatch.setenv("FREEROUTING", f"{sys.executable} {script}")
        return lambda: (tmp_path / "router.py.args").read_text().split("\n")

    return stand_in


def test_both_router_stages_run_on_one_thread(tmp_path, stub):
    """-mt 1 limits only the autorouter; the optimizer's threads made the same DSN route
    three different ways in six runs, so its own limit must be passed too."""
    ran_with = stub(session="(session x)")
    (tmp_path / "b.dsn").write_text("(pcb b)")
    freerouting(tmp_path / "b.dsn", tmp_path / "b.ses", options=["--x=1"])
    args = ran_with()
    assert args[args.index("-mt") + 1] == "1"
    assert "--router.optimizer.max_threads=1" in args
    assert args[-1] == "--x=1"  # the caller's options come last


NECK = "--router.automatic_neckdown=false"
OBSTACLE = "--router.plane_as_obstacle=true"
FANOUT = "--router.fanout.enabled=false"
QUICK = [FANOUT, "--router.optimizer.enabled=false"]


@pytest.mark.parametrize(
    ("how", "options"),
    [
        ({}, []),
        # Fan-out necks whatever the neck-down setting is, so it goes with it.
        ({"neck_down": False}, [NECK, FANOUT]),
        ({"cross_planes": False}, [OBSTACLE]),
        ({"quick": True}, QUICK),
        ({"neck_down": False, "cross_planes": False, "quick": True}, [NECK, OBSTACLE, *QUICK]),
    ],
)
def test_how_a_job_is_to_be_routed_is_said_in_the_routers_settings(tmp_path, stub, how, options):
    ran_with = stub()
    Freerouting().route(Job(FOOTPRINTS, OUTLINE, CLASSES, {}, **how), tmp_path, "b")
    args = ran_with()
    assert args[args.index("--router.optimizer.max_threads=1") + 1 :] == options


def test_the_router_is_run_for_the_passes_it_was_made_with(tmp_path, stub):
    ran_with = stub()
    for router, passes in ((Freerouting(), "100"), (Freerouting(passes=7), "7")):
        router.route(Job(FOOTPRINTS, OUTLINE, CLASSES, {}), tmp_path, "b")
        args = ran_with()
        assert args[args.index("-mp") + 1] == passes


@pytest.mark.parametrize(("stage", "stem", "log"), [
    ("", "b", "freerouting.log"),
    ("power", "b-power", "freerouting-power.log"),
])  # fmt: skip
def test_a_run_leaves_its_files_named_for_the_board_and_the_stage(tmp_path, stub, stage, stem, log):
    ran_with = stub(said="routing")
    Freerouting().route(Job(FOOTPRINTS, OUTLINE, CLASSES, {}), tmp_path, "b", stage)
    args = ran_with()
    assert args[args.index("-de") + 1] == str(tmp_path / f"{stem}.dsn")
    assert args[args.index("-do") + 1] == str(tmp_path / f"{stem}.ses")
    assert sorted(p.name for p in tmp_path.iterdir() if p.suffix != ".py" and p.suffix != ".args") \
        == sorted([f"{stem}.dsn", f"{stem}.ses", log])  # fmt: skip
    assert (tmp_path / log).read_text() == "routing\n"


def test_the_job_is_written_as_the_dsn_writer_writes_it(tmp_path, stub):
    """Everything a job says of the board reaches the router's input."""
    stub()
    fixed = ([Wire("B", "F.Cu", 1.0, [(7.0, 10.0), (7.0, 14.0)])],
             [Via("B", "Via[0-1]_1000:500_um", (7.0, 14.0))])  # fmt: skip
    plane = [("A", "B.Cu", [(1.0, 1.0), (39.0, 1.0), (39.0, 19.0), (1.0, 19.0)])]
    gaps = {("Wide", "Default"): 0.6}
    whole = Job(FOOTPRINTS, OUTLINE, CLASSES, {"Wide": ["B"]}, edge_clearance=0.3,
                wires=fixed[0], vias=fixed[1], class_clearances=gaps, keepouts=WALLS,
                planes=plane)  # fmt: skip
    (tmp_path / "direct").mkdir()
    written = {}
    for only in (None, frozenset({"B"})):
        Freerouting().route(replace(whole, only=only), tmp_path, "b")
        direct = write_dsn(tmp_path / "direct" / "b.dsn", FOOTPRINTS, OUTLINE, CLASSES,
                           {"Wide": ["B"]}, edge_clearance=0.3,
                           only=None if only is None else set(only), fixed=fixed,
                           class_clearances=gaps, areas=WALLS, planes=plane)  # fmt: skip
        written[only] = (tmp_path / "b.dsn").read_text()
        assert written[only] == direct.read_text()
    # And each of them is in it: the test is not of two empty files.
    for said in ('(net "A"', '(net "B"', "(type protect)", "(class_class", '(keepout ""',
                 '(plane "A"', '(via "Via[0-1]_1000:500_um" 7000'):  # fmt: skip
        assert said in written[None], said
    assert '(net "B"' in written[frozenset({"B"})]
    assert '(net "A"' not in written[frozenset({"B"})]


def test_a_run_hands_back_the_sessions_wires_and_vias_and_what_the_log_says(tmp_path, stub):
    stub(said=COMPLETED.format(n=3, v=0))
    run = Freerouting().route(Job(FOOTPRINTS, OUTLINE, CLASSES, {}), tmp_path, "b")
    assert run.wires == (
        Wire("A", "F.Cu", 0.5, [(5.0, 10.0), (6.0, 10.0), (6.0, 12.0)]),
        Wire("B", "B.Cu", 1.0, [(25.0, 10.0), (7.0, 10.0)]),
    )
    assert run.vias == (Via("A", "Via[0-1]_800:400_um", (6.0, 12.0)),)
    assert run.unrouted == 3


@pytest.mark.parametrize(
    ("log", "left"),
    [
        ("\n".join([PASS.format(n=2), PASS.format(n=1), COMPLETED.format(n=0, v=4)]), 0),
        ("\n".join([PASS.format(n=2), COMPLETED.format(n=12, v=0), "Saving output"]), 12),
        # The last stage to complete is the one that stands.
        ("\n".join([COMPLETED.format(n=5, v=0), PASS.format(n=4), COMPLETED.format(n=1, v=0)]), 1),
        # A router that stopped before its autorouter was done has not said.
        ("\n".join([PASS.format(n=2), PASS.format(n=1)]), None),
        ("\n".join([COMPLETED.format(n=1, v=0).split(", final score")[0], PASS.format(n=2)]), 2),
        ("Auto-routing stage completed", None),
        ("", None),
    ],
)
def test_what_is_left_unrouted_is_what_the_autorouter_ended_on(log, left):
    assert unrouted(log) == left


def test_a_router_that_fails_or_writes_no_session_is_an_error(tmp_path, monkeypatch):
    whole = Job(FOOTPRINTS, OUTLINE, CLASSES, {})
    monkeypatch.setenv("FREEROUTING", f"{sys.executable} -c 'import sys; sys.exit(3)'")
    with pytest.raises(RouterError, match="freerouting exited 3"):
        Freerouting().route(whole, tmp_path, "b")
    monkeypatch.setenv("FREEROUTING", f"{sys.executable} -c 'print(1)'")
    with pytest.raises(RouterError, match="freerouting exited 0"):
        Freerouting().route(whole, tmp_path, "b")
    monkeypatch.setenv("FREEROUTING", "no-such-router-command")
    with pytest.raises(RouterError, match="not found"):
        Freerouting().route(whole, tmp_path, "b")


@pytest.fixture
def router():
    """Freerouting itself, where there is one."""
    try:
        router_command()
    except RouterError as e:
        pytest.skip(str(e))
    return Freerouting()


def joined(wires, net: str) -> bool:
    """Whether *net*'s wires, taken end to end, join its two pads."""
    reach = {PADS[net][0]}
    segments = [(a, b) for w in wires if w.net == net
                for a, b in zip(w.points, w.points[1:], strict=False)]  # fmt: skip
    while True:
        more = {q for a, b in segments for p, q in ((a, b), (b, a)) if p in reach} - reach
        if not more:
            return PADS[net][1] in reach
        reach |= more


def test_freerouting_routes_a_board_and_says_it_left_nothing(tmp_path, router):
    run = router.route(Job(FOOTPRINTS, OUTLINE, CLASSES, {}), tmp_path, "b")
    assert run.unrouted == 0
    assert joined(run.wires, "A") and joined(run.wires, "B")
    assert {w.width for w in run.wires} == {0.5}


def test_freerouting_says_what_it_could_not_route(tmp_path, router):
    """With the board walled in two on both layers, neither net can be joined."""
    run = router.route(Job(FOOTPRINTS, OUTLINE, CLASSES, {}, keepouts=WALLS), tmp_path, "b")
    assert run.unrouted == 2
    assert not joined(run.wires, "A") and not joined(run.wires, "B")


def test_freerouting_routes_a_board_in_stages(tmp_path, router):
    """The wide net first and alone, then the other around it; laid, the board has both."""
    whole = Job(FOOTPRINTS, OUTLINE, CLASSES, {"Wide": ["B"]})
    routed = staged(router, whole, tmp_path, "b")
    assert [(stage, run.unrouted) for stage, run in routed.runs] == [("power", 0), ("", 0)]
    first = routed.runs[0][1]
    assert {w.net for w in first.wires} == {"B"} and joined(first.wires, "B")
    assert joined(routed.wires, "A") and joined(routed.wires, "B")
    assert {w.width for w in routed.wires if w.net == "B"} == {1.0}
    for left in ("b-power.dsn", "b-power.ses", "freerouting-power.log", "b.dsn", "b.ses",
                 "freerouting.log"):  # fmt: skip
        assert (tmp_path / left).exists(), left
    # The router's settings and its own log go beside its output, not into the home.
    assert (tmp_path / "freerouting").is_dir()
    assert os.environ.get("FREEROUTING__USER_DATA_PATH") is None
    board = Board()
    lay(board, routed)
    nets = [str(find(s, "net")[1]) for s in find_all(board.sexpr(), "segment")]  # type: ignore[index]
    assert set(nets) == {"A", "B"}
    assert len(nets) == sum(len(w.points) - 1 for w in routed.wires)
