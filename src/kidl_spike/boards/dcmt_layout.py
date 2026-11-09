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

from pathlib import Path

from kidl_spike.boards.common import SLICE_S
from kidl_spike.boards.dcmt import SPEC
from kidl_spike.boards.slice import ORIGIN, Spot
from kidl_spike.boards.slice_build import Root, dru_rules, hull_pours, netclasses
from kidl_spike.boards.slice_build import build_pcb as _build_pcb

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
}
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
POUR_MARGIN = 1.5
LOGO = (136.5, 82.0)
LABEL_AT = (171.0, 115.0)  # right of the Nano, between the bridge and the encoders
# The bus connector carries both channels' supply and return; a thermal relief there,
# 3.6 mm from the edge and among the bus tracks, is starved of spokes.
ROOT = Root(fixed=FIXED, hs1_vias=HS1_VIAS, logo=LOGO, label_at=LABEL_AT, label_sep="\n",
            solid_pads=frozenset({"J1"}), pours=hull_pours(POUR_MARGIN))  # fmt: skip
NETCLASSES, MEMBERS = netclasses(SPEC)
DRU_RULES = dru_rules(SPEC)
__all__ = ["SLICE_S", "ORIGIN"]


def build_pcb(outdir: Path, name: str, pad_nets: dict, fields: dict, source: str) -> Path:
    """Write the routed board, project, rules and lib tables (``slice_build.build_pcb``)."""
    return _build_pcb(SPEC, outdir, name, pad_nets, fields, source)
