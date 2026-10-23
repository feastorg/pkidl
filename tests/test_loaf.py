"""The generated Loaf must be netlist-equivalent to the hand-drawn Loaf_x004.

The fixture is KiCad's own netlist export of the original board (provenance in
the file), so this compares the generator against KiCad's reading of the
original rather than against the generator's own constants.
"""

import json
from pathlib import Path

import pytest

from kidl_spike import libs

FIXTURE = Path(__file__).parent / "fixtures" / "loaf_x004_nets.json"


@pytest.fixture
def loaf_nets(tmp_path):
    skidl = pytest.importorskip("skidl")
    try:
        libs.master_lib_root()
    except libs.LibraryError as e:
        pytest.skip(str(e))
    if libs.stock_dirs()[0] is None:
        pytest.skip("no stock KiCad symbol library present")

    from kidl_spike.boards import loaf

    skidl.reset()
    return loaf.circuit(workdir=tmp_path)


def test_netlist_matches_original(loaf_nets):
    expected = {name: set(nodes) for name, nodes in json.loads(FIXTURE.read_text())["nets"].items()}
    # Power flags (#FLG) are virtual parts; the original has none, by design.
    generated = {
        name: {f"{p.part.ref}.{p.num}" for p in net.pins if not p.part.ref.startswith("#")}
        for name, net in loaf_nets.items()
    }
    assert generated == expected
