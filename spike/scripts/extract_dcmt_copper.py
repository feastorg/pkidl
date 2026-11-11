"""Extract the original DCMT's power copper and signal crossings into dcmt_copper.py.

usage: uv run python scripts/extract_dcmt_copper.py ../../Slice_DCMT/hardware/BREAD_Slice.kicad_pcb

Writes src/kidl_spike/boards/dcmt_copper.py: data, not code to edit by hand.

What it takes, from Slice_DCMT@b32e3b2:

- **Bridge block** (relative to the LMD18200's origin). This board's bridge block is
  the original's first channel (LMD185001, its U2, which sits where this board's U2
  does) with its two terminals moved into the column the second channel's use. So:
  from the first channel, the VS pour, the F.Cu GNDPWR pour under the body, the VS,
  GNDPWR and +12V tracks short of the terminal column, and the crossings of its
  signals; from the second (LMD185002, its U3), what is bound to the terminals: the
  +VDC and output pours and tracks. This board's second channel is its first,
  translated, so the original's second-channel signals into its U3 are taken at
  board positions, shifted onto this board's U3, to meet the root's.
- **Root** (board millimetres): the +12V pours (both layers), the board-wide GNDPWR
  pour on B.Cu and the logic GND pour on B.Cu; the +12V and GNDPWR tracks outside both
  channels' areas; the +12V vias; and the crossings of the signals there.

A crossing is an original signal track over a pour of another net on its layer, kept
as the track (layer, width, start, end): the build snaps its ends onto this board's
pads and keeps the pour out of a rectangle around it (a corridor).
"""

# pyright: reportOptionalSubscript=false, reportArgumentType=false
# It reads one known board: a node missing from it should fail loudly, as it does.

from __future__ import annotations

import sys
from pathlib import Path

from pkidl.sexpr import find, find_all, parse

ORIGINAL_U2 = (155.570692, 74.2)  # where this board's U2 is too
ORIGINAL_U3 = (155.208301, 42.15)
# The terminal column sits where it does on the original, and this board's U3 does not:
# copper bound to a terminal is placed from the terminal (the original's second channel's
# output terminal J7 and supply terminal J6), the rest from the LMD18200.
ORIGINAL_TERMINALS = {"JOUT": (188.55, 53.45), "JVDC": (188.55, 62.2)}
# Only the outputs: VDC is on F.Cu beside the VS pour, whose neck between it and the body's
# GNDPWR it would squeeze below the pour minimum if moved with its terminal.
TERMINAL_OF = {"OUT1": "JOUT", "OUT2": "JOUT"}
CH2_DX = 155.570692 - ORIGINAL_U3[0]  # this board's U3 is right of the original's by this
# A crossing belongs to the block only beside its LMD18200: further left, in the first
# channel's area, runs the Nano's signal bus, which is not the block's and would land in
# the second channel's area if translated with it. Those stay at board positions.
BLOCK_X_MIN = 153.5
ROLE_NAMES = {"DIR": "DIR", "BR": "BRAKE", "PWM": "PWM", "THRM": "THRM", "CSENS": "CSENS"}
SIGNALS = {f"/{k}{ch}": f"CH{ch}_{v}" for ch in (1, 2) for k, v in ROLE_NAMES.items()}
TERMINAL_X = 183.0  # the terminal column: copper right of this belongs to the terminals
TERMINAL_ROLES = ("VDC", "OUT1", "OUT2")
CH2 = "/Motor Driver LMD185002/"
CH1 = "/Motor Driver LMD185001/"
ROLES = {"VS": "VS", "+VDC": "VDC", "OUTPUT1": "OUT1", "OUTPUT2": "OUT2"}
OUT = Path(__file__).resolve().parents[1] / "src/kidl_spike/boards/dcmt_copper.py"


def in_ch2(p):
    return (
        p[0] > 148 and p[1] < 70
    )  # the second channel's block reaches y 68 (S2), the first starts at 73


def in_ch1(p):
    return p[0] > 148 and 70 <= p[1] < 106


def xy(node, key):
    v = find(node, key)
    return (float(v[1]), float(v[2]))


def pts(zone):
    return [(float(p[1]), float(p[2])) for p in find_all(find(find(zone, "polygon"), "pts"), "xy")]


def inside(q, poly):
    x, y = q
    c = False
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1], strict=True):
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            c = not c
    return c


def rel1(p):
    return (round(p[0] - ORIGINAL_U2[0], 4), round(p[1] - ORIGINAL_U2[1], 4))


def rel2(p):
    return (round(p[0] - ORIGINAL_U3[0], 4), round(p[1] - ORIGINAL_U3[1], 4))


def relj(p, j):
    x, y = ORIGINAL_TERMINALS[j]
    return (round(p[0] - x, 4), round(p[1] - y, 4))


def role_of(net, prefix):
    """VS, VDC, OUT1 or OUT2 for a channel's power net, else None."""
    return ROLES.get(net[len(prefix) :]) if net.startswith(prefix) else None


def r4(p):
    return (round(p[0], 4), round(p[1], 4))


def listing(name, items):
    return [f"{name} = [", *(f"    {item!r}," for item in items), "]"]


def main(src: str) -> None:
    board = parse(Path(src).read_text())
    zones = [z for z in find_all(board, "zone") if find(z, "keepout") is None]
    znet = lambda z: str((find(z, "net_name") or find(z, "net"))[1])  # noqa: E731
    zlayers = lambda z: [str(v) for v in (find(z, "layers") or find(z, "layer"))[1:]]  # noqa: E731
    zpri = lambda z: int(find(z, "priority")[1]) if find(z, "priority") is not None else 0  # noqa: E731
    bridge_zones, root_zones = [], []
    for z in zones:
        net, layers, poly = znet(z), zlayers(z), pts(z)
        role1, role2 = role_of(net, CH1), role_of(net, CH2)
        if role1 == "VS":
            bridge_zones.append(("VS", layers, zpri(z), [rel1(p) for p in poly], "U"))
        elif role2 in TERMINAL_ROLES:
            if role2 in TERMINAL_OF:
                j = TERMINAL_OF[role2]
                bridge_zones.append((role2, layers, zpri(z), [relj(p, j) for p in poly], j))
            else:
                bridge_zones.append((role2, layers, zpri(z), [rel2(p) for p in poly], "U"))
        elif net == "GNDPWR" and layers == ["F.Cu"] and all(in_ch1(p) for p in poly):
            bridge_zones.append(("GNDPWR", layers, zpri(z), [rel1(p) for p in poly], "U"))
        elif net in ("+12V", "GND") or (net == "GNDPWR" and layers == ["B.Cu"]):
            root_zones.append((net, layers, zpri(z), [r4(p) for p in poly]))
    pour_outlines = [(znet(z), lay, pts(z)) for z in zones for lay in zlayers(z)]
    bridge_tracks, root_tracks, bridge_corr, root_corr = [], [], [], []
    for s in find_all(board, "segment"):
        net, lay, w = str(find(s, "net")[1]), str(find(s, "layer")[1]), float(find(s, "width")[1])
        a, b = xy(s, "start"), xy(s, "end")
        ch1, ch2 = in_ch1(a) or in_ch1(b), in_ch2(a) or in_ch2(b)
        role1, role2 = role_of(net, CH1), role_of(net, CH2)
        if role1 or role2 or net in ("+12V", "GNDPWR"):  # power copper
            if ch2 and role2 in TERMINAL_ROLES:
                j = TERMINAL_OF.get(role2, "U")
                rel = (lambda p, j=j: relj(p, j)) if j != "U" else rel2
                bridge_tracks.append((role2, lay, w, rel(a), rel(b), j))
            elif ch1 and max(a[0], b[0]) <= TERMINAL_X and (role1 in ("VS", None)):
                bridge_tracks.append((role1 or net, lay, w, rel1(a), rel1(b), "U"))
            elif not (ch1 or ch2) and net in ("+12V", "GNDPWR"):
                root_tracks.append((net, lay, w, r4(a), r4(b)))
            continue
        if net == "GND":
            continue
        samples = [
            (a[0] + (b[0] - a[0]) * k / 10, a[1] + (b[1] - a[1]) * k / 10) for k in range(11)
        ]
        if not any(
            zl == lay and zn != net and any(inside(q, poly) for q in samples)
            for zn, zl, poly in pour_outlines
        ):
            continue
        if ch1 and max(a[0], b[0]) > BLOCK_X_MIN:
            bridge_corr.append((lay, w, rel1(a), rel1(b)))
        elif ch2:
            # The original's second-channel signals reach its U3, which sits CH2_DX left of
            # this board's: shifted onto it, these meet the root corridors where the
            # original's do. (The block's own, from the first channel, may not.)
            root_corr.append((lay, w, r4((a[0] + CH2_DX, a[1])), r4((b[0] + CH2_DX, b[1]))))
        else:
            root_corr.append((lay, w, r4(a), r4(b)))
    # The bridge control signals, routed as the original routes them: they are the
    # signals that cross the pours, and their paths are a designer's. Board positions; the
    # build snaps their ends onto this board's pads.
    signal_tracks, signal_vias = [], []
    for s in find_all(board, "segment"):
        net = str(find(s, "net")[1])
        if net in SIGNALS:
            a, b = xy(s, "start"), xy(s, "end")
            signal_tracks.append(
                (SIGNALS[net], str(find(s, "layer")[1]), float(find(s, "width")[1]), r4(a), r4(b))
            )
    for v in find_all(board, "via"):
        net = str(find(v, "net")[1])
        if net in SIGNALS:
            signal_vias.append(
                (
                    SIGNALS[net],
                    float(find(v, "size")[1]),
                    float(find(v, "drill")[1]),
                    r4(xy(v, "at")),
                )
            )
    root_vias = []
    for v in find_all(board, "via"):
        if str(find(v, "net")[1]) == "+12V":
            root_vias.append(
                ("+12V", float(find(v, "size")[1]), float(find(v, "drill")[1]), r4(xy(v, "at")))
            )
    out = [
        "# ruff: noqa: E501  (generated data: long polygons stay on one line)",
        '"""The original DCMT\'s power copper and signal crossings. Generated: do not edit.',
        "",
        "Made by scripts/extract_dcmt_copper.py from feastorg/Slice_DCMT@b32e3b2; its",
        "docstring says what is taken and why. BRIDGE_* are relative to their anchor, the last",
        "field: the LMD18200 (U) or a terminal (JOUT, JVDC);",
        "ROOT_* are board millimetres. Zones: (net or role, layers, priority, polygon).",
        "Tracks: (net or role, layer, width, start, end). Vias: (net, diameter, drill, at).",
        "Corridors: (layer, width, start, end): signal tracks that pours keep clear of.",
        '"""',
        "",
        "# fmt: off",
        *listing("BRIDGE_ZONES", bridge_zones),
        *listing("BRIDGE_TRACKS", bridge_tracks),
        *listing("BRIDGE_CORRIDORS", bridge_corr),
        *listing("ROOT_ZONES", root_zones),
        *listing("ROOT_TRACKS", root_tracks),
        *listing("ROOT_VIAS", root_vias),
        *listing("ROOT_CORRIDORS", root_corr),
        *listing("SIGNAL_TRACKS", signal_tracks),
        *listing("SIGNAL_VIAS", signal_vias),
        "# fmt: on",
        "",
    ]
    OUT.write_text("\n".join(out))
    print(f"wrote {OUT}: bridge zones {len(bridge_zones)}, tracks {len(bridge_tracks)}, corridors "
          f"{len(bridge_corr)}; root zones {len(root_zones)}, tracks {len(root_tracks)}, vias "
          f"{len(root_vias)}, corridors {len(root_corr)}")  # fmt: skip


if __name__ == "__main__":
    main(sys.argv[1])
