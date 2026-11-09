"""The generated Slice_DCMT must be equivalent to the hand-drawn original.

The fixture is KiCad's own netlist export of the original board
(feastorg/Slice_DCMT@b32e3b2), so the generator is compared against KiCad's
reading of the original, not against the generator's own constants.

Nets are compared by the pins they join, not by name: the generator's names are
chosen, the original's come from its sheets.

KiCad's ERC and DRC verdicts on the generated files run in CI's KiCad job.
"""

import json
from pathlib import Path

import pytest

from kidl_spike import libs
from kidl_spike.boards import dcmt
from kidl_spike.boards.common import default_circuit
from pkidl.route import RouterError, router_command
from pkidl.sexpr import find, find_all, parse

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "slice_dcmt_nets.json").read_text())

# Off-board parts the original marks exclude_from_board (the motors), left out
# of the generated circuit (see dcmt.py).
OFF_BOARD = {ref for ref, c in FIXTURE["components"].items() if not c["on_board"]}
# Mounting holes: on the board, but board-only footprints, not symbols (F-019).
BOARD_ONLY = {"H1", "H2", "H3", "H4"}


def _require() -> None:
    pytest.importorskip("skidl")
    try:
        libs.master_lib_root()
    except libs.LibraryError as e:
        pytest.skip(str(e))
    if libs.stock_dirs()[0] is None:
        pytest.skip("no stock KiCad symbol library present")


def _pins(nodes: list[str]) -> frozenset[str]:
    return frozenset(n for n in nodes if n.split(".")[0] not in OFF_BOARD)


@pytest.fixture(scope="module")
def dcmt_nets(tmp_path_factory):
    _require()
    return dcmt.circuit(workdir=tmp_path_factory.mktemp("env"))


def test_off_board_parts_are_the_motors():
    assert {"M1", "M2"} == OFF_BOARD


def test_netlist_matches_original(dcmt_nets):
    generated = {
        frozenset(f"{p.part.ref}.{p.num}" for p in net.pins if not p.part.ref.startswith("#"))
        for net in dcmt_nets.values()
    }
    expected = {_pins(nodes) for name, nodes in FIXTURE["nets"].items()
                if not name.startswith("unconnected-")}  # fmt: skip
    assert generated == expected


def test_unconnected_pins_match_original(dcmt_nets):
    """Every pin the original leaves unconnected is marked no-connect, and no other."""
    expected = {n for name, nodes in FIXTURE["nets"].items() if name.startswith("unconnected-")
                for n in nodes}  # fmt: skip
    assert {f"{p.part.ref}.{p.num}" for p in default_circuit().NC.pins} == expected


def test_parts_match_original(dcmt_nets):
    generated = {
        p.ref: {"symbol": p.name, "value": str(p.value), "footprint": p.footprint}
        for p in default_circuit().parts
        if not p.ref.startswith("#")
    }
    expected = {
        ref: {"symbol": c["symbol"].split(":")[1], "value": c["value"], "footprint": c["footprint"]}
        for ref, c in FIXTURE["components"].items()
        if ref not in OFF_BOARD | BOARD_ONLY
    }
    assert generated == expected


def test_hierarchy_matches_original(dcmt_nets):
    """Each original sheet instance is one subcircuit call holding the same parts,
    and the two calls are one subcircuit called twice."""
    by_sheet: dict[str, set[str]] = {}
    for ref, c in FIXTURE["components"].items():
        if ref not in OFF_BOARD | BOARD_ONLY:
            by_sheet.setdefault(c["sheet"], set()).add(ref)
    by_call: dict[tuple, set[str]] = {}
    for p in default_circuit().parts:
        if not p.ref.startswith("#"):
            by_call.setdefault(p.hiertuple, set()).add(p.ref)
    assert sorted(map(sorted, by_call.values())) == sorted(map(sorted, by_sheet.values()))
    assert sorted(h[-1] for h in by_call if len(h) > 1) == ["bridge1", "bridge2"]


# ─── The board ──────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def dcmt_board(tmp_path_factory) -> Path:
    _require()
    if libs.stock_dirs()[1] is None:
        pytest.skip("no stock KiCad footprint library present")
    try:
        router_command()
    except RouterError as e:
        pytest.skip(str(e))
    return dcmt.build(tmp_path_factory.mktemp("a"), source="test") / "dcmt.kicad_pcb"


def _get(node: list, key: str) -> list:
    child = find(node, key)
    assert child is not None, key
    return child


def _footprints(board: Path) -> dict[str, list]:
    return {next(p[2] for p in find_all(fp, "property") if p[1] == "Reference"): fp
            for fp in find_all(parse(board.read_text()), "footprint")}  # fmt: skip


def _pad_nets(board: Path) -> dict[str, set[str]]:
    pads: dict[str, set[str]] = {}
    for ref, fp in _footprints(board).items():
        for pad in find_all(fp, "pad"):
            net = find(pad, "net")
            if net is not None:
                pads.setdefault(net[1], set()).add(f"{ref}.{pad[1]}")
    return pads


def test_board_pads_match_original_netlist(dcmt_board):
    """Every pad carries the net the original gives it; each no-connect pin a net of its own."""
    pads = _pad_nets(dcmt_board)
    assert {frozenset(p) for p in pads.values()} == {_pins(n) for n in FIXTURE["nets"].values()}
    # Board files escape "/" in a net name as {slash}; the netlist export does not.
    unconnected = {n.replace("{slash}", "/") for n in pads if n.startswith("unconnected-")}
    assert unconnected == {n for n in FIXTURE["nets"] if n.startswith("unconnected-")}


def test_board_follows_slice_format(dcmt_board):
    """The Slice S edge, its four holes, and the bus where the format puts it."""
    from kidl_spike.boards.common import SLICE_S
    from kidl_spike.boards.slice import ORIGIN

    board = parse(dcmt_board.read_text())
    xs, ys = [], []
    for item in board:
        if isinstance(item, list) and item[0] in ("gr_line", "gr_arc"):
            for key in ("start", "end"):
                xs.append(float(_get(item, key)[1]))
                ys.append(float(_get(item, key)[2]))
    assert (min(xs), min(ys), max(xs), max(ys)) == SLICE_S.outline(*ORIGIN)
    fps = _footprints(dcmt_board)
    for ref, (x, y) in zip(sorted(BOARD_ONLY), SLICE_S.holes(*ORIGIN), strict=True):
        at, drill = _get(fps[ref], "at"), _get(_get(fps[ref], "pad"), "drill")
        assert (float(at[1]), float(at[2]), float(drill[1])) == (x, y, SLICE_S.hole_d), ref
    pins = [_get(p, "at") for p in find_all(fps["J1"], "pad")]
    at = _get(fps["J1"], "at")
    centre_y = float(at[2]) + sum(float(p[2]) for p in pins) / len(pins)
    assert float(at[1]) - ORIGIN[0] == pytest.approx(SLICE_S.bus_inset)
    assert ORIGIN[1] + SLICE_S.height - centre_y == pytest.approx(SLICE_S.bus_from_bottom)


def test_bridge_blocks_repeat_by_translation(dcmt_board):
    """Both bridges are one layout, the second a pure translation of the first."""
    from kidl_spike.boards.dcmt import BRIDGES

    fps = _footprints(dcmt_board)

    def spot(ref):
        at, layer = _get(fps[ref], "at"), _get(fps[ref], "layer")
        return float(at[1]), float(at[2]), float(at[3]) if len(at) > 3 else 0.0, layer[1]

    first, second = BRIDGES
    offsets = set()
    for role, ref in first.items():
        if isinstance(ref, str) and ref in fps:
            (x1, y1, r1, l1), (x2, y2, r2, l2) = spot(ref), spot(second[role])
            assert (r1, l1) == (r2, l2), role
            offsets.add((round(x2 - x1, 4), round(y2 - y1, 4)))
    assert offsets == {(0.0, -32.05)}


def test_motor_netclass_sized_for_the_design_current(dcmt_board):
    """Every net carrying a channel's motor current is in Motor, sized by IPC-2221 for 3 A."""
    from kidl_spike.boards.dcmt_layout import MOTOR_AMPS

    project = json.loads(dcmt_board.with_suffix(".kicad_pro").read_text())["net_settings"]
    members = {p["pattern"] for p in project["netclass_patterns"] if p["netclass"] == "Motor"}
    pads = _pad_nets(dcmt_board)
    # The original's per-channel high-current nets: supply, external supply, outputs.
    original = {_pins(FIXTURE["nets"][f"Motor Driver LMD18500{ch}/{n}"])
                for ch in (1, 2) for n in ("VS", "+VDC", "OUTPUT1", "OUTPUT2")}  # fmt: skip
    assert {frozenset(pads[m]) for m in members} == original
    motor = next(c for c in project["classes"] if c["name"] == "Motor")
    assert MOTOR_AMPS == 3.0
    # IPC-2221, outer layer, 1 oz, 10 C rise: 3 A needs 1.36 mm.
    assert motor["track_width"] >= 1.36


def test_power_pours_follow_the_blocks(dcmt_board):
    """Each channel's power pours exist, and the second's is the first's, translated."""
    board = parse(dcmt_board.read_text())
    zones: dict[tuple[str, str], list[tuple[float, float]]] = {}
    for z in find_all(board, "zone"):
        pts = [(float(p[1]), float(p[2])) for p in find_all(_get(_get(z, "polygon"), "pts"), "xy")]
        zones[(_get(z, "net")[1], _get(z, "layer")[1])] = pts
    for net, layer in (("VS", "F.Cu"), ("VDC", "F.Cu"), ("OUT1", "B.Cu"), ("OUT2", "B.Cu")):
        a, b = zones[(f"CH1_{net}", layer)], zones[(f"CH2_{net}", layer)]
        assert len(a) == len(b), net
        assert {
            (round(q[0] - p[0], 4), round(q[1] - p[1], 4)) for p, q in zip(a, b, strict=True)
        } == {(0.0, -32.05)}, net


def test_board_is_routed(dcmt_board):
    """Every net with more than one pad has copper; the router reported nothing left over."""
    board = parse(dcmt_board.read_text())
    routed = {_get(s, "net")[1] for s in find_all(board, "segment")}
    multi = {n for n, p in _pad_nets(dcmt_board).items() if len(p) > 1}
    assert multi <= routed
    log = (dcmt_board.parent / "freerouting.log").read_text()
    assert "(0 unrouted and 0 violations)" in log.split("Auto-routing stage completed")[-1]


def test_board_is_byte_stable(dcmt_board):
    """A second build, routing included, writes the same files byte for byte."""
    first = dcmt_board.parent
    second = dcmt.build(first.parent / "b", source="test")
    for name in ("dcmt.dsn", "dcmt.ses", "dcmt.kicad_pcb", "dcmt.kicad_pro", "dcmt.kicad_dru",
                 "sym-lib-table", "fp-lib-table"):  # fmt: skip
        assert (second / name).read_bytes() == (first / name).read_bytes(), name


def _rules(board: Path) -> dict[str, str]:
    """Rule name -> rule text, from the generated .kicad_dru beside the board."""
    text = board.with_suffix(".kicad_dru").read_text()
    return {chunk.split('"')[1]: chunk for chunk in text.split("(rule ")[1:]}


def test_rules_gate_widths_and_holes(dcmt_board):
    """Netclass widths are DRC minimums, and metal mounting hardware gets a keepout."""
    rules = _rules(dcmt_board)
    assert "(constraint track_width (min 1.4mm))" in rules["Motor width"]
    assert "(constraint track_width (min 1.4mm))" in rules["Power width"]
    assert "(constraint track_width (min 0.5mm))" in rules["Default width"]
    assert "(constraint hole_clearance (min 2mm))" in rules["mounting hole keepout"]
