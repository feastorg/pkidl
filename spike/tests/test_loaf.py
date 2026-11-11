"""The generated Loaf must be equivalent to the hand-drawn Loaf_x004.

The fixtures come from the original board (feastorg/Loaf_x004@ebf47df): KiCad's
own netlist export of it, and its placed footprints as KiCad saved them. So the
generator is compared against KiCad's reading of the original, not against the
generator's own constants.

KiCad's ERC and DRC verdicts on the generated files run in CI's KiCad job.
"""

import json
from pathlib import Path

import pytest
from pkidl.footprint import pad_xy
from pkidl.sexpr import find, find_all, parse

from kidl_spike import libs
from kidl_spike.boards import loaf_layout

FIXTURES = Path(__file__).parent / "fixtures"
NETS = FIXTURES / "loaf_x004_nets.json"
FOOTPRINTS = FIXTURES / "loaf_x004_footprints.kicad_pcb"


def _expected_nets() -> dict[str, set[str]]:
    return {name: set(nodes) for name, nodes in json.loads(NETS.read_text())["nets"].items()}


def _require(footprints: bool = False) -> None:
    pytest.importorskip("skidl")
    try:
        libs.master_lib_root()
    except libs.LibraryError as e:
        pytest.skip(str(e))
    stock_sym, stock_fp = libs.stock_dirs()
    if stock_sym is None:
        pytest.skip("no stock KiCad symbol library present")
    if footprints and stock_fp is None:
        pytest.skip("no stock KiCad footprint library present")


@pytest.fixture
def loaf_nets(tmp_path):
    _require()
    from kidl_spike.boards import loaf

    return loaf.circuit(workdir=tmp_path)


@pytest.fixture
def loaf_board(tmp_path) -> Path:
    _require(footprints=True)
    from kidl_spike.boards import loaf

    return loaf.build(tmp_path / "a", source="test") / "loaf.kicad_pcb"


def test_netlist_matches_original(loaf_nets):
    # Power flags (#FLG) are virtual parts; the original has none, by design.
    generated = {
        name: {f"{p.part.ref}.{p.num}" for p in net.pins if not p.part.ref.startswith("#")}
        for name, net in loaf_nets.items()
    }
    assert generated == _expected_nets()


def test_board_pads_match_original_netlist(loaf_board):
    """Every pad on the generated board carries the net the original gives it."""
    generated: dict[str, set[str]] = {}
    for fp in find_all(parse(loaf_board.read_text()), "footprint"):
        ref = next(p[2] for p in find_all(fp, "property") if p[1] == "Reference")
        for pad in find_all(fp, "pad"):
            net = find(pad, "net")
            if net is not None:
                generated.setdefault(net[1], set()).add(f"{ref}.{pad[1]}")
    assert generated == _expected_nets()


def test_interface_matches_original():
    """The fixed mechanical interface is exactly where the original puts it."""
    from kidl_spike.boards.loaf_layout import PLACEMENT

    original = {}
    for fp in find_all(parse(FOOTPRINTS.read_text()), "footprint"):
        ref = next(p[2] for p in find_all(fp, "property") if p[1] == "Reference")
        at, layer = find(fp, "at"), find(fp, "layer")
        assert at is not None and layer is not None
        rot = float(at[3]) if len(at) > 3 else 0.0
        original[ref] = (float(at[1]), float(at[2]), rot, layer[1] == "B.Cu")
    assert {ref: original[ref] for ref in PLACEMENT} == PLACEMENT


def test_board_is_byte_stable(loaf_board):
    """A second build writes the same board, project and library tables, byte for byte."""
    from kidl_spike.boards import loaf

    first = loaf_board.parent
    second = loaf.build(first.parent / "b", source="test")
    for name in ("loaf.kicad_pcb", "loaf.kicad_pro", "loaf.kicad_dru", "sym-lib-table",
                 "fp-lib-table"):  # fmt: skip
        assert (second / name).read_bytes() == (first / name).read_bytes(), name


def _rules(board: Path) -> dict[str, str]:
    """Rule name -> rule text, from the generated .kicad_dru beside the board."""
    text = board.with_suffix(".kicad_dru").read_text()
    return {chunk.split('"')[1]: chunk for chunk in text.split("(rule ")[1:]}


def test_rules_gate_widths_and_holes(loaf_board):
    """The bus width is a DRC minimum, and the slice connectors' holes get a keepout."""
    rules = _rules(loaf_board)
    assert "(constraint track_width (min 0.4mm))" in rules["BREAD width"]
    hole = rules["mounting hole keepout"]
    assert "(constraint hole_clearance (min 2mm))" in hole
    assert all(f"memberOfFootprint('{j}')" in hole for j in ("J3", "J4", "J5", "J6"))


def test_supply_pours_connect_pads_solidly(loaf_board):
    """Thermal spokes would limit each slice pin to about 2.9 A, under the 5 A budget."""
    zones = {}
    for z in find_all(parse(loaf_board.read_text()), "zone"):
        net = find(z, "net")
        assert net is not None
        zones[net[1]] = z
    for net in ("+12V", "GND"):
        connect = find(zones[net], "connect_pads")
        assert connect is not None and connect[1] == "yes", net


def _texts(board: Path) -> list[tuple[str, float, float]]:
    out = []
    for g in find_all(parse(board.read_text()), "gr_text"):
        at = find(g, "at")
        assert at is not None
        out.append((str(g[1]), float(at[1]), float(at[2])))
    return out


def test_every_bus_pin_is_labelled(loaf_board):
    """As on the original: each bus connector's pins carry their signal's short name, in
    the pin's row (J7, beside the board edge, just right of each pin)."""
    board = parse(loaf_board.read_text())
    texts = _texts(loaf_board)
    fps = {next(p for p in find_all(f, "property") if p[1] == "Reference")[2]: f
           for f in find_all(board, "footprint")}  # fmt: skip
    labels = 0
    for ref in loaf_layout.BUS_CONNECTORS:
        for pad in find_all(fps[ref], "pad"):
            net = find(pad, "net")
            if net is None:
                continue
            px, py = pad_xy(fps[ref], str(pad[1]))
            name = loaf_layout.PIN_LABEL[str(net[1])]
            dy = loaf_layout.PIN_LABEL_RIGHT.get(ref, (0, 0))[1]
            row = [t for t in texts if t[0] == name and abs(t[2] - (py + dy)) < 0.01
                   and abs(t[1] - px) < 15]  # fmt: skip
            assert row, (ref, pad[1], name)
            labels += 1
    assert labels == 60
    assert sorted(t[0] for t in texts if t[0].startswith("SLICE")) == [
        f"SLICE {n}" for n in range(1, 5)
    ]


def test_silk_over_copper_is_an_error(loaf_board):
    pro = json.loads(loaf_board.with_suffix(".kicad_pro").read_text())
    assert pro["board"]["design_settings"]["rule_severities"]["silk_over_copper"] == "error"


def test_every_text_is_on_the_board(loaf_board):
    """J2's header body overhangs the edge; its pin labels must still land on the board."""
    from pkidl.silk import text_box

    x0, y0, x1, y1 = loaf_layout.OUTLINE
    for g in find_all(parse(loaf_board.read_text()), "gr_text"):
        at, font = find(g, "at"), find(find(g, "effects"), "font")  # type: ignore[arg-type]
        assert at is not None and font is not None
        size = float(find(font, "size")[1])  # type: ignore[index]
        bx0, by0, bx1, by1 = text_box(str(g[1]).split("\n")[0], (float(at[1]), float(at[2])),
                                      size, 0.12, float(at[3]) if len(at) > 3 else 0.0)  # fmt: skip
        assert x0 <= bx0 and bx1 <= x1 and y0 <= by0 and by1 <= y1, (g[1], bx0, bx1)
