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

from pkidl.dsn import Via, Wire, via_padstack
from pkidl.footprint import pad_xy
from pkidl.sexpr import Node, find, find_all
from shapely.geometry import Polygon, box

from kidl_spike.boards import dcmt_copper as cu
from kidl_spike.boards.block_layout import at_offset
from kidl_spike.boards.common import SLICE_S
from kidl_spike.boards.dcmt import SPEC
from kidl_spike.boards.slice import ORIGIN, Spot
from kidl_spike.boards.slice_build import Authored, Root, dru_rules, hull_pours, netclasses
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


SNAP = 1.0  # mm: a copied track end this near one of this board's pads goes onto it
CORRIDOR_MARGIN = 0.8  # mm either side of a crossing track that pours keep out of


def snap_to_pads(
    p: tuple[float, float], pads: list[tuple[str, tuple[float, float]]], net: str | None = None
) -> tuple[float, float]:
    """*p* moved onto the nearest pad within SNAP (of *net*, if given): (net, centre) pads."""
    near = [(math.dist(p, c), c) for n, c in pads if net is None or n == net]
    d, c = min(near, default=(math.inf, p))
    return (round(c[0], 6), round(c[1], 6)) if d <= SNAP else p


def authored(placed: dict[str, Node], bridges: list[dict]) -> Authored:
    """The original's power copper and signal crossings (``dcmt_copper``): the root's where
    they are, each bridge's at its anchor: the LMD18200, or the terminal the copper is
    bound to.

    This board's footprints and parts sit up to about 0.7 mm from the original's, so a
    copied track or crossing that ends near a pad is moved onto this board's pad: its end
    goes to the nearest pad within SNAP (of the same net, for a track). Ends shared by
    two segments move together, so a copied track stays in one piece.

    The bridge control signals (DIR, BRAKE, PWM, THRM, CSENS) are the original's routes
    too: they cross the pours, and where they go is the designer's choice the corridors
    are made for.

    Some copied power tracks are narrower than their class's 1.4 mm, as the original draws
    them, and KiCad warns (track_width). Each is short and carries little current: the
    0.5 mm GNDPWR joining each bridge's sense resistor and capacitor (pads 1.3 mm wide) to
    the LMD18200's pin 7, and the 0.9-1.0 mm +12V into the buck's 0.5 mm pins. Kept as
    drawn (decided 2026-11-11).
    """
    pads = [(str(n[-1]), pad_xy(fp, str(pad[1])))
            for fp in placed.values() for pad in find_all(fp, "pad")
            if (n := find(pad, "net")) is not None and str(n[-1])]  # fmt: skip

    def snap(p: tuple[float, float], net: str | None = None) -> tuple[float, float]:
        return snap_to_pads(p, pads, net)

    def net(role: str, ch: str) -> str:
        return role if role in ("GNDPWR", "+12V") else f"{ch}_{role}"

    zones = [(n, layers, pri, poly) for n, layers, pri, poly in cu.ROOT_ZONES]
    tracks = [(n, layer, w, a, e) for n, layer, w, a, e in cu.ROOT_TRACKS]
    vias = [Via(n, via_padstack(d, h), at) for n, d, h, at in cu.ROOT_VIAS]
    crossings = list(cu.ROOT_CORRIDORS)
    for b in bridges:
        u, ch = placed[b["U"]], b["ch"]
        at = {"U": placed[b["U"]], "JOUT": placed[b["JOUT"]], "JVDC": placed[b["JVDC"]]}
        zones += [(net(role, ch), layers, pri, _clip([at_offset(at[j], *p) for p in poly]))
                  for role, layers, pri, poly, j in cu.BRIDGE_ZONES]  # fmt: skip
        tracks += [(net(role, ch), layer, w, at_offset(at[j], *a), at_offset(at[j], *e))
                   for role, layer, w, a, e, j in cu.BRIDGE_TRACKS]  # fmt: skip
        crossings += [(layer, w, at_offset(u, *a), at_offset(u, *e))
                      for layer, w, a, e in cu.BRIDGE_CORRIDORS]  # fmt: skip
    ends = [(n, layer, w, snap(a, n), snap(e, n)) for n, layer, w, a, e in tracks]
    # A short stub with both ends near one pad snaps to nothing: it goes.
    ends += [(n, layer, w, snap(a, n), snap(e, n)) for n, layer, w, a, e in cu.SIGNAL_TRACKS]
    wires = [Wire(n, layer, w, [a, e]) for n, layer, w, a, e in ends if a != e]
    vias += [Via(n, via_padstack(d, h), at) for n, d, h, at in cu.SIGNAL_VIAS]
    a, e = GND_TIE
    pin = pad_xy(placed["A1"], "29")
    wires.append(Wire("GND", "F.Cu", GND_TIE_WIDTH, [(round(pin[0], 6), round(pin[1], 6)), a, e]))
    vias.append(Via("GND", via_padstack(*BODY_TIE_VIA), e))
    for b in bridges:  # the body that needs it, tied to the right-edge strip (BODY_TIE)
        if b["ch"] not in BODY_TIE_CHANNELS:
            continue
        a, e = (at_offset(placed[b["U"]], *p) for p in BODY_TIE)
        wires.append(Wire("GNDPWR", "F.Cu", BODY_TIE_WIDTH, [a, e]))
        vias.append(Via("GNDPWR", via_padstack(*BODY_TIE_VIA), e))
    corridors = [(layer, _corridor(snap(a), snap(e), w)) for layer, w, a, e in crossings]
    return Authored(zones=zones, wires=wires, vias=vias, corridors=corridors)


# A deliberate addition (2026-11-11): the first channel's LMD18200 body, its F.Cu GNDPWR
# pour and the B.Cu GNDPWR under it, is closed in by its output pours, so it joins the
# board's GNDPWR only through a pour neck the 0.5 mm minimum drops (the original's too: its
# J4.1 is unconnected when filled at 0.5 mm). A track at the class width from the body's
# F.Cu pour to the right edge, then a via into the B.Cu strip kept there, ties it. The
# second channel's body joins through U3.7 and needs none (its tie would pass hole H3's
# keepout). From the LMD18200's origin: 7.9 mm down clears the output terminal's first pin
# by 0.7 mm (Motor wants 0.6), the tab's hole by 2.2 mm and the edge by 0.6 mm.
BODY_TIE = ((25.9, 7.9), (35.73, 7.9))
BODY_TIE_WIDTH = 1.4  # the Power and Motor class width
BODY_TIE_VIA = (0.8, 0.4)
BODY_TIE_CHANNELS = ("CH1",)

# Also deliberate (2026-11-11): the Nano's pin 29 reaches no GND fill, so a F.Cu track
# from the pin, bending at the first point, ends in a via into the GND between the encoder
# crossings, which the right-edge GND joins to the rest. The line crosses no F.Cu copper.
# The bend had a via too, into the B.Cu GND around the pin; that fill stops 0.85 mm short
# of it, so it joined nothing (KiCad: via_dangling) and is gone.
GND_TIE = ((160.5, 104.5), (182.0, 114.0))
GND_TIE_WIDTH = 0.5

# A deliberate change from the original (2026-11-11): its output and supply pours run to
# within 1.5 mm of the right edge, leaving GNDPWR on B.Cu a strip about 0.5 mm wide there,
# which the 0.5 mm pour minimum drops, splitting GNDPWR. Stopping the bridge pours here
# leaves it at least 1 mm. The terminal pins end at x 189.9.
BRIDGE_POUR_X_MAX = 190.6


def _clip(poly: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """*poly* cut at BRIDGE_POUR_X_MAX."""
    cut = Polygon(poly).intersection(box(-1e6, -1e6, BRIDGE_POUR_X_MAX, 1e6))
    assert isinstance(cut, Polygon), "a bridge pour split by the cut"
    return [(round(x, 4), round(y, 4)) for x, y in cut.exterior.coords[:-1]]


def _corridor(
    a: tuple[float, float], b: tuple[float, float], w: float
) -> list[tuple[float, float]]:
    """The rectangle around a track from *a* to *b*, *w* wide, CORRIDOR_MARGIN either side."""
    h = w / 2 + CORRIDOR_MARGIN
    length = math.dist(a, b) or 1.0
    ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
    nx, ny = -uy * h, ux * h
    a2, b2 = (a[0] - ux * h, a[1] - uy * h), (b[0] + ux * h, b[1] + uy * h)
    return [(round(x, 4), round(y, 4)) for x, y in
            ((a2[0] + nx, a2[1] + ny), (b2[0] + nx, b2[1] + ny),
             (b2[0] - nx, b2[1] - ny), (a2[0] - nx, a2[1] - ny))]  # fmt: skip


ROOT = Root(fixed=FIXED, hs1_vias=HS1_VIAS, logo=LOGO, label_at=LABEL_AT, label_sep="\n",
            solid_pads=frozenset({"J1"}), pours=hull_pours(POUR_MARGIN),
            # With the authored copper, these pads' thermal reliefs are starved (the Nano's
            # GND pins, the bootstrap capacitors' output pins, the switches' +12V pins):
            # they join their pours solidly, as RLHT's Nano does.
            authored_solid_pads=frozenset({"A1", "C9", "C14", "S1", "S2"}),
            authored=authored)  # fmt: skip
NETCLASSES, MEMBERS = netclasses(SPEC)
DRU_RULES = dru_rules(SPEC)
__all__ = ["SLICE_S", "ORIGIN"]


def build_pcb(outdir: Path, name: str, pad_nets: dict, fields: dict, source: str) -> Path:
    """Write the routed board, project, rules and lib tables (``slice_build.build_pcb``)."""
    return _build_pcb(SPEC, outdir, name, pad_nets, fields, source)
