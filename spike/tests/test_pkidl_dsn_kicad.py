"""pkidl's DSN against KiCad's own, on boards we didn't draw.

Each fixture under ``tests/fixtures/external`` is a PCBench board (see its
``manifest.json``): the board upgraded to KiCad 10, and the DSN KiCad exported
for it. pkidl writes its own DSN from the board's footprints, and the two are
compared where routing depends on them: where each pin sits, which pins each net
joins, and the copper each pad puts on each layer.
"""

import json
import math
from pathlib import Path

import pytest

from pkidl.dsn import write_dsn
from pkidl.project import NetClass
from pkidl.sexpr import Node, find, find_all, parse

FIXTURES = Path(__file__).parent / "fixtures" / "external"
MANIFEST = json.loads((FIXTURES / "manifest.json").read_text())
BOARDS = [b["board_id"] for b in MANIFEST["boards"]]
TOL = 2.0  # um; both writers round to 0.1 um or coarser

# KiCad writes a pad whose copper is no wider than its drill as a hole in the
# image, not a pin. pkidl writes a pin, which keeps out the same area.
HOLES_AS_PINS = {"bldc-gimbal-1d_gimbal-board": {"H1-1", "H2-1", "H3-1", "H4-1"}}


def _read_dsn(path: Path) -> Node:
    # Specctra's (string_quote ") holds a lone quote character
    return parse(path.read_text().replace('(string_quote ")', "(string_quote q)"))


@pytest.fixture(scope="module", params=BOARDS)
def pair(request, tmp_path_factory) -> tuple[str, Node, Node]:
    board_id = request.param
    board = parse((FIXTURES / board_id / "board.kicad_pcb").read_text())
    edge = [
        (float(p[1]), float(p[2]))
        for g in find_all(board, "gr_line") + find_all(board, "gr_rect") + find_all(board, "gr_arc")
        if str(find(g, "layer")[1]) == "Edge.Cuts"  # type: ignore[index]
        for k in ("start", "end", "mid")
        if (p := find(g, k)) is not None
    ]
    xs, ys = [p[0] for p in edge], [p[1] for p in edge]
    outline = [(min(xs), min(ys)), (max(xs), min(ys)), (max(xs), max(ys)), (min(xs), max(ys))]
    out = tmp_path_factory.mktemp(board_id) / "pkidl.dsn"
    write_dsn(out, find_all(board, "footprint"), outline, [NetClass("Default", 0.2, 0.25)], {})
    return board_id, _read_dsn(FIXTURES / board_id / "kicad.dsn"), _read_dsn(out)


def _rotate(x: float, y: float, deg: float) -> tuple[float, float]:
    a = math.radians(deg)
    return x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)


def _pins(dsn: Node):
    """Each placed pin: (REF-PIN without its @n suffix, padstack, place transform)."""
    lib = find(dsn, "library")
    images = {str(i[1]): i for i in find_all(lib, "image")}  # type: ignore[arg-type]
    for comp in find_all(find(dsn, "placement"), "component"):  # type: ignore[arg-type]
        for pl in find_all(comp, "place"):
            ref, x, y, side, rot = str(pl[1]), float(pl[2]), float(pl[3]), str(pl[4]), float(pl[5])
            for pin in find_all(images[str(comp[1])], "pin"):
                r = find(pin, "rotate")
                name, px, py = [t for t in pin[2:] if not isinstance(t, list)]
                back = side == "back"
                pin_at = (float(px), float(py), float(r[1]) if r else 0.0)
                place = _placer(pin_at, (x, y, rot), back)
                yield f"{ref}-{str(name).split('@')[0]}", str(pin[1]), place, back


def _placer(pin_at, place_at, back):
    """Image-local um -> board um: the pin's rotation and offset, the side, the place."""
    px, py, prot = pin_at
    x, y, rot = place_at

    def place(u: float, v: float) -> tuple[float, float]:
        u, v = _rotate(u, v, prot)
        u, v = _rotate(-(px + u) if back else px + u, py + v, rot)
        return x + u, y + v

    return place


def _box(pts, grow):
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs) - grow, min(ys) - grow, max(xs) + grow, max(ys) + grow


def _union(a, b):
    return min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])


def _positions(dsn: Node) -> dict[str, list[tuple[float, float]]]:
    out: dict[str, list[tuple[float, float]]] = {}
    for name, _, place, _ in _pins(dsn):
        out.setdefault(name, []).append(place(0.0, 0.0))
    return {k: sorted(v) for k, v in out.items()}


def _copper(dsn: Node) -> dict[tuple[str, str], tuple[float, float, float, float]]:
    """(REF-PIN, layer) -> bounding box of the pin's copper on that layer, in um."""
    lib = find(dsn, "library")
    stacks = {str(p[1]): p for p in find_all(lib, "padstack")}  # type: ignore[arg-type]
    out: dict[tuple[str, str], tuple[float, float, float, float]] = {}
    for name, stack, place, back in _pins(dsn):
        for shape in find_all(stacks[stack], "shape"):
            kind, layer, *rest = shape[1]
            v = [float(t) for t in rest if not isinstance(t, list)]
            if back:
                layer = {"F.Cu": "B.Cu", "B.Cu": "F.Cu"}.get(layer, layer)
            if kind == "circle":
                pts, grow = [place(*(v[1:3] if len(v) >= 3 else (0.0, 0.0)))], v[0] / 2
            elif kind == "rect":
                pts, grow = [place(a, b) for a in (v[0], v[2]) for b in (v[1], v[3])], 0.0
            else:  # path, polygon: an aperture width, then points
                pts, grow = [place(v[i], v[i + 1]) for i in range(1, len(v) - 1, 2)], v[0] / 2
            box, key = _box(pts, grow), (name, str(layer))
            out[key] = _union(out[key], box) if key in out else box
    return out


def _nets(dsn: Node) -> dict[str, list[str]]:
    return {
        str(n[1]): sorted(str(t) for t in p[1:])
        for n in find_all(find(dsn, "network"), "net")  # type: ignore[arg-type]
        if (p := find(n, "pins")) is not None
    }


def test_every_pin_sits_where_kicad_puts_it(pair):
    board_id, kicad, ours = pair
    k, p = _positions(kicad), _positions(ours)
    assert set(p) - set(k) == HOLES_AS_PINS.get(board_id, set())
    assert set(k) <= set(p)

    def moved(n):
        return len(k[n]) != len(p[n]) or any(
            math.dist(a, b) > TOL for a, b in zip(k[n], p[n], strict=True)
        )

    assert not {n: (k[n], p[n]) for n in k if moved(n)}


def test_nets_join_the_pins_kicads_do(pair):
    _, kicad, ours = pair
    k, p = _nets(kicad), _nets(ours)
    # pkidl leaves out a net with one pin: there's nothing to route
    assert {n: v for n, v in k.items() if len(v) > 1} == p


def test_pads_put_copper_where_kicads_do(pair):
    board_id, kicad, ours = pair
    k, p = _copper(kicad), _copper(ours)
    holes = HOLES_AS_PINS.get(board_id, set())
    assert {key for key in set(p) - set(k) if key[0] not in holes} == set()
    assert set(k) <= set(p)

    def moved(key):
        return max(abs(a - b) for a, b in zip(k[key], p[key], strict=True)) > TOL

    assert not {key: (k[key], p[key]) for key in k if moved(key)}
