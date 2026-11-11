"""Slice_TC4: a Slice that is only a YAML file (tc4.yaml), built by slice_build.

Four of this repo's thermocouple blocks on RLHT's root layout, with the Nano pin map and
channel positions of feastorg/Slice_THRM_31855. KiCad's ERC, DRC and schematic parity
run in CI's KiCad job.
"""

import importlib.util
import re
from pathlib import Path

import pytest
from pkidl.route import RouterError, router_command
from pkidl.sexpr import find, find_all, parse

from kidl_spike import libs
from kidl_spike.boards import slice_build
from kidl_spike.boards.spec import load

SPEC = load("tc4")


@pytest.fixture(scope="module")
def tc4_board(tmp_path_factory) -> Path:
    pytest.importorskip("skidl")
    try:
        libs.master_lib_root()
        router_command()
    except (libs.LibraryError, RouterError) as e:
        pytest.skip(str(e))
    if libs.stock_dirs()[0] is None or libs.stock_dirs()[1] is None:
        pytest.skip("no stock KiCad libraries present")
    return slice_build.build("tc4", tmp_path_factory.mktemp("a"), source="test") / "tc4.kicad_pcb"


def test_it_is_only_a_yaml_file():
    assert importlib.util.find_spec("kidl_spike.boards.tc4") is None
    assert importlib.util.find_spec("kidl_spike.boards.tc4_layout") is None


def test_the_references_nano_pins():
    """Slice_THRM_31855's map: SS1-SS4 on Nano pins 12, 11, 10, 9; SCK 15; SO 14."""
    assert [t["ss"] for t in SPEC.channels("thermocouple")] == [12, 11, 10, 9]
    assert SPEC.circuit.nano_pins[15] == "TC_CLK" and SPEC.circuit.nano_pins[14] == "TC_DATA"
    c = SPEC.circuit
    used = [*c.nano_pins, *c.nano_unused, *(t["ss"] for t in SPEC.channels("thermocouple"))]
    assert sorted(used) == list(range(1, 31))


def test_board_is_routed_and_byte_stable(tc4_board):
    board = parse(tc4_board.read_text())
    routed = {find(s, "net")[1] for s in find_all(board, "segment")}  # type: ignore[index]
    pads: dict[str, int] = {}
    for fp in find_all(board, "footprint"):
        for pad in find_all(fp, "pad"):
            net = find(pad, "net")
            if net is not None:
                pads[net[1]] = pads.get(net[1], 0) + 1
    assert {n for n, k in pads.items() if k > 1} <= routed
    log = (tc4_board.parent / "freerouting.log").read_text()
    before = re.search(r"Board has (\d+) pre-existing clearance violation", log)
    after = re.search(r"\((\d+) unrouted and (\d+) violations\)",
                      log.split("Auto-routing stage completed")[-1])  # fmt: skip
    assert after is not None and after[1] == "0"
    assert int(after[2]) == (int(before[1]) if before else 0)
    second = slice_build.build("tc4", tc4_board.parent.parent / "b", source="test")
    for name in ("tc4.dsn", "tc4.ses", "tc4.kicad_pcb", "tc4.kicad_pro", "tc4.kicad_dru"):
        assert (tc4_board.parent / name).read_bytes() == (second / name).read_bytes(), name
