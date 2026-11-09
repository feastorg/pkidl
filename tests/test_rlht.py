"""The generated Slice_RLHT must be equivalent to the hand-drawn original.

The fixture is KiCad's own netlist export of the original board
(feastorg/Slice_RLHT@a7308f3), so the generator is compared against KiCad's
reading of the original, not against the generator's own constants.

Nets are compared by the pins they join, not by name: the original's names are
mostly KiCad's automatic ones (``Net-(D2-A)``), the generator's are chosen.

KiCad's ERC and DRC verdicts on the generated files run in CI's KiCad job.
"""

import json
from pathlib import Path

import pytest

from kidl_spike import libs
from kidl_spike.boards import rlht
from pkidl.route import RouterError, router_command
from pkidl.sexpr import find, find_all, parse

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "slice_rlht_nets.json").read_text())

# The off-board E-stop switches, left out of the generated circuit (see rlht.py).
OFF_BOARD = {"SW1", "SW2"}
# Mounting holes: on the board, but board-only footprints, not symbols (F-019).
BOARD_ONLY = {"H1", "H2", "H3", "H4"}

# The nets the original draws in 3 mm track, from its board
# (hardware/BREAD_Slice.kicad_pcb, segments of width 3): the relay-switched lines.
ORIGINAL_HV = ["Relay/IN", "Relay/NC", "Relay/NO", "Relay1/IN", "Relay1/NC", "Relay1/NO",
               "Net-(J4-Pin_1)", "Net-(J4-Pin_2)", "Net-(J5-Pin_1)", "Net-(J5-Pin_2)"]  # fmt: skip

# Deliberate differences from the original: reference -> field -> generated value.
CHANGED = {
    "D1": {"symbol": "WS2812B_5050_RGB_LED"},
    "U1": {"value": "AP63205WU-7"},
}


def _require() -> None:
    pytest.importorskip("skidl")
    try:
        libs.master_lib_root()
    except libs.LibraryError as e:
        pytest.skip(str(e))
    if libs.stock_dirs()[0] is None:
        pytest.skip("no stock KiCad symbol library present")


def _expected() -> set[frozenset[str]]:
    """The original's nets as pin sets: off-board pins dropped, unconnected pins skipped."""
    out = set()
    for name, nodes in FIXTURE["nets"].items():
        pins = frozenset(n for n in nodes if n.split(".")[0] not in OFF_BOARD)
        if not name.startswith("unconnected-"):
            out.add(pins)
    return out


@pytest.fixture(scope="module")
def rlht_nets(tmp_path_factory):
    _require()

    return rlht.circuit(workdir=tmp_path_factory.mktemp("env"))


def test_netlist_matches_original(rlht_nets):
    generated = {
        frozenset(f"{p.part.ref}.{p.num}" for p in net.pins if not p.part.ref.startswith("#"))
        for net in rlht_nets.values()
    }
    assert generated == _expected()


def test_unconnected_pins_match_original(rlht_nets):
    """Every pin the original leaves unconnected is marked no-connect, and no other."""

    expected = {n for name, nodes in FIXTURE["nets"].items() if name.startswith("unconnected-")
                for n in nodes}  # fmt: skip
    generated = {f"{p.part.ref}.{p.num}" for p in rlht.default_circuit().NC.pins}
    assert generated == expected


def test_parts_match_original(rlht_nets):
    generated = {
        p.ref: {"symbol": p.name, "value": str(p.value), "footprint": p.footprint}
        for p in rlht.default_circuit().parts
        if not p.ref.startswith("#")
    }
    expected = {}
    for ref, c in FIXTURE["components"].items():
        if ref in OFF_BOARD | BOARD_ONLY:
            continue
        fields = {
            "symbol": c["symbol"].split(":")[1],
            "value": c["value"],
            "footprint": c["footprint"],
        }
        expected[ref] = fields | CHANGED.get(ref, {})
    assert generated == expected


def test_hierarchy_matches_original(rlht_nets):
    """Each original sheet instance is one subcircuit call holding the same parts,
    and the four calls are two subcircuits called twice each."""
    by_sheet: dict[str, set[str]] = {}
    for ref, c in FIXTURE["components"].items():
        if ref not in OFF_BOARD | BOARD_ONLY:
            by_sheet.setdefault(c["sheet"], set()).add(ref)
    by_call: dict[tuple, set[str]] = {}
    for p in rlht.default_circuit().parts:
        if not p.ref.startswith("#"):
            by_call.setdefault(p.hiertuple, set()).add(p.ref)
    assert sorted(map(sorted, by_call.values())) == sorted(map(sorted, by_sheet.values()))
    calls = sorted(h[-1] for h in by_call if len(h) > 1)
    assert calls == ["max31855k1", "max31855k2", "relay1", "relay2"]


# ─── The board ──────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def rlht_board(tmp_path_factory) -> Path:
    _require()
    if libs.stock_dirs()[1] is None:
        pytest.skip("no stock KiCad footprint library present")
    try:
        router_command()
    except RouterError as e:
        pytest.skip(str(e))
    return rlht.build(tmp_path_factory.mktemp("a"), source="test") / "rlht.kicad_pcb"


def _get(node: list, key: str) -> list:
    child = find(node, key)
    assert child is not None, key
    return child


def _footprints(board: Path) -> dict[str, list]:
    return {next(p[2] for p in find_all(fp, "property") if p[1] == "Reference"): fp
            for fp in find_all(parse(board.read_text()), "footprint")}  # fmt: skip


def test_board_pads_match_original_netlist(rlht_board):
    """Every pad carries the net the original gives it; each no-connect pin a net of its own."""
    pads: dict[str, set[str]] = {}
    for ref, fp in _footprints(rlht_board).items():
        for pad in find_all(fp, "pad"):
            net = find(pad, "net")
            if net is not None:
                pads.setdefault(net[1], set()).add(f"{ref}.{pad[1]}")
    expected = {frozenset(n for n in nodes if n.split(".")[0] not in OFF_BOARD)
                for nodes in FIXTURE["nets"].values()}  # fmt: skip
    assert {frozenset(p) for p in pads.values()} == expected
    # Board files escape "/" in a net name as {slash}; the netlist export does not.
    unconnected = {n.replace("{slash}", "/") for n in pads if n.startswith("unconnected-")}
    assert unconnected == {n for n in FIXTURE["nets"] if n.startswith("unconnected-")}


def test_board_follows_slice_format(rlht_board):
    """70 x 100 mm, four 5 mm holes 5 mm in from the corners, the bus where the format puts it."""
    from kidl_spike.boards.common import SLICE_S
    from kidl_spike.boards.rlht_layout import ORIGIN

    # Format S as the fleet's format table states it (bread-mechanical
    # slice-case/design/synth/formats.yaml).
    assert (SLICE_S.width, SLICE_S.height, SLICE_S.corner_r) == (70.0, 100.0, 5.0)
    assert (SLICE_S.bus_inset, SLICE_S.bus_from_bottom) == (3.6, 50.0)
    assert (SLICE_S.hole_inset, SLICE_S.hole_d) == (5.0, 5.0)
    board = parse(rlht_board.read_text())
    xs, ys = [], []
    for item in board:
        if isinstance(item, list) and item[0] in ("gr_line", "gr_arc"):
            for key in ("start", "end"):
                xs.append(float(_get(item, key)[1]))
                ys.append(float(_get(item, key)[2]))
    assert (min(xs), min(ys), max(xs), max(ys)) == SLICE_S.outline(*ORIGIN)
    fps = _footprints(rlht_board)
    for ref, (x, y) in zip(sorted(BOARD_ONLY), SLICE_S.holes(*ORIGIN), strict=True):
        at, drill = _get(fps[ref], "at"), _get(_get(fps[ref], "pad"), "drill")
        assert (float(at[1]), float(at[2]), float(drill[1])) == (x, y, SLICE_S.hole_d), ref
    # J1: pin row centre 3.6 mm from the bus edge, 50 mm up from the bottom edge.
    pins = [_get(p, "at") for p in find_all(fps["J1"], "pad")]
    at = _get(fps["J1"], "at")
    centre_y = float(at[2]) + sum(float(p[2]) for p in pins) / len(pins)
    assert float(at[1]) - ORIGIN[0] == pytest.approx(SLICE_S.bus_inset)
    assert ORIGIN[1] + SLICE_S.height - centre_y == pytest.approx(SLICE_S.bus_from_bottom)


def test_blocks_repeat_by_translation(rlht_board):
    """Each subcircuit's parts are one layout, instanced once per channel at an offset."""
    from kidl_spike.boards.rlht import RELAYS, THERMOCOUPLES

    fps = _footprints(rlht_board)

    def spot(ref):
        at, layer = _get(fps[ref], "at"), _get(fps[ref], "layer")
        return float(at[1]), float(at[2]), float(at[3]) if len(at) > 3 else 0.0, layer[1]

    for channels in (RELAYS, THERMOCOUPLES):
        first, second = channels
        roles = [k for k, v in first.items() if isinstance(v, str) and v in fps]
        offsets = set()
        for role in roles:
            (x1, y1, r1, l1), (x2, y2, r2, l2) = spot(first[role]), spot(second[role])
            assert (r1, l1) == (r2, l2), role
            offsets.add((round(x2 - x1, 4), round(y2 - y1, 4)))
        assert len(offsets) == 1, offsets


def test_hv_relay_netclass_covers_the_original_3mm_nets(rlht_board):
    """HV Relay holds exactly the nets the original routes in 3 mm track, with its rules."""
    project = json.loads(rlht_board.with_suffix(".kicad_pro").read_text())["net_settings"]
    members = {p["pattern"] for p in project["netclass_patterns"] if p["netclass"] == "HV Relay"}
    pads: dict[str, set[str]] = {}
    for ref, fp in _footprints(rlht_board).items():
        for pad in find_all(fp, "pad"):
            net = find(pad, "net")
            if net is not None:
                pads.setdefault(net[1], set()).add(f"{ref}.{pad[1]}")
    original = {frozenset(n for n in FIXTURE["nets"][name] if n.split(".")[0] not in OFF_BOARD)
                for name in ORIGINAL_HV}  # fmt: skip
    assert {frozenset(pads[m]) for m in members} == original
    cls = next(c for c in project["classes"] if c["name"] == "HV Relay")
    assert (cls["track_width"], cls["clearance"]) == (3.0, 1.25)


def test_board_is_routed(rlht_board):
    """Every net with more than one pad has copper; the router reported nothing left over."""
    board = parse(rlht_board.read_text())
    routed = {_get(s, "net")[1] for s in find_all(board, "segment")}
    pads: dict[str, int] = {}
    for fp in find_all(board, "footprint"):
        for pad in find_all(fp, "pad"):
            net = find(pad, "net")
            if net is not None:
                pads[net[1]] = pads.get(net[1], 0) + 1
    assert {n for n, k in pads.items() if k > 1} <= routed
    log = (rlht_board.parent / "freerouting.log").read_text()
    assert "(0 unrouted and 0 violations)" in log.split("Auto-routing stage completed")[-1]


def test_board_is_byte_stable(rlht_board):
    """A second build, routing included, writes the same files byte for byte."""
    first = rlht_board.parent
    second = rlht.build(first.parent / "b", source="test")
    for name in ("rlht.dsn", "rlht.ses", "rlht.kicad_pcb", "rlht.kicad_pro", "rlht.kicad_dru",
                 "sym-lib-table", "fp-lib-table"):  # fmt: skip
        assert (second / name).read_bytes() == (first / name).read_bytes(), name


def _rules(board: Path) -> dict[str, str]:
    """Rule name -> rule text, from the generated .kicad_dru beside the board."""
    text = board.with_suffix(".kicad_dru").read_text()
    return {chunk.split('"')[1]: chunk for chunk in text.split("(rule ")[1:]}


def test_rules_gate_widths_mains_spacing_and_holes(rlht_board):
    """The decisions of 2026-11-08 are DRC rules: mains spacing (IEC 60664-1, 230 V),
    netclass widths as minimums, and a keepout for metal mounting hardware."""
    rules = _rules(rlht_board)
    assert "(constraint track_width (min 3mm))" in rules["HV Relay width"]
    assert "(constraint track_width (min 0.5mm))" in rules["Default width"]
    assert "(constraint clearance (min 3mm))" in rules["mains to LV clearance"]
    assert "(constraint creepage (min 5.6mm))" in rules["mains to LV creepage"]
    assert "(constraint clearance (min 1.5mm))" in rules["mains to mains clearance"]
    assert "memberOfFootprint('H?')" in rules["mounting hole keepout"]
    assert "(constraint hole_clearance (min 2mm))" in rules["mounting hole keepout"]
