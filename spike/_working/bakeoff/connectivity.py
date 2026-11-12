"""Which pads of each routed net are left disconnected, given wires, vias and planes.

usage: unrouted.py STAGE.dsn OUT.ses BOARD
Pads join if a wire or via touches both (within the pad, approximated as 0.8 mm), or if
both sit inside one plane polygon on a layer the pad has.
"""
import re, sys
from pkidl.dsn import read_ses
from pkidl.footprint import pad_xy
from pkidl.sexpr import find, find_all, parse

tree = parse(open(sys.argv[1]).read().replace("(string_quote \")", "(string_quote q)", 1))
um = lambda v: float(v) / 1000  # DSN in um (resolution um 10, unit um): ours and KiCad's
nets = {str(n[1]): [str(p) for p in find(n, "pins")[1:]] for n in find_all(find(tree, "network"), "net")
        if find(n, "pins") is not None}
planes = []
for pl in find_all(find(tree, "structure"), "plane"):
    poly = find(pl, "polygon")
    v = [um(x) for x in poly[3:]]
    planes.append((str(pl[1]), str(poly[1]), [(v[i], -v[i + 1]) for i in range(0, len(v) - 1, 2)]))
board = parse(open(sys.argv[3]).read())
pads = {}
shapes = {}  # pad half-sizes and absolute angle
for fp in find_all(board, "footprint"):
    ref = str(find(find(fp, "property"), "property")[2]) if False else None
    for prop in find_all(fp, "property"):
        if str(prop[1]) == "Reference":
            ref = str(prop[2])
    for pad in find_all(fp, "pad"):
        lay = " ".join(str(x) for x in find(pad, "layers")[1:])
        layers = {"F.Cu", "B.Cu"} if "*.Cu" in lay else {l for l in ("F.Cu", "B.Cu") if l in lay}
        size = find(pad, "size")
        pa = find(pad, "at")
        ang = float(pa[3]) if pa is not None and len(pa) > 3 else 0.0
        pads[f"{ref}-{pad[1]}"] = (pad_xy(fp, str(pad[1])), layers)
        shapes[f"{ref}-{pad[1]}"] = (float(size[1]) / 2, float(size[2]) / 2 if len(size) > 2 else float(size[1]) / 2, ang)


def inside(p, poly):
    x, y = p; c = False
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            c = not c
    return c


import math


def in_pad(name, q, margin=0.3):
    """Is point q on pad *name* (its real rectangle, rotated), within *margin* mm?"""
    (cx, cy), _ = pads[name]
    hx, hy, ang = shapes[name]
    a = math.radians(ang)
    dx, dy = q[0] - cx, q[1] - cy
    lx, ly = dx * math.cos(a) - dy * math.sin(a), dx * math.sin(a) + dy * math.cos(a)
    return abs(lx) <= hx + margin and abs(ly) <= hy + margin


def touch(p, q):
    if p[0][0] == "pad" and q[0][0] != "pad":
        return in_pad(p[0][1], q[1])
    if q[0][0] == "pad" and p[0][0] != "pad":
        return in_pad(q[0][1], p[1])
    return abs(p[1][0] - q[1][0]) < 0.05 and abs(p[1][1] - q[1][1]) < 0.05


from pkidl.dsn import Via, Wire  # fixed wiring in the DSN counts too
wiring = find(tree, "wiring")
fixed_w, fixed_v = [], []
for w in find_all(wiring, "wire") if wiring is not None else []:
    path, net = find(w, "path"), find(w, "net")
    v = [um(x) for x in path[3:]]
    fixed_w.append(Wire(str(net[1]), str(path[1]), um(path[2]), [(v[i], -v[i + 1]) for i in range(0, len(v) - 1, 2)]))
for v in find_all(wiring, "via") if wiring is not None else []:
    if find(v, "net") is not None:
        fixed_v.append(Via(str(find(v, "net")[1]), str(v[1]), (um(v[2]), -um(v[3]))))
missing = 0
wires, vias = read_ses(__import__("pathlib").Path(sys.argv[2])) if sys.argv[2] != "-" else ([], [])
wires = wires + fixed_w
vias = vias + fixed_v
def via_r(v):
    m = re.search(r"_(\d+):(\d+)_um", v.padstack)
    return int(m[1]) / 2000 if m else 0.3


def seg_dist(q, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = dx * dx + dy * dy
    s = 0.0 if L == 0 else max(0.0, min(1.0, ((q[0] - a[0]) * dx + (q[1] - a[1]) * dy) / L))
    return math.hypot(q[0] - a[0] - s * dx, q[1] - a[1] - s * dy)


def samples(a, b, step=0.1):
    n = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) / step))
    return [(a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n) for k in range(n + 1)]


for net, pins in sorted(nets.items()):
    parent = {}

    def f(a):
        parent.setdefault(a, a)
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def u(a, b):
        parent[f(a)] = f(b)

    mypads = [p for p in pins if p in pads]
    segs = [(("w", i), w.layer, w.width, a, b) for i, w in enumerate(wires) if w.net == net
            for a, b in zip(w.points, w.points[1:] or w.points)]
    myvias = [(("v", i), v.at, via_r(v)) for i, v in enumerate(vias) if v.net == net]
    myplanes = [(("plane", k), lay, poly) for k, (n, lay, poly) in enumerate(planes) if n == net]
    for p in mypads:
        f(("pad", p))
    for node, lay, w, a, b in segs:  # a segment touching a pad anywhere along it
        for p in mypads:
            if lay in pads[p][1] and any(in_pad(p, q, margin=w / 2) for q in samples(a, b)):
                u(node, ("pad", p))
        for vn, at, r in myvias:
            if seg_dist(at, a, b) <= w / 2 + r:
                u(node, vn)
        for pn, play, poly in myplanes:
            if play == lay and (inside(a, poly) or inside(b, poly)):
                u(node, pn)
    for x in range(len(segs)):  # segments meeting: an end of one on the other, same layer
        n1, l1, w1, a1, b1 = segs[x]
        for y in range(x):
            n2, l2, w2, a2, b2 = segs[y]
            if n1 != n2 and l1 == l2 and f(n1) != f(n2):
                tol = (w1 + w2) / 2 * 0.5 + 0.01
                if min(seg_dist(a1, a2, b2), seg_dist(b1, a2, b2), seg_dist(a2, a1, b1), seg_dist(b2, a1, b1)) <= tol:
                    u(n1, n2)
    for vn, at, r in myvias:
        for p in mypads:
            if in_pad(p, at, margin=r):
                u(vn, ("pad", p))
        for pn, play, poly in myplanes:
            if inside(at, poly):
                u(vn, pn)
    for p in mypads:
        for pn, play, poly in myplanes:
            if play in pads[p][1] and inside(pads[p][0], poly):
                u(("pad", p), pn)
    groups = {}
    for p in mypads:
        groups.setdefault(f(("pad", p)), []).append(p)
    if len(groups) > 1:
        missing += len(groups) - 1
        if "-v" in sys.argv:
            print(net, "pieces:", sorted(groups.values(), key=len, reverse=True))

print('MISSING', missing)
