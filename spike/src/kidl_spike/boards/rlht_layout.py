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

from pathlib import Path

from kidl_spike.boards.block_layout import MAINS_LV_CREEPAGE
from kidl_spike.boards.common import SLICE_S
from kidl_spike.boards.rlht import SPEC
from kidl_spike.boards.slice import ORIGIN, Spot
from kidl_spike.boards.slice_build import (
    STITCH_VIA,
    Root,
    dru_rules,
    ground_both_layers,
    netclasses,
)
from kidl_spike.boards.slice_build import build_pcb as _build_pcb

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
# GND vias at HS1, the original's, from HS1's origin: (dx, dy, diameter, drill).
HS1_VIAS = [
    (-5.2, 1.85, 0.8, 0.4), (-5.0, 5.1, 0.8, 0.4), (-2.6, 2.3, 0.5, 0.3), (-1.5, -0.4, 0.5, 0.3),
    (-1.4, -5.15, 0.8, 0.4), (-1.3, -3.4, 0.5, 0.3), (-0.6, -0.4, 0.5, 0.3), (-0.2, -2.6, 0.5, 0.3),
    (-0.2, -1.3, 0.5, 0.3), (1.0, -3.4, 0.5, 0.3), (5.5, -3.45, 0.8, 0.4), (5.5, -0.55, 0.8, 0.4),
    (5.5, 4.45, 0.8, 0.4),
]  # fmt: skip

# The Nano's GND pins join the GND pours directly: routing beside them can leave a thermal
# relief one spoke short of the two the rules require.
ROOT = Root(fixed=FIXED, hs1_vias=HS1_VIAS, logo=(136.5, 83.0), label_at=(161.0, 136.6),
            label_sep=" | ", solid_pads=frozenset({"A1"}), pours=ground_both_layers)  # fmt: skip
NETCLASSES, MEMBERS = netclasses(SPEC)
DRU_RULES = dru_rules(SPEC)
__all__ = ["MAINS_LV_CREEPAGE", "STITCH_VIA", "SLICE_S", "ORIGIN"]


def build_pcb(outdir: Path, name: str, pad_nets: dict, fields: dict, source: str) -> Path:
    """Write the routed board, project, rules and lib tables (``slice_build.build_pcb``)."""
    return _build_pcb(SPEC, outdir, name, pad_nets, fields, source)
