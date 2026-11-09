"""Slice_HBTC: a Slice composed from existing blocks, generated from hbtc.yaml alone.

There is no original to compare against. These tests check what the composition
promises: every Nano pin used once, generated references that collide with nothing,
a fully routed board, and the same bytes from two builds. KiCad's ERC, DRC and
schematic parity run in CI's KiCad job.
"""

import re
from pathlib import Path

import pytest

from kidl_spike import libs
from kidl_spike.boards import hbtc
from pkidl.route import RouterError, router_command
from pkidl.sexpr import find, find_all, parse


def _require() -> None:
    pytest.importorskip("skidl")
    try:
        libs.master_lib_root()
    except libs.LibraryError as e:
        pytest.skip(str(e))
    if libs.stock_dirs()[0] is None or libs.stock_dirs()[1] is None:
        pytest.skip("no stock KiCad libraries present")
    try:
        router_command()
    except RouterError as e:
        pytest.skip(str(e))


@pytest.fixture(scope="module")
def hbtc_board(tmp_path_factory) -> Path:
    _require()
    return hbtc.build(tmp_path_factory.mktemp("a"), source="test") / "hbtc.kicad_pcb"


def test_every_nano_pin_is_used_once():
    c = hbtc.SPEC.circuit
    used = list(c.nano_pins) + list(c.nano_unused)
    for ch in c.channels:
        used += list(ch.params.get("pins", {}).values())
        used += [ch.params[k] for k in ("ss", "ctrl", "a", "b") if k in ch.params]
    assert sorted(used) == list(range(1, 31))


def test_references_are_generated_and_unique():
    refs = [v for ch in hbtc.SPEC.circuit.channels for k, v in ch.params.items()
            if k != "ch" and isinstance(v, str) and re.fullmatch(r"[A-Z]+\d+", v)]  # fmt: skip
    assert len(refs) == len(set(refs)) == 10 + 7 + 7
    assert "U1" not in refs and "J1" not in refs  # the buck's and the bus's


def test_board_is_routed(hbtc_board):
    board = parse(hbtc_board.read_text())
    routed = {find(s, "net")[1] for s in find_all(board, "segment")}  # type: ignore[index]
    pads: dict[str, int] = {}
    for fp in find_all(board, "footprint"):
        for pad in find_all(fp, "pad"):
            net = find(pad, "net")
            if net is not None:
                pads[net[1]] = pads.get(net[1], 0) + 1
    assert {n for n, k in pads.items() if k > 1} <= routed
    for log_name in ("freerouting-power.log", "freerouting.log"):
        log = (hbtc_board.parent / log_name).read_text()
        before = re.search(r"Board has (\d+) pre-existing clearance violation", log)
        after = re.search(r"\((\d+) unrouted and (\d+) violations\)",
                          log.split("Auto-routing stage completed")[-1])  # fmt: skip
        assert after is not None and after[1] == "0", log_name
        assert int(after[2]) == (int(before[1]) if before else 0), log_name


def test_board_is_byte_stable(hbtc_board):
    """A second build, routing included, writes the same files byte for byte."""
    first = hbtc_board.parent
    second = hbtc.build(first.parent / "b", source="test")
    for name in ("hbtc.dsn", "hbtc.ses", "hbtc-power.dsn", "hbtc-power.ses", "hbtc.kicad_pcb",
                 "hbtc.kicad_pro", "hbtc.kicad_dru", "sym-lib-table", "fp-lib-table"):  # fmt: skip
        assert (first / name).read_bytes() == (second / name).read_bytes(), name
