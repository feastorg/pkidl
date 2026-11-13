"""Measures of a filled board: what its pours actually came out as.

Run on a board whose zones KiCad has filled (``kicad-cli pcb drc --refill-zones
--save-board``): the fill is KiCad's, not pkidl's model of it.

``python -m pkidl.measure BOARD [NET ...]`` prints each net's regions.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from shapely.geometry import Point, Polygon

from pkidl.footprint import pad_at
from pkidl.sexpr import Node, find, find_all, parse


@dataclass(frozen=True)
class Regions:
    """A net's filled copper: *pieces* per layer, and *count*, the pieces left once those
    on different layers that share a via or through-hole pad of the net are joined."""

    pieces: dict[str, int]
    count: int


def regions(board: Node, nets: set[str] | None = None) -> dict[str, Regions]:
    """Each net's pour regions on *board* (filled), or only *nets*'."""
    pieces: dict[str, list[tuple[str, Polygon]]] = {}
    for z in find_all(board, "zone"):
        n = find(z, "net_name") or find(z, "net")
        if find(z, "keepout") is not None or n is None or not str(n[-1]):
            continue
        net = str(n[-1])
        if nets is not None and net not in nets:
            continue
        for f in find_all(z, "filled_polygon"):
            layer, pts = find(f, "layer"), find(f, "pts")
            assert layer is not None and pts is not None
            ring = [(float(p[1]), float(p[2])) for p in find_all(pts, "xy")]
            pieces.setdefault(net, []).append((str(layer[1]), Polygon(ring)))
    joints: dict[str, list[tuple[float, float]]] = {}
    for v in find_all(board, "via"):
        n, at = find(v, "net"), find(v, "at")
        if n is not None and at is not None:
            joints.setdefault(str(n[-1]), []).append((float(at[1]), float(at[2])))
    for fp in find_all(board, "footprint"):
        for pad in find_all(fp, "pad"):
            n = find(pad, "net")
            if n is not None and str(pad[2]) == "thru_hole":
                joints.setdefault(str(n[-1]), []).append(pad_at(fp, pad))
    out = {}
    for net, ps in sorted(pieces.items()):
        parent = list(range(len(ps)))

        def root(i: int, parent: list[int] = parent) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for q in joints.get(net, []):
            hit = [i for i, (_, poly) in enumerate(ps) if poly.covers(Point(q))]
            for i in hit[1:]:
                parent[root(i)] = root(hit[0])
        per: dict[str, int] = {}
        for layer, _ in ps:
            per[layer] = per.get(layer, 0) + 1
        out[net] = Regions(per, len({root(i) for i in range(len(ps))}))
    return out


def main(argv: list[str]) -> int:
    """``BOARD [NET ...] [NET=REGIONS ...]``: print the nets' regions; exit 1 if a net
    named with ``=`` has another count."""
    board = parse(Path(argv[1]).read_text())
    want = dict(a.rsplit("=", 1) for a in argv[2:] if "=" in a)
    nets = {a for a in argv[2:] if "=" not in a} | set(want)
    got = regions(board, nets or None)
    bad = 0
    for net, r in got.items():
        print(f"{net}: {r.count} region(s); pieces {r.pieces}")
    for net, n in want.items():
        count = got[net].count if net in got else 0
        if count != int(n):
            print(f"{net}: want {n} region(s), got {count}", file=sys.stderr)
            bad = 1
    return bad


if __name__ == "__main__":
    sys.exit(main(sys.argv))
