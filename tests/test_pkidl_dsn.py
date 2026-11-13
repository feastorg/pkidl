"""pkidl's DSN writer: which nets the router sees, fixed routes and class clearances."""

from pkidl.dsn import Via, Wire, write_dsn
from pkidl.project import NetClass
from pkidl.sexpr import parse

FOOTPRINT = """(footprint "R" (at {x} 10) (property "Reference" "{ref}")
  (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net "A"))
  (pad "2" smd rect (at 2 0) (size 1 1) (layers "F.Cu") (net "HV")))"""
FOOTPRINTS = [parse(FOOTPRINT.format(x=x, ref=ref)) for x, ref in ((10, "R1"), (20, "R2"))]
OUTLINE = [(0.0, 0.0), (40.0, 0.0), (40.0, 30.0), (0.0, 30.0)]
CLASSES = [NetClass("Default", 0.2, 0.5), NetClass("HV", 1.25, 3.0)]
MEMBERS = {"HV": ["HV"]}


def test_only_leaves_other_nets_out_of_the_network(tmp_path):
    text = write_dsn(
        tmp_path / "b.dsn", FOOTPRINTS, OUTLINE, CLASSES, MEMBERS, only={"HV"}
    ).read_text()
    assert '(net "HV" (pins R1-2 R2-2))' in text
    assert '(net "A"' not in text
    assert '(class "Default"' not in text
    assert text.count("(pin Pad") == 4  # every pin is still an obstacle


def test_fixed_routes_are_protected_wiring(tmp_path):
    fixed = ([Wire("HV", "F.Cu", 3.0, [(12.0, 10.0), (22.0, 10.5)])],
             [Via("HV", "Via[0-1]_1000:500_um", (15.0, 12.0))])  # fmt: skip
    text = write_dsn(
        tmp_path / "b.dsn", FOOTPRINTS, OUTLINE, CLASSES, MEMBERS, fixed=fixed
    ).read_text()
    assert '(wire (path F.Cu 3000 12000 -10000 22000 -10500) (net "HV") (type protect))' in text
    assert '(via "Via[0-1]_1000:500_um" 15000 -12000 (net "HV") (type protect))' in text


def test_class_clearance_needs_both_classes(tmp_path):
    pair = {("HV", "Default"): 3.0}
    both = write_dsn(tmp_path / "a.dsn", FOOTPRINTS, OUTLINE, CLASSES, MEMBERS,
                     class_clearances=pair).read_text()  # fmt: skip
    assert '(class_class (classes "HV" "Default") (rule (clearance 3000)))' in both
    one = write_dsn(tmp_path / "b.dsn", FOOTPRINTS, OUTLINE, CLASSES, MEMBERS, only={"HV"},
                    class_clearances=pair).read_text()  # fmt: skip
    assert "class_class" not in one


# KiCad's NetTie-2_SMD_Pad2.0mm: two 2 mm pads joined by a 4 x 2 mm polygon.
NET_TIE = """(footprint "NT" (at 10 10 {rot}) (property "Reference" "NT1")
  (pad "1" smd circle (at -2 0 {rot}) (size 2 2) (layers "B.Cu") (net "A"))
  (pad "2" smd circle (at 2 0 {rot}) (size 2 2) (layers "B.Cu") (net "B"))
  (fp_poly (pts (xy -2 1) (xy 2 1) (xy 2 -1) (xy -2 -1)) (fill yes) (layer "B.Cu")))"""


def test_net_tie_bridge_is_a_keepout_its_pads_stay_reachable(tmp_path):
    """The copper between a net tie's pads is kept out; the pads themselves are not."""
    for rot, rect in ((0, "-1000 -1000 1000 1000"), (90, "-1000 -1000 1000 1000")):
        text = write_dsn(tmp_path / f"{rot}.dsn", [parse(NET_TIE.format(rot=rot))], OUTLINE,
                         CLASSES, MEMBERS).read_text()  # fmt: skip
        assert f'(keepout "" (rect B.Cu {rect}))' in text, rot


def test_planes_are_written_closed_in_the_structure(tmp_path):
    """A plane is a pour the router connects through: net, layer, closed polygon in um."""
    square = [(1.0, 1.0), (5.0, 1.0), (5.0, 4.0), (1.0, 4.0)]
    text = write_dsn(
        tmp_path / "b.dsn", FOOTPRINTS, OUTLINE, CLASSES, MEMBERS, planes=[("A", "B.Cu", square)]
    ).read_text()
    plane = (
        '(plane "A" (polygon B.Cu 0  1000 -1000  5000 -1000  5000 -4000  1000 -4000  1000 -1000))'
    )
    assert plane in text
    assert text.index(plane) < text.index("  (placement")  # in the structure


HOLED = """(footprint "SW" (at 10 10) (property "Reference" "SW1")
  (pad "1" thru_hole circle (at 0 5) (size 2 2) (drill 1) (layers "*.Cu") (net "A"))
  (pad "" np_thru_hole circle (at 3 0) (size {size} {size}) (drill {drill})
    (layers "*.Cu" "*.Mask")))"""


def _hole(tmp_path, size, drill, **said):
    """The keepout written for an unplated hole 3 mm right of its part's origin."""
    footprints = [parse(HOLED.format(size=size, drill=drill))]
    text = write_dsn(tmp_path / "b.dsn", footprints, OUTLINE, CLASSES, MEMBERS, **said).read_text()
    (line,) = [line.strip() for line in text.splitlines() if "(circle signal" in line]
    return line


def test_an_unplated_hole_is_kept_out_of_as_far_as_kicad_asks_of_a_hole(tmp_path):
    # The least clearance of the classes is 0.2 mm, which the router keeps from a
    # keepout, and KiCad asks 0.25 mm from a hole: the circle is 0.05 mm wider each side.
    assert _hole(tmp_path, 1.27, 1.27) == '(keepout "" (circle signal 1370 3000 0))'
    # Where the router's clearance is already as much, the hole is its own width.
    assert _hole(tmp_path, 1.27, 1.27, hole_clearance=0.2) == (
        '(keepout "" (circle signal 1270 3000 0))'
    )
    assert _hole(tmp_path, 1.27, 1.27, hole_clearance=0.1) == (
        '(keepout "" (circle signal 1270 3000 0))'
    )


def test_an_unplated_hole_with_a_ring_round_it_is_kept_out_of_as_wide_as_its_pad(tmp_path):
    # A 2.1 mm hole in a 3.1 mm pad: the ring is copper on no net.
    assert _hole(tmp_path, 3.1, 2.1) == '(keepout "" (circle signal 3200 3000 0))'
    # A slot is taken by its longer side.
    assert _hole(tmp_path, 1, "oval 1 2.5") == '(keepout "" (circle signal 2600 3000 0))'


def test_the_router_holds_the_first_classs_clearance_from_a_hole_whatever_the_others_are(
    tmp_path,
):
    # Freerouting keeps a net's clearance from a keepout and never less than the first
    # class's, so that is what the hole's own clearance is measured against: 0.6 mm is
    # already more than KiCad's 0.25 mm, though another class has 0.1 mm.
    classes = [NetClass("Default", 0.6, 0.5), NetClass("Fine", 0.1, 0.2)]
    text = write_dsn(tmp_path / "b.dsn", [parse(HOLED.format(size=1.27, drill=1.27))],
                     OUTLINE, classes, {"Fine": ["A"]}).read_text()  # fmt: skip
    assert '(keepout "" (circle signal 1270 3000 0))' in text


def test_an_unplated_hole_in_a_pad_with_corners_is_kept_out_of_to_its_corners(tmp_path):
    squared = HOLED.replace("np_thru_hole circle", "np_thru_hole rect")
    text = write_dsn(tmp_path / "b.dsn", [parse(squared.format(size=4, drill=2))],
                     OUTLINE, CLASSES, MEMBERS).read_text()  # fmt: skip
    # 4 mm square is 5.6569 mm corner to corner, and 0.05 mm more each side.
    assert '(keepout "" (circle signal 5756.9 3000 0))' in text
