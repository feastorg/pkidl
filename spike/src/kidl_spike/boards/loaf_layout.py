"""Physical layer of Loaf_x004: a fixed mechanical interface, a generated layout.

The mechanical interface does not move. Slices plug into J3–J6 and Loafs chain
through J2/J7, so the outline and those positions are taken from the hand-drawn
board (feastorg/Loaf_x004@ebf47df, hardware/BREAD_Loaf.kicad_pcb). Everything
else is generated:

- the five bus signals run as straight tracks from J2 to J7, through the
  matching pin of every slice connector (all six share the same pin rows);
- GND is a pour over the whole of B.Cu;
- +12V is a pour over F.Cu. The signal tracks split it into a band above the bus
  (pin 2s) and one below (pin 9s and the jack); the two join around the ends of
  the bus, left of J2 and right of J7.
"""

from __future__ import annotations

from pathlib import Path

from pkidl.board import Board
from pkidl.footprint import Placement, pad_xy, place
from pkidl.project import (
    PARITY_ERRORS,
    SILK_ERRORS,
    DruRule,
    NetClass,
    width_rules,
    write_project,
    write_rules,
)
from pkidl.silk import nearest_clear_spot, place_references, silk_box, text_box

from kidl_spike import libs
from kidl_spike.boards.common import symbols
from kidl_spike.boards.spec import load_loaf

# The interface, from loaf.yaml: edge, corner radius, connectors as
# reference -> (x, y, rotation, on the back), and the logo and label spots.
SPEC = load_loaf()
OUTLINE = SPEC.outline
CORNER_RADIUS = SPEC.corner_radius
PLACEMENT = SPEC.interface
LOGO = ("KMLib_Aesthetic:OSHW_Logo_10mm", *SPEC.logo)
LABEL_AT = SPEC.label_at
# Every bus connector's pins are labelled, as on the original, by these short names.
PIN_LABEL = {"GND": "GND", "+12V": "12V", "SCL_5V": "SCL", "SDA_5V": "SDA",
             "E_STOP_5V": "ESTOP", "INT_5V": "INT", "SYNC_5V": "SYNC"}  # fmt: skip
BUS_CONNECTORS = ["J2", "J3", "J4", "J5", "J6", "J7"]
PIN_LABEL_GAP = 0.4  # pin label to the connector's outline
LABEL_EDGE = 0.5  # pin label to the board edge, at least
# J7, 3.7 mm right of J6, has no room on its left: the original's small diagonal labels
# right of each pin, (dx, dy, size, angle) from the pad.
PIN_LABEL_RIGHT = {"J7": (2.0, 0.2, 0.6, -45.0)}
# Slot titles, where the original puts them: from each slice connector's origin.
SLOT_TITLE = (-11.8, -19.5)

SIGNALS = ["SCL_5V", "SDA_5V", "E_STOP_5V", "INT_5V", "SYNC_5V"]
BUS_NETS = ["+12V", "GND", *SIGNALS]

NETCLASSES = [
    NetClass("Default", clearance=0.2, track_width=0.25),
    NetClass("BREAD", clearance=0.2, track_width=0.4),
]
# The slice connectors' 3.3 mm holes take metal hardware (decided 2026-11-08). The
# barrel jack's own non-plated pegs are left out.
DRU_RULES = width_rules(NETCLASSES) + [
    DruRule(
        "mounting hole keepout",
        "hole_clearance",
        2.0,
        condition="A.Pad_Type == 'NPTH, mechanical' && (A.memberOfFootprint('J3') || "
        "A.memberOfFootprint('J4') || A.memberOfFootprint('J5') || A.memberOfFootprint('J6'))",
        why="metal screws and standoffs: no copper within 2 mm of a hole's edge",
    )  # fmt: skip
]

# Design rules carried over from the original project, plus a board-edge
# clearance for the pours.
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


def build_pcb(
    outdir: Path,
    name: str,
    pad_nets: dict[str, dict[str, str]],
    fields: dict[str, dict[str, str]],
    source: str,
) -> Path:
    """Write ``<name>.kicad_pcb``, ``<name>.kicad_pro`` and lib tables into *outdir*.

    From the circuit: *pad_nets* (reference -> pad number -> net) and *fields*
    (reference -> symbol fields KiCad copies onto the footprint, which parity
    compares). The schematic already in *outdir* supplies the symbol links and
    values.
    """
    links = symbols(outdir / f"{name}.kicad_sch")
    board = Board()
    board.outline_rounded_rect(*OUTLINE, CORNER_RADIUS)

    placed = {}
    for ref, (x, y, rot, back) in sorted(PLACEMENT.items()):
        link = links[ref]
        lib_id = link.fields["Footprint"]
        p = Placement(
            lib_id, ref, link.fields["Value"], x, y, rot, back,
            nets=pad_nets[ref], path=link.path, sheetfile=link.sheetfile,
            sheetname=link.sheetname, fields=fields[ref],
        )  # fmt: skip
        placed[ref] = place(libs.footprint_file(lib_id), p)
        board.footprint(placed[ref])

    lib_id, x, y = LOGO
    board.footprint(place(libs.footprint_file(lib_id), Placement(lib_id, "LOGO1", "", x, y)))

    pin = {net: n for n, net in pad_nets["J2"].items()}
    for net in SIGNALS:
        board.track(pad_xy(placed["J2"], pin[net]), pad_xy(placed["J7"], pin[net]), 0.4, net)

    for ref in BUS_CONNECTORS:
        outline = silk_box(placed[ref])
        assert outline is not None
        # By pin number: the pad map's order varies between runs, and labels that repeat
        # (GND, 12V) are numbered in the order they are written.
        for number, net in sorted(pad_nets[ref].items(), key=lambda kv: int(kv[0])):
            text = PIN_LABEL[net]
            px, py = pad_xy(placed[ref], number)
            if ref in PIN_LABEL_RIGHT:
                dx, dy, size, angle = PIN_LABEL_RIGHT[ref]
                board.text(text, (px + dx, py + dy), size=size, thickness=size * 0.15, angle=angle)
                continue
            half = text_box(text, (0, 0), 0.8, 0.12, 0)[2]
            # Left of the outline, but never past the edge: J2's header body overhangs
            # it, so its labels go between the edge and its pads, as on the original.
            x = max(outline[0] - PIN_LABEL_GAP - half, OUTLINE[0] + LABEL_EDGE + half)
            board.text(text, (x, py), size=0.8, thickness=0.12)
    for slot, ref in enumerate(["J3", "J4", "J5", "J6"], start=1):
        jx, jy = PLACEMENT[ref][:2]
        title = f"SLICE {slot}"
        want = (jx + SLOT_TITLE[0], jy + SLOT_TITLE[1])
        at = nearest_clear_spot(board.items, title, want, OUTLINE, size=2.5, thickness=0.375)
        board.text(title, at or want, size=2.5, thickness=0.375)

    # Solid pad connections: thermal spokes limit a slice pin to about 2.9 A, under
    # the 5 A budget (decided 2026-11-08). Above 5 A, see _working/05-board-review.md.
    board.pour("GND", "B.Cu", solid=True)
    board.pour("+12V", "F.Cu", solid=True)

    libs.write_project_lib_tables(outdir)
    write_project(
        outdir / f"{name}.kicad_pro",
        netclasses=NETCLASSES,
        members={"BREAD": BUS_NETS},
        rules=RULES,
        severities=PARITY_ERRORS | SILK_ERRORS,
    )
    write_rules(outdir / f"{name}.kicad_dru", DRU_RULES)
    place_references(board.items, OUTLINE)
    label = f"Loaf_x004 | kidl-spike {source}"
    # After the references, nearest its intended spot that is clear of parts and
    # text: its length varies with the source id, so it gives way, not them.
    at = nearest_clear_spot(board.items, label, LABEL_AT, OUTLINE, size=0.8, thickness=0.12)
    board.text(label, at or LABEL_AT, size=0.8, thickness=0.12)
    return board.write(outdir / f"{name}.kicad_pcb")
