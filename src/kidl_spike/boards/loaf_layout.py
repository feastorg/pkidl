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

from kidl_spike import libs
from pkidl.board import Board
from pkidl.footprint import Placement, pad_xy, place
from pkidl.project import PARITY_ERRORS, NetClass, write_project
from pkidl.sexpr import find, find_all, parse

# Board edge (x0, y0, x1, y1) and corner radius, mm. The original's left edge is
# 0.014 mm out of square; that is not part of the interface.
OUTLINE = (48.3, 77.0, 169.5, 127.0)
CORNER_RADIUS = 2.0

# The interface: reference -> (x, y, rotation, on the back).
PLACEMENT = {
    "J1": (86.5, 114.7, 180.0, True),  # 12 V barrel jack
    "J2": (58.3, 90.6, 180.0, True),  # chain in (pin header)
    "J3": (70.9, 102.02, 0.0, False),  # slice connectors, 30.4 mm pitch
    "J4": (101.3, 102.02, 0.0, False),
    "J5": (131.7, 102.02, 0.0, False),
    "J6": (162.1, 102.02, 0.0, False),
    "J7": (165.8, 90.6, 180.0, True),  # chain out (pin socket)
}
LOGO = ("KMLib_Aesthetic:OSHW_Logo_10mm", 59.0, 120.7)
LABEL_AT = (116.5, 79.0)  # between the J4 and J5 mounting holes

SIGNALS = ["SCL_5V", "SDA_5V", "E_STOP_5V", "INT_5V", "SYNC_5V"]
BUS_NETS = ["+12V", "GND", *SIGNALS]

NETCLASSES = [
    NetClass("Default", clearance=0.2, track_width=0.25),
    NetClass("BREAD", clearance=0.2, track_width=0.4),
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


def _symbols(schematic: Path) -> dict[str, tuple[str, dict[str, str]]]:
    """Reference -> (symbol uuid, fields) from a generated schematic."""
    out = {}
    for sym in find_all(parse(schematic.read_text()), "symbol"):
        if find(sym, "lib_id") is None:
            continue
        props = {p[1]: p[2] for p in find_all(sym, "property")}
        ref = props.get("Reference", "")
        uid = find(sym, "uuid")
        if ref.startswith("#") or uid is None:
            continue  # power symbols and flags have no footprint
        out[ref] = (str(uid[1]), props)
    return out


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
    symbols = _symbols(outdir / f"{name}.kicad_sch")
    board = Board()
    board.outline_rounded_rect(*OUTLINE, CORNER_RADIUS)

    placed = {}
    for ref, (x, y, rot, back) in sorted(PLACEMENT.items()):
        uid, props = symbols[ref]
        lib_id = props["Footprint"]
        p = Placement(
            lib_id, ref, props["Value"], x, y, rot, back,
            nets=pad_nets[ref], path=f"/{uid}", sheetfile=f"{name}.kicad_sch",
            fields=fields[ref],
        )  # fmt: skip
        placed[ref] = place(libs.footprint_file(lib_id), p)
        board.footprint(placed[ref])

    lib_id, x, y = LOGO
    board.footprint(place(libs.footprint_file(lib_id), Placement(lib_id, "LOGO1", "", x, y)))

    pin = {net: n for n, net in pad_nets["J2"].items()}
    for net in SIGNALS:
        board.track(pad_xy(placed["J2"], pin[net]), pad_xy(placed["J7"], pin[net]), 0.4, net)

    x0, y0, x1, y1 = OUTLINE
    edge = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    board.zone("GND", "B.Cu", edge)
    board.zone("+12V", "F.Cu", edge)
    board.text(f"Loaf_x004 | kidl-spike {source}", LABEL_AT, size=0.8, thickness=0.12)

    libs.write_project_lib_tables(outdir)
    write_project(
        outdir / f"{name}.kicad_pro",
        netclasses=NETCLASSES,
        members={"BREAD": BUS_NETS},
        rules=RULES,
        severities=PARITY_ERRORS,
    )
    return board.write(outdir / f"{name}.kicad_pcb")
