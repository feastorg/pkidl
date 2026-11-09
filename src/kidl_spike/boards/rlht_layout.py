"""Physical layer of Slice_RLHT: the Slice S format, block placement, routed by Freerouting.

What is fixed:

- the format: a 70 x 100 mm board, R5 corners, four 5 mm holes 5 mm in from each
  corner, and the bus connector J1 with its pin-row centre 3.6 mm from the bus
  edge and 50 mm up from the bottom (``common.SLICE_S``);
- the Nano (A1), where the original puts it: its USB overhangs the bottom edge,
  and the Slice case places its USB port from the board file.

What is generated:

- each subcircuit's parts are placed as a block: one relative layout per block,
  instanced once per channel at a fixed pitch. The relay block is a relay
  channel (relay, coil diode, opto, its resistor, fuse and terminal); the
  thermocouple block is a MAX31855K front end and its terminal. Root parts (the
  buck converter and the status LED) keep the original's positions;
- the routing: Freerouting, on a DSN pkidl writes from the placed board;
- a GND pour on both layers.

Board coordinates are the original's (feastorg/Slice_RLHT@a7308f3), so the two
compare directly.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from kidl_spike import libs
from kidl_spike.boards.block_layout import (
    RELAY_TERMINAL,
    TC_TERMINAL,
    channel_spots,
    label_terminal,
)
from kidl_spike.boards.common import SLICE_S
from kidl_spike.boards.rlht import RELAYS, THERMOCOUPLES
from kidl_spike.boards.slice import (
    MOUNTING_HOLE_RULE,
    ORIGIN,
    RULES,
    SIGNAL_MINIMUM,
    Spot,
    outline_polygon,
    place_board,
    route,
)
from pkidl.dsn import Via, via_padstack
from pkidl.footprint import Placement, place
from pkidl.project import (
    PARITY_ERRORS,
    SILK_ERRORS,
    DruRule,
    NetClass,
    width_rules,
    write_project,
    write_rules,
)
from pkidl.sexpr import find
from pkidl.silk import nearest_clear_spot, place_references
from pkidl.stitch import stitch_points

# Fixed, by the format or by the original.
J1_PIN1 = SLICE_S.bus_pin1(*ORIGIN)
FIXED = {
    "J1": Spot(*J1_PIN1),  # slice bus, pins running down the bus edge
    "A1": Spot(135.0, 100.0),  # Arduino Nano, USB over the bottom edge
    # 12 V -> 5 V buck: the regulator and its passives underneath, the heatsink
    # pad on top.
    "U1": Spot(132.7, 64.1, 0, True),
    "C1": Spot(132.5, 60.8, 180, True),
    "C2": Spot(135.1, 67.6, 180, True),
    "C3": Spot(137.8, 60.8, 0, True),
    "C4": Spot(137.8, 57.8, 0, True),
    "L1": Spot(137.8, 64.1, 0, True),
    "HS1": Spot(135.3, 62.7),
    "D1": Spot(173.3, 136.132769),  # status LED
}
# The 6-way terminals sit where the original puts them, 31.89 mm apart (each is
# 31.48 long); the top one as high as the top-right hole's courtyard allows.
RELAY_ANCHORS = [(153.725, 62.9), (153.725, 94.79)]

TC_ANCHORS = [(163.68, 125.0), (163.68, 118.0)]  # 7 mm apart: the 2-way terminal is 6.54

LOGO = ("KMLib_Aesthetic:OSHW_Logo_10mm", 136.5, 83.0)
LABEL_AT = (161.0, 136.6)


HV_NETS = [f"{r['ch']}_{n}" for r in RELAYS for n in ("COM", "NO", "NC", "LINE", "ESTOP")]
NETCLASSES = [
    # The Slice design constraints: 0.5 mm minimum track, 0.2 mm spacing.
    NetClass("Default", clearance=0.2, track_width=0.5, via_diameter=1.0, via_drill=0.5),
    # The relay-switched heater lines, from the original's HV Relay class.
    NetClass("HV Relay", clearance=1.25, track_width=3.0, via_diameter=1.6, via_drill=0.8),
]
MEMBERS = {"HV Relay": HV_NETS}

# Mains on the relay-switched lines (decided 2026-11-08). IEC 60664-1, 230 V,
# overvoltage category II, pollution degree 2, material group III, as reproduced in
# TI SLUP421: reinforced insulation to the bus side (SELV), basic between mains
# conductors. Warnings until the layout meets them; J4/J5 pin 3 (GND between mains
# pins) cannot, by circuit (Slice_RLHT#90).
MAINS_LV_CLEARANCE = 3.0
MAINS_LV_CREEPAGE = 5.6
MAINS_RULES = [
    DruRule("mains to LV clearance", "clearance", MAINS_LV_CLEARANCE,
            "A.NetClass == 'HV Relay' && B.NetClass != 'HV Relay'",
            why="reinforced clearance: Table F.2, one step above 2.5 kV"),
    DruRule("mains to LV creepage", "creepage", MAINS_LV_CREEPAGE,
            "A.NetClass == 'HV Relay' && B.NetClass != 'HV Relay'",
            why="reinforced creepage: twice Table F.4's ~2.8 mm basic value at 250 V"),
    DruRule("mains to mains clearance", "clearance", 1.5,
            "A.NetClass == 'HV Relay' && B.NetClass == 'HV Relay' && A.NetName != B.NetName",
            why="basic clearance as the floor between mains conductors"),
]  # fmt: skip
# GND vias at HS1, the original's, from HS1's origin: (dx, dy, diameter, drill).
HS1_VIAS = [
    (-5.2, 1.85, 0.8, 0.4), (-5.0, 5.1, 0.8, 0.4), (-2.6, 2.3, 0.5, 0.3), (-1.5, -0.4, 0.5, 0.3),
    (-1.4, -5.15, 0.8, 0.4), (-1.3, -3.4, 0.5, 0.3), (-0.6, -0.4, 0.5, 0.3), (-0.2, -2.6, 0.5, 0.3),
    (-0.2, -1.3, 0.5, 0.3), (1.0, -3.4, 0.5, 0.3), (5.5, -3.45, 0.8, 0.4), (5.5, -0.55, 0.8, 0.4),
    (5.5, 4.45, 0.8, 0.4),
]  # fmt: skip
# GND stitching between the two pours, placed after routing where nothing else is: the
# original's 0.8/0.4 vias, kept the mains creepage from HV copper and the mounting-hardware
# keepout from holes.
STITCH_PITCH = 5.0
STITCH_VIA = (0.8, 0.4)

# The mains routes are full width (two-stage routing, 2026-11-09): their minimum is an error.
DRU_RULES = (
    [
        replace(r, severity="error") if r.name == "HV Relay width" else r
        for r in width_rules(NETCLASSES, minimums=SIGNAL_MINIMUM)
    ]
    + MAINS_RULES
    + [MOUNTING_HOLE_RULE]
)


def placement() -> dict[str, Spot]:
    """Every footprint's position, by reference."""
    spots = dict(FIXED)
    for r, anchor in zip(RELAYS, RELAY_ANCHORS, strict=True):
        spots |= channel_spots("relay", r, anchor)
    for t, anchor in zip(THERMOCOUPLES, TC_ANCHORS, strict=True):
        spots |= channel_spots("thermocouple", t, anchor)
    return spots


def build_pcb(
    outdir: Path,
    name: str,
    pad_nets: dict[str, dict[str, str]],
    fields: dict[str, dict[str, str]],
    source: str,
) -> Path:
    """Write ``<name>.kicad_pcb``, ``<name>.kicad_pro`` and lib tables into *outdir*, routed.

    As ``loaf_layout.build_pcb``. Routing writes ``<name>.dsn``, ``<name>.ses`` and
    the router's log alongside.
    """
    # The Nano's GND pins join the GND pours directly: routing beside them can leave a
    # thermal relief one spoke short of the two the rules require.
    board, placed = place_board(
        outdir, name, placement(), pad_nets, fields, solid_pads=frozenset({"A1"})
    )
    # The mains routes cannot all keep 3 mm from LV copper (pins sit closer by their
    # footprints), so only the signals routed around them are held to it.
    hs1 = find(placed["HS1"], "at")
    assert hs1 is not None
    hx, hy = float(hs1[1]), float(hs1[2])
    vias = [Via("GND", via_padstack(d, h), (round(hx + dx, 6), round(hy + dy, 6)))
            for dx, dy, d, h in HS1_VIAS]  # fmt: skip
    route(board, placed, outdir, name, NETCLASSES, MEMBERS,
          signal_clearances={("HV Relay", "Default"): MAINS_LV_CLEARANCE}, vias=vias)  # fmt: skip
    keep = {net: MAINS_LV_CREEPAGE for net in HV_NETS} | {"": MOUNTING_HOLE_RULE.min_mm}
    edge_clearance = float(RULES["min_copper_edge_clearance"])
    for p in stitch_points(board.items, "GND", outline_polygon(), pitch=STITCH_PITCH,
                           diameter=STITCH_VIA[0], clearance=0.5, edge=edge_clearance,
                           keep_from=keep):  # fmt: skip
        board.via(p, *STITCH_VIA, "GND")

    lib_id, x, y = LOGO
    board.footprint(place(libs.footprint_file(lib_id), Placement(lib_id, "LOGO1", "", x, y)))
    # Terminal labels go left of the terminal's silkscreen outline, a gap clear of it.
    for chans, labels in ((RELAYS, RELAY_TERMINAL), (THERMOCOUPLES, TC_TERMINAL)):
        for c in chans:
            label_terminal(board, placed, c, labels, SLICE_S.outline(*ORIGIN))

    x0, y0, x1, y1 = SLICE_S.outline(*ORIGIN)
    edge = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    for layer in ("F.Cu", "B.Cu"):
        # Not POUR_MIN_WIDTH yet: at 0.5 mm, U1.4 and U5.3 keep one thermal spoke of two.
        board.zone("GND", layer, edge, clearance=0.5)

    libs.write_project_lib_tables(outdir)
    write_project(
        outdir / f"{name}.kicad_pro",
        netclasses=NETCLASSES,
        members=MEMBERS,
        rules=RULES,
        severities=PARITY_ERRORS | SILK_ERRORS,
    )
    write_rules(outdir / f"{name}.kicad_dru", DRU_RULES)
    place_references(board.items, SLICE_S.outline(*ORIGIN))
    label = f"Slice_RLHT | kidl-spike {source}"
    # After the references, nearest its intended spot that is clear of parts and
    # text: its length varies with the source id, so it gives way, not them.
    at = nearest_clear_spot(
        board.items, label, LABEL_AT, SLICE_S.outline(*ORIGIN), size=0.8, thickness=0.12
    )
    board.text(label, at or LABEL_AT, size=0.8, thickness=0.12)
    return board.write(outdir / f"{name}.kicad_pcb")
