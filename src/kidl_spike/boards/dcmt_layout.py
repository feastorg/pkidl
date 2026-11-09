"""Physical layer of Slice_DCMT: the Slice S format, block placement, power pours, routed.

What is fixed:

- the format (``slice.py``): edge, holes, and the bus connector J1;
- the Nano (A1), where the original puts it: its USB overhangs the bottom edge,
  and the Slice case places its USB port from the board file.

What is generated:

- each H-bridge's parts are placed as one block, instanced per channel at the
  original's channel pitch. The block is the original's first channel, with its
  two terminals moved into the right-edge column so the second channel's clear
  the top-right hole. Root parts (buck, net tie, LED, encoder terminals) keep the
  original's positions;
- the routing: Freerouting connects every net, motor current nets included, at
  their netclass widths;
- pours on top of the routing, for current capacity: each power net's pour is
  the outline around its pads, so a channel placed twice gets its pours twice.
  Connectivity never depends on a pour: the tracks carry every connection.
"""

from __future__ import annotations

import math
from pathlib import Path

from kidl_spike import libs
from kidl_spike.boards.block_layout import (
    LABEL_DX,
    bridge_terminals,
    bridge_vias,
    bridge_zones,
    channel_spots,
)
from kidl_spike.boards.common import SLICE_S
from kidl_spike.boards.dcmt import BRIDGES, ENCODERS
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
from pkidl.sexpr import Node, find
from pkidl.silk import nearest_clear_spot, place_references

# The design current of each motor channel. The LMD18200 is rated 3 A continuous.
MOTOR_AMPS = 3.0


def ipc2221_width(amps: float, rise_c: float = 10.0, copper_oz: float = 1.0) -> float:
    """Track width (mm, rounded up to 0.1) for *amps* on an outer layer, IPC-2221.

    I = 0.048 * dT^0.44 * A^0.725, with A the cross-section in mil^2; 1 oz copper
    is 1.378 mil thick.
    """
    area_mil2 = (amps / (0.048 * rise_c**0.44)) ** (1 / 0.725)
    width_mm = area_mil2 / (1.378 * copper_oz) * 0.0254
    return math.ceil(width_mm * 10 - 1e-9) / 10


# Fixed, by the format or by the original.
FIXED = {
    "J1": Spot(*SLICE_S.bus_pin1(*ORIGIN)),  # slice bus, pins running down the bus edge
    "A1": Spot(142.61, 97.44),  # Arduino Nano, USB over the bottom edge
    # 12 V -> 5 V buck underneath, its heatsink pad on top; the net tie beside it.
    "U1": Spot(128.75, 122.755, 0, True),
    "C1": Spot(128.8, 119.5, 180, True),
    "C2": Spot(131.15, 126.255, 180, True),
    "C3": Spot(133.85, 119.455, 0, True),
    "C4": Spot(133.85, 116.4, 0, True),
    "L1": Spot(133.85, 122.755, 0, True),
    "HS1": Spot(131.8, 121.45),
    "NT1": Spot(128.7, 115.2, 90, True),
    "D1": Spot(173.1, 135.732769),  # status LED
    "J2": Spot(188.75, 119.68, -90),  # encoder 1
    "J3": Spot(188.76, 108.04, -90),  # encoder 2
}
# The original's channel pitch (U2 to U3), 32.05 mm.
BRIDGE_ANCHORS = [(155.570692, 74.2), (155.570692, 42.15)]

LOGO = ("KMLib_Aesthetic:OSHW_Logo_10mm", 136.5, 82.0)
LABEL_AT = (171.0, 115.0)  # right of the Nano, between the bridge and the encoders
# Encoder pins carry their channel: the two terminals are 4 mm apart, no room for a title.
ENCODER_TERMINAL = {1: "{n}A", 2: "{n}B", 3: "5V", 4: "GND"}

MOTOR_NETS = [f"{b['ch']}_{n}" for b in BRIDGES for n in ("VS", "VDC", "OUT1", "OUT2")]
POWER_NETS = ["+12V", "GNDPWR"]
NETCLASSES = [
    # The Slice design constraints: 0.5 mm minimum track, 0.2 mm spacing.
    NetClass("Default", clearance=0.2, track_width=0.5, via_diameter=1.0, via_drill=0.5),
    # A channel's motor current. Clearance per IPC-2221 B2 (outer layer, uncoated)
    # for 31-150 V: VS can be an external supply, up to the LMD18200's 55 V.
    NetClass(
        "Motor",
        clearance=0.6,
        track_width=ipc2221_width(MOTOR_AMPS),
        via_diameter=1.6,
        via_drill=0.8,
    ),  # fmt: skip
    # Both channels' supply and return. The tracks are sized for one channel; the
    # pours on both layers carry the rest.
    NetClass(
        "Power",
        clearance=0.2,
        track_width=ipc2221_width(MOTOR_AMPS),
        via_diameter=1.6,
        via_drill=0.8,
    ),  # fmt: skip
]
MEMBERS = {"Motor": MOTOR_NETS, "Power": POWER_NETS}
DRU_RULES = width_rules(NETCLASSES, minimums=SIGNAL_MINIMUM) + [MOUNTING_HOLE_RULE]

# Pours: (net, layer, priority). Higher priority wins where pours overlap.
POURS = [
    *[(f"{b['ch']}_VDC", "F.Cu", 5) for b in BRIDGES],
    *[(f"{b['ch']}_VS", "F.Cu", 4) for b in BRIDGES],
    ("+12V", "F.Cu", 3),
    ("GND", "B.Cu", 1),
]
POUR_MARGIN = 1.5

# GND vias at HS1, the original's, from HS1's origin: (dx, dy, diameter, drill). Less the
# one at (-5.45, -0.55), where this board's +12V leaves C1: there, it necks +12V for 4 mm.
HS1_VIAS = [
    (-5.55, 1.8, 0.8, 0.4),
    (-5.45, 5.005, 0.8, 0.4),
    (-3.325, 3.45, 0.8, 0.4),
    (-3.1, -4.25, 1.6, 0.8),
    (-1.275, -5.4, 0.8, 0.4),
    (-1.025, -4.075, 0.8, 0.4),
    (-0.65, -0.45, 0.8, 0.4),
    (-0.625, -2.775, 0.8, 0.4),
    (-0.6, 3.25, 0.8, 0.4),
    (1.375, -3.55, 0.8, 0.4),
    (2.05, -0.575, 0.8, 0.4),
    (2.05, 3.3, 0.8, 0.4),
    (2.1, 5.2, 0.8, 0.4),
    (5.075, -5.025, 0.8, 0.4),
    (5.075, -2.125, 0.8, 0.4),
    (5.075, 2.875, 0.8, 0.4),
    (5.075, 5.15, 0.8, 0.4),
    (5.125, 0.47, 0.8, 0.4),
]


def _at(footprint: Node, dx: float, dy: float) -> tuple[float, float]:
    """A point *dx*, *dy* from a placed footprint's origin, in board millimetres."""
    at = find(footprint, "at")
    assert at is not None
    return (round(float(at[1]) + dx, 6), round(float(at[2]) + dy, 6))


def placement() -> dict[str, Spot]:
    """Every footprint's position, by reference."""
    spots = dict(FIXED)
    for b, anchor in zip(BRIDGES, BRIDGE_ANCHORS, strict=True):
        spots |= channel_spots("bridge", b, anchor)
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
    # The bus connector carries both channels' supply and return; a thermal relief
    # there, 3.6 mm from the edge and among the bus tracks, is starved of spokes.
    board, placed = place_board(
        outdir, name, placement(), pad_nets, fields, solid_pads=frozenset({"J1"})
    )
    vias = [Via("GND", via_padstack(d, h), _at(placed["HS1"], dx, dy)) for dx, dy, d, h in HS1_VIAS]
    for b in BRIDGES:
        vias += bridge_vias(placed, b)
    route(board, placed, outdir, name, NETCLASSES, MEMBERS, vias=vias)

    lib_id, x, y = LOGO
    board.footprint(place(libs.footprint_file(lib_id), Placement(lib_id, "LOGO1", "", x, y)))
    # (terminal, pin labels, title or "", silkscreen layer, distance left of the pads).
    terminals = [t for b in BRIDGES for t in bridge_terminals(b)]
    for ref, ch, _, _ in ENCODERS:
        labels = {pin: label.format(n=ch[-1]) for pin, label in ENCODER_TERMINAL.items()}
        terminals.append((ref, labels, "", "F.SilkS", LABEL_DX))
    for ref, labels, title, layer, dx in terminals:
        texts = [(label, pad_xy(placed[ref], str(pin))) for pin, label in labels.items()]
        if title:
            px, py = pad_xy(placed[ref], str(min(labels)))
            texts.append((title, (px, py - 4.6)))  # clear of the bridge's reference text
        for text, (px, py) in texts:
            board.text(text, (px - dx, py), layer=layer, size=0.8, thickness=0.12, angle=90)

    for net, layer, priority in POURS:
        board.zone(net, layer, pour_outline(placed, net, POUR_MARGIN), clearance=0.5,
                   min_thickness=POUR_MIN_WIDTH, priority=priority, solid=True)  # fmt: skip
    for b in BRIDGES:
        bridge_zones(board, placed, b)
    # GNDPWR fills the back. On the front it is only under the bodies: elsewhere it would
    # cover the logic area, where
    # its one connection is a bulk capacitor's pad: the GND/GNDPWR split would not exist.
    x0, y0, x1, y1 = SLICE_S.outline(*ORIGIN)
    edge = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    board.zone("GNDPWR", "B.Cu", edge, clearance=0.5, min_thickness=POUR_MIN_WIDTH)

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
    label = f"Slice_DCMT\nkidl-spike {source}"
    # After the references, nearest its intended spot that is clear of parts and
    # text: its length varies with the source id, so it gives way, not them.
    at = nearest_clear_spot(
        board.items, label, LABEL_AT, SLICE_S.outline(*ORIGIN), size=0.8, thickness=0.12
    )
    board.text(label, at or LABEL_AT, size=0.8, thickness=0.12)
    return board.write(outdir / f"{name}.kicad_pcb")
