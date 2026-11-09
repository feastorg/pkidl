"""Physical layer of Slice_HBTC: composed from the existing boards' pieces.

- the Slice format, holes, bus connector, routing and pours (``slice.py``);
- the root parts (Nano, buck, net tie, LED) where Slice_DCMT has them, and DCMT's GND
  vias at HS1, since the buck sits in the same place;
- the bridge block, its GNDPWR field, output strips and terminal labels, and the
  thermocouple block and its labels (``block_layout.py``), at the anchors in
  ``hbtc.yaml``;
- DCMT's netclasses for the motor and power nets, sized for one channel's current.
"""

from __future__ import annotations

from pathlib import Path

from kidl_spike import libs
from kidl_spike.boards import dcmt_layout
from kidl_spike.boards.block_layout import (
    TC_TERMINAL,
    at_offset,
    bridge_terminals,
    bridge_vias,
    bridge_zones,
    channel_spots,
    label_terminal,
)
from kidl_spike.boards.common import SLICE_S
from kidl_spike.boards.hbtc import BRIDGES, SPEC, THERMOCOUPLES
from kidl_spike.boards.slice import (
    MOUNTING_HOLE_RULE,
    ORIGIN,
    POUR_MIN_WIDTH,
    RULES,
    SIGNAL_MINIMUM,
    Spot,
    place_board,
    pour_outline,
    route,
)
from pkidl.dsn import Via, via_padstack
from pkidl.footprint import Placement, pad_xy, place
from pkidl.project import (
    PARITY_ERRORS,
    SILK_ERRORS,
    NetClass,
    width_rules,
    write_project,
    write_rules,
)
from pkidl.silk import nearest_clear_spot, place_references

# The root parts, where DCMT has them: its buck, net tie, Nano and LED (not its encoder
# terminals, which this board does not have).
ROOT = ("J1", "A1", "U1", "C1", "C2", "C3", "C4", "L1", "HS1", "NT1", "D1")
FIXED = {ref: dcmt_layout.FIXED[ref] for ref in ROOT}
LOGO = dcmt_layout.LOGO
LABEL_AT = dcmt_layout.LABEL_AT

MOTOR_NETS = [f"{b['ch']}_{n}" for b in BRIDGES for n in ("VS", "VDC", "OUT1", "OUT2")]
NETCLASSES = [
    NetClass("Default", clearance=0.2, track_width=0.5, via_diameter=1.0, via_drill=0.5),
    *[c for c in dcmt_layout.NETCLASSES if c.name in ("Motor", "Power")],
]
MEMBERS = {"Motor": MOTOR_NETS, "Power": ["+12V", "GNDPWR"]}
DRU_RULES = width_rules(NETCLASSES, minimums=SIGNAL_MINIMUM) + [MOUNTING_HOLE_RULE]
# Pours: (net, layer, priority), as on DCMT for its one bridge.
POURS = [
    *[(f"{b['ch']}_VDC", "F.Cu", 5) for b in BRIDGES],
    *[(f"{b['ch']}_VS", "F.Cu", 4) for b in BRIDGES],
    ("+12V", "F.Cu", 3),
    ("GND", "B.Cu", 1),
]


def placement() -> dict[str, Spot]:
    """Every footprint's position, by reference."""
    spots = dict(FIXED)
    for b in BRIDGES:
        spots |= channel_spots("bridge", b, SPEC.anchors[b["ch"]])
    for t in THERMOCOUPLES:
        spots |= channel_spots("thermocouple", t, SPEC.anchors[t["ch"]])
    return spots


def build_pcb(
    outdir: Path,
    name: str,
    pad_nets: dict[str, dict[str, str]],
    fields: dict[str, dict[str, str]],
    source: str,
) -> Path:
    """Write ``<name>.kicad_pcb``, ``<name>.kicad_pro`` and lib tables into *outdir*, routed."""
    outline = SLICE_S.outline(*ORIGIN)
    board, placed = place_board(
        outdir, name, placement(), pad_nets, fields, solid_pads=frozenset({"J1"})
    )
    hs1 = at_offset(placed["HS1"], 0, 0)
    vias = [Via("GND", via_padstack(d, h), (round(hs1[0] + dx, 6), round(hs1[1] + dy, 6)))
            for dx, dy, d, h in dcmt_layout.HS1_VIAS]  # fmt: skip
    for b in BRIDGES:
        vias += bridge_vias(placed, b)
    route(board, placed, outdir, name, NETCLASSES, MEMBERS, vias=vias)

    lib_id, x, y = LOGO
    board.footprint(place(libs.footprint_file(lib_id), Placement(lib_id, "LOGO1", "", x, y)))
    for ref, labels, title, layer, dx in [t for b in BRIDGES for t in bridge_terminals(b)]:
        texts = [(label, pad_xy(placed[ref], str(pin))) for pin, label in labels.items()]
        if title:
            px, py = pad_xy(placed[ref], str(min(labels)))
            texts.append((title, (px, py - 4.6)))  # clear of the bridge's reference text
        for text, (px, py) in texts:
            board.text(text, (px - dx, py), layer=layer, size=0.8, thickness=0.12, angle=90)
    for t in THERMOCOUPLES:
        label_terminal(board, placed, t, TC_TERMINAL, outline)

    for net, layer, priority in POURS:
        board.zone(net, layer, pour_outline(placed, net, dcmt_layout.POUR_MARGIN), clearance=0.5,
                   min_thickness=POUR_MIN_WIDTH, priority=priority, solid=True)  # fmt: skip
    for b in BRIDGES:
        bridge_zones(board, placed, b)
    x0, y0, x1, y1 = outline
    board.zone("GNDPWR", "B.Cu", [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], clearance=0.5,
               min_thickness=POUR_MIN_WIDTH)  # fmt: skip

    libs.write_project_lib_tables(outdir)
    write_project(outdir / f"{name}.kicad_pro", netclasses=NETCLASSES, members=MEMBERS,
                  rules=RULES, severities=PARITY_ERRORS | SILK_ERRORS)  # fmt: skip
    write_rules(outdir / f"{name}.kicad_dru", DRU_RULES)
    place_references(board.items, outline)
    label = f"Slice_HBTC\nkidl-spike {source}"
    at = nearest_clear_spot(board.items, label, LABEL_AT, outline, size=0.8, thickness=0.12)
    board.text(label, at or LABEL_AT, size=0.8, thickness=0.12)
    return board.write(outdir / f"{name}.kicad_pcb")
