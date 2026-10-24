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

from dataclasses import dataclass
from pathlib import Path

from kidl_spike import libs
from kidl_spike.boards.common import SLICE_S, symbols
from kidl_spike.boards.rlht import RELAYS, THERMOCOUPLES
from pkidl.board import Board
from pkidl.dsn import read_ses, write_dsn
from pkidl.footprint import Placement, pad_xy, place
from pkidl.project import PARITY_ERRORS, NetClass, write_project
from pkidl.route import freerouting

ORIGIN = (122.6, 39.8)  # top-left corner of the board edge


@dataclass(frozen=True)
class Spot:
    x: float
    y: float
    rot: float = 0.0
    back: bool = False

    def at(self, dx: float, dy: float) -> Spot:
        return Spot(round(self.x + dx, 6), round(self.y + dy, 6), self.rot, self.back)


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
HOLES = dict(zip(["H1", "H2", "H3", "H4"], SLICE_S.holes(*ORIGIN), strict=True))
HOLE_FOOTPRINT = "MountingHole:MountingHole_5mm"

# Relay block, relative to the relay. The original's first channel, with the
# terminal 3.7 mm closer, so the second channel's relay clears the Nano, and the
# opto and its resistor underneath moved left, between the Nano's pin rows.
RELAY_BLOCK = {
    "K": Spot(0, 0),
    "D": Spot(-4.025, -7.61, -90),
    "R": Spot(-8.5, 5.6, 0, True),
    "U": Spot(-8.5, 2.6, 180, True),
    "F": Spot(16.175, -13.2, 180),
    "J": Spot(32.875, 16.2, 90),
}
# The 6-way terminals sit where the original puts them, 31.89 mm apart (each is
# 31.48 long); the top one as high as the top-right hole's courtyard allows.
RELAY_ANCHORS = [(153.725, 62.9), (153.725, 94.79)]

# Thermocouple block, relative to the converter. Its pins 1-4 (GND, T-, T+, VCC)
# face the filter and the terminal; 5-7 (SCK, CS, SO) face the Nano.
TC_BLOCK = {
    "U": Spot(0, 0, 180),
    "C": Spot(5.25, 0, -90),
    "FBP": Spot(9.05, -1.3),
    "FBN": Spot(9.05, 1.39),
    "RCLK": Spot(-6.4, -1.35),
    "RSS": Spot(-6.4, 1.35),
    "J": Spot(24.89, 1.27, 90),
}
TC_ANCHORS = [(163.68, 125.0), (163.68, 118.0)]  # 7 mm apart: the 2-way terminal is 6.54

LOGO = ("KMLib_Aesthetic:OSHW_Logo_10mm", 136.5, 83.0)
LABEL_AT = (161.0, 136.6)

# Terminal labels, by pin, beside each terminal.
RELAY_TERMINAL = {1: "LINE", 2: "ESTOP", 3: "GND", 4: "ESTOP", 5: "NO", 6: "NC"}
TC_TERMINAL = {1: "T-", 2: "T+"}

HV_NETS = [f"{r['ch']}_{n}" for r in RELAYS for n in ("COM", "NO", "NC", "LINE", "ESTOP")]
NETCLASSES = [
    # The Slice design constraints: 0.5 mm minimum track, 0.2 mm spacing.
    NetClass("Default", clearance=0.2, track_width=0.5, via_diameter=1.0, via_drill=0.5),
    # The relay-switched heater lines, from the original's HV Relay class.
    NetClass("HV Relay", clearance=1.25, track_width=3.0, via_diameter=1.6, via_drill=0.8),
]
MEMBERS = {"HV Relay": HV_NETS}

# Design rules carried over from the original project, with the board-edge
# clearance the Loaf uses for its pours.
RULES: dict[str, float | bool] = {
    "allow_blind_buried_vias": False,
    "allow_microvias": False,
    "max_error": 0.005,
    "min_clearance": 0.1,
    "min_connection": 0.0,
    "min_copper_edge_clearance": 0.5,
    "min_hole_clearance": 0.25,
    "min_hole_to_hole": 0.25,
    "min_resolved_spokes": 2,
    "min_silk_clearance": 0.0,
    "min_text_height": 0.8,
    "min_text_thickness": 0.08,
    "min_through_hole_diameter": 0.3,
    "min_track_width": 0.2,
    "min_via_annular_width": 0.05,
    "min_via_diameter": 0.4,
}


def placement() -> dict[str, Spot]:
    """Every footprint's position, by reference."""
    spots = dict(FIXED)
    for r, (ax, ay) in zip(RELAYS, RELAY_ANCHORS, strict=True):
        for role, spot in RELAY_BLOCK.items():
            spots[r[role]] = spot.at(ax, ay)
    for t, (ax, ay) in zip(THERMOCOUPLES, TC_ANCHORS, strict=True):
        for role, spot in TC_BLOCK.items():
            spots[t[role]] = spot.at(ax, ay)
    return spots


def _outline_polygon(
    x0: float, y0: float, x1: float, y1: float, r: float
) -> list[tuple[float, float]]:
    """The rounded-rectangle edge as a polygon whose corner chords lie inside the arcs."""
    import math

    pts = []
    for cx, cy, a0 in ((x1 - r, y0 + r, -90), (x1 - r, y1 - r, 0), (x0 + r, y1 - r, 90),
                       (x0 + r, y0 + r, 180)):  # fmt: skip
        for i in range(5):
            a = math.radians(a0 + 22.5 * i)
            pts.append((round(cx + r * math.cos(a), 6), round(cy + r * math.sin(a), 6)))
    return pts


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
    links = symbols(outdir / f"{name}.kicad_sch")
    board = Board()
    outline = SLICE_S.outline(*ORIGIN)
    board.outline_rounded_rect(*outline, SLICE_S.corner_r)

    placed = {}
    for ref, s in sorted(placement().items()):
        link = links[ref]
        lib_id = link.fields["Footprint"]
        p = Placement(
            lib_id, ref, link.fields["Value"], s.x, s.y, s.rot, s.back,
            nets=pad_nets.get(ref, {}), path=link.path, sheetfile=link.sheetfile,
            sheetname=link.sheetname, fields=fields[ref],
        )  # fmt: skip
        placed[ref] = place(libs.footprint_file(lib_id), p)
        board.footprint(placed[ref])
    for ref, (x, y) in HOLES.items():
        hole = Placement(HOLE_FOOTPRINT, ref, "MountingHole", x, y, board_only=True)
        placed[ref] = place(libs.footprint_file(HOLE_FOOTPRINT), hole)
        board.footprint(placed[ref])

    dsn = write_dsn(
        outdir / f"{name}.dsn", list(placed.values()),
        _outline_polygon(*outline, SLICE_S.corner_r), NETCLASSES, MEMBERS,
        edge_clearance=float(RULES["min_copper_edge_clearance"]),
    )  # fmt: skip
    ses = freerouting(dsn, outdir / f"{name}.ses", log=outdir / "freerouting.log")
    wires, vias = read_ses(ses)
    via_size = {f"Via[0-1]_{round(c.via_diameter * 1000)}:{round(c.via_drill * 1000)}_um":
                (c.via_diameter, c.via_drill) for c in NETCLASSES}  # fmt: skip
    for w in wires:
        for a, b in zip(w.points, w.points[1:], strict=False):
            board.track(a, b, w.width, w.net, w.layer)
    for v in vias:
        size, drill = via_size[v.padstack]
        board.via(v.at, size, drill, v.net)

    lib_id, x, y = LOGO
    board.footprint(place(libs.footprint_file(lib_id), Placement(lib_id, "LOGO1", "", x, y)))
    for chans, labels in ((RELAYS, RELAY_TERMINAL), (THERMOCOUPLES, TC_TERMINAL)):
        for c in chans:
            for pin, label in labels.items():
                px, py = pad_xy(placed[c["J"]], str(pin))
                board.text(label, (px - 6.5, py), size=1.0, thickness=0.15)
            px, py = pad_xy(placed[c["J"]], str(max(labels)))
            board.text(c["ch"], (px - 6.5, py - 3.0), size=1.2, thickness=0.2)

    x0, y0, x1, y1 = outline
    edge = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    for layer in ("F.Cu", "B.Cu"):
        board.zone("GND", layer, edge, clearance=0.5)
    board.text(f"Slice_RLHT | kidl-spike {source}", LABEL_AT, size=0.8, thickness=0.12)

    libs.write_project_lib_tables(outdir)
    write_project(
        outdir / f"{name}.kicad_pro",
        netclasses=NETCLASSES,
        members=MEMBERS,
        rules=RULES,
        severities=PARITY_ERRORS,
    )
    return board.write(outdir / f"{name}.kicad_pcb")
