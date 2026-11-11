"""Each Slice block's layout: its parts relative to an anchor, and what it adds to the
board (pours, thermal vias, terminal labels). A board places a block by giving each
channel an anchor; the block's parts follow, so a block placed twice repeats exactly.
"""

from __future__ import annotations

import math

from pkidl.board import Board
from pkidl.dsn import Via, via_padstack
from pkidl.footprint import pad_xy
from pkidl.project import DruRule, NetClass
from pkidl.sexpr import Node, find
from pkidl.silk import nearest_clear_spot, silk_box, text_box

from kidl_spike.boards.slice import POUR_MIN_WIDTH, Spot

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

# Each channel's LMD18200 lies flat, its metal back at ground, and sheds heat into GNDPWR
# on both layers through a via field, as the original's first channel does. Board
# millimetres from the LMD18200's origin (U2 at 155.570692, 74.2 on both boards; the
# channels are rotated alike, so these translate):
# - GNDPWR on F.Cu under the body, above every other pour;
BODY_GNDPWR = [
    (11.93, -0.016),
    (12.791, -0.9),
    (24.55, -0.9),
    (25.932, 0.417),
    (25.92, 17.579),
    (24.791, 18.68),
    (13.474, 18.68),
    (11.93, 17.126),
]
# - the original's vias: a 9 x 8 grid at 1.2 mm less 8 points (some at the tab hole), and
#   less its bottom row here: this board's output terminal pin sits 1.4 mm below it, and
#   a full-width OUT2 track does not pass at the Motor clearance. 56 vias of the 64;
THERMAL_VIA = (0.6, 0.4)
THERMAL_SKIP = {(7, 3), (7, 4), (8, 0), (8, 2), (8, 3), (8, 4), (8, 5), (8, 7)}
THERMAL_VIAS = [
    (round(12.479 + 1.2 * i, 3), round(4.31 + 1.2 * j, 3))
    for i in range(9)
    for j in range(7)
    if (i, j) not in THERMAL_SKIP
]
# - on B.Cu, the outputs run as strips beside the field, the original's, extended to this
#   board's output terminal (moved into the right-edge column); GNDPWR fills between.
OUT_STRIPS = [
    (
        "OUT1",
        3,
        [(2.65, -0.9), (35.5, -0.9), (35.5, 12.3), (30.03, 12.3), (30.03, 3.4), (2.65, 3.4)],
    ),
    # Past the field, only as deep as the terminal pin: J4 below needs its GNDPWR.
    (
        "OUT2",
        2,
        [(2.5, 13.6), (35.5, 13.6), (35.5, 15.9), (30.03, 15.9), (30.03, 18.1), (2.5, 18.1)],
    ),
]

# Terminal labels run along each terminal, this far left of its pads: between the
# terminal's outline and the bulk capacitor's, a gap about 2.5 mm wide.
LABEL_DX = 5.4

# Terminal labels, by pin, beside each terminal.
OUT_TERMINAL = {1: "OUT1", 2: "OUT2"}
VDC_TERMINAL = {1: "GND", 2: "VDC"}

LABEL_GAP = 0.4  # terminal label to the terminal's outline
# Terminal labels, by pin.
RELAY_TERMINAL = {1: "LINE", 2: "ESTOP", 3: "GND", 4: "ESTOP", 5: "NO", 6: "NC"}
TC_TERMINAL = {1: "T-", 2: "T+"}


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


# What each block kind brings to the board's rules.
# - A relay switches mains: its lines are the HV Relay class, full width, kept from
#   everything else by the mains rules.
HV_RELAY = NetClass("HV Relay", clearance=1.25, track_width=3.0, via_diameter=1.6, via_drill=0.8)
HV_SIGNALS = ("COM", "NO", "NC", "LINE", "ESTOP")
# - A bridge carries a motor channel's current: its supply and outputs are the Motor
#   class. Clearance per IPC-2221 B2 (outer layer, uncoated) for 31-150 V: VS can be an
#   external supply, up to the LMD18200's 55 V.
MOTOR = NetClass("Motor", clearance=0.6, track_width=ipc2221_width(MOTOR_AMPS),
                 via_diameter=1.6, via_drill=0.8)  # fmt: skip
MOTOR_SIGNALS = ("VS", "VDC", "OUT1", "OUT2")
# - A board's supply and return (its power_nets): sized for one motor channel; the
#   pours on both layers carry the rest.
POWER = NetClass("Power", clearance=0.2, track_width=ipc2221_width(MOTOR_AMPS),
                 via_diameter=1.6, via_drill=0.8)  # fmt: skip

# Encoder pins carry their channel: the two terminals are 4 mm apart, no room for a title.
ENCODER_TERMINAL = {1: "{n}A", 2: "{n}B", 3: "5V", 4: "GND"}
# Encoder block: just its terminal, turned to face the edge.
ENCODER_BLOCK = {"J": Spot(0, 0, -90)}

BLOCK_SPOTS = {"relay": RELAY_BLOCK, "thermocouple": TC_BLOCK, "bridge": BRIDGE_BLOCK,
               "encoder": ENCODER_BLOCK}  # fmt: skip


def channel_spots(kind: str, params: dict, anchor: tuple[float, float]) -> dict[str, Spot]:
    """The positions of a channel's parts, by reference, its block placed at *anchor*."""
    ax, ay = anchor
    return {params[role]: spot.at(ax, ay) for role, spot in BLOCK_SPOTS[kind].items()}


def at_offset(footprint: Node, dx: float, dy: float) -> tuple[float, float]:
    """A point *dx*, *dy* from a placed footprint's origin, in board millimetres."""
    at = find(footprint, "at")
    assert at is not None
    return (round(float(at[1]) + dx, 6), round(float(at[2]) + dy, 6))


def bridge_vias(placed: dict[str, Node], b: dict) -> list[Via]:
    """A bridge's thermal via field, under its LMD18200."""
    return [Via("GNDPWR", via_padstack(*THERMAL_VIA), at_offset(placed[b["U"]], dx, dy))
            for dx, dy in THERMAL_VIAS]  # fmt: skip


def bridge_zones(board: Board, placed: dict[str, Node], b: dict) -> None:
    """A bridge's GNDPWR under its body (F.Cu) and its output strips (B.Cu)."""
    u = placed[b["U"]]
    board.zone("GNDPWR", "F.Cu", [at_offset(u, *p) for p in BODY_GNDPWR], clearance=0.5,
               min_thickness=POUR_MIN_WIDTH, priority=6, solid=True)  # fmt: skip
    for out, priority, outline in OUT_STRIPS:
        board.zone(f"{b['ch']}_{out}", "B.Cu", [at_offset(u, *p) for p in outline], clearance=0.5,
                   min_thickness=POUR_MIN_WIDTH, priority=priority, solid=True)  # fmt: skip


def bridge_terminals(b: dict) -> list[tuple[str, dict[int, str], str, str, float]]:
    """A bridge's terminal labels: (terminal, pin labels, title or "", silk layer,
    distance left of the pads). The supply terminal's go underneath: on top, the bulk
    capacitor's outline leaves 0.7 mm, and underneath, the 1 uF capacitor's pad sits
    1.2 mm further left."""
    return [(b["JOUT"], OUT_TERMINAL, b["ch"], "F.SilkS", LABEL_DX),
            (b["JVDC"], VDC_TERMINAL, "", "B.SilkS", LABEL_DX - 1.2)]  # fmt: skip


def label_terminal(
    board: Board, placed: dict[str, Node], c: dict, labels: dict[int, str], outline_box: tuple
) -> None:
    """A relay or thermocouple terminal's pin labels, left of its silkscreen outline, and
    its channel title at the nearest clear spot above them."""
    outline = silk_box(placed[c["J"]])
    assert outline is not None
    for pin, label in labels.items():
        _, py = pad_xy(placed[c["J"]], str(pin))
        half = text_box(label, (0, 0), 1.0, 0.15, 0)[2]
        board.text(label, (outline[0] - LABEL_GAP - half, py), size=1.0, thickness=0.15)
    _, py = pad_xy(placed[c["J"]], str(max(labels)))
    half = text_box(c["ch"], (0, 0), 1.2, 0.2, 0)[2]
    want = (outline[0] - LABEL_GAP - half, py - 3.0)
    # The title need not line up with a pin: the nearest clear spot to it.
    at = nearest_clear_spot(board.items, c["ch"], want, outline_box, size=1.2, thickness=0.2)
    board.text(c["ch"], at or want, size=1.2, thickness=0.2)


def encoder_terminals(e: dict) -> list[tuple[str, dict[int, str], str, str, float]]:
    """An encoder terminal's pin labels, as ``bridge_terminals``: they carry the channel."""
    labels = {pin: label.format(n=e["ch"][-1]) for pin, label in ENCODER_TERMINAL.items()}
    return [(e["J"], labels, "", "F.SilkS", LABEL_DX)]


def terminal_labels(
    board: Board,
    placed: dict[str, Node],
    entries: list[tuple[str, dict[int, str], str, str, float]],
) -> None:
    """Pin labels along each terminal, *dx* left of its pads, turned along it; a title, if
    any, above the first pin, clear of the bridge's reference text."""
    for ref, labels, title, layer, dx in entries:
        texts = [(label, pad_xy(placed[ref], str(pin))) for pin, label in labels.items()]
        if title:
            px, py = pad_xy(placed[ref], str(min(labels)))
            texts.append((title, (px, py - 4.6)))
        for text, (px, py) in texts:
            board.text(text, (px - dx, py), layer=layer, size=0.8, thickness=0.12, angle=90)


# A thermocouple front end's regions, from the converter (all its parts are on F.Cu):
# - no track or via on B.Cu under its inputs, from the converter's input pins to the
#   terminal: a signal there (a bridge's current sense, say) couples into microvolts;
# - GND on B.Cu over the whole block, above a power-ground pour: on a board whose bus
#   ground carries motor current, the front end still sits on logic ground.
TC_INPUT_KEEPOUT = (3.5, -2.6, 26.0, 2.9)  # x0, y0, x1, y1
TC_GROUND = (-8.5, -3.4, 28.5, 3.4)  # under 7 mm, the closest channel pitch: regions never touch


def thermocouple_region(t: dict, anchor: tuple[float, float], box: tuple) -> list[tuple]:
    """One of a thermocouple channel's regions, *box* from its converter, as a polygon."""
    ax, ay = anchor
    x0, y0, x1, y1 = box
    return [
        (round(ax + x, 6), round(ay + y, 6)) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
    ]
