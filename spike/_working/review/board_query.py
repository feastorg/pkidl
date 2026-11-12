"""Query a .kicad_pcb: what copper is in a window, or how a net is routed.

usage (from the kidl-spike checkout, with `uv run python`):
  board_query.py BOARD window X0 Y0 X1 Y1   # tracks, vias, pads, zones touching the window (board mm, y down)
  board_query.py BOARD net NAME             # every track/via/pad of a net, with widths
  board_query.py BOARD nets                 # per-net summary: segments, min/max width, layers, vias
  board_query.py BOARD footprints           # every footprint: ref, value, lib id, position, side

Widths and clearances are in mm. Pad positions are their centres on the board.
"""

import math
import sys
from collections import defaultdict

from pkidl.footprint import pad_xy
from pkidl.sexpr import find, find_all, parse


def g(node, key):
    c = find(node, key)
    return c[1:] if c else None


board = parse(open(sys.argv[1]).read())
mode = sys.argv[2]

segs = []
for s in find_all(board, "segment"):
    a, b = g(s, "start"), g(s, "end")
    segs.append({"net": str(g(s, "net")[0]), "layer": str(g(s, "layer")[0]), "w": float(g(s, "width")[0]),
                 "a": (float(a[0]), float(a[1])), "b": (float(b[0]), float(b[1]))})
vias = []
for v in find_all(board, "via"):
    at = g(v, "at")
    vias.append({"net": str(g(v, "net")[0]), "at": (float(at[0]), float(at[1])), "size": float(g(v, "size")[0]),
                 "drill": float(g(v, "drill")[0])})
pads = []
fps = []
for fp in find_all(board, "footprint"):
    ref = next((p[2] for p in find_all(fp, "property") if p[1] == "Reference"), "?")
    val = next((p[2] for p in find_all(fp, "property") if p[1] == "Value"), "")
    at = g(fp, "at")
    fps.append((ref, val, str(fp[1]), at, str(g(fp, "layer")[0])))
    for pad in find_all(fp, "pad"):
        try:
            x, y = pad_xy(fp, str(pad[1]))
        except StopIteration:
            continue
        net = g(pad, "net")
        size = g(pad, "size")
        pads.append({"ref": ref, "num": str(pad[1]), "net": str(net[0]) if net else "-", "at": (x, y),
                     "type": str(pad[2]), "shape": str(pad[3]), "size": (float(size[0]), float(size[1])),
                     "layers": " ".join(map(str, g(pad, "layers")))})
zones = []
for z in find_all(board, "zone"):
    pts = [(float(p[1]), float(p[2])) for p in find_all(find(find(z, "polygon"), "pts"), "xy")]
    filled = find_all(z, "filled_polygon")
    pri = g(z, "priority")
    cp = find(z, "connect_pads")
    zones.append({"net": str(g(z, "net")[0]) if g(z, "net") else "-", "layer": " ".join(map(str, (g(z, "layer") or g(z, "layers")))),
                  "priority": pri[0] if pri else "0", "outline": pts, "filled_pieces": len(filled),
                  "connect": " ".join(str(x) for x in cp[1:] if not isinstance(x, list)) or "thermal"})


def seg_hits(s, x0, y0, x1, y1):
    for t in [i / 20 for i in range(21)]:
        x = s["a"][0] + (s["b"][0] - s["a"][0]) * t
        y = s["a"][1] + (s["b"][1] - s["a"][1]) * t
        if x0 <= x <= x1 and y0 <= y <= y1:
            return True
    return False


def fmt(p):
    return f"({p[0]:.3f}, {p[1]:.3f})"


if mode == "window":
    x0, y0, x1, y1 = map(float, sys.argv[3:7])
    print(f"window x {x0}..{x1} y {y0}..{y1}")
    print("PADS:")
    for p in pads:
        if x0 <= p["at"][0] <= x1 and y0 <= p["at"][1] <= y1:
            print(f"  {p['ref']}.{p['num']:4} {p['net']:32} at {fmt(p['at'])} {p['type']} {p['shape']} {p['size'][0]}x{p['size'][1]} [{p['layers']}]")
    print("TRACKS:")
    for s in segs:
        if seg_hits(s, x0, y0, x1, y1):
            ln = math.dist(s["a"], s["b"])
            print(f"  {s['net']:32} {s['layer']:5} w={s['w']:<6} {fmt(s['a'])} -> {fmt(s['b'])} len {ln:.2f}")
    print("VIAS:")
    for v in vias:
        if x0 <= v["at"][0] <= x1 and y0 <= v["at"][1] <= y1:
            print(f"  {v['net']:32} at {fmt(v['at'])} size {v['size']} drill {v['drill']}")
    print("ZONES (outline bbox overlapping the window):")
    for z in zones:
        xs, ys = [p[0] for p in z["outline"]], [p[1] for p in z["outline"]]
        if min(xs) <= x1 and max(xs) >= x0 and min(ys) <= y1 and max(ys) >= y0:
            print(f"  {z['net']:32} {z['layer']:9} priority {z['priority']} connect {z['connect']} "
                  f"filled pieces {z['filled_pieces']} bbox {min(xs):.1f},{min(ys):.1f}..{max(xs):.1f},{max(ys):.1f}")
elif mode == "net":
    name = sys.argv[3]
    for p in pads:
        if p["net"] == name:
            print(f"  pad {p['ref']}.{p['num']} at {fmt(p['at'])} {p['shape']} {p['size'][0]}x{p['size'][1]} [{p['layers']}]")
    for s in segs:
        if s["net"] == name:
            print(f"  track {s['layer']} w={s['w']} {fmt(s['a'])} -> {fmt(s['b'])} len {math.dist(s['a'], s['b']):.2f}")
    for v in vias:
        if v["net"] == name:
            print(f"  via at {fmt(v['at'])} size {v['size']} drill {v['drill']}")
elif mode == "nets":
    by = defaultdict(list)
    for s in segs:
        by[s["net"]].append(s)
    vc = defaultdict(int)
    for v in vias:
        vc[v["net"]] += 1
    pc = defaultdict(int)
    for p in pads:
        pc[p["net"]] += 1
    for net in sorted(set(by) | set(pc)):
        ss = by.get(net, [])
        ws = sorted({s["w"] for s in ss})
        print(f"  {net:34} pads {pc[net]:3} segs {len(ss):3} vias {vc[net]:2} widths {ws} layers {sorted({s['layer'] for s in ss})}")
elif mode == "footprints":
    for ref, val, lib, at, layer in sorted(fps):
        print(f"  {ref:7} {val[:18]:18} {lib[:70]:70} at {' '.join(map(str, at))} {layer}")
