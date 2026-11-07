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
from kidl_spike.boards.common import SLICE_S
from kidl_spike.boards.dcmt import BRIDGES, ENCODERS
from kidl_spike.boards.slice import ORIGIN, RULES, Spot, place_board, pour_outline, route
from pkidl.footprint import Placement, pad_xy, place
from pkidl.project import PARITY_ERRORS, NetClass, write_project

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
# H-bridge block, relative to the bridge. The original's first channel, with the
# output and supply terminals stacked in the right-edge column.
BRIDGE_BLOCK = {
    "U": Spot(0, 0, -90),
    "CBULK": Spot(21.1, 22.45, -45),
    "CVS": Spot(25.25, 21.75, -45, True),
    "CSNS": Spot(-2.720692, 10.2875, 90),
    "CB1": Spot(2.1875, 1.7, 180, True),
    "CB2": Spot(1.65, 15.3, 0, True),
    "R": Spot(-5.251384, 10.3, 90),
    "S": Spot(6.1, 23.6, 90),
    "JOUT": Spot(33.0, 10.6, -90),
    "JVDC": Spot(33.0, 19.5, -90),
}
# The original's channel pitch (U2 to U3), 32.05 mm.
BRIDGE_ANCHORS = [(155.570692, 74.2), (155.570692, 42.15)]

LOGO = ("KMLib_Aesthetic:OSHW_Logo_10mm", 136.5, 82.0)
LABEL_AT = (171.0, 115.0)  # right of the Nano, between the bridge and the encoders
# Terminal labels run along each terminal, this far left of its pads: between the
# terminal's outline and the bulk capacitor's, a gap about 2.5 mm wide.
LABEL_DX = 5.4

# Terminal labels, by pin, beside each terminal.
OUT_TERMINAL = {1: "OUT1", 2: "OUT2"}
VDC_TERMINAL = {1: "GND", 2: "VDC"}
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

# Pours: (net, layer, priority). Higher priority wins where pours overlap.
POURS = [
    *[(f"{b['ch']}_VDC", "F.Cu", 5) for b in BRIDGES],
    *[(f"{b['ch']}_VS", "F.Cu", 4) for b in BRIDGES],
    ("+12V", "F.Cu", 3),
    *[(f"{b['ch']}_OUT1", "B.Cu", 3) for b in BRIDGES],
    *[(f"{b['ch']}_OUT2", "B.Cu", 2) for b in BRIDGES],
    ("GND", "B.Cu", 1),
]
POUR_MARGIN = 1.5


def placement() -> dict[str, Spot]:
    """Every footprint's position, by reference."""
    spots = dict(FIXED)
    for b, (ax, ay) in zip(BRIDGES, BRIDGE_ANCHORS, strict=True):
        for role, spot in BRIDGE_BLOCK.items():
            spots[b[role]] = spot.at(ax, ay)
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
    route(board, placed, outdir, name, NETCLASSES, MEMBERS)

    lib_id, x, y = LOGO
    board.footprint(place(libs.footprint_file(lib_id), Placement(lib_id, "LOGO1", "", x, y)))
    # (terminal, pin labels, title or "", silkscreen layer, distance left of the pads).
    # The supply terminal's labels go underneath: on top, the bulk capacitor's outline
    # leaves 0.7 mm, and underneath, the 1 uF capacitor's pad sits 1.2 mm further left.
    terminals = []
    for b in BRIDGES:
        terminals.append((b["JOUT"], OUT_TERMINAL, b["ch"], "F.SilkS", LABEL_DX))
        terminals.append((b["JVDC"], VDC_TERMINAL, "", "B.SilkS", LABEL_DX - 1.2))
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
                   priority=priority, solid=True)  # fmt: skip
    x0, y0, x1, y1 = SLICE_S.outline(*ORIGIN)
    edge = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    for layer in ("F.Cu", "B.Cu"):
        board.zone("GNDPWR", layer, edge, clearance=0.5)
    board.text(f"Slice_DCMT\nkidl-spike {source}", LABEL_AT, size=0.8, thickness=0.12)

    libs.write_project_lib_tables(outdir)
    write_project(
        outdir / f"{name}.kicad_pro",
        netclasses=NETCLASSES,
        members=MEMBERS,
        rules=RULES,
        severities=PARITY_ERRORS,
    )
    return board.write(outdir / f"{name}.kicad_pcb")
