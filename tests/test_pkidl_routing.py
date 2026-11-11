"""pkidl's staged routing: what each stage asks of a router, and what comes of the runs.

The router here hands back what a test scripts for it and records what it was asked:
the stages are told apart from the engine. ``tests/test_pkidl_route.py`` runs the real
one.
"""

import pytest

from pkidl.board import Board
from pkidl.dsn import Via, Wire
from pkidl.project import NetClass
from pkidl.routing import Job, Routed, Run, lay, staged
from pkidl.sexpr import find, find_all, parse

FOOTPRINT = """(footprint "R" (at {x} 10) (property "Reference" "{ref}")
  (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net "A"))
  (pad "2" smd rect (at 2 0) (size 1 1) (layers "F.Cu") (net "HV"))
  (pad "3" smd rect (at 4 0) (size 1 1) (layers "F.Cu") (net "GND"))
  (pad "4" smd rect (at 6 0) (size 1 1) (layers "F.Cu") (net ""))
  (pad "5" smd rect (at 8 0) (size 1 1) (layers "F.Cu")))"""
FOOTPRINTS = [parse(FOOTPRINT.format(x=x, ref=ref)) for x, ref in ((10, "R1"), (25, "R2"))]
OUTLINE = [(0.0, 0.0), (40.0, 0.0), (40.0, 30.0), (0.0, 30.0)]
ONE_CLASS = [NetClass("Default", 0.2, 0.5)]
CLASSES = [*ONE_CLASS, NetClass("HV", 1.25, 3.0), NetClass("Motor", 0.5, 2.0)]
MEMBERS = {"HV": ["HV"], "Motor": ["M+"]}
GAPS = {("HV", "Default"): 3.0}

VIA = "Via[0-1]_800:400_um"
AUTHORED = Wire("HV", "F.Cu", 3.0, [(12.0, 10.0), (12.0, 14.0)])
THERMAL = Via("GND", VIA, (14.0, 12.0))
STITCH = Via("HV", VIA, (12.0, 14.0))
KEEPOUT = ("F.Cu", [(30.0, 1.0), (38.0, 1.0), (38.0, 5.0), (30.0, 5.0)])
HV_POUR = ("HV", "F.Cu", [(1.0, 20.0), (20.0, 20.0), (20.0, 29.0), (1.0, 29.0)])
GND_POUR = ("GND", "B.Cu", [(1.0, 1.0), (39.0, 1.0), (39.0, 29.0), (1.0, 29.0)])

HV_ROUTE = Wire("HV", "F.Cu", 3.0, [(12.0, 10.0), (27.0, 10.0)])
A_ROUTE = Wire("A", "F.Cu", 0.5, [(10.0, 10.0), (10.0, 8.0), (25.0, 8.0), (25.0, 10.0)])
GND_ROUTE = Wire("GND", "B.Cu", 0.5, [(14.0, 10.0), (29.0, 10.0)])
A_VIA = Via("A", VIA, (10.0, 8.0))


class Scripted:
    """A router that hands back the run scripted for a stage and records each job."""

    def __init__(self, **runs: Run):
        self.runs = runs
        self.asked: list[tuple[str, Job]] = []
        self.where: list[tuple[object, str]] = []

    def route(self, job, outdir, name, stage=""):
        self.asked.append((stage, job))
        self.where.append((outdir, name))
        return self.runs.get(stage or "rest", Run((), ()))


def job(classes=CLASSES, **said) -> Job:
    return Job(FOOTPRINTS, OUTLINE, classes, MEMBERS, edge_clearance=0.4, **said)


def how(j: Job) -> tuple[bool, bool, bool]:
    return j.neck_down, j.cross_planes, j.quick


def test_a_board_with_one_class_and_no_planes_is_routed_in_one_run(tmp_path):
    router = Scripted(rest=Run((A_ROUTE, HV_ROUTE), (A_VIA,), 0))
    whole = job(ONE_CLASS, wires=[AUTHORED], vias=[THERMAL], keepouts=[KEEPOUT],
                class_clearances=GAPS)  # fmt: skip
    routed = staged(router, whole, tmp_path, "b")
    assert router.asked == [("", whole)]
    assert router.where == [(tmp_path, "b")]
    assert how(router.asked[0][1]) == (True, True, False)
    assert routed == Routed(
        (A_ROUTE, HV_ROUTE, AUTHORED), (A_VIA,), (("", Run((A_ROUTE, HV_ROUTE), (A_VIA,), 0)),)
    )


def test_the_nets_of_every_class_but_the_first_are_routed_first_alone_and_not_necked(tmp_path):
    router = Scripted()
    whole = job(wires=[AUTHORED], vias=[THERMAL], keepouts=[KEEPOUT], class_clearances=GAPS)
    staged(router, whole, tmp_path, "b")
    assert [stage for stage, _ in router.asked] == ["power", ""]
    assert router.where == [(tmp_path, "b")] * 2
    _, power = router.asked[0]
    assert power.only == {"HV", "M+"}
    assert how(power) == (False, True, False)
    # The clearances between classes are the second stage's, from this one's copper.
    assert power.class_clearances is None
    assert (list(power.wires), list(power.vias)) == ([AUTHORED], [THERMAL])
    assert (list(power.keepouts), list(power.planes)) == ([KEEPOUT], [])
    # The board is the one that was given.
    assert power.footprints is FOOTPRINTS
    assert (power.outline, power.netclasses, power.members) == (OUTLINE, CLASSES, MEMBERS)
    assert power.edge_clearance == 0.4


def test_the_first_classes_nets_wait_for_the_second_stage_though_named(tmp_path):
    router = Scripted()
    named = {"Default": ["A"], **MEMBERS}
    staged(router, Job(FOOTPRINTS, OUTLINE, CLASSES, named), tmp_path, "b")
    assert router.asked[0][1].only == {"HV", "M+"}
    router = Scripted()
    staged(router, Job(FOOTPRINTS, OUTLINE, CLASSES, {"Default": ["A"]}), tmp_path, "b")
    assert [stage for stage, _ in router.asked] == [""]


def test_a_class_with_no_nets_on_the_board_makes_no_first_stage(tmp_path):
    router = Scripted()
    staged(router, Job(FOOTPRINTS, OUTLINE, CLASSES, {}), tmp_path, "b")
    assert [stage for stage, _ in router.asked] == [""]


def test_the_rest_is_routed_around_the_first_stages_copper(tmp_path):
    """The first stage's wires and vias are fixed for the second, with what was there
    before routing and did not come back: each once."""
    back = Wire("HV", "F.Cu", 3.0, [(12.0, 14.0), (12.0, 10.0)])  # AUTHORED, handed back
    made = Via("HV", VIA, (27.0, 10.0))  # one the first stage put in
    router = Scripted(power=Run((HV_ROUTE, back), (STITCH, made), 0))
    other = Wire("GND", "B.Cu", 0.5, [(14.0, 10.0), (14.0, 12.0)])
    whole = job(wires=[AUTHORED, other], vias=[STITCH, THERMAL], keepouts=[KEEPOUT],
                class_clearances=GAPS)  # fmt: skip
    staged(router, whole, tmp_path, "b")
    _, rest = router.asked[1]
    assert rest.only is None
    assert how(rest) == (True, True, False)
    assert list(rest.wires) == [HV_ROUTE, back, other]
    assert list(rest.vias) == [STITCH, made, THERMAL]
    assert rest.class_clearances == GAPS
    assert (list(rest.keepouts), list(rest.planes)) == ([KEEPOUT], [])


def test_what_was_routed_is_each_stages_copper_once(tmp_path):
    first = Run((HV_ROUTE,), (STITCH,), 0)
    # The second run hands back every net, the first stage's copper among it.
    second = Run((HV_ROUTE, A_ROUTE), (STITCH, A_VIA), 1)
    router = Scripted(power=first, rest=second)
    routed = staged(router, job(wires=[AUTHORED], vias=[STITCH]), tmp_path, "b")
    assert routed.wires == (HV_ROUTE, A_ROUTE, AUTHORED)
    assert routed.vias == (STITCH, A_VIA)
    assert routed.runs == (("power", first), ("", second))


def test_an_authored_wire_the_router_hands_back_is_kept_once(tmp_path):
    """The router rounds a fixed wire to 0.1 um and may reverse it: it is still the same
    wire. One it does not hand back is still on the board."""
    authored = [Wire("HV", "F.Cu", 1.4, [(181.47070000001, 82.1), (191.30070000002, 82.1)]),
                Wire("HV", "F.Cu", 1.4, [(10.0, 10.0), (20.0, 10.0)])]  # fmt: skip
    back = Wire("HV", "F.Cu", 1.4, [(191.3007, 82.1), (181.4707, 82.1)])
    router = Scripted(rest=Run((back,), ()))
    routed = staged(router, job(ONE_CLASS, wires=authored), tmp_path, "b")
    assert routed.wires == (back, authored[1])


@pytest.mark.parametrize(
    ("change", "kept"),
    [
        ({"net": "A"}, True),  # another net's copper over the same ground
        ({"layer": "B.Cu"}, True),  # the other side of the board
        ({"points": [(12.0, 10.0), (12.0, 14.001)]}, True),  # a micrometre longer
        ({"points": [(12.0, 10.0), (12.0, 14.0004)]}, False),  # the same to the micrometre
        ({"points": [(12.0, 10.0), (12.0, 12.0), (12.0, 14.0)]}, True),  # in two pieces
        ({"width": 1.0}, False),  # the router's width for it
    ],
)
def test_a_wire_is_the_same_wire_by_its_net_layer_and_ends(tmp_path, change, kept):
    back = Wire(**{"net": "HV", "layer": "F.Cu", "width": 3.0, "points": AUTHORED.points} | change)
    router = Scripted(rest=Run((back,), ()))
    routed = staged(router, job(ONE_CLASS, wires=[AUTHORED]), tmp_path, "b")
    assert routed.wires == ((back, AUTHORED) if kept else (back,))


def test_a_wire_of_several_segments_is_handed_back_when_all_of_them_are(tmp_path):
    bend = Wire("HV", "F.Cu", 3.0, [(12.0, 10.0), (12.0, 14.0), (16.0, 14.0)])
    halves = (Wire("HV", "F.Cu", 3.0, [(12.0, 10.0), (12.0, 14.0)]),
              Wire("HV", "F.Cu", 3.0, [(16.0, 14.0), (12.0, 14.0)]))  # fmt: skip
    for back, kept in ((halves, False), (halves[:1], True)):
        router = Scripted(rest=Run(back, ()))
        routed = staged(router, job(ONE_CLASS, wires=[bend]), tmp_path, "b")
        assert routed.wires == ((*back, bend) if kept else back)


def test_until_the_last_stage_every_other_net_keeps_out_of_a_plane(tmp_path):
    router = Scripted()
    whole = job(keepouts=[KEEPOUT], planes=[GND_POUR, HV_POUR], class_clearances=GAPS)
    staged(router, whole, tmp_path, "b")
    assert [stage for stage, _ in router.asked] == ["power", "", "cross"]
    _, power = router.asked[0]
    # A plane makes its net one the router connects: only the power nets' pours are
    # planes in their stage, and the others are kept out of like any keepout.
    assert list(power.planes) == [HV_POUR]
    assert list(power.keepouts) == [KEEPOUT, GND_POUR[1:]]
    assert how(power) == (False, False, False)
    _, rest = router.asked[1]
    assert list(rest.planes) == [GND_POUR, HV_POUR]
    assert list(rest.keepouts) == [KEEPOUT]
    assert how(rest) == (True, False, True)


def test_what_is_left_may_cross_a_signal_nets_pour_and_never_a_power_nets(tmp_path):
    second = Run((HV_ROUTE, A_ROUTE), (STITCH, A_VIA), 1)
    router = Scripted(rest=second)
    whole = job(wires=[AUTHORED], keepouts=[KEEPOUT], planes=[GND_POUR, HV_POUR],
                class_clearances=GAPS)  # fmt: skip
    staged(router, whole, tmp_path, "b")
    assert router.where == [(tmp_path, "b")] * 3
    _, cross = router.asked[2]
    # The nets the board's pads are on, but for the power nets. A pad on no net is on none.
    assert cross.only == {"A", "GND"}
    assert list(cross.planes) == [GND_POUR]
    assert list(cross.keepouts) == [KEEPOUT, HV_POUR[1:]]
    assert how(cross) == (True, True, True)
    assert cross.class_clearances == GAPS
    # Everything routed so far is fixed.
    assert list(cross.wires) == [HV_ROUTE, A_ROUTE, AUTHORED]
    assert list(cross.vias) == [STITCH, A_VIA]


def test_the_last_stage_hands_back_the_signal_nets_and_the_power_nets_carry_forward(tmp_path):
    second = Run((HV_ROUTE, A_ROUTE), (STITCH, A_VIA), 1)
    longer = Wire("A", "B.Cu", 0.5, [(10.0, 10.0), (25.0, 10.0)])
    third = Run((longer, GND_ROUTE), (THERMAL,), 0)
    router = Scripted(rest=second, cross=third)
    routed = staged(router, job(wires=[AUTHORED], planes=[GND_POUR]), tmp_path, "b")
    assert routed.wires == (longer, GND_ROUTE, HV_ROUTE, AUTHORED)
    assert routed.vias == (THERMAL, STITCH)
    assert routed.runs == (("power", Run((), ())), ("", second), ("cross", third))


def test_a_board_with_planes_and_one_class_is_routed_then_crossed(tmp_path):
    router = Scripted()
    staged(router, job(ONE_CLASS, planes=[GND_POUR]), tmp_path, "b")
    assert [(stage, how(j)) for stage, j in router.asked] == [
        ("", (True, False, True)),
        ("cross", (True, True, True)),
    ]
    assert router.asked[1][1].only == {"A", "HV", "GND"}


def test_each_stage_says_which_nets_and_how_whatever_the_job_has(tmp_path):
    asked = dict(only=frozenset({"A"}), neck_down=False, cross_planes=False, quick=True)
    router = Scripted()
    staged(router, job(**asked), tmp_path, "b")
    assert [(j.only, how(j)) for _, j in router.asked] == [
        ({"HV", "M+"}, (False, True, False)),
        (None, (True, True, False)),
    ]
    router = Scripted()
    staged(router, job(planes=[GND_POUR], neck_down=False, cross_planes=False), tmp_path, "b")
    assert [how(j) for _, j in router.asked] == [
        (False, False, False),
        (True, False, True),
        (True, True, True),
    ]


def test_what_was_routed_is_laid_as_a_track_a_segment_and_its_vias():
    board = Board()
    lay(
        board,
        Routed(
            (A_ROUTE, HV_ROUTE, GND_ROUTE),
            (A_VIA, Via("HV", "Via[0-1]_1000:500_um", (27, 10))),
            (),
        ),
    )
    drawn = board.sexpr()

    def said(node, *keys):
        return tuple(" ".join(str(v) for v in find(node, k)[1:]) for k in keys)  # type: ignore[index]

    tracks = [said(s, "start", "end", "width", "layer", "net") for s in find_all(drawn, "segment")]
    assert tracks == [
        ("10 10", "10 8", "0.5", "F.Cu", "A"),
        ("10 8", "25 8", "0.5", "F.Cu", "A"),
        ("25 8", "25 10", "0.5", "F.Cu", "A"),
        ("12 10", "27 10", "3", "F.Cu", "HV"),
        ("14 10", "29 10", "0.5", "B.Cu", "GND"),
    ]  # fmt: skip
    assert [said(v, "at", "size", "drill", "net") for v in find_all(drawn, "via")] == [
        ("10 8", "0.8", "0.4", "A"),
        ("27 10", "1", "0.5", "HV"),
    ]
