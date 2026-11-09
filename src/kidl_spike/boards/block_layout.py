"""Each Slice block's layout: its parts relative to an anchor, and what it adds to the
board (pours, thermal vias, terminal labels). A board places a block by giving each
channel an anchor; the block's parts follow, so a block placed twice repeats exactly.
"""

from __future__ import annotations

from kidl_spike.boards.slice import POUR_MIN_WIDTH, Spot
from pkidl.board import Board
from pkidl.dsn import Via, via_padstack
from pkidl.footprint import pad_xy
from pkidl.sexpr import Node, find
from pkidl.silk import nearest_clear_spot, silk_box, text_box

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


BLOCK_SPOTS = {"relay": RELAY_BLOCK, "thermocouple": TC_BLOCK, "bridge": BRIDGE_BLOCK}


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
