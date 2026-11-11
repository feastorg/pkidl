"""What every generated Slice board shares on the physical side.

The board edge and holes come from the format (``common.SLICE_S``), drawn at the
originals' origin so a generated board and its original compare directly. Each
Slice layout supplies its placement, netclasses, pours and labels; this module
places the footprints, adds the holes and routes the board through Freerouting.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from pkidl.board import Board
from pkidl.dsn import Via, Wire
from pkidl.footprint import Placement, place
from pkidl.project import DruRule, NetClass
from pkidl.route import Freerouting
from pkidl.routing import Job, lay, staged
from pkidl.sexpr import Node

from kidl_spike import libs
from kidl_spike.boards.common import SLICE_S, symbols

ORIGIN = (122.6, 39.8)  # top-left corner of the board edge, as on the originals

HOLES = dict(zip(["H1", "H2", "H3", "H4"], SLICE_S.holes(*ORIGIN), strict=True))
HOLE_FOOTPRINT = "MountingHole:MountingHole_5mm"

# Design rules carried over from the original projects, with the board-edge
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

# Signal tracks route at the Default class's 0.5 mm and may neck to 3/4 of it, which the
# router needs to complete them (decided 2026-11-09).
SIGNAL_MINIMUM = {"Default": (0.375, "signals may neck from 0.5 to 0.375 mm (decided 2026-11-09)")}

# The Slice design constraint's 0.5 mm minimum track, as the narrowest a pour may fill.
POUR_MIN_WIDTH = 0.5

MOUNTING_HOLE_RULE = DruRule(
    "mounting hole keepout", "hole_clearance", 2.0, condition="A.memberOfFootprint('H?')",
    why="metal screws and standoffs (decided 2026-11-08): no copper within 2 mm of a hole's "
    "edge, room for a screw head or washer on a 5 mm hole",
)  # fmt: skip


@dataclass(frozen=True)
class Spot:
    x: float
    y: float
    rot: float = 0.0
    back: bool = False

    def at(self, dx: float, dy: float) -> Spot:
        return Spot(round(self.x + dx, 6), round(self.y + dy, 6), self.rot, self.back)


def outline_polygon() -> list[tuple[float, float]]:
    """The rounded-rectangle edge as a polygon whose corner chords lie inside the arcs."""
    x0, y0, x1, y1 = SLICE_S.outline(*ORIGIN)
    r = SLICE_S.corner_r
    pts = []
    for cx, cy, a0 in ((x1 - r, y0 + r, -90), (x1 - r, y1 - r, 0), (x0 + r, y1 - r, 90),
                       (x0 + r, y0 + r, 180)):  # fmt: skip
        for i in range(5):
            a = math.radians(a0 + 22.5 * i)
            pts.append((round(cx + r * math.cos(a), 6), round(cy + r * math.sin(a), 6)))
    return pts


def place_board(
    outdir: Path,
    name: str,
    spots: dict[str, Spot],
    pad_nets: dict[str, dict[str, str]],
    fields: dict[str, dict[str, str]],
    solid_pads: frozenset[str] = frozenset(),
) -> tuple[Board, dict[str, Node]]:
    """A board with the Slice edge, every footprint at its spot, and the holes.

    Footprints link to their symbols in the schematic already in *outdir*. The
    pads of the footprints in *solid_pads* join pours without thermal reliefs.
    """
    links = symbols(outdir / f"{name}.kicad_sch")
    board = Board()
    board.outline_rounded_rect(*SLICE_S.outline(*ORIGIN), SLICE_S.corner_r)
    placed = {}
    for ref, s in sorted(spots.items()):
        link = links[ref]
        lib_id = link.fields["Footprint"]
        p = Placement(
            lib_id, ref, link.fields["Value"], s.x, s.y, s.rot, s.back,
            nets=pad_nets.get(ref, {}), path=link.path, sheetfile=link.sheetfile,
            sheetname=link.sheetname, fields=fields[ref],
            # SKiDL writes every symbol in_bom; parity wants the footprint to agree.
            in_bom=True, solid_pads=ref in solid_pads,
        )  # fmt: skip
        placed[ref] = place(libs.footprint_file(lib_id), p)
        board.footprint(placed[ref])
    for ref, (x, y) in HOLES.items():
        hole = Placement(HOLE_FOOTPRINT, ref, "MountingHole", x, y, board_only=True)
        placed[ref] = place(libs.footprint_file(HOLE_FOOTPRINT), hole)
        board.footprint(placed[ref])
    return board, placed


def route(
    board: Board,
    placed: dict[str, Node],
    outdir: Path,
    name: str,
    netclasses: list[NetClass],
    members: dict[str, list[str]],
    signal_clearances: dict[tuple[str, str], float] | None = None,
    vias: list[Via] | None = None,
    keepouts: list[tuple[str, list[tuple[float, float]]]] | None = None,
    planes: list[tuple[str, str, list[tuple[float, float]]]] | None = None,
    wires: list[Wire] | None = None,
) -> None:
    """Route *board* with Freerouting, in pkidl's stages (``pkidl.routing.staged``), and
    add its tracks and vias.

    The nets of every class but Default (power, motor, mains) are routed first, alone,
    with neck-down off. The rest are then routed around those with neck-down on: signal
    tracks may neck to 3/4 of their width (decided 2026-11-09), kept *signal_clearances*
    (class pairs, mm) from the first stage's copper. *vias* are placed before routing
    and kept: thermal vias under a part, say. *keepouts* (layer, polygon) hold every
    track and via out. *planes* (``pkidl.fill.prefill``) are pours the router connects
    through and every other net keeps out of; a third stage then routes whatever is
    left, crossing signal nets' pours if it must. *wires* are tracks placed before
    routing and kept, as *vias* are: a block's power copper, say. Each ends up on the
    board once. Writes ``<name>-power.dsn``/``.ses``, ``<name>.dsn``/``.ses`` and the
    router's logs into *outdir*.
    """
    job = Job(
        list(placed.values()),
        outline_polygon(),
        netclasses,
        members,
        edge_clearance=float(RULES["min_copper_edge_clearance"]),
        wires=wires or (),
        vias=vias or (),
        class_clearances=signal_clearances,
        keepouts=keepouts or (),
        planes=planes or (),
    )
    lay(board, staged(Freerouting(), job, outdir, name))
