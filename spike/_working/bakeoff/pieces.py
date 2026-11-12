"""Fill pieces per (net, layer) on a filled board, with each piece's area (mm²), largest first."""
import sys
from collections import defaultdict
from pkidl.sexpr import find, find_all, parse


def area(pts):
    return abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]))) / 2


out = defaultdict(list)
for z in find_all(parse(open(sys.argv[1]).read()), "zone"):
    if find(z, "keepout") is not None:
        continue
    net = str((find(z, "net_name") or find(z, "net"))[1])
    for f in find_all(z, "filled_polygon"):
        pts = [(float(p[1]), float(p[2])) for p in find_all(find(f, "pts"), "xy")]
        out[(net, str(find(f, "layer")[1]))].append(round(area(pts), 1))
for k in sorted(out):
    print(f"{k[0]:12s} {k[1]:5s} pieces {len(out[k])}: {sorted(out[k], reverse=True)}")
