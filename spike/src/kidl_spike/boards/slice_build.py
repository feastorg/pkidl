"""One build sequence for every Nano Slice, driven by its YAML spec.

A Slice is its root parts, laid out by a ``Root`` (the bus, Nano, buck, LED and net
tie where one of the existing boards has them, with that board's pours), and its
channels, each a block at an anchor. What a block brings follows from its kind
(``block_layout``): its parts, netclass and rules, pours, thermal vias and labels. So a
new Slice is a YAML file naming a root and its channels.

The sequence: place, fixed vias, route, stitch, logo, terminal labels in channel order,
pours, project and rules, references, then the source label.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from pkidl.board import Board
from pkidl.dsn import Via, Wire, via_padstack
from pkidl.dsn import via_size as _via_size
from pkidl.fill import prefill
from pkidl.footprint import Placement, place
from pkidl.project import (
    PARITY_ERRORS,
    SILK_ERRORS,
    DruRule,
    NetClass,
    width_rules,
    write_project,
    write_rules,
)
from pkidl.sexpr import Node, parse
from pkidl.silk import nearest_clear_spot, place_references
from pkidl.stitch import stitch_points
from shapely.geometry import LineString, Polygon
from shapely.geometry import Point as SPoint

from kidl_spike import libs
from kidl_spike.boards.block_layout import (
    HV_RELAY,
    HV_SIGNALS,
    MAINS_LV_CLEARANCE,
    MAINS_LV_CREEPAGE,
    MAINS_RULES,
    MOTOR,
    MOTOR_SIGNALS,
    POWER,
    RELAY_TERMINAL,
    TC_GROUND,
    TC_INPUT_KEEPOUT,
    TC_TERMINAL,
    at_offset,
    bridge_terminals,
    bridge_vias,
    bridge_zones,
    channel_spots,
    encoder_terminals,
    label_terminal,
    terminal_labels,
    thermocouple_region,
)
from kidl_spike.boards.common import SLICE_S
from kidl_spike.boards.slice import (
    MOUNTING_HOLE_RULE,
    ORIGIN,
    POUR_MIN_WIDTH,
    RULES,
    SIGNAL_MINIMUM,
    Spot,
    outline_polygon,
    place_board,
    route,
)
from kidl_spike.boards.spec import BoardSpec

LOGO_FOOTPRINT = "KMLib_Aesthetic:OSHW_Logo_10mm"
DEFAULT = NetClass("Default", clearance=0.2, track_width=0.5, via_diameter=1.0, via_drill=0.5)
STITCH_PITCH = 5.0  # GND stitching: the original RLHT's 0.8/0.4 vias, on a grid
STITCH_VIA = (0.8, 0.4)
# Clear of other copper by this much, so the pours reach a stitching via on both layers:
# at 0.5 mm, vias boxed in by tracks landed in pockets the fill drops (dangling vias).
STITCH_CLEARANCE = 1.0


@dataclass(frozen=True)
class Root:
    """Where a Slice's root parts go, and the board-level copper that goes with them."""

    fixed: dict[str, Spot]
    hs1_vias: list[tuple[float, float, float, float]]  # GND vias at HS1: dx, dy, d, drill
    logo: tuple[float, float]
    label_at: tuple[float, float]
    label_sep: str  # between the title and the source id: " | " or a new line
    solid_pads: frozenset[str]  # parts whose pads join the pours without thermals
    # The board-level pours: (board, placed, outline box, block pours first) -> None.
    pours: Callable[[Board, dict[str, Node], tuple[float, float, float, float], list], None]
    # Power copper drawn as data, placed before routing: (placed, bridge channels) ->
    # Authored. A board whose spec asks for it (``authored_copper``) gets these pours
    # instead of the hull pours and bridge zones, and routes against them
    # (``pkidl.fill.prefill``, planes).
    authored: Callable[[dict[str, Node], list[dict]], Authored] | None = None
    authored_solid_pads: frozenset[str] = frozenset()  # more solid pads, with ``authored``


@dataclass(frozen=True)
class Authored:
    """Power copper as a designer draws it, in board millimetres."""

    zones: list[tuple[str, list[str], int, list[tuple[float, float]]]]  # net, layers, priority
    wires: list[Wire]  # fixed tracks the pours can't stand in for
    vias: list[Via]
    corridors: list[
        tuple[str, list[tuple[float, float]]]
    ]  # layer, polygon: no pour, signals may cross


def root(spec: BoardSpec) -> Root:
    """The root layout a spec names: ``<root>_layout.ROOT``."""
    return importlib.import_module(f"kidl_spike.boards.{spec.root}_layout").ROOT


def netclasses(spec: BoardSpec) -> tuple[list[NetClass], dict[str, list[str]]]:
    """The board's netclasses, Default first, and their members, from its blocks."""
    relays, bridges = spec.channels("relay"), spec.channels("bridge")
    classes, members = [DEFAULT], {}
    if relays:
        classes.append(HV_RELAY)
        members["HV Relay"] = [f"{r['ch']}_{n}" for r in relays for n in HV_SIGNALS]
    if bridges:
        classes.append(MOTOR)
        members["Motor"] = [f"{b['ch']}_{n}" for b in bridges for n in MOTOR_SIGNALS]
    if spec.power_nets:
        classes.append(POWER)
        members["Power"] = list(spec.power_nets)
    return classes, members


def dru_rules(spec: BoardSpec) -> list[DruRule]:
    """Width minimums for every class; with relays, the mains rules, and HV width an
    error (the mains routes are full width); the mounting-hole keepout."""
    classes, _ = netclasses(spec)
    rules = width_rules(classes, minimums=SIGNAL_MINIMUM)
    if spec.channels("relay"):
        rules = [replace(r, severity="error") if r.name == "HV Relay width" else r for r in rules]
        rules += MAINS_RULES
    return rules + [MOUNTING_HOLE_RULE]


def placement(spec: BoardSpec) -> dict[str, Spot]:
    """Every footprint's position, by reference."""
    spots = dict(root(spec).fixed)
    for c in spec.circuit.channels:
        if c.params["ch"] in spec.anchors:
            spots |= channel_spots(c.kind, c.params, spec.anchors[c.params["ch"]])
    return spots


def build_pcb(
    spec: BoardSpec,
    outdir: Path,
    name: str,
    pad_nets: dict[str, dict[str, str]],
    fields: dict[str, dict[str, str]],
    source: str,
) -> Path:
    """Write ``<name>.kicad_pcb``, ``<name>.kicad_pro``, ``<name>.kicad_dru`` and lib
    tables into *outdir*, routed."""
    r = root(spec)
    outline = SLICE_S.outline(*ORIGIN)
    classes, members = netclasses(spec)
    relays, bridges = spec.channels("relay"), spec.channels("bridge")
    hv_nets = members.get("HV Relay", [])

    board, placed = place_board(outdir, name, placement(spec), pad_nets, fields,
                                solid_pads=r.solid_pads | (r.authored_solid_pads
                                                           if spec.authored_copper
                                                           else frozenset()))  # fmt: skip
    hx, hy = at_offset(placed["HS1"], 0, 0)
    vias = [Via("GND", via_padstack(d, h), (round(hx + dx, 6), round(hy + dy, 6)))
            for dx, dy, d, h in r.hs1_vias]  # fmt: skip
    for b in bridges:
        vias += bridge_vias(placed, b)
    # The mains routes cannot all keep 3 mm from LV copper (pins sit closer by their
    # footprints), so only the signals routed around them are held to it.
    clearances = {("HV Relay", "Default"): MAINS_LV_CLEARANCE} if relays else None
    thermocouples = [(t, spec.anchors[t["ch"]]) for t in spec.channels("thermocouple")]
    # B.Cu under each thermocouple front end: no track under its inputs; on a board whose
    # bus ground is a power ground, none under the whole block, which gets logic ground.
    box = TC_GROUND if spec.circuit.ground != "GND" else TC_INPUT_KEEPOUT
    inputs = [("B.Cu", thermocouple_region(t, a, box)) for t, a in thermocouples]
    authored = r.authored(placed, bridges) if r.authored and spec.authored_copper else None
    planes, wires = None, None
    if authored:
        for net, layers, priority, poly in authored.zones:
            for layer in layers:
                board.zone(net, layer, poly, clearance=0.5, min_thickness=POUR_MIN_WIDTH,
                           priority=priority)  # fmt: skip
        for i, (layer, poly) in enumerate(authored.corridors):
            board.rule_area(f"corridor {i}", layer, poly, tracks=True, vias=True)
        vias += authored.vias
        wires = authored.wires
        edge = float(RULES["min_copper_edge_clearance"])
        class_gap = {n: c.clearance for c in classes for n in members.get(c.name, [])}
        planes = prefill(board.items + _nodes(wires, vias), outline_polygon(), edge, class_gap)
        # A copied via joins its net only where both layers have that net's copper there;
        # one that doesn't is dropped, and the pours are filled again without it.
        joined = [v for v in vias if v not in authored.vias or _joins_both(v, planes, wires)]
        if len(joined) < len(vias):
            vias = joined
            planes = prefill(board.items + _nodes(wires, vias), outline_polygon(), edge,
                             class_gap)  # fmt: skip
    route(board, placed, outdir, name, classes, members, signal_clearances=clearances,
          vias=vias, keepouts=inputs, planes=planes, wires=wires)  # fmt: skip
    if spec.stitch:
        keep = {net: MAINS_LV_CREEPAGE for net in hv_nets} | {"": MOUNTING_HOLE_RULE.min_mm}
        edge = float(RULES["min_copper_edge_clearance"])
        for p in stitch_points(board.items, "GND", outline_polygon(), pitch=STITCH_PITCH,
                               diameter=STITCH_VIA[0], clearance=STITCH_CLEARANCE, edge=edge,
                               keep_from=keep, avoid=[poly for _, poly in inputs]):  # fmt: skip
            board.via(p, *STITCH_VIA, "GND")

    board.footprint(place(libs.footprint_file(LOGO_FOOTPRINT),
                          Placement(LOGO_FOOTPRINT, "LOGO1", "", *r.logo)))  # fmt: skip
    for c in spec.circuit.channels:
        if c.kind == "relay":
            label_terminal(board, placed, c.params, RELAY_TERMINAL, outline)
        elif c.kind == "thermocouple":
            label_terminal(board, placed, c.params, TC_TERMINAL, outline)
        elif c.kind == "bridge":
            terminal_labels(board, placed, bridge_terminals(c.params))
        elif c.kind == "encoder":
            terminal_labels(board, placed, encoder_terminals(c.params))

    if not authored:
        block_pours = [*[(f"{b['ch']}_VDC", "F.Cu", 5) for b in bridges],
                       *[(f"{b['ch']}_VS", "F.Cu", 4) for b in bridges]]  # fmt: skip
        r.pours(board, placed, outline, block_pours)
        for b in bridges:
            bridge_zones(board, placed, b)
    for t, a in thermocouples:
        # The router's keepout, as a rule area DRC holds the board to.
        board.rule_area(f"{t['ch']} inputs", "B.Cu", thermocouple_region(t, a, box), pours=True)
        if spec.circuit.ground != "GND":
            # Logic ground on B.Cu over the whole block, above the power-ground pour. No
            # track crosses it (below), so it fills as one piece, joined to the board's GND
            # pour where the two overlap at the converter.
            board.zone("GND", "B.Cu", thermocouple_region(t, a, TC_GROUND), clearance=0.5,
                       min_thickness=POUR_MIN_WIDTH, priority=4, solid=True)  # fmt: skip
    if spec.circuit.ground != "GND" and not authored:
        # The power ground fills the back. On the front it is only under the bridges'
        # bodies: elsewhere it would cover the logic area, where its one connection is a
        # bulk capacitor's pad: the GND/GNDPWR split would not exist.
        board.pour(spec.circuit.ground, "B.Cu", clearance=0.5, min_thickness=POUR_MIN_WIDTH)

    libs.write_project_lib_tables(outdir)
    write_project(outdir / f"{name}.kicad_pro", netclasses=classes, members=members,
                  rules=RULES, severities=PARITY_ERRORS | SILK_ERRORS)  # fmt: skip
    write_rules(outdir / f"{name}.kicad_dru", dru_rules(spec))
    place_references(board.items, outline)
    label = f"{spec.title}{r.label_sep}kidl-spike {source}"
    # After the references, nearest its intended spot that is clear of parts and text:
    # its length varies with the source id, so it gives way, not them.
    at = nearest_clear_spot(board.items, label, r.label_at, outline, size=0.8, thickness=0.12)
    board.text(label, at or r.label_at, size=0.8, thickness=0.12)
    return board.write(outdir / f"{name}.kicad_pcb")


def _joins_both(via: Via, planes: list, wires: list[Wire]) -> bool:
    """Whether *via* touches its net's copper, a plane or a wire, on F.Cu and on B.Cu."""
    ring = SPoint(via.at).buffer(_via_size(via.padstack)[0] / 2)
    copper = {"F.Cu": [], "B.Cu": []}
    for net, layer, poly in planes:
        if net == via.net and layer in copper:
            copper[layer].append(Polygon(poly))
    for w in wires:
        if w.net == via.net and w.layer in copper:
            copper[w.layer].append(LineString(w.points).buffer(w.width / 2))
    return all(any(g.intersects(ring) for g in gs) for gs in copper.values())


def _nodes(wires: list[Wire], vias: list[Via]) -> list[Node]:
    """Fixed tracks and vias as board nodes, for ``prefill`` to keep pours clear of."""
    out = [parse(f'(segment (start {a[0]} {a[1]}) (end {b[0]} {b[1]}) (width {w.width}) '
                 f'(layer "{w.layer}") (net "{w.net}"))')
           for w in wires for a, b in zip(w.points, w.points[1:], strict=False)]  # fmt: skip
    for v in vias:
        d, _ = _via_size(v.padstack)
        out.append(parse(f'(via (at {v.at[0]} {v.at[1]}) (size {d}) (net "{v.net}"))'))
    return out


def hull_pours(margin: float) -> Callable[..., None]:
    """Pours around each net's pads (``Board.pour`` around the parts): the blocks', then
    ``+12V`` on the front and ``GND`` on the back, as on DCMT."""

    def pours(board: Board, placed: dict[str, Node], outline: tuple, block: list) -> None:
        for net, layer, priority in [*block, ("+12V", "F.Cu", 3), ("GND", "B.Cu", 1)]:
            board.pour(net, layer, around=placed.values(), margin=margin, clearance=0.5,
                       min_thickness=POUR_MIN_WIDTH, priority=priority, solid=True)  # fmt: skip

    return pours


def ground_both_layers(board: Board, placed: dict[str, Node], outline: tuple, block: list) -> None:
    """GND over the whole board on both layers, as on RLHT, after any block pours."""
    for net, layer, priority in block:
        board.pour(net, layer, around=placed.values(), margin=1.5, clearance=0.5,
                   min_thickness=POUR_MIN_WIDTH, priority=priority, solid=True)  # fmt: skip
    for layer in ("F.Cu", "B.Cu"):
        # Not POUR_MIN_WIDTH yet: at 0.5 mm, U1.4 and U5.3 keep one thermal spoke of two.
        board.pour("GND", layer, clearance=0.5)


def build(name: str, outdir: Path | None = None, source: str | None = None) -> Path:
    """Build the Slice ``boards/<name>.yaml`` describes into *outdir* (``build/<name>``):
    netlist, schematic, routed board, project and rules. A Slice needs no module of its
    own. Returns the directory written."""
    from kidl_spike.boards.blocks import build_circuit
    from kidl_spike.boards.common import generate
    from kidl_spike.boards.spec import load

    spec = load(name)
    outdir = outdir or Path("build") / name
    # Absolute workdir so the materialised fp-lib-table survives generate's chdir.
    nets = build_circuit(spec.circuit, workdir=(outdir / "kicad-env").resolve())

    def pcb(out: Path, board: str, pad_nets: dict, fields: dict, src: str) -> Path:
        return build_pcb(spec, out, board, pad_nets, fields, src)

    return generate(outdir, name, nets, pcb, source)
